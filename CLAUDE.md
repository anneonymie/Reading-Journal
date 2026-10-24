# Reading Journal

A self-hosted reading journal for manga, novels and fanfic, replacing a Discord forum. Runs on Windows now and moves to a home server (Docker) later.

## Key files

- `002.5 Journaling systems.md`: the requirements. Source of truth for what the app should do. Ask before editing it.
- `002.6 Schema.md`: plain-English description of the schema and which rules are enforced by the database vs the app. Keep it in sync with `schema.sql`.
- `schema.sql`: the runnable schema (SQLite 3.43+, STRICT tables, FTS5).
- `old_schemas/`: each earlier release's `schema.sql`, used by tests to upgrade a real old database. Never edit these.
- `test_schema.py`, `test_app.py`: tests for every rule in the requirements.
- `seed.py`: builds sample data in `journal-demo/`.
- `README.md`: user-facing instructions. Written for a non-programmer; keep it that way.
- `CHANGELOG.md`: what changed in each release, also written for a non-programmer. The app shows it at `/changelog`, so the Docker image includes it.

## App structure

Flask app served by waitress. Server-rendered Jinja templates; plain SQL through `sqlite3`, no ORM. Many rules (progress, search sync, tag cycles) are enforced by triggers in `schema.sql`, not Python.

- `run.py`: entry point. Reads `JOURNAL_DATA`, `JOURNAL_HOST`, `JOURNAL_PORT` and starts waitress. `start.bat` sets up `.venv` and runs it.
- `journal/__init__.py`: `VERSION` (the release version, shown in the footer) and `create_app(data_dir)`, which creates the data folder, runs `init_db` and closes the per-request connection on teardown.
- `journal/db.py`: `connect()` (the only way to open a connection; turns on foreign keys), `init_db()` (creates, upgrades or refuses the database), `MIGRATIONS` (upgrade steps), `SetupError`.
- `journal/views.py`: every route, in one blueprint `bp`, plus form parsing and validation. Get the request's connection with `db()`. `/media/<path>` serves images from the data folder.
- `journal/images.py`: `store_image()`. Validates uploads with Pillow and stores them as `images/<sha[:2]>/<sha>.<ext>`, deduped by hash.
- `journal/text.py`: Markdown rendering (raw HTML disabled), UTC timestamp helpers, number formatting.
- `journal/templates/`: Jinja templates. `base.html` is the layout (header, footer with links, version and logo credit); `_macros.html` holds shared bits.
- `journal/static/`: `style.css`, `app.js` (optional enhancements; every page works without JS), bundled fonts, `emojione-notebook.svg` (logo and tab icon; EmojiOne's icon, recolored by me). CC BY 4.0 requires the footer credit: creator, that it was changed, and a link to the licence. Keep all three.
- `Dockerfile`, `docker-compose.yml`: home server deployment. The data folder is mounted at `/data`.

## Commands

- Run tests: `python test_schema.py` and `python test_app.py`. Both must report all tests passed.
- Sample data: `python seed.py`, then run the app with `JOURNAL_DATA=journal-demo`.
- Start the app: `start.bat`

## Rules

- Run both test files after any change to the schema or app. Add or update a test for every new rule.
- When the schema changes: first save the current `schema.sql` as `old_schemas/schema_v<current version>.sql` (copy it byte-for-byte from the last release tag, e.g. `cmd /c "git cat-file blob v0.1.0:schema.sql > old_schemas\schema_v2.sql"`; PowerShell redirection re-encodes text). Then update `002.6 Schema.md`, bump `SCHEMA_VERSION` in `journal/db.py` and `PRAGMA user_version` in `schema.sql` together, and add a `MIGRATIONS` step from the previous version, with a test that upgrades a database made by the old schema. Existing databases need a migration, not a rebuild. On startup `init_db` backs up `journal.db` to `backups/` before migrating, runs all steps in one transaction, and refuses databases newer than `SCHEMA_VERSION`; keep those guarantees and their tests.
- Every user-facing change gets a line under "Unreleased" in `CHANGELOG.md`, in plain language: what changed for me, not how.
- `journal-data/` holds my real journal. Never write to or delete anything in it. Don't read it unless I ask. When I do, check with me that the journal is stopped, copy the whole folder to a temporary location outside the project, work only on the copy, and delete the copy afterwards. Prefer checks that don't read my writing (version number, integrity check, record counts) over reading entries. Tests use in-memory databases or temporary folders; demos use `journal-demo/`.
- Every database connection must run `PRAGMA foreign_keys = ON`.
- Every database connection must be closed, including in tests and scripts: use `try`/`finally` or the per-request `db()`. Windows won't delete or replace a file that's still open, so a leaked connection breaks cleanup, backups and moves. Close opened files and test responses too.
- Timestamps are UTC text in exactly `2026-10-18T14:03:00Z` form.
- Say "image", not "screenshot", in the app, docs, code and when talking to me. Images include covers, pictures in entries and custom emoji.
- Prose fields end in `_md` and hold Markdown. Image paths are relative to the data folder, forward slashes only.
- Data must stay platform agnostic: Markdown for prose, image files on disk, open formats for everything else.
- Target environment: Windows, Python 3.13+. Avoid Unix-only commands in scripts the user runs.

## Releases

The version lives only in `VERSION` in `journal/__init__.py`. Git tags are `v` plus the version, e.g. `v0.1.0`. When I say "release":

1. Make sure everything else is committed and both test files pass. If not, stop and tell me.
2. Pick the version. If `VERSION` has never been tagged, release it as is: the first release is 0.1.0. Otherwise, fixes only raise the last number (0.1.0 to 0.1.1); anything new or changed raises the middle number and resets the last (0.1.3 to 0.2.0). Tell me which and why. Only go to 1.0.0 if I ask.
3. In `CHANGELOG.md`, rename "Unreleased" to `<version> (<YYYY-MM-DD>)` and add a new empty "Unreleased" above it. If "Unreleased" is empty, ask whether to release anyway.
4. Set `VERSION`, then run both test files again.
5. Commit as `Release <version>` and create an annotated tag: `git tag -a v<version> -m "Release <version>"`.
6. Don't push anywhere unless I ask.

## Working with me

- I'm not a software engineer. When you use a technical term or describe what code does, add one plain-language sentence explaining it.
- Keep commentary concise unless we're building on an existing idea.
- If you see a flaw in my reasoning or requirements, say so.
- Don't restate what I've told you unless we're building on it.
- No em dashes where a comma or colon works. Avoid "reads as", "load-bearing" (outside architecture) and "to flag".
- No purple prose, mixed metaphors or excessive praise.
- If my message ends mid-sentence or without punctuation, I hit Enter by accident. Wait for the rest.
- Ask before large refactors or anything hard to undo.
