"""Reading Journal web app."""
import secrets
from pathlib import Path

from flask import Flask, g

from . import db as dbmod
from .text import fmt_num, render_markdown

# The app's release version. Change it only as part of a release (see CLAUDE.md).
VERSION = "0.2.0"


def create_app(data_dir, testing=False):
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "images").mkdir(exist_ok=True)
    db_path = data_dir / "journal.db"
    dbmod.init_db(db_path)

    app = Flask(__name__)
    app.config.update(
        DATA_DIR=str(data_dir),
        DB_PATH=str(db_path),
        TESTING=testing,
        MAX_CONTENT_LENGTH=200 * 1024 * 1024,   # one post with many images
        SECRET_KEY=_secret_key(db_path),
    )

    app.jinja_env.filters["md"] = render_markdown
    app.jinja_env.filters["num"] = fmt_num
    app.jinja_env.globals["app_version"] = VERSION

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    from .views import bp
    app.register_blueprint(bp)
    return app


def _secret_key(db_path):
    """A random key kept in the database, so messages survive restarts."""
    conn = dbmod.connect(db_path)
    try:
        row = conn.execute("SELECT value FROM app_setting WHERE key = 'secret_key'").fetchone()
        if row:
            return row["value"]
        key = secrets.token_hex(32)
        with conn:
            conn.execute("INSERT INTO app_setting(key, value) VALUES ('secret_key', ?)", (key,))
        return key
    finally:
        conn.close()
