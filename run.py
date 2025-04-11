import jour.app
import notch
import signal
import sys

log = notch.make_log("jour.entrypoint")


def handle_sigterm(_signal, _frame):
    sys.exit()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)
    jour.app.main()
