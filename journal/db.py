"""Database connection and setup.

Every connection goes through connect(), which switches on foreign keys.
SQLite leaves them off by default, and without them deletes don't cascade.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"
STARTER_TAGS_PATH = Path(__file__).resolve().parent / "starter_tags.json"
SCHEMA_VERSION = 5
MIN_SQLITE = (3, 43, 0)


def _v2_to_v3(conn):
    # Editing a journal entry no longer moves the series' progress.
    conn.execute("DROP TRIGGER journal_progress_after_update")


def _v3_to_v4(conn):
    # A work can have several publishers: move each work's one publisher into the new tables.
    conn.execute("""CREATE TABLE publisher (
                        id    INTEGER PRIMARY KEY,
                        name  TEXT NOT NULL UNIQUE COLLATE NOCASE
                    ) STRICT""")
    conn.execute("""CREATE TABLE work_publisher (
                        work_id      INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
                        publisher_id INTEGER NOT NULL REFERENCES publisher(id) ON DELETE CASCADE,
                        position     INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (work_id, publisher_id)
                    ) STRICT""")
    conn.execute("""INSERT OR IGNORE INTO publisher(name)
                    SELECT trim(publisher) FROM work WHERE trim(coalesce(publisher, '')) <> '' ORDER BY id""")
    conn.execute("""INSERT INTO work_publisher(work_id, publisher_id, position)
                    SELECT w.id, p.id, 0 FROM work w JOIN publisher p ON p.name = trim(w.publisher)""")
    conn.execute("ALTER TABLE work DROP COLUMN publisher")


def _v4_to_v5(conn):
    # Tags get editable categories instead of a fixed category word, and the starter tags arrive.
    conn.execute("""CREATE TABLE tag_category (
                        id             INTEGER PRIMARY KEY,
                        name           TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        color          TEXT NOT NULL DEFAULT '#808080'
                                       CHECK (length(color) = 7 AND color GLOB '#[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
                        description_md TEXT,
                        position       INTEGER NOT NULL DEFAULT 0
                    ) STRICT""")
    conn.execute("ALTER TABLE tag ADD COLUMN category_id INTEGER REFERENCES tag_category(id) ON DELETE SET NULL")
    load_starter_tags(conn)
    # The old fixed word 'genre' becomes the Genre category; the other old words had no meaning in the app.
    conn.execute("""UPDATE tag SET category_id = (SELECT id FROM tag_category WHERE name = 'Genre')
                    WHERE category = 'genre' AND category_id IS NULL""")
    conn.execute("ALTER TABLE tag DROP COLUMN category")


def load_starter_tags(conn):
    """Add the starter categories and tags from starter_tags.json.

    Anything that already exists by name is left as it is, except that an uncategorized
    tag gets its starter category and a starter CW is marked. Aliases that would clash
    with an existing name, and nesting that would loop, are skipped.
    """
    data = json.loads(STARTER_TAGS_PATH.read_text(encoding="utf-8"))
    one = lambda sql, args: conn.execute(sql, args).fetchone()
    position = one("SELECT coalesce(max(position) + 1, 0) FROM tag_category", ())[0]
    for cat in data["categories"]:
        if not one("SELECT 1 FROM tag_category WHERE name = ?", (cat["name"],)):
            conn.execute("INSERT INTO tag_category(name, color, description_md, position) VALUES (?,?,?,?)",
                         (cat["name"], cat["color"], cat["description"], position))
            position += 1
        cat_id = one("SELECT id FROM tag_category WHERE name = ?", (cat["name"],))[0]
        for t in cat["tags"]:
            if one("SELECT 1 FROM tag_alias WHERE alias = ?", (t["name"],)):
                continue
            conn.execute("INSERT OR IGNORE INTO tag(name, category_id) VALUES (?, ?)", (t["name"], cat_id))
            tag_id = one("SELECT id FROM tag WHERE name = ?", (t["name"],))[0]
            conn.execute("UPDATE tag SET category_id = ? WHERE id = ? AND category_id IS NULL", (cat_id, tag_id))
            if t["cw"]:
                conn.execute("INSERT OR IGNORE INTO cw_setting(tag_id) VALUES (?)", (tag_id,))
    # Aliases and nesting refer to other tags, so they go in once every tag exists.
    for cat in data["categories"]:
        for t in cat["tags"]:
            row = one("SELECT id FROM tag WHERE name = ?", (t["name"],))
            if row is None:
                continue
            for alias in t["aliases"]:
                if not (one("SELECT 1 FROM tag WHERE name = ?", (alias,))
                        or one("SELECT 1 FROM tag_alias WHERE alias = ?", (alias,))):
                    conn.execute("INSERT INTO tag_alias(alias, tag_id) VALUES (?, ?)", (alias, row[0]))
            for child in t["children"]:
                c = one("SELECT id, parent_id FROM tag WHERE name = ?", (child,))
                if c and c["parent_id"] is None and not one(
                        "SELECT 1 FROM tag_ancestor WHERE tag_id = ? AND ancestor_id = ?", (row[0], c["id"])):
                    conn.execute("UPDATE tag SET parent_id = ? WHERE id = ?", (row[0], c["id"]))


# Upgrade steps: MIGRATIONS[n](conn) takes a database from version n to n + 1.
# All steps run in one transaction, so they must use conn.execute(), never
# conn.executescript(), which commits part-way through.
# old_schemas/ keeps each earlier schema.sql so tests can upgrade a real old database.
MIGRATIONS = {2: _v2_to_v3, 3: _v3_to_v4, 4: _v4_to_v5}


class SetupError(RuntimeError):
    """A problem the person running the app has to fix (shown as a plain message)."""


def check_sqlite():
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        raise SetupError(
            f"This Python comes with SQLite {sqlite3.sqlite_version}, but the journal needs "
            f"{'.'.join(map(str, MIN_SQLITE))} or newer. Install Python 3.13 or newer from python.org."
        )


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        conn.close()
        raise SetupError("SQLite refused to enable foreign keys; the journal can't run safely.")
    return conn


def init_db(db_path):
    """Create the database on first run, upgrade an older one, refuse anything unexpected."""
    check_sqlite()
    conn = connect(db_path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            tables = conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
            if tables:
                raise SetupError(f"{db_path} already contains data that isn't a reading journal.")
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            load_starter_tags(conn)
        elif version > SCHEMA_VERSION:
            raise SetupError(
                f"{db_path} was last used by a newer version of the journal (database version {version}; "
                f"this app supports up to {SCHEMA_VERSION}). Install the newer version to open it."
            )
        elif version < SCHEMA_VERSION:
            migrate(conn, db_path, version)
        # Write-ahead logging lets the phone and the PC use the journal at the same time.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.commit()
    finally:
        conn.close()


def migrate(conn, db_path, version):
    """Back up, then run every upgrade step from `version` in one transaction."""
    missing = [n for n in range(version, SCHEMA_VERSION) if n not in MIGRATIONS]
    if missing:
        raise SetupError(
            f"{db_path} is database version {version}, and this app has no upgrade from version "
            f"{missing[0]}. Nothing was changed."
        )
    backup = backup_db(conn, db_path, version)
    conn.isolation_level = None   # BEGIN and COMMIT are issued by hand below
    # Steps that rebuild a table need foreign keys off (it can't change inside a
    # transaction); every link is checked before committing instead.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        for n in range(version, SCHEMA_VERSION):
            MIGRATIONS[n](conn)
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(f"it left {len(broken)} broken links between records")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.execute("COMMIT")
    except Exception as e:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise SetupError(
            f"Upgrading {db_path} failed, so nothing was changed: {e}. "
            f"A copy from before the upgrade is at {backup}."
        ) from e
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.isolation_level = ""


def backup_db(conn, db_path, version):
    """Copy the database into backups/ next to it and check the copy before returning its path."""
    folder = Path(db_path).parent / "backups"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")   # no colons: Windows forbids them in names
    dest_path = folder / f"journal-v{version}-{stamp}.db"
    try:
        folder.mkdir(exist_ok=True)
        dest = connect(dest_path)
        try:
            conn.backup(dest)
            ok = (dest.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                  and dest.execute("PRAGMA user_version").fetchone()[0] == version)
        finally:
            dest.close()
    except (sqlite3.Error, OSError) as e:
        raise SetupError(f"Couldn't back up {db_path} before upgrading ({e}), so it wasn't upgraded.") from e
    if not ok:
        raise SetupError(f"The backup of {db_path} didn't check out, so it wasn't upgraded.")
    return dest_path
