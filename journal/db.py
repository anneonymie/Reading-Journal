"""Database connection and setup.

Every connection goes through connect(), which switches on foreign keys.
SQLite leaves them off by default, and without them deletes don't cascade.
"""
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"
SCHEMA_VERSION = 2
MIN_SQLITE = (3, 43, 0)


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
    """Create the database on first run; refuse to open anything unexpected."""
    check_sqlite()
    conn = connect(db_path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            tables = conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
            if tables:
                raise SetupError(f"{db_path} already contains data that isn't a reading journal.")
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        elif version != SCHEMA_VERSION:
            raise SetupError(
                f"{db_path} is schema version {version}, but this app expects {SCHEMA_VERSION}."
            )
        # Write-ahead logging lets the phone and the PC use the journal at the same time.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.commit()
    finally:
        conn.close()
