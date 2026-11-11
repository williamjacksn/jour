import calendar
import datetime as dt
import functools
import secrets
import typing
import urllib.parse
import uuid

import flask
import fort
import httpx
import waitress
import werkzeug

import jour.components
import jour.models
import jour.oidc

app = flask.Flask(__name__)
# Lax stops other sites from making the browser send our cookie on cross-site POSTs
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def _build_month(date: dt.date) -> str:
    start = date.replace(day=1)
    end = date.replace(day=calendar.monthrange(date.year, date.month)[1])
    dwj = jour.models.journals.list_dates_between(flask.g.user_db, start, end)
    return jour.components.month(date, dwj)


def _get_db() -> fort.SQLiteDatabase:
    return fort.SQLiteDatabase(str(jour.models.paths.app_db_path()))


def login_required(f: typing.Callable) -> typing.Callable:
    @functools.wraps(f)
    def decorated_function(*args, **kwargs) -> typing.Any:  # noqa: ANN002, ANN003, ANN401
        app.logger.debug(f"Logged in user: {flask.g.email}")
        if flask.g.email is None:
            return jour.components.landing()
        user = jour.models.users.get_by_email(flask.g.db, flask.g.email)
        if user is None:
            if not jour.models.access.signup_allowed(flask.g.settings, flask.g.email):
                return jour.components.not_invited(), 403
            user = jour.models.users.get_or_create(flask.g.db, flask.g.email)
        # The administrator can never be locked out by the disabled flag
        if user["is_disabled"] and not flask.g.is_admin:
            return jour.components.account_disabled(), 403
        flask.g.user = user
        # Every user gets a journal database of their own
        flask.g.user_db = jour.models.userdb.open_db(user["user_id"])
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f: typing.Callable) -> typing.Callable:
    @login_required
    @functools.wraps(f)
    def decorated_function(*args, **kwargs) -> typing.Any:  # noqa: ANN002, ANN003, ANN401
        if not flask.g.is_admin:
            return jour.components.forbidden(), 403
        return f(*args, **kwargs)

    return decorated_function


@app.before_request
def before_request() -> None:
    app.logger.debug(f"{flask.request.method} {flask.request.path}")
    if flask.request.method == "POST":
        # Field names only: values can be journal text or secrets
        app.logger.debug(f"Form fields: {list(flask.request.values.keys())}")

    flask.session.permanent = True
    flask.g.db = _get_db()
    flask.g.settings = jour.models.settings.Settings(flask.g.db)
    flask.g.email = flask.session.get("email")
    flask.g.is_admin = jour.models.access.is_admin(
        flask.g.settings.admin_email, flask.g.email
    )
    flask.g.user_db = None


@app.teardown_request
def teardown_request(_exc: BaseException | None) -> None:
    for name in ("user_db", "db"):
        db = flask.g.get(name)
        if db is not None:
            db.cnx.close()


@app.get("/")
@login_required
def index() -> werkzeug.Response:
    d = dt.datetime.now(tz=dt.UTC).astimezone().date()
    return flask.redirect(jour.components.build_url("month", d))


@app.get("/<year>/<month_>")
@login_required
def month(year: str, month_: str) -> str:
    date = dt.date(int(year), int(month_), 1)
    return _build_month(date)


@app.get("/<year>/<month_>/<day_>")
@login_required
def day(year: str, month_: str, day_: str, edit: bool = False) -> str:
    date = dt.date(int(year), int(month_), int(day_))
    j = jour.models.journals.get_for_date(flask.g.user_db, date)
    if j:
        entry_text = j["journal_data"]
    else:
        entry_text = ""
    if edit:
        return jour.components.day_edit(date, entry_text)
    else:
        return jour.components.day(date, entry_text)


@app.post("/<year>/<month_>/<day_>/delete")
@login_required
def day_delete(year: str, month_: str, day_: str) -> werkzeug.Response:
    d = dt.date(int(year), int(month_), int(day_))
    existing = jour.models.journals.get_for_date(flask.g.user_db, d)
    if existing:
        jour.models.journals.delete(flask.g.user_db, d)
    return flask.redirect(jour.components.build_url("month", d))


@app.get("/<year>/<month_>/<day_>/edit")
@login_required
def day_edit(year: str, month_: str, day_: str) -> str:
    return day(year, month_, day_, edit=True)


@app.post("/<year>/<month_>/<day_>/update")
@login_required
def day_update(year: str, month_: str, day_: str) -> werkzeug.Response:
    d = dt.date(int(year), int(month_), int(day_))
    description = flask.request.values.get("entry-text")
    existing = jour.models.journals.get_for_date(flask.g.user_db, d)
    if existing:
        params = {
            "journal_id": existing["journal_id"],
            "journal_date": d,
            "journal_data": description,
        }
    else:
        params = {
            "journal_id": uuid.uuid4(),
            "journal_date": d,
            "journal_data": description,
        }
    jour.models.journals.upsert(flask.g.user_db, params)
    return flask.redirect(jour.components.build_url("day", d))


@app.get("/admin")
@admin_required
def admin() -> werkzeug.Response:
    return flask.redirect(flask.url_for("admin_users"))


@app.get("/admin/users")
@admin_required
def admin_users() -> str:
    admin_email = flask.g.settings.admin_email
    rows = []
    for u in jour.models.users.list_all(flask.g.db):
        entries, size = jour.models.userdb.stats(u["user_id"])
        rows.append(
            {
                **u,
                "entries": entries,
                "size": size,
                "is_admin": jour.models.access.is_admin(admin_email, u["email"]),
            }
        )
    return jour.components.admin_users(rows)


def _target_user(user_id: str) -> dict:
    """Look up the user an admin action applies to; the admin cannot target self."""
    user = jour.models.users.get_by_id(flask.g.db, user_id)
    if user is None:
        flask.abort(404)
    if jour.models.access.is_admin(flask.g.settings.admin_email, user["email"]):
        flask.abort(400)
    return user


@app.post("/admin/users/<user_id>/disable")
@admin_required
def admin_user_disable(user_id: str) -> werkzeug.Response:
    user = _target_user(user_id)
    jour.models.users.set_disabled(flask.g.db, user["user_id"], disabled=True)
    return flask.redirect(flask.url_for("admin_users"))


@app.post("/admin/users/<user_id>/enable")
@admin_required
def admin_user_enable(user_id: str) -> werkzeug.Response:
    user = _target_user(user_id)
    jour.models.users.set_disabled(flask.g.db, user["user_id"], disabled=False)
    return flask.redirect(flask.url_for("admin_users"))


@app.post("/admin/users/<user_id>/delete")
@admin_required
def admin_user_delete(user_id: str) -> werkzeug.Response:
    user = _target_user(user_id)
    jour.models.userdb.delete_files(user["user_id"])
    jour.models.users.delete(flask.g.db, user["user_id"])
    return flask.redirect(flask.url_for("admin_users"))


SETTINGS_FIELDS = (
    "admin_email",
    "openid_client_id",
    "openid_discovery_document",
    "scheme",
    "signup_allowlist",
    "signup_policy",
)


def _validate_settings(
    form: typing.Mapping[str, str],
) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    values = {name: form.get(name, "").strip() for name in SETTINGS_FIELDS}
    values["admin_email"] = jour.models.users.normalize_email(values["admin_email"])
    if "@" not in values["admin_email"] or " " in values["admin_email"]:
        errors.append("Admin email must be an email address.")
    if not values["openid_client_id"]:
        errors.append("Client ID is required.")
    discovery = urllib.parse.urlparse(values["openid_discovery_document"])
    if discovery.scheme not in ("http", "https") or not discovery.netloc:
        errors.append("Discovery document must be an http or https URL.")
    if values["scheme"] not in ("http", "https"):
        errors.append("Redirect URI scheme must be http or https.")
    if values["signup_policy"] not in jour.models.access.POLICIES:
        errors.append("Choose who can create an account.")
    # Store the allowlist tidy: one normalized entry per line
    entries = jour.models.access.parse_allowlist(values["signup_allowlist"])
    values["signup_allowlist"] = "\n".join(sorted(entries))
    return values, errors


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings() -> str | tuple[str, int] | werkzeug.Response:
    s = flask.g.settings
    if flask.request.method == "POST":
        values, errors = _validate_settings(flask.request.form)
        if errors:
            return (
                jour.components.admin_settings(
                    values, errors, secret_is_set=bool(s.openid_client_secret)
                ),
                400,
            )
        for name, value in values.items():
            s.set_by_name(name, value)
        secret = flask.request.form.get("openid_client_secret", "").strip()
        if secret:
            s.openid_client_secret = secret
        return flask.redirect(flask.url_for("admin_settings", saved=1))
    values = {name: s.get_by_name(name) for name in SETTINGS_FIELDS}
    return jour.components.admin_settings(
        values,
        [],
        saved=flask.request.args.get("saved") == "1",
        secret_is_set=bool(s.openid_client_secret),
    )


@app.get("/authorize")
def authorize() -> werkzeug.Response:
    # Both are single use: pop them so a replayed callback cannot succeed
    state = flask.session.pop("state", None)
    nonce = flask.session.pop("nonce", None)
    if not state or state != flask.request.values.get("state"):
        return flask.Response("State mismatch", 401)
    discovery_document = httpx.get(flask.g.settings.openid_discovery_document).json()
    token_endpoint = discovery_document.get("token_endpoint")
    data = {
        "code": flask.request.values.get("code"),
        "client_id": flask.g.settings.openid_client_id,
        "client_secret": flask.g.settings.openid_client_secret,
        "redirect_uri": flask.url_for(
            "authorize", _external=True, _scheme=flask.g.settings.scheme
        ),
        "grant_type": "authorization_code",
    }
    response = httpx.post(token_endpoint, data=data)
    if response.is_error:
        # The error body describes the problem and contains no secrets
        app.logger.warning(
            f"Token request failed: {response.status_code} {response.text}"
        )
    response.raise_for_status()
    response_data = response.json()
    id_token = response_data.get("id_token")
    try:
        claim = jour.oidc.verify_id_token(
            id_token or "",
            discovery_document=discovery_document,
            client_id=flask.g.settings.openid_client_id,
            nonce=nonce or "",
        )
    except jour.oidc.InvalidIdTokenError as e:
        app.logger.warning(f"Rejected ID token: {e}")
        return flask.Response("Could not verify your sign-in", 401)
    email = claim.get("email")
    if not email or claim.get("email_verified") is False:
        return flask.Response("A verified email address is required", 403)
    flask.session["email"] = jour.models.users.normalize_email(email)
    jour.models.users.record_sign_in(flask.g.db, email)
    return flask.redirect(flask.url_for("index"))


@app.post("/go")
def go() -> werkzeug.Response:
    year = flask.request.values["year"]
    month_ = flask.request.values["month"]
    d = dt.date(int(year), int(month_), 1)
    response = flask.make_response()
    response.headers["HX-Location"] = jour.components.build_url("month", d)
    return response


@app.get("/favicon.svg")
def favicon() -> flask.Response:
    return flask.Response(jour.components.favicon(), mimetype="image/svg+xml")


# @app.route("/knock", methods=["GET", "POST"])
# def knock():
#     if flask.request.method == "GET":
#         return jour.components.knock()
#     pw = flask.request.values.get("pw")
#     if pw == flask.g.settings.openid_client_id:
#         flask.session["email"] = flask.g.settings.admin_email
#         return flask.redirect(flask.url_for("index"))
#     return flask.redirect(flask.url_for("knock"))


@app.post("/search")
@login_required
def search() -> str:
    q = flask.request.values.get("q")
    if q:
        page = int(flask.request.values.get("page", 1))
        results = jour.models.journals.search(flask.g.user_db, q, page)
        return jour.components.search(results, page)
    return ""


@app.post("/sign-out")
def sign_out() -> werkzeug.Response:
    flask.session.clear()
    return flask.redirect(flask.url_for("index"))


@app.get("/sign-in")
def sign_in() -> werkzeug.Response:
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    flask.session["state"] = state
    flask.session["nonce"] = nonce
    redirect_uri = flask.url_for(
        "authorize", _external=True, _scheme=flask.g.settings.scheme
    )
    query = {
        "client_id": flask.g.settings.openid_client_id,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": redirect_uri,
        "state": state,
        "nonce": nonce,
    }
    discovery_document = httpx.get(flask.g.settings.openid_discovery_document).json()
    auth_endpoint = discovery_document.get("authorization_endpoint")
    auth_url = f"{auth_endpoint}?{urllib.parse.urlencode(query)}"
    app.logger.debug(f"Redirecting to {auth_url=}")
    return flask.redirect(auth_url, 307)


def main() -> None:
    db = _get_db()
    jour.models.init(db)
    app.secret_key = jour.models.settings.Settings(db).secret_key
    waitress.serve(app)
