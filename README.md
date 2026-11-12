# SchoolHub

One local dashboard for every assignment across Canvas, Gradescope and plain course websites —
with all the files downloaded into your own class folders.

No AI, no cloud, no account: a Python script talks to your school's APIs, saves files where you'd
put them yourself, and writes a static page you open in your browser. Everything stays on your Mac.

![Dashboard](docs/dashboard.png)

## What it does

- **Collects assignments** from Canvas (API), Gradescope (unofficial API) and course websites that
  have their own parser (15-122 at CMU ships as an example), and merges duplicates: a homework that
  exists on both Canvas and Gradescope is one row, with whichever source knows the most.
- **Downloads files** into your existing class folders: assignment attachments, the files you
  submitted, Canvas module files, a course's whole Files page where permitted, and public handouts
  from course sites. Never deletes; never overwrites a file you've edited (it saves
  `name (updated 2026-09-12).ext` alongside instead).
- **Tracks status** per assignment: To do, Due soon, Submitted, Graded, Missing, Offline.
- **Mark as done** with ✓ for work the APIs can't see (paper hand-ins, Autolab). The next sync
  double-checks each mark against Canvas/Gradescope. One it can't confirm still counts as done (your
  ✓ is your word; a check-in or a paper hand-in leaves nothing to find), with a note on the item and
  a one-time alert from that sync, in case the hand-in didn't go through.
- **Add your own tasks** with the **+** button (or press **N**): a name, a course or "Personal", an
  optional due date and time, and notes. They get ✓, Undo, overdue warnings and due-soon alerts like
  everything else, and they show up on the phone view.
- **Undo and redo** for everything you change: **Cmd+Z** (or Ctrl+Z) takes back the last change to a
  ✓, a task or the day planner, and **Shift+Cmd+Z** (Shift+Ctrl+Z, or Ctrl+Y) makes it again, about a
  hundred steps back for as long as the page is open. See [Undo and redo](#undo-and-redo).
- **Opens at once** when you come back to it: the page is drawn from what the server said last
  time, kept in the browser, and asks again quietly. See [Opening at once](#opening-at-once).
- **Tells you what changed**: due dates that moved, newly posted assignments, work due within 36
  hours that isn't done, and anything newly missing.
- **Fails loudly**: if a course website changes shape, the parser refuses to guess — it reports the
  problem and keeps showing the last good copy.

## Install

```bash
git clone https://github.com/ArnavBali36/schoolhub.git
cd schoolhub
python3 -m venv .venv
.venv/bin/pip install truststore gradescopeapi   # gradescopeapi only if you use Gradescope
cp config.example.json config.json
chmod 600 config.json          # it will hold your token and password
```

Then edit `config.json`:

- `canvas_base_url`: e.g. `https://canvas.instructure.com`, no trailing slash.
- `canvas_token`: Canvas → Account → Settings → **+ New Access Token**. Treat it like a password;
  it can do anything your account can.
- `school_root`: the folder holding your class folders.
- `canvas_courses`: map each Canvas course id → the folder name to use, plus a short label.
  Get the ids by running the sync once; unmapped courses land in `Other/<course name>`.
  Add `"skip": true` to hide a course.
- `gradescope`: your Gradescope email and password (optional). If your school uses single sign-on,
  set a Gradescope password first via "Forgot password".
- `web_courses`: course sites with a parser in this repo. Add `"skip": true` to hide one (a dropped
  class); its Gradescope course, if it has one, needs `"skip": true` under `gradescope.courses` too.

Run it:

```bash
.venv/bin/python sync.py        # ~1 minute
open dashboard.html
```

## The local server (optional but recommended)

`server.py` serves the dashboard on <http://localhost:8722>, which adds:

- the ✓ **mark as done** buttons (saved to `state/marks.json`, checked by the next sync)
- the **+** button for your own tasks (saved to `state/tasks.json`)
- the day planner beside the list (saved to `state/plan.json`; see below)
- **Sync now**, next to the time of the last sync (in the header, or above the lists on a phone);
  each sync the server runs adds its output to `state/sync.log`, which is where "Sync failed" points
- files opening in their real apps, and folders in Finder
- a **catch-up sync** if the data is more than 20 hours old

It binds to `127.0.0.1` only, refuses cross-site requests (custom-header + Host checks), and never
serves its own folder (however its name is spelled: macOS ignores case) or any hidden file or folder,
so your token stays out of the browser. Class files are shown, never run: an SVG or HTML file opens
in a sandbox with no script, and a `.js` file comes as plain text. The page itself runs only its own
scripts (a Content-Security-Policy of `script-src 'self'`).

```bash
.venv/bin/python server.py
```

To run it at login on macOS, copy `examples/com.schoolhub.server.plist` to
`~/Library/LaunchAgents/`, fix the paths inside, and
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.schoolhub.server.plist`.
Its log goes to `~/Library/Logs/schoolhub-server.log`, not into the SchoolHub folder, because macOS
refuses to start a launch agent whose log file is inside a folder it protects, such as Desktop (the
service then fails with `EX_CONFIG`).

To run a second copy beside it (say, a test folder), give it another port:
`SCHOOLHUB_PORT=8733 .venv/bin/python server.py`.

**After updating SchoolHub** (`git pull`), restart the server: it reads its list of page files (and
its own code, such as `plan.py`) when it starts, so an old one serves the new page without its scripts and the dashboard stays blank. If
it runs at login: `launchctl kickstart -k gui/$(id -u)/com.schoolhub.server`.

## The day planner

Beside the list (or under **Day** on a narrow screen) is a calendar of the day by the hour, 5 AM to
midnight by default. It holds the three meals, each with where you eat it, and blocks of your own:
**Deep work**, **Socialize** or a plain **Block**. Each block lists the things to get done in it:
assignments and tasks dragged in from the list, or to-dos you type. A meal's place and time and a
block marked to repeat are set once per weekday in the weekly form (**Week…**), so set Sunday's lunch
place once and every Sunday shows it; a change made on one day stays on that day. Resting the pointer
on a block (or on a flag of something due) shows its details beside it, as does Tab from the
keyboard; a click opens the same details as a card you can act on. The whole design is in
[docs/planner.md](docs/planner.md).

It is saved through `GET /api/plan?from=&to=` and `POST /api/plan`, one key per object (`settings`,
`week:sun` … `week:sat`, `day:YYYY-MM-DD`). Every save is checked by `plan.py`, which refuses what
breaks a rule with the reason; `tests/plan_vectors.json` holds the cases, and the public site's copy
of the server checks against the same file. Without a shared database the plan lives in
`state/plan.json`. With Turso it is the table `school_plan` (key, value, time of the change), made by
QuantPrep's migration `0008_school_plan.sql` or, on a database of your own, by `turso-schema.sql`;
until that table exists, saving the plan fails with "couldn't reach the cloud database" while marks
and tasks carry on. With Upstash it is the hash `schoolhub:plan`, but the old phone view does not
show the planner. On first start with a database, a `state/plan.json` you already have is copied up
once, as marks and tasks are.

## Undo and redo

Every change you make to your own data is a step: a ✓ made or taken away, a task added, edited,
pinned or deleted, and everything in the day planner (a block made, moved, resized, edited or
deleted, its items, a meal changed or skipped for a day, an assignment dropped onto the day, **Plan
it**, the weekly form and the hours shown). **Cmd+Z** or **Ctrl+Z** takes the last step back;
**Shift+Cmd+Z**, **Shift+Ctrl+Z** or **Ctrl+Y** makes it again. One action is one step even when it
saves several things, a new change clears what could be redone, and the page keeps about a hundred
steps until it is closed or reloaded (a finished **Sync now** reloads it). The view and the theme are
not data, so they are not steps.

- A toast names what happened, "Undid: moved Lunch to 3:00 PM", with **Redo** (or **Undo**) on it.
  Deleting a task or a block offers **Undo** on its own toast, as before.
- While you type in a field the keys are the field's own undo. While a form is open (a task, a
  block, the week) and you are not typing, they do nothing, so nothing changes underneath the form.
- What you deleted comes back as it was: a task under its own id with its fields, its ✓ and the time
  it was made; a block with its items, their ticks and its place; a ✓ with the time it was made, so
  the nightly check's answer for it still applies. The server stamps every save of a task
  (`updated_at`), so that one field is new.
- An undo saves through the same requests as the change itself, so it works the same on the Mac and
  on a hosted copy. It first asks the server what is stored now. If that is no longer what the step
  left (the same thing was changed on another device since), it takes back only its own change where
  the two do not touch (your move of one block, beside a block added on the phone), and where they do
  it changes nothing and says "Can't undo: … It was changed somewhere else since." If the server
  cannot be reached it changes nothing and the step stays, to try again.

`POST /api/mark` takes an optional `marked_at` for this: a mark put back keeps the time it was made
(a UTC time that is not in the future; anything else is stamped now, as before). The Mac app's Edit
menu can ask the page with `SchoolHub.undo()` and `SchoolHub.redo()`: each answers `true` when the
page took the request and `false` when it belongs to the field being typed in.

## Opening at once

Coming back to the page is a page load, and a load used to wait for its answers one after another:
`data.js`, then where the page is and your marks, then your tasks and the plan. Where the server is
not this Mac (a hosted copy) each took most of a second, and the list, the ✓ buttons and the planner
each appeared in turn.

Now the page keeps the last answers in the browser (`localStorage`) and starts from them: the list,
the ✓ buttons, your tasks and the planner are drawn at once, and the same requests as before go out
behind them, all together.

- **The same answer changes nothing on the page.** A different one (a ✓ made on your phone, a new
  sync) is taken in place: the list is drawn again where it is, an open drawer stays open where you
  were reading, and the undo history stays.
- **A copy is only shown, never saved from.** A ✓ made in the first moment shows at once and is
  sent when the server has answered; a task's form waits for the same answer before it saves and
  closes. The planner can be read from its copy and changed once
  the server's plan is here, usually well under a second; if that takes more than 1.2 s the day dims
  as it does whenever it loads. If the server does not answer at all, the page becomes the read-only
  view it always was then, and says a change could not be saved.
- **What is kept:** the last sync's data (what `data.js` holds), your marks and tasks with where the
  page saves, and the planner's two weeks around today. One set per address and path, and per kind of
  site (the phone view has its own). Each copy carries the time it was kept and is ignored after 3
  days, or if it is not what it should be; the plan's copy is used only if it covers today, and
  shows each date as it was stored, so yesterday's blocks never show as today's. "Synced 5h ago"
  is always the time of the data on show.
- **Limits.** Data over 1.5 million characters is not kept (the page then waits for `data.js` as
  before). A browser that keeps nothing (a private window, site data blocked, a full disk) gives the
  page as it was before: every visit a first visit. Opened from disk nothing is kept. The copies hold
  your assignments, grades and feedback, in that browser, like the page itself does while open:
  clear the site's data to remove them.

Nothing else changed about what is asked from where: no service worker, no new file, and `data.js`
is still never cached by the browser (it is only no longer waited for: `<script async>`).

## Light and dark

The button at the right of the header steps through **System**, **Light** and **Dark**. System
follows your Mac's appearance, and changes with it while the page is open. The choice is saved in
the browser (localStorage `qp.theme`), and a change in one tab applies to every other open tab of
the same address. `theme-init.js` sets the theme before the page first paints, so it never flashes
the other one, and `bar.js` fills in the header (the theme button, the view you were on) before it
is first drawn.

## Running under a path prefix

The dashboard asks its own server for everything with relative URLs (`api/marks`, `data.js`,
`file/<name>?p=…`), so another server can put it under a path such as `/school/` by forwarding
`/school/<rest>` to `http://127.0.0.1:8722/<rest>` (with `Host` set to `127.0.0.1:8722`, and the
`X-SchoolHub` header passed through on POSTs). The page's scripts are files of their own, so it
also runs under a Content-Security-Policy of `script-src 'self'`. In a class file's link the name
is only there so the browser's tab shows it; the server serves the file that `p` names.

If that server also answers `platform.json` next to the page, the dashboard joins it as one
platform: the plain title becomes a switch between the apps, and **O** opens the other one.

```json
{"apps": [{"id": "quant", "name": "QuantPrep", "href": "/"},
          {"id": "school", "name": "School", "href": "/school/"}]}
```

`id` `school` is SchoolHub itself; every `href` must be a path on the same address. Opened on
its own port (where `platform.json` answers 204 No Content), from disk or as the phone view there
is no platform, and nothing changes. The last answer is kept in the browser (localStorage
`qp.platform`), so the switch is drawn from the first paint on the next visit.

A platform that also serves your other devices (say, your phone over a private network to the Mac)
adds `"remote": true` to `platform.json` for their requests. The dashboard then offers nothing that
would act on the Mac's own screen: files the browser can show (PDFs, pictures, text) open in a tab
as usual, every other file downloads (its link carries a small ↓ and the tooltip "Downloads to this
device"), and a folder is shown as text ("On your Mac: ~/…") instead of Open folder. Marks, tasks
and Sync now work as on the Mac. If `platform.json` gives any other answer than 200 or 204 (or
404), the page plays safe and behaves as remote. The forwarding server must also refuse `api/open`
and `api/reveal` itself for those requests: the page leaving them out is a convenience, not the
protection.

A platform that puts a public copy of the dashboard on the internet (saving marks and tasks to a
shared database, such as Turso below) adds `"public": true`. The page then behaves as from another
device, except that files are listed by name only, as on the phone view, and there is no Sync now:
syncs run on your Mac. That server answers `data.js` and the `api/` routes for marks and tasks
itself, and serves no files.

## Tests

```bash
.venv/bin/python -m unittest discover tests
```

They use a throwaway folder with made-up data, never your `config.json`, `state/` or `data.js`.
The checks of the dashboard's file and folder links run its own code under Node when `node` is
installed, and are skipped otherwise. The Turso checks run against a stand-in for its HTTP API
(`tests/fake_turso.py`) over a throwaway SQLite file, never a real database.

## Nightly sync

`sync.py` prints nothing unless something needs your attention, which makes it a good cron job:

```
0 5 * * *  /path/to/schoolhub/.venv/bin/python /path/to/schoolhub/sync.py
```

To keep its summary line in `state/sync.log` too, beside the syncs the server runs, end the line with
`2>> /path/to/schoolhub/state/sync.log` (what needs your attention still comes by cron's mail).

It stops itself after 15 minutes (`SCHOOLHUB_TIMEOUT` seconds) rather than hanging, keeps the last
good copy of anything it couldn't reach, and reports the timeout.

## Phone view (optional)

`publish.py` builds a read-only copy of the dashboard into `schoolhub-site/` and can deploy it to
Vercel, so you can check your assignments from your phone:

```bash
.venv/bin/python publish.py            # build only
npx vercel login                       # once
.venv/bin/python publish.py --deploy   # build + deploy, prints your URL
```

There's no login screen. Instead the page is published under one unguessable path segment
(generated into `config.json` as `site.secret`), with `robots.txt` and `X-Robots-Tag: noindex` so it
stays out of search engines. **Anyone with the link can read your assignments and grades, so treat
the link like a password.** Prefer a real login? Put the site behind your host's password protection
and drop the secret path.

The hosted copy has no file links (files live on your Mac), and it's read-only unless you connect
the free database below.
Set `site.auto_deploy` to `true` in `config.json` and every sync republishes it, so the phone view
keeps up with the nightly run.

New Vercel projects enable "Vercel Authentication" (Settings → Deployment Protection), which puts a
Vercel login in front of the site. Turn it off if you want the link to just work.

## Edit from your phone (optional, free)

Connect a free Upstash Redis database to the Vercel project and the phone view can save ✓ marks and
tasks too. Your Mac and phone then share one copy of both; grades and files stay where they are.

1. Vercel dashboard → your project → **Storage** → **Create Database** → **Upstash for Redis** →
   Free plan → connect it to the project.
2. Give the site's API its key, and pull the database credentials to your Mac:
   ```bash
   cd schoolhub-site
   printf '%s' "<site.secret from config.json>" | npx vercel env add SCHOOLHUB_SECRET production
   npx vercel env pull ../state/cloud.env --environment=production
   ```
3. Restart `server.py` (on first start it copies your existing marks and tasks up), then run
   `publish.py --deploy`.

`vercel/api/state.js` only answers requests that carry the site's secret path segment. The database
token stays on Vercel and in `state/cloud.env` (gitignored) and never reaches the browser.

## Marks, tasks and data.js in Turso (optional)

Instead of Upstash, SchoolHub can keep ✓ marks and your own tasks in a [Turso](https://turso.tech)
database (hosted libSQL, free tier) that other apps share: say, a hosted copy of the dashboard that
saves marks to the same place. Put its URL and a token in `state/cloud.env`, by hand or with
`npx vercel env pull` from a Vercel project the database is connected to:

```
TURSO_DATABASE_URL="libsql://<database>-<org>.turso.io"
TURSO_AUTH_TOKEN="<token>"
```

With both set, SchoolHub uses Turso (even if Upstash's variables are there too). Then:

1. Restart `server.py`, which reads `state/cloud.env` only when it starts (with the launchd service:
   `launchctl kickstart -k gui/$(id -u)/com.schoolhub.server`).
2. Run `python3 cloud.py`. It says which database `state/cloud.env` names and counts the marks and
   tasks in it, reading only. `server.py` quietly falls back to the local files whenever the
   database does not answer, so this is how you see that the database is reachable. It reads the
   file afresh, so it checks what the next start of `server.py` will use, not the one already
   running: restart first.
3. Run Sync now (or `python3 sync.py`) once, so the hosted copy has your assignments.

- Marks and tasks are rows of `school_kv` (`name` is `marks` or `tasks`, `key` the assignment or task
  id, `value_json` the object, `updated_at` in milliseconds). On first start `server.py` copies the
  ones you already have into an empty table.
- The day planner's keys are rows of `school_plan` (`key`, `value_json`, `updated_at`), a table of
  its own because `school_kv` only allows marks and tasks. On a database you made before the planner,
  add it with the `school_plan` statement from `turso-schema.sql`.
- After every sync, a copy of the new `data.js` is saved as the one row of `school_data`, so the
  hosted copy shows the same assignments. If that fails, the sync still finishes and lists it with
  its other issues. The hosted copy shows no assignments until the first sync after you add these
  lines (step 3).
- The phone view above keeps saving to Upstash, which your Mac no longer reads: ✓ marks and tasks
  made there stay there. Use the hosted copy that reads Turso instead, and set `site.auto_deploy`
  to `false` if you no longer want the phone view republished after each sync.

It talks to Turso's HTTP API (`/v2/pipeline`) with the standard library; the token stays in
`state/cloud.env`. SchoolHub never creates or changes tables: on a database of your own, make them
once with `turso db shell <database> < turso-schema.sql`; if another app owns the database and makes
them with its own migrations, leave it to that app.

What goes to `school_data` is made to be shown without a login (`public_copy` in `sync.py`): your
assignments, grades, feedback and Canvas instructions as they are, but paths on your Mac written from
`~` (no user name) and links without the parameters that open a file without signing in (Canvas's
`verifier=`, a storage link's signature). Never the files themselves. Your own `data.js` keeps
everything. Anyone who can read the database, or open a hosted copy without a login, can read what
it holds.

## Where files land

```
<school_root>/<course folder>/
├── Assignments/<assignment>/      attachments, Instructions.html, Submitted/
├── Materials/<module>/            Canvas module files, course-site handouts
└── Files/<folder>/                mirror of the Canvas Files page (when permitted)
```

`state/manifest.json` records what was downloaded (by file id and version), so re-runs only fetch
what's new or changed.

## Adding your own course website

Course sites vary, so each gets a small parser. Copy `cs15122_source.py`, keep the same
`sync(wcfg, root, store, now)` signature, return a course dict with `assignments` and `materials`,
and raise an exception if the page stops matching what you expect — the sync will show the last good
copy instead of silently losing the course. Then add an entry to `web_courses` in your config.

## Notes and limits

- **Gradescope has no official API.** `gradescopeapi` logs in as you by scraping, so it can break
  when Gradescope changes. Failures are reported, never silent.
- **Autolab isn't supported**, so those submissions can't be verified; mark them done yourself.
- **Canvas access is read-only here.** Nothing in this repo submits, posts or deletes.
- Your token and password live only in `config.json` (gitignored), and your school data only in
  `data.js` and `state/` (also gitignored).

## License

MIT
