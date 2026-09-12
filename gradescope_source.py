"""Gradescope source for SchoolHub, via the unofficial `gradescopeapi` package.

Gradescope has no official API, so this logs in with your Gradescope email/password
and can break if Gradescope changes its site. It pulls status, due dates and grades;
student-side file downloads aren't supported by the package.

Courses that also exist on Canvas (matched by course number, e.g. 21-127, or by an
explicit "canvas" id in config) are merged into the Canvas course; others (like 15-122)
become their own course in the dashboard.
"""
import re
from datetime import timezone

from gradescopeapi.classes.connection import GSConnection

BASE = "https://www.gradescope.com"
CODE = re.compile(r"(\d{2})-?(\d{3})")


def _utc(dt):
    return dt.astimezone(timezone.utc) if dt else None


def _num(s):
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def _code(text):
    m = CODE.search(text or "")
    return f"{m.group(1)}-{m.group(2)}" if m else None


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _status(a, now):
    s = (a.submissions_status or "").lower()
    if _num(a.grade) is not None or "graded" in s:
        return "graded"
    if "submitted" in s and "no submission" not in s:
        return "submitted"
    deadline = _utc(a.late_due_date) or _utc(a.due_date)
    return "missing" if deadline and deadline < now else "todo"


def _record(cid, a, now):
    aid = a.assignment_id or _norm(a.name)
    due = _utc(a.due_date)
    return {
        "id": f"gradescope:{cid}:{aid}",
        "name": a.name,
        "due_at": due.isoformat() if due else None,
        "points": _num(a.max_grade),
        "status": _status(a, now),
        "score": _num(a.grade),
        "grade": None,
        "submitted_at": None,
        "late": False,
        "platform": "Gradescope",
        "verifiable": True,
        "url": f"{BASE}/courses/{cid}/assignments/{a.assignment_id}" if a.assignment_id else f"{BASE}/courses/{cid}",
        "folder": None,
        "files": [],
        "submitted_files": [],
        "description_html": "",
        "comments": [],
    }


def _merge(course, records):
    existing = {_norm(a["name"]): a for a in course["assignments"]}
    for r in records:
        a = existing.get(_norm(r["name"]))
        if a is None:
            # Skip undated in-class activities nobody has submitted to; they're just noise.
            if r["due_at"] or r["status"] != "todo":
                course["assignments"].append(r)
            continue
        if a["status"] in ("todo", "missing", "offline", "check") and r["status"] in ("submitted", "graded"):
            a["status"] = r["status"]
        if a.get("score") is None and r["score"] is not None:
            a["score"] = r["score"]
            a["points"] = a.get("points") or r["points"]
        a["gradescope_url"] = r["url"]
        a["verifiable"] = True


def _current_term(course, now):
    season = "fall" if now.month >= 8 else "spring" if now.month <= 5 else "summer"
    return str(course.year) == str(now.year) and season in (course.semester or "").lower()


def sync(gs_cfg, root, store, canvas_courses, now):
    conn = GSConnection()
    conn.login(gs_cfg["email"], gs_cfg["password"])
    mapping = gs_cfg.get("courses", {})
    by_canvas_id = {c["id"]: c for c in canvas_courses}
    by_code = {}
    for c in canvas_courses:
        code = _code(c.get("short")) or _code(c["name"])
        if code:
            by_code[code] = c

    out = []
    for cid, course in conn.account.get_courses().get("student", {}).items():
        ccfg = mapping.get(str(cid), {})
        if ccfg.get("skip") or not (ccfg or gs_cfg.get("all_terms") or _current_term(course, now)):
            continue
        code = _code(course.name) or _code(course.full_name)
        records = [_record(cid, a, now) for a in conn.account.get_assignments(cid) if "UNGRADED" not in a.name.upper()]
        target = by_canvas_id.get(f"canvas:{ccfg['canvas']}") if ccfg.get("canvas") else by_code.get(code)
        if target:
            _merge(target, records)
            continue
        folder = root / ccfg["folder"] if ccfg.get("folder") else next(
            (p for p in root.iterdir() if p.is_dir() and code and code in p.name), None)
        out.append({
            "id": f"gradescope:{cid}",
            "source": "gradescope",
            "name": course.full_name or course.name,
            "short": ccfg.get("short") or code or course.name,
            "url": f"{BASE}/courses/{cid}",
            "folder": str(folder) if folder and folder.exists() else None,
            "color": ccfg.get("color"),
            "assignments": records,
            "materials": [],
        })
    return out
