import caldav
import calendar
import datetime
import flask
import fort
import icalendar
import jour.filters
import jour.models
import pathlib
import uuid
import waitress

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


def _get_caldav_client(db: 'fort.SQLiteDatabase'):
    caldav_url = jour.models.settings.get_str(db, 'caldav/url')
    caldav_username = jour.models.settings.get_str(db, 'caldav/username')
    caldav_password = jour.models.settings.get_enc(db, 'caldav/password')
    caldav_client = caldav.DAVClient(url=caldav_url, username=caldav_username, password=caldav_password)
    return caldav_client


def _get_caldav_collection(db: 'fort.SQLiteDatabase'):
    client = _get_caldav_client(db)
    caldav_collection_url = jour.models.settings.get_str(db, 'caldav/collection-url')
    collection = client.calendar(url=caldav_collection_url)
    return collection


def _get_db() -> fort.SQLiteDatabase:
    db_path = pathlib.Path().resolve() / '.local/jour.db'
    return fort.SQLiteDatabase(db_path)


@app.before_request
def before_request():
    flask.g.db = _get_db()
    app.logger.debug(f'{flask.request.method} {flask.request.path}')
    if flask.request.method == 'POST':
        for k, v in flask.request.values.lists():
            app.logger.debug(f'{k}: {v}')


@app.get('/')
def index():
    d = datetime.date.today()
    return flask.redirect(_build_url('month', d))


@app.get('/<year>/<month_>')
def month(year, month_):
    date = datetime.date(int(year), int(month_), 1)
    return _build_month(date)


@app.get('/<year>/<month_>/<day_>')
def day(year, month_, day_, edit=False):
    flask.g.date = datetime.date(int(year), int(month_), int(day_))
    j = jour.models.journals.get_for_date(flask.g.db, flask.g.date)
    if j:
        parsed = icalendar.Calendar.from_ical(j['journal_data'])
        flask.g.entry_text = parsed.subcomponents[0]['description']
    else:
        flask.g.entry_text = ''
    if edit:
        return flask.render_template('day-edit.html')
    else:
        return flask.render_template('day.html')


@app.post('/<year>/<month_>/<day_>/delete')
def day_delete(year, month_, day_):
    collection = _get_caldav_collection(flask.g.db)
    d = datetime.date(int(year), int(month_), int(day_))
    existing = jour.models.journals.get_for_date(flask.g.db, d)
    if existing:
        uid = str(existing['journal_id'])
        server_journal = collection.journal_by_uid(uid)
        server_journal.delete()
        jour.models.journals.delete(flask.g.db, d)
    return flask.redirect(_build_url('month', d))


@app.get('/<year>/<month_>/<day_>/edit')
def day_edit(year, month_, day_):
    return day(year, month_, day_, edit=True)


@app.post('/<year>/<month_>/<day_>/update')
def day_update(year, month_, day_):
    collection = _get_caldav_collection(flask.g.db)
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
            'journal_data': local_journal.to_ical(),
        }
        jour.models.journals.upsert(flask.g.db, params)
    else:
        summary = f'Journal entry for {d}'
        server_journal = collection.save_journal(dtstart=d, summary=summary, description=description)
        params = {
            'journal_id': uuid.UUID(server_journal.id),
            'journal_date': d,
            'journal_data': server_journal.icalendar_instance.to_ical(),
        }
        jour.models.journals.upsert(flask.g.db, params)
    return flask.redirect(_build_url('day', d))


@app.get('/caldav')
def caldav_():
    flask.g.collection = _get_caldav_collection(flask.g.db)
    return flask.render_template('caldav.html')


@app.get('/caldav/sync')
def caldav_sync():
    flask.g.collection = _get_caldav_collection(flask.g.db)
    for j in flask.g.collection.journals():
        comp = j.icalendar_instance.subcomponents[0]
        params = {
            'journal_id': uuid.UUID(comp['uid']),
            'journal_date': comp['dtstart'].dt,
            'journal_data': j.icalendar_instance.to_ical(),
        }
        jour.models.journals.upsert(flask.g.db, params)
    return flask.redirect(flask.url_for('caldav_'))


@app.post('/configure/collection')
def configure_collection():
    jour.models.settings.set_str(flask.g.db, 'caldav/collection-url', flask.request.values.get('caldav-collection-url'))
    return flask.redirect(flask.url_for('index'))


@app.post('/configure/credentials')
def configure_credentials():
    jour.models.settings.set_str(flask.g.db, 'caldav/url', flask.request.values.get('caldav-url'))
    jour.models.settings.set_str(flask.g.db, 'caldav/username', flask.request.values.get('caldav-username'))
    jour.models.settings.set_enc(flask.g.db, 'caldav/password', flask.request.values.get('caldav-password'))
    return flask.redirect(flask.url_for('index'))


def main():
    db = _get_db()
    jour.models.init(db)
    app.secret_key = jour.models.settings.secret_key(db)
    app.add_template_filter(jour.filters.md)
    app.add_template_global(_build_url, 'build_url')
    waitress.serve(app)
