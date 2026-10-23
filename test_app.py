"""Tests for the web app. Run with:  python3 test_app.py

Each test starts the app on a fresh temporary data folder and uses it the
way a browser would (filling in forms, uploading files). The folder is deleted
straight after the test; a test that leaves a file in it open fails.
"""
import gc
import io
import re
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image

from journal import create_app
from journal.db import connect


def png(color=(200, 50, 50), size=(40, 60)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    buf.seek(0)
    return buf


class App:
    instances = []   # deleted by cleanup() after each test

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        App.instances.append(self)
        self.app = create_app(self.tmp.name, testing=True)
        self.client = self.app.test_client()

    def db(self):
        return connect(self.app.config["DB_PATH"])

    def one(self, sql, args=()):
        conn = self.db()
        try:
            row = conn.execute(sql, args).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def add_work(self, **fields):
        data = {"title": "Test Manga", "format_code": "manga", "length_unit": "chapter", "status": "reading"}
        data.update(fields)
        r = self.client.post("/works/new", data=data, content_type="multipart/form-data")
        assert r.status_code == 302, r.get_data(as_text=True)[:2000]
        return int(re.search(r"/works/(\d+)", r.headers["Location"]).group(1))

    def post_entry(self, work_id, expect=302, **fields):
        r = self.client.post(f"/works/{work_id}/entries", data=fields, content_type="multipart/form-data")
        assert r.status_code == expect, (r.status_code, r.get_data(as_text=True)[:2000])
        return r


def cleanup(strict=True):
    """Delete the data folders the last test made.

    On Windows an open database or file can't be deleted, so with strict=True
    a leftover open handle fails the test instead of leaving the folder behind.
    """
    error = None
    while App.instances:
        tmp = App.instances.pop().tmp
        try:
            tmp.cleanup()
        except OSError as e:
            error = error or e
            gc.collect()   # the leaked handle is garbage once the test returns; free it so the folder still goes
            shutil.rmtree(tmp.name, ignore_errors=True)
    if strict and error:
        raise RuntimeError(f"left a file open in its data folder ({error})")


# ---------------------------------------------------------------- works

def test_pages_load():
    a = App()
    wid = a.add_work()
    for url in ("/", "/works/new", f"/works/{wid}", f"/works/{wid}/edit", f"/works/{wid}/delete", "/?status=reading"):
        assert a.client.get(url).status_code == 200, url
    assert a.client.get("/works/999").status_code == 404

def test_foreign_keys_on_every_connection():
    a = App()
    assert a.one("PRAGMA foreign_keys") == 1

def test_add_work_with_everything():
    a = App()
    wid = a.add_work(title="Lantern", length_total="120", authors="Mori\nmori\nAki", artists="Ren",
                     alt_titles="Ranta\nLantern", src_anilist="https://anilist.co/manga/12345/Lantern",
                     src_mangaupdates="https://www.mangaupdates.com/series/pm5ww2j/lantern",
                     src_ao3="", cover=(png(), "cover.png"))
    assert a.one("SELECT length_total FROM work WHERE id = ?", (wid,)) == 120
    assert a.one("SELECT COUNT(*) FROM work_creator WHERE work_id = ?", (wid,)) == 3   # duplicate Mori dropped
    assert a.one("SELECT COUNT(*) FROM work_alt_title WHERE work_id = ?", (wid,)) == 1   # same as title dropped
    assert a.one("SELECT external_id FROM work_source_id WHERE source_code = 'anilist'") == "12345"
    assert a.one("SELECT external_id FROM work_source_id WHERE source_code = 'mangaupdates'") == "pm5ww2j"
    path = a.one("SELECT i.file_path FROM work w JOIN image i ON i.id = w.cover_image_id")
    assert (Path(a.tmp.name) / path).is_file()
    with a.client.get(f"/media/{path}") as r:   # closing releases the image file
        assert r.status_code == 200

def test_new_work_logs_initial_status():
    a = App()
    wid = a.add_work(status="tbr")
    assert a.one("SELECT status_code FROM work_current_status WHERE work_id = ?", (wid,)) == "tbr"
    assert a.one("SELECT status_to FROM journal_entry WHERE work_id = ? AND kind = 'status'", (wid,)) == "tbr"

def test_unit_defaults_to_format():
    a = App()
    wid = a.add_work(format_code="light_novel", length_unit="")
    assert a.one("SELECT length_unit FROM work WHERE id = ?", (wid,)) == "volume"

def test_work_form_validation_keeps_input():
    a = App()
    r = a.client.post("/works/new", data={"title": "", "format_code": "scroll", "length_total": "-3",
                                          "description_md": "keep me", "status": "reading"})
    body = r.get_data(as_text=True)
    assert r.status_code == 400
    assert "Title is required" in body and "Choose a format" in body and "Total length" in body
    assert "keep me" in body
    assert a.one("SELECT COUNT(*) FROM work") == 0

def test_duplicate_source_id_rejected_with_link():
    a = App()
    first = a.add_work(title="First", src_anilist="555")
    r = a.client.post("/works/new", data={"title": "Second", "format_code": "manga", "status": "tbr",
                                          "src_anilist": "anilist.co/manga/555"})
    body = r.get_data(as_text=True)
    assert r.status_code == 400 and f"/works/{first}" in body and "already used by" in body
    assert a.one("SELECT COUNT(*) FROM work") == 1

def test_bad_source_link_rejected():
    a = App()
    r = a.client.post("/works/new", data={"title": "x", "format_code": "manga", "status": "tbr",
                                          "src_ao3": "https://example.com/works/1"})
    assert r.status_code == 400 and "AO3" in r.get_data(as_text=True)

def test_not_an_image_rejected():
    a = App()
    r = a.client.post("/works/new", data={"title": "x", "format_code": "manga", "status": "tbr",
                                          "cover": (io.BytesIO(b"not an image"), "cover.png")},
                      content_type="multipart/form-data")
    assert r.status_code == 400 and "an image the journal can read" in r.get_data(as_text=True)
    assert a.one("SELECT COUNT(*) FROM work") == 0

def test_edit_work_and_unit_change_clears_progress():
    a = App()
    wid = a.add_work(src_anilist="1")
    a.post_entry(wid, body="hi", progress="12")
    r = a.client.post(f"/works/{wid}/edit", data={"title": "Renamed", "format_code": "manga",
                                                  "length_unit": "volume", "src_anilist": "1"},
                      content_type="multipart/form-data", follow_redirects=True)
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and "Renamed" in body and "cleared" in body
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) is None
    assert a.one("SELECT progress_valid FROM journal_entry_progress WHERE work_id = ? AND progress_value IS NOT NULL", (wid,)) == 0
    assert a.one("SELECT external_id FROM work_source_id WHERE work_id = ?", (wid,)) == "1"   # own ID isn't a conflict

def test_delete_work():
    a = App()
    wid = a.add_work()
    a.post_entry(wid, body="x")
    assert a.client.post(f"/works/{wid}/delete").status_code == 302
    assert a.one("SELECT COUNT(*) FROM work") == 0
    assert a.one("SELECT COUNT(*) FROM journal_entry") == 0
    assert a.one("SELECT COUNT(*) FROM status_event") == 0

# ---------------------------------------------------------------- journal

def test_post_entry_with_screenshots_and_progress():
    a = App()
    wid = a.add_work()
    a.post_entry(wid, body="Chapter **one**", progress="1", images=[(png(), "a.png"), (png((0, 0, 255)), "b.png")])
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) == 1
    assert a.one("SELECT COUNT(*) FROM journal_entry_image") == 2
    page = a.client.get(f"/works/{wid}").get_data(as_text=True)
    assert "<strong>one</strong>" in page and "Ch 1" in page

def test_same_screenshot_stored_once():
    a = App()
    wid = a.add_work()
    a.post_entry(wid, images=[(png(), "a.png")])
    a.post_entry(wid, images=[(png(), "copy.png")])
    assert a.one("SELECT COUNT(*) FROM image") == 1
    assert a.one("SELECT COUNT(*) FROM journal_entry_image") == 2

def test_empty_entry_rejected():
    a = App()
    wid = a.add_work()
    r = a.post_entry(wid, expect=400, body="   ", progress="")
    assert "Write something" in r.get_data(as_text=True)

def test_bad_progress_keeps_text():
    a = App()
    wid = a.add_work()
    r = a.post_entry(wid, expect=400, body="my thoughts", progress="twelve")
    body = r.get_data(as_text=True)
    assert "Progress must be a number" in body and "my thoughts" in body
    assert a.one("SELECT COUNT(*) FROM journal_entry WHERE kind = 'note'") == 0

def test_bad_screenshot_posts_nothing():
    a = App()
    wid = a.add_work()
    r = a.post_entry(wid, expect=400, body="keep", images=[(png(), "ok.png"), (io.BytesIO(b"junk"), "bad.png")])
    assert "keep" in r.get_data(as_text=True)
    assert a.one("SELECT COUNT(*) FROM journal_entry WHERE kind = 'note'") == 0
    assert a.one("SELECT COUNT(*) FROM image") == 0

def test_raw_html_is_not_run():
    a = App()
    wid = a.add_work()
    a.post_entry(wid, body="<script>alert(1)</script> [x](javascript:alert(1))")
    page = a.client.get(f"/works/{wid}").get_data(as_text=True)
    assert "<script>alert(1)" not in page and 'href="javascript:' not in page

def test_backdated_entry():
    a = App()
    wid = a.add_work()
    a.post_entry(wid, body="old", posted_at="2024-03-05T08:00:00Z")
    assert a.one("SELECT posted_at FROM journal_entry WHERE body_md = 'old'") == "2024-03-05T08:00:00Z"
    a.post_entry(wid, expect=400, body="bad date", posted_at="2024-3-5T08:00:00Z")

def test_progress_prefilled_in_composer():
    a = App()
    wid = a.add_work()
    a.post_entry(wid, body="x", progress="22.5")
    page = a.client.get(f"/works/{wid}").get_data(as_text=True)
    assert re.search(r'name="progress" inputmode="decimal" autocomplete="off" value="22.5"', page)

def test_edit_entry_rules():
    a = App()
    wid = a.add_work()
    a.post_entry(wid, body="tyop", progress="120", images=[(png(), "a.png")])
    eid = a.one("SELECT id FROM journal_entry WHERE kind = 'note'")
    a.client.post(f"/works/{wid}/progress", data={"progress": "0"})          # reread reset
    # fixing a typo without touching progress must not move the work back to 120
    r = a.client.post(f"/entries/{eid}/edit", data={"body": "typo", "progress": "120",
                                                    "posted_at": a.one("SELECT posted_at FROM journal_entry WHERE id = ?", (eid,))},
                      content_type="multipart/form-data")
    assert r.status_code == 302
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) == 0
    assert a.one("SELECT edited_at IS NOT NULL FROM journal_entry WHERE id = ?", (eid,)) == 1
    # raising progress in an edit moves the work forward
    a.client.post(f"/entries/{eid}/edit", data={"body": "typo", "progress": "130"}, content_type="multipart/form-data")
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) == 130
    # removing the screenshot and adding another
    img = a.one("SELECT image_id FROM journal_entry_image WHERE entry_id = ?", (eid,))
    a.client.post(f"/entries/{eid}/edit", data={"body": "typo", "progress": "130", "remove_image": str(img),
                                                "images": [(png((1, 2, 3)), "n.png")]}, content_type="multipart/form-data")
    conn = a.db()
    try:
        rows = conn.execute("SELECT image_id FROM journal_entry_image WHERE entry_id = ?", (eid,)).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1 and rows[0][0] != img
    # emptying everything is refused
    r = a.client.post(f"/entries/{eid}/edit", data={"body": "", "progress": "",
                                                    "remove_image": str(rows[0][0])}, content_type="multipart/form-data")
    assert r.status_code == 400

def test_delete_entry_keeps_progress():
    a = App()
    wid = a.add_work()
    a.post_entry(wid, body="x", progress="22")
    eid = a.one("SELECT id FROM journal_entry WHERE kind = 'note'")
    assert a.client.post(f"/entries/{eid}/delete").status_code == 302
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) == 22

def test_mismatched_unit_shows_question_mark():
    a = App()
    wid = a.add_work()
    a.post_entry(wid, body="x", progress="5")
    conn = a.db()
    with conn:
        conn.execute("INSERT INTO journal_entry(work_id, body_md, progress_value, progress_unit) VALUES (?, 'v', 2, 'volume')", (wid,))
    conn.close()
    page = a.client.get(f"/works/{wid}").get_data(as_text=True)
    assert 'class="why"' in page and "counts in volumes" in page
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) == 5

# ---------------------------------------------------------------- status, progress, review

def test_status_change_logs_entry():
    a = App()
    wid = a.add_work(status="reading")
    a.client.post(f"/works/{wid}/status", data={"status": "paused"})
    assert a.one("SELECT status_code FROM work_current_status WHERE work_id = ?", (wid,)) == "paused"
    assert a.one("SELECT status_from || '>' || status_to FROM journal_entry WHERE kind = 'status' ORDER BY id DESC") == "reading>paused"

def test_same_status_does_nothing():
    a = App()
    wid = a.add_work(status="reading")
    a.client.post(f"/works/{wid}/status", data={"status": "reading"})
    assert a.one("SELECT COUNT(*) FROM status_event WHERE work_id = ?", (wid,)) == 1

def test_reread_prompt():
    a = App()
    wid = a.add_work(status="reading")
    a.post_entry(wid, body="done", progress="64")
    a.client.post(f"/works/{wid}/status", data={"status": "completed"})
    r = a.client.post(f"/works/{wid}/status", data={"status": "reading"})
    assert r.status_code == 200 and "Reset progress to 0" in r.get_data(as_text=True)
    assert a.one("SELECT status_code FROM work_current_status WHERE work_id = ?", (wid,)) == "completed"   # nothing yet
    a.client.post(f"/works/{wid}/status", data={"status": "reading", "reset": "yes"})
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) == 0
    assert a.one("SELECT completions FROM work_completion_count WHERE work_id = ?", (wid,)) == 1
    a.post_entry(wid, body="reread", progress="3")
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) == 3

def test_reread_keep_progress():
    a = App()
    wid = a.add_work(status="completed")
    a.client.post(f"/works/{wid}/progress", data={"progress": "50"})
    a.client.post(f"/works/{wid}/status", data={"status": "reading", "reset": "no"})
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) == 50
    assert a.one("SELECT status_code FROM work_current_status WHERE work_id = ?", (wid,)) == "reading"

def test_paused_to_reading_no_prompt():
    a = App()
    wid = a.add_work(status="paused")
    r = a.client.post(f"/works/{wid}/status", data={"status": "reading"})
    assert r.status_code == 302

def test_deleting_status_entry_keeps_status():
    a = App()
    wid = a.add_work(status="reading")
    a.client.post(f"/works/{wid}/status", data={"status": "dropped"})
    eid = a.one("SELECT id FROM journal_entry WHERE status_to = 'dropped'")
    a.client.post(f"/entries/{eid}/delete")
    assert a.one("SELECT status_code FROM work_current_status WHERE work_id = ?", (wid,)) == "dropped"

def test_manual_progress_can_go_down_or_clear():
    a = App()
    wid = a.add_work()
    a.client.post(f"/works/{wid}/progress", data={"progress": "30"})
    a.client.post(f"/works/{wid}/progress", data={"progress": "10"})
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) == 10
    a.client.post(f"/works/{wid}/progress", data={"progress": ""})
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) is None
    assert a.client.post(f"/works/{wid}/progress", data={"progress": "-1"}).status_code == 400

def test_rating_and_review():
    a = App()
    wid = a.add_work()
    a.client.post(f"/works/{wid}/review", data={"rating": "8.5", "review_md": "Great"})
    assert a.one("SELECT rating FROM work WHERE id = ?", (wid,)) == 8.5
    for bad in ("8.55", "11", "-1", "nan", "abc"):
        assert a.client.post(f"/works/{wid}/review", data={"rating": bad}).status_code == 400, bad
    assert a.one("SELECT rating FROM work WHERE id = ?", (wid,)) == 8.5

def test_notes():
    a = App()
    wid = a.add_work()
    a.client.post(f"/works/{wid}/notes", data={"notes_md": "Up to the festival arc"})
    assert "Up to the festival arc" in a.client.get(f"/works/{wid}").get_data(as_text=True)

def test_library_filter():
    a = App()
    a.add_work(title="Reading one", status="reading")
    a.add_work(title="Paused one", status="paused")
    a.client.get("/")                       # clears the "Added …" messages
    page = a.client.get("/?status=paused").get_data(as_text=True)
    assert "Paused one" in page and "Reading one" not in page

def test_media_cannot_escape_data_folder():
    a = App()
    for url in ("/media/journal.db", "/media/images/../journal.db", "/media/images/%2e%2e/journal.db",
                "/media/images/./../journal.db", "/media/images//journal.db", "/media/images/..%5Cjournal.db",
                "/media/images/..\\journal.db"):
        assert a.client.get(url).status_code == 404, url

def test_reopening_existing_data_folder():
    a = App()
    a.add_work(title="Persisted")
    again = create_app(a.tmp.name, testing=True)
    assert "Persisted" in again.test_client().get("/").get_data(as_text=True)


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            cleanup()
            print(f"PASS  {name}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
            cleanup(strict=False)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
