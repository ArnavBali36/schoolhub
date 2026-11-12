# The day planner

Written 2026-11-08 from the learner's request: a calendar beside the list. The list moves to the left
and a day calendar sits on the right, from 5 AM to midnight by the hour. It has blocks for meals,
deep work, socializing and anything else. Each meal shows where to eat, from a weekly form (set
Sunday's lunch place once and every Sunday shows it). Every block can hold the work to get done in
it: assignments dragged in from the list, or the learner's own items. The search box goes, and Show
done becomes a quiet control.

"5am to 12pm" is read as 5 AM to 12 AM (midnight). Lunch at 4 PM and dinner at 6 PM only fit that
reading. The range is a setting.

## 1. What is kept

Everything lives under a new store name, `plan`, beside `marks` and `tasks`, one key per object:

| Key | Value |
|---|---|
| `settings` | `{day_start, day_end}` (hours, integers, defaults 5 and 24) |
| `week:sun` … `week:sat` | that weekday's template: `{meals, blocks}` |
| `day:YYYY-MM-DD` | that date's own changes and blocks: `{meals, blocks, repeats}` |

```jsonc
// week:<wd>
{
  "meals": {                       // all three always present after cleaning
    "breakfast": {"start": "11:00", "end": "12:00", "place": "", "off": false},
    "lunch":     {"start": "16:00", "end": "17:00", "place": "", "off": false},
    "dinner":    {"start": "18:00", "end": "19:00", "place": "", "off": false}
  },
  "blocks": [                      // repeating blocks: shown on every such weekday
    {"id": "r8c1d2e3f4", "type": "deep", "title": "Deep work", "start": "09:00", "end": "11:00"}
  ]
}
// day:<date>: every field optional; a missing week or day key means the defaults
{
  "meals": {                       // this date only; a field left out comes from the week
    "lunch": {"start": "16:30", "end": "17:30", "place": "…", "off": false, "items": [ITEM, …]}
  },
  "blocks": [                      // one-off blocks on this date
    {"id": "b1a2b3c4d5", "type": "social", "title": "Dinner with friends", "start": "19:00",
     "end": "21:00", "items": [ITEM, …]}
  ],
  "repeats": {                     // a repeating block's changes on this date, by its id
    "r8c1d2e3f4": {"start": "09:30", "end": "11:30", "skip": false, "items": [ITEM, …]}
  }
}
// ITEM: work to get done in a block
{"id": "i0a1b2c3d4", "kind": "work", "ref": "<assignment or task id>", "text": "<name when added>",
 "course": "<course name when added>", "done": false}
{"id": "i5e6f7a8b9", "kind": "own", "text": "Read chapter 3", "done": false}
```

**Defaults.** Breakfast is 11:00–12:00, lunch 16:00–17:00 and dinner 18:00–19:00, every place
empty, nothing off. The day runs 5 to 24.

**What shows on a date:**

- **Meals:** the date's override over the weekday's template over the defaults, field by field.
- **Repeating blocks:** the weekday's blocks, each with the date's `repeats[id]` over it. A block
  with `skip` is hidden, and a `repeats` entry whose id is no longer in the week is ignored.
- **One-off blocks:** the date's own.

Items always belong to the date, never to the week.

**Cleaning** happens on every save, with the same rules in server.py and the public site's
schoolPublic.ts. Test vectors in `tests/plan_vectors.json` are used by both. A value that breaks a
rule is refused with 400 and a short reason; nothing is silently changed except where noted.

- **Key:** must match `^(settings|week:(sun|mon|tue|wed|thu|fri|sat)|day:\d{4}-\d{2}-\d{2})$`, and a
  day must be a real calendar date.
- **Times:**
  - written `HH:MM`, from `00:00` to `24:00`, minutes a multiple of 5;
  - `start < end`, and each block lasts at least 15 minutes;
  - a time is not limited to the shown range.
- **settings:** `day_start` is an integer from 0 to 23, and `day_end` an integer from 1 to 24 that is
  at least 4 hours after `day_start`.
- **type:** one of `deep` (Deep work), `social` (Socialize) or `other` (Block). Meals are not
  blocks.
- **Lengths:**
  - `title` is trimmed to at most 120 characters; empty becomes the type's name;
  - `place` is trimmed to at most 120 characters;
  - item `text` is trimmed to at most 200 characters, and an `own` item must not be empty;
  - item `course` is at most 120 characters, and `ref` at most 200.
- **Ids:** `^[a-z0-9]{6,32}$`, unique within the value (blocks and items together). The page makes
  them.
- **Counts:** at most 40 blocks in a day or week value, 50 items in a block or meal, and 100
  `repeats` entries.
- **Booleans:** `off`, `done` and `skip` are made true or false. Unknown fields are dropped, and so
  are `items` on a week's blocks.
- **Saving:** a whole value is replaced at once. Saving `null` deletes the key, which brings back the
  defaults.

## 2. Requests

Both servers answer these the same way: SchoolHub's server.py on the Mac, and QuantPrep's
schoolPublic.ts under `/school/` on the public site. A POST needs `X-SchoolHub: 1`, as the others
do.

- `GET /api/plan?from=YYYY-MM-DD&to=YYYY-MM-DD`
  - answers `{"settings": {...}, "week": {"sun": {...}, …}, "days": {"YYYY-MM-DD": {...}}}`;
  - `settings` and all seven weekdays are always present, as stored or as defaults, cleaned;
  - `days` holds only stored dates in the range;
  - the range is inclusive and at most 62 days; without one it is today ±7 days on the server's
    clock;
  - a bad range is a 400.
- `POST /api/plan {"key": "...", "value": {...} | null}`
  - answers `{"key": "...", "value": <cleaned value or null>}`;
  - a bad key or value is a 400 with the reason as text.

**Storage:**

- **On the Mac without a cloud:** `state/plan.json`, keyed as above.
- **With Turso:** a new table, `school_plan (key TEXT PRIMARY KEY, value_json TEXT NOT NULL,
  updated_at INTEGER NOT NULL) STRICT`. It is made by QuantPrep migration `0008_school_plan.sql`,
  and `turso-schema.sql` gets the same table for a database of its own.
  - school_kv is not touched: its CHECK allows only marks and tasks, and rebuilding the table that
    holds the live marks is not worth the risk.
  - cloud.py reads and writes `plan` there. Upstash, the old phone site's store, uses the hash
    `schoolhub:plan`.
- **Seeding:** the plan joins the seed-once mechanism, so a Mac that had a local plan.json copies it
  up once. Its "seeded" record is kept per database, as marks' and tasks' are.
- **Old phone site:** the site at schoolhub-site.vercel.app (vercel/api/state.js, Upstash) is not
  extended. The page hides the planner there, and in a file:// copy.

The public site refuses to start while a migration is pending. So `./qp run migrate` runs on the Mac
before the deploy.

## 3. The page

### Layout

- **Wide screens (1100 px and up):** two columns under the bar. The left column, about 60 percent,
  holds the summary tiles and the list as now. The right column holds the planner: sticky below the
  bar, as tall as the window, scrolling inside itself.
  - The page column widens to 1440 px for this; the bar keeps QuantPrep's 1040 px column, so the
    app switch stays put.
- **Narrower screens:** the bar's views gain a third button, **Day**, which shows the planner alone,
  full width. Upcoming and By course stay as now. The view is remembered as before (`sh:view`).
  Where the right column exists, Day is not offered, and a remembered Day shows Upcoming.
- **Search:** the box and its filtering go. So does a key that only focused it.
- **Show done:** leaves the toolbar, and the toolbar goes. It becomes a small text button at the end
  of the list, "Show 8 done" or "Hide done", in the muted colour. It is remembered as before.

### The planner

- **Header:**
  - the date, "Sunday, November 8", with ‹ and › for the day before and after (keys `[` and `]` when
    not typing), and **Today** when another day is shown;
  - **Week…**, which opens the weekly form;
  - **+ Block**.
- **Timeline:**
  - a row per hour from `day_start` to `day_end`, labelled 5 AM … 11 PM, ending at 12 AM;
  - 48 px an hour, a faint line at each half hour;
  - on today it scrolls so the current hour is near the top, and shows a now line in `--bad`,
    updated each minute.
- **Assignment markers:** assignments and dated tasks due on the shown date are small flags on the
  right edge at their due time, such as "11:59 PM · HW 5". All-day ones sit in a strip under the
  header. Clicking one opens its drawer, as in the list.
- **Blocks** sit in absolute position by time, and blocks that overlap share the width side by side.
  Each kind has its own colour from the theme's tokens, and its name is written on it, so colour is
  never the only cue (the colours, and how the kind is told, changed on 2026-11-11: see "soft cells,
  vivid bars" below):

  | Kind | Look |
  |---|---|
  | Meal | warm (`--warn-soft` fill, `--warn` edge), "Lunch · <place>" or "Lunch · set a place" |
  | Deep work | `--accent-soft` fill with an `--accent` edge |
  | Socialize | `--good-soft` fill with a `--good` edge |
  | Block | `--surface-3` fill with a `--border-strong` edge |

  A block shows its title, its time range ("4:00–5:00 PM") and as many items as fit, each with a
  checkbox. Below those it shows "+2 more" when some don't fit.
- **Mouse, pen and touch** (pointer events), snapping to 15 minutes:
  - **Create:** drag on an empty part of the timeline to make a block. It opens the block editor
    with the type to choose, Deep work by default. A plain click on empty time makes a one-hour
    block there.
  - **Move:** drag a block's body. A movement under 4 px is a click, which opens the editor.
  - **Resize:** drag its top or bottom edge, which has a resize handle and cursor.
  - The block shows its new times while moving. It saves on release, and Esc during a drag puts it
    back.
- **Dragging work in** (HTML5 drag and drop, desktop):
  - every open assignment or task row in the left list can be dragged, with a grip shown on hover;
  - dropping it on a block adds it as a `work` item;
  - dropping it on empty time makes a one-hour Deep work block there holding it;
  - a block under the drag is highlighted.
- **Without dragging:** the block editor's **Add from my list** gives the same thing on touch and
  from the keyboard. So does the assignment drawer's **Plan it** button, which adds the assignment to
  the next deep work block today (or a new one at the next whole hour).

### Added 2026-11-08: the whole day always in view, and details on click

The learner asked for two more things. Every block of the day must be visible whatever the screen
size, and clicking an event must show more about it.

- **The whole day fits.** The timeline never scrolls inside itself. The hour height is the space the
  planner has, from below its header to the bottom of the window (or of the Day view on narrow
  screens), divided by the number of hours shown. It is recomputed on resize, and when the settings
  change the range.
  - The minimum is 22 px an hour. Only a window too short even for that (under about 420 px of
    planner) scrolls, and then it scrolls to now.
  - This replaces the fixed 48 px an hour.
- **Short blocks stay readable.** A block is at least 20 px tall whatever its length. When it is
  short it switches to a compact single line, "Lunch · Chipotle · 4–5 PM", cut with an ellipsis.
  Items show only where there is room, with "+N" otherwise.
  - Overlapping blocks still share the width. A column narrower than 70 px shows only the kind's
    initial and colour, plus its name for screen readers. (Since 2026-11-11 the kind's icon, not
    its initial.)
  - Hour labels thin out (every 2 or 3 hours) when the hour height is under 30 px.
- **Clicking a block opens its details** (a click is a release under 4 px of movement). Dragging
  still moves it. The details are a card next to the block on wide screens, and a bottom sheet on
  narrow ones. The card shows:
  - the kind and the full title;
  - the time range and the length ("4:00–5:00 PM · 1 hr");
  - the place, for a meal;
  - "Repeats every Sunday" or "Changed for today only", as the case is;
  - every item, each with:
    - its checkbox;
    - for a work item, its course dot and name, its due date and its status from the list (done,
      overdue, due in 2 days), and a link that opens the assignment's drawer.

  Its buttons are **Edit** (the block editor), **Delete**, **Skip today** or **No lunch today**, as
  the kind allows, and **Close**. Esc and a click outside close it. Focus moves into the card and
  returns to the block afterwards.
- **Assignment markers** open the assignment's drawer, as before. The editor is reached from the
  details' Edit, and opens straight away for a block just created.

### Added 2026-11-11: soft cells, vivid bars

The learner asked for the page to look more like three references they sent, the calendar cards most
of all, with the layout and every behaviour kept. This is the look; nothing above changes in what
the planner does. Where a line above describes the first look (the fills and edges in the table of
kinds, the kind's initial on a narrow column, the now line in `--bad`), this section replaces it.

None of it changes a token the page shares with QuantPrep (`--bg`, the surfaces, text, the accent,
the glass, `--titlebar`): the bar and the Mac app's title strip are the same in both apps. School's
own tokens come after those in each theme's block, and every one has a value in light, dark and red.

- **Canvas:** soft washes of lilac (left), rose (right) and sky (from below) on a fixed layer of
  their own, `body::after`. The layer starts under the bar's resting place and fades in over the
  first 240 px, so nothing of it is ever behind the bar. Dark has the same washes at about a third
  of the strength; Night a breath of red, with no blue.
  - Only `--text` and `--muted` are written straight on the canvas, and both keep 4.5:1 at the
    strongest point of the washes. Anything in another colour stands on a ground of its own: a
    course's links are small pills, a warning note sits on `--warn-soft`.
- **Header:** the date is a large light heading (21 to 26 px with the pane's width) with **Today**,
  **Week…** and **+ Block** as pills beside it, each with a small icon. The date has three lengths
  and the page shows the one that fits: "Thursday, November 12", "Thu, Nov 12", and on a phone on
  another day than today, where Today joins the buttons, "Nov 12".
  - The date and the buttons share a line; the date gives way, never the buttons. On the narrowest
    phones (a pane under about 310 px) the date has a line of its own above them.
  - In Night the light display type (the date, the hour numerals) is a weight heavier: thin red
    strokes on black are harder to read.
- **Week strip:** under the date, the week of the day on show, Sunday to Saturday, a chip a day (the
  weekday over the date), between the ‹ and › buttons, which still step a day. A chip shows its day.
  The day on show is solid: in the accent when it is today (which also carries a dot), in ink when
  it is another day. In a short window the chips take one line ("Wed 11") where the pane is wide
  enough for seven of those; a short phone keeps the weekday over the date.
  - The seven chips are made once and kept; only their date and state change, so one that has the
    focus keeps it.
  - They are one stop for Tab, on the day on show. The arrow keys, Home and End move the focus
    between them; Enter or Space shows the focused day.
  - The day on show has `aria-current="date"`. Each chip is read as its full date, and today's
    ends in ", today".
- **Hour rail:** a large light numeral with a small AM or PM beside it (19 px and 10.5 px).
- **Timeline:** each hour is a soft rounded cell on a tray, drawn from gradients alone
  (`--cell-shape`), with a dotted line at the half hour.
  - Today's last hours gone by are hatched, lightly: most at the now line, fading out over the three
    and a half hours above it. So a day seen late in the evening is still a tray of white cells, and
    a day that is over is not hatched at all. The hatching takes no pointer.
- **Now:** a dashed line in `--accent` across the cells, from a small solid pill in the hour rail
  that says the time. It runs under the blocks, and the block that is on says "Now".
  - The pill and an hour's label never overlap. A label within 9 px of the now line gives way to the
    pill, which says the time; one within 16 px steps 8 px away from it (the first and the last
    label give way instead, as a step would take them out of the tray).
- **Free time:** a stretch of an hour and a half or more between two blocks gets a dashed card that
  says how long it is ("2 hr free"), its words on a pill of their own.
  - Decoration only: hidden from screen readers, and the pointer goes through it, so a click or a
    drag there still makes a block.
  - Today it shows only for time still to come: a stretch that has begun has none.
  - Nothing before the first block of the day or after the last.
- **Blocks** are bars in a gradient per kind, each with its own ink (4.5:1 on both ends of the
  gradient, under the sheen and on the nested panel; checked in the tests in light, dark and red):

  | Kind | Light | Dark | Night |
  |---|---|---|---|
  | Meal | amber to coral, dark brown ink | deep amber-brown, cream ink | dark red-brown, amber ink |
  | Deep work | deep violet, white ink | rich violet, white ink | dark red, red-orange ink |
  | Socialize | green, dark green ink | deep green, pale green ink | dark brown, amber ink |
  | Block | pale blue, navy ink | slate blue, pale blue ink | darkest red, red ink |

  - **Edge:** a bar has a hairline of its kind's edge colour, drawn at `--pb-edge-mix` over the bar
    (60% in light, 50% in dark, the whole colour in Night). The bar's edge is at least 3:1 against
    the hour cell in every theme.
  - **Dark:** the bars are deep, low fills of each kind's hue with light ink, so nothing glares on
    the dark tray; deep work is the richest of the four, as it is the strongest in light.
  - **The plain Block** is pale on purpose, the quiet one of the four. It has the same parts as the
    others: its icon in a bubble that shows on the pale bar, its edge, and a soft shadow taken from
    its edge colour.
  - A tall block's items sit on a nested panel.
- **One chip** at the end of a bar's first line, white on the bar: "Now" while the block is on, else
  "2 of 3 done" where it has items, else the kind's name (see the next point). A block too narrow
  for a chip (under 260 px inside) says "+N" for the items it does not show: at the end of its line,
  or after the time on the second line of a tall block.
  - "+N more" keeps its own line under the items where there is room for it. It is never written
    beside "N of M done".
- **The kind's name** (decided 2026-11-11; it replaces "its name is written on it"). The kind is
  never told by colour alone, and this is how:
  - every block of every size has its kind's icon: in a bubble where the block has room, alone where
    it is short or narrow, and alone in the middle of a column too narrow for words. The letters
    (M, D, S, B) are gone;
  - the block's label for a screen reader, its preview on hover or focus and its details card always
    say the name;
  - the name is also written on the bar, as the chip, where the block has room for a chip, the title
    does not already say it (a meal's does, and so does a block titled "Deep work"), and no count of
    items has the chip;
  - the plain kind's name, "Block", is never written on a bar: beside a block's own title it says
    nothing.
- **What gives way.** A title is never cut to make room for a time or a chip. The first line of a
  bar holds what fits whole, and what does not goes in this order: the chip, then the time, and only
  then is the title cut with an ellipsis. (The line wraps and shows its first line only; planner.js
  also leaves the time out where it reckons it would not fit.) The time and the count are in the
  block's preview and its details. A narrow tall block writes its time in the compact form
  ("4–5:30 PM").
- **As a block gets shorter or narrower** the decorations go: one line with a smaller bubble, then
  the icon alone, then the icon alone in the middle of the column. The block is a named container
  (`container: pblock / inline-size`), and the rules that do this ask for it by name.
- **Dragging:** the bar lifts with a bright rim. Moved, it also tilts about a degree; resized by an
  edge, it stays square to the hours. It stays solid, so its words keep their contrast, and its time
  shows while it is dragged even where the block is too narrow for it at rest. Nothing on a block is
  blurred.
- **Night:** the bars are dark reds to ambers with bright ink of their own and a bright hairline, and
  the chip is bright with dark ink. The hatching is faint. No colour has blue.
- **The other surfaces** follow the same family:
  - the **details card** and the assignment **drawer** are nearly solid (the thick glass with most
    of `--surface` mixed in), so the vivid bars under them never show through as smudges; solid
    wherever the glass is (reduced transparency);
  - the **preview** on hover keeps the thick glass in light and is solid in dark and Night, with the
    kind as a small bar of its own;
  - the **toast** (with Undo or Redo) is an ink capsule with its button as a chip;
  - the line under **Sync now** that says when the Mac syncs next is the preview's surface as one
    compact line with a small clock;
  - ticks and radio buttons in the card, the editor and the weekly form are drawn, the same in every
    theme;
  - while the planner **waits for the server's plan** the day is dimmed to 55% and its buttons are off;
  - in the list, a two-line row with width to spare (beside the planner, on a tablet) draws its
    course's dot large, as a round bubble at its left. Never on a phone.
- **Checked in the tests:** ink on every bar, the edge against the cell, text on the washed canvas
  and every other new pair, in all three themes; no blue in any Night colour; a value in dark and
  red for every one of School's tokens.

### Changing a repeating block or a meal

Moving or resizing a repeating block or a meal on the timeline changes that date only. The editor
then shows "Changed for today only" with **Use this time every Sunday**, which saves the time into
the week and clears the date's override.

### The block editor

A dialog, built like the task dialog, with these fields:

- **Kind:** Deep work, Socialize or Block. A meal has its kind fixed, so this is shown as text.
- **Title.**
- **Start and end:** time inputs, 5-minute steps.
- **Repeat every <weekday>:** a checkbox on blocks; ticking it moves a one-off block into the week.
  Unticking it on a repeating block asks whether to remove it from every <weekday> or only skip it
  today.
- **Where to eat (meals):** set for this date only, with a link to change it for every <weekday> in
  the weekly form.
- **Things to get done:**
  - a list with checkboxes and a remove button;
  - an "Add a to-do" input, which adds on Enter;
  - **Add from my list**, a list of open assignments and tasks by due date (course dot and name)
    that adds the one picked;
  - a work item whose assignment is done in the list shows "done" beside it.
- **Delete:** for a one-off block, delete. For a repeating block, skip today. For a meal, "No lunch
  today" (`off`). Each comes with the toast's Undo, which is the page's undo for that step.

Items can also be ticked straight on the timeline.

### The weekly form

Opened with **Week…**. It is a dialog with a table, one row per weekday, Sunday first:

- for each of breakfast, lunch and dinner: a place input, start and end times, and an "off" toggle;
- below the table: the repeating blocks by weekday, each with remove;
- day start and day end, as hour selects.

Save writes the changed `week:*` keys and `settings`. Its note says: "Places and times here repeat
every week. Changes on one day in the calendar stay on that day."

### Saving

- Changes show at once and save to `/api/plan` for that key.
- A failed save shows the toast "Couldn't save the plan", puts back what the server last had for the
  keys being saved, and loads the plan again.
- The plan loads for the shown date ±7 days, and again when the date leaves that range.
- Loading and saving use the same `X-SchoolHub` header and base path as tasks.
- The plan is reloaded with the marks and tasks: on focus, and after reloadState.

### Added 2026-11-11: undo and redo

The learner asked for "some ctrl z option" for anything done to a task or the calendar. Cmd+Z or
Ctrl+Z takes back the last change; Shift+Cmd+Z, Shift+Ctrl+Z or Ctrl+Y makes it again. The history
is the page's (dashboard.js, "undo and redo"), shared with marks and tasks; the planner adds its
changes to it.

- **One action is one step**, whatever it saves. Every change goes through `record(label, date, ref,
  fn)`, which notes each key saved inside `fn` with its value before and the value left. Making a
  block repeat saves `week:wed` and `day:…` and is still one step. A save that changes nothing is no
  step. A test fails if a change is added outside `record()`.
- **The label** is what the toast says after "Undid:" or "Redid:": "moved Lunch to 3:00 PM",
  "resized “Gym” to 8:00–9:30 AM", "deleted “Gym”", "ticked “Read chapter 3” in “Deep work”",
  "skipped lunch today", "set Lunch’s place to “Chipotle”", "changed your week".
- **The way back** saves through `save()` like the change itself, the week before the date. Each key
  is stored whole, so saving its old value blindly would also undo whatever another device saved to
  the same date since. So the step first asks `GET /api/plan` what is stored now:
  - a key still as the step left it gets the value it had, exactly: a deleted block is back with its
    id, fields, items, their ticks and its place in the list;
  - a key changed since gets only the step's own change taken back (`rebase()`: objects field by
    field, blocks and items by id), cleaned like any edit, so a block added on the phone stays;
  - where the step and the other change touched the same thing (the block was moved again, or the
    step would delete a block that has a new item), nothing is saved, the step goes, and the toast
    says "Can't undo: … It was changed somewhere else since."
  - the settings and a weekday going back to the defaults are stored as no key, which is what they
    were before their first change.
- **Where it shows.** Taking a step back shows the date it happened on. An open details card follows
  the plan as after any change. The keys do nothing while a block is dragged, or while a form is
  open and no field has focus; in a field they are the field's own.
- **When it fails.** If the server cannot be asked, nothing changes and the step stays. If the
  change itself failed to save, it is put back on the page and is no step.

### Added 2026-11-11: details on hover

The learner asked to see a calendar block's details on hover "instead of just the click thing".
Blocks can be 20 px tall with one cut line, which is where it helps most. Clicking still opens the
card; the preview comes first, and is only read.

- **What shows it.** A mouse, trackpad or pen pointer that comes onto a block and stays for 350 ms.
  The same for a flag of something due at a time, and for the chips in the strip (a block outside
  the hours shown, something due with no time). While one preview shows, going on to the next block
  shows that one at once.
- **From the keyboard.** Tab onto a block, flag or chip shows the same preview after the same wait.
  It has `role="tooltip"`, and the block's button is `aria-describedby` it while it shows. Focus never
  moves into it. Focus the page itself puts back (after a redraw, a dialog or the drawer closing,
  the window coming back to the front) brings no preview.
- **What it says** is what the details card says, written by the same functions (`detailsHtml`,
  `dueHtml`, `workLine` in planner.js), so the two cannot drift apart:
  - a block: its kind, full title, time range and length, the place for a meal, "Repeats every
    Wednesday" or "Changed for today only", and its items, each with its tick drawn (named "Done" or
    "To do" for a screen reader) and, for work, its course, due date and status. It lists six items,
    then "+3 more". A block holding nothing has no "Things to get done" line (the card has, with
    the hint to edit).
  - something due: its full name, its course, when it is due, its status in the list, and a task's
    notes (four lines).
- **Where it goes.** Beside the block, left of it first (the planner is on the right), else right,
  else under or over it. Its top is in line with the block's, moved up where it would leave the
  window. It is always 8 px inside the window and never over the block. A flag's preview goes
  under or over the flag, their right edges in line, because a flag grows to the left to show its
  name while pointed at. Where no side has room for all of it (a long block in a phone-sized
  window with a mouse), it takes the side with the most room, is cut there and fades out.
- **It never gets in the way.** It takes no pointer (`pointer-events: none`), so everything under
  it stays clickable. It goes at once on any press (so making, moving, resizing and dragging in
  work as before, and it does not come back for that block until the pointer has left it), on a
  scroll, on Esc, when a dialog or the drawer opens, when the window is resized or left, and 120 ms
  after the pointer or the focus leaves. No preview shows while a block is dragged or while a
  dialog or the drawer is open.
- **A touch never shows it** (`pointerType` "touch" is ignored); a tap opens the card as before.
- **No doubled tooltip.** Blocks, flags and chips no longer carry a `title`.
- **It follows the plan.** After a redraw (an item ticked, a step undone, the day changed) a preview
  that shows is filled in again, and goes if its block went or is no longer under the pointer. A
  block drawn under a pointer that lies still shows nothing until the pointer moves.
- **How it is wired.** One element (`#planTip` in dashboard.html), one timer, and listeners on the
  planner and the page only (`pointermove` and `pointerleave`, `focusin` and `focusout`; a press,
  a key, a scroll). Nothing is added to a block, which carries only `data-tip` (`b:` and the block's
  ref, or `d:` and the assignment's id). No MutationObserver.
- **Look.** The details card's material, smaller: thick glass in light, solid `--surface` in dark
  and Night, solid where transparency is reduced; a 140 ms fade that is off under reduced motion.
  Every colour is a token, so Night's preview has no blue. Emoji in it are marked as everywhere.

### Added 2026-11-11: drawn at once from the last visit

The learner noticed that switching between the two apps "is reloading everything". In a browser a
switch is a page load, and the planner was the last thing to appear: it waited for the page to learn
where it saves, and then for `/api/plan`.

- **What is kept.** After every load whose dates cover today, and every save that went through, the
  plan as the page holds it (`settings`, the seven weekdays, the loaded dates) is kept in the
  browser with its range, through dashboard.js's `SchoolHub.kept` (README, "Opening at once").
- **The next visit.** When the page knows where it saves, which with dashboard.js's own copy is at
  once, the planner draws the kept plan (`showKept`) and asks `/api/plan` as before (`load`).
- **Read, never changed.** While the copy shows (`copied`) nothing is editable: a drag does not
  start, nothing drops, a tick goes back, the card's buttons are off. So nothing is ever saved from a
  copy, and whatever the server has since is not overwritten. **+ Block** and **Every week** pressed
  meanwhile open once the plan is here; **Plan it** waits for it.
- **The answer.** The same as the copy: nothing is drawn again, only what may be changed is switched
  on (`unlock`). Different: drawn again, as after any load. None: the copy goes from the page and
  the planner says "Couldn't load the plan", as without a copy.
- **A slow answer.** The copy looks like the plan for 1.2 s (`COPY_QUIET_MS`); after that the day is
  dimmed and the buttons are off, as whenever the plan loads, until the answer comes.
- **Never the wrong day.** The planner shows today, and a date shows its own stored value, so a copy
  kept yesterday shows today as it was known then. A copy whose dates do not cover today is not
  used. One older than 3 days, or not a plan, is not used either.

### Access

- Every control has a label.
- Blocks are buttons that open their details card (Edit there opens the editor).
- A block's, flag's or chip's preview also shows when Tab brings focus onto it, and describes its
  button while it shows (see "details on hover").
- The timeline is a list in reading order for screen readers ("Lunch, 4:00 to 5:00 PM, at …, 2
  things to get done").
- Contrast follows the existing tokens, and nothing depends on colour alone.

## 4. Theme

The learner reported that the System theme "doesn't work". It was tested on 2026-11-08 on the Mac
page, the public School page and the public Prep page. Each followed the operating system's light and
dark both at load and live, so nothing changes here. If a computer stays dark, the browser's own
appearance setting (for example Chrome's Appearance → Mode) may be overriding macOS.
