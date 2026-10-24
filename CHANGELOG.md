# Changelog
Updates to the Reading Journal app. The current app version appears at the bottom of each page. And yes, this too is yaoi. 🍋

## Unreleased

- The changelog page no longer shows an empty "Unreleased" section when there's nothing new yet.
- On a work's page, the description now sits at the top under the creators, and alternate titles have moved into Details. The creators line reads "Manhwa by …" without a comma.
- Creators are added one person at a time: type their name, then tick Writer, Artist, both, or neither. Someone who did both is listed once as "(Writer and Artist)", and someone with neither ticked is listed by name alone. Writers are now labelled "(Writer)" on the work page.
- Marking a work Completed now sets its progress to the full length, when the total is known.
- Editing a journal entry no longer changes the work's progress, even if you change the entry's progress. This stops an old entry edited during a reread from jumping the work ahead. Only new entries move progress forward; to fix it, use Progress on the work's page.
- This version updates how your journal stores its data, so the first time it starts it saves a backup in `journal-data/backups` first.
- On the edit page, a red × on the cover removes it, with an Undo link until you save. Uploading a new cover still replaces the old one without needing the ×.

## 0.1.0 (2026-10-23)

The first numbered version of the journal. It can already:

- Keep a library of manga, novels and fanfic, with covers, authors and artists, other titles, and links to AniList, MangaUpdates and AO3.
- Hold a journal for each work: posts written in Markdown, with images and how far you've read.
- Track your reading status (reading, paused, completed and so on), with a choice to reset progress when you start a reread.
- Store a rating, a review and private notes for each work.
- Filter the library by status.
- Work from your phone over your home Wi-Fi.

New in this version:

- A notebook logo at the top of every page and on the browser tab.
- A footer on every page with links to the library, Add Work and this changelog, plus the version number.
- A clearer message when your library has no works yet, with a pointer to how to bring in an existing journal.
- Step-by-step instructions in the README for restoring a backup and moving your journal to a new computer.
- Safer updates. When a new version of the journal needs to change how your data is stored, it first saves a copy of your journal in `journal-data/backups`, then updates it automatically. If anything goes wrong, your journal is left exactly as it was.
- If your journal was last opened by a newer version of the app, an older version refuses to open it rather than risk damaging it.
