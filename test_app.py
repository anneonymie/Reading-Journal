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
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

from journal import VERSION, create_app
from journal import db as dbmod
from journal.db import connect


def png(color=(200, 50, 50), size=(40, 60)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    buf.seek(0)
    return buf


OLD_SCHEMAS = Path(__file__).parent / "old_schemas"


class App:
    instances = []   # deleted by cleanup() after each test

    def __init__(self, old_schema=None, before=None):
        self.tmp = tempfile.TemporaryDirectory()
        App.instances.append(self)
        if old_schema:   # start from a journal made by an earlier release, with before(conn) adding data
            conn = connect(Path(self.tmp.name) / "journal.db")
            try:
                conn.executescript((OLD_SCHEMAS / old_schema).read_text(encoding="utf-8"))
                if before:
                    before(conn)
                conn.commit()
            finally:
                conn.close()
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
    wid = a.add_work(title="Lantern", length_total="120", creator_name=["Mori", "mori", "Aki", "Ren"],
                     creator_author=["0", "1", "2"], creator_artist=["3"],
                     alt_title=["Ranta", "Lantern", "ranta", ""],
                     source_link=["https://anilist.co/manga/12345/Lantern",
                                  "https://www.mangaupdates.com/series/pm5ww2j/lantern"], cover=(png(), "cover.png"))
    assert a.one("SELECT length_total FROM work WHERE id = ?", (wid,)) == 120
    assert a.one("SELECT COUNT(*) FROM work_creator WHERE work_id = ?", (wid,)) == 3   # duplicate Mori dropped
    assert a.one("SELECT COUNT(*) FROM work_alt_title WHERE work_id = ?", (wid,)) == 1   # same as title, repeat and blank dropped
    assert a.one("SELECT external_id FROM work_source_id WHERE source_code = 'anilist'") == "12345"
    assert a.one("SELECT external_id FROM work_source_id WHERE source_code = 'mangaupdates'") == "pm5ww2j"
    path = a.one("SELECT i.file_path FROM work w JOIN image i ON i.id = w.cover_image_id")
    assert (Path(a.tmp.name) / path).is_file()
    with a.client.get(f"/media/{path}") as r:   # closing releases the image file
        assert r.status_code == 200

def test_work_page_header_and_details():
    a = App()
    wid = a.add_work(title="Lantern", format_code="manhwa", creator_name=["Mori", "Aki"],
                     description_md="A *quiet* story.", alt_title=["Ranta"])
    page = a.client.get(f"/works/{wid}").get_data(as_text=True)
    head = re.search(r'<header class="work-head">(.*?)</header>', page, re.S).group(1)
    details = re.search(r"<summary>Details</summary>(.*?)</details>", page, re.S).group(1)
    assert "Manhwa by Aki and Mori" in head
    assert head.index("Manhwa by") < head.index("A <em>quiet</em> story.")   # creators, then description
    assert "Ranta" not in head and "<dt>Alternate titles</dt><dd>Ranta</dd>" in details
    assert "quiet" not in details

def creators_line(a, wid):
    meta = re.search(r'<p class="work-meta">(.*?)</p>', a.client.get(f"/works/{wid}").get_data(as_text=True), re.S)
    return " ".join(meta.group(1).split())

def creator_roles(a, wid):
    conn = a.db()
    try:
        return conn.execute("""SELECT c.name, wc.role FROM work_creator wc JOIN creator c ON c.id = wc.creator_id
                               WHERE wc.work_id = ? ORDER BY c.name, wc.role""", (wid,)).fetchall()
    finally:
        conn.close()

def test_creator_roles_shown_once_per_person():
    a = App()
    # Mori is typed twice (different capitals) with a different role each time
    wid = a.add_work(format_code="manhwa", creator_name=["Mori", "Ren", "Asdf", "mori"],
                     creator_author=["0"], creator_artist=["1", "3"])
    assert creators_line(a, wid) == "Manhwa by Mori (Writer and Artist), Ren (Artist) and Asdf"
    assert [tuple(r) for r in creator_roles(a, wid)] == [
        ("Asdf", "unspecified"), ("Mori", "artist"), ("Mori", "author"), ("Ren", "artist")]

def test_creator_without_role():
    a = App()
    wid = a.add_work(format_code="manhwa", creator_name=["Asdf"])
    assert creators_line(a, wid) == "Manhwa by Asdf"

def test_edit_form_keeps_creators_and_roles():
    a = App()
    wid = a.add_work(creator_name=["Mori", "Asdf"], creator_author=["0"], creator_artist=["0"])
    form = a.client.get(f"/works/{wid}/edit").get_data(as_text=True)
    shown, spare = form.split("<noscript>")[:2]   # the first spare row is the creators'
    rows = re.findall(r'<div class="creator-row".*?</div>', shown, re.S)
    assert len(rows) == 2   # just the two people: no blank rows
    assert 'value="Mori"' in rows[0] and rows[0].count("checked") == 2 and "Role (optional):" in rows[0]
    assert 'value="Asdf"' in rows[1] and "checked" not in rows[1]
    # without JavaScript there's no Add button, so one blank row hides in <noscript>
    assert 'name="creator_name" value=""' in spare and 'value="2"' in spare.split("</noscript>")[0]
    # a role the form doesn't manage, as an import might add
    conn = a.db()
    with conn:
        conn.execute("INSERT INTO creator(name) VALUES ('Kei')")
        conn.execute("INSERT INTO work_creator SELECT ?, id, 'translator' FROM creator WHERE name = 'Kei'", (wid,))
    conn.close()
    # untick Mori's artist role; a tick on a blank row is ignored
    r = a.client.post(f"/works/{wid}/edit", data={"title": "Test Manga", "format_code": "manga",
                      "length_unit": "chapter", "creator_name": ["Mori", "Asdf", ""],
                      "creator_author": ["0"], "creator_artist": ["2"]}, content_type="multipart/form-data")
    assert r.status_code == 302
    assert [tuple(r) for r in creator_roles(a, wid)] == [
        ("Asdf", "unspecified"), ("Kei", "translator"), ("Mori", "author")]

def test_new_work_form_has_one_blank_creator_row():
    a = App()
    shown = a.client.get("/works/new").get_data(as_text=True).split("<noscript>")[0]
    rows = re.findall(r'<div class="creator-row".*?</div>', shown, re.S)
    assert len(rows) == 1 and 'value=""' in rows[0]

def test_creators_kept_when_form_has_errors():
    a = App()
    r = a.client.post("/works/new", data={"title": "", "format_code": "manga", "status": "tbr",
                                          "creator_name": ["Mori"], "creator_artist": ["0"]})
    rows = re.findall(r'<div class="creator-row".*?</div>', r.get_data(as_text=True), re.S)
    assert r.status_code == 400 and 'value="Mori"' in rows[0] and rows[0].count("checked") == 1

def test_alternate_titles_one_per_row():
    a = App()
    wid = a.add_work(alt_title=["Ranta", "Ranta no Hi"])
    form = a.client.get(f"/works/{wid}/edit").get_data(as_text=True)
    shown, spare = form.split('<legend>Alternate titles</legend>')[1].split("<noscript>")[:2]
    assert re.findall(r'name="alt_title" value="([^"]*)"', shown) == ["Ranta", "Ranta no Hi"]
    assert 'name="alt_title" value=""' in spare   # one blank row for adding without JavaScript
    assert a.client.get("/works/new").get_data(as_text=True).count('name="alt_title" value=""') == 2   # row + spare

def work_dates(a, wid):
    conn = a.db()
    try:
        return tuple(conn.execute("SELECT pub_start, pub_end FROM work WHERE id = ?", (wid,)).fetchone())
    finally:
        conn.close()

def test_publication_dates_from_year_and_month():
    a = App()
    wid = a.add_work(pub_start_year="2019", pub_start_month="04", pub_end_year="2023")
    assert work_dates(a, wid) == ("2019-04", "2023")
    form = a.client.get(f"/works/{wid}/edit").get_data(as_text=True)
    assert 'name="pub_start_year" value="2019"' in form and '<option value="04" selected>April' in form
    # Started April 2019, Ended 2019 is fine: only the year is known for the end
    a.client.post(f"/works/{wid}/edit", data={"title": "T", "format_code": "manga", "pub_start_year": "2019",
                  "pub_start_month": "04", "pub_end_year": "2019"}, content_type="multipart/form-data")
    assert work_dates(a, wid) == ("2019-04", "2019")

def test_publication_date_mistakes_rejected():
    a = App()
    for data, message in [({"pub_start_month": "04"}, "add a year to go with the month"),
                          ({"pub_start_year": "19"}, "four digits"),
                          ({"pub_start_year": "2020", "pub_end_year": "2019"}, "Ended can&#39;t be before Started"),
                          ({"pub_start_year": "2020", "pub_start_month": "05",
                            "pub_end_year": "2020", "pub_end_month": "03"}, "Ended can&#39;t be before Started")]:
        r = a.client.post("/works/new", data={"title": "x", "format_code": "manga", "status": "tbr", **data})
        assert r.status_code == 400 and message in r.get_data(as_text=True), data
    assert a.one("SELECT COUNT(*) FROM work") == 0

def test_old_free_text_publication_date_kept():
    a = App()
    wid = a.add_work()
    conn = a.db()
    with conn:
        conn.execute("UPDATE work SET pub_start = 'Spring 2019' WHERE id = ?", (wid,))
    conn.close()
    form = a.client.get(f"/works/{wid}/edit").get_data(as_text=True)
    assert "Saved as “Spring 2019”" in form
    legacy = re.search(r'name="pub_start_legacy" value="([^"]*)"', form).group(1)
    base = {"title": "T", "format_code": "manga", "pub_start_legacy": legacy}
    a.client.post(f"/works/{wid}/edit", data=base, content_type="multipart/form-data")
    assert work_dates(a, wid) == ("Spring 2019", None)   # saving without a year keeps it
    a.client.post(f"/works/{wid}/edit", data={**base, "pub_start_year": "2019"}, content_type="multipart/form-data")
    assert work_dates(a, wid) == ("2019", None)          # picking a year replaces it

def test_work_page_year_and_open_sections():
    a = App()
    wid = a.add_work(title="Wolf in the House", pub_start_year="2017", pub_start_month="06")
    page = a.client.get(f"/works/{wid}").get_data(as_text=True)
    assert '<h1>Wolf in the House <span class="work-year">(2017)</span></h1>' in page
    assert page.count('<details class="panel" open>') == 3   # notes, review and details
    assert "Reading status" in page
    no_year = a.add_work(title="Undated")
    assert "<h1>Undated</h1>" in a.client.get(f"/works/{no_year}").get_data(as_text=True)

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
    first = a.add_work(title="First", source_link=["https://anilist.co/manga/555"])
    r = a.client.post("/works/new", data={"title": "Second", "format_code": "manga", "status": "tbr",
                                          "source_link": ["anilist.co/manga/555"]})
    body = r.get_data(as_text=True)
    assert r.status_code == 400 and f"/works/{first}" in body and "already used by" in body
    assert a.one("SELECT COUNT(*) FROM work") == 1

def test_source_links_recognised_by_site():
    a = App()
    wid = a.add_work(source_link=["https://archiveofourown.org/works/42/chapters/7", "",
                                  "https://www.mangaupdates.com/series/pm5ww2j/lantern"])
    conn = a.db()
    try:
        assert dict(conn.execute("SELECT source_code, external_id FROM work_source_id WHERE work_id = ?",
                                 (wid,)).fetchall()) == {"ao3": "42", "mangaupdates": "pm5ww2j"}
    finally:
        conn.close()
    # the edit form shows them as links, in site order
    form = a.client.get(f"/works/{wid}/edit").get_data(as_text=True)
    assert re.findall(r'name="source_link" value="([^"]+)"', form) == [
        "https://www.mangaupdates.com/series/pm5ww2j", "https://archiveofourown.org/works/42"]

def test_bad_source_links_rejected():
    a = App()
    for links, message in [(["https://example.com/works/1"], "isn&#39;t a link to a work on AniList, MangaUpdates or AO3"),
                           (["555"], "Paste the whole link"),   # a bare number could be from any site
                           (["https://anilist.co/manga/1", "https://anilist.co/manga/2"], "only have one AniList link")]:
        r = a.client.post("/works/new", data={"title": "x", "format_code": "manga", "status": "tbr", "source_link": links})
        body = r.get_data(as_text=True)
        assert r.status_code == 400 and message in body, links
        assert all(f'value="{link}"' in body for link in links)   # what was typed is kept
    # the same link twice is just a repeat, not a conflict
    a.add_work(source_link=["https://anilist.co/manga/1", "anilist.co/manga/1"])
    assert a.one("SELECT COUNT(*) FROM work_source_id") == 1

def work_publisher_names(a, wid):
    conn = a.db()
    try:
        return [r[0] for r in conn.execute("""SELECT p.name FROM work_publisher wp JOIN publisher p ON p.id = wp.publisher_id
                                              WHERE wp.work_id = ? ORDER BY wp.position""", (wid,))]
    finally:
        conn.close()

def test_several_publishers():
    a = App()
    wid = a.add_work(publisher=["Kodansha", "", "Yen Press", "kodansha"])
    assert work_publisher_names(a, wid) == ["Kodansha", "Yen Press"]   # in order, repeats dropped
    page = a.client.get(f"/works/{wid}").get_data(as_text=True)
    assert "<dt>Publishers</dt><dd>Kodansha<br>Yen Press</dd>" in page
    form = a.client.get(f"/works/{wid}/edit").get_data(as_text=True)
    assert re.findall(r'name="publisher" value="([^"]+)"', form) == ["Kodansha", "Yen Press"]
    # a second work shares the publisher, whatever the capitals
    other = a.add_work(publisher=["KODANSHA"])
    assert work_publisher_names(a, other) == ["Kodansha"] and a.one("SELECT COUNT(*) FROM publisher") == 2
    # reordering and removing
    a.client.post(f"/works/{wid}/edit", data={"title": "T", "format_code": "manga", "publisher": ["Yen Press"]},
                  content_type="multipart/form-data")
    assert work_publisher_names(a, wid) == ["Yen Press"]
    assert "<dt>Publisher</dt><dd>Yen Press</dd>" in a.client.get(f"/works/{wid}").get_data(as_text=True)

def test_required_fields_marked():
    a = App()
    form = a.client.get("/works/new").get_data(as_text=True)
    assert 'Title <span class="required" aria-hidden="true">*</span>' in form
    assert 'Format <span class="required" aria-hidden="true">*</span>' in form
    assert form.count('class="required"') == 3   # the two fields and the key

def test_not_an_image_rejected():
    a = App()
    r = a.client.post("/works/new", data={"title": "x", "format_code": "manga", "status": "tbr",
                                          "cover": (io.BytesIO(b"not an image"), "cover.png")},
                      content_type="multipart/form-data")
    assert r.status_code == 400 and "an image the journal can read" in r.get_data(as_text=True)
    assert a.one("SELECT COUNT(*) FROM work") == 0

def test_edit_work_and_unit_change_clears_progress():
    a = App()
    wid = a.add_work(source_link=["https://anilist.co/manga/1"])
    a.post_entry(wid, body="hi", progress="12")
    r = a.client.post(f"/works/{wid}/edit", data={"title": "Renamed", "format_code": "manga",
                                                  "length_unit": "volume", "source_link": ["https://anilist.co/manga/1"]},
                      content_type="multipart/form-data", follow_redirects=True)
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and "Renamed" in body and "cleared" in body
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) is None
    assert a.one("SELECT progress_valid FROM journal_entry_progress WHERE work_id = ? AND progress_value IS NOT NULL", (wid,)) == 0
    assert a.one("SELECT external_id FROM work_source_id WHERE work_id = ?", (wid,)) == "1"   # own ID isn't a conflict

def test_remove_cover_button():
    a = App()
    wid = a.add_work(cover=(png(), "cover.png"))
    form = a.client.get(f"/works/{wid}/edit").get_data(as_text=True)
    assert 'id="remove-cover" name="remove_cover"' in form and 'for="remove-cover" class="remove-cover"' in form
    edit = {"title": "Test Manga", "format_code": "manga", "length_unit": "chapter"}
    # a new upload replaces the cover without ticking remove
    a.client.post(f"/works/{wid}/edit", data={**edit, "cover": (png((0, 0, 255)), "new.png")},
                  content_type="multipart/form-data")
    assert a.one("SELECT COUNT(*) FROM image") == 2
    new = a.one("SELECT cover_image_id FROM work WHERE id = ?", (wid,))
    assert new == a.one("SELECT max(id) FROM image")
    a.client.post(f"/works/{wid}/edit", data={**edit, "remove_cover": "1"}, content_type="multipart/form-data")
    assert a.one("SELECT cover_image_id FROM work WHERE id = ?", (wid,)) is None
    assert 'id="remove-cover"' not in a.client.get(f"/works/{wid}/edit").get_data(as_text=True)

def test_delete_work():
    a = App()
    wid = a.add_work()
    a.post_entry(wid, body="x")
    assert a.client.post(f"/works/{wid}/delete").status_code == 302
    assert a.one("SELECT COUNT(*) FROM work") == 0
    assert a.one("SELECT COUNT(*) FROM journal_entry") == 0
    assert a.one("SELECT COUNT(*) FROM status_event") == 0

# ---------------------------------------------------------------- journal

def test_post_entry_with_images_and_progress():
    a = App()
    wid = a.add_work()
    a.post_entry(wid, body="Chapter **one**", progress="1", images=[(png(), "a.png"), (png((0, 0, 255)), "b.png")])
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) == 1
    assert a.one("SELECT COUNT(*) FROM journal_entry_image") == 2
    page = a.client.get(f"/works/{wid}").get_data(as_text=True)
    assert "<strong>one</strong>" in page and "Ch 1" in page

def test_same_image_stored_once():
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

def test_bad_image_posts_nothing():
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
    # raising progress in an edit doesn't move the work either: the journal is a log
    a.client.post(f"/entries/{eid}/edit", data={"body": "typo", "progress": "130"}, content_type="multipart/form-data")
    assert a.one("SELECT progress_value FROM journal_entry WHERE id = ?", (eid,)) == 130
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) == 0
    # removing the image and adding another
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

def entry_image_ids(a, eid):
    conn = a.db()
    try:
        return [r[0] for r in conn.execute(
            "SELECT image_id FROM journal_entry_image WHERE entry_id = ? ORDER BY position", (eid,))]
    finally:
        conn.close()

def test_edit_entry_reorders_images():
    a = App()
    wid = a.add_work()
    a.post_entry(wid, body="x", images=[(png((1, 1, 1)), "a.png"), (png((2, 2, 2)), "b.png"), (png((3, 3, 3)), "c.png")])
    eid = a.one("SELECT id FROM journal_entry WHERE kind = 'note'")
    first, second, third = entry_image_ids(a, eid)
    page = a.client.get(f"/entries/{eid}/edit").get_data(as_text=True)
    assert re.findall(r'name="image_order" value="(\d+)"', page) == [str(first), str(second), str(third)]
    # move the last image to the front and add a new one, which goes at the end
    a.client.post(f"/entries/{eid}/edit", data={"body": "x", "image_order": [str(third), str(first), str(second)],
                                                "images": [(png((4, 4, 4)), "d.png")]}, content_type="multipart/form-data")
    order = entry_image_ids(a, eid)
    assert order[:3] == [third, first, second] and len(order) == 4
    # removing one keeps the others in order
    a.client.post(f"/entries/{eid}/edit", data={"body": "x", "image_order": [str(i) for i in order],
                                                "remove_image": str(first)}, content_type="multipart/form-data")
    assert entry_image_ids(a, eid) == [third, second, order[3]]

def test_edit_entry_page_layout():
    a = App()
    wid = a.add_work(length_total="55")
    a.post_entry(wid, body="x", progress="12")
    eid = a.one("SELECT id FROM journal_entry WHERE kind = 'note'")
    page = a.client.get(f"/entries/{eid}/edit").get_data(as_text=True)
    assert "<h1>Edit Journal Entry</h1>" in page and "of 55 chapters" in page
    assert "+ Add images" in page.split("<legend>Images</legend>")[1].split("</fieldset>")[0]   # inside the box
    assert "You can use Markdown to format your entry" in page
    # no total: a question mark instead
    other = a.add_work()
    a.post_entry(other, body="y", progress="3")
    eid = a.one("SELECT id FROM journal_entry WHERE kind = 'note' AND work_id = ?", (other,))
    assert "of ? chapters" in a.client.get(f"/entries/{eid}/edit").get_data(as_text=True)

def test_format_reference_matches_rendering():
    a = App()
    wid = a.add_work()
    page = a.client.get(f"/works/{wid}").get_data(as_text=True)
    help_box = page.split('<details class="format-help">')[1].split("</details>")[0]
    assert "<code>**bold**</code>" in help_box and "<strong>bold</strong>" in help_box
    assert "<s>strikethrough</s>" in help_box and "<hr" in help_box

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

def test_completed_fills_in_progress():
    a = App()
    wid = a.add_work(length_total="64")
    a.post_entry(wid, body="x", progress="30")
    a.client.post(f"/works/{wid}/status", data={"status": "completed"})
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) == 64
    # with no total, completing leaves progress alone
    ongoing = a.add_work(title="Ongoing")
    a.post_entry(ongoing, body="x", progress="12")
    a.client.post(f"/works/{ongoing}/status", data={"status": "completed"})
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (ongoing,)) == 12
    # adding a work as Completed fills it in too
    done = a.add_work(title="Done", status="completed", length_total="10")
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (done,)) == 10

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

def test_back_to_tbr_offers_reset():
    a = App()
    wid = a.add_work(status="reading")
    a.post_entry(wid, body="x", progress="20")
    r = a.client.post(f"/works/{wid}/status", data={"status": "tbr"})
    assert r.status_code == 200 and "Reset progress to 0" in r.get_data(as_text=True)
    assert a.one("SELECT status_code FROM work_current_status WHERE work_id = ?", (wid,)) == "reading"   # nothing yet
    a.client.post(f"/works/{wid}/status", data={"status": "tbr", "reset": "yes"})
    assert a.one("SELECT status_code FROM work_current_status WHERE work_id = ?", (wid,)) == "tbr"
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) == 0

def test_back_to_tbr_keep_progress():
    a = App()
    wid = a.add_work(status="dropped")
    a.client.post(f"/works/{wid}/progress", data={"progress": "7"})
    a.client.post(f"/works/{wid}/status", data={"status": "tbr", "reset": "no"})
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) == 7
    assert a.one("SELECT status_code FROM work_current_status WHERE work_id = ?", (wid,)) == "tbr"

def test_back_to_tbr_without_progress_no_prompt():
    a = App()
    wid = a.add_work(status="reading")
    assert a.client.post(f"/works/{wid}/status", data={"status": "tbr"}).status_code == 302
    # a reset answer sent for a change that doesn't offer one is ignored
    a.client.post(f"/works/{wid}/progress", data={"progress": "5"})
    a.client.post(f"/works/{wid}/status", data={"status": "paused", "reset": "yes"})
    assert a.one("SELECT progress_current FROM work WHERE id = ?", (wid,)) == 5

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

def test_empty_library_message():
    a = App()
    page = a.client.get("/").get_data(as_text=True)
    assert "You don't have any works in your journal. Use the Add Work button to add one." in page
    assert ">Add Work</a>" in page
    assert "Restoring or moving your journal" in page

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

def test_footer_version_links_and_credit():
    a = App()
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)
    footer = re.search(r'<footer class="site">(.*?)</footer>', a.client.get("/").get_data(as_text=True), re.S).group(1)
    assert f'Reading Journal {VERSION} • <a href="/changelog">Changelog</a>' in footer
    for href in ('href="/"', 'href="/works/new"',
                 'href="https://creativecommons.org/licenses/by/4.0/"'):
        assert href in footer, href
    assert "Notebook logo by EmojiOne, recolored, licensed under" in footer   # CC BY: credit, changes, licence link

def test_changelog_page():
    a = App()
    r = a.client.get("/changelog")
    page = r.get_data(as_text=True)
    assert r.status_code == 200 and "<h1>Changelog</h1>" in page and "<h2>0.1.0" in page

def test_changelog_hides_empty_unreleased():
    from journal.views import hide_empty_unreleased
    empty = "# Changelog\n\n## Unreleased\n\n## 0.2.0 (2027-01-01)\n\n- Thing\n"
    assert hide_empty_unreleased(empty) == "# Changelog\n\n## 0.2.0 (2027-01-01)\n\n- Thing\n"
    assert hide_empty_unreleased("# Changelog\n\n## Unreleased\n") == "# Changelog\n\n"
    filled = "# Changelog\n\n## Unreleased\n\n- New thing\n\n## 0.2.0 (2027-01-01)\n"
    assert hide_empty_unreleased(filled) == filled

def test_logo_served():
    a = App()
    r = a.client.get("/static/emojione-notebook.svg")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml"
    r.close()

# ---------------------------------------------------------------- database upgrades

@contextmanager
def schema_version(target, migrations):
    """Pretend the app's schema is at `target`, with these upgrade steps."""
    saved = dbmod.SCHEMA_VERSION, dbmod.MIGRATIONS
    dbmod.SCHEMA_VERSION, dbmod.MIGRATIONS = target, migrations
    try:
        yield
    finally:
        dbmod.SCHEMA_VERSION, dbmod.MIGRATIONS = saved

def refused(a):
    """Start-up check that must fail; returns the message the person would see."""
    try:
        dbmod.init_db(a.app.config["DB_PATH"])
    except dbmod.SetupError as e:
        return str(e)
    raise AssertionError("the journal opened a database it should have refused")

def backups(a):
    return sorted(Path(a.tmp.name, "backups").glob("*.db"))

def add_shelf(conn):
    conn.execute("ALTER TABLE work ADD COLUMN shelf TEXT")

def has_shelf(a):
    return a.one("SELECT COUNT(*) FROM pragma_table_info('work') WHERE name = 'shelf'") == 1

# The safety tests below pretend the app has moved past the real current version V.
V = dbmod.SCHEMA_VERSION

def test_upgrade_backs_up_then_migrates():
    a = App()
    a.add_work(title="Before")
    with schema_version(V + 1, {V: add_shelf}):
        dbmod.init_db(a.app.config["DB_PATH"])
    assert a.one("PRAGMA user_version") == V + 1 and has_shelf(a)
    [backup] = backups(a)
    old = connect(backup)
    try:
        assert old.execute("PRAGMA user_version").fetchone()[0] == V
        assert old.execute("SELECT title FROM work").fetchone()[0] == "Before"
        assert old.execute("SELECT COUNT(*) FROM pragma_table_info('work') WHERE name = 'shelf'").fetchone()[0] == 0
    finally:
        old.close()

def test_upgrade_runs_every_step_in_order():
    a = App()
    a.add_work()
    steps = {V: add_shelf, V + 1: lambda c: c.execute("UPDATE work SET shelf = 'top'")}
    with schema_version(V + 2, steps):
        dbmod.init_db(a.app.config["DB_PATH"])
    assert a.one("PRAGMA user_version") == V + 2
    assert a.one("SELECT shelf FROM work") == "top"
    assert len(backups(a)) == 1   # one backup per upgrade, not per step

def test_failed_upgrade_changes_nothing():
    a = App()
    def broken(conn):
        add_shelf(conn)
        raise ValueError("step went wrong")
    with schema_version(V + 1, {V: broken}):
        msg = refused(a)
    [backup] = backups(a)
    assert "nothing was changed" in msg and "step went wrong" in msg and str(backup) in msg
    assert a.one("PRAGMA user_version") == V and not has_shelf(a)
    assert a.one("PRAGMA foreign_keys") == 1

def test_upgrade_that_breaks_links_is_undone():
    a = App()
    orphan = lambda c: c.execute("INSERT INTO work_creator VALUES (999, 999, 'author')")
    with schema_version(V + 1, {V: orphan}):
        msg = refused(a)
    assert "broken links" in msg
    assert a.one("PRAGMA user_version") == V
    assert a.one("SELECT COUNT(*) FROM work_creator") == 0

def test_newer_database_refused():
    a = App()
    conn = a.db()
    try:
        conn.execute(f"PRAGMA user_version = {V + 1}")
    finally:
        conn.close()
    msg = refused(a)
    assert "newer version" in msg
    assert a.one("PRAGMA user_version") == V + 1
    assert backups(a) == []

def test_missing_upgrade_step_refused():
    a = App()
    with schema_version(V + 2, {V: add_shelf}):   # no step from V + 1 to V + 2
        msg = refused(a)
    assert f"no upgrade from version {V + 1}" in msg
    assert a.one("PRAGMA user_version") == V and not has_shelf(a)
    assert backups(a) == []

def test_upgrade_from_v2_journal():
    def old_data(conn):
        conn.execute("INSERT INTO work(id, title, format_code) VALUES (1, 'Old Work', 'manga')")
        conn.execute("INSERT INTO journal_entry(work_id, body_md, progress_value, progress_unit) VALUES (1, 'old', 64, 'chapter')")
    a = App(old_schema="schema_v2.sql", before=old_data)   # starting the app upgrades it
    assert a.one("PRAGMA user_version") == V and len(backups(a)) == 1
    assert a.one("SELECT progress_current FROM work WHERE id = 1") == 64   # data kept
    # the upgraded journal has the same tables, views and triggers as a brand-new one
    objects = "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY 1, 2"
    fresh = App()
    conn, new_conn = a.db(), fresh.db()
    try:
        assert conn.execute(objects).fetchall() == new_conn.execute(objects).fetchall()
    finally:
        conn.close()
        new_conn.close()
    # v3 rule: correcting an old entry during a reread leaves progress alone
    a.client.post("/works/1/progress", data={"progress": "0"})
    eid = a.one("SELECT id FROM journal_entry WHERE body_md = 'old'")
    a.client.post(f"/entries/{eid}/edit", data={"body": "old", "progress": "65"}, content_type="multipart/form-data")
    assert a.one("SELECT progress_current FROM work WHERE id = 1") == 0

def test_upgrade_from_v3_journal_moves_publishers():
    def old_data(conn):
        conn.executemany("INSERT INTO work(id, title, format_code, publisher) VALUES (?, ?, 'manga', ?)",
                         [(1, "One", "Kodansha"), (2, "Two", " kodansha "), (3, "Three", None), (4, "Four", "")])
    a = App(old_schema="schema_v3.sql", before=old_data)
    assert a.one("PRAGMA user_version") == V and len(backups(a)) == 1
    assert work_publisher_names(a, 1) == ["Kodansha"] and work_publisher_names(a, 2) == ["Kodansha"]
    assert work_publisher_names(a, 3) == [] and work_publisher_names(a, 4) == []
    assert a.one("SELECT COUNT(*) FROM publisher") == 1
    # same tables, views, triggers and columns as a brand-new journal
    objects = "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY 1, 2"
    columns = "SELECT name, type, \"notnull\", dflt_value, pk FROM pragma_table_info(?)"
    fresh = App()
    conn, new_conn = a.db(), fresh.db()
    try:
        assert conn.execute(objects).fetchall() == new_conn.execute(objects).fetchall()
        for table in ("work", "publisher", "work_publisher"):
            assert conn.execute(columns, (table,)).fetchall() == new_conn.execute(columns, (table,)).fetchall(), table
    finally:
        conn.close()
        new_conn.close()
    assert "<dt>Publisher</dt><dd>Kodansha</dd>" in a.client.get("/works/2").get_data(as_text=True)

def test_up_to_date_database_not_backed_up():
    a = App()
    dbmod.init_db(a.app.config["DB_PATH"])
    assert backups(a) == []


# ---------------------------------------------------------------- dev mode

def test_dev_mode_uses_demo_journal():
    import run
    data_dir, port = run.dev_settings({})
    assert data_dir.name == "journal-demo" and port == 8420
    assert run.dev_settings({"JOURNAL_DATA": "elsewhere"})[0] == Path("elsewhere")

def test_dev_mode_rereads_templates():
    import run
    with tempfile.TemporaryDirectory() as tmp:
        assert run.dev_app(tmp).jinja_env.auto_reload

def test_dev_mode_shows_error_instead_of_stopping():
    import run
    with tempfile.TemporaryDirectory() as tmp:
        not_a_folder = Path(tmp) / "file.txt"
        not_a_folder.write_text("x")
        app = run.dev_app(not_a_folder)   # create_app can't make a data folder here
        statuses = []
        body = b"".join(app({}, lambda status, headers: statuses.append(status)))
    assert statuses[0].startswith("500") and b"couldn't start" in body


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
