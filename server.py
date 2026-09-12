#!/usr/bin/env python3
"""SchoolHub local server: http://localhost:8722

Serves the dashboard and your class files, and saves "mark as done" clicks to
state/marks.json so the nightly sync can double-check them. Listens on 127.0.0.1 only.
"""
import json
import mimetypes
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

HUB = Path(__file__).resolve().parent
MARKS = HUB / "state" / "marks.json"
PORT = 8722
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
PAGES = {"/": "dashboard.html", "/dashboard.html": "dashboard.html", "/data.js": "data.js"}
STALE_HOURS = 20
LOCK = threading.Lock()
SYNC_LOCK = threading.Lock()
sync_state = {"running": False, "started_at": None, "finished_at": None, "ok": None, "output": ""}


def run_sync():
    try:
        p = subprocess.run([sys.executable, str(HUB / "sync.py")], capture_output=True, text=True, timeout=1800)
        ok, out = p.returncode == 0, (p.stdout + p.stderr).strip()
    except Exception as e:
        ok, out = False, str(e)
    with SYNC_LOCK:
        sync_state.update(running=False, finished_at=datetime.now(timezone.utc).isoformat(), ok=ok, output=out[-4000:])


def school_root():
    cfg = json.loads((HUB / "config.json").read_text())
    return Path(cfg["school_root"]).expanduser().resolve()


def allowed_path(p):
    """Only files inside the School folder, and never SchoolHub itself (config holds the token)."""
    try:
        path = Path(p).expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    root = school_root()
    if root not in path.parents or path == HUB or HUB in path.parents:
        return None
    return path if path.exists() else None


def load_marks():
    try:
        return json.loads(MARKS.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_marks(marks):
    MARKS.parent.mkdir(exist_ok=True)
    tmp = MARKS.with_suffix(".tmp")
    tmp.write_text(json.dumps(marks, indent=1))
    tmp.replace(MARKS)


class Handler(BaseHTTPRequestHandler):
    server_version = "SchoolHub"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body=b"", ctype="text/plain", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
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
            ctype = "text/html; charset=utf-8" if f.suffix == ".html" else "text/javascript; charset=utf-8"
            return self._send(200, f.read_bytes(), ctype)
        if url.path == "/api/sync":
            with SYNC_LOCK:
                return self._json(sync_state)
        if url.path == "/api/marks":
            with LOCK:
                return self._json(load_marks())
        if url.path == "/file":
            p = allowed_path(parse_qs(url.query).get("p", [""])[0])
            if not p or not p.is_file():
                return self._send(404, b"not found")
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            return self._send(200, p.read_bytes(), ctype,
                              {"Content-Disposition": f"inline; filename*=UTF-8''{quote(p.name)}"})
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
        path = urlsplit(self.path).path

        if path == "/api/mark":
            aid = str(body.get("id") or "")
            if not aid:
                return self._send(400, b"missing id")
            with LOCK:
                marks = load_marks()
                if body.get("done"):
                    marks[aid] = {"marked_at": datetime.now(timezone.utc).isoformat(),
                                  "name": body.get("name"), "course": body.get("course")}
                else:
                    marks.pop(aid, None)
                save_marks(marks)
            return self._json(marks)

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


if __name__ == "__main__":
    threading.Thread(target=catch_up_loop, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
