# Changelog
Updates to the Reading Journal app. The current app version appears at the bottom of each page. And yes, this too is yaoi. 🍋

## Unreleased

- Tags! Add them to a work from the Tags box on its page: start typing and pick a suggestion, or press Enter to create a new tag. Suggestions find other names for a tag (typing "yaoi" finds Boys' Love), forgive typos, and suggest tags you often use together.
- Click a tag on a work to choose its category, mark it as a content warning, or note why it applies to that work.
- Content warnings are listed separately from the other tags on a work's page.
- New Tags page, linked at the top: every tag grouped by category, with each category's description. Categories can be renamed, recolored, described, added, deleted and dragged into a new order.
- Each tag has its own page with its description, other names, the works that use it, and a link to show them in the library.
- The library can show just the works with one tag.
- The journal comes with a starter set of about 230 tags in nine categories, with names familiar from Goodreads, AO3, AniList and MangaUpdates. Your journal is updated to add them the first time you start this version, after saving a backup.

## 0.4.0 (2026-11-10)

- Implemented drag-and-drop to reorder images. In Javascript, all things are possible. 
- Edit Journal Entry: new images appear alongside the saved ones and can be placed anywhere among them before saving.
- Edit Journal Entry: a red × removes an image straight away instead of a Remove tick box. 
- Work pages: notes show as formatted text, with an Edit button to change them, like journal entries.
- Work pages: Edit Details is now a button to the right of the title.
- Work pages: the cover is larger in a wide browser window.
- New Credits page, linked from the footer, lists the logo, font and other borrowed work with their licenses.

## 0.3.0 (2026-10-25)

- New `dev.bat` for working on the app: it opens the sample journal and restarts by itself when the code changes, so there's no need to restart it by hand.
- Journal: horizontal lines (`---`) are now a subtle gray.
- Journal: a "You can use Markdown to format your entry" reference under the new entry box and on Edit Journal Entry, showing how to bold, italicize and more.
- Journal: images can be put in order with arrow buttons before posting, and on Edit Journal Entry.
- Work pages: Notes, Review and Details are always open.
- Work pages: the year it started publishing appears after the title, like "Wolf in the House (2017)".
- Work pages: "Status" is now "Reading status", here and on Add Work, so it isn't mixed up with publishing status.
- Work pages: changing the reading status to TBR asks whether to reset progress to 0.
- Work pages: "+ Add images" button label.
- Add/Edit Work: alternate titles are added one per box, with "+ Add another title".
- Add/Edit Work: a work can have several publishers, with "+ Add another publisher". Existing publishers carry over.
- Add/Edit Work: source links are now one list. Paste a link from AniList, MangaUpdates or AO3 and the journal works out which site it's from. Links have to be whole links now, not just the ID number.
- Add/Edit Work: Title and Format are marked with a red asterisk as required.
- Database now level 4. The first time this version starts, it saves a backup in `journal-data/backups` before updating.
- Add/Edit Work: Started and Ended have a year box and month list instead of free text, and Ended can't be before Started.
- Edit Journal Entry: renamed from "Edit entry". "+ Add images" now sits inside the Images box. Progress reads "[ ] of 55 chapters" (or "of ?" with no total). The date box is narrower.

## 0.2.0 (2026-10-23)

- Changelog page no longer shows an empty "Unreleased" section when there's nothing new yet.
- Work pages: description now sits at the top under the creators.
- Work pages: moved alternate titles into Details. 
- Work pages: removed comma from creators line.
- Add/Edit Work: Creators are now added one person at a time. Added boxes for Writer, Artist, both, or neither. Creator entries now properly combine multiple roles. When no roles are selected, nothing appears in the parentheses.
- Edit Work: replaced "Remove cover" tick box with red X on cover image. Same functionality, but clearer.
- Marking a work Completed now sets its progress to the full length, when the total is known.
- Reworked work progress adjustments via journal entries: before, editing entries updated progress. There were too many edge cases complicating this functionality, though, so now editing journal entries no longer effects work progress.
- Database now level 3. 📢

## 0.1.0 (2026-10-23)

The first numbered version of the journal. It can already:

- Keep a library of manga, novels and fanfic, with covers, authors and artists, other titles, and links to AniList, MangaUpdates and AO3.
- Hold a journal for each work: posts written in Markdown, with images and reading progress.
- Track reading status (reading, paused, completed and so on), with a choice to reset progress when status is changed from Complete to In Progress.
- Store a rating, a review and private notes for each work.
- Filter the library by status.
- Works from phone over home Wi-Fi.

Other goodies:

- Added a notebook logo at the top of every page and on the browser tab. on wednesdays we wear pink
- Added a footer with major links + this changelog and the version number.
- Clarified message clearer message that shows when the library has no works yet.
- Step-by-step instructions in the README for restoring a backup and moving journal to a new computer.
- Implemented better updates. When a new version of the journal needs to change how  data is stored, it first saves a copy of  journal in `journal-data/backups`, then updates it automatically. Ideally this means the data remains untouched if something goes wrong.
- Added app version control: if the journal was last opened by a newer version of the app, an older version refuses to open it rather than risk damaging it.
