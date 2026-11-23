#!/usr/bin/env python3
"""SchoolHub local server: http://localhost:8722

Serves the dashboard and your class files, saves "mark as done" clicks to state/marks.json
(which the next sync double-checks), stores your own tasks in state/tasks.json and the day planner in
state/plan.json. Syncs by itself whenever the last good sync is more than 12 hours old and the Mac is
awake (autosync.py). Listens on 127.0.0.1 only.
"""
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import autosync
import cloud
import plan

HUB = Path(__file__).resolve().parent
MARKS = HUB / "state" / "marks.json"
TASKS = HUB / "state" / "tasks.json"
PLAN = HUB / "state" / "plan.json"  # the day planner, one key per object (docs/planner.md)
NOTES = HUB / "state" / "notes.json"  # the Notes button's notes, one per id
TASK_ID = re.compile(r"^task:[a-z0-9]{8,32}$")
NOTE_ID = re.compile(r"^note:[a-z0-9]{8,32}$")
NOTE_LIMIT = 20000  # characters in a note
NOTES_LIMIT = 500   # notes in all
FILES = {"marks": MARKS, "tasks": TASKS, "plan": PLAN, "notes": NOTES}
CLOUD = cloud.connect()  # shared with the phone view when state/cloud.env exists
PORT = int(os.environ.get("SCHOOLHUB_PORT") or 8722)  # another port for a test copy beside the real one
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
PAGES = {"/": "dashboard.html", "/dashboard.html": "dashboard.html", "/dashboard.js": "dashboard.js",
         "/theme-init.js": "theme-init.js", "/bar.js": "bar.js", "/data.js": "data.js", "/favicon.svg": "favicon.svg",
         "/planner.js": "planner.js"}
PAGE_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}
# The dashboard runs only its own scripts (it has none inline), and shows pictures in assignment
# instructions from Canvas over https. A platform that forwards to this server gives it the same policy.
PAGE_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
            "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
# Course files come from Canvas and course sites: they are shown, never run. An SVG or HTML file opened
# from the dashboard runs in a sandbox with no script; a PDF runs none (a sandbox would stop the
# browser's PDF view). A script file is sent as plain text, so no page can load it as a script.
FILE_CSP = ("sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; media-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
PDF_CSP = ("default-src 'self'; script-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
           "connect-src 'none'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
SCRIPT_TYPE = re.compile(r"(java|ecma|j|live)script", re.I)  # text/javascript and the like, not postscript
LOCK = threading.Lock()
SYNC_LOCK = threading.Lock()  # guards sync_state and AUTO; never held while a sync or the network is waited on
sync_state = {"running": False, "started_at": None, "finished_at": None, "ok": None, "output": ""}
AUTO = autosync.AutoSync(time.time())  # when the server syncs by itself (autosync.py)


def sync_log():
    """Where each sync the server runs (Sync now, or by itself) adds its output: state/sync.log,
    where a cron line can add its own (README)."""
    return HUB / "state" / "sync.log"


CAFFEINATE = Path("/usr/bin/caffeinate")  # macOS's own tool: keeps the Mac awake while a process runs


def stay_awake(pid):
    """Keeps the Mac from going to sleep by itself while the process with this id runs: macOS's own
    caffeinate, told to hold off idle sleep (-i) for as long as that process lives (-w). A sync takes
    a minute or two, and a Mac on battery left alone for one minute would otherwise freeze it
    halfway. It changes no setting and ends with the sync; closing the lid still puts the Mac to
    sleep. Returns the caffeinate process, or None where there is no such tool (not a Mac)."""
    if not CAFFEINATE.is_file():
        return None
    try:
        return subprocess.Popen([str(CAFFEINATE), "-i", "-w", str(pid)], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None


def sync_py():
    """Runs sync.py to its end: (whether it got there, what it printed). At most 30 minutes: then
    it is stopped, and that counts as a failure."""
    keeper = None
    try:
        with subprocess.Popen([sys.executable, str(HUB / "sync.py")], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) as p:
            keeper = stay_awake(p.pid)
            try:
                out, err = p.communicate(timeout=1800)
            except BaseException:  # the time ran out (or the server is stopping): the sync does not run on alone
                p.kill()
                raise
        return p.returncode == 0, (out + err).strip()
    except Exception as e:
        return False, str(e)
    finally:
        if keeper:  # it ends by itself with the sync; this only tidies up after it
            try:
                keeper.terminate()
                keeper.wait(timeout=5)
            except Exception:
                pass


def run_sync(clock=time.time):
    began = clock()
    started = datetime.fromtimestamp(began, timezone.utc).isoformat()
    ok, out = sync_py()
    # Kept where the page's "Sync failed" points, since the output is otherwise only in memory.
    try:
        with sync_log().open("a") as f:
            f.write(f"--- sync from the server, {started}: {'done' if ok else 'failed'}\n")
            if out:
                f.write(out + "\n")
    except OSError:
        pass
    # A daily task's old ✓ marks are folded when one is stored through this server; a ✓ made on the
    # public site is stored there, so the marks are looked at after each sync too (the Mac runs one
    # twice a day by itself). Never an error: tidy_daily keeps its own.
    with LOCK:
        tidy_daily()
    with SYNC_LOCK:
        good = AUTO.finished(ok, began, clock(), synced())
        if not good:
            log(f"sync {'left something unread' if ok else 'failed'} ({AUTO.failures} in a row): the next try "
                f"by itself is in {autosync.retry_delay(AUTO.failures) // 60} min at the earliest")
        sync_state.update(running=False, finished_at=datetime.now(timezone.utc).isoformat(), ok=ok, output=out[-4000:])


def synced():
    """The sync that wrote the data.js now on disk: when it began and whether it read every source.
    Read from the file at each look, so a sync run from Terminal counts, and a restart forgets nothing."""
    return autosync.last_sync(HUB / "data.js")


def in_background(fn):
    threading.Thread(target=fn, daemon=True).start()


def start_sync(manual=False):
    """Starts a sync unless one is running: never two at once. The caller holds SYNC_LOCK."""
    if sync_state["running"]:
        return False
    if manual:
        AUTO.manual()
    sync_state.update(running=True, started_at=datetime.now(timezone.utc).isoformat(), ok=None, output="")
    in_background(run_sync)
    return True


def auto_on():
    """Whether the server syncs by itself: not before config.json exists (nothing to sync with), and
    not with SCHOOLHUB_AUTOSYNC=0 (a test copy beside the real one would sync into the same class folders)."""
    return os.environ.get("SCHOOLHUB_AUTOSYNC", "1").strip().lower() not in ("0", "off", "no", "false") \
        and (HUB / "config.json").is_file()


def canvas_url():
    try:
        return json.loads((HUB / "config.json").read_text()).get("canvas_base_url")
    except (OSError, ValueError, AttributeError):
        return None


def sync_status(now=None):
    """What GET /api/sync answers: the sync the server last ran, as ever, plus data_at (the time in
    the data.js now on disk, so an open page can tell that a newer one is there) and auto (when the
    next sync will start by itself: AutoSync.status)."""
    now = time.time() if now is None else now
    with SYNC_LOCK:
        on_disk = synced()
        return {**sync_state, "data_at": on_disk[2],
                "auto": AUTO.status(now, on_disk, sync_state["running"], auto_on())}


def auto_tick(now, clock=time.time, awake=time.monotonic):
    """One look: starts a sync if the last good one is over 12 hours old, the Mac has been awake a
    moment, no retry is being waited for and Canvas can be reached. Returns whether it started one.
    `clock` and `awake` are the loop's two clocks (auto_sync_loop)."""
    with SYNC_LOCK:
        if sync_state["running"] or not auto_on() or not AUTO.due(now, synced()):
            return False
    # Asked outside the lock (it waits on the network). Offline is not a failed try: the next look asks
    # again, so the sync starts within a minute or so of the network coming back.
    url = canvas_url()
    asked, up = clock(), awake()
    online = not url or autosync.reachable(url)
    wall, awake_for = clock() - asked, awake() - up
    with SYNC_LOCK:
        # The answer can take seconds on a network that is up but slow, and the lid may close in
        # them: the answer then comes at some later wake, which may itself last only seconds. That
        # is a sleep like any other: the Mac is given its moment again, and nothing starts now.
        if autosync.woke(wall, awake_for):
            AUTO.waited(asked + wall, wall, awake_for)
            return False
        AUTO.offline = not online
        if not online or not start_sync():
            return False
        began, complete, _ = synced()
    log("syncing by itself: " + (f"the last good sync was {(now - began) / 3600:.1f} hours ago" if complete
                                 else "the last sync left something unread, or there is none yet"))
    return True


def school_root():
    cfg = json.loads((HUB / "config.json").read_text())
    return Path(cfg["school_root"]).expanduser().resolve()


def identity(path):
    """A file or folder as the disk knows it: the same for every spelling of its name."""
    st = path.stat()
    return st.st_dev, st.st_ino


def allowed_path(p):
    """A file or folder inside the School folder, or None. Never SchoolHub's own folder (config.json
    holds your Canvas token and Gradescope password, state/ your marks) and never a hidden one.

    The Mac's disk ignores case, so ".../schoolhub/config.json" is the same file as
    ".../SchoolHub/config.json": folders are compared by identity on the disk, not by name."""
    if not isinstance(p, str) or not p:
        return None
    try:
        path = Path(p).expanduser().resolve(strict=True)
        chain = [path, *path.parents]
        ids = [identity(x) for x in chain]
        root, hub = identity(school_root()), identity(HUB)
    except (OSError, RuntimeError, ValueError):
        return None
    if hub in ids or root not in ids[1:]:
        return None
    # The file itself and its folders below the School folder: none of them hidden (.git, .env).
    if any(x.name.startswith(".") for x in chain[:ids.index(root)]):
        return None
    return path


def read_state(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_state(path, obj):
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1))
    tmp.replace(path)


SEEDED_FILE = HUB / "state" / "cloud-seeded.json"  # which shared databases hold all of this Mac's
SEEDED = {"marks": False, "tasks": False, "plan": False, "notes": False}  # only then is the cloud trusted
BACKUPS = HUB / "state" / "backups"
KEEP_BACKUPS = 20


def log(msg):
    print(f"{datetime.now().isoformat(timespec='seconds')} {msg}", file=sys.stderr, flush=True)


def ensure_seeded(name):
    """Whether the shared database holds every mark, task or plan key this Mac had when it first
    connected. Each name is copied and remembered on its own.

    Until it does, the server reads and serves its own files (a partial set read from the cloud
    would replace them) and keeps trying the copy. Remembered per database in SEEDED_FILE, so the
    copy runs once and never brings back what the phone deleted later."""
    if not CLOUD:
        return False
    if SEEDED[name]:
        return True
    who = cloud.identity(CLOUD)
    if read_state(SEEDED_FILE).get(who, {}).get(name):
        SEEDED[name] = True
        return True
    try:
        cloud.seed(CLOUD, name, read_state(FILES[name]))
    except (OSError, RuntimeError) as e:
        log(f"copying {name} to the shared database failed, keeping the local file: {e}")
        return False
    record = read_state(SEEDED_FILE)
    record.setdefault(who, {})[name] = True
    write_state(SEEDED_FILE, record)
    SEEDED[name] = True
    log(f"{name} copied to the shared database; it is now the one the server reads")
    return True


def keep_copy(name, data):
    """Before the local file takes a set from the cloud that lacks some of its keys (deleted on the
    phone, or a database gone wrong), a dated copy of it is kept in state/backups/. A daily task's
    ✓ that was folded into its ledger there (tidy_daily) is not lost, so it does not count; a
    ledger that holds fewer days there than here is a loss like a key gone."""
    local = read_state(FILES[name])
    gone = set(local) - set(data)
    if name == "marks":
        gone = {key for key in gone if not folded(key, data)} | {key for key in local if lost_days(key, local, data)}
    if gone:
        backup(name, local)


def backup(name, data):
    """A dated copy of marks, tasks or the plan in state/backups/; the last KEEP_BACKUPS are kept."""
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    (BACKUPS / f"{name}-{stamp}.json").write_text(json.dumps(data, indent=1))
    for old in sorted(BACKUPS.glob(f"{name}-*.json"))[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)


def fresh(name):
    """Marks, tasks, the plan or the notes read from the shared database itself, or None when that
    cannot be done now (it did not answer, or it does not hold everything this Mac had yet): never
    the local copy, which may be behind it. With no shared database the local file is the store."""
    if not CLOUD:
        return read_state(FILES[name])
    if not SEEDED[name]:
        return None
    try:
        data = CLOUD.get_all(name)
    except (OSError, RuntimeError):
        return None
    # The local copy is for offline reads and the next sync: a disk that cannot take it (full, say)
    # does not make the database's answer any less right.
    try:
        keep_copy(name, data)
        write_state(FILES[name], data)
    except OSError as e:
        log(f"keeping the local copy of {name} failed: {e}")
    return data


def load(name):
    """Marks, tasks or the plan: from the cloud database once it holds everything this Mac had (the phone
    can change them there), else the local file."""
    data = fresh(name)
    return read_state(FILES[name]) if data is None else data


def put(name, key, obj):
    if CLOUD:
        CLOUD.put(name, key, obj)
    data = read_state(FILES[name])
    data[key] = obj
    write_state(FILES[name], data)


def remove(name, key):
    if CLOUD:
        CLOUD.remove(name, key)
    data = read_state(FILES[name])
    data.pop(key, None)
    write_state(FILES[name], data)


def remove_all(name, keys):
    """Several keys at once: one request to the shared database, however many there are."""
    if CLOUD:
        CLOUD.remove_many(name, keys)
    data = read_state(FILES[name])
    for key in keys:
        data.pop(key, None)
    write_state(FILES[name], data)


# A mark's time as either server writes it: UTC, to the second or with 3 or 6 decimals, ending in
# +00:00 (this server, the public site) or Z (the phone view). [0-9] and fullmatch for the reasons
# plan.py gives.
MARK_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{3}|\.[0-9]{6})?(?:Z|\+00:00)")


def mark_time(given):
    """When a mark was made: now, or the time sent with a mark the page puts back as it was (its undo
    of taking the mark away), so the last sync's answer for that very mark still applies to it.
    Only a real time written as MARK_TIME that is not in the future; anything else is now. A server
    without this rule (the phone view's, or a public copy from before it) stamps the mark now, which
    the page takes as it comes."""
    now = datetime.now(timezone.utc)
    if isinstance(given, str) and MARK_TIME.fullmatch(given):
        try:
            if datetime.fromisoformat(given.replace("Z", "+00:00")) <= now:
                return given
        except ValueError:
            pass
    return now.isoformat()


REPEAT_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

# ---------- daily tasks: the days done, kept for good ----------
#
# A task that repeats is shown by the page as an item of each day it is on, and its ✓ is an ordinary
# mark under "<task id>@<day>" (dashboard.js, "daily tasks"). So that a run of days can be counted
# for as long as it lasts, those marks are never thrown away; but a mark is some 140 characters, and
# every mark travels in every answer. So the ✓ of a day more than a week past is FOLDED: its day
# goes into the task's ledger, one mark under "<task id>@done" whose `days` are written as runs
# ("2026-11-03", or "2026-11-09..2026-11-13" for days in a row: years of a daily task are one
# entry), and the day's own mark goes. The page, QuantPrep's Dashboard and its public site read a
# task's days from both. The ledger does not need the task: it outlives a deleted task, and is
# found again by one brought back.
#
# This server is the only writer of ledgers: the public site and the phone view store and remove
# daily marks under the same three rules at the door (daily_guard) and never fold. A ledger is
# changed by hand only in the database itself.
DAILY_MARK = re.compile(r"(task:[a-z0-9]{8,32})@([0-9]{4}-[0-9]{2}-[0-9]{2})")
LEDGER = "@done"
FOLD_AFTER = 7       # days: a ✓ at most this old is a mark, made and taken back as any ✓ is
TICK_AHEAD = 2       # days: how far past this computer's today a ✓ may be dated (clocks differ by a day)
FOLD_WHEN = 14       # days: a task's marks are folded once its oldest ✓ is older than this
FOLD_AT_ONCE = 31    # days folded at a time, the oldest first
RUN_DAYS_LIMIT = 5000
LEDGER_LIMIT = 40000  # days of a ledger read before it is written again: over a century of them


def real_day(v):
    """Whether v is a day on the calendar written YYYY-MM-DD, of the year 2000 or later: the one
    rule the page (realDay) and QuantPrep (isDay) use too."""
    if type(v) is not str or not REPEAT_DATE.fullmatch(v) or v < "2000-01-01":
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


def day_runs(days):
    """Days written as runs: sorted, each once, a day alone as itself and days in a row as
    "first..last". What is not a real day is left out. tests/daily_vectors.json holds this and
    run_days to what the page and QuantPrep do."""
    runs, first, last = [], None, None
    for day in sorted({d for d in days if real_day(d)}):
        if last is not None and date.fromisoformat(day) - date.fromisoformat(last) == timedelta(days=1):
            last = day
            continue
        if first is not None:
            runs.append(first if first == last else f"{first}..{last}")
        first = last = day
    if first is not None:
        runs.append(first if first == last else f"{first}..{last}")
    return runs


def run_days(runs, limit=RUN_DAYS_LIMIT):
    """The days of a list of runs, each once, sorted. What is no day or run is left out (a run
    written backwards too). At most `limit` days are read, from the end of the list back, so a list
    too long keeps its latest days."""
    days = set()
    for run in reversed(runs) if isinstance(runs, list) else ():
        if type(run) is not str:
            continue
        parts = run.split("..")
        first, last = parts[0], parts[1] if len(parts) > 1 else parts[0]
        if len(parts) > 2 or not real_day(first) or not real_day(last) or last < first:
            continue
        day, stop = date.fromisoformat(last), date.fromisoformat(first)
        while day >= stop and len(days) < limit:
            days.add(day.isoformat())
            day -= timedelta(days=1)
    return sorted(days)


def ledger_days(marks, tid, limit=RUN_DAYS_LIMIT):
    """The days in the ledger of the daily task `tid`, or none when it has no ledger that reads."""
    ledger = marks.get(tid + LEDGER)
    return run_days(ledger.get("days"), limit) if isinstance(ledger, dict) else []


def folded(key, marks):
    """Whether `key` is a daily task's ✓ whose day is in that task's ledger in `marks`."""
    m = DAILY_MARK.fullmatch(key) if type(key) is str else None
    return bool(m) and m.group(2) in ledger_days(marks, m.group(1))


def lost_days(key, local, data):
    """Whether `key` is a ledger whose days in `local` are not all in `data`, as that ledger's or
    as marks of their own."""
    if type(key) is not str or not key.endswith(LEDGER):
        return False
    tid = key[:-len(LEDGER)]
    there = set(ledger_days(data, tid, LEDGER_LIMIT))
    return any(day not in there and f"{tid}@{day}" not in data for day in ledger_days(local, tid, LEDGER_LIMIT))


def days_ago(today, n):
    return (today - timedelta(days=n)).isoformat()


def daily_guard(aid, done, today):
    """What api/mark does with the mark `aid` before anything is stored, by this computer's `today`:

      "bad id"   it names a ledger, which no request makes or takes away;
      "bad day"  a daily task's ✓ for a day that is no day, or more than FOLD_AFTER days past, or
                 more than TICK_AHEAD days ahead. Two honest clocks are never more than a day
                 apart, so no real ✓ is refused, and none can be made that is old enough to fold;
      "keep"     taking away a daily task's ✓ of a day more than FOLD_AFTER days past: that is its
                 history, so nothing changes (a page from before the ledger tidied such marks by
                 deleting them);
      None       any other mark: stored, or removed.

    The public site (QuantPrep's schoolPublic.ts) and the phone view (vercel/api/state.js) decide
    the same way; the `guard` cases in tests/daily_vectors.json hold all three to it."""
    if aid.endswith(LEDGER):
        return "bad id"
    m = DAILY_MARK.fullmatch(aid)
    if not m:
        return None
    day, cut = m.group(2), days_ago(today, FOLD_AFTER)
    if done:
        return None if real_day(day) and cut <= day <= days_ago(today, -TICK_AHEAD) else "bad day"
    return "keep" if real_day(day) and day < cut else None


def fold_plan(marks, today):
    """What to fold now, or None: (task id, its days to fold, its ledger's days as they are then).

    Of the daily tasks with a ✓ more than FOLD_AFTER days past, the one whose oldest waits longest,
    once that one is more than FOLD_WHEN days past: its marks older than FOLD_AFTER days, the
    oldest FOLD_AT_ONCE of them. So a task's marks are folded about once a week, a week's worth at
    a time, and a task no longer ticked gets its turn too."""
    cut, old = days_ago(today, FOLD_AFTER), {}
    for key in marks:
        m = DAILY_MARK.fullmatch(key) if type(key) is str else None
        if m and real_day(m.group(2)) and m.group(2) < cut:
            old.setdefault(m.group(1), []).append(m.group(2))
    if not old:
        return None
    tid = min(old, key=lambda t: (min(old[t]), t))
    if min(old[tid]) >= days_ago(today, FOLD_WHEN):
        return None
    days = sorted(old[tid])[:FOLD_AT_ONCE]
    # An entry of the stored ledger that does not read as a day or a run (one edited by hand, say)
    # is carried over as it is, after the runs: no reader counts it, and no fold throws it away.
    stored = marks.get(tid + LEDGER)
    stored = stored.get("days") if isinstance(stored, dict) else None
    unread = [r for r in stored if not (type(r) is str and run_days([r], 1))] if isinstance(stored, list) else []
    return tid, days, day_runs(ledger_days(marks, tid, LEDGER_LIMIT) + days) + unread


def tidy_daily(today=None):
    """Run after a daily task's ✓ is stored, with LOCK held: folds what fold_plan says, if anything.

    The marks are read from the shared database itself, never from the local copy (which may lack
    days the ledger there already holds), and nothing is folded when it cannot be read. The ledger
    is written first and read back, and only the marks of days it then holds are removed: a
    failure in between leaves a day in both, which every reader counts once, and a later fold
    finishes the job. It never raises: the ✓ that set it off is stored whatever happens here."""
    try:
        marks = fresh("marks")
        plan = fold_plan(marks, today or date.today()) if marks is not None else None
        if not plan:
            return
        tid, days, runs = plan
        ledger = marks.get(tid + LEDGER)
        if tid + LEDGER in marks and not (isinstance(ledger, dict) and isinstance(ledger.get("days"), list)):
            # A ledger that is no ledger (changed by hand in the database): it is replaced, so the
            # marks as they were are kept in state/backups first.
            backup("marks", marks)
        put("marks", tid + LEDGER, {"marked_at": datetime.now(timezone.utc).isoformat(), "days": runs})
        after = fresh("marks")
        if after is None:
            return
        held = set(ledger_days(after, tid, LEDGER_LIMIT))
        gone = [f"{tid}@{day}" for day in days if day in held]
        if gone:
            remove_all("marks", gone)
    except Exception as e:  # the ✓ is stored; the fold waits for the next one
        log(f"folding a daily task's old marks failed, they stay as they are: {e}")


def clean_repeat(given):
    """A task's repeat, for one that shows fresh each day it is on (the page's Daily group): the
    weekdays, 0 for Sunday to 6 for Saturday as the page counts them, and the last day it shows
    (until, a date or None for no end). None for a task that does not repeat. Returns (repeat, error)."""
    if given is None or given is False:
        return None, None
    if not isinstance(given, dict):
        return None, "repeat must be an object"
    days = given.get("days")
    if not isinstance(days, list) or not days or any(type(d) is not int or not 0 <= d <= 6 for d in days):
        return None, "repeat needs days, each a weekday from 0 (Sunday) to 6"
    until = given.get("until") or None
    if until is not None:
        try:
            if not isinstance(until, str) or not REPEAT_DATE.fullmatch(until):
                raise ValueError(until)
            date.fromisoformat(until)
        except ValueError:
            return None, "repeat's until must be a date written YYYY-MM-DD"
    return {"days": sorted(set(days)), "until": until}, None


def clean_task(body, existing):
    """Validate a task from the dashboard form. Returns (task, error)."""
    name = str(body.get("name") or "").strip()[:200]
    if not name:
        return None, "a task needs a name"
    due = body.get("due_at") or None
    if due:
        try:
            datetime.fromisoformat(str(due).replace("Z", "+00:00"))
        except ValueError:
            return None, "due_at must be an ISO date"
    repeat, error = clean_repeat(body.get("repeat"))
    if error:
        return None, error
    if repeat:
        due = None  # it shows on its days, never by a date of its own
    stamp = datetime.now(timezone.utc).isoformat()
    return {
        "name": name,
        "course_id": str(body.get("course_id") or "personal")[:80],
        "due_at": due,
        "all_day": bool(due) and bool(body.get("all_day")),
        # Kept at the top under "My tasks", or put in the list by its date like any other item. A
        # task saved without the choice (before it existed) is pinned when it has no date, as then.
        "pinned": bool(body["pinned"]) if "pinned" in body else not due,
        "notes": str(body.get("notes") or "").strip()[:5000],
        "created_at": (existing or {}).get("created_at") or body.get("created_at") or stamp,
        "updated_at": stamp,
        # Only on a task that repeats, so every other task is stored as it always was.
        **({"repeat": repeat} if repeat else {}),
    }, None


def clean_note(body, existing):
    """A note from the Notes popup: its text, kept as typed (only the end's blank lines go), and
    when it was made and last changed. Returns (note, error)."""
    text = body.get("text")
    if not isinstance(text, str):
        return None, "a note's text must be a string"
    text = text.rstrip()
    if not text.strip():
        return None, "a note needs some text"
    if len(text) > NOTE_LIMIT:
        return None, f"a note is at most {NOTE_LIMIT} characters"
    stamp = datetime.now(timezone.utc).isoformat()
    return {
        "text": text,
        "created_at": (existing or {}).get("created_at") or stamp,
        "updated_at": stamp,
    }, None


class Handler(BaseHTTPRequestHandler):
    server_version = "SchoolHub"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body=b"", ctype="text/plain", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj):
        self._send(200, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        # Host check blocks DNS-rebinding tricks from other websites.
        if self.headers.get("Host") not in ALLOWED_HOSTS:
            return self._send(403, b"forbidden")
        url = urlsplit(self.path)
        if url.path in PAGES:
            f = HUB / PAGES[url.path]
            if not f.exists():
                return self._send(404, b"not found")
            page = f.suffix == ".html"
            return self._send(200, f.read_bytes(), PAGE_TYPES[f.suffix],
                              {"Content-Security-Policy": PAGE_CSP} if page else None)
        if url.path == "/platform.json":
            # On its own server SchoolHub is not part of a platform: nothing to describe, so the page
            # keeps its plain title. (A 204 rather than a 404, which browsers log as an error.)
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if url.path == "/api/sync":
            return self._json(sync_status())
        if url.path == "/api/tasks":
            with LOCK:
                return self._json({"tasks": load("tasks")})
        if url.path == "/api/marks":
            with LOCK:
                return self._json(load("marks"))
        if url.path == "/api/notes":
            with LOCK:
                return self._json({"notes": load("notes")})
        if url.path == "/api/plan":
            # Dates on this computer's clock, as the page shows them.
            try:
                start, end = plan.plan_range(parse_qs(url.query, keep_blank_values=True), date.today())
            except plan.Refused as e:
                return self._send(400, str(e).encode())
            with LOCK:
                return self._json(plan.assemble(load("plan"), start, end))
        # /file?p=<path>, or /file/<name>?p=<path>: the name is only for the browser (a PDF tab
        # shows it as its title); the file is always the one p names.
        if url.path == "/file" or url.path.startswith("/file/"):
            p = allowed_path(parse_qs(url.query).get("p", [""])[0])
            if not p or not p.is_file():
                return self._send(404, b"not found")
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            if SCRIPT_TYPE.search(ctype):
                ctype = "text/plain; charset=utf-8"
            return self._send(200, p.read_bytes(), ctype,
                              {"Content-Disposition": f"inline; filename*=UTF-8''{quote(p.name)}",
                               "Content-Security-Policy": PDF_CSP if ctype == "application/pdf" else FILE_CSP})
        self._send(404, b"not found")

    do_HEAD = do_GET

    def do_POST(self):
        # Requiring a custom header forces a CORS preflight that we never approve,
        # so other sites open in your browser can't call these endpoints.
        if self.headers.get("Host") not in ALLOWED_HOSTS or self.headers.get("X-SchoolHub") != "1":
            return self._send(403, b"forbidden")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except (json.JSONDecodeError, ValueError):
            return self._send(400, b"bad request")
        if not isinstance(body, dict):
            return self._send(400, b"bad request")
        path = urlsplit(self.path).path

        if path == "/api/mark":
            aid = str(body.get("id") or "")
            if not aid:
                return self._send(400, b"missing id")
            done = bool(body.get("done"))
            with LOCK:
                # One day for the door and the fold, read under the lock: an untick let through just
                # before midnight must not meet a fold made just after it.
                today = date.today()
                guard = daily_guard(aid, done, today)
                if guard in ("bad id", "bad day"):
                    return self._send(400, guard.encode())
                try:
                    if guard == "keep":
                        pass
                    elif done:
                        put("marks", aid, {"marked_at": mark_time(body.get("marked_at")),
                                           "name": body.get("name"), "course": body.get("course")})
                    else:
                        remove("marks", aid)
                except (OSError, RuntimeError):
                    return self._send(502, b"couldn't reach the cloud database")
                if done and DAILY_MARK.fullmatch(aid):
                    tidy_daily(today)
                marks = load("marks")
            return self._json(marks)

        if path == "/api/task":
            tid = str(body.get("id") or "") or f"task:{uuid.uuid4().hex[:12]}"
            if not TASK_ID.match(tid):
                return self._send(400, b"bad task id")
            with LOCK:
                task, error = clean_task(body, load("tasks").get(tid))
                if error:
                    return self._send(400, error.encode())
                task = {"id": tid, **task}
                try:
                    put("tasks", tid, task)
                except (OSError, RuntimeError):
                    return self._send(502, b"couldn't reach the cloud database")
                tasks = load("tasks")
            return self._json({"task": task, "tasks": tasks})

        if path == "/api/task/delete":
            with LOCK:
                tid = str(body.get("id") or "")
                removed = load("tasks").get(tid)
                try:
                    remove("tasks", tid)
                except (OSError, RuntimeError):
                    return self._send(502, b"couldn't reach the cloud database")
                tasks = load("tasks")
            return self._json({"removed": removed, "tasks": tasks})

        if path == "/api/note":
            nid = str(body.get("id") or "") or f"note:{uuid.uuid4().hex[:12]}"
            if not NOTE_ID.match(nid):
                return self._send(400, b"bad note id")
            with LOCK:
                notes = load("notes")
                if nid not in notes and len(notes) >= NOTES_LIMIT:
                    return self._send(400, f"there is room for {NOTES_LIMIT} notes".encode())
                note, error = clean_note(body, notes.get(nid))
                if error:
                    return self._send(400, error.encode())
                note = {"id": nid, **note}
                try:
                    put("notes", nid, note)
                except (OSError, RuntimeError):
                    return self._send(502, b"couldn't reach the cloud database")
                notes = load("notes")
            return self._json({"note": note, "notes": notes})

        if path == "/api/note/delete":
            with LOCK:
                nid = str(body.get("id") or "")
                removed = load("notes").get(nid)
                try:
                    remove("notes", nid)
                except (OSError, RuntimeError):
                    return self._send(502, b"couldn't reach the cloud database")
                notes = load("notes")
            return self._json({"removed": removed, "notes": notes})

        if path == "/api/plan":
            # A whole value replaces the key's; null deletes it, which brings back the defaults. A
            # body without "value" is refused rather than read as null, so a slip never deletes.
            if "value" not in body:
                return self._send(400, b"missing value")
            key = body.get("key")
            value, error = plan.clean_plan(key, body["value"])
            if error:
                return self._send(400, error.encode())
            with LOCK:
                try:
                    if value is None:
                        remove("plan", key)
                    else:
                        put("plan", key, value)
                except (OSError, RuntimeError):
                    return self._send(502, b"couldn't reach the cloud database")
            return self._json({"key": key, "value": value})

        if path == "/api/sync":
            with SYNC_LOCK:
                start_sync(manual=True)
            return self._json(sync_status())

        if path in ("/api/open", "/api/reveal"):
            p = allowed_path(body.get("path") or "")
            if not p:
                return self._send(404, b"not found")
            reveal = path == "/api/reveal" and p.is_file()
            subprocess.run(["open", "-R", str(p)] if reveal else ["open", str(p)], check=False)
            return self._json({"ok": True})

        self._send(404, b"not found")


def auto_sync_loop(clock=time.time, sleep=time.sleep, awake=time.monotonic):
    """Looks once a minute whether a sync is due (auto_tick). `awake` is a clock that stops while
    the Mac sleeps: a wait that took longer by the wall clock than by that one was partly slept
    through, and the Mac is then given a moment (autosync.SETTLE) before a sync starts."""
    # The two clocks are compared from one look to the next, not only across the wait between
    # them, so a sleep that began while a look was busy is seen at the next one too.
    before, up = clock(), awake()
    while True:
        sleep(autosync.TICK)
        now, now_up = clock(), awake()
        try:
            with SYNC_LOCK:
                AUTO.waited(now, now - before, now_up - up)
            before, up = now, now_up
            auto_tick(now, clock, awake)
        except Exception as e:  # the loop outlives anything a look runs into
            log(f"looking whether a sync is due failed: {e}")


def seed_loop():
    """Copies the local marks, tasks, plan and notes to the shared database, retrying every minute until all
    four are there. Each is tried on its own, so one that keeps failing (the plan's table not made
    yet on Turso, say) never holds up the others."""
    while not all(SEEDED.values()):
        for name in FILES:
            with LOCK:
                ensure_seeded(name)
        if not all(SEEDED.values()):
            time.sleep(60)


if __name__ == "__main__":
    if CLOUD:
        threading.Thread(target=seed_loop, daemon=True).start()
    threading.Thread(target=auto_sync_loop, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
