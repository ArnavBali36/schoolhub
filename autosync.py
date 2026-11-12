"""When SchoolHub's server syncs by itself.

A sync starts whenever the last good one is more than 12 hours old and the Mac is awake, at any
hour. server.py looks about once a minute (auto_sync_loop); this file holds what it decides with,
so the rule can be checked with a made-up clock: no test sleeps and none runs a sync.

The last good sync is read from data.js itself, not from the file's date and not from the server's
memory:

- sync.py writes data.js only when it runs to the end, in one move, with the time the sync began
  (`generated_at`) and whether it read every source (`complete`). A sync that crashed or was killed
  leaves the old file, so the old time still stands. One that could not reach Canvas does write a
  new file (without what it could not read), marked incomplete: that is not a good sync, and it is
  tried again soon rather than in 12 hours.
- The file's date says less: it changes when the file is copied or restored, and a failed sync
  changes it too.
- The server's memory is gone at every restart. All it keeps here is how many syncs failed in a row
  and when the last try was; forgetting those costs one early retry.

A Mac asleep with its lid closed still wakes many times an hour, for seconds at a time, to keep its
network alive (in a week of one MacBook's power log: 422 such wakes, 23 seconds on average, none over
121). A sync started in one of those would be frozen halfway, so a sync starts only once the Mac has
been awake for two minutes in one stretch (SETTLE), which also gives Wi-Fi time to come back after
the lid opens. Sleep is told from two clocks: the one on the
wall, and the one that stops while the Mac sleeps (time.monotonic).
"""
import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

SYNC_AFTER = 12 * 3600  # a sync starts by itself once the last good one is this old
TICK = 60  # the loop looks this often
WAKE_GAP = 15  # the two clocks this far apart over one wait: the Mac slept in it
SETTLE = 120  # awake (or the server running) this long in one stretch before a sync starts by itself
RETRY = (300, 600, 1200, 2400, 3600)  # the wait after 1, 2, 3, 4 and 5 or more failures in a row
FUTURE = 300  # a time further ahead than this comes from a clock that was wrong: not believed


def retry_delay(failures):
    """Seconds to wait after this many failed syncs in a row: 5 minutes, doubling, an hour at most."""
    return RETRY[min(failures, len(RETRY)) - 1] if failures > 0 else 0


def woke(wall, awake):
    """Whether the Mac slept during one wait of the loop, given how long the wait took by the clock
    on the wall and by the clock that stops while the Mac sleeps. A clock that was set, forward or
    back, counts too: every time kept here is the wall clock's, and none should be waited on that
    will not come."""
    return abs(wall - awake) > WAKE_GAP


def next_sync(now, good_at, last_try, failures, awake_since):
    """(when, why): the time from which a sync may start by itself, and what sets it. One is due
    when `when` <= now. All times are seconds since 1970, by the wall clock.

    good_at      when the last good sync began, or None (none yet, or the latest could not read
                 every source)
    last_try     when the last sync the server ran ended, or None
    failures     how many of those failed in a row
    awake_since  when the server started or the Mac last woke

    why is "fresh" (the last good sync is under 12 hours old), "retry" (waiting after a failure),
    "settling" (only just awake) or "stale" (nothing in the way)."""
    believed = good_at is not None and good_at <= now + FUTURE
    when = good_at + SYNC_AFTER if believed else now
    why = "fresh" if when > now else "stale"
    # A failure counts until a good sync comes after it (one run from Terminal, say).
    failed = failures > 0 and last_try is not None and last_try <= now + FUTURE
    if failed and not (believed and good_at >= last_try):
        retry = last_try + retry_delay(failures)
        if retry > max(when, now):
            when, why = retry, "retry"
    if when < awake_since + SETTLE and awake_since <= now + FUTURE:
        when = awake_since + SETTLE
        if when > now:
            why = "settling"
    return when, why


_read = {}  # path -> (the file's date and size, what last_sync read): parsed again only when it changes


def last_sync(data_js):
    """(began, complete, generated_at) for the data.js at this path: when the sync that wrote it
    began (seconds since 1970), whether it read every source, and the time as the file gives it.
    (None, False, None) when there is no data.js or it cannot be read.

    A data.js from before `complete` existed counts as complete when it lists no errors."""
    path = str(data_js)
    try:
        st = os.stat(path)
        key = (st.st_mtime_ns, st.st_size)
        if path in _read and _read[path][0] == key:
            return _read[path][1]
        data = json.loads(Path(path).read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";"))
        stamp = data["generated_at"]
        began = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        complete = data["complete"] is True if "complete" in data else not data.get("errors")
        result = (began, complete, stamp)
    except OSError:
        return None, False, None  # no file (yet): asked again at the next look
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        result = (None, False, None)
    _read[path] = (key, result)
    return result


def reachable(url, timeout=5):
    """Whether a connection to this address's server can be opened. False without a network, which
    is the usual state just after the lid opens: a sync started then would only fail."""
    try:
        parts = urlsplit(url)
        if not parts.hostname or not isinstance(parts.hostname, str):
            return False
        port = parts.port or (80 if parts.scheme == "http" else 443)
        with socket.create_connection((parts.hostname, port), timeout=timeout):
            return True
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def iso(t):
    return None if t is None else datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


class AutoSync:
    """What the server remembers between looks, and what it says about the next sync. `synced` is
    always what last_sync reads from data.js at that moment: nothing about the last good sync is
    kept here."""

    def __init__(self, now):
        self.awake_since = now  # the server started, or the Mac woke
        self.failures = 0
        self.last_try = None
        self.offline = False  # the last look found a sync due and no way to Canvas

    def waited(self, now, wall, awake):
        """After each wait of the loop (it took `wall` seconds by the clock, `awake` of them awake):
        if the Mac slept in it, the two minutes of settling start again."""
        if woke(wall, awake):
            self.awake_since = now

    def plan(self, now, synced):
        began, complete, _ = synced
        return next_sync(now, began if complete else None, self.last_try, self.failures, self.awake_since)

    def due(self, now, synced):
        return self.plan(now, synced)[0] <= now

    def manual(self):
        """Sync now was pressed: the count of failures starts again."""
        self.failures, self.last_try, self.offline = 0, None, False

    def finished(self, ok, started, now, synced):
        """A sync the server ran has ended. `ok` is sync.py's own word (it ran to the end). It was a
        good one only if the data.js it left is its own (made since `started`) and read every
        source; anything else counts as a failure, and the next try waits longer."""
        began, complete, _ = synced
        good = bool(ok and complete and began is not None and began >= started - 60)
        self.failures = 0 if good else self.failures + 1
        self.last_try = now
        return good

    def status(self, now, synced, running=False, on=True):
        """For GET /api/sync: what a page needs to say when the next sync will happen.

        state         "waiting" (next_at is 12 hours after the last good sync), "retrying" (next_at
                      is the next try after a failure), "settling" (just awake: next_at is a minute
                      or two away), "due" (at the next look), "offline" (due, waiting for the
                      network), "running" or "off"
        next_at       when the next sync may start by itself, or null (running, offline, off)
        last_good_at  when the last good sync began, or null (none yet, or the latest one could
                      not read every source)"""
        began, complete, _ = synced
        when, why = self.plan(now, synced)
        if not on:
            state, at = "off", None
        elif running:
            state, at = "running", None
        elif when > now:
            state, at = {"fresh": "waiting", "retry": "retrying", "settling": "settling"}[why], when
        elif self.offline:
            state, at = "offline", None
        else:
            state, at = "due", now
        return {"on": on, "every_hours": SYNC_AFTER // 3600, "state": state, "next_at": iso(at),
                "last_good_at": iso(began if complete else None), "failures": self.failures}
