import argparse
import sys
from collections.abc import Callable

import jour.app
import jour.models


class Args:
    func: Callable
    key: str
    value: str
    provider_id: str
    name: str | None
    discovery_document: str | None
    client_id: str | None
    client_secret: str | None
    enabled: bool | None
    trust_email: bool | None


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

    ps_provider = sp.add_parser("provider", help="manage sign-in providers")
    sp_provider = ps_provider.add_subparsers()
    sp_provider.required = True

    ps_provider_list = sp_provider.add_parser("list")
    ps_provider_list.set_defaults(func=cli_provider_list)

    presets = ", ".join(jour.models.providers.PRESETS)
    ps_provider_set = sp_provider.add_parser(
        "set",
        help=f"create or update a provider; presets fill in defaults for: {presets}",
    )
    ps_provider_set.add_argument("provider_id")
    ps_provider_set.add_argument("--name")
    ps_provider_set.add_argument("--discovery-document")
    ps_provider_set.add_argument("--client-id")
    ps_provider_set.add_argument("--client-secret")
    ps_provider_set.add_argument("--enabled", action=argparse.BooleanOptionalAction)
    ps_provider_set.add_argument("--trust-email", action=argparse.BooleanOptionalAction)
    ps_provider_set.set_defaults(func=cli_provider_set)

    ps_provider_remove = sp_provider.add_parser("remove")
    ps_provider_remove.add_argument("provider_id")
    ps_provider_remove.set_defaults(func=cli_provider_remove)

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


def cli_provider_list(args: Args) -> None:
    db = jour.app._get_db()
    for p in jour.models.providers.list_all(db):
        print(f"{p['provider_id']}: {p['display_name']}")
        print(f"    enabled: {bool(p['is_enabled'])}")
        print(f"    trust_email: {bool(p['trust_email'])}")
        print(f"    discovery_document: {p['discovery_document']}")
        print(f"    client_id: {p['client_id']}")
        print(f"    client_secret: {'(set)' if p['client_secret'] else '(not set)'}")


def cli_provider_set(args: Args) -> None:
    db = jour.app._get_db()
    settings = jour.models.settings.Settings(db)
    existing = jour.models.providers.get(db, args.provider_id)
    preset = jour.models.providers.PRESETS.get(args.provider_id)

    def pick(given: str | None, key: str, preset_value: str = "") -> str:
        if given is not None:
            return given
        if existing:
            return existing[key]
        return preset_value

    name = pick(args.name, "display_name", preset.display_name if preset else "")
    discovery = pick(
        args.discovery_document,
        "discovery_document",
        preset.discovery_document if preset else "",
    )
    client_id = pick(args.client_id, "client_id")
    if args.enabled is not None:
        enabled = args.enabled
    else:
        enabled = bool(existing["is_enabled"]) if existing else True
    if args.trust_email is not None:
        trust_email = args.trust_email
    elif existing:
        trust_email = bool(existing["trust_email"])
    else:
        trust_email = preset.trust_email if preset else False
    has_secret = bool(args.client_secret or (existing and existing["client_secret"]))
    errors = jour.models.providers.validate(
        args.provider_id,
        display_name=name,
        discovery_document=discovery,
        client_id=client_id,
        has_secret=has_secret,
    )
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        sys.exit(1)
    jour.models.providers.save(
        db,
        settings,
        args.provider_id,
        display_name=name,
        discovery_document=discovery,
        client_id=client_id,
        secret=args.client_secret or None,
        is_enabled=enabled,
        trust_email=trust_email,
    )
    print(f"Saved provider {args.provider_id}")


def cli_provider_remove(args: Args) -> None:
    db = jour.app._get_db()
    if jour.models.providers.get(db, args.provider_id) is None:
        print(f"No such provider: {args.provider_id}", file=sys.stderr)
        sys.exit(1)
    linked = jour.models.identities.count_by_provider(db).get(args.provider_id, 0)
    if linked:
        print(
            f"{linked} user(s) sign in with {args.provider_id}; "
            "disable it instead (--no-enabled).",
            file=sys.stderr,
        )
        sys.exit(1)
    jour.models.providers.delete(db, args.provider_id)
    print(f"Removed provider {args.provider_id}")


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
