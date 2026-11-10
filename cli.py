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
    ps_set.add_argument(
        "key",
        choices=list(jour.models.settings.REGISTRY),
        help="; ".join(
            f"{d.name}: {d.description}" for d in jour.models.settings.REGISTRY.values()
        ),
    )
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
    definition = jour.models.settings.REGISTRY[args.key]
    if definition.encrypted:
        print(f"Setting {args.key}")
    else:
        print(f"Setting {args.key} to {args.value}")
    settings.set_by_name(args.key, args.value)


def cli_show(args: Args) -> None:
    db = jour.app._get_db()
    settings = jour.models.settings.Settings(db)
    for name, definition in jour.models.settings.REGISTRY.items():
        value = settings.get_by_name(name)
        if definition.encrypted:
            value = "(set)" if value else "(not set)"
        print(f"{name}:", value)


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
