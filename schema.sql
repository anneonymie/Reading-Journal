-- Reading Journal schema, draft 2
-- Requires SQLite 3.43+ (STRICT tables, FTS5 trigram tokenizer, contentless_delete)
--
-- Conventions
--   * Timestamps used for ordering are UTC text in exactly this shape:
--     2026-10-18T14:03:00Z  (enforced, so sorting is always correct)
--   * Prose fields end in _md and hold Markdown
--   * Image files live in the data folder; only relative paths are stored here
--
-- IMPORTANT FOR THE APP: SQLite only enforces foreign keys when each
-- connection runs  PRAGMA foreign_keys = ON;  The app must do this on every
-- connection it opens. The line below only covers the connection that
-- creates the database.

PRAGMA foreign_keys = ON;

-- ============================================================
-- Lookups (editable lists the app reads from)
-- ============================================================

CREATE TABLE progress_unit (
    code        TEXT PRIMARY KEY,          -- 'chapter'
    singular    TEXT NOT NULL,             -- 'chapter'
    plural      TEXT NOT NULL,             -- 'chapters'
    abbrev      TEXT NOT NULL              -- 'Ch'
) STRICT;

INSERT INTO progress_unit VALUES
    ('chapter', 'chapter', 'chapters', 'Ch'),
    ('volume',  'volume',  'volumes',  'Vol'),
    ('page',    'page',    'pages',    'p'),
    ('episode', 'episode', 'episodes', 'Ep'),
    ('percent', 'percent', 'percent',  '%');

CREATE TABLE format (
    code         TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    default_unit TEXT NOT NULL REFERENCES progress_unit(code),  -- pre-selected when adding a work
    sort_order   INTEGER NOT NULL
) STRICT;

INSERT INTO format VALUES
    ('manga',       'Manga',       'chapter', 1),
    ('manhwa',      'Manhwa',      'chapter', 2),
    ('manhua',      'Manhua',      'chapter', 3),
    ('webcomic',    'Webcomic',    'chapter', 4),
    ('comic',       'Comic',       'chapter', 5),
    ('light_novel', 'Light Novel', 'volume',  6),
    ('web_novel',   'Web Novel',   'chapter', 7),
    ('novel',       'Novel',       'page',    8),
    ('fanfic',      'Fanfic',      'chapter', 9),
    ('other',       'Other',       'chapter', 10);

CREATE TABLE status (
    code        TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    sort_order  INTEGER NOT NULL
) STRICT;

INSERT INTO status VALUES
    ('tbr',       'TBR',               1),
    ('reading',   'Currently Reading', 2),
    ('paused',    'Paused',            3),
    ('completed', 'Completed',         4),
    ('dropped',   'Dropped',           5);

CREATE TABLE source (
    code         TEXT PRIMARY KEY,         -- 'anilist'
    name         TEXT NOT NULL,            -- 'AniList'
    url_template TEXT                      -- 'https://anilist.co/manga/{id}'
) STRICT;

INSERT INTO source VALUES
    ('anilist',      'AniList',      'https://anilist.co/manga/{id}'),
    ('mangaupdates', 'MangaUpdates', 'https://www.mangaupdates.com/series/{id}'),
    ('ao3',          'AO3',          'https://archiveofourown.org/works/{id}');

CREATE TABLE relation_type (
    code          TEXT PRIMARY KEY,
    label         TEXT NOT NULL,           -- shown on the "from" work
    inverse_label TEXT NOT NULL,           -- shown on the "to" work
    symmetric     INTEGER NOT NULL DEFAULT 0 CHECK (symmetric IN (0,1))
) STRICT;

INSERT INTO relation_type VALUES
    ('adaptation_of', 'Adaptation of',   'Adapted as',      0),
    ('prequel_of',    'Prequel of',      'Sequel of',       0),
    ('side_story_of', 'Side story of',   'Has side story',  0),
    ('same_universe', 'Same universe as','Same universe as',1),
    ('fanfic_of',     'Fanfic of',       'Has fanfic',      0);

-- ============================================================
-- Images (files on disk, metadata here)
-- ============================================================

CREATE TABLE image (
    id            INTEGER PRIMARY KEY,
    file_path     TEXT NOT NULL UNIQUE     -- relative to the data folder: images/ab/abcd1234.png
                  -- must stay relative and inside the data folder; forward slashes only
                  CHECK (file_path <> '' AND substr(file_path, 1, 1) <> '/'
                         AND instr(file_path, '..') = 0 AND instr(file_path, '\') = 0
                         AND instr(file_path, ':') = 0),
    sha256        TEXT NOT NULL UNIQUE,    -- the same image uploaded twice is stored once
    mime_type     TEXT NOT NULL,
    width         INTEGER,
    height        INTEGER,
    original_name TEXT,
    alt_text      TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
) STRICT;

-- ============================================================
-- Works
-- ============================================================

CREATE TABLE work (
    id               INTEGER PRIMARY KEY,
    title            TEXT NOT NULL,
    format_code      TEXT NOT NULL REFERENCES format(code),
    description_md   TEXT,
    cover_image_id   INTEGER REFERENCES image(id) ON DELETE SET NULL,
    publisher        TEXT,
    pub_start        TEXT,                 -- date or partial date: '2019' or '2019-04'
    pub_end          TEXT,
    pub_status       TEXT CHECK (pub_status IN ('ongoing','completed','hiatus','cancelled')),

    -- Length: unit is required, total is optional (ongoing series)
    length_unit      TEXT NOT NULL DEFAULT 'chapter' REFERENCES progress_unit(code),
    length_total     REAL CHECK (length_total > 0),

    -- Current progress is a series property, always in length_unit
    progress_current REAL CHECK (progress_current >= 0),

    -- 0.0 to 10.0 in steps of 0.1
    rating           REAL CHECK (rating BETWEEN 0 AND 10 AND round(rating * 10) = rating * 10),
    review_md        TEXT,
    notes_md         TEXT,                 -- "where I'm at" notes

    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
) STRICT;

-- Keep updated_at current on any change. (Recursive triggers are off by
-- default in SQLite, so this does not re-fire itself.)
CREATE TRIGGER work_touch
AFTER UPDATE ON work
WHEN NEW.updated_at IS OLD.updated_at
BEGIN
    UPDATE work SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = NEW.id;
END;

CREATE TABLE work_alt_title (
    id        INTEGER PRIMARY KEY,
    work_id   INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    title     TEXT NOT NULL,
    language  TEXT,                        -- 'ja', 'ja-Latn', 'en'
    UNIQUE (work_id, title)
) STRICT;

CREATE TABLE creator (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE
) STRICT;

CREATE TABLE work_creator (
    work_id    INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    creator_id INTEGER NOT NULL REFERENCES creator(id) ON DELETE CASCADE,
    role       TEXT NOT NULL DEFAULT 'author',   -- author, artist, translator, original creator
    PRIMARY KEY (work_id, creator_id, role)
) STRICT;

-- Source IDs: one ID per source per work, and an ID can't be on two works
CREATE TABLE work_source_id (
    work_id     INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    source_code TEXT NOT NULL REFERENCES source(code),
    external_id TEXT NOT NULL,
    PRIMARY KEY (work_id, source_code),
    UNIQUE (source_code, external_id)
) STRICT;

CREATE TABLE work_relation (
    from_work_id  INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    to_work_id    INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    relation_code TEXT NOT NULL REFERENCES relation_type(code),
    note_md       TEXT,
    PRIMARY KEY (from_work_id, to_work_id, relation_code),
    CHECK (from_work_id <> to_work_id)
) STRICT;

-- For symmetric relations (same universe), A→B and B→A would be duplicates
CREATE TRIGGER work_relation_symmetric_dup
BEFORE INSERT ON work_relation
WHEN (SELECT symmetric FROM relation_type WHERE code = NEW.relation_code) = 1
 AND EXISTS (SELECT 1 FROM work_relation
             WHERE from_work_id = NEW.to_work_id
               AND to_work_id = NEW.from_work_id
               AND relation_code = NEW.relation_code)
BEGIN
    SELECT RAISE(ABORT, 'this relation already exists in the other direction');
END;

-- Custom fields (e.g. "Platform")
CREATE TABLE custom_field (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    value_type TEXT NOT NULL CHECK (value_type IN ('text','number','date','boolean','choice','url')),
    sort_order INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE custom_field_choice (
    field_id INTEGER NOT NULL REFERENCES custom_field(id) ON DELETE CASCADE,
    value    TEXT NOT NULL,
    PRIMARY KEY (field_id, value)
) STRICT;

CREATE TABLE work_custom_value (
    work_id  INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    field_id INTEGER NOT NULL REFERENCES custom_field(id) ON DELETE CASCADE,
    value    TEXT NOT NULL,                -- text/number/date/boolean/url are validated by the app
    PRIMARY KEY (work_id, field_id)
) STRICT;

-- Choice fields only accept one of their defined choices
CREATE TRIGGER custom_value_choice_ins
BEFORE INSERT ON work_custom_value
WHEN (SELECT value_type FROM custom_field WHERE id = NEW.field_id) = 'choice'
 AND NOT EXISTS (SELECT 1 FROM custom_field_choice WHERE field_id = NEW.field_id AND value = NEW.value)
BEGIN
    SELECT RAISE(ABORT, 'value is not one of this field''s choices');
END;

CREATE TRIGGER custom_value_choice_upd
BEFORE UPDATE ON work_custom_value
WHEN (SELECT value_type FROM custom_field WHERE id = NEW.field_id) = 'choice'
 AND NOT EXISTS (SELECT 1 FROM custom_field_choice WHERE field_id = NEW.field_id AND value = NEW.value)
BEGIN
    SELECT RAISE(ABORT, 'value is not one of this field''s choices');
END;

-- ============================================================
-- Status history
-- ============================================================

CREATE TABLE status_event (
    id          INTEGER PRIMARY KEY,
    work_id     INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    status_code TEXT NOT NULL REFERENCES status(code),
    changed_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
                CHECK (changed_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z')
) STRICT;

CREATE INDEX status_event_work ON status_event(work_id, changed_at);

-- Current status = most recent event (ties broken by insertion order)
CREATE VIEW work_current_status AS
SELECT w.id AS work_id, se.status_code, se.changed_at
FROM work w
LEFT JOIN status_event se ON se.id = (
    SELECT id FROM status_event
    WHERE work_id = w.id
    ORDER BY changed_at DESC, id DESC
    LIMIT 1
);

-- Times a work has been completed (rereads = completions - 1)
CREATE VIEW work_completion_count AS
SELECT work_id, COUNT(*) AS completions
FROM status_event
WHERE status_code = 'completed'
GROUP BY work_id;

-- ============================================================
-- Journal (one journal per work)
-- ============================================================

CREATE TABLE journal_entry (
    id              INTEGER PRIMARY KEY,
    work_id         INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL DEFAULT 'note' CHECK (kind IN ('note','status')),
    body_md         TEXT,
    posted_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
                    CHECK (posted_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z'),
    edited_at       TEXT
                    CHECK (edited_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z'),

    -- Progress snapshot. The unit is stored per entry so a later change
    -- to the series unit never loses data.
    progress_value  REAL CHECK (progress_value >= 0),
    progress_unit   TEXT REFERENCES progress_unit(code),

    -- Status entries are a log of the change, not a link that controls it.
    -- Deleting the entry leaves the status_event alone; deleting the
    -- status_event leaves this entry (and its snapshot) alone.
    status_event_id INTEGER REFERENCES status_event(id) ON DELETE SET NULL,
    status_from     TEXT REFERENCES status(code),
    status_to       TEXT REFERENCES status(code),

    -- Import provenance (Discord message ID etc.) so re-running an import never duplicates
    import_source   TEXT,
    import_ref      TEXT,

    CHECK ((progress_value IS NULL) = (progress_unit IS NULL)),
    CHECK (kind = 'status' OR (status_event_id IS NULL AND status_from IS NULL AND status_to IS NULL)),
    CHECK (kind = 'note'   OR status_to IS NOT NULL),
    CHECK ((import_source IS NULL) = (import_ref IS NULL)),
    UNIQUE (import_source, import_ref)
) STRICT;

CREATE INDEX journal_entry_work ON journal_entry(work_id, posted_at);

-- Entries whose unit doesn't match the series are flagged (0) and ignored
CREATE VIEW journal_entry_progress AS
SELECT je.id AS entry_id,
       je.work_id,
       je.progress_value,
       je.progress_unit,
       w.length_unit AS series_unit,
       CASE
           WHEN je.progress_value IS NULL THEN NULL
           WHEN je.progress_unit = w.length_unit THEN 1
           ELSE 0
       END AS progress_valid
FROM journal_entry je
JOIN work w ON w.id = je.work_id;

-- One-time progress update: creating or editing an entry so its progress
-- is farther along (same unit) moves the series forward. Deleting does nothing.
CREATE TRIGGER journal_progress_after_insert
AFTER INSERT ON journal_entry
WHEN NEW.progress_value IS NOT NULL
BEGIN
    UPDATE work
    SET progress_current = NEW.progress_value
    WHERE id = NEW.work_id
      AND length_unit = NEW.progress_unit
      AND (progress_current IS NULL OR progress_current < NEW.progress_value);
END;

CREATE TRIGGER journal_progress_after_update
AFTER UPDATE OF progress_value, progress_unit ON journal_entry
WHEN NEW.progress_value IS NOT NULL
 AND (NEW.progress_value IS NOT OLD.progress_value OR NEW.progress_unit IS NOT OLD.progress_unit)
BEGIN
    UPDATE work
    SET progress_current = NEW.progress_value
    WHERE id = NEW.work_id
      AND length_unit = NEW.progress_unit
      AND (progress_current IS NULL OR progress_current < NEW.progress_value);
END;

CREATE TABLE journal_entry_image (
    entry_id INTEGER NOT NULL REFERENCES journal_entry(id) ON DELETE CASCADE,
    image_id INTEGER NOT NULL REFERENCES image(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (entry_id, image_id)
) STRICT;

-- Gallery: highlighted images per work
CREATE TABLE work_gallery (
    work_id    INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    image_id   INTEGER NOT NULL REFERENCES image(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL DEFAULT 0,
    caption_md TEXT,
    PRIMARY KEY (work_id, image_id)
) STRICT;

-- ============================================================
-- Tags (one shared pool for works and images)
-- ============================================================

CREATE TABLE tag (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE COLLATE NOCASE,
    category       TEXT NOT NULL DEFAULT 'misc'
                   CHECK (category IN ('genre','trope','device','misc')),
    parent_id      INTEGER REFERENCES tag(id) ON DELETE SET NULL,
    description_md TEXT,
    CHECK (parent_id IS NULL OR parent_id <> id)
) STRICT;

-- Every tag paired with itself and each of its ancestors (depth 0 = itself)
CREATE VIEW tag_ancestor AS
WITH RECURSIVE up(tag_id, ancestor_id, depth) AS (
    SELECT id, id, 0 FROM tag
    UNION
    SELECT up.tag_id, t.parent_id, up.depth + 1
    FROM up JOIN tag t ON t.id = up.ancestor_id
    WHERE t.parent_id IS NOT NULL AND up.depth < 50
)
SELECT tag_id, ancestor_id, depth FROM up;

-- Nesting can't loop (A inside B inside A)
CREATE TRIGGER tag_parent_no_cycle
BEFORE UPDATE OF parent_id ON tag
WHEN NEW.parent_id IS NOT NULL
 AND EXISTS (SELECT 1 FROM tag_ancestor WHERE tag_id = NEW.parent_id AND ancestor_id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'a tag cannot be nested inside itself or its own children');
END;

-- Aliases resolve to a canonical tag; an alias can't also be a tag name
CREATE TABLE tag_alias (
    alias  TEXT PRIMARY KEY COLLATE NOCASE,
    tag_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE
) STRICT;

CREATE TRIGGER tag_alias_no_clash_ins
BEFORE INSERT ON tag_alias
WHEN EXISTS (SELECT 1 FROM tag WHERE name = NEW.alias)
BEGIN
    SELECT RAISE(ABORT, 'alias matches an existing tag name');
END;

CREATE TRIGGER tag_alias_no_clash_upd
BEFORE UPDATE OF alias ON tag_alias
WHEN EXISTS (SELECT 1 FROM tag WHERE name = NEW.alias)
BEGIN
    SELECT RAISE(ABORT, 'alias matches an existing tag name');
END;

CREATE TRIGGER tag_name_no_clash_ins
BEFORE INSERT ON tag
WHEN EXISTS (SELECT 1 FROM tag_alias WHERE alias = NEW.name)
BEGIN
    SELECT RAISE(ABORT, 'tag name matches an existing alias');
END;

CREATE TRIGGER tag_name_no_clash_upd
BEFORE UPDATE OF name ON tag
WHEN EXISTS (SELECT 1 FROM tag_alias WHERE alias = NEW.name)
BEGIN
    SELECT RAISE(ABORT, 'tag name matches an existing alias');
END;

-- A tag is a content warning if it has a row here. Display settings live here too.
CREATE TABLE cw_setting (
    tag_id     INTEGER PRIMARY KEY REFERENCES tag(id) ON DELETE CASCADE,
    blur       INTEGER NOT NULL DEFAULT 1 CHECK (blur IN (0,1)),
    badge      INTEGER NOT NULL DEFAULT 1 CHECK (badge IN (0,1)),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1))
) STRICT;

-- Per-work tagging with an optional justification
CREATE TABLE work_tag (
    work_id          INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    tag_id           INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    justification_md TEXT,                 -- "the side couple in Ch. 64 begin as rivals"
    PRIMARY KEY (work_id, tag_id)
) STRICT;

CREATE INDEX work_tag_tag ON work_tag(tag_id);

CREATE TABLE image_tag (
    image_id INTEGER NOT NULL REFERENCES image(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    PRIMARY KEY (image_id, tag_id)
) STRICT;

CREATE INDEX image_tag_tag ON image_tag(tag_id);

-- CW display for any image: blur/badge if any of its tags, or their parents, is a CW.
-- Every screen that shows an image reads this, so the setting is consistent everywhere.
CREATE VIEW image_cw AS
SELECT it.image_id,
       MAX(cs.blur)  AS blur,
       MAX(cs.badge) AS badge,
       group_concat(DISTINCT t.name) AS cw_tags
FROM image_tag it
JOIN tag_ancestor ta ON ta.tag_id = it.tag_id
JOIN cw_setting cs   ON cs.tag_id = ta.ancestor_id
JOIN tag t           ON t.id = ta.ancestor_id
GROUP BY it.image_id;

-- Same for works (CW badges on library cards and work pages)
CREATE VIEW work_cw AS
SELECT wt.work_id,
       MAX(cs.blur)  AS blur,
       MAX(cs.badge) AS badge,
       group_concat(DISTINCT t.name) AS cw_tags
FROM work_tag wt
JOIN tag_ancestor ta ON ta.tag_id = wt.tag_id
JOIN cw_setting cs   ON cs.tag_id = ta.ancestor_id
JOIN tag t           ON t.id = ta.ancestor_id
GROUP BY wt.work_id;

-- Tag search index: names and aliases, trigram for fuzzy/substring matching
CREATE VIRTUAL TABLE tag_search USING fts5(
    term, tag_id UNINDEXED, is_alias UNINDEXED,
    tokenize = 'trigram'
);

CREATE TRIGGER tag_search_ins AFTER INSERT ON tag BEGIN
    INSERT INTO tag_search(term, tag_id, is_alias) VALUES (NEW.name, NEW.id, 0);
END;
CREATE TRIGGER tag_search_upd AFTER UPDATE OF name ON tag BEGIN
    DELETE FROM tag_search WHERE tag_id = NEW.id AND is_alias = 0;
    INSERT INTO tag_search(term, tag_id, is_alias) VALUES (NEW.name, NEW.id, 0);
END;
CREATE TRIGGER tag_search_del AFTER DELETE ON tag BEGIN
    DELETE FROM tag_search WHERE tag_id = OLD.id;
END;
CREATE TRIGGER tag_alias_search_ins AFTER INSERT ON tag_alias BEGIN
    INSERT INTO tag_search(term, tag_id, is_alias) VALUES (NEW.alias, NEW.tag_id, 1);
END;
CREATE TRIGGER tag_alias_search_upd AFTER UPDATE ON tag_alias BEGIN
    DELETE FROM tag_search WHERE tag_id = OLD.tag_id AND is_alias = 1 AND term = OLD.alias;
    INSERT INTO tag_search(term, tag_id, is_alias) VALUES (NEW.alias, NEW.tag_id, 1);
END;
CREATE TRIGGER tag_alias_search_del AFTER DELETE ON tag_alias BEGIN
    DELETE FROM tag_search WHERE tag_id = OLD.tag_id AND is_alias = 1 AND term = OLD.alias;
END;

-- Default content warnings (inserted after the search triggers so they're indexed)
INSERT INTO tag (name) VALUES ('Explicit sex'), ('Violence'), ('Sexual assault');
INSERT INTO cw_setting (tag_id, is_default)
    SELECT id, 1 FROM tag WHERE name IN ('Explicit sex','Violence','Sexual assault');

-- ============================================================
-- Lists
-- ============================================================

CREATE TABLE list (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description_md TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
) STRICT;

CREATE TABLE list_item (
    list_id  INTEGER NOT NULL REFERENCES list(id) ON DELETE CASCADE,
    work_id  INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    note_md  TEXT,                         -- why it's on the list
    position INTEGER NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (list_id, work_id)
) STRICT;

-- ============================================================
-- Full-text search: works and journal entries
-- ============================================================

-- What gets indexed for each work
CREATE VIEW work_search_source AS
SELECT w.id,
       w.title,
       (SELECT group_concat(title, ' | ') FROM work_alt_title WHERE work_id = w.id) AS alt_titles,
       (SELECT group_concat(c.name, ' | ')
          FROM work_creator wc JOIN creator c ON c.id = wc.creator_id
         WHERE wc.work_id = w.id) AS creators,
       w.description_md AS description,
       w.review_md      AS review,
       w.notes_md       AS notes
FROM work w;

CREATE VIRTUAL TABLE work_search USING fts5(
    title, alt_titles, creators, description, review, notes,
    content = '',                          -- index only; text stays in the real tables
    contentless_delete = 1,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- Kept in sync automatically: any change to a work, its alt titles or its
-- creators re-indexes that work (rowid = work.id)
CREATE TRIGGER work_search_ins AFTER INSERT ON work BEGIN
    INSERT INTO work_search(rowid, title, alt_titles, creators, description, review, notes)
        SELECT * FROM work_search_source WHERE id = NEW.id;
END;
CREATE TRIGGER work_search_upd AFTER UPDATE OF title, description_md, review_md, notes_md ON work BEGIN
    DELETE FROM work_search WHERE rowid = NEW.id;
    INSERT INTO work_search(rowid, title, alt_titles, creators, description, review, notes)
        SELECT * FROM work_search_source WHERE id = NEW.id;
END;
CREATE TRIGGER work_search_del AFTER DELETE ON work BEGIN
    DELETE FROM work_search WHERE rowid = OLD.id;
END;

CREATE TRIGGER work_search_alt_ins AFTER INSERT ON work_alt_title BEGIN
    DELETE FROM work_search WHERE rowid = NEW.work_id;
    INSERT INTO work_search(rowid, title, alt_titles, creators, description, review, notes)
        SELECT * FROM work_search_source WHERE id = NEW.work_id;
END;
CREATE TRIGGER work_search_alt_upd AFTER UPDATE ON work_alt_title BEGIN
    DELETE FROM work_search WHERE rowid IN (OLD.work_id, NEW.work_id);
    INSERT INTO work_search(rowid, title, alt_titles, creators, description, review, notes)
        SELECT * FROM work_search_source WHERE id IN (OLD.work_id, NEW.work_id);
END;
CREATE TRIGGER work_search_alt_del AFTER DELETE ON work_alt_title BEGIN
    DELETE FROM work_search WHERE rowid = OLD.work_id;
    INSERT INTO work_search(rowid, title, alt_titles, creators, description, review, notes)
        SELECT * FROM work_search_source WHERE id = OLD.work_id;
END;

CREATE TRIGGER work_search_wc_ins AFTER INSERT ON work_creator BEGIN
    DELETE FROM work_search WHERE rowid = NEW.work_id;
    INSERT INTO work_search(rowid, title, alt_titles, creators, description, review, notes)
        SELECT * FROM work_search_source WHERE id = NEW.work_id;
END;
CREATE TRIGGER work_search_wc_upd AFTER UPDATE ON work_creator BEGIN
    DELETE FROM work_search WHERE rowid IN (OLD.work_id, NEW.work_id);
    INSERT INTO work_search(rowid, title, alt_titles, creators, description, review, notes)
        SELECT * FROM work_search_source WHERE id IN (OLD.work_id, NEW.work_id);
END;
CREATE TRIGGER work_search_wc_del AFTER DELETE ON work_creator BEGIN
    DELETE FROM work_search WHERE rowid = OLD.work_id;
    INSERT INTO work_search(rowid, title, alt_titles, creators, description, review, notes)
        SELECT * FROM work_search_source WHERE id = OLD.work_id;
END;

CREATE TRIGGER work_search_creator_upd AFTER UPDATE OF name ON creator BEGIN
    DELETE FROM work_search WHERE rowid IN (SELECT work_id FROM work_creator WHERE creator_id = NEW.id);
    INSERT INTO work_search(rowid, title, alt_titles, creators, description, review, notes)
        SELECT * FROM work_search_source
        WHERE id IN (SELECT work_id FROM work_creator WHERE creator_id = NEW.id);
END;

CREATE VIRTUAL TABLE journal_search USING fts5(
    body,
    content = 'journal_entry', content_rowid = 'id',
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER journal_search_ins AFTER INSERT ON journal_entry BEGIN
    INSERT INTO journal_search(rowid, body) VALUES (NEW.id, NEW.body_md);
END;
CREATE TRIGGER journal_search_del AFTER DELETE ON journal_entry BEGIN
    INSERT INTO journal_search(journal_search, rowid, body) VALUES ('delete', OLD.id, OLD.body_md);
END;
CREATE TRIGGER journal_search_upd AFTER UPDATE OF body_md ON journal_entry BEGIN
    INSERT INTO journal_search(journal_search, rowid, body) VALUES ('delete', OLD.id, OLD.body_md);
    INSERT INTO journal_search(rowid, body) VALUES (NEW.id, NEW.body_md);
END;

-- ============================================================
-- Emoji and settings
-- ============================================================

CREATE TABLE custom_emoji (
    shortcode TEXT PRIMARY KEY CHECK (shortcode <> '' AND shortcode NOT GLOB '*[^a-z0-9_+-]*'),
    image_id  INTEGER NOT NULL REFERENCES image(id),   -- an image in use as an emoji can't be deleted
    keywords  TEXT                         -- space-separated, for picker search
) STRICT;

CREATE TABLE app_setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

-- Schema version, for future migrations
PRAGMA user_version = 2;
