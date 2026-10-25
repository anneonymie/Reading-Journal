"""Tests for schema.sql. Run with:  python3 test_schema.py

Each test builds a fresh in-memory database from schema.sql and checks one
rule from the requirements. Prints PASS/FAIL per test and exits non-zero
if anything fails.
"""
import sqlite3
import sys
from pathlib import Path

SCHEMA = (Path(__file__).parent / "schema.sql").read_text()


def new_db():
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("INSERT INTO work(id, title, format_code) VALUES (1, 'Manga A', 'manga')")
    db.execute("INSERT INTO work(id, title, format_code, length_unit) VALUES (2, 'Novel B', 'light_novel', 'volume')")
    return db


def rejects(db, sql, args=()):
    try:
        db.execute(sql, args)
    except sqlite3.Error:
        return True
    return False


def one(db, sql, args=()):
    row = db.execute(sql, args).fetchone()
    return row[0] if row else None


def add_entry(db, work_id=1, body="x", value=None, unit=None, **kw):
    cols = ["work_id", "body_md", "progress_value", "progress_unit"] + list(kw)
    vals = [work_id, body, value, unit] + list(kw.values())
    cur = db.execute(
        f"INSERT INTO journal_entry({', '.join(cols)}) VALUES ({', '.join('?' * len(vals))})", vals
    )
    return cur.lastrowid


# ---------------------------------------------------------------- works

def test_sqlite_version():
    assert sqlite3.sqlite_version_info >= (3, 43), sqlite3.sqlite_version

def test_format_must_be_from_list():
    db = new_db()
    assert rejects(db, "INSERT INTO work(title, format_code) VALUES ('x', 'scroll')")

def test_unit_must_be_from_list():
    db = new_db()
    assert rejects(db, "INSERT INTO work(title, format_code, length_unit) VALUES ('x','manga','furlong')")

def test_length_total_optional_but_positive():
    db = new_db()
    db.execute("UPDATE work SET length_total = NULL WHERE id = 1")
    assert rejects(db, "UPDATE work SET length_total = 0 WHERE id = 1")

def test_rating_scale():
    db = new_db()
    for r in [i / 10 for i in range(101)]:          # every value 0.0..10.0
        db.execute("UPDATE work SET rating = ? WHERE id = 1", (r,))
    for bad in (8.55, -0.1, 10.1):
        assert rejects(db, "UPDATE work SET rating = ? WHERE id = 1", (bad,)), bad

def test_updated_at_touch():
    db = new_db()
    db.execute("UPDATE work SET updated_at = '2000-01-01T00:00:00Z' WHERE id = 1")
    db.execute("UPDATE work SET title = 'Renamed' WHERE id = 1")
    assert one(db, "SELECT updated_at FROM work WHERE id = 1") != "2000-01-01T00:00:00Z"

def test_source_ids():
    db = new_db()
    db.execute("INSERT INTO work_source_id VALUES (1, 'anilist', '123')")
    db.execute("INSERT INTO work_source_id VALUES (1, 'mangaupdates', 'abc')")   # several sources OK
    db.execute("INSERT INTO work_source_id VALUES (2, 'mangaupdates', '123')")   # same number, other source OK
    assert rejects(db, "INSERT INTO work_source_id VALUES (2, 'anilist', '123')")  # ID on two works
    assert rejects(db, "INSERT INTO work_source_id VALUES (1, 'anilist', '999')")  # two IDs, one source
    assert rejects(db, "INSERT INTO work_source_id VALUES (1, 'goodreads', '1')")  # unknown source

def test_relations():
    db = new_db()
    assert rejects(db, "INSERT INTO work_relation(from_work_id, to_work_id, relation_code) VALUES (1, 1, 'prequel_of')")
    db.execute("INSERT INTO work_relation(from_work_id, to_work_id, relation_code) VALUES (1, 2, 'adaptation_of')")
    db.execute("INSERT INTO work_relation(from_work_id, to_work_id, relation_code) VALUES (2, 1, 'prequel_of')")
    db.execute("INSERT INTO work_relation(from_work_id, to_work_id, relation_code) VALUES (1, 2, 'same_universe')")
    assert rejects(db, "INSERT INTO work_relation(from_work_id, to_work_id, relation_code) VALUES (2, 1, 'same_universe')")

def test_custom_choice_field():
    db = new_db()
    db.execute("INSERT INTO custom_field(id, name, value_type) VALUES (1, 'Platform', 'choice')")
    db.execute("INSERT INTO custom_field_choice VALUES (1, 'Kindle'), (1, 'Webtoon')")
    db.execute("INSERT INTO work_custom_value VALUES (1, 1, 'Kindle')")
    assert rejects(db, "INSERT INTO work_custom_value VALUES (2, 1, 'Paper')")
    assert rejects(db, "UPDATE work_custom_value SET value = 'Paper' WHERE work_id = 1")
    db.execute("INSERT INTO custom_field(id, name, value_type) VALUES (2, 'Read on', 'text')")
    db.execute("INSERT INTO work_custom_value VALUES (1, 2, 'anything')")

# ---------------------------------------------------------------- progress

def test_progress_moves_forward_on_create():
    db = new_db()
    add_entry(db, value=5, unit="chapter")
    assert one(db, "SELECT progress_current FROM work WHERE id = 1") == 5

def test_progress_never_moves_backward():
    db = new_db()
    add_entry(db, value=10, unit="chapter")
    add_entry(db, value=3, unit="chapter")
    assert one(db, "SELECT progress_current FROM work WHERE id = 1") == 10

def test_progress_edit_does_nothing():
    db = new_db()
    add_entry(db, value=5, unit="chapter")
    e = add_entry(db, value=2, unit="chapter")
    db.execute("UPDATE journal_entry SET progress_value = 22 WHERE id = ?", (e,))   # editing up: no change
    assert one(db, "SELECT progress_current FROM work WHERE id = 1") == 5
    db.execute("UPDATE journal_entry SET progress_value = 1 WHERE id = ?", (e,))    # editing down: no change
    assert one(db, "SELECT progress_current FROM work WHERE id = 1") == 5

def test_progress_edit_during_reread_does_nothing():
    db = new_db()
    e = add_entry(db, value=64, unit="chapter")
    db.execute("UPDATE work SET progress_current = 0 WHERE id = 1")      # reread reset
    db.execute("UPDATE journal_entry SET progress_value = 65 WHERE id = ?", (e,))   # correcting an old entry
    assert one(db, "SELECT progress_current FROM work WHERE id = 1") == 0

def test_progress_resave_without_change_does_nothing():
    db = new_db()
    e = add_entry(db, value=120, unit="chapter")
    db.execute("UPDATE work SET progress_current = 0 WHERE id = 1")      # reread reset
    db.execute("UPDATE journal_entry SET body_md = 'typo fixed', progress_value = 120, progress_unit = 'chapter' WHERE id = ?", (e,))
    assert one(db, "SELECT progress_current FROM work WHERE id = 1") == 0

def test_progress_delete_does_nothing():
    db = new_db()
    e = add_entry(db, value=22, unit="chapter")
    db.execute("DELETE FROM journal_entry WHERE id = ?", (e,))
    assert one(db, "SELECT progress_current FROM work WHERE id = 1") == 22

def test_progress_manual_is_kept():
    db = new_db()
    db.execute("UPDATE work SET progress_current = 0 WHERE id = 1")   # reread reset
    add_entry(db, value=4, unit="chapter")
    assert one(db, "SELECT progress_current FROM work WHERE id = 1") == 4

def test_progress_without_total_length():
    db = new_db()   # work 1 has no length_total
    add_entry(db, value=7, unit="chapter")
    assert one(db, "SELECT progress_current FROM work WHERE id = 1") == 7

def test_mismatched_unit_ignored_and_flagged():
    db = new_db()
    add_entry(db, value=3, unit="chapter")
    e = add_entry(db, value=99, unit="volume")
    assert one(db, "SELECT progress_current FROM work WHERE id = 1") == 3
    assert one(db, "SELECT progress_valid FROM journal_entry_progress WHERE entry_id = ?", (e,)) == 0

def test_unit_change_keeps_entries():
    db = new_db()
    e = add_entry(db, value=12, unit="chapter")
    db.execute("UPDATE work SET length_unit = 'volume' WHERE id = 1")
    assert one(db, "SELECT progress_valid FROM journal_entry_progress WHERE entry_id = ?", (e,)) == 0
    db.execute("UPDATE work SET length_unit = 'chapter' WHERE id = 1")
    assert one(db, "SELECT progress_valid FROM journal_entry_progress WHERE entry_id = ?", (e,)) == 1

def test_progress_needs_value_and_unit_together():
    db = new_db()
    assert rejects(db, "INSERT INTO journal_entry(work_id, progress_value) VALUES (1, 4)")
    assert rejects(db, "INSERT INTO journal_entry(work_id, progress_unit) VALUES (1, 'chapter')")

def test_entry_without_progress():
    db = new_db()
    add_entry(db, body="just thoughts")
    assert one(db, "SELECT progress_current FROM work WHERE id = 1") is None

# ---------------------------------------------------------------- status

def test_current_status_is_latest():
    db = new_db()
    db.execute("INSERT INTO status_event(work_id, status_code, changed_at) VALUES (1, 'reading',   '2026-01-01T00:00:00Z')")
    db.execute("INSERT INTO status_event(work_id, status_code, changed_at) VALUES (1, 'completed', '2026-02-01T00:00:00Z')")
    db.execute("INSERT INTO status_event(work_id, status_code, changed_at) VALUES (1, 'tbr',       '2025-12-01T00:00:00Z')")  # backdated
    assert one(db, "SELECT status_code FROM work_current_status WHERE work_id = 1") == "completed"
    assert one(db, "SELECT status_code FROM work_current_status WHERE work_id = 2") is None

def test_rereads_counted():
    db = new_db()
    for i, s in enumerate(["reading", "completed", "reading", "completed"]):
        db.execute("INSERT INTO status_event(work_id, status_code, changed_at) VALUES (1, ?, ?)",
                   (s, f"2026-0{i+1}-01T00:00:00Z"))
    assert one(db, "SELECT completions FROM work_completion_count WHERE work_id = 1") == 2

def test_timestamp_format_enforced():
    db = new_db()
    for bad in ("2026-01-01 00:00:00", "2026-01-01T00:00:00.123Z", "2026-01-01T00:00:00+02:00", "Jan 1"):
        assert rejects(db, "INSERT INTO status_event(work_id, status_code, changed_at) VALUES (1, 'tbr', ?)", (bad,)), bad
        assert rejects(db, "INSERT INTO journal_entry(work_id, posted_at) VALUES (1, ?)", (bad,)), bad

def test_status_entry_is_only_a_log():
    db = new_db()
    db.execute("INSERT INTO status_event(id, work_id, status_code) VALUES (1, 1, 'reading')")
    db.execute("INSERT INTO status_event(id, work_id, status_code, changed_at) VALUES (2, 1, 'completed', '2099-01-01T00:00:00Z')")
    e = add_entry(db, body=None, kind="status", status_event_id=2, status_from="reading", status_to="completed")
    db.execute("DELETE FROM journal_entry WHERE id = ?", (e,))
    assert one(db, "SELECT status_code FROM work_current_status WHERE work_id = 1") == "completed"
    assert one(db, "SELECT COUNT(*) FROM status_event") == 2

def test_deleting_status_history_keeps_entry():
    db = new_db()
    db.execute("INSERT INTO status_event(id, work_id, status_code) VALUES (1, 1, 'completed')")
    e = add_entry(db, body=None, kind="status", status_event_id=1, status_from="reading", status_to="completed")
    db.execute("DELETE FROM status_event WHERE id = 1")
    row = db.execute("SELECT status_event_id, status_to FROM journal_entry WHERE id = ?", (e,)).fetchone()
    assert row == (None, "completed")

def test_status_fields_only_on_status_entries():
    db = new_db()
    assert rejects(db, "INSERT INTO journal_entry(work_id, status_to) VALUES (1, 'tbr')")
    assert rejects(db, "INSERT INTO journal_entry(work_id, kind) VALUES (1, 'status')")   # status entry needs status_to

# ---------------------------------------------------------------- journal

def test_journal_search_follows_edits_and_deletes():
    db = new_db()
    e = add_entry(db, body="the ||twist|| in chapter five")
    q = "SELECT rowid FROM journal_search WHERE journal_search MATCH ?"
    assert db.execute(q, ("twist",)).fetchall() == [(e,)]
    db.execute("UPDATE journal_entry SET body_md = 'nothing here' WHERE id = ?", (e,))
    assert db.execute(q, ("twist",)).fetchall() == []
    db.execute("DELETE FROM journal_entry WHERE id = ?", (e,))
    assert db.execute(q, ("nothing",)).fetchall() == []

def test_import_never_duplicates():
    db = new_db()
    add_entry(db, import_source="discord", import_ref="m1")
    assert rejects(db, "INSERT INTO journal_entry(work_id, import_source, import_ref) VALUES (1, 'discord', 'm1')")
    add_entry(db)    # hand-written entries (no import ref) are unlimited
    add_entry(db)

def test_one_journal_per_work_and_cascade():
    db = new_db()
    add_entry(db, work_id=1)
    assert rejects(db, "INSERT INTO journal_entry(work_id) VALUES (999)")   # no orphan entries
    db.execute("DELETE FROM work WHERE id = 1")
    assert one(db, "SELECT COUNT(*) FROM journal_entry") == 0

# ---------------------------------------------------------------- images

def test_image_paths_and_dedupe():
    db = new_db()
    db.execute("INSERT INTO image(file_path, sha256, mime_type) VALUES ('images/ab/a.png', 'h1', 'image/png')")
    assert rejects(db, "INSERT INTO image(file_path, sha256, mime_type) VALUES ('images/b.png', 'h1', 'image/png')")
    for bad in ("/abs/a.png", "../a.png", "images\\a.png", "C:/a.png", ""):
        assert rejects(db, "INSERT INTO image(file_path, sha256, mime_type) VALUES (?, ?, 'image/png')", (bad, bad + "h")), bad

def test_emoji_image_protected():
    db = new_db()
    db.execute("INSERT INTO image(id, file_path, sha256, mime_type) VALUES (1, 'images/e.png', 'h', 'image/png')")
    db.execute("INSERT INTO custom_emoji VALUES ('blush_big', 1, 'happy shy')")
    assert rejects(db, "DELETE FROM image WHERE id = 1")
    assert rejects(db, "INSERT INTO custom_emoji VALUES ('Blush', 1, NULL)")
    assert rejects(db, "INSERT INTO custom_emoji VALUES ('', 1, NULL)")

# ---------------------------------------------------------------- tags

def test_shared_tag_pool():
    db = new_db()
    db.execute("INSERT INTO tag(id, name) VALUES (10, 'Childhood')")
    db.execute("INSERT INTO image(id, file_path, sha256, mime_type) VALUES (1, 'images/a.png', 'h', 'image/png')")
    db.execute("INSERT INTO image_tag VALUES (1, 10)")
    db.execute("INSERT INTO work_tag(work_id, tag_id) VALUES (1, 10)")

def test_tag_names_case_insensitive():
    db = new_db()
    db.execute("INSERT INTO tag(name) VALUES ('Found Family')")
    assert rejects(db, "INSERT INTO tag(name) VALUES ('found family')")

def test_alias_and_name_cannot_collide():
    db = new_db()
    db.execute("INSERT INTO tag(id, name) VALUES (10, 'Enemies to Lovers')")
    db.execute("INSERT INTO tag(id, name) VALUES (11, 'Slow Burn')")
    db.execute("INSERT INTO tag_alias VALUES ('Rivals to Lovers', 10)")
    assert rejects(db, "INSERT INTO tag_alias VALUES ('enemies to LOVERS', 10)")
    assert rejects(db, "INSERT INTO tag(name) VALUES ('rivals to lovers')")
    assert rejects(db, "UPDATE tag SET name = 'Rivals to Lovers' WHERE id = 11")
    assert rejects(db, "UPDATE tag_alias SET alias = 'slow burn'")
    assert rejects(db, "INSERT INTO tag_alias VALUES ('RIVALS TO LOVERS', 11)")   # alias used once

def test_tag_search_index_stays_in_sync():
    db = new_db()
    db.execute("INSERT INTO tag(id, name) VALUES (10, 'Enemies to Lovers')")
    db.execute("INSERT INTO tag_alias VALUES ('Rivals to Lovers', 10)")
    q = "SELECT term, tag_id FROM tag_search WHERE tag_search MATCH ? ORDER BY term"
    assert db.execute(q, ("lover",)).fetchall() == [("Enemies to Lovers", 10), ("Rivals to Lovers", 10)]
    db.execute("UPDATE tag SET name = 'Enemies 2 Lovers' WHERE id = 10")
    assert db.execute(q, ('"enemies to"',)).fetchall() == []    # old name gone from the index
    assert [r[0] for r in db.execute(q, ("lover",))] == ["Enemies 2 Lovers", "Rivals to Lovers"]
    db.execute("UPDATE tag_alias SET alias = 'Frenemies' WHERE tag_id = 10")
    assert db.execute(q, ("rivals",)).fetchall() == []
    db.execute("DELETE FROM tag WHERE id = 10")
    assert one(db, "SELECT COUNT(*) FROM tag_search WHERE tag_id = 10") == 0

def test_default_cws_present_and_searchable():
    db = new_db()
    names = {r[0] for r in db.execute("SELECT t.name FROM cw_setting c JOIN tag t ON t.id = c.tag_id WHERE c.is_default = 1")}
    assert names == {"Explicit sex", "Violence", "Sexual assault"}
    assert one(db, "SELECT COUNT(*) FROM tag_search WHERE tag_search MATCH 'violen'") == 1

def test_parent_cycles_blocked():
    db = new_db()
    db.execute("INSERT INTO tag(id, name) VALUES (101, 'A'), (102, 'B'), (103, 'C')")
    db.execute("UPDATE tag SET parent_id = 101 WHERE id = 102")   # B inside A
    db.execute("UPDATE tag SET parent_id = 102 WHERE id = 103")   # C inside B
    assert rejects(db, "UPDATE tag SET parent_id = 103 WHERE id = 101")   # A inside C: loop
    assert rejects(db, "UPDATE tag SET parent_id = 102 WHERE id = 101")   # A inside B: loop
    assert rejects(db, "UPDATE tag SET parent_id = 101 WHERE id = 101")   # inside itself
    db.execute("UPDATE tag SET parent_id = NULL WHERE id = 103")          # un-nesting is fine
    db.execute("UPDATE tag SET parent_id = 103 WHERE id = 101")           # now no loop, allowed

def test_cw_inherited_from_parent_for_images_and_works():
    db = new_db()
    vid = one(db, "SELECT id FROM tag WHERE name = 'Violence'")
    db.execute("INSERT INTO tag(id, name, parent_id) VALUES (50, 'Gore', ?)", (vid,))
    db.execute("INSERT INTO tag(id, name, parent_id) VALUES (51, 'Body horror', 50)")   # grandchild
    db.execute("INSERT INTO image(id, file_path, sha256, mime_type) VALUES (1, 'images/a.png', 'h', 'image/png')")
    db.execute("INSERT INTO image_tag VALUES (1, 51)")
    db.execute("INSERT INTO work_tag(work_id, tag_id) VALUES (1, 51)")
    assert db.execute("SELECT image_id, blur, badge, cw_tags FROM image_cw").fetchall() == [(1, 1, 1, "Violence")]
    assert db.execute("SELECT work_id, cw_tags FROM work_cw").fetchall() == [(1, "Violence")]
    db.execute("UPDATE cw_setting SET blur = 0 WHERE tag_id = ?", (vid,))
    assert one(db, "SELECT blur FROM image_cw WHERE image_id = 1") == 0

def test_untagged_image_has_no_cw():
    db = new_db()
    db.execute("INSERT INTO tag(id, name) VALUES (10, 'Pretty')")
    db.execute("INSERT INTO image(id, file_path, sha256, mime_type) VALUES (1, 'images/a.png', 'h', 'image/png')")
    db.execute("INSERT INTO image_tag VALUES (1, 10)")
    assert db.execute("SELECT * FROM image_cw").fetchall() == []

def test_tag_justification():
    db = new_db()
    db.execute("INSERT INTO tag(id, name) VALUES (10, 'Enemies to Lovers')")
    db.execute("INSERT INTO work_tag VALUES (1, 10, 'the side couple in Ch. 64 begin as rivals')")
    assert rejects(db, "INSERT INTO work_tag VALUES (1, 10, 'again')")

# ---------------------------------------------------------------- lists

def test_lists():
    db = new_db()
    db.execute("INSERT INTO list(id, name) VALUES (1, 'Discord Recommendations')")
    db.execute("INSERT INTO list_item(list_id, work_id, note_md) VALUES (1, 1, 'great art')")
    db.execute("INSERT INTO list_item(list_id, work_id) VALUES (1, 2)")
    assert rejects(db, "INSERT INTO list_item(list_id, work_id) VALUES (1, 1)")
    assert rejects(db, "INSERT INTO list(name) VALUES ('discord recommendations')")

# ---------------------------------------------------------------- work search

def test_work_search_stays_in_sync():
    db = new_db()
    q = "SELECT rowid FROM work_search WHERE work_search MATCH ? ORDER BY rowid"
    assert db.execute(q, ("manga",)).fetchall() == [(1,)]
    db.execute("INSERT INTO work_alt_title(work_id, title) VALUES (1, 'Kimi no Koto')")
    assert db.execute(q, ("koto",)).fetchall() == [(1,)]
    db.execute("INSERT INTO creator(id, name) VALUES (1, 'Tanaka')")
    db.execute("INSERT INTO work_creator(work_id, creator_id) VALUES (1, 1), (2, 1)")
    assert db.execute(q, ("tanaka",)).fetchall() == [(1,), (2,)]
    db.execute("UPDATE creator SET name = 'Suzuki' WHERE id = 1")
    assert db.execute(q, ("tanaka",)).fetchall() == []
    assert db.execute(q, ("suzuki",)).fetchall() == [(1,), (2,)]
    db.execute("UPDATE work SET review_md = 'heartbreaking ending' WHERE id = 2")
    assert db.execute(q, ("heartbreaking",)).fetchall() == [(2,)]
    db.execute("UPDATE work SET title = 'Something Else' WHERE id = 1")
    assert db.execute(q, ("manga",)).fetchall() == []
    db.execute("DELETE FROM work_alt_title WHERE work_id = 1")
    assert db.execute(q, ("koto",)).fetchall() == []
    db.execute("DELETE FROM work WHERE id = 1")
    assert db.execute(q, ("suzuki",)).fetchall() == [(2,)]
    assert db.execute(q, ("something",)).fetchall() == []

def test_progress_update_does_not_break_search():
    db = new_db()
    add_entry(db, value=5, unit="chapter")
    assert db.execute("SELECT rowid FROM work_search WHERE work_search MATCH 'manga'").fetchall() == [(1,)]

def test_integrity():
    db = new_db()
    assert one(db, "PRAGMA integrity_check") == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert one(db, "PRAGMA user_version") == 4


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
