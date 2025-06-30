import calendar
import datetime
import functools
import pathlib
import urllib.parse
import uuid

import flask
import fort
import httpx
import jwt
import waitress
import whitenoise

import jour.components
import jour.models

app = flask.Flask(__name__)


def _build_month(date: datetime.date):
    start = date.replace(day=1)
    end = date.replace(day=calendar.monthrange(date.year, date.month)[1])
    dwj = jour.models.journals.list_dates_between(flask.g.db, start, end)
    return jour.components.month(date, dwj)


def _get_db() -> fort.SQLiteDatabase:
    db_path = pathlib.Path().resolve() / ".local/jour.db"
    return fort.SQLiteDatabase(db_path)


def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        app.logger.debug(f"Logged in user: {flask.g.email}")
        if flask.g.email is None:
            return flask.redirect(flask.url_for("sign_in"))
        if flask.g.email == flask.g.settings.user_email:
            return f(*args, **kwargs)
        return jour.components.not_authorized()

    return decorated_function


@app.before_request
def before_request():
    app.logger.debug(f"{flask.request.method} {flask.request.path}")
    if flask.request.method == "POST":
        for k, v in flask.request.values.lists():
            app.logger.debug(f"{k}: {v}")

    flask.session.permanent = True
    flask.g.db = _get_db()
    flask.g.settings = jour.models.settings.Settings(flask.g.db)
    flask.g.email = flask.session.get("email")


@app.get("/")
@login_required
def index():
    d = datetime.date.today()
    return flask.redirect(jour.components.build_url("month", d))


@app.get("/<year>/<month_>")
@login_required
def month(year, month_):
    date = datetime.date(int(year), int(month_), 1)
    return _build_month(date)


@app.get("/<year>/<month_>/<day_>")
@login_required
def day(year, month_, day_, edit=False):
    date = datetime.date(int(year), int(month_), int(day_))
    j = jour.models.journals.get_for_date(flask.g.db, date)
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
def day_delete(year, month_, day_):
    d = datetime.date(int(year), int(month_), int(day_))
    existing = jour.models.journals.get_for_date(flask.g.db, d)
    if existing:
        jour.models.journals.delete(flask.g.db, d)
    return flask.redirect(jour.components.build_url("month", d))


@app.get("/<year>/<month_>/<day_>/edit")
@login_required
def day_edit(year, month_, day_):
    return day(year, month_, day_, edit=True)


@app.post("/<year>/<month_>/<day_>/update")
@login_required
def day_update(year, month_, day_):
    d = datetime.date(int(year), int(month_), int(day_))
    description = flask.request.values.get("entry-text")
    existing = jour.models.journals.get_for_date(flask.g.db, d)
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
    jour.models.journals.upsert(flask.g.db, params)
    return flask.redirect(jour.components.build_url("day", d))


@app.get("/authorize")
def authorize():
    if flask.session.get("state") != flask.request.values.get("state"):
        return "State mismatch", 401
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
    app.logger.debug(f"{data=}")
    response = httpx.post(token_endpoint, data=data)
    app.logger.debug(f"{response.content=}")
    response.raise_for_status()
    response_data = response.json()
    app.logger.debug(f"{response_data=}")
    id_token = response_data.get("id_token")
    app.logger.debug(f"{id_token=}")
    algorithms = discovery_document.get("id_token_signing_alg_values_supported")
    claim = jwt.decode(
        id_token, options={"verify_signature": False}, algorithms=algorithms
    )
    flask.session["email"] = claim.get("email")
    return flask.redirect(flask.url_for("index"))


@app.get("/favicon.svg")
def favicon():
    return flask.Response(jour.components.favicon(), mimetype="image/svg+xml")


# @app.route("/knock", methods=["GET", "POST"])
# def knock():
#     if flask.request.method == "GET":
#         return jour.components.knock()
#     pw = flask.request.values.get("pw")
#     if pw == flask.g.settings.openid_client_id:
#         flask.session["email"] = flask.g.settings.user_email
#         return flask.redirect(flask.url_for("index"))
#     return flask.redirect(flask.url_for("knock"))


@app.post("/search")
@login_required
def search():
    q = flask.request.values.get("q")
    if q:
        page = int(flask.request.values.get("page", 1))
        results = jour.models.journals.search(flask.g.db, q, page)
        return jour.components.search(results, page)
    return ""


@app.get("/sign-in")
def sign_in():
    state = str(uuid.uuid4())
    flask.session["state"] = state
    redirect_uri = flask.url_for(
        "authorize", _external=True, _scheme=flask.g.settings.scheme
    )
    query = {
        "client_id": flask.g.settings.openid_client_id,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    discovery_document = httpx.get(flask.g.settings.openid_discovery_document).json()
    auth_endpoint = discovery_document.get("authorization_endpoint")
    auth_url = f"{auth_endpoint}?{urllib.parse.urlencode(query)}"
    app.logger.debug(f"Redirecting to {auth_url=}")
    return flask.redirect(auth_url, 307)


def main():
    db = _get_db()
    jour.models.init(db)
    static = pathlib.Path(__file__).resolve().with_name("static")
    app.wsgi_app = whitenoise.WhiteNoise(app.wsgi_app, root=static, prefix="static/")
    app.secret_key = jour.models.settings.Settings(db).secret_key
    waitress.serve(app)
