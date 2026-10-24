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
- To move the journal to another computer or restore a backup, see "Restoring or moving your journal" below.
- When an update changes how the journal stores your data, it first saves a copy in `journal-data/backups`. Once you're happy the update worked, you can delete old copies to save space.
- If the journal says your data was last used by a newer version, install that newer version. An older one won't open it, to keep it safe.
- The version you're running is shown at the bottom of every page. `CHANGELOG.md` lists what changed in each version.

## Restoring or moving your journal

Always stop the journal first (close its window). Copying or replacing files while it's running can damage your journal.

**Moving to a new computer**

1. On the new computer, install Python as in "Running it on Windows" above.
2. Copy the journal's folder (the one with `start.bat` in it) to the new computer. Leave out the `.venv` folder: it only works on the computer that made it, and `start.bat` makes a fresh one.
3. Copy your `journal-data` folder into that folder, next to `start.bat`. If there's already a `journal-data` folder there, from trying the journal out on the new computer, rename it to `journal-data-old` first.
4. Double-click `start.bat` and check your works are there.

To move to the home server instead, see "Moving to a home server" below.

**Restoring a backup of your `journal-data` folder**

1. Rename the current `journal-data` folder to `journal-data-old`, so nothing is lost if the backup turns out to be the wrong one.
2. Copy your backup folder in next to `start.bat` and make sure it's named `journal-data`.
3. Double-click `start.bat` and check your works are there. Once you're happy, you can delete `journal-data-old`.

**Restoring a copy from `journal-data/backups`**

The journal saves these automatically before an update changes how your data is stored. They hold your works and journal entries; your images stay in the `images` folder and don't need restoring. Each name says which data version it is and when it was saved (in UTC, the time in London without summer time), like `journal-v2-20261023T144000Z.db`.

1. In `journal-data`, rename `journal.db` to `journal-old.db`. If there are files called `journal.db-wal` or `journal.db-shm`, rename those to `journal-old.db-wal` and `journal-old.db-shm`. They belong to the old database and would damage the restored one.
2. Copy the backup file from `backups` into `journal-data` and rename it to `journal.db`. If Windows hides file extensions, the names show without `.db`.
3. These copies are from before an update, so starting the journal will run that update again. If the update itself caused the problem, you'll need the previous version of the journal too: ask for help before restoring.

When the journal starts on a restored or moved journal, it checks the data first. Data from an older version is backed up and updated automatically. Data from a newer version isn't opened, so an older copy of the journal can't damage it.

## Trying it with sample data

`python seed.py` creates a separate `journal-demo` folder with invented works. To view it, run the app with the `JOURNAL_DATA` environment variable set to `journal-demo`. Your real `journal-data` is never touched.

## Moving to a home server (Docker)

1. Copy this project folder and your `journal-data` folder to the server, side by side.
2. Run `docker compose up -d --build` in the project folder.
3. Open `http://<server address>:8420`.

Keep `journal-data` on the server's own disk, not on a network share: SQLite can corrupt databases over network file systems.

## Checking changes

`python test_schema.py` and `python test_app.py` check every rule in the requirements. Both should report all tests passed.
