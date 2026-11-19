"""Pages and form handlers."""
import difflib
import math
import re
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template,
                   request, send_from_directory, url_for)

from .db import connect
from .images import ImageError, store_image
from .text import now_utc, parse_utc

bp = Blueprint("journal", __name__)

# How a pasted link is recognized as a source and turned into its ID.
SOURCE_PATTERNS = {
    "anilist": [r"anilist\.co/(?:manga|anime)/(\d+)"],
    "mangaupdates": [r"mangaupdates\.com/series/([0-9a-z]+)", r"mangaupdates\.com/series\.html\?id=(\d+)"],
    "ao3": [r"archiveofourown\.org/works/(\d+)"],
}
PUB_STATUSES = [("", "Unknown"), ("ongoing", "Ongoing"), ("completed", "Completed"),
                ("hiatus", "On hiatus"), ("cancelled", "Canceled")]
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


def parse_source_links(links, sources, errors):
    """Work out which site each pasted link is from: {source code: ID}."""
    names = {s["code"]: s["name"] for s in sources}
    *others, last = names.values()
    found = {}
    for raw in links:
        match = next(((code, m.group(1)) for code, patterns in SOURCE_PATTERNS.items()
                      for p in patterns if (m := re.search(p, raw.lower()))), None)
        if match is None:
            errors.append(f"“{raw}” isn't a link to a work on {', '.join(others)} or {last}. "
                          "Paste the whole link from the work's page.")
        elif found.get(match[0], match[1]) != match[1]:
            errors.append(f"A work can only have one {names[match[0]]} link.")
        else:
            found[match[0]] = match[1]
    return found


def source_url(source, external_id):
    return source["url_template"].replace("{id}", external_id)


def distinct(values):
    """Non-blank values with repeats dropped (regardless of capitals), in order."""
    seen, out = set(), []
    for value in values:
        value = value.strip()[:MAX_TITLE]
        if value and value.lower() not in seen:
            seen.add(value.lower())
            out.append(value)
    return out


PARTIAL_DATE = re.compile(r"(\d{4})(?:-(0[1-9]|1[0-2]))?")


def split_partial_date(value):
    """'2019-04' -> year, month and no leftover. Anything else is kept whole as a leftover."""
    m = PARTIAL_DATE.fullmatch(value or "")
    if m:
        return {"year": m.group(1), "month": m.group(2) or "", "legacy": ""}
    return {"year": "", "month": "", "legacy": value or ""}


def read_partial_date(form, prefix, label, errors):
    """Combine the year box and month list into '2019' or '2019-04'.

    With no year, a leftover value saved before the pickers existed is kept as it was.
    """
    year, month = form[f"{prefix}_year"], form[f"{prefix}_month"]
    if not year:
        if month:
            errors.append(f"{label}: add a year to go with the month.")
        return form[f"{prefix}_legacy"] or None
    if not re.fullmatch(r"[12]\d{3}", year):
        errors.append(f"{label}: the year must be four digits, like 2019.")
        return None
    if month and not re.fullmatch(r"0[1-9]|1[0-2]", month):
        month = ""
    return f"{year}-{month}" if month else year


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
    tag = None
    if request.args.get("tag", "").isdigit():
        tag = c.execute(f"{TAG_SELECT} WHERE t.id = ?", (int(request.args["tag"]),)).fetchone()
    tag_id = tag["id"] if tag else None
    tagged = "(? IS NULL OR w.id IN (SELECT work_id FROM work_tag WHERE tag_id = ?))"
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
           WHERE (? IS NULL OR cs.status_code = ?) AND {tagged}
           ORDER BY last_active DESC, w.id DESC""".replace("{tagged}", tagged),
        (status, status, tag_id, tag_id),
    ).fetchall()
    # The status counts follow the tag filter, so they match what each tab shows.
    counts = {r["status_code"]: r["n"] for r in c.execute(
        f"""SELECT cs.status_code, COUNT(*) AS n FROM work_current_status cs JOIN work w ON w.id = cs.work_id
            WHERE {tagged} GROUP BY cs.status_code""", (tag_id, tag_id))}
    total = c.execute(f"SELECT COUNT(*) FROM work w WHERE {tagged}", (tag_id, tag_id)).fetchone()[0]
    return render_template("library.html", works=works, status=status, counts=counts,
                           total=total, tag=tag, **lookups())


# ------------------------------------------------------------------ add / edit works

PUB_DATES = {"pub_start": "Started", "pub_end": "Ended"}


def empty_work_form():
    form = {"title": "", "format_code": "", "length_unit": "", "length_total": "", "pub_status": "",
            "description_md": "", "alt_titles": [], "publishers": [], "source_links": [], "creators": [],
            "status": "tbr"}
    for prefix in PUB_DATES:
        form.update({f"{prefix}_year": "", f"{prefix}_month": "", f"{prefix}_legacy": ""})
    return form


def work_form_from_db(work_id):
    c = db()
    w = c.execute("SELECT * FROM work WHERE id = ?", (work_id,)).fetchone()
    form = empty_work_form()
    for key in ("title", "format_code", "length_unit", "pub_status", "description_md"):
        form[key] = w[key] or ""
    for prefix in PUB_DATES:
        for part, value in split_partial_date(w[prefix]).items():
            form[f"{prefix}_{part}"] = value
    form["length_total"] = "" if w["length_total"] is None else f"{w['length_total']:g}"
    form["alt_titles"] = [r["title"] for r in c.execute(
        "SELECT title FROM work_alt_title WHERE work_id = ? ORDER BY id", (work_id,))]
    form["publishers"] = [r["name"] for r in work_publishers(work_id)]
    form["creators"] = work_creators(work_id)
    form["source_links"] = [source_url(r, r["external_id"]) for r in work_sources(work_id)]
    return form


def work_publishers(work_id):
    return db().execute(
        """SELECT p.name FROM work_publisher wp JOIN publisher p ON p.id = wp.publisher_id
           WHERE wp.work_id = ? ORDER BY wp.position, p.name""", (work_id,)).fetchall()


def work_sources(work_id):
    return db().execute(
        """SELECT s.name, s.url_template, x.external_id FROM work_source_id x
           JOIN source s ON s.code = x.source_code WHERE x.work_id = ? ORDER BY s.rowid""",
        (work_id,)).fetchall()


def read_work_form(is_new):
    f = request.form
    form = empty_work_form()
    for key in form:
        form[key] = (f.get(key) or "").strip()
    for key, field in (("alt_titles", "alt_title"), ("publishers", "publisher"), ("source_links", "source_link")):
        form[key] = [v.strip()[:MAX_TITLE] for v in f.getlist(field) if v.strip()]
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
    dates = {prefix: read_partial_date(form, prefix, label, errors) for prefix, label in PUB_DATES.items()}
    start, end = (split_partial_date(dates[p]) for p in PUB_DATES)
    if start["year"] and end["year"]:
        # Compare only as precisely as both are known: Started 2019-04, Ended 2019 is fine.
        n = min(len(dates["pub_start"]), len(dates["pub_end"]))
        if dates["pub_end"][:n] < dates["pub_start"][:n]:
            errors.append("Ended can't be before Started.")
    if is_new and form["status"] not in {r["code"] for r in lk["statuses"]}:
        errors.append("Choose a status.")
    sources = parse_source_links(form["source_links"], lk["sources"], errors)
    parsed = {"length_total": total, "sources": sources, **dates, "publishers": distinct(form["publishers"]),
              "alt_titles": [t for t in distinct(form["alt_titles"]) if t.lower() != form["title"].lower()],
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
    c.execute("DELETE FROM work_publisher WHERE work_id = ?", (work_id,))
    for pos, name in enumerate(parsed["publishers"]):
        c.execute("INSERT OR IGNORE INTO publisher(name) VALUES (?)", (name,))
        c.execute("""INSERT INTO work_publisher(work_id, publisher_id, position)
                     SELECT ?, id, ? FROM publisher WHERE name = ?""", (work_id, pos, name))
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
    if new == "completed":
        # Finishing means all of it has been read; with no total there's nothing to fill in.
        c.execute("UPDATE work SET progress_current = length_total WHERE id = ? AND length_total IS NOT NULL",
                  (work_id,))


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
                """INSERT INTO work(title, format_code, description_md, cover_image_id,
                                    pub_start, pub_end, pub_status, length_unit, length_total)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (form["title"], form["format_code"], form["description_md"] or None, cover_id,
                 parsed["pub_start"], parsed["pub_end"],
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
                       pub_start=?, pub_end=?, pub_status=?, length_unit=?, length_total=?
                   WHERE id=?""",
                (form["title"], form["format_code"], form["description_md"] or None, cover_id,
                 parsed["pub_start"], parsed["pub_end"],
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
                           publishers=work_publishers(work_id), work_sources=work_sources(work_id),
                           entries=entries, images=images,
                           tags=work_tags(work_id), reasons=work_tag_reasons(work_id), categories=categories(),
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
    # Starting a reread, or putting a work back on the TBR pile with some progress, offers a fresh start.
    rereading = old == "completed" and new == "reading"
    offer_reset = rereading or (new == "tbr" and bool(work["progress_current"]))
    reset = request.form.get("reset")
    if offer_reset and reset not in ("yes", "no"):
        return render_template("confirm_reset.html", work=work, new=new, rereading=rereading)
    with db() as c:
        add_status_change(c, work_id, old, new)
        if reset == "yes" and offer_reset:
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

def place_images(c, entry_id, image_ids):
    """Give the entry exactly these images' positions, in this order, adding any it doesn't have yet.
    An image listed twice (the same file uploaded again) keeps its first place."""
    pos = 0
    for image_id in dict.fromkeys(i for i in image_ids if i):
        c.execute("""INSERT INTO journal_entry_image(entry_id, image_id, position) VALUES (?,?,?)
                     ON CONFLICT(entry_id, image_id) DO UPDATE SET position = excluded.position""",
                  (entry_id, image_id, pos))
        pos += 1


def store_uploads(c, uploads):
    return [store_image(c, current_app.config["DATA_DIR"], up) for up in uploads]


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
            place_images(c, entry_id, store_uploads(c, uploads))
    except ImageError as e:
        return render_work(work_id, composer=composer,
                           errors=[f"{e} Nothing was posted; attach the images again."], status=400)
    return redirect(url_for(".work_page", work_id=work_id) + f"#entry-{entry_id}")


def get_entry_or_404(entry_id):
    row = db().execute(
        """SELECT je.*, p.progress_valid, p.series_unit, u.abbrev AS entry_unit_abbrev, u.plural AS entry_unit_plural,
                  su.abbrev AS series_unit_abbrev, su.plural AS series_unit_plural, w.title AS work_title,
                  w.length_total AS series_total,
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


def image_order(kept, new_count):
    """The entry's images in the order the form sent them. Kept images are their ids; uploads are
    ("new", n) for the n-th uploaded file, sent as "new:n". Anything left out goes at the end."""
    ids = [i["id"] for i in kept]
    sent = []
    for x in request.form.getlist("image_order"):
        if x.isdigit() and int(x) in ids:
            sent.append(int(x))
        elif x.startswith("new:") and x[4:].isdigit() and int(x[4:]) < new_count:
            sent.append(("new", int(x[4:])))
    return list(dict.fromkeys(sent + ids + [("new", n) for n in range(new_count)]))


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
                new_ids = store_uploads(c, uploads)
                place_images(c, entry_id, [new_ids[x[1]] if isinstance(x, tuple) else x
                                           for x in image_order(kept, len(uploads))])
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


# ------------------------------------------------------------------ tags

UNCATEGORIZED_COLOR = "#808080"
MAX_TAG_NAME = 100
HEX_COLOR = re.compile(r"#[0-9a-f]{6}")
# One tag with everything a chip needs: its category's name and color, and whether it's a CW.
TAG_SELECT = """SELECT t.id, t.name, t.description_md, t.category_id, t.parent_id,
                       coalesce(c.name, 'Uncategorized') AS category_name,
                       coalesce(c.color, '#808080') AS color, c.position AS category_position,
                       EXISTS (SELECT 1 FROM cw_setting WHERE tag_id = t.id) AS is_cw
                FROM tag t LEFT JOIN tag_category c ON c.id = t.category_id"""
CATEGORY_ORDER = "c.position IS NULL, c.position, t.name COLLATE NOCASE"   # uncategorized last


def categories():
    return db().execute("SELECT * FROM tag_category ORDER BY position, name").fetchall()


def get_tag_or_404(tag_id):
    row = db().execute(f"{TAG_SELECT} WHERE t.id = ?", (tag_id,)).fetchone()
    if row is None:
        abort(404)
    return row


def clean_tag_name(raw):
    return " ".join((raw or "").split())[:MAX_TAG_NAME]


def find_tag(name):
    """The tag with this name or alias (capitals don't matter), or None."""
    row = db().execute("""SELECT id FROM tag WHERE name = ?
                          UNION ALL SELECT tag_id FROM tag_alias WHERE alias = ? LIMIT 1""", (name, name)).fetchone()
    return row[0] if row else None


def find_or_create_tag(c, name):
    """Typing a name that doesn't exist yet creates it, uncategorized."""
    return find_tag(name) or c.execute("INSERT INTO tag(name) VALUES (?)", (name,)).lastrowid


def suggest_tags(query, exclude=(), limit=8):
    """Clever tag search: exact name or alias, then names starting with it, then words starting
    with it, then anything containing it, then near misses (typos). If there's room left,
    tags often used on the same works as the best match follow, marked as similar."""
    q = " ".join(query.split()).casefold()
    if not q:
        return []
    terms = db().execute("""SELECT name AS term, id AS tag_id, 0 AS is_alias FROM tag
                            UNION ALL SELECT alias, tag_id, 1 FROM tag_alias""").fetchall()
    best = {}
    for term, tag_id, is_alias in terms:
        t = term.casefold()
        if t == q:
            rank = 0
        elif t.startswith(q):
            rank = 1
        elif any(w.startswith(q) for w in re.split(r"[\s/\-:]+", t)):
            rank = 2
        elif q in t:
            rank = 3
        elif len(q) >= 3 and difflib.SequenceMatcher(None, q, t).ratio() >= 0.75:
            rank = 4
        else:
            continue
        if tag_id not in exclude and (tag_id not in best or rank < best[tag_id][0]):
            best[tag_id] = (rank, term if is_alias else None)
    tags = {t["id"]: t for t in db().execute(TAG_SELECT)}
    found = []
    for tag_id, (rank, alias) in best.items():
        tag = tags[tag_id]
        found.append({"id": tag_id, "name": tag["name"], "color": tag["color"], "alias": alias,
                      "category": tag["category_name"], "rank": rank})
    found.sort(key=lambda s: (s["rank"], len(s["name"]), s["name"].casefold()))
    found = found[:limit]
    if found and len(found) < limit:
        taken = {s["id"] for s in found} | set(exclude)
        for row in db().execute(f"""{TAG_SELECT} JOIN (
                    SELECT b.tag_id, COUNT(*) AS n FROM work_tag a JOIN work_tag b ON b.work_id = a.work_id
                    WHERE a.tag_id = ? AND b.tag_id <> a.tag_id GROUP BY b.tag_id) s ON s.tag_id = t.id
                    ORDER BY s.n DESC, t.name COLLATE NOCASE""", (found[0]["id"],)):
            if len(found) >= limit:
                break
            if row["id"] not in taken:
                found.append({"id": row["id"], "name": row["name"], "color": row["color"], "alias": None,
                              "category": row["category_name"], "similar_to": found[0]["name"]})
    for s in found:
        s.pop("rank", None)
    return found


@bp.get("/tags/suggest")
def tags_suggest():
    q = request.args.get("q", "")
    exclude = ()
    if request.args.get("work", "").isdigit():
        exclude = {r[0] for r in db().execute("SELECT tag_id FROM work_tag WHERE work_id = ?",
                                              (int(request.args["work"]),))}
    found = suggest_tags(q, exclude)
    # Typing the name or alias of a tag the work already has says so, rather than offering to create it.
    already = find_tag(" ".join(q.split()))
    if already in exclude:
        tag = get_tag_or_404(already)
        found.insert(0, {"id": already, "name": tag["name"], "color": tag["color"], "alias": None,
                         "category": tag["category_name"], "on_work": True})
    return jsonify(found)


def work_tags(work_id):
    return db().execute(f"""{TAG_SELECT} JOIN work_tag wt ON wt.tag_id = t.id AND wt.work_id = ?
                            ORDER BY {CATEGORY_ORDER}""", (work_id,)).fetchall()


def work_tag_reasons(work_id):
    return {r["tag_id"]: r["justification_md"] for r in db().execute(
        "SELECT tag_id, justification_md FROM work_tag WHERE work_id = ?", (work_id,))}


def after_work_tags(work_id):
    """The browser's script asks for just the tags box back; without it, return to the page."""
    if request.headers.get("X-Partial"):
        return render_template("_work_tags.html", work=get_work_or_404(work_id), tags=work_tags(work_id),
                               reasons=work_tag_reasons(work_id), categories=categories())
    return redirect(url_for(".work_page", work_id=work_id) + "#tags")


def set_cw(c, tag_id, on):
    if on:
        c.execute("INSERT OR IGNORE INTO cw_setting(tag_id) VALUES (?)", (tag_id,))
    else:
        c.execute("DELETE FROM cw_setting WHERE tag_id = ?", (tag_id,))


def read_category_id(raw):
    """A category id from a form, or None for Uncategorized (and for anything unknown)."""
    if raw and raw.isdigit() and db().execute("SELECT 1 FROM tag_category WHERE id = ?", (int(raw),)).fetchone():
        return int(raw)
    return None


@bp.post("/works/<int:work_id>/tags")
def work_tag_add(work_id):
    get_work_or_404(work_id)
    name = clean_tag_name(request.form.get("name"))
    if name:
        with db() as c:
            tag_id = find_or_create_tag(c, name)
            c.execute("INSERT OR IGNORE INTO work_tag(work_id, tag_id) VALUES (?, ?)", (work_id, tag_id))
    return after_work_tags(work_id)


@bp.post("/works/<int:work_id>/tags/<int:tag_id>")
def work_tag_update(work_id, tag_id):
    """The pop-up on a tag: the tag's category and CW (shared by every work), and this work's reason."""
    get_work_or_404(work_id)
    get_tag_or_404(tag_id)
    reason = (request.form.get("reason") or "").strip() or None
    with db() as c:
        c.execute("UPDATE tag SET category_id = ? WHERE id = ?", (read_category_id(request.form.get("category")), tag_id))
        set_cw(c, tag_id, request.form.get("cw") == "1")
        c.execute("UPDATE work_tag SET justification_md = ? WHERE work_id = ? AND tag_id = ?", (reason, work_id, tag_id))
    return after_work_tags(work_id)


@bp.post("/works/<int:work_id>/tags/<int:tag_id>/remove")
def work_tag_remove(work_id, tag_id):
    get_work_or_404(work_id)
    with db() as c:
        c.execute("DELETE FROM work_tag WHERE work_id = ? AND tag_id = ?", (work_id, tag_id))
    return after_work_tags(work_id)


@bp.get("/tags")
def tags_page():
    c = db()
    groups = [{"category": cat, "tags": []} for cat in categories()]
    by_id = {g["category"]["id"]: g for g in groups}
    loose = {"category": None, "tags": []}
    uses = dict(c.execute("SELECT tag_id, COUNT(*) FROM work_tag GROUP BY tag_id").fetchall())
    for t in c.execute(f"{TAG_SELECT} ORDER BY t.name COLLATE NOCASE"):
        by_id.get(t["category_id"], loose)["tags"].append({**dict(t), "uses": uses.get(t["id"], 0)})
    if loose["tags"]:
        groups.append(loose)
    return render_template("tags.html", groups=groups)


@bp.post("/tags")
def tag_create():
    """Find or create a tag by name and open its page."""
    name = clean_tag_name(request.form.get("name"))
    if not name:
        return redirect(url_for(".tags_page"))
    with db() as c:
        tag_id = find_or_create_tag(c, name)
    return redirect(url_for(".tag_page", tag_id=tag_id))


@bp.get("/tags/<int:tag_id>")
def tag_page(tag_id):
    tag = get_tag_or_404(tag_id)
    c = db()
    works = c.execute("""SELECT w.id, w.title, i.file_path AS cover_path, f.label AS format_label, wt.justification_md
                         FROM work_tag wt JOIN work w ON w.id = wt.work_id
                         JOIN format f ON f.code = w.format_code
                         LEFT JOIN image i ON i.id = w.cover_image_id
                         WHERE wt.tag_id = ? ORDER BY w.title COLLATE NOCASE""", (tag_id,)).fetchall()
    aliases = [r[0] for r in c.execute("SELECT alias FROM tag_alias WHERE tag_id = ? ORDER BY alias COLLATE NOCASE", (tag_id,))]
    parent = get_tag_or_404(tag["parent_id"]) if tag["parent_id"] else None
    children = c.execute(f"{TAG_SELECT} WHERE t.parent_id = ? ORDER BY t.name COLLATE NOCASE", (tag_id,)).fetchall()
    return render_template("tag.html", tag=tag, works=works, aliases=aliases, parent=parent,
                           children=children, categories=categories())


@bp.post("/tags/<int:tag_id>")
def tag_update(tag_id):
    tag = get_tag_or_404(tag_id)
    name = clean_tag_name(request.form.get("name")) or tag["name"]
    other = find_tag(name)
    if other and other != tag_id:
        flash(f"There's already a tag or alias called “{name}”, so the name wasn't changed.")
        name = tag["name"]
    with db() as c:
        # Renaming a tag to one of its own aliases swaps them: the alias goes, since a name and alias can't match.
        c.execute("DELETE FROM tag_alias WHERE alias = ? AND tag_id = ?", (name, tag_id))
        c.execute("UPDATE tag SET name = ?, category_id = ?, description_md = ? WHERE id = ?",
                  (name, read_category_id(request.form.get("category")),
                   (request.form.get("description_md") or "").strip() or None, tag_id))
        set_cw(c, tag_id, request.form.get("cw") == "1")
    return redirect(url_for(".tag_page", tag_id=tag_id))


@bp.post("/tags/<int:tag_id>/delete")
def tag_delete(tag_id):
    tag = get_tag_or_404(tag_id)
    with db() as c:
        c.execute("DELETE FROM tag WHERE id = ?", (tag_id,))
    flash(f"Deleted the tag {tag['name']}.")
    return redirect(url_for(".tags_page"))


def read_category_form(errors, current_id=None):
    name = " ".join((request.form.get("name") or "").split())[:60]
    color = (request.form.get("color") or "").lower()
    if not name:
        errors.append("A category needs a name.")
    elif db().execute("SELECT 1 FROM tag_category WHERE name = ? AND id IS NOT ?", (name, current_id)).fetchone():
        errors.append(f"There's already a category called “{name}”.")
    if not HEX_COLOR.fullmatch(color):
        color = UNCATEGORIZED_COLOR
    return name, color, (request.form.get("description_md") or "").strip() or None


@bp.post("/categories")
def category_create():
    errors = []
    name, color, description = read_category_form(errors)
    if errors:
        flash(errors[0])
        return redirect(url_for(".tags_page"))
    with db() as c:
        cat_id = c.execute("""INSERT INTO tag_category(name, color, description_md, position)
                              VALUES (?, ?, ?, (SELECT coalesce(max(position) + 1, 0) FROM tag_category))""",
                           (name, color, description)).lastrowid
    return redirect(url_for(".tags_page") + f"#category-{cat_id}")


@bp.post("/categories/<int:cat_id>")
def category_update(cat_id):
    if not db().execute("SELECT 1 FROM tag_category WHERE id = ?", (cat_id,)).fetchone():
        abort(404)
    errors = []
    name, color, description = read_category_form(errors, cat_id)
    if errors:
        flash(errors[0] + " Nothing was changed.")
    else:
        with db() as c:
            c.execute("UPDATE tag_category SET name = ?, color = ?, description_md = ? WHERE id = ?",
                      (name, color, description, cat_id))
    return redirect(url_for(".tags_page") + f"#category-{cat_id}")


@bp.post("/categories/<int:cat_id>/delete")
def category_delete(cat_id):
    row = db().execute("SELECT name FROM tag_category WHERE id = ?", (cat_id,)).fetchone()
    if row is None:
        abort(404)
    with db() as c:
        c.execute("DELETE FROM tag_category WHERE id = ?", (cat_id,))
    flash(f"Deleted the category {row['name']}. Its tags are now Uncategorized.")
    return redirect(url_for(".tags_page"))


@bp.post("/categories/order")
def category_order():
    """Categories in the order they were dragged into; any left out keep their place after them."""
    known = [r[0] for r in db().execute("SELECT id FROM tag_category ORDER BY position, name")]
    sent = [int(x) for x in request.form.getlist("order") if x.isdigit() and int(x) in known]
    with db() as c:
        for pos, cat_id in enumerate(dict.fromkeys(sent + known)):
            c.execute("UPDATE tag_category SET position = ? WHERE id = ?", (pos, cat_id))
    if request.headers.get("X-Partial"):
        return "", 204
    return redirect(url_for(".tags_page"))


# ------------------------------------------------------------------ files

CHANGELOG_PATH = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def hide_empty_unreleased(text):
    """Drop the "Unreleased" heading when nothing has been added under it yet."""
    return re.sub(r"^## Unreleased\s*(?=^## |\Z)", "", text, flags=re.M)


@bp.get("/changelog")
def changelog():
    text = hide_empty_unreleased(CHANGELOG_PATH.read_text(encoding="utf-8"))
    return render_template("changelog.html", text=text)


@bp.get("/credits")
def credits():
    return render_template("credits.html")


@bp.get("/media/<path:rel>")
def media(rel):
    # Only files inside images/ are served. Reject any "..", backslash or empty part outright,
    # because normalizing "images/../journal.db" would otherwise reach the database.
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
