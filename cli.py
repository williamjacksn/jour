import argparse
from collections.abc import Callable

import jour.app
import jour.models


class Args:
    func: Callable
    key: str
    value: str


def parse_args() -> Args:
    parser = argparse.ArgumentParser()
    sp = parser.add_subparsers()
    sp.required = True

    ps_init = sp.add_parser("init")
    ps_init.set_defaults(func=cli_init)

    ps_set = sp.add_parser("set")
    ps_set.add_argument("key")
    ps_set.add_argument("value")
    ps_set.set_defaults(func=cli_set)

    ps_show = sp.add_parser("show")
    ps_show.set_defaults(func=cli_show)

    return parser.parse_args(namespace=Args())


def cli_init(args: Args) -> None:
    db = jour.app._get_db()
    jour.models.init(db)


def cli_set(args: Args) -> None:
    db = jour.app._get_db()
    settings = jour.models.settings.Settings(db)
    if args.key == "openid_client_secret":
        print(f"Setting openid_client_secret to {args.value}")
        settings.openid_client_secret = args.value


def cli_show(args: Args) -> None:
    db = jour.app._get_db()
    settings = jour.models.settings.Settings(db)
    print("openid_client_id:", settings.openid_client_id)
    print("openid_client_secret:", settings.openid_client_secret)
    print("openid_discovery_document:", settings.openid_discovery_document)
    print("scheme:", settings.scheme)


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
