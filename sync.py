#!/usr/bin/env python3
"""SchoolHub sync: mirrors Canvas (and Gradescope, if configured) into your class folders
and writes data.js for dashboard.html.

Never deletes anything, and never overwrites a downloaded file you've edited.
Stdout only lists things that need attention, so a nightly cron job stays quiet when
everything is fine. A run summary goes to stderr.

Usage: python3 sync.py [--open]
"""
import html
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    # Use the macOS keychain for TLS trust; python.org Python ships without system CAs.
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

# Gradescope's library sets no timeout of its own; this keeps a stalled read from hanging forever.
socket.setdefaulttimeout(90)

HUB = Path(__file__).resolve().parent
STATE = HUB / "state"
MANIFEST = STATE / "manifest.json"
ALERTED = STATE / "alerted.json"
MARKS = STATE / "marks.json"
TASKS = STATE / "tasks.json"
DATA_JS = HUB / "data.js"
MAX_BYTES = 250 * 1024 * 1024
OFFLINE_TYPES = {"none", "on_paper", "not_graded"}
FILE_LINK = re.compile(r"(?:/courses/(\d+))?/files/(\d+)")


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    tmp = Path(f"{path}.tmp")
    tmp.write_text(json.dumps(obj, indent=1))
    tmp.replace(path)


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def fmt_local(dt):
    return dt.astimezone().strftime("%a %-m/%-d %-I:%M %p")


def safe_name(s, limit=110):
    s = html.unescape(s or "untitled")
    s = re.sub(r"[/:\\\x00-\x1f]", "-", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:limit].rstrip(" .") or "untitled"


def unique_path(p):
    candidate, n = p, 2
    while candidate.exists():
        candidate = p.with_name(f"{p.stem} ({n}){p.suffix}")
        n += 1
    return candidate


def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


class _DropAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Canvas downloads redirect to storage hosts that reject our bearer token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


OPENER = urllib.request.build_opener(_DropAuthOnRedirect)


class Canvas:
    def __init__(self, base, token):
        self.base = base.rstrip("/")
        self.token = token

    def request(self, url, raw=False):
        headers = {"User-Agent": "SchoolHub/1.0"}
        if url.startswith(self.base):
            headers["Authorization"] = f"Bearer {self.token}"
        for attempt in range(3):
            try:
                resp = OPENER.open(urllib.request.Request(url, headers=headers), timeout=90)
                if raw:
                    return resp
                with resp:
                    return json.loads(resp.read().decode()), resp.headers.get("Link", "")
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise

    def _url(self, path, params):
        return f"{self.base}/api/v1{path}?" + urllib.parse.urlencode(params, doseq=True)

    def get(self, path, **params):
        return self.request(self._url(path, params))[0]

    def get_all(self, path, **params):
        params.setdefault("per_page", 100)
        url, out = self._url(path, params), []
        while url:
            data, link = self.request(url)
            out.extend(data if isinstance(data, list) else [data])
            m = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = m.group(1) if m and m.group(1).startswith(self.base) else None
        return out

    def download(self, url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        with self.request(url, raw=True) as resp, open(part, "wb") as f:
            while chunk := resp.read(1 << 16):
                f.write(chunk)
        part.replace(dest)


class FileStore:
    """Downloads each source file once, tracked by id; never clobbers files you've edited."""

    def __init__(self, downloader):
        self.manifest = load_json(MANIFEST, {})
        self.download = downloader
        self.new = []
        self.errors = []

    def fetch(self, key, name, size, version, url, dest_dir, download=None):
        name = safe_name(name)
        if size and size > MAX_BYTES:
            self.errors.append(f"Skipped {name}: {size // 1_000_000} MB is over the size limit")
            return None
        rec = self.manifest.get(key)
        if rec and Path(rec["path"]).exists():
            path = Path(rec["path"])
            if rec["version"] == version:
                return self._out(path)
            st = path.stat()
            untouched = st.st_size == rec["size"] and abs(st.st_mtime - rec["mtime"]) < 2
            today = datetime.now().strftime("%Y-%m-%d")
            dest = path if untouched else unique_path(path.with_name(f"{path.stem} (updated {today}){path.suffix}"))
        else:
            dest = dest_dir / name
            if dest.exists():
                if size and dest.stat().st_size == size:
                    self._record(key, dest, version)
                    return self._out(dest)
                dest = unique_path(dest)
        try:
            (download or self.download)(url, dest)
        except Exception as e:
            self.errors.append(f"Couldn't download {name}: {e}")
            return None
        self._record(key, dest, version)
        self.new.append(str(dest))
        return self._out(dest)

    def _record(self, key, path, version):
        st = path.stat()
        self.manifest[key] = {"path": str(path), "version": version, "size": st.st_size, "mtime": st.st_mtime}

    @staticmethod
    def _out(path):
        return {"name": path.name, "path": str(path), "size": path.stat().st_size}

    def save(self):
        save_json(MANIFEST, self.manifest)


# ---------- Canvas ----------

def canvas_status(a, sub, now):
    if sub.get("excused"):
        return "excused"
    if sub.get("score") is not None or sub.get("grade") not in (None, "") or sub.get("workflow_state") == "graded":
        return "graded"
    if sub.get("submitted_at") or sub.get("workflow_state") in ("submitted", "pending_review"):
        return "submitted"
    if set(a.get("submission_types") or []) <= OFFLINE_TYPES:
        return "offline"
    due = parse_ts(a.get("due_at"))
    missing = sub["missing"] if "missing" in sub else bool(due and due < now)
    if missing:
        # Leftovers from a reused course shell (due dates from a past year) aren't actionable.
        return "expired" if now - due > timedelta(days=120) else "missing"
    return "todo"


def canvas_platform(a):
    types = set(a.get("submission_types") or [])
    if "external_tool" in types:
        tool = json.dumps(a.get("external_tool_tag_attributes") or {}).lower()
        return "Gradescope" if "gradescope" in tool else "External tool"
    if "online_quiz" in types:
        return "Canvas quiz"
    if "discussion_topic" in types:
        return "Discussion"
    if types & {"online_upload", "online_text_entry", "online_url", "media_recording"}:
        return "Canvas"
    if "on_paper" in types:
        return "On paper"
    return "Not online"


def write_instructions(adir, a, desc, local):
    def relink(m):
        link = FILE_LINK.search(m.group(1))
        if link and link.group(2) in local:
            return f'href="{urllib.parse.quote(os.path.relpath(local[link.group(2)], adir))}"'
        return m.group(0)

    due = parse_ts(a.get("due_at"))
    page = (
        f"<!doctype html><meta charset='utf-8'><title>{html.escape(a['name'])}</title>"
        "<style>body{font:16px/1.55 -apple-system,sans-serif;max-width:760px;margin:40px auto;padding:0 20px}"
        "img{max-width:100%}</style>"
        f"<h1>{html.escape(a['name'])}</h1>"
        f"<p><b>Due:</b> {fmt_local(due) if due else 'No due date'} · "
        f"<a href='{html.escape(a.get('html_url') or '')}'>Open on Canvas</a></p><hr>"
        + re.sub(r'href="([^"]*)"', relink, desc)
    )
    adir.mkdir(parents=True, exist_ok=True)
    out = adir / "Instructions.html"
    if not out.exists() or out.read_text() != page:
        out.write_text(page)


def sync_canvas_course(cv, course, folder, store, now):
    cid = str(course["id"])
    meta_cache = {}

    def file_meta(fid, course_id):
        if fid not in meta_cache:
            meta = None
            for path in (f"/courses/{course_id}/files/{fid}", f"/files/{fid}"):
                try:
                    meta = cv.get(path)
                    break
                except urllib.error.HTTPError:
                    continue
            if meta and (meta.get("locked_for_user") or not meta.get("url")):
                meta = None
            meta_cache[fid] = meta
        return meta_cache[fid]

    def fetch(meta, dest_dir):
        return store.fetch(f"canvas:{meta['id']}", meta.get("display_name") or meta.get("filename"),
                           meta.get("size"), meta.get("updated_at") or meta.get("modified_at"),
                           meta["url"], dest_dir)

    assignments = cv.get_all(f"/courses/{cid}/assignments", order_by="due_at", **{"include[]": ["submission"]})
    subs = {}
    try:
        for s in cv.get_all(f"/courses/{cid}/students/submissions",
                            **{"student_ids[]": "self", "include[]": ["submission_comments"]}):
            subs[s["assignment_id"]] = s
    except urllib.error.HTTPError:
        pass

    items = []
    for a in assignments:
        sub = {**(a.get("submission") or {}), **subs.get(a["id"], {})}
        desc = a.get("description") or ""
        adir = folder / "Assignments" / safe_name(a["name"])
        files, local = [], {}
        for m in FILE_LINK.finditer(desc):
            fid = m.group(2)
            if fid in local:
                continue
            meta = file_meta(fid, m.group(1) or cid)
            rec = meta and fetch(meta, adir)
            if rec:
                files.append(rec)
                local[fid] = rec["path"]
        submitted = [r for att in sub.get("attachments") or [] if att.get("url") and (r := fetch(att, adir / "Submitted"))]
        if files or submitted or len(strip_tags(desc)) > 200:
            write_instructions(adir, a, desc, local)
        items.append({
            "id": f"canvas:{a['id']}",
            "name": a["name"],
            "due_at": a.get("due_at"),
            "points": a.get("points_possible"),
            "status": canvas_status(a, sub, now),
            "score": sub.get("score"),
            "grade": sub.get("grade"),
            "submitted_at": sub.get("submitted_at"),
            "late": bool(sub.get("late")),
            "platform": canvas_platform(a),
            "verifiable": not set(a.get("submission_types") or []) <= OFFLINE_TYPES,
            "url": a.get("html_url"),
            "folder": str(adir) if adir.exists() else None,
            "files": files,
            "submitted_files": submitted,
            "description_html": desc,
            "comments": [{"author": c.get("author_name"), "text": c.get("comment"), "at": c.get("created_at")}
                         for c in sub.get("submission_comments") or []],
        })

    materials = []
    try:
        modules = cv.get_all(f"/courses/{cid}/modules", **{"include[]": ["items"]})
    except urllib.error.HTTPError:
        modules = []
    for i, mod in enumerate(modules, 1):
        mod_items = mod.get("items")
        if mod_items is None:
            try:
                mod_items = cv.get_all(f"/courses/{cid}/modules/{mod['id']}/items")
            except urllib.error.HTTPError:
                mod_items = []
        mdir = folder / "Materials" / f"{i:02d} {safe_name(mod['name'], 80)}"
        entries = []
        for it in mod_items:
            if it["type"] == "File":
                meta = file_meta(str(it.get("content_id")), cid)
                rec = meta and fetch(meta, mdir)
                if rec:
                    entries.append({"type": "File", **rec})
            elif it["type"] in ("ExternalUrl", "Page", "Assignment", "Quiz", "Discussion", "ExternalTool"):
                entries.append({"type": it["type"], "name": it["title"],
                                "url": it.get("external_url") or it.get("html_url")})
        if entries:
            materials.append({"name": mod["name"], "items": entries})

    # Courses that expose their Files page get a full mirror, grouped by top-level folder.
    try:
        folders = {f["id"]: f["full_name"] for f in cv.get_all(f"/courses/{cid}/folders")}
        course_files = cv.get_all(f"/courses/{cid}/files")
    except urllib.error.HTTPError:
        course_files = []
    groups = {}
    for f in course_files:
        if f.get("locked_for_user") or f.get("hidden_for_user") or not f.get("url"):
            continue
        sub_path = folders.get(f.get("folder_id"), "").split("/", 1)[1:]  # drop the "course files" root
        parts = [safe_name(p, 80) for p in sub_path[0].split("/")] if sub_path else []
        rec = fetch(f, folder.joinpath("Files", *parts))
        if rec:
            groups.setdefault(parts[0] if parts else "Files", []).append({"type": "File", **rec})
    materials += [{"name": f"Files · {k}", "items": v} for k, v in sorted(groups.items())]

    return {
        "id": f"canvas:{cid}",
        "source": "canvas",
        "name": course["name"],
        "url": f"{cv.base}/courses/{cid}",
        "folder": str(folder) if folder.exists() else None,
        "assignments": items,
        "materials": materials,
    }


def sync_canvas(cv, cfg, store, errors, now):
    root = Path(cfg["school_root"]).expanduser()
    mapping = cfg.get("canvas_courses", {})
    try:
        courses = cv.get_all("/courses", enrollment_state="active")
    except Exception as e:
        hint = " (token expired or revoked? make a new one in Canvas settings)" if "401" in str(e) else ""
        errors.append(f"Canvas: couldn't list courses: {e}{hint}")
        return []
    out = []
    for course in courses:
        ccfg = mapping.get(str(course["id"]), {})
        if ccfg.get("skip") or "name" not in course:
            continue
        folder = root / (ccfg.get("folder") or f"Other/{safe_name(course['name'])}")
        try:
            c = sync_canvas_course(cv, course, folder, store, now)
            c["short"] = ccfg.get("short") or course.get("course_code") or course["name"]
            c["color"] = ccfg.get("color")
            out.append(c)
        except Exception as e:
            errors.append(f"Canvas {course['name']}: {e}")
        store.save()
    return out


# ---------- course websites (e.g. 15-122) ----------

def sync_web(cfg, store, errors, now, previous):
    root = Path(cfg["school_root"]).expanduser()
    out = []
    for wcfg in cfg.get("web_courses", []):
        try:
            module = __import__(f"{wcfg['type']}_source")
            course = module.sync(wcfg, root, store, now)
            course["web_type"] = wcfg["type"]
            out.append(course)
        except Exception as e:
            errors.append(f"{wcfg.get('short') or wcfg['type']}: {e}")
            # Keep showing the last good copy rather than dropping the course.
            old = next((c for c in previous["courses"] if c.get("web_type") == wcfg["type"]), None)
            if old:
                old["stale"] = True
                out.append(old)
        store.save()
    return out


# ---------- marks and tasks: cloud database if connected, else local files ----------

def load_user_state(name):
    """Marks/tasks from the shared database when connected (the phone can change them), else local."""
    path = MARKS if name == "marks" else TASKS
    try:
        import cloud
        db = cloud.connect()
        if db:
            data = db.get_all(name)
            save_json(path, data)
            return data
    except Exception:
        pass
    return load_json(path, {})


# ---------- your own tasks (the dashboard's + button) ----------

def add_tasks(courses, now):
    """Place tasks from state/tasks.json under the course you picked, or under "Personal"."""
    for c in courses:  # a stale course copied from the last run can still carry old task rows
        c["assignments"] = [a for a in c["assignments"] if not a.get("is_task")]
    courses[:] = [c for c in courses if c["id"] != "personal"]
    by_id = {c["id"]: c for c in courses}
    personal = {"id": "personal", "source": "personal", "name": "Personal tasks", "short": "Personal",
                "color": "#8e8e93", "url": None, "folder": None, "assignments": [], "materials": []}
    for t in load_user_state("tasks").values():
        due = parse_ts(t.get("due_at"))
        by_id.get(t.get("course_id"), personal)["assignments"].append({
            "id": t["id"], "name": t["name"], "due_at": t.get("due_at"), "all_day": bool(t.get("all_day")),
            "points": None, "status": "overdue" if due and due < now else "todo",
            "score": None, "grade": None, "submitted_at": None, "late": False,
            "platform": "My task", "verifiable": False, "url": None, "folder": None,
            "files": [], "submitted_files": [], "description_html": "", "comments": [],
            "notes": t.get("notes", ""), "is_task": True, "course_id": t.get("course_id") or "personal",
            "created_at": t.get("created_at", ""),
        })
    if personal["assignments"]:
        courses.append(personal)


# ---------- "mark as done" double-check ----------

def apply_marks(courses):
    """Compare dashboard marks (state/marks.json) with what Canvas/Gradescope report."""
    marks = load_user_state("marks")
    flagged = []
    for c in courses:
        for a in c["assignments"]:
            a.pop("marked_done", None)
            a.pop("mark_check", None)
            m = marks.get(a["id"])
            if not m:
                continue
            a["marked_done"] = m["marked_at"]
            if a["status"] in ("submitted", "graded", "excused"):
                a["mark_check"] = "confirmed"
            elif a.get("verifiable"):
                a["mark_check"] = "not_found"
                flagged.append((c, a))
            else:
                a["mark_check"] = "unverifiable"
    return flagged


# ---------- Gradescope (optional) ----------

def sync_gradescope(cfg, store, canvas_courses, errors, now):
    gs = cfg.get("gradescope") or {}
    if not (gs.get("email") and gs.get("password")):
        return []
    try:
        import gradescope_source
        return gradescope_source.sync(gs, Path(cfg["school_root"]).expanduser(), store, canvas_courses, now)
    except Exception as e:
        errors.append(f"Gradescope: {e}")
        return []


# ---------- change detection ----------

class SyncTimeout(BaseException):
    """Raised by the watchdog. BaseException so per-source handlers don't swallow it."""


def watchdog(seconds):
    def fire(signum, frame):
        raise SyncTimeout(f"sync timed out after {seconds // 60} min")

    signal.signal(signal.SIGALRM, fire)
    signal.alarm(seconds)


def load_previous():
    try:
        return json.loads(DATA_JS.read_text().split("=", 1)[1].strip().rstrip(";"))
    except (FileNotFoundError, IndexError, json.JSONDecodeError):
        return {"courses": []}


def detect_changes(courses, previous):
    """Due dates that moved and assignments that appeared since the last sync."""
    before = {c["id"]: {a["id"]: a for a in c["assignments"]} for c in previous.get("courses", [])}
    moved, added = [], []
    for c in courses:
        old = before.get(c["id"])
        if old is None or c.get("stale"):
            continue
        for a in c["assignments"]:
            if a.get("is_task"):
                continue  # you made it yourself; no need to announce it
            prev = old.get(a["id"])
            if prev is None:
                added.append((c, a))
                continue
            new_due, old_due = parse_ts(a.get("due_at")), parse_ts(prev.get("due_at"))
            if new_due and old_due and abs((new_due - old_due).total_seconds()) > 60:
                a["due_changed_from"] = prev["due_at"]
                moved.append((c, a))
    return moved, added


def fmt_when(a, iso):
    dt = parse_ts(iso)
    return dt.astimezone().strftime("%a %-m/%-d") if a.get("all_day") else fmt_local(dt)


# ---------- output ----------

def attention(courses, flagged, changes, store, errors, now):
    alerted = load_json(ALERTED, {})
    lines = []
    for c in courses:
        for a in c["assignments"]:
            due = parse_ts(a.get("due_at"))
            if not due:
                continue
            if a["status"] == "todo" and not a.get("marked_done") and due - now < timedelta(hours=36):
                state = "not submitted" if a.get("verifiable") else "not marked done"
                lines.append(f"⏰ {c['short']}: {a['name']} is due {fmt_local(due)} and {state}")
            elif (a["status"] in ("missing", "overdue") and not a.get("marked_done")
                  and a["id"] not in alerted and now - due < timedelta(days=21)):
                alerted[a["id"]] = now.isoformat()
                lines.append(f"❌ {c['short']}: {a['name']} is {a['status']} (was due {fmt_local(due)})")
    moved, added = changes
    finished = ("submitted", "graded", "excused", "expired")
    for c, a in moved:
        if a["status"] not in finished:
            lines.append(f"📅 {c['short']}: {a['name']} moved from {fmt_when(a, a['due_changed_from'])} "
                         f"to {fmt_when(a, a['due_at'])}")
    for c, a in added:
        due = parse_ts(a.get("due_at"))
        if due and due > now and a["status"] not in finished:
            lines.append(f"🆕 {c['short']}: new assignment {a['name']}, due {fmt_when(a, a['due_at'])}")
    for c, a in flagged:
        key = f"mark:{a['id']}:{a['marked_done']}"
        if key not in alerted:
            alerted[key] = now.isoformat()
            lines.append(f"🔎 {c['short']}: you marked {a['name']} done, but {a['platform']} shows no submission")
    save_json(ALERTED, alerted)
    lines += [f"⚠️ {e}" for e in errors]
    if lines and store.new:
        lines.append(f"📥 {len(store.new)} new file(s) saved to your class folders")
    return lines


def main():
    cfg = load_json(HUB / "config.json", None)
    if not cfg:
        sys.exit(f"Missing or invalid {HUB / 'config.json'}")
    STATE.mkdir(exist_ok=True)
    started = time.time()
    now = datetime.now(timezone.utc)

    cv = Canvas(cfg["canvas_base_url"], cfg["canvas_token"])
    store = FileStore(cv.download)
    errors = store.errors
    previous = load_previous()
    watchdog(int(os.environ.get("SCHOOLHUB_TIMEOUT", "900")))
    courses = []
    try:
        courses = sync_canvas(cv, cfg, store, errors, now)
        courses += sync_web(cfg, store, errors, now, previous)
        courses += sync_gradescope(cfg, store, courses, errors, now)
    except SyncTimeout as e:
        errors.append(f"{e}; keeping the last good copy of whatever it didn't reach")
        seen = {c["id"] for c in courses}
        for old in previous.get("courses", []):
            if old["id"] not in seen:
                old["stale"] = True
                courses.append(old)
    finally:
        signal.alarm(0)
    store.save()
    add_tasks(courses, now)
    flagged = apply_marks(courses)
    changes = detect_changes(courses, previous)

    data = {"generated_at": now.isoformat(), "errors": errors, "new_files": store.new, "courses": courses}
    tmp = HUB / "data.js.tmp"
    tmp.write_text("window.SCHOOL_DATA = " + json.dumps(data) + ";\n")
    tmp.replace(DATA_JS)

    site = cfg.get("site") or {}
    if site.get("auto_deploy"):
        try:
            import publish
            publish.build(cfg)
            url = publish.deploy(site)
            print(f"[schoolhub] published to {url}", file=sys.stderr)
        except Exception as e:
            errors.append(f"Publishing the phone view failed: {e}")

    lines = attention(courses, flagged, changes, store, errors, now)
    if lines:
        print("\n".join(lines))
    n = sum(len(c["assignments"]) for c in courses)
    print(f"[schoolhub] {len(courses)} courses, {n} assignments, {len(store.new)} new files, "
          f"{len(errors)} errors in {time.time() - started:.0f}s", file=sys.stderr)
    if "--open" in sys.argv:
        subprocess.run(["open", str(HUB / "dashboard.html")])


if __name__ == "__main__":
    main()
