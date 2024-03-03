import flask
import waitress

app = flask.Flask(__name__)


@app.get('/')
def index():
    return 'ok'


def main():
    waitress.serve(app)
