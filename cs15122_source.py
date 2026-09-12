"""15-122 course-website source for SchoolHub.

15-122 lives on its own site (www.cs.cmu.edu/~15122), not Canvas. Its handouts page builds
everything from JavaScript calls like release_pr("2026-09-03T18:00:00-04:00", 8, "pr02",
"PR 02") plus a schedule block of C.addHw(...) lines, so this parses those directly:

- Assignments: written homework (PR, handed in on Gradescope) and programming homework
  (PG, Autolab) with real due dates; checkins and the final as in-person items.
- Files: public lecture notes, review slides, lecture code, guides and practice exams are
  downloaded into the class folder. Homework writeups are behind the Autolab login, so
  they're linked instead, and any copy you saved yourself (e.g. pr02.pdf) gets attached.

SchoolHub can't see 15-122 submissions, so past-due items show as "Check" until you mark
them done (or until Gradescope is configured and its statuses merge in).
"""
import re
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
PLATFORM = {"PR": "Gradescope", "PG": "Autolab"}
RELEASE = re.compile(r'release_(pr|ep|pg|rc|ch)\("([^"]+)",\s*(?:\d+,\s*)?"([^"]+)",\s*"([^"]+)"')


def _get(url, method="GET"):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "SchoolHub/1.0"})
    return urllib.request.urlopen(req, timeout=60)


def _download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    with _get(url) as resp, open(part, "wb") as f:
        while chunk := resp.read(1 << 16):
            f.write(chunk)
    part.replace(dest)


def _fetch_public(store, base, rel, dest_dir):
    """Download a handout if it's published; a 404 just means it isn't out yet."""
    url = f"{base}/{rel}"
    try:
        with _get(url, "HEAD") as resp:
            size = int(resp.headers.get("Content-Length") or 0)
            version = resp.headers.get("Last-Modified") or str(size)
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return None
        raise
    rec = store.fetch(f"cs15122:{rel}", Path(rel).name, size, version, url, dest_dir, download=_download)
    return {"type": "File", **rec} if rec else None


def _clock(s):
    m = re.match(r"(\d{1,2})(?::(\d\d))?\s*(am|pm)", s.strip().lower())
    if not m:
        return time(23, 59)
    return time(int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0), int(m.group(2) or 0))


def _first(pattern, text, default=""):
    m = re.search(pattern, text)
    return m.group(1) if m else default


def _item(aid, name, due, points, status, platform, url, **extra):
    return {"id": aid, "name": name, "due_at": due.isoformat(), "points": points, "status": status,
            "score": None, "grade": None, "submitted_at": None, "late": False, "platform": platform,
            "verifiable": False, "url": url, "folder": None, "files": [], "submitted_files": [],
            "description_html": "", "comments": [], **extra}


def sync(wcfg, root, store, now):
    base = wcfg.get("url", "https://www.cs.cmu.edu/~15122").rstrip("/")
    with _get(f"{base}/handouts.shtml") as resp:
        page = resp.read().decode("utf-8", "replace")
    # Drop HTML comments and //-commented lines: the page keeps old semesters' entries in them.
    src = "\n".join(ln for ln in re.sub(r"(?s)<!--.*?-->", "", page).splitlines()
                    if not ln.lstrip().startswith("//"))
    folder = root / wcfg.get("folder", "15-122")
    title = _first(r"<title>\s*(?:CS\s*)?15-122:\s*([^(<]+)", page, "Principles of Imperative Computation").strip()
    autolab = _first(r'autolab\s*=\s*"([^"]+)"', src)
    gradescope = _first(r'gradescope\s*=\s*"([^"]+)"', src)
    handouts = f"{base}/handouts.shtml"

    # ---- homework: each C.addHw(kind, due, pts, _, release_offset_days) pairs with the
    # release_pr/release_pg call published on due + offset.
    due_time = {k: _clock(t) for k, t in re.findall(r"C\.newHw\('(\w+)',\s*'[^']*',\s*'[^']*',\s*'([^']*)'", src)}
    releases = {}
    for kind, when, rid, name in RELEASE.findall(src):
        if kind in ("pr", "pg") and "UNGRADED" not in name:
            releases[(kind.upper(), datetime.fromisoformat(when).astimezone(TZ).date())] = (rid, name)
    dues = {}
    for kind, y, m, d, pts, offset in re.findall(
            r"C\.addHw\('(PR|PG)',\s*(\d{4}),\s*(\d{1,2}),\s*(\d{1,2}),\s*'\s*(\d+)pt',\s*'[^']*',\s*(-?\d+)", src):
        due_day = date(int(y), int(m), int(d))
        dues.setdefault((kind, due_day + timedelta(days=int(offset))), []).append((due_day, int(pts)))

    # If the page's structure changes, fail loudly instead of quietly showing an empty course.
    matched = sum(1 for key in dues if key in releases)
    if not dues or matched < len(dues) / 2:
        raise RuntimeError(f"the handouts page changed format ({len(dues)} due dates found, {matched} matched to "
                           "a handout). Showing the last good copy; cs15122_source.py needs an update")

    assignments = []
    for (kind, released), parts in dues.items():
        rid, name = releases.get((kind, released), (None, None))
        if not rid:
            rid = f"{kind.lower()}-{min(parts)[0]:%m%d}"
            name = f"{'Written' if kind == 'PR' else 'Programming'} homework"
        for n, (due_day, pts) in enumerate(sorted(parts), 1):
            due = datetime.combine(due_day, due_time.get(kind, time(23, 59)), TZ)
            local = folder / rid
            assignments.append(_item(
                f"cs15122:{rid}" + (f":{n}" if len(parts) > 1 else ""),
                f"{name} (part {n})" if len(parts) > 1 else name,
                due, pts, "todo" if due > now else "check", PLATFORM[kind],
                f"{autolab}/assessments/{rid}/writeup" if autolab and releases.get((kind, released)) else handouts,
                gradescope_url=gradescope if kind == "PR" and gradescope else None,
                folder=str(local) if local.is_dir() else None,
                files=[{"name": p.name, "path": str(p), "size": p.stat().st_size}
                       for p in sorted(folder.glob(f"{rid}*.pdf"))] if folder.exists() else [],
            ))

    # ---- in-person assessments (no submission to track)
    for i, (y, m, d) in enumerate(re.findall(r"C\.addExam\('CH',\s*(\d{4}),\s*(\d{1,2}),\s*(\d{1,2})", src), 1):
        day = datetime.combine(date(int(y), int(m), int(d)), time(12), TZ)
        assignments.append(_item(f"cs15122:checkin{i:02d}", f"CH {i:02d}", day, 60, "offline", "In person",
                                 handouts, all_day=True))
    final = re.search(r"C\.setFinal\((\d{4}),\s*(\d{1,2}),\s*(\d{1,2})", src)
    if final:
        day = datetime.combine(date(*map(int, final.groups())), time(12), TZ)
        assignments.append(_item("cs15122:final", "Final Exam", day, 250, "offline", "In person", handouts, all_day=True))
    assignments.sort(key=lambda a: a["due_at"])

    # ---- public handouts -> class folder
    mdir = folder / "Materials"
    lectures = re.findall(r'release_(?:lec|ext)\("([^"]+)",\s*"[^"]+"', src)
    extra_slides = re.findall(r'release_ext\("[^"]+",\s*"[^"]+",\s*"([^"]+)"', src)
    guides = re.findall(r'release_gts\("([^"]+)"', src)
    exams = re.findall(r'release_exam\([^,]+,\s*"([^"]+)"', src)
    misc = re.findall(r'release_misc\([^,]+,\s*-?\d+,\s*"([^"]+)"', src)
    groups = [
        ("Lecture notes", [_fetch_public(store, base, f"handouts/lectures/{i}.pdf", mdir / "Lecture Notes") for i in lectures]),
        ("Review slides", [_fetch_public(store, base, f"handouts/slides/review/{i}.pdf", mdir / "Slides")
                           for i in lectures + extra_slides]),
        ("Lecture code", [_fetch_public(store, base, f"handouts/code/{i}.tgz", mdir / "Code") for i in lectures]),
        ("Guides to success", [_fetch_public(store, base, f"handouts/gts/{i}.pdf", mdir / "Guides") for i in guides]),
        ("Practice exams", [_fetch_public(store, base, f"handouts/exams/{i}{s}.pdf", mdir / "Practice Exams")
                            for i in exams for s in ("", "-sol")]),
        ("Misc", [_fetch_public(store, base, f, mdir) for f in misc]),
    ]
    prefix = {"pr": "", "ep": "", "ch": "", "pg": "Programming: ", "rc": "Recitation: "}
    groups.append(("Writeups (Autolab login)", [
        {"type": "Autolab", "name": prefix[kind] + name, "url": f"{autolab}/assessments/{rid}/writeup"}
        for kind, when, rid, name in RELEASE.findall(src)
        if autolab and datetime.fromisoformat(when) <= now]))
    groups.append(("Resources", [{"type": "Link", "name": re.sub(r"<[^>]+>", "", name), "url": url}
                                 for url, name in re.findall(r'release_resource\("([^"]+)",\s*"([^"]+)"', src)]))
    materials = [{"name": title_, "items": [i for i in items if i]} for title_, items in groups if any(items)]

    return {
        "id": "web:15122",
        "source": "web",
        "name": title,
        "short": wcfg.get("short", "15-122"),
        "url": handouts,
        "folder": str(folder) if folder.exists() else None,
        "color": wcfg.get("color"),
        "assignments": assignments,
        "materials": materials,
    }
