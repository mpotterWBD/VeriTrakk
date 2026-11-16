# VeriTrakk Changelog

VeriTrakk is versioned **x.y.z** ([semantic versioning](https://semver.org)):

| Part | Goes up when | Example |
|------|--------------|---------|
| **x** major | a change means older files or logs no longer work the way they did | a new file format |
| **y** minor | a new feature, with older files still working | a new log option |
| **z** patch | a fix, nothing new | a crash fixed |

The version lives in one place, `src/version.py`; the app's header and every
log PDF's footer show it. Each release gets a section below (newest first) and
a git tag `vX.Y.Z`.

---

## Unreleased

### App
- The version shows on the home screen under the name, and on the run screen
  under the logo's line (as well as in the header).

## 1.1.0 (2026-11-16)

### App
- **The logo in the app.** The home screen's left panel shows the Westbound
  Designs logo, drawn in text (Braille dots, in the logo's cyan) from
  `assets/logo_with_circle_nowords.svg`, sized to the panel. The matrix rain is
  gone.
- **Run screen.** The left panel has the logo in its top-left corner, a line
  under it, then the quest's name, file and progress. Like the panel's other
  lines, it's green clocked in and grey clocked out.
- **Narrower left panel** on the run and build screens: 52 columns, about the
  logo's width (it was 30% of the window). The home screen keeps 30%.
- **Cleaner logo drawing.** Each dot is lit by how much of it the logo covers, so
  edges are even; drawn small, the logo's two inner arrows are left out (they
  only blurred into the rest). Settings at the top of `src/logo_art.py`.

### Fixes
- The logo's right edge was cut off by a dot (its width was rounded down).

## 1.0.0 (2026-11-16)

The first numbered release. Everything before it is in the git history.

### Logging a work quest
- **One PDF per work quest.** Logging writes only `<quest>.wrkqstlog.pdf` (and a
  copy in `data/logs`); no `.wrkqstlog` / `.prcsslog` text files.
- **Nothing is deleted.** The quest file and the processes logged with it move
  into a folder beside the PDF, `<quest> Files`, so they can be opened again. The
  quest file there has its links pointed at the moved processes.
- **Log from the open quest.** The Logs button logs the finished work quest that's
  open (or the one Carry Over just finished), after a confirmation listing what
  will be written and moved. With nothing finished open, it opens the Logs browser,
  which now shows only logs (PDFs open in the PDF viewer; older text logs still open
  in the app).

### Linked processes in the quest's log
- Each completed process a quest links is included in the quest's PDF, under the
  task it was built from, in a plum box that holds that task too.
- A linked template that was never run, an unfinished process, or a missing file
  is left where it is and noted in the log as not logged.

### Reading the log
- **Groups kept together.** Under each parent, its plain children come first, then
  each child group whole.
- **Colors by level.** Parents are bold and larger, each level the next color down
  the tree (black, blue, brick red, ...); a child with no children of its own is in
  its parent's color, plain and smaller.
- All notes are one color (teal).
- **Carried-over tasks** (finished by Carry Over and handed to the next quest) are
  labelled CARRIED OVER, in gray, instead of looking done. Carry Over records this
  from 1.0.0 on.
- The Westbound Designs logo as a pale watermark on every page.
- Text size, watermark size and strength are settings at the top of
  `src/storage.py` (`PDF_TEXT_SCALE`, `PDF_WATERMARK_WIDTH`, `PDF_WATERMARK_STRENGTH`).

### App
- Long step labels wrap to the window width in the run and build trees instead of
  being cut off.
- The version shows in the header.

### Fixes
- Curly quotes, dashes and other characters outside Latin-1 no longer stop a PDF
  being written (they print as the font's own, or `?`).
- A completed one-off (non-template) linked process is logged with its quest.
