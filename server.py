#!/usr/bin/env python3
"""SchoolHub local server: http://localhost:8722

Serves the dashboard and your class files, saves "mark as done" clicks to state/marks.json
(which the nightly sync double-checks), and stores your own tasks in state/tasks.json. Listens on 127.0.0.1 only.
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
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import cloud

HUB = Path(__file__).resolve().parent
MARKS = HUB / "state" / "marks.json"
TASKS = HUB / "state" / "tasks.json"
TASK_ID = re.compile(r"^task:[a-z0-9]{8,32}$")
FILES = {"marks": MARKS, "tasks": TASKS}
CLOUD = cloud.connect()  # shared with the phone view when state/cloud.env exists
PORT = int(os.environ.get("SCHOOLHUB_PORT") or 8722)  # another port for a test copy beside the real one
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
PAGES = {"/": "dashboard.html", "/dashboard.html": "dashboard.html", "/dashboard.js": "dashboard.js",
         "/theme-init.js": "theme-init.js", "/bar.js": "bar.js", "/data.js": "data.js", "/favicon.svg": "favicon.svg"}
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
STALE_HOURS = 20
LOCK = threading.Lock()
SYNC_LOCK = threading.Lock()
sync_state = {"running": False, "started_at": None, "finished_at": None, "ok": None, "output": ""}


def sync_log():
    """Where each sync the server runs (Sync now, the catch-up) adds its output: state/sync.log,
    where the nightly sync's cron line can add its own (README)."""
    return HUB / "state" / "sync.log"


def run_sync():
    started = datetime.now(timezone.utc).isoformat()
    try:
        p = subprocess.run([sys.executable, str(HUB / "sync.py")], capture_output=True, text=True, timeout=1800)
        ok, out = p.returncode == 0, (p.stdout + p.stderr).strip()
    except Exception as e:
        ok, out = False, str(e)
    # Kept where the page's "Sync failed" points, since the output is otherwise only in memory.
    try:
        with sync_log().open("a") as f:
            f.write(f"--- sync from the server, {started}: {'done' if ok else 'failed'}\n")
            if out:
                f.write(out + "\n")
    except OSError:
        pass
    with SYNC_LOCK:
        sync_state.update(running=False, finished_at=datetime.now(timezone.utc).isoformat(), ok=ok, output=out[-4000:])


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
SEEDED = {"marks": False, "tasks": False}           # marks and tasks: only then is the cloud trusted
BACKUPS = HUB / "state" / "backups"
KEEP_BACKUPS = 20


def log(msg):
    print(f"{datetime.now().isoformat(timespec='seconds')} {msg}", file=sys.stderr, flush=True)


def ensure_seeded(name):
    """Whether the shared database holds every mark or task this Mac had when it first connected.

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
    phone, or a database gone wrong), a dated copy of it is kept in state/backups/."""
    local = read_state(FILES[name])
    if not set(local) - set(data):
        return
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    (BACKUPS / f"{name}-{stamp}.json").write_text(json.dumps(local, indent=1))
    for old in sorted(BACKUPS.glob(f"{name}-*.json"))[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)


def load(name):
    """Marks or tasks: from the cloud database once it holds everything this Mac had (the phone
    can change them there), else the local file."""
    if CLOUD and SEEDED[name]:
        try:
            data = CLOUD.get_all(name)
            keep_copy(name, data)
            write_state(FILES[name], data)  # local copy for offline reads and the nightly sync
            return data
        except (OSError, RuntimeError):
            pass
    return read_state(FILES[name])


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
    stamp = datetime.now(timezone.utc).isoformat()
    return {
        "name": name,
        "course_id": str(body.get("course_id") or "personal")[:80],
        "due_at": due,
        "all_day": bool(due) and bool(body.get("all_day")),
        "notes": str(body.get("notes") or "").strip()[:5000],
        "created_at": (existing or {}).get("created_at") or body.get("created_at") or stamp,
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
            with SYNC_LOCK:
                return self._json(sync_state)
        if url.path == "/api/tasks":
            with LOCK:
                return self._json({"tasks": load("tasks")})
        if url.path == "/api/marks":
            with LOCK:
                return self._json(load("marks"))
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
            with LOCK:
                try:
                    if body.get("done"):
                        put("marks", aid, {"marked_at": datetime.now(timezone.utc).isoformat(),
                                           "name": body.get("name"), "course": body.get("course")})
                    else:
                        remove("marks", aid)
                except (OSError, RuntimeError):
                    return self._send(502, b"couldn't reach the cloud database")
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

        if path == "/api/sync":
            with SYNC_LOCK:
                if not sync_state["running"]:
                    sync_state.update(running=True, started_at=datetime.now(timezone.utc).isoformat(), ok=None, output="")
                    threading.Thread(target=run_sync, daemon=True).start()
                return self._json(sync_state)

        if path in ("/api/open", "/api/reveal"):
            p = allowed_path(body.get("path") or "")
            if not p:
                return self._send(404, b"not found")
            reveal = path == "/api/reveal" and p.is_file()
            subprocess.run(["open", "-R", str(p)] if reveal else ["open", str(p)], check=False)
            return self._json({"ok": True})

        self._send(404, b"not found")


def catch_up_loop():
    """If the nightly sync didn't land (asleep, network hiccup), sync once we notice."""
    while True:
        time.sleep(900)
        try:
            age_hours = (time.time() - (HUB / "data.js").stat().st_mtime) / 3600
        except OSError:
            age_hours = 1e6
        with SYNC_LOCK:
            due = age_hours > STALE_HOURS and 6 <= datetime.now().hour < 23 and not sync_state["running"]
            if due:
                sync_state.update(running=True, started_at=datetime.now(timezone.utc).isoformat(), ok=None, output="")
        if due:
            threading.Thread(target=run_sync, daemon=True).start()


def seed_loop():
    """Copies the local marks and tasks to the shared database, retrying every minute until both
    are there."""
    while not all(SEEDED.values()):
        for name in FILES:
            with LOCK:
                ensure_seeded(name)
        if not all(SEEDED.values()):
            time.sleep(60)


if __name__ == "__main__":
    if CLOUD:
        threading.Thread(target=seed_loop, daemon=True).start()
    threading.Thread(target=catch_up_loop, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
