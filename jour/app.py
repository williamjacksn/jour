import caldav
import calendar
import datetime
import flask
import fort
import functools
import icalendar
import jour.filters
import jour.models
import jwt
import pathlib
import requests
import urllib.parse
import uuid
import waitress
import whitenoise

app = flask.Flask(__name__)


def _build_month(date: datetime.date):
    flask.g.start = date.replace(day=1)
    flask.g.end = date.replace(day=calendar.monthrange(date.year, date.month)[1])
    flask.g.dates_with_journals = jour.models.journals.list_dates_between(flask.g.db, flask.g.start, flask.g.end)
    flask.g.today = datetime.date.today()
    flask.g.month_name = calendar.month_name[flask.g.start.month]
    flask.g.cal = calendar.Calendar(firstweekday=calendar.SUNDAY)
    flask.g.day_names = (calendar.day_name[i][0:2] for i in flask.g.cal.iterweekdays())
    flask.g.prev_month = flask.g.start - datetime.timedelta(days=1)
    flask.g.next_month = flask.g.start + datetime.timedelta(days=31)
    return flask.render_template('month.html')


def _build_url(endpoint: str, d: datetime.date):
    year = d.year
    month_ = d.strftime('%m')
    day_ = d.strftime('%d')
    if endpoint in ['month']:
        return flask.url_for(endpoint, year=year, month_=month_)
    if endpoint in ['day', 'day_delete', 'day_edit', 'day_update']:
        return flask.url_for(endpoint, year=year, month_=month_, day_=day_)


def _get_caldav_client():
    caldav_url = flask.g.settings.caldav_url
    caldav_username = flask.g.settings.caldav_username
    caldav_password = flask.g.settings.caldav_password
    return caldav.DAVClient(url=caldav_url, username=caldav_username, password=caldav_password)


def _get_caldav_collection():
    client = _get_caldav_client()
    return client.calendar(url=flask.g.settings.caldav_collection_url)


def _get_db() -> fort.SQLiteDatabase:
    db_path = pathlib.Path().resolve() / '.local/jour.db'
    return fort.SQLiteDatabase(db_path)


def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        app.logger.debug(f'Logged in user: {flask.g.email}')
        if flask.g.email is None:
            return flask.redirect(flask.url_for('sign_in'))
        if flask.g.email == flask.g.settings.user_email:
            return f(*args, **kwargs)
        return flask.render_template('not-authorized.html')
    return decorated_function


@app.before_request
def before_request():
    app.logger.debug(f'{flask.request.method} {flask.request.path}')
    if flask.request.method == 'POST':
        for k, v in flask.request.values.lists():
            app.logger.debug(f'{k}: {v}')

    flask.session.permanent = True
    flask.g.db = _get_db()
    flask.g.settings = jour.models.settings.Settings(flask.g.db)
    flask.g.email = flask.session.get('email')


@app.get('/')
@login_required
def index():
    d = datetime.date.today()
    return flask.redirect(_build_url('month', d))


@app.get('/<year>/<month_>')
@login_required
def month(year, month_):
    date = datetime.date(int(year), int(month_), 1)
    return _build_month(date)


@app.get('/<year>/<month_>/<day_>')
@login_required
def day(year, month_, day_, edit=False):
    flask.g.date = datetime.date(int(year), int(month_), int(day_))
    j = jour.models.journals.get_for_date(flask.g.db, flask.g.date)
    if j:
        flask.g.entry_text = j['journal_data']
    else:
        flask.g.entry_text = ''
    if edit:
        return flask.render_template('day-edit.html')
    else:
        return flask.render_template('day.html')


@app.post('/<year>/<month_>/<day_>/delete')
@login_required
def day_delete(year, month_, day_):
    collection = _get_caldav_collection()
    d = datetime.date(int(year), int(month_), int(day_))
    existing = jour.models.journals.get_for_date(flask.g.db, d)
    if existing:
        uid = str(existing['journal_id'])
        server_journal = collection.journal_by_uid(uid)
        server_journal.delete()
        jour.models.journals.delete(flask.g.db, d)
    return flask.redirect(_build_url('month', d))


@app.get('/<year>/<month_>/<day_>/edit')
@login_required
def day_edit(year, month_, day_):
    return day(year, month_, day_, edit=True)


@app.post('/<year>/<month_>/<day_>/update')
@login_required
def day_update(year, month_, day_):
    collection = _get_caldav_collection()
    d = datetime.date(int(year), int(month_), int(day_))
    description = flask.request.values.get('entry-text')
    existing = jour.models.journals.get_for_date(flask.g.db, d)
    if existing:
        local_journal = icalendar.Calendar.from_ical(existing['journal_data'])
        local_journal.subcomponents[0]['description'] = description
        collection.save_journal(ical=local_journal.to_ical())
        params = {
            'journal_id': existing['journal_id'],
            'journal_date': d,
            'journal_data': description,
        }
        jour.models.journals.upsert(flask.g.db, params)
    else:
        summary = f'Journal entry for {d}'
        server_journal = collection.save_journal(dtstart=d, summary=summary, description=description)
        params = {
            'journal_id': uuid.UUID(server_journal.id),
            'journal_date': d,
            'journal_data': description,
        }
        jour.models.journals.upsert(flask.g.db, params)
    return flask.redirect(_build_url('day', d))


@app.get('/authorize')
def authorize():
    if flask.session.get('state') != flask.request.values.get('state'):
        return 'State mismatch', 401
    discovery_document = requests.get(flask.g.settings.openid_discovery_document).json()
    token_endpoint = discovery_document.get('token_endpoint')
    data = {
        'code': flask.request.values.get('code'),
        'client_id': flask.g.settings.openid_client_id,
        'client_secret': flask.g.settings.openid_client_secret,
        'redirect_uri': flask.url_for('authorize', _external=True, _scheme=flask.g.settings.scheme),
        'grant_type': 'authorization_code'
    }
    app.logger.debug(f'{data=}')
    response = requests.post(token_endpoint, data=data)
    app.logger.debug(f'{response.content=}')
    response.raise_for_status()
    response_data = response.json()
    app.logger.debug(f'{response_data=}')
    id_token = response_data.get('id_token')
    app.logger.debug(f'{id_token=}')
    algorithms = discovery_document.get('id_token_signing_alg_values_supported')
    claim = jwt.decode(id_token, options={'verify_signature': False}, algorithms=algorithms)
    flask.session['email'] = claim.get('email')
    return flask.redirect(flask.url_for('index'))


@app.get('/caldav')
@login_required
def caldav_():
    flask.g.collection = _get_caldav_collection()
    return flask.render_template('caldav.html')


@app.get('/caldav/sync')
@login_required
def caldav_sync():
    flask.g.collection = _get_caldav_collection()
    for j in flask.g.collection.journals():
        comp = j.icalendar_component
        params = {
            'journal_id': uuid.UUID(comp['uid']),
            'journal_date': comp['dtstart'].dt,
            'journal_data': j.icalendar_component['description'],
        }
        jour.models.journals.upsert(flask.g.db, params)
    return flask.redirect(flask.url_for('caldav_'))


@app.post('/configure/collection')
@login_required
def configure_collection():
    flask.g.settings.caldav_collection_url = flask.request.values.get('caldav-collection-url')
    return flask.redirect(flask.url_for('index'))


@app.post('/configure/credentials')
@login_required
def configure_credentials():
    flask.g.settings.caldav_url = flask.request.values.get('caldav-url')
    flask.g.settings.caldav_username = flask.request.values.get('caldav-username')
    flask.g.settings.caldav_password = flask.request.values.get('caldav-password')
    return flask.redirect(flask.url_for('index'))


@app.post('/search')
@login_required
def search():
    q = flask.request.values.get('q')
    if q:
        flask.g.page = int(flask.request.values.get('page', 1))
        flask.g.results = jour.models.journals.search(flask.g.db, q, flask.g.page)
        return flask.render_template('search.html')
    return ''


@app.get('/sign-in')
def sign_in():
    state = str(uuid.uuid4())
    flask.session['state'] = state
    redirect_uri = flask.url_for('authorize', _external=True, _scheme=flask.g.settings.scheme)
    query = {
        'client_id': flask.g.settings.openid_client_id,
        'response_type': 'code',
        'scope': 'openid email profile',
        'redirect_uri': redirect_uri,
        'state': state
    }
    discovery_document = requests.get(flask.g.settings.openid_discovery_document).json()
    auth_endpoint = discovery_document.get('authorization_endpoint')
    auth_url = f'{auth_endpoint}?{urllib.parse.urlencode(query)}'
    app.logger.debug(f'Redirecting to {auth_url=}')
    return flask.redirect(auth_url, 307)


def main():
    db = _get_db()
    jour.models.init(db)
    static = pathlib.Path(__file__).resolve().with_name('static')
    app.wsgi_app = whitenoise.WhiteNoise(app.wsgi_app, root=static, prefix='static/')
    app.secret_key = jour.models.settings.Settings(db).secret_key
    app.add_template_filter(jour.filters.md)
    app.add_template_global(_build_url, 'build_url')
    waitress.serve(app)
