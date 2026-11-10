# Jour

A web app for keeping a journal.

## Running locally

After you check out the repository, you can run a local instance of **Jour** through `uv`.

    uv run run.py

## Data storage

Everything lives under `.local/`:

- `.local/jour.db` is the application database. It holds settings and the list of users.
- `.local/users/<user-id>.db` is a separate database for each person who signs in. It holds only that person's journal entries.

Anyone who can authenticate with the configured OpenID provider gets their own journal on first sign-in. Email addresses are matched case-insensitively and must be verified by the provider.

### Upgrading from a single-user install

Set `admin_email` before the first start of the new version:

    uv run cli.py set admin_email you@example.com

On startup the existing journal entries are moved into that user's database. Before anything is removed, a backup of the old application database is written to `.local/jour.db.pre-multiuser.bak`. Delete it once you have confirmed everything looks right.
