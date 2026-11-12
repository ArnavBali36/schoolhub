"""The day planner's store (docs/planner.md, section 1): the cleaning every saved value goes through,
the defaults, and what GET /api/plan answers.

QuantPrep's schoolPublic.ts does the same for the public site, and both are checked against
tests/plan_vectors.json, so a rule or a message changed here must change there too. Server code
only: server.py never serves this file.
"""
import re
from datetime import date, timedelta

# [0-9] rather than \d, which in Python also matches other scripts' digits; fullmatch rather than
# $, which in Python also matches before a final newline. Both would let through what JavaScript
# refuses.
KEY = re.compile(r"settings|week:(?:sun|mon|tue|wed|thu|fri|sat)|day:([0-9]{4})-([0-9]{2})-([0-9]{2})")
DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
ID = re.compile(r"[a-z0-9]{6,32}")
TIME = re.compile(r"([0-9]{2}):([0-9]{2})")
WEEKDAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
TYPES = {"deep": "Deep work", "social": "Socialize", "other": "Block"}
MEALS = {"breakfast": ("11:00", "12:00"), "lunch": ("16:00", "17:00"), "dinner": ("18:00", "19:00")}
MAX_BLOCKS, MAX_ITEMS, MAX_REPEATS = 40, 50, 100
MIN_MINUTES = 5   # one step of the clock: the page's drags make 15 or more, a typed time may be shorter
MAX_RANGE_DAYS = 62
AROUND_TODAY = 7


class Refused(ValueError):
    """A value that breaks a rule; its text is the reason the 400 gives."""


def default_settings():
    return {"day_start": 5, "day_end": 24}


def default_week():
    return {"meals": {name: {"start": start, "end": end, "place": "", "off": False}
                      for name, (start, end) in MEALS.items()},
            "blocks": []}


def _real_date(y, m, d):
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def _flag(v):
    """off, done and skip made true or false the same way in both servers (JavaScript's truthiness
    and Python's differ for lists and objects): true, a number other than 0, or a string other than
    "" is true; anything else is false."""
    if v is True:
        return True
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return v != 0
    return isinstance(v, str) and v != ""


def _hour(v, lo, hi, reason):
    # 5.0 is the integer 5 in JavaScript, so it is one here too; true is not a number in JSON.
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise Refused(reason)
    return v


def _minutes(v):
    """A time's minutes since midnight, or Refused."""
    m = TIME.fullmatch(v) if isinstance(v, str) else None
    if m:
        hours, minutes = int(m.group(1)), int(m.group(2))
        if (hours < 24 and minutes < 60 or hours == 24 and minutes == 0) and minutes % 5 == 0:
            return hours * 60 + minutes
    raise Refused("times are HH:MM from 00:00 to 24:00 in 5-minute steps")


def _times(src, out, required):
    """start and end from src into out. A block's are required; a date's change to a meal or to a
    repeating block may give either alone, the other coming from the week, so the order is checked
    only when both are given."""
    for field in ("start", "end"):
        if src.get(field) is not None:
            _minutes(src[field])
            out[field] = src[field]
        elif required:
            raise Refused("a block needs a start and an end")
    if "start" in out and "end" in out:
        length = _minutes(out["end"]) - _minutes(out["start"])
        if length <= 0:
            raise Refused("a block must end after it starts")
        if length < MIN_MINUTES:
            raise Refused(f"a block lasts at least {MIN_MINUTES} minutes")


def _text(src, field, limit):
    """A shown name: trimmed, then cut to limit characters. Left out or null is ""."""
    v = src.get(field)
    if v is None:
        return ""
    if not isinstance(v, str):
        raise Refused(f"{field} must be a string")
    return v.strip()[:limit]


def _kept(src, field, limit):
    """A copy kept as given (an item's ref and course): too long is refused, never cut, since a cut
    ref would point at nothing."""
    v = src.get(field)
    if v is None:
        return ""
    if not isinstance(v, str):
        raise Refused(f"{field} must be a string")
    if len(v) > limit:
        raise Refused(f"{field} is at most {limit} characters")
    return v


def _id(v, ids):
    if not isinstance(v, str) or not ID.fullmatch(v):
        raise Refused("bad id")
    if v in ids:
        raise Refused("ids must be unique")
    ids.add(v)
    return v


def _item(src, ids):
    if not isinstance(src, dict):
        raise Refused("an item must be an object")
    out = {"id": _id(src.get("id"), ids)}
    kind = src.get("kind")
    if not isinstance(kind, str) or kind not in ("work", "own"):
        raise Refused("kind must be work or own")
    out["kind"] = kind
    out["text"] = _text(src, "text", 200)
    if kind == "own":
        if not out["text"]:
            raise Refused("a to-do needs text")
    else:
        if src.get("ref") is None or src.get("ref") == "":
            raise Refused("a work item needs a ref")
        out["ref"] = _kept(src, "ref", 200)
        out["course"] = _kept(src, "course", 120)
    out["done"] = _flag(src.get("done"))
    return out


def _items(src, ids, out):
    """A block's or meal's items into out, when it has them."""
    v = src.get("items")
    if v is None:
        return
    if not isinstance(v, list):
        raise Refused("items must be a list")
    if len(v) > MAX_ITEMS:
        raise Refused("at most 50 items in a block or meal")
    out["items"] = [_item(x, ids) for x in v]


def _block(src, ids, dated):
    if not isinstance(src, dict):
        raise Refused("a block must be an object")
    out = {"id": _id(src.get("id"), ids)}
    kind = src.get("type")
    if not isinstance(kind, str) or kind not in TYPES:
        raise Refused("type must be deep, social or other")
    out["type"] = kind
    out["title"] = _text(src, "title", 120) or TYPES[kind]
    _times(src, out, required=True)
    # Items belong to a date, never to the week: a week's blocks drop theirs.
    if dated:
        _items(src, ids, out)
    return out


def _blocks(v, ids, dated):
    if v is None:
        return []
    if not isinstance(v, list):
        raise Refused("blocks must be a list")
    if len(v) > MAX_BLOCKS:
        raise Refused("at most 40 blocks")
    return [_block(x, ids, dated) for x in v]


def _meals_object(v):
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise Refused("meals must be an object")
    return v


def _week_meal(name, src):
    """A weekday's meal, every field there: one left out is the default's."""
    if src is None:
        src = {}
    if not isinstance(src, dict):
        raise Refused("a meal must be an object")
    start, end = MEALS[name]
    times = {"start": start if src.get("start") is None else src["start"],
             "end": end if src.get("end") is None else src["end"]}
    out = {}
    _times(times, out, required=True)
    out["place"] = _text(src, "place", 120)
    out["off"] = _flag(src.get("off"))
    return out


def _day_meal(src, ids):
    """A date's change to a meal: only the fields given, the rest coming from the week."""
    if not isinstance(src, dict):
        raise Refused("a meal must be an object")
    out = {}
    _times(src, out, required=False)
    if src.get("place") is not None:
        out["place"] = _text(src, "place", 120)
    if src.get("off") is not None:
        out["off"] = _flag(src["off"])
    _items(src, ids, out)
    return out


def _repeats(v, ids):
    if not isinstance(v, dict):
        raise Refused("repeats must be an object")
    if len(v) > MAX_REPEATS:
        raise Refused("at most 100 repeats")
    out = {}
    for block_id, src in v.items():
        # The id of a week's block, so not one of this value's own ids.
        if not isinstance(block_id, str) or not ID.fullmatch(block_id):
            raise Refused("bad id")
        if not isinstance(src, dict):
            raise Refused("a repeat must be an object")
        change = {}
        _times(src, change, required=False)
        if src.get("skip") is not None:
            change["skip"] = _flag(src["skip"])
        _items(src, ids, change)
        out[block_id] = change
    return out


def _settings(v):
    start = 5 if v.get("day_start") is None else v["day_start"]
    end = 24 if v.get("day_end") is None else v["day_end"]
    start = _hour(start, 0, 23, "day_start must be a whole hour from 0 to 23")
    end = _hour(end, 1, 24, "day_end must be a whole hour from 1 to 24")
    if end - start < 4:
        raise Refused("day_end must be at least 4 hours after day_start")
    return {"day_start": start, "day_end": end}


def _week(v):
    meals = _meals_object(v.get("meals"))
    out = {"meals": {name: _week_meal(name, meals.get(name)) for name in MEALS}}
    out["blocks"] = _blocks(v.get("blocks"), set(), dated=False)
    return out


def _day(v):
    """A date's value keeps only the fields it was given; a field it lacks means the week's."""
    ids, out = set(), {}
    if v.get("meals") is not None:
        meals = _meals_object(v["meals"])
        out["meals"] = {name: _day_meal(meals[name], ids) for name in MEALS if meals.get(name) is not None}
    if v.get("blocks") is not None:
        out["blocks"] = _blocks(v["blocks"], ids, dated=True)
    if v.get("repeats") is not None:
        out["repeats"] = _repeats(v["repeats"], ids)
    return out


def _check_key(key):
    m = KEY.fullmatch(key) if isinstance(key, str) else None
    if not m:
        raise Refused("bad key")
    if key.startswith("day:") and not _real_date(*m.groups()):
        raise Refused("bad key: not a real date")
    return key.split(":")[0]


def clean_plan(key, value):
    """A plan key and its value as the page sends it. Returns (cleaned, None), (None, None) for null
    (which deletes the key), or (None, reason) for a value that breaks a rule. Unknown fields are
    dropped; nothing else is changed except where docs/planner.md says so."""
    try:
        kind = _check_key(key)
        if value is None:
            return None, None
        if not isinstance(value, dict):
            raise Refused("the value must be an object")
        if kind == "settings":
            return _settings(value), None
        if kind == "week":
            return _week(value), None
        return _day(value), None
    except Refused as e:
        return None, str(e)


def plan_range(query, today):
    """The dates GET /api/plan answers for, from its query (parse_qs's dict, blank values kept):
    from and to inclusive, at most 62 days, or today ±7 without either. Refused for a bad range.

    A parameter given empty counts as given (and is bad), as URLSearchParams sees it."""
    given = [query[name][0] if name in query else None for name in ("from", "to")]
    if given == [None, None]:
        return today - timedelta(days=AROUND_TODAY), today + timedelta(days=AROUND_TODAY)
    if None in given:
        raise Refused("bad range: give both from and to")
    days = []
    for v in given:
        m = DATE.fullmatch(v)
        d = m and _real_date(*m.groups())
        if not d:
            raise Refused("bad range: from and to are YYYY-MM-DD dates")
        days.append(d)
    start, end = days
    if end < start:
        raise Refused("bad range: to is before from")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise Refused("bad range: at most 62 days")
    return start, end


def assemble(stored, start, end):
    """What GET /api/plan answers: the settings and all seven weekdays (as stored, or the defaults),
    and the stored dates from start to end. Everything is cleaned on the way out too, so a value
    saved before a rule changed never reaches the page broken; one that no longer passes is left out
    (a date) or shown as the defaults (the settings or a weekday)."""
    def stored_or(key, default):
        value, error = clean_plan(key, stored.get(key))
        return default if error or value is None else value

    days = {}
    for key in stored:
        m = KEY.fullmatch(key) if isinstance(key, str) and key.startswith("day:") else None
        d = m and _real_date(*m.groups())
        if d and start <= d <= end:
            value, error = clean_plan(key, stored[key])
            if not error and value is not None:
                days[d.isoformat()] = value
    return {"settings": stored_or("settings", default_settings()),
            "week": {wd: stored_or(f"week:{wd}", default_week()) for wd in WEEKDAYS},
            "days": dict(sorted(days.items()))}
