import signal
import sys

import notch

import jour.app

notch.configure()


def handle_sigterm(_signal, _frame):
    sys.exit()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)
    jour.app.main()
