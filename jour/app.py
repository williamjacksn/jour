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


def _build_monthly_calendar(date: datetime.date):
    flask.g.start = date.replace(day=1)
    flask.g.end = date.replace(day=calendar.monthrange(date.year, date.month)[1])
    flask.g.dates_with_journals = jour.models.journals.list_dates_between(flask.g.db, flask.g.start, flask.g.end)
    flask.g.today = datetime.date.today()
    flask.g.month_name = calendar.month_name[flask.g.start.month]
    flask.g.cal = calendar.Calendar(firstweekday=calendar.SUNDAY)
    flask.g.day_names = (calendar.day_name[i][0:2] for i in flask.g.cal.iterweekdays())
    flask.g.prev_month = flask.g.start - datetime.timedelta(days=1)
    flask.g.next_month = flask.g.start + datetime.timedelta(days=31)
    return flask.render_template('monthly-calendar.html')


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
    flask.g.today = datetime.date.today()
    return flask.render_template('index.html')


@app.get('/caldav')
def caldav_():
    flask.g.collection = _get_caldav_collection(flask.g.db)
    return flask.render_template('caldav.html')


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


@app.post('/journal')
def journal():
    flask.g.date = datetime.date.fromisoformat(flask.request.values.get('date'))
    j = jour.models.journals.get_for_date(flask.g.db, flask.g.date)
    if j:
        parsed = icalendar.Calendar.from_ical(j['journal_data'])
        flask.g.entry_text = parsed.subcomponents[0]['description']
    else:
        flask.g.entry_text = ''
    return flask.render_template('journal.html')


@app.post('/journal/delete')
def journal_delete():
    collection = _get_caldav_collection(flask.g.db)
    date = datetime.date.fromisoformat(flask.request.values.get('entry-date'))
    existing = jour.models.journals.get_for_date(flask.g.db, date)
    if existing:
        uid = str(existing['journal_id'])
        server_journal = collection.journal_by_uid(uid)
        server_journal.delete()
        jour.models.journals.delete(flask.g.db, date)
    return _build_monthly_calendar(date)


@app.post('/journal/save')
def journal_save():
    collection = _get_caldav_collection(flask.g.db)
    date = datetime.date.fromisoformat(flask.request.values.get('entry-date'))
    description = flask.request.values.get('entry-text')
    existing = jour.models.journals.get_for_date(flask.g.db, date)
    if existing:
        local_journal = icalendar.Calendar.from_ical(existing['journal_data'])
        local_journal.subcomponents[0]['description'] = description
        collection.save_journal(ical=local_journal.to_ical())
        params = {
            'journal_id': existing['journal_id'],
            'journal_date': date,
            'journal_data': local_journal.to_ical(),
        }
        jour.models.journals.upsert(flask.g.db, params)
    else:
        server_journal = collection.save_journal(dtstart=date, summary=f'Journal entry for {date}',
                                                 description=description)
        params = {
            'journal_id': uuid.UUID(server_journal.id),
            'journal_date': date,
            'journal_data': server_journal.icalendar_instance.to_ical()
        }
        jour.models.journals.upsert(flask.g.db, params)
    return _build_monthly_calendar(date)


@app.post('/monthly/calendar')
def monthly_calendar():
    requested_date = datetime.date.fromisoformat(flask.request.values.get('date'))
    return _build_monthly_calendar(requested_date)


@app.get('/sync')
def sync():
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


def main():
    db = _get_db()
    jour.models.init(db)
    app.secret_key = jour.models.settings.secret_key(db)
    app.add_template_filter(jour.filters.md)
    waitress.serve(app)
