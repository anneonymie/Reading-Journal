"""Pages and form handlers."""
import math
import re
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, send_from_directory, url_for)

from .db import connect
from .images import ImageError, store_image
from .text import now_utc, parse_utc

bp = Blueprint("journal", __name__)

# How a pasted URL is turned into a source ID. The first pattern accepts a bare ID.
SOURCE_PATTERNS = {
    "anilist": (r"\d+", [r"anilist\.co/(?:manga|anime)/(\d+)"]),
    "mangaupdates": (r"[0-9a-z]+", [r"mangaupdates\.com/series/([0-9a-z]+)",
                                    r"mangaupdates\.com/series\.html\?id=(\d+)"]),
    "ao3": (r"\d+", [r"archiveofourown\.org/works/(\d+)"]),
}
PUB_STATUSES = [("", "Unknown"), ("ongoing", "Ongoing"), ("completed", "Completed"),
                ("hiatus", "On hiatus"), ("cancelled", "Cancelled")]
MAX_TITLE = 300
# Creator roles the work form manages: stored role -> label shown. A creator added
# with neither role ticked gets the single role NO_ROLE and is shown with no label.
CREATOR_ROLES = {"author": "Writer", "artist": "Artist"}
NO_ROLE = "unspecified"


def db():
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def lookups():
    c = db()
    return {
        "formats": c.execute("SELECT * FROM format ORDER BY sort_order").fetchall(),
        "units": c.execute("SELECT * FROM progress_unit").fetchall(),
        "statuses": c.execute("SELECT * FROM status ORDER BY sort_order").fetchall(),
        "sources": c.execute("SELECT * FROM source ORDER BY rowid").fetchall(),
        "pub_statuses": PUB_STATUSES,
    }


def get_work_or_404(work_id):
    row = db().execute(
        """SELECT w.*, f.label AS format_label, u.abbrev AS unit_abbrev, u.plural AS unit_plural,
                  i.file_path AS cover_path, cs.status_code, s.label AS status_label
           FROM work w
           JOIN format f ON f.code = w.format_code
           JOIN progress_unit u ON u.code = w.length_unit
           LEFT JOIN image i ON i.id = w.cover_image_id
           JOIN work_current_status cs ON cs.work_id = w.id
           LEFT JOIN status s ON s.code = cs.status_code
           WHERE w.id = ?""",
        (work_id,),
    ).fetchone()
    if row is None:
        abort(404)
    return row


# ------------------------------------------------------------------ parsing helpers

def parse_number(raw, label, errors, minimum=0.0, allow_zero=True):
    """Return a float, None for blank, or add an error."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        errors.append(f"{label} must be a number.")
        return None
    if not math.isfinite(value) or value < minimum or (not allow_zero and value == 0):
        errors.append(f"{label} must be {'more than' if not allow_zero else 'at least'} {minimum:g}.")
        return None
    return value


def parse_rating(raw, errors):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        errors.append("Rating must be a number from 0.0 to 10.0.")
        return None
    if not value.is_finite() or value < 0 or value > 10 or value != value.quantize(Decimal("0.1")):
        errors.append("Rating must be from 0.0 to 10.0, with at most one decimal place.")
        return None
    return float(value)


def parse_source_id(code, raw, errors, name):
    raw = (raw or "").strip()
    if not raw:
        return None
    bare, url_patterns = SOURCE_PATTERNS[code]
    lowered = raw.lower()
    if re.fullmatch(bare, lowered):
        return lowered
    for pattern in url_patterns:
        m = re.search(pattern, lowered)
        if m:
            return m.group(1)
    errors.append(f"{name}: paste the work's {name} link or its ID.")
    return None


def lines(raw):
    seen, out = set(), []
    for line in (raw or "").splitlines():
        line = line.strip()
        if line and line.lower() not in seen:
            seen.add(line.lower())
            out.append(line[:MAX_TITLE])
    return out


def merge_creators(rows):
    """One entry per person (names match regardless of capitals), combining the roles of repeated rows."""
    people = {}
    for r in rows:
        if r["name"]:
            p = people.setdefault(r["name"].lower(), {"name": r["name"], **{k: False for k in CREATOR_ROLES}})
            for k in CREATOR_ROLES:
                p[k] = p[k] or r[k]
    return list(people.values())


def work_creators(work_id):
    """The work's creators as the form shows them: writers first, then artists, then the rest."""
    rows = [{"name": r["name"], **{k: r["role"] == k for k in CREATOR_ROLES}} for r in db().execute(
        f"""SELECT c.name, wc.role FROM work_creator wc JOIN creator c ON c.id = wc.creator_id
            WHERE wc.work_id = ? AND wc.role IN ({",".join("?" * (len(CREATOR_ROLES) + 1))})""",
        (work_id, *CREATOR_ROLES, NO_ROLE))]
    return sorted(merge_creators(rows), key=lambda p: ([not p[k] for k in CREATOR_ROLES], p["name"].lower()))


# ------------------------------------------------------------------ library

@bp.get("/")
def library():
    c = db()
    status = request.args.get("status") or None
    valid = {r["code"] for r in c.execute("SELECT code FROM status")}
    if status not in valid:
        status = None
    works = c.execute(
        """SELECT w.id, w.title, f.label AS format_label, i.file_path AS cover_path,
                  cs.status_code, s.label AS status_label, w.progress_current, w.length_total,
                  u.abbrev AS unit_abbrev,
                  max(w.updated_at, coalesce((SELECT max(posted_at) FROM journal_entry
                                              WHERE work_id = w.id), '')) AS last_active
           FROM work w
           JOIN format f ON f.code = w.format_code
           JOIN progress_unit u ON u.code = w.length_unit
           LEFT JOIN image i ON i.id = w.cover_image_id
           JOIN work_current_status cs ON cs.work_id = w.id
           LEFT JOIN status s ON s.code = cs.status_code
           WHERE ? IS NULL OR cs.status_code = ?
           ORDER BY last_active DESC, w.id DESC""",
        (status, status),
    ).fetchall()
    counts = {r["status_code"]: r["n"] for r in c.execute(
        "SELECT status_code, COUNT(*) AS n FROM work_current_status GROUP BY status_code")}
    total = c.execute("SELECT COUNT(*) FROM work").fetchone()[0]
    return render_template("library.html", works=works, status=status, counts=counts,
                           total=total, **lookups())


# ------------------------------------------------------------------ add / edit works

def empty_work_form():
    return {"title": "", "format_code": "", "length_unit": "", "length_total": "",
            "pub_status": "", "publisher": "", "pub_start": "", "pub_end": "",
            "description_md": "", "alt_titles": "", "creators": [],
            "status": "tbr", "src_anilist": "", "src_mangaupdates": "", "src_ao3": ""}


def work_form_from_db(work_id):
    c = db()
    w = c.execute("SELECT * FROM work WHERE id = ?", (work_id,)).fetchone()
    form = empty_work_form()
    for key in ("title", "format_code", "length_unit", "pub_status", "publisher",
                "pub_start", "pub_end", "description_md"):
        form[key] = w[key] or ""
    form["length_total"] = "" if w["length_total"] is None else f"{w['length_total']:g}"
    form["alt_titles"] = "\n".join(r["title"] for r in c.execute(
        "SELECT title FROM work_alt_title WHERE work_id = ? ORDER BY id", (work_id,)))
    form["creators"] = work_creators(work_id)
    for r in c.execute("SELECT source_code, external_id FROM work_source_id WHERE work_id = ?", (work_id,)):
        form[f"src_{r['source_code']}"] = r["external_id"]
    return form


def read_work_form(is_new):
    f = request.form
    form = empty_work_form()
    for key in form:
        form[key] = (f.get(key) or "").strip()
    # Each creator row is a name plus role tick boxes whose value is the row's number.
    ticked = {k: set(f.getlist(f"creator_{k}")) for k in CREATOR_ROLES}
    form["creators"] = [row for i, name in enumerate(f.getlist("creator_name"))
                        if (row := {"name": name.strip()[:MAX_TITLE],
                                    **{k: str(i) in ticked[k] for k in CREATOR_ROLES}})["name"]]
    errors = []
    lk = lookups()
    formats = {r["code"]: r for r in lk["formats"]}
    units = {r["code"] for r in lk["units"]}

    if not form["title"]:
        errors.append("Title is required.")
    form["title"] = form["title"][:MAX_TITLE]
    if form["format_code"] not in formats:
        errors.append("Choose a format.")
    if form["length_unit"] not in units:
        if form["format_code"] in formats:
            form["length_unit"] = formats[form["format_code"]]["default_unit"]
        else:
            errors.append("Choose a progress unit.")
    total = parse_number(form["length_total"], "Total length", errors, allow_zero=False)
    if form["pub_status"] not in {code for code, _ in PUB_STATUSES}:
        form["pub_status"] = ""
    if is_new and form["status"] not in {r["code"] for r in lk["statuses"]}:
        errors.append("Choose a status.")
    sources = {}
    for s in lk["sources"]:
        value = parse_source_id(s["code"], form[f"src_{s['code']}"], errors, s["name"])
        if value:
            sources[s["code"]] = value
    parsed = {"length_total": total, "sources": sources,
              "alt_titles": [t for t in lines(form["alt_titles"]) if t.lower() != form["title"].lower()],
              "creators": merge_creators(form["creators"])}
    return form, parsed, errors


def source_conflicts(sources, work_id):
    """Messages for source IDs that already belong to another work."""
    msgs = []
    for code, ext in sources.items():
        row = db().execute(
            """SELECT w.id, w.title, s.name FROM work_source_id x
               JOIN work w ON w.id = x.work_id JOIN source s ON s.code = x.source_code
               WHERE x.source_code = ? AND x.external_id = ? AND x.work_id IS NOT ?""",
            (code, ext, work_id),
        ).fetchone()
        if row:
            msgs.append((f"{row['name']} ID {ext} is already used by ", row["title"], row["id"]))
    return msgs


def save_related(c, work_id, parsed):
    c.execute("DELETE FROM work_alt_title WHERE work_id = ?", (work_id,))
    for t in parsed["alt_titles"]:
        c.execute("INSERT INTO work_alt_title(work_id, title) VALUES (?, ?)", (work_id, t))
    # Roles the form doesn't manage (e.g. imported translators) are left alone.
    c.execute(f"DELETE FROM work_creator WHERE work_id = ? AND role IN ({','.join('?' * (len(CREATOR_ROLES) + 1))})",
              (work_id, *CREATOR_ROLES, NO_ROLE))
    for p in parsed["creators"]:
        c.execute("INSERT OR IGNORE INTO creator(name) VALUES (?)", (p["name"],))
        cid = c.execute("SELECT id FROM creator WHERE name = ?", (p["name"],)).fetchone()["id"]
        for role in [k for k in CREATOR_ROLES if p[k]] or [NO_ROLE]:
            c.execute("INSERT OR IGNORE INTO work_creator(work_id, creator_id, role) VALUES (?,?,?)",
                      (work_id, cid, role))
    c.execute("DELETE FROM work_source_id WHERE work_id = ?", (work_id,))
    for code, ext in parsed["sources"].items():
        c.execute("INSERT INTO work_source_id(work_id, source_code, external_id) VALUES (?,?,?)",
                  (work_id, code, ext))


def add_status_change(c, work_id, old, new, when=None):
    when = when or now_utc()
    ev = c.execute("INSERT INTO status_event(work_id, status_code, changed_at) VALUES (?,?,?)",
                   (work_id, new, when)).lastrowid
    c.execute("""INSERT INTO journal_entry(work_id, kind, posted_at, status_event_id, status_from, status_to)
                 VALUES (?, 'status', ?, ?, ?, ?)""", (work_id, when, ev, old, new))


@bp.route("/works/new", methods=["GET", "POST"])
def work_new():
    if request.method == "GET":
        return render_template("work_form.html", form=empty_work_form(), work=None, errors=[],
                               conflicts=[], **lookups())
    form, parsed, errors = read_work_form(is_new=True)
    conflicts = source_conflicts(parsed["sources"], None)
    if errors or conflicts:
        return render_template("work_form.html", form=form, work=None, errors=errors,
                               conflicts=conflicts, **lookups()), 400
    c = db()
    try:
        with c:
            cover_id = store_image(c, current_app.config["DATA_DIR"], request.files.get("cover"))
            work_id = c.execute(
                """INSERT INTO work(title, format_code, description_md, cover_image_id, publisher,
                                    pub_start, pub_end, pub_status, length_unit, length_total)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (form["title"], form["format_code"], form["description_md"] or None, cover_id,
                 form["publisher"] or None, form["pub_start"] or None, form["pub_end"] or None,
                 form["pub_status"] or None, form["length_unit"], parsed["length_total"]),
            ).lastrowid
            save_related(c, work_id, parsed)
            add_status_change(c, work_id, None, form["status"])
    except ImageError as e:
        return render_template("work_form.html", form=form, work=None, errors=[str(e)],
                               conflicts=[], **lookups()), 400
    flash(f"Added {form['title']}.")
    return redirect(url_for(".work_page", work_id=work_id))


@bp.route("/works/<int:work_id>/edit", methods=["GET", "POST"])
def work_edit(work_id):
    work = get_work_or_404(work_id)
    if request.method == "GET":
        return render_template("work_form.html", form=work_form_from_db(work_id), work=work,
                               errors=[], conflicts=[], **lookups())
    form, parsed, errors = read_work_form(is_new=False)
    conflicts = source_conflicts(parsed["sources"], work_id)
    if errors or conflicts:
        return render_template("work_form.html", form=form, work=work, errors=errors,
                               conflicts=conflicts, **lookups()), 400
    c = db()
    unit_changed = form["length_unit"] != work["length_unit"]
    try:
        with c:
            cover_id = work["cover_image_id"]
            if request.form.get("remove_cover"):
                cover_id = None
            new_cover = store_image(c, current_app.config["DATA_DIR"], request.files.get("cover"))
            if new_cover:
                cover_id = new_cover
            c.execute(
                """UPDATE work SET title=?, format_code=?, description_md=?, cover_image_id=?,
                       publisher=?, pub_start=?, pub_end=?, pub_status=?, length_unit=?, length_total=?
                   WHERE id=?""",
                (form["title"], form["format_code"], form["description_md"] or None, cover_id,
                 form["publisher"] or None, form["pub_start"] or None, form["pub_end"] or None,
                 form["pub_status"] or None, form["length_unit"], parsed["length_total"], work_id),
            )
            if unit_changed:
                # Current progress was measured in the old unit, so it no longer means anything.
                c.execute("UPDATE work SET progress_current = NULL WHERE id = ?", (work_id,))
            save_related(c, work_id, parsed)
    except ImageError as e:
        return render_template("work_form.html", form=form, work=work, errors=[str(e)],
                               conflicts=[], **lookups()), 400
    if unit_changed:
        mismatched = db().execute(
            "SELECT COUNT(*) FROM journal_entry_progress WHERE work_id = ? AND progress_valid = 0",
            (work_id,)).fetchone()[0]
        msg = "Saved. The progress unit changed, so current progress was cleared; set it again below."
        if mismatched:
            msg += f" {mismatched} journal {'entry uses' if mismatched == 1 else 'entries use'} a different unit and won't count toward progress."
        flash(msg)
    else:
        flash("Saved.")
    return redirect(url_for(".work_page", work_id=work_id))


@bp.route("/works/<int:work_id>/delete", methods=["GET", "POST"])
def work_delete(work_id):
    work = get_work_or_404(work_id)
    if request.method == "GET":
        n = db().execute("SELECT COUNT(*) FROM journal_entry WHERE work_id = ?", (work_id,)).fetchone()[0]
        return render_template("work_delete.html", work=work, entry_count=n)
    with db() as c:
        c.execute("DELETE FROM work WHERE id = ?", (work_id,))
    flash(f"Deleted {work['title']}.")
    return redirect(url_for(".library"))


# ------------------------------------------------------------------ work page

def render_work(work_id, composer=None, errors=None, status=200):
    c = db()
    work = get_work_or_404(work_id)
    alt_titles = c.execute("SELECT title FROM work_alt_title WHERE work_id = ? ORDER BY id", (work_id,)).fetchall()
    creators = [{"name": p["name"], "roles": " and ".join(label for k, label in CREATOR_ROLES.items() if p[k])}
                for p in work_creators(work_id)]
    sources = c.execute(
        """SELECT s.name, s.url_template, x.external_id FROM work_source_id x
           JOIN source s ON s.code = x.source_code WHERE x.work_id = ? ORDER BY s.rowid""",
        (work_id,)).fetchall()
    entries = c.execute(
        """SELECT je.*, p.progress_valid, u.abbrev AS entry_unit_abbrev, u.plural AS entry_unit_plural,
                  sf.label AS from_label, st.label AS to_label
           FROM journal_entry je
           JOIN journal_entry_progress p ON p.entry_id = je.id
           LEFT JOIN progress_unit u ON u.code = je.progress_unit
           LEFT JOIN status sf ON sf.code = je.status_from
           LEFT JOIN status st ON st.code = je.status_to
           WHERE je.work_id = ?
           ORDER BY je.posted_at, je.id""", (work_id,)).fetchall()
    images = {}
    for r in c.execute(
            """SELECT ji.entry_id, i.id, i.file_path, i.width, i.height, i.alt_text
               FROM journal_entry_image ji JOIN image i ON i.id = ji.image_id
               JOIN journal_entry je ON je.id = ji.entry_id
               WHERE je.work_id = ? ORDER BY ji.position, i.id""", (work_id,)):
        images.setdefault(r["entry_id"], []).append(r)
    completions = c.execute("SELECT completions FROM work_completion_count WHERE work_id = ?",
                            (work_id,)).fetchone()
    if composer is None:
        composer = {"body": "", "progress": "" if work["progress_current"] is None
                    else f"{work['progress_current']:g}", "posted_at": ""}
    return render_template("work.html", work=work, alt_titles=alt_titles, creators=creators,
                           work_sources=sources, entries=entries, images=images,
                           completions=completions["completions"] if completions else 0,
                           composer=composer, errors=errors or [], **lookups()), status


@bp.get("/works/<int:work_id>")
def work_page(work_id):
    return render_work(work_id)


@bp.post("/works/<int:work_id>/status")
def work_status(work_id):
    work = get_work_or_404(work_id)
    new = request.form.get("status")
    if new not in {r["code"] for r in lookups()["statuses"]}:
        abort(400)
    old = work["status_code"]
    if new == old:
        flash(f"Status is already {work['status_label']}.")
        return redirect(url_for(".work_page", work_id=work_id))
    reset = request.form.get("reset")
    if old == "completed" and new == "reading" and reset not in ("yes", "no"):
        return render_template("confirm_reread.html", work=work)
    with db() as c:
        add_status_change(c, work_id, old, new)
        if reset == "yes" and old == "completed" and new == "reading":
            c.execute("UPDATE work SET progress_current = 0 WHERE id = ?", (work_id,))
    return redirect(url_for(".work_page", work_id=work_id) + "#latest")


@bp.post("/works/<int:work_id>/progress")
def work_progress(work_id):
    get_work_or_404(work_id)
    errors = []
    value = parse_number(request.form.get("progress"), "Progress", errors)
    if errors:
        return render_work(work_id, errors=errors, status=400)
    with db() as c:
        c.execute("UPDATE work SET progress_current = ? WHERE id = ?", (value, work_id))
    flash("Progress updated.")
    return redirect(url_for(".work_page", work_id=work_id))


@bp.post("/works/<int:work_id>/review")
def work_review(work_id):
    get_work_or_404(work_id)
    errors = []
    rating = parse_rating(request.form.get("rating"), errors)
    if errors:
        return render_work(work_id, errors=errors, status=400)
    review = (request.form.get("review_md") or "").strip() or None
    with db() as c:
        c.execute("UPDATE work SET rating = ?, review_md = ? WHERE id = ?", (rating, review, work_id))
    flash("Review saved.")
    return redirect(url_for(".work_page", work_id=work_id))


@bp.post("/works/<int:work_id>/notes")
def work_notes(work_id):
    get_work_or_404(work_id)
    notes = (request.form.get("notes_md") or "").strip() or None
    with db() as c:
        c.execute("UPDATE work SET notes_md = ? WHERE id = ?", (notes, work_id))
    flash("Notes saved.")
    return redirect(url_for(".work_page", work_id=work_id))


# ------------------------------------------------------------------ journal entries

def attach_images(c, entry_id, uploads, start=0):
    pos = start
    for up in uploads:
        image_id = store_image(c, current_app.config["DATA_DIR"], up)
        if image_id:
            c.execute("INSERT OR IGNORE INTO journal_entry_image(entry_id, image_id, position) VALUES (?,?,?)",
                      (entry_id, image_id, pos))
            pos += 1
    return pos - start


def read_posted_at(errors):
    raw = (request.form.get("posted_at") or "").strip()
    if not raw:
        return None
    value = parse_utc(raw)
    if value is None:
        errors.append("The date couldn't be read. Use the date picker, or the form 2026-10-17T14:03:00Z.")
    return value


@bp.post("/works/<int:work_id>/entries")
def entry_create(work_id):
    work = get_work_or_404(work_id)
    body = (request.form.get("body") or "").strip()
    composer = {"body": body, "progress": request.form.get("progress", ""),
                "posted_at": request.form.get("posted_at", "")}
    errors = []
    progress = parse_number(request.form.get("progress"), "Progress", errors)
    posted_at = read_posted_at(errors)
    uploads = [u for u in request.files.getlist("images") if u and u.filename]
    if not errors and not body and not uploads and progress is None:
        errors.append("Write something, add an image or record your progress.")
    if errors:
        return render_work(work_id, composer=composer, errors=errors, status=400)
    c = db()
    try:
        with c:
            entry_id = c.execute(
                """INSERT INTO journal_entry(work_id, body_md, posted_at, progress_value, progress_unit)
                   VALUES (?, ?, coalesce(?, strftime('%Y-%m-%dT%H:%M:%SZ','now')), ?, ?)""",
                (work_id, body or None, posted_at, progress,
                 work["length_unit"] if progress is not None else None),
            ).lastrowid
            attach_images(c, entry_id, uploads)
    except ImageError as e:
        return render_work(work_id, composer=composer,
                           errors=[f"{e} Nothing was posted; attach the images again."], status=400)
    return redirect(url_for(".work_page", work_id=work_id) + f"#entry-{entry_id}")


def get_entry_or_404(entry_id):
    row = db().execute(
        """SELECT je.*, p.progress_valid, p.series_unit, u.abbrev AS entry_unit_abbrev, u.plural AS entry_unit_plural,
                  su.abbrev AS series_unit_abbrev, su.plural AS series_unit_plural, w.title AS work_title,
                  sf.label AS from_label, st.label AS to_label
           FROM journal_entry je
           JOIN journal_entry_progress p ON p.entry_id = je.id
           JOIN work w ON w.id = je.work_id
           JOIN progress_unit su ON su.code = w.length_unit
           LEFT JOIN progress_unit u ON u.code = je.progress_unit
           LEFT JOIN status sf ON sf.code = je.status_from
           LEFT JOIN status st ON st.code = je.status_to
           WHERE je.id = ?""", (entry_id,)).fetchone()
    if row is None:
        abort(404)
    return row


def entry_images(entry_id):
    return db().execute(
        """SELECT i.id, i.file_path, i.width, i.height, ji.position FROM journal_entry_image ji
           JOIN image i ON i.id = ji.image_id WHERE ji.entry_id = ? ORDER BY ji.position, i.id""",
        (entry_id,)).fetchall()


@bp.route("/entries/<int:entry_id>/edit", methods=["GET", "POST"])
def entry_edit(entry_id):
    entry = get_entry_or_404(entry_id)
    imgs = entry_images(entry_id)
    if request.method == "GET":
        form = {"body": entry["body_md"] or "", "posted_at": entry["posted_at"],
                "progress": "" if entry["progress_value"] is None else f"{entry['progress_value']:g}"}
        return render_template("entry_edit.html", entry=entry, images=imgs, form=form, errors=[])

    body = (request.form.get("body") or "").strip()
    form = {"body": body, "posted_at": request.form.get("posted_at", ""),
            "progress": request.form.get("progress", "")}
    errors = []
    posted_at = read_posted_at(errors) or entry["posted_at"]
    is_note = entry["kind"] == "note"
    progress = parse_number(request.form.get("progress"), "Progress", errors) if is_note else None
    remove = {int(x) for x in request.form.getlist("remove_image") if x.isdigit()}
    uploads = [u for u in request.files.getlist("images") if u and u.filename] if is_note else []
    kept = [i for i in imgs if i["id"] not in remove]
    if is_note and not errors and not body and not kept and not uploads and progress is None:
        errors.append("An entry needs text, an image or progress. To remove it entirely, use Delete.")
    if errors:
        return render_template("entry_edit.html", entry=entry, images=imgs, form=form, errors=errors), 400

    # A new progress value keeps the entry's own unit; an entry gaining progress uses the series unit.
    unit = entry["progress_unit"] or entry["series_unit"]
    c = db()
    try:
        with c:
            if is_note:
                c.execute("""UPDATE journal_entry SET body_md = ?, posted_at = ?, edited_at = ?,
                                 progress_value = ?, progress_unit = ? WHERE id = ?""",
                          (body or None, posted_at, now_utc(), progress,
                           unit if progress is not None else None, entry_id))
                for image_id in remove:
                    c.execute("DELETE FROM journal_entry_image WHERE entry_id = ? AND image_id = ?",
                              (entry_id, image_id))
                start = max([i["position"] for i in kept], default=-1) + 1
                attach_images(c, entry_id, uploads, start)
            else:
                c.execute("UPDATE journal_entry SET body_md = ?, posted_at = ?, edited_at = ? WHERE id = ?",
                          (body or None, posted_at, now_utc(), entry_id))
    except ImageError as e:
        return render_template("entry_edit.html", entry=entry, images=imgs, form=form,
                               errors=[f"{e} Nothing was saved."]), 400
    return redirect(url_for(".work_page", work_id=entry["work_id"]) + f"#entry-{entry_id}")


@bp.post("/entries/<int:entry_id>/delete")
def entry_delete(entry_id):
    entry = get_entry_or_404(entry_id)
    with db() as c:
        c.execute("DELETE FROM journal_entry WHERE id = ?", (entry_id,))
    flash("Entry deleted.")
    return redirect(url_for(".work_page", work_id=entry["work_id"]) + "#latest")


# ------------------------------------------------------------------ files

CHANGELOG_PATH = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def hide_empty_unreleased(text):
    """Drop the "Unreleased" heading when nothing has been added under it yet."""
    return re.sub(r"^## Unreleased\s*(?=^## |\Z)", "", text, flags=re.M)


@bp.get("/changelog")
def changelog():
    text = hide_empty_unreleased(CHANGELOG_PATH.read_text(encoding="utf-8"))
    return render_template("changelog.html", text=text)


@bp.get("/media/<path:rel>")
def media(rel):
    # Only files inside images/ are served. Reject any "..", backslash or empty part outright,
    # because normalising "images/../journal.db" would otherwise reach the database.
    parts = rel.split("/")
    if (len(parts) < 2 or parts[0] != "images" or "\\" in rel
            or any(p in ("", ".", "..") for p in parts)):
        abort(404)
    return send_from_directory(current_app.config["DATA_DIR"], rel, max_age=31536000)


@bp.app_errorhandler(404)
def not_found(_e):
    return render_template("message.html", title="Not found",
                           message="That page doesn't exist. It may have been deleted."), 404


@bp.app_errorhandler(413)
def too_large(_e):
    return render_template("message.html", title="Upload too large",
                           message="That upload is over 200 MB in total. Post fewer images at once."), 413


@bp.app_errorhandler(sqlite3.IntegrityError)
def integrity_error(e):
    current_app.logger.warning("Integrity error: %s", e)
    return render_template("message.html", title="That change wasn't saved",
                           message=f"The journal rejected it to protect your data ({e}). Go back and try again."), 400
