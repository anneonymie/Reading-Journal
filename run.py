"""Start the Reading Journal.

Settings come from environment variables (all optional):
  JOURNAL_DATA  folder holding journal.db and images   (default: journal-data next to this file)
  JOURNAL_HOST  network address to listen on           (default: 0.0.0.0, reachable from your phone)
  JOURNAL_PORT  port                                   (default: 8420)

  python run.py --dev   restarts by itself when the code changes, for working on the app.
                        Uses journal-demo unless JOURNAL_DATA is set, and only this computer can open it.
"""
import os
import socket
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent


def lan_address():
    """This computer's address on the home network, for opening the journal on a phone."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))   # reserved test address; nothing is actually sent
            return s.getsockname()[0]
    except OSError:
        return None


def main():
    from waitress import serve
    from journal import create_app
    from journal.db import SetupError

    data_dir = Path(os.environ.get("JOURNAL_DATA") or HERE / "journal-data")
    host = os.environ.get("JOURNAL_HOST", "0.0.0.0")
    port = int(os.environ.get("JOURNAL_PORT", "8420"))

    try:
        app = create_app(data_dir)
    except SetupError as e:
        print(f"\nThe journal couldn't start: {e}\n")
        sys.exit(1)

    print(f"\nReading Journal is running. Your data is in {data_dir.resolve()}")
    print(f"  On this computer:  http://localhost:{port}")
    if host in ("0.0.0.0", "::"):
        ip = lan_address()
        if ip:
            print(f"  On your phone:     http://{ip}:{port}  (same Wi-Fi)")
    print("Close this window to stop it.\n")
    serve(app, host=host, port=port, threads=8)


def dev_settings(environ):
    """Data folder and port for dev mode. Never the network: Flask's test server isn't safe there."""
    data_dir = Path(environ.get("JOURNAL_DATA") or HERE / "journal-demo")
    return data_dir, int(environ.get("JOURNAL_PORT", "8420"))


def dev_app(data_dir):
    """The app with templates re-read on every page, or a page showing why it couldn't start.

    Showing the error instead of quitting keeps the server watching, so fixing the code brings it back.
    """
    try:
        from journal import create_app
        app = create_app(data_dir)
        app.jinja_env.auto_reload = True
        return app
    except Exception:
        message = traceback.format_exc()
        print(message)

        def error_page(environ, start_response):
            start_response("500 Internal Server Error", [("Content-Type", "text/plain; charset=utf-8")])
            return [f"The journal couldn't start. Fix the code and refresh.\n\n{message}".encode()]
        return error_page


def dev():
    from werkzeug.serving import is_running_from_reloader, run_simple

    data_dir, port = dev_settings(os.environ)
    if is_running_from_reloader():
        app = dev_app(data_dir)
    else:
        # This first process only watches files and restarts the one that serves pages.
        app = None
        print(f"\nReading Journal (dev mode) is running. Data: {data_dir.resolve()}")
        print(f"  http://localhost:{port}")
        print("It restarts by itself when the code changes; refresh the page to see changes.")
        print("Close this window to stop it.\n")
    run_simple("127.0.0.1", port, app, use_reloader=True, reloader_type="stat",
               extra_files=[str(HERE / "schema.sql")])


if __name__ == "__main__":
    dev() if "--dev" in sys.argv[1:] else main()
