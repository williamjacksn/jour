# Jour

A web app for keeping a journal.

## Running locally

After you check out the repository, you can run a local instance of **Jour** through `uv`.

    uv run run.py

## Data storage

Everything lives under `.local/`:

- `.local/jour.db` is the application database. It holds settings and the list of users.
- `.local/users/<user-id>.db` is a separate database for each person who signs in. It holds only that person's journal entries.

Anyone the sign-up policy allows (see the admin page) gets their own journal on first sign-in.

### Upgrading from a single-user install

Set `admin_email` before the first start of the new version:

    uv run cli.py set admin_email you@example.com

On startup the existing journal entries are moved into that user's database. Before anything is removed, a backup of the old application database is written to `.local/jour.db.pre-multiuser.bak`. Delete it once you have confirmed everything looks right.

## Sign-in providers

Jour signs people in with OpenID Connect. Providers are configured on the admin page (**Admin > Sign-in**) or from the command line. Each provider needs a client ID and secret from the provider's console, and the callback URL that the admin page shows must be registered there.

    uv run cli.py provider set google --client-id <id> --client-secret <secret>
    uv run cli.py provider list

`google` and `microsoft` are presets: the name, discovery URL and email trust are filled in for you. Any other OpenID Connect provider needs `--name` and `--discovery-document` too.

- People are identified by the provider and its stable subject id, not by email. If someone changes their email at the provider they keep their account.
- A second provider links to an existing account by email only when it is marked **trusts email**. Turn that on only for providers that verify email ownership. Otherwise a sign-in with an address that already has an account is refused.
- A provider that people have used cannot be deleted, only disabled.
- The first Microsoft provider keeps the old `/authorize` callback URL, so the redirect URI registered before providers existed still works.
