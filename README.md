# Reading Journal

A personal reading journal you run yourself. Everything lives in one folder, `journal-data`: the database (`journal.db`) and your images (`images/`).

## Running it on Windows

1. Install **Python 3.13 or newer** from https://www.python.org/downloads/. In the installer, tick **Add python.exe to PATH**.
2. Double-click **start.bat**. The first run takes a minute to set up; after that it starts in a few seconds.
3. The window shows two addresses. Open the first one (`http://localhost:8420`) in your browser.
4. To stop the journal, close that window.

Windows may ask whether to allow Python on the network. Allow it on **private networks** if you want to use the journal from your phone.

## Using it from your phone

While the journal is running on your PC, open the second address the window shows (something like `http://192.168.1.20:8420`) on your phone. The phone must be on the same Wi-Fi. Add it to your home screen for quick access.

There is no password, so anyone on your home Wi-Fi who knows the address can open the journal. Don't run it on public or shared networks.

## Your data

- Back up the `journal-data` folder regularly. It is your whole journal.
- Copy it only while the journal is stopped.
- To move the journal to another computer or the home server, stop it and copy the folder.
- When an update changes how the journal stores your data, it first saves a copy in `journal-data/backups`. Once you're happy the update worked, you can delete old copies to save space.
- If the journal says your data was last used by a newer version, install that newer version. An older one won't open it, to keep it safe.
- The version you're running is shown at the bottom of every page. `CHANGELOG.md` lists what changed in each version.

## Trying it with sample data

`python seed.py` creates a separate `journal-demo` folder with invented works. To view it, run the app with the `JOURNAL_DATA` environment variable set to `journal-demo`. Your real `journal-data` is never touched.

## Moving to a home server (Docker)

1. Copy this project folder and your `journal-data` folder to the server, side by side.
2. Run `docker compose up -d --build` in the project folder.
3. Open `http://<server address>:8420`.

Keep `journal-data` on the server's own disk, not on a network share: SQLite can corrupt databases over network file systems.

## Checking changes

`python test_schema.py` and `python test_app.py` check every rule in the requirements. Both should report all tests passed.
