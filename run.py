import signal
import sys
import types

import notch

import jour.app

notch.configure()


def handle_sigterm(_signal: int, _frame: types.FrameType | None) -> None:
    sys.exit()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)
    jour.app.main()
