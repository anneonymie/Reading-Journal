"""Database connection and setup.

Every connection goes through connect(), which switches on foreign keys.
SQLite leaves them off by default, and without them deletes don't cascade.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"
SCHEMA_VERSION = 3
MIN_SQLITE = (3, 43, 0)


def _v2_to_v3(conn):
    # Editing a journal entry no longer moves the series' progress.
    conn.execute("DROP TRIGGER journal_progress_after_update")


# Upgrade steps: MIGRATIONS[n](conn) takes a database from version n to n + 1.
# All steps run in one transaction, so they must use conn.execute(), never
# conn.executescript(), which commits part-way through.
# old_schemas/ keeps each earlier schema.sql so tests can upgrade a real old database.
MIGRATIONS = {2: _v2_to_v3}


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
