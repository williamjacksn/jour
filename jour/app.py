import caldav
import calendar
import datetime
import flask
import fort
import jour.filters
import jour.models
import pathlib
import uuid
import waitress

app = flask.Flask(__name__)

def _get_db() -> fort.SQLiteDatabase:
    db_path = pathlib.Path().resolve() / '.local/jour.db'
    return fort.SQLiteDatabase(db_path)


@app.before_request
def before_request():
    flask.g.db = _get_db()
    if flask.request.method == 'POST':
        for k, v in flask.request.values.lists():
            app.logger.debug(f'{k}: {v}')


@app.get('/')
def index():
    flask.g.caldav_url = jour.models.settings.get_str(flask.g.db, 'caldav/url')
    flask.g.caldav_username = jour.models.settings.get_str(flask.g.db, 'caldav/username')
    flask.g.caldav_password = jour.models.settings.get_enc(flask.g.db, 'caldav/password')
    if flask.g.caldav_url and flask.g.caldav_username and flask.g.caldav_password:
        flask.g.caldav_client = caldav.DAVClient(url=flask.g.caldav_url, username=flask.g.caldav_username, password=flask.g.caldav_password)
        flask.g.caldav_principal = flask.g.caldav_client.principal()
        flask.g.caldav_collection_url = jour.models.settings.get_str(flask.g.db, 'caldav/collection-url')
        if flask.g.caldav_collection_url:
            flask.g.collection = flask.g.caldav_client.calendar(url=flask.g.caldav_collection_url)
            for j in flask.g.collection.journals():
                comp = j.icalendar_instance.subcomponents[0]
                params = {
                    'journal_id': uuid.UUID(comp['uid']),
                    'journal_date': comp['dtstart'].dt,
                    'journal_data': j.icalendar_instance.to_ical(),
                }
                jour.models.journals.upsert(flask.g.db, params)
            flask.g.cal = calendar.Calendar(firstweekday=calendar.SUNDAY)
            flask.g.day_names = (calendar.day_name[i] for i in flask.g.cal.iterweekdays())
            flask.g.today = datetime.date.today()
            flask.g.month_name = calendar.month_name[flask.g.today.month]
            return flask.render_template('index.html')
        return flask.render_template('select-collection.html')
    return flask.render_template('configure.html')


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


@app.post('/new')
def new():
    url = jour.models.settings.get_str(flask.g.db, 'caldav/url')
    username = jour.models.settings.get_str(flask.g.db, 'caldav/username')
    password = jour.models.settings.get_enc(flask.g.db, 'caldav/password')
    client = caldav.DAVClient(url=url, username=username, password=password)
    collection_url = jour.models.settings.get_str(flask.g.db, 'caldav/collection-url')
    collection = client.calendar(url=collection_url)
    dtstart = datetime.datetime.strptime(flask.request.values.get('entry-date'), '%Y-%m-%d').date()
    collection.save_journal(dtstart=dtstart, summary=f'Journal entry for {dtstart}', description=flask.request.values.get('entry-text'))
    return flask.redirect(flask.url_for('index'))


def main():
    db = _get_db()
    jour.models.init(db)
    app.secret_key = jour.models.settings.secret_key(db)
    app.add_template_filter(jour.filters.md)
    waitress.serve(app)
