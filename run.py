"""Start the Reading Journal.

Settings come from environment variables (all optional):
  JOURNAL_DATA  folder holding journal.db and images   (default: journal-data next to this file)
  JOURNAL_HOST  network address to listen on           (default: 0.0.0.0, reachable from your phone)
  JOURNAL_PORT  port                                   (default: 8420)
"""
import os
import socket
import sys
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


if __name__ == "__main__":
    main()
