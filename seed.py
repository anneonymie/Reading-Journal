"""Fill a separate demo folder with invented sample works, for trying the app out.

    python seed.py [folder]      (default folder: journal-demo)

Then start the app with JOURNAL_DATA set to that folder. Never touches your real journal-data.
"""
import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from werkzeug.datastructures import FileStorage

from journal import create_app
from journal.db import connect
from journal.images import store_image
from journal.views import add_status_change


def picture(w, h, a, b, label=None):
    img = Image.new("RGB", (w, h), a)
    d = ImageDraw.Draw(img)
    for i in range(0, h, 6):
        t = i / h
        d.line([(0, i), (w, i)], fill=tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3)), width=6)
    for x in range(0, w, 14):
        for y in range(0, h, 14):
            d.ellipse([x, y, x + 3, y + 3], fill=tuple(min(255, c + 25) for c in b))
    if label:
        d.rectangle([12, h - 40, 12 + 9 * len(label), h - 14], fill=(255, 255, 255))
        d.text((18, h - 36), label, fill=(20, 20, 30))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return FileStorage(buf, filename=f"{label or 'image'}.png")


WORKS = [
    dict(title="The Lantern Keeper's Apprentice", fmt="manga", unit="chapter", total=None,
         authors=["Mori Aki"], status=["tbr", "reading"], colors=((40, 60, 110), (230, 170, 60)),
         entries=[("Picked this up from a recommendation. The **first chapter** is gorgeous.", 1, 2),
                  ("The mentor reveal in this arc! ||She knew all along.||", 8, 1),
                  ("Slower chapter, mostly worldbuilding about the lantern guilds.", 12, 0),
                  (None, 15, 1)]),
    dict(title="Salt & Static", fmt="manhwa", unit="chapter", total=88,
         authors=["Han Yerin"], status=["reading"], colors=((20, 90, 90), (200, 230, 220)),
         entries=[("Art style takes a minute to get used to, but the paneling is clever.", 4, 1),
                  ("Logged this one in volumes by mistake.", 2, 0, "volume"),
                  ("Halfway. The radio-tower episode made me tear up.", 44, 2)]),
    dict(title="Moonlit Ledger", fmt="light_novel", unit="volume", total=12,
         authors=["Kisaragi Tomo"], artists=["Natsume Ren"], status=["reading", "paused"],
         colors=((70, 40, 90), (240, 200, 220)),
         entries=[("Volume 1 is all setup, but the ledger magic system is fun.", 1, 0),
                  ("Pausing until the next translated volume comes out.", 3, 0)]),
    dict(title="Second Spring at Hanamura High", fmt="manga", unit="chapter", total=64,
         authors=["Aoyama Sei"], status=["reading", "completed", "reading"], colors=((230, 120, 140), (255, 240, 200)),
         rating=9.5, review="Comfort read. The ending is earned.",
         entries=[("Rereading this because I missed these kids.", 6, 1)]),
    dict(title="Paper Cranes Over Kessler Street", fmt="fanfic", unit="chapter", total=None,
         authors=["inkwellwren"], status=["completed"], colors=((240, 240, 235), (120, 130, 150)),
         entries=[]),
]


def main():
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "journal-demo")
    if folder.resolve() == (Path(__file__).resolve().parent / "journal-data").resolve():
        sys.exit("Refusing to seed the real journal-data folder.")
    app = create_app(folder)
    c = connect(app.config["DB_PATH"])
    try:
        seed(app, c, folder)
    finally:
        c.close()
    print(f"Seeded {len(WORKS)} sample works into {folder.resolve()}")


def seed(app, c, folder):
    if c.execute("SELECT COUNT(*) FROM work").fetchone()[0]:
        sys.exit(f"{folder} already has works; delete the folder to re-seed.")
    data = app.config["DATA_DIR"]
    with app.app_context(), c:
        day = 0
        for spec in WORKS:
            a, b = spec["colors"]
            cover = store_image(c, data, picture(300, 450, a, b))
            wid = c.execute(
                "INSERT INTO work(title, format_code, length_unit, length_total, cover_image_id, rating, review_md) VALUES (?,?,?,?,?,?,?)",
                (spec["title"], spec["fmt"], spec["unit"], spec["total"], cover, spec.get("rating"), spec.get("review"))).lastrowid
            for role in ("authors", "artists"):
                for name in spec.get(role, []):
                    c.execute("INSERT OR IGNORE INTO creator(name) VALUES (?)", (name,))
                    cid = c.execute("SELECT id FROM creator WHERE name = ?", (name,)).fetchone()[0]
                    c.execute("INSERT INTO work_creator VALUES (?,?,?)", (wid, cid, role[:-1]))
            old = None
            for s in spec["status"]:
                day += 1
                add_status_change(c, wid, old, s, f"2026-09-{day:02d}T10:00:00Z")
                old = s
            if spec["title"].startswith("Second Spring"):
                c.execute("UPDATE work SET progress_current = 0 WHERE id = ?", (wid,))
            for i, entry in enumerate(spec["entries"]):
                body, prog, shots = entry[:3]
                unit = entry[3] if len(entry) > 3 else spec["unit"]
                day += 1
                eid = c.execute(
                    "INSERT INTO journal_entry(work_id, body_md, posted_at, progress_value, progress_unit) VALUES (?,?,?,?,?)",
                    (wid, body, f"2026-{9 + day // 30:02d}-{day % 30 + 1:02d}T{20 + i % 3}:15:00Z", prog, unit)).lastrowid
                for n in range(shots):
                    img = store_image(c, data, picture(720, 1000 if n % 2 else 520, b, a, f"p{eid}-{n}"))
                    c.execute("INSERT INTO journal_entry_image VALUES (?,?,?)", (eid, img, n))


if __name__ == "__main__":
    main()
