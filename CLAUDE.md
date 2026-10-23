# Reading Journal

A self-hosted reading journal for manga, novels and fanfic, replacing a Discord forum. Runs on Windows now and moves to a home server (Docker) later.

## Key files

- `002.5 Journaling systems.md`: the requirements. Source of truth for what the app should do. Ask before editing it.
- `002.6 Schema.md`: plain-English description of the schema and which rules are enforced by the database vs the app. Keep it in sync with `schema.sql`.
- `schema.sql`: the runnable schema (SQLite 3.43+, STRICT tables, FTS5).
- `test_schema.py`, `test_app.py`: tests for every rule in the requirements.
- `seed.py`: builds sample data in `journal-demo/`.
- `README.md`: user-facing instructions. Written for a non-programmer; keep it that way.

## Commands

- Run tests: `python test_schema.py` and `python test_app.py`. Both must report all tests passed.
- Sample data: `python seed.py`, then run the app with `JOURNAL_DATA=journal-demo`.
- Start the app: `start.bat`

## Rules

- Run both test files after any change to the schema or app. Add or update a test for every new rule.
- When the schema changes, update `002.6 Schema.md` and bump `PRAGMA user_version`. Existing databases need a migration, not a rebuild.
- Never read from, write to, or delete anything in `journal-data/`. It holds real data. Tests use in-memory databases; demos use `journal-demo/`.
- Every database connection must run `PRAGMA foreign_keys = ON`.
- Timestamps are UTC text in exactly `2026-10-18T14:03:00Z` form.
- Prose fields end in `_md` and hold Markdown. Image paths are relative to the data folder, forward slashes only.
- Data must stay platform agnostic: Markdown for prose, image files on disk, open formats for everything else.
- Target environment: Windows, Python 3.13+. Avoid Unix-only commands in scripts the user runs.

## Working with me

- Keep commentary concise unless we're building on an existing idea.
- If you see a flaw in my reasoning or requirements, say so.
- Don't restate what I've told you unless we're building on it.
- No em dashes where a comma or colon works. Avoid "reads as", "load-bearing" (outside architecture) and "to flag".
- No purple prose, mixed metaphors or excessive praise.
- If my message ends mid-sentence or without punctuation, I hit Enter by accident. Wait for the rest.
- Ask before large refactors or anything hard to undo.
