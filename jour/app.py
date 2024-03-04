import flask
import fort
import jour.db
import pathlib
import waitress

app = flask.Flask(__name__)

db_path = pathlib.Path().resolve() / '.local/jour.db'


@app.before_request
def before_request():
    flask.g.db = fort.SQLiteDatabase(db_path)


@app.get('/')
def index():
    flask.g.caldav_url = jour.db.settings.get_str(flask.g.db, 'caldav/url')
    flask.g.caldav_username = jour.db.settings.get_str(flask.g.db, 'caldav/username')
    flask.g.caldav_password = jour.db.settings.get_enc(flask.g.db, 'caldav/password')
    if flask.g.caldav_url and flask.g.caldav_username and flask.g.caldav_password:
        return 'ok'
    return flask.render_template('configure.html')


def main():
    db = fort.SQLiteDatabase(db_path)
    jour.db.init(db)
    app.secret_key = jour.db.settings.secret_key(db)
    waitress.serve(app)
