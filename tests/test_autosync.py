"""Checks for the sync the server runs by itself (autosync.py, its loop in server.py, and what
sync.py leaves for it), standard library only.

    python3 -m unittest discover tests

Everything runs on a made-up clock in a throwaway folder: no test sleeps, none runs a real sync,
none reaches Canvas or any other server (the one socket opened is to this computer), and none reads
your config.json, state/ or data.js.
"""
import contextlib
import fcntl
import importlib.util
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
# server.py connects to the optional cloud database when it is imported; the tests never do.
sys.modules.setdefault("cloud", types.SimpleNamespace(connect=lambda: None, seed=lambda *a: None))

import autosync  # noqa: E402
import sync  # noqa: E402

# A copy of its own, so the other test files still import server.py with their own port.
_spec = importlib.util.spec_from_file_location("server_under_autosync_test", REPO / "server.py")
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)

T0 = 1_800_000_000  # a made-up "now", on a whole minute
HOUR = 3600
AWAKE = T0 - 10 * HOUR  # awake since long ago: settling plays no part


def stamp(t):
    return autosync.datetime.fromtimestamp(t, autosync.timezone.utc).isoformat()


def write_data(hub, began, complete=True, errors=(), legacy=False):
    """A data.js as sync.py writes it (legacy: as it wrote it before `complete` existed)."""
    data = {"generated_at": stamp(began), "complete": complete, "errors": list(errors), "new_files": [], "courses": []}
    if legacy:
        del data["complete"]
    (hub / "data.js").write_text("window.SCHOOL_DATA = " + json.dumps(data) + ";\n")


class RuleTest(unittest.TestCase):
    """next_sync: the whole rule, as a function of the clock and four remembered times."""

    def due(self, now, good_at, last_try=None, failures=0, awake_since=AWAKE):
        when, why = autosync.next_sync(now, good_at, last_try, failures, awake_since)
        return when <= now, when, why

    def test_due_once_the_last_good_sync_is_over_12_hours_old(self):
        for age in (0, HOUR, 11 * HOUR + 3599, 12 * HOUR - 1):
            with self.subTest(age=age):
                self.assertEqual(self.due(T0, T0 - age), (False, T0 - age + 12 * HOUR, "fresh"))
        for age in (12 * HOUR, 12 * HOUR + 1, 20 * HOUR, 72 * HOUR):
            with self.subTest(age=age):
                due, when, why = self.due(T0, T0 - age)
                self.assertTrue(due)
                self.assertEqual(why, "stale")
        self.assertEqual(autosync.SYNC_AFTER, 12 * HOUR)

    def test_at_any_hour_of_the_day(self):
        # The old rule looked only between 6 AM and 11 PM. This one is never told the time of day.
        for hour in range(24):
            with self.subTest(hour=hour):
                now = T0 + hour * HOUR
                self.assertTrue(self.due(now, now - 13 * HOUR)[0])
                self.assertFalse(self.due(now, now - 11 * HOUR)[0])

    def test_no_good_sync_on_record_is_due_now(self):
        self.assertEqual(self.due(T0, None), (True, T0, "stale"))

    def test_a_sync_dated_ahead_of_the_clock_is_not_believed(self):
        # Made while the clock was wrong: waiting 12 hours from a time that has not come would wait for ever.
        self.assertEqual(self.due(T0, T0 + 24 * HOUR), (True, T0, "stale"))
        # A few seconds ahead is only two clocks disagreeing.
        self.assertEqual(self.due(T0, T0 + 30), (False, T0 + 30 + 12 * HOUR, "fresh"))

    def test_just_awake_it_waits_for_the_mac_to_settle(self):
        self.assertEqual(autosync.SETTLE, 120)
        for awake_for in (0, 30, 119):
            with self.subTest(awake_for=awake_for):
                woke_at = T0 - awake_for
                self.assertEqual(self.due(T0, T0 - 13 * HOUR, awake_since=woke_at), (False, woke_at + 120, "settling"))
                self.assertEqual(self.due(T0, None, awake_since=woke_at), (False, woke_at + 120, "settling"))
        self.assertTrue(self.due(T0, T0 - 13 * HOUR, awake_since=T0 - 120)[0])
        # It never puts off a sync that is not due anyway.
        self.assertEqual(self.due(T0, T0 - HOUR, awake_since=T0), (False, T0 + 11 * HOUR, "fresh"))
        # A wake time ahead of the clock (the clock was set back) is not waited for.
        self.assertTrue(self.due(T0, None, awake_since=T0 + 24 * HOUR)[0])

    def test_the_wait_after_failures_grows_to_twelve_hours_and_no_further(self):
        # 5, 10, 20 and 40 minutes; three tries an hour apart; 3 and 6 hours; then the 12 hours
        # between good syncs. Never every hour for ever: each try is a whole sync, with its logins.
        self.assertEqual([autosync.retry_delay(n) for n in range(13)],
                         [0, 300, 600, 1200, 2400, 3600, 3600, 3600, 3 * HOUR, 6 * HOUR, 12 * HOUR, 12 * HOUR, 12 * HOUR])
        self.assertEqual(autosync.RETRY[-1], autosync.SYNC_AFTER)
        self.assertEqual(list(autosync.RETRY), sorted(autosync.RETRY))

    def test_after_a_failure_the_next_try_waits(self):
        for failures, wait in ((1, 300), (2, 600), (3, 1200), (4, 2400), (5, 3600), (8, 3 * HOUR), (40, 12 * HOUR)):
            with self.subTest(failures=failures):
                tried = T0 - 60
                self.assertEqual(self.due(T0, None, tried, failures), (False, tried + wait, "retry"))
                self.assertEqual(self.due(T0, T0 - 30 * HOUR, tried, failures), (False, tried + wait, "retry"))
                self.assertFalse(self.due(tried + wait - 1, None, tried, failures)[0])
                self.assertTrue(self.due(tried + wait, None, tried, failures)[0])

    def test_a_failure_never_brings_a_sync_forward(self):
        # Sync now failed three hours after a good sync: the next one by itself is still at 12 hours.
        self.assertEqual(self.due(T0, T0 - 3 * HOUR, T0 - 60, 1), (False, T0 + 9 * HOUR, "fresh"))

    def test_a_good_sync_after_the_failure_clears_it(self):
        # Run from Terminal, say: the server only sees the new data.js.
        self.assertEqual(self.due(T0, T0 - 50, T0 - 100, 5), (False, T0 - 50 + 12 * HOUR, "fresh"))
        later = T0 - 50 + 12 * HOUR
        self.assertTrue(self.due(later, T0 - 50, T0 - 100, 5)[0])

    def test_a_try_dated_ahead_of_the_clock_is_not_waited_for(self):
        self.assertTrue(self.due(T0, None, T0 + 24 * HOUR, 3)[0])

    def test_a_wait_longer_by_the_wall_clock_than_awake_was_a_sleep(self):
        self.assertEqual((autosync.TICK, autosync.WAKE_GAP), (60, 15))
        self.assertFalse(autosync.woke(60, 60))
        self.assertFalse(autosync.woke(68.2, 68.1))  # the wait ran late: both clocks say so
        self.assertFalse(autosync.woke(75, 60))
        self.assertTrue(autosync.woke(76, 60))
        self.assertTrue(autosync.woke(9 * HOUR + 60, 60))
        self.assertTrue(autosync.woke(60, 8))  # on time by the wall clock, asleep for most of it
        self.assertTrue(autosync.woke(-30, 60))  # the clock was set back
        auto = autosync.AutoSync(T0)
        auto.waited(T0 + 60, 60, 60)
        self.assertEqual(auto.awake_since, T0)
        auto.waited(T0 + 9 * HOUR, 9 * HOUR - 60, 60)
        self.assertEqual(auto.awake_since, T0 + 9 * HOUR)


class LastSyncTest(unittest.TestCase):
    """The last good sync is read from data.js itself."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.hub = Path(tmp.name)
        self.data = self.hub / "data.js"

    def test_the_time_is_the_one_inside_not_the_files_date(self):
        write_data(self.hub, T0 - 30 * HOUR)
        os.utime(self.data, (T0, T0))  # copied or restored just now
        self.assertEqual(autosync.last_sync(self.data), (T0 - 30 * HOUR, True, stamp(T0 - 30 * HOUR)))
        write_data(self.hub, T0 - HOUR)
        os.utime(self.data, (T0 - 90 * HOUR, T0 - 90 * HOUR))  # an old date on a new sync
        self.assertEqual(autosync.last_sync(self.data)[0], T0 - HOUR)

    def test_a_sync_that_could_not_read_everything_is_not_a_good_one(self):
        write_data(self.hub, T0, complete=False, errors=["Canvas: couldn't list courses: <urlopen error>"])
        self.assertEqual(autosync.last_sync(self.data), (T0, False, stamp(T0)))
        # A file that could not be saved is listed too, and the sync is still complete.
        write_data(self.hub, T0 + 1, complete=True, errors=["Skipped big.mov: 300 MB is over the size limit"])
        self.assertEqual(autosync.last_sync(self.data)[:2], (T0 + 1, True))

    def test_a_data_js_from_before_complete_existed(self):
        write_data(self.hub, T0, legacy=True)
        self.assertEqual(autosync.last_sync(self.data)[:2], (T0, True))
        write_data(self.hub, T0 + 1, legacy=True, errors=["Gradescope: login failed"])
        self.assertEqual(autosync.last_sync(self.data)[:2], (T0 + 1, False))

    def test_no_data_js_or_one_that_cannot_be_read(self):
        self.assertEqual(autosync.last_sync(self.data), (None, False, None))
        for text in ("", "window.SCHOOL_DATA = {", "window.SCHOOL_DATA = [];\n", 'window.SCHOOL_DATA = {"courses": []};\n',
                     'window.SCHOOL_DATA = {"generated_at": "yesterday"};\n', 'window.SCHOOL_DATA = {"generated_at": 5};\n'):
            with self.subTest(text=text):
                self.data.write_text(text)
                self.assertEqual(autosync.last_sync(self.data), (None, False, None))

    def test_a_new_data_js_is_seen_at_once(self):
        write_data(self.hub, T0)
        self.assertEqual(autosync.last_sync(self.data)[0], T0)
        self.assertEqual(autosync.last_sync(self.data)[0], T0)
        write_data(self.hub, T0 + 7 * HOUR, complete=False)
        self.assertEqual(autosync.last_sync(self.data)[:2], (T0 + 7 * HOUR, False))
        self.data.unlink()
        self.assertEqual(autosync.last_sync(self.data), (None, False, None))

    def test_a_sync_is_good_only_if_it_left_its_own_complete_data_js(self):
        auto = autosync.AutoSync(T0)
        good, old, partial = (T0 + 5, True, ""), (T0 - 30 * HOUR, True, ""), (T0 + 5, False, "")
        self.assertFalse(auto.finished(False, T0, T0 + 80, old))  # it crashed: the old file is still there
        self.assertFalse(auto.finished(True, T0, T0 + 80, partial))  # it ran, and could not read Canvas
        self.assertFalse(auto.finished(True, T0, T0 + 80, old))  # it says it ran, and wrote nothing
        self.assertFalse(auto.finished(True, T0, T0 + 80, (None, False, None)))
        self.assertEqual((auto.failures, auto.last_try), (4, T0 + 80))
        self.assertTrue(auto.finished(True, T0, T0 + 90, good))
        self.assertEqual((auto.failures, auto.last_try), (0, T0 + 90))


class ReachableTest(unittest.TestCase):
    def test_a_server_that_answers_and_one_that_does_not(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            port = s.getsockname()[1]
            self.assertTrue(autosync.reachable(f"http://127.0.0.1:{port}/x"))
        self.assertFalse(autosync.reachable(f"http://127.0.0.1:{port}"))  # closed now
        for url in (None, "", "not a url", "https://", 7):
            with self.subTest(url=url):
                self.assertFalse(autosync.reachable(url, timeout=0.2))


class Stop(Exception):
    pass


class LoopTest(unittest.TestCase):
    """server.py's loop, run on a made-up clock against a made-up sync."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.hub = Path(tmp.name).resolve() / "SchoolHub"
        (self.hub / "state").mkdir(parents=True)
        (self.hub / "config.json").write_text(json.dumps({"school_root": str(self.hub.parent),
                                                          "canvas_base_url": "https://canvas.invalid",
                                                          "canvas_token": "not-a-real-token"}))
        self.t = T0
        self.up = 500.0  # the clock that stops while the Mac sleeps
        self.dozing = False  # True: each wait ends on time by the wall clock, the Mac asleep for most of it
        self.starts = []  # when each sync began
        self.pending = []  # syncs begun and not yet ended
        self.hold = False  # True: a sync that does not end (the Mac slept in the middle of it)
        self.online = True
        self.asked = 0  # how often Canvas was asked for
        self.outcome = "good"  # what the next made-up sync does: "good", "incomplete" or "crash"
        self.naps = {}  # the Mac sleeps: {from when: for how many seconds}
        self.logged = []
        env = {k: v for k, v in os.environ.items() if k != "SCHOOLHUB_AUTOSYNC"}
        for target, name, value in (
                (server, "HUB", self.hub), (server, "AUTO", autosync.AutoSync(T0)),
                (server, "sync_state", {"running": False, "started_at": None, "finished_at": None, "ok": None, "output": ""}),
                (server, "in_background", self.begin), (server, "sync_py", self.sync_py),
                (server, "log", self.logged.append), (autosync, "reachable", self.reachable)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    # ---- the made-up world ----

    def clock(self):
        return self.t

    def reachable(self, url):
        self.assertEqual(url, "https://canvas.invalid")
        self.asked += 1
        return self.online

    def begin(self, fn):
        self.starts.append(self.t - T0)
        self.pending.append((fn, self.t))

    def sync_py(self):
        began = self.starts[-1] + T0 + 1
        if self.outcome == "crash":
            return False, "Traceback (most recent call last): ..."
        write_data(self.hub, began, complete=self.outcome == "good",
                   errors=[] if self.outcome == "good" else ["Canvas: couldn't list courses: <urlopen error>"])
        return True, "[schoolhub] 9 courses"

    def end_syncs(self):
        """Each sync begun takes 45 seconds, beside the loop's wait."""
        while self.pending and not self.hold:
            fn, began = self.pending.pop(0)
            times = iter((began, began + 45))
            fn(clock=lambda: next(times))

    def loop(self, until):
        """Runs the server's loop until T0 + `until` seconds on the made-up clock."""
        def sleep(seconds):
            if self.t + seconds > T0 + until:
                raise Stop
            self.end_syncs()
            self.t += seconds
            self.up += 8 if self.dozing else seconds
            for at in [at for at in self.naps if T0 + at <= self.t]:
                self.t += self.naps.pop(at)  # asleep: only the wall clock moves
        with self.assertRaises(Stop):
            server.auto_sync_loop(clock=self.clock, sleep=sleep, awake=lambda: self.up)

    def state(self):
        return server.sync_status(self.t)["auto"]

    @staticmethod
    def tries(first, waits):
        """When each try begins: the first look at or after the end of the wait that follows a 45-second failure."""
        out, t = [], first
        for wait in waits:
            out.append(t)
            t = -(-(t + 45 + wait) // 60) * 60
        return out

    # ---- the checks ----

    def test_shortly_after_the_server_starts(self):
        write_data(self.hub, T0 - 13 * HOUR)
        self.assertEqual(self.state()["state"], "settling")
        self.assertEqual(self.state()["next_at"], stamp(T0 + 120))
        self.loop(10 * 60)
        self.assertEqual(self.starts, [120])  # the second look; the first found the server only a minute old
        self.assertIn("syncing by itself: the last good sync was 13.0 hours ago", self.logged)
        self.assertEqual(self.state()["state"], "waiting")
        self.assertEqual(self.state()["last_good_at"], stamp(T0 + 121))

    def test_no_data_js_yet(self):
        self.loop(10 * 60)
        self.assertEqual(self.starts, [120])

    def test_every_12_hours_day_and_night(self):
        write_data(self.hub, T0 - 2 * HOUR)
        self.assertEqual(self.state(), {"on": True, "every_hours": 12, "state": "waiting", "failures": 0,
                                        "next_at": stamp(T0 + 10 * HOUR), "last_good_at": stamp(T0 - 2 * HOUR)})
        self.loop(60 * HOUR)
        # Twelve hours after the sync before, whatever the hour: five in two and a half days.
        self.assertEqual(self.starts, [10 * HOUR, 22 * HOUR + 60, 34 * HOUR + 120, 46 * HOUR + 180, 58 * HOUR + 240])
        self.assertEqual(self.asked, 5)  # Canvas is asked for only when a sync is about to start

    def test_never_two_at_once(self):
        write_data(self.hub, T0 - 13 * HOUR)
        self.hold = True  # the sync never ends
        self.loop(3 * HOUR)
        self.assertEqual(self.starts, [120])
        self.assertEqual(self.state()["state"], "running")
        self.assertIsNone(self.state()["next_at"])
        # Sync now while it runs starts nothing either.
        with server.SYNC_LOCK:
            self.assertFalse(server.start_sync(manual=True))
        self.assertEqual(len(self.pending), 1)

    def test_a_failing_sync_is_tried_again_with_a_growing_wait(self):
        write_data(self.hub, T0 - 13 * HOUR)
        self.outcome = "crash"
        self.loop(6 * HOUR)
        expected = self.tries(120, [300, 600, 1200, 2400, 3600, 3600, 3600, 3 * HOUR, 6 * HOUR])
        self.assertEqual(self.starts, [t for t in expected if t <= 6 * HOUR])
        self.assertEqual(expected[:6], [120, 480, 1140, 2400, 4860, 8520])  # 5, 10, 20 and 40 minutes, then an hour
        self.assertEqual(len(self.starts), 8)  # in six hours of failing: not one a minute
        status = self.state()
        self.assertEqual((status["state"], status["failures"]), ("retrying", 8))
        self.assertEqual(status["next_at"], stamp(T0 + self.starts[-1] + 45 + 3 * HOUR))  # and the waits go on growing
        self.assertIn("sync failed (1 in a row): the next try by itself is in 5 min at the earliest", self.logged)

    def test_a_source_that_fails_every_time_is_not_synced_every_hour_for_ever(self):
        # An expired Canvas token, a changed Gradescope password: every sync ends incomplete, for a
        # week. Ten tries on the first day, then the two a day of a good week (it was 24 a day).
        write_data(self.hub, T0 - 13 * HOUR)
        self.outcome = "incomplete"
        self.loop(7 * 24 * HOUR)
        day = 24 * HOUR
        self.assertEqual([sum(1 for s in self.starts if d * day <= s < (d + 1) * day) for d in range(7)], [10, 2, 2, 2, 2, 2, 2])
        status = self.state()
        self.assertEqual((status["state"], status["failures"]), ("retrying", 22))
        self.assertEqual(status["next_at"], stamp(T0 + self.starts[-1] + 45 + 12 * HOUR))
        # The first good sync ends it: the next is 12 hours after that one, and a failure then
        # starts at 5 minutes again.
        self.outcome = "good"
        self.loop(8 * day)
        self.assertEqual(self.state()["failures"], 0)
        self.assertEqual(self.state()["state"], "waiting")

    def test_a_sync_that_could_not_read_canvas_counts_as_a_failure(self):
        write_data(self.hub, T0 - 13 * HOUR)
        self.outcome = "incomplete"  # sync.py ran to the end, and its data.js says Canvas could not be read
        self.loop(15 * 60)
        self.assertEqual(self.starts, [120, 480])  # again after 5 minutes, not after 12 hours
        self.assertIsNone(self.state()["last_good_at"])
        self.assertIn("sync left something unread (1 in a row): the next try by itself is in 5 min at the earliest", self.logged)
        self.outcome = "good"
        self.loop(13 * HOUR)
        self.assertEqual(self.starts, [120, 480, 1140, 1140 + 12 * HOUR + 60])
        self.assertEqual(self.state()["failures"], 0)

    def test_a_good_sync_starts_the_count_again(self):
        write_data(self.hub, T0 - 13 * HOUR)
        self.outcome = "crash"
        self.loop(1200)
        self.assertEqual(self.starts, [120, 480, 1140])
        self.end_syncs()
        self.outcome = "good"
        self.loop(2400)
        self.assertEqual(self.starts, [120, 480, 1140, 2400])
        self.end_syncs()
        self.outcome = "crash"
        self.loop(2400 + 12 * HOUR + 600)
        # The failure 12 hours on is the first in a row again: 5 minutes, not 40.
        again = 2400 + 12 * HOUR + 60
        self.assertEqual(self.starts[4:], [again, again + 360])

    def test_sync_now_starts_the_count_again(self):
        write_data(self.hub, T0 - 13 * HOUR)
        self.outcome = "crash"
        self.loop(2460)
        self.assertEqual(self.starts, [120, 480, 1140, 2400])
        self.end_syncs()  # the fourth has failed: the next try by itself is 40 minutes away
        self.assertEqual((self.state()["state"], self.state()["failures"]), ("retrying", 4))
        with server.SYNC_LOCK:
            self.assertTrue(server.start_sync(manual=True))  # the button
        self.assertEqual(self.starts[-1], 2460)
        self.assertEqual(self.state()["failures"], 0)
        self.loop(2460 + 15 * 60)
        # It failed too: one failure in a row, so 5 minutes.
        self.assertEqual(self.starts[5:], [2460 + 360])

    def test_after_a_sleep_it_gives_the_mac_a_moment(self):
        write_data(self.hub, T0 - HOUR)  # due 11 hours from now
        self.naps[600] = 12 * HOUR  # the lid closes ten minutes in, for the night
        self.loop(14 * HOUR)
        woke = 600 + 12 * HOUR  # the look that finds the clock 12 hours on
        self.assertEqual(self.starts, [woke + 120])
        self.assertIn("syncing by itself: the last good sync was 13.2 hours ago", self.logged)

    def test_the_short_wakes_of_a_sleeping_mac_start_nothing(self):
        write_data(self.hub, T0 - 13 * HOUR)
        self.loop(60)  # one look, a minute after the start
        # Lid closed: awake a few seconds at a time, so each minute of waiting takes several by the clock.
        for i in range(600):
            self.naps[self.t - T0] = 130
            self.loop(self.t - T0 + 60 + 130)
        self.assertEqual(self.starts, [])
        self.assertEqual(self.asked, 0)
        self.assertEqual(self.state()["state"], "settling")
        # A longer wake (they run to two minutes) has gone too before a sync would start: awake at one
        # look and at the next, asleep again by the one after.
        for i in range(600):
            self.naps[self.t - T0] = 900
            self.loop(self.t - T0 + 60 + 900 + 60)
        self.assertEqual(self.starts, [])
        # However the waiting is counted: were it to end on time by the wall clock with the Mac asleep
        # for most of it, the other clock would show the sleep all the same.
        self.dozing = True
        self.loop(self.t - T0 + 10 * HOUR)
        self.dozing = False
        self.assertEqual((self.starts, self.asked), ([], 0))
        # Asleep till morning; then the lid opens and stays open.
        self.naps[self.t - T0] = 8 * HOUR
        opened = self.t - T0 + 60 + 8 * HOUR  # the look that finds the night gone
        self.loop(opened + 600)
        self.assertEqual(self.starts, [opened + 120])

    def test_a_sleep_while_canvas_is_asked_for_is_a_sleep_too(self):
        # A sync is due and the network slow: the lid closes while the look waits to hear whether
        # Canvas can be reached, and the answer comes a second into the next wake, eight hours on.
        # Nothing starts in that wake's first second: the Mac gets its two minutes again.
        write_data(self.hub, T0 - 13 * HOUR)
        naps = [8 * HOUR]

        def slow_network(url):
            if naps:
                self.t += naps.pop() + 1  # asleep with the question open; answered a second after waking
                self.up += 1
            return True
        with mock.patch.object(autosync, "reachable", slow_network):
            self.loop(120)  # the second look: due, and Canvas is asked for
            woke = 120 + 8 * HOUR
            self.assertEqual(self.starts, [])
            self.assertEqual(self.state()["state"], "settling")
            self.loop(9 * HOUR)
        self.assertEqual(len(self.starts), 1)
        self.assertGreaterEqual(self.starts[0] - woke, autosync.SETTLE)
        self.assertLessEqual(self.starts[0] - woke, autosync.SETTLE + 2 * autosync.TICK + 1)

    def test_a_sleep_anywhere_in_a_look_is_seen_at_the_next(self):
        # The two clocks are compared from one look to the next, not only across the wait between.
        write_data(self.hub, T0 - 13 * HOUR)
        real, naps = server.auto_tick, [3 * HOUR]

        def tick(now, *clocks):
            if naps:
                self.t += naps.pop()  # the Mac slept in the middle of this look
                return False
            return real(now, *clocks)
        with mock.patch.object(server, "auto_tick", tick):
            self.loop(4 * HOUR)
        # Seen at the look after it (at 3 h + 2 min), and the sync waits its two minutes from there.
        self.assertEqual(self.starts, [3 * HOUR + 120 + autosync.SETTLE])

    def test_offline_is_not_a_failure(self):
        write_data(self.hub, T0 - 13 * HOUR)
        self.online = False
        self.loop(3 * HOUR)
        self.assertEqual(self.starts, [])
        status = self.state()
        self.assertEqual((status["state"], status["next_at"], status["failures"]), ("offline", None, 0))
        self.assertEqual(self.logged, [])
        self.online = True
        self.loop(3 * HOUR + 60)
        self.assertEqual(self.starts, [3 * HOUR + 60])  # the very next look
        self.assertEqual(self.state()["state"], "running")

    def test_a_sync_run_from_terminal_counts(self):
        write_data(self.hub, T0 - 13 * HOUR)
        self.loop(60)
        write_data(self.hub, T0 + 70)  # python3 sync.py, by hand
        self.loop(12 * HOUR)
        self.assertEqual(self.starts, [])
        self.assertEqual((self.state()["state"], self.state()["next_at"]), ("waiting", stamp(T0 + 70 + 12 * HOUR)))
        self.loop(12 * HOUR + 10 * 60)
        self.assertEqual(self.starts, [12 * HOUR + 120])

    def test_a_restart_forgets_the_wait_but_not_the_last_good_sync(self):
        write_data(self.hub, T0 - 13 * HOUR)
        self.outcome = "crash"
        self.loop(2460)
        self.assertEqual(self.starts, [120, 480, 1140, 2400])
        self.end_syncs()
        self.assertEqual(self.state()["failures"], 4)  # 40 minutes to the next try
        restarted = self.t
        with mock.patch.object(server, "AUTO", autosync.AutoSync(restarted)):
            self.loop(restarted - T0 + 300)
            self.assertEqual(self.starts[4:], [restarted - T0 + 120])  # one early try
            self.end_syncs()
        # A fresh data.js is still fresh to a server that has only just started.
        write_data(self.hub, self.t - HOUR)
        with mock.patch.object(server, "AUTO", autosync.AutoSync(self.t)):
            before = len(self.starts)
            self.loop(self.t - T0 + HOUR)
            self.assertEqual(len(self.starts), before)
            self.assertEqual(server.sync_status(self.t)["auto"]["state"], "waiting")

    def test_never_by_itself_without_config_json_or_when_turned_off(self):
        write_data(self.hub, T0 - 13 * HOUR)
        with mock.patch.dict(os.environ, {"SCHOOLHUB_AUTOSYNC": "0"}):
            self.loop(HOUR)
            self.assertEqual(self.state(), {"on": False, "every_hours": 12, "state": "off", "next_at": None,
                                            "last_good_at": stamp(T0 - 13 * HOUR), "failures": 0})
        (self.hub / "config.json").rename(self.hub / "config.json.away")
        self.loop(2 * HOUR)
        self.assertEqual(self.state()["state"], "off")
        self.assertEqual((self.starts, self.asked), ([], 0))
        # Sync now still works when it is off.
        with mock.patch.dict(os.environ, {"SCHOOLHUB_AUTOSYNC": "0"}), server.SYNC_LOCK:
            self.assertTrue(server.start_sync(manual=True))

    def test_the_loop_outlives_a_look_that_fails(self):
        write_data(self.hub, T0 - 13 * HOUR)
        real, calls = server.auto_tick, []

        def tick(now, *clocks):
            calls.append(now)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return real(now, *clocks)
        with mock.patch.object(server, "auto_tick", tick):
            self.loop(5 * 60)
        self.assertEqual(self.logged[0], "looking whether a sync is due failed: boom")
        self.assertEqual(self.starts, [120])

    def test_what_the_page_is_told(self):
        write_data(self.hub, T0 - 2 * HOUR)
        status = server.sync_status(T0)
        # As before, for Sync now…
        self.assertEqual({k: status[k] for k in ("running", "started_at", "finished_at", "ok", "output")},
                         {"running": False, "started_at": None, "finished_at": None, "ok": None, "output": ""})
        # …and what is new: the time in the data.js on disk, and the next sync by itself.
        self.assertEqual(set(status), {"running", "started_at", "finished_at", "ok", "output", "data_at", "auto"})
        self.assertEqual(status["data_at"], stamp(T0 - 2 * HOUR))
        self.assertEqual(status["auto"]["next_at"], "2027-01-15T18:00:00+00:00")
        json.dumps(status)
        (self.hub / "data.js").unlink()
        self.assertIsNone(server.sync_status(T0)["data_at"])

    def test_sync_now_over_http(self):
        # Over HTTP the server reads the real clock: this one check is set at the real time.
        self.t = int(time.time())
        server.AUTO.awake_since = self.t - HOUR
        write_data(self.hub, self.t - HOUR)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)

        def ask(method):
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request(method, "/api/sync", body=b"{}" if method == "POST" else None,
                         headers={"Host": f"127.0.0.1:{port}", "X-SchoolHub": "1"})
            r = conn.getresponse()
            body = r.read()
            conn.close()
            return r.status, json.loads(body)
        with mock.patch.object(server, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"}):
            status, body = ask("GET")
            self.assertEqual((status, body["running"], body["auto"]["state"]), (200, False, "waiting"))
            status, body = ask("POST")
            self.assertEqual((status, body["running"], body["auto"]["state"]), (200, True, "running"))
            self.assertIsNotNone(body["started_at"])
            ask("POST")  # pressed again while it runs
            self.assertEqual(len(self.pending), 1)
            self.end_syncs()
            status, body = ask("GET")
            self.assertEqual((body["running"], body["ok"], body["auto"]["state"]), (False, True, "waiting"))
            self.assertEqual(body["data_at"], stamp(self.starts[-1] + T0 + 1))


class SyncPyTest(unittest.TestCase):
    """What sync.py leaves for the server: `complete` in data.js, and one sync at a time. Canvas is
    stood in for; nothing here reaches a network."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        hub = self.root / "SchoolHub"
        (hub / "state").mkdir(parents=True)
        self.hub = hub
        no_cloud = types.SimpleNamespace(connect=lambda: None, Turso=type("Turso", (), {}))
        patches = [mock.patch.dict(sys.modules, {"cloud": no_cloud}), mock.patch.object(sys, "argv", ["sync.py"])]
        for name, path in {"HUB": hub, "STATE": hub / "state", "MANIFEST": hub / "state" / "manifest.json",
                           "ALERTED": hub / "state" / "alerted.json", "MARKS": hub / "state" / "marks.json",
                           "TASKS": hub / "state" / "tasks.json", "DATA_JS": hub / "data.js"}.items():
            patches.append(mock.patch.object(sync, name, path))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        # Nothing sync.py writes may still point into the real SchoolHub folder.
        for name, value in vars(sync).items():
            if isinstance(value, Path):
                self.assertNotIn(REPO, [value, *value.parents], name)
        (hub / "config.json").write_text(json.dumps({"canvas_base_url": "https://canvas.invalid",
                                                     "canvas_token": "not-a-real-token", "school_root": str(self.root)}))

    def run_sync(self, canvas=None):
        out, err = io.StringIO(), io.StringIO()
        canvas = canvas or (lambda cv, cfg, store, errors, now, previous=None: [])
        with mock.patch.object(sync, "sync_canvas", canvas), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            sync.main()
        text = (self.hub / "data.js").read_text()
        return json.loads(text.split("=", 1)[1].strip().rstrip(";")), out.getvalue(), err.getvalue()

    def test_a_sync_that_read_everything_is_complete(self):
        data, out, err = self.run_sync()
        self.assertIs(data["complete"], True)
        self.assertEqual(data["errors"], [])
        self.assertEqual(autosync.last_sync(self.hub / "data.js")[1], True)

    def test_canvas_out_of_reach_is_incomplete(self):
        # The real sync_canvas, with a Canvas that cannot be reached.
        down = mock.patch.object(sync.Canvas, "get_all", side_effect=urllib.error.URLError("no route to host"))
        with down, contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            sync.main()
        began, complete, _ = autosync.last_sync(self.hub / "data.js")
        self.assertIs(complete, False)
        self.assertIsNotNone(began)
        self.assertIn("Canvas: couldn't list courses", out.getvalue())

    def test_a_course_or_a_source_that_fails_is_incomplete(self):
        def one_course_down(cv, cfg, store, errors, now, previous=None):
            errors.append("Canvas Calculus: HTTP Error 500")
            return []
        data, out, err = self.run_sync(one_course_down)
        self.assertIs(data["complete"], False)
        self.assertEqual(data["errors"], ["Canvas Calculus: HTTP Error 500"])
        self.assertIn("1 errors", err)

    def test_a_file_that_could_not_be_saved_leaves_it_complete(self):
        # Too big, or a link that answers 403: it would fail the same way at every sync.
        def one_file_skipped(cv, cfg, store, errors, now, previous=None):
            store.errors.append("Skipped lecture.mov: 300 MB is over the size limit")
            return []
        data, out, err = self.run_sync(one_file_skipped)
        self.assertIs(data["complete"], True)
        self.assertEqual(data["errors"], ["Skipped lecture.mov: 300 MB is over the size limit"])
        self.assertIn("⚠️ Skipped lecture.mov", out)
        self.assertIn("1 errors", err)

    # ---- what could not be read keeps its last good copy ----

    @staticmethod
    def a_course(cid, source="canvas", name=None, due="2026-12-01T05:00:00+00:00"):
        prefix = "canvas" if source == "canvas" else source
        return {"id": f"{prefix}:{cid}", "source": source, "name": name or f"Course {cid}", "short": f"C{cid}", "color": None, "url": None,
                "folder": None, "materials": [],
                "assignments": [{"id": f"{prefix}:{cid}:1", "name": "HW 1", "due_at": due, "points": 10, "status": "todo", "score": None,
                                 "grade": None, "submitted_at": None, "late": False, "platform": "Canvas", "verifiable": True, "url": None,
                                 "folder": None, "files": [], "submitted_files": [], "description_html": "", "comments": []}]}

    def last_data(self, courses, **more):
        data = {"generated_at": autosync.datetime.now(autosync.timezone.utc).isoformat(), "complete": True, "errors": [], "new_files": [],
                "courses": courses, **more}
        (self.hub / "data.js").write_text("window.SCHOOL_DATA = " + json.dumps(data) + ";\n")

    def real_sync(self, listed=None, broken=(), gradescope=None):
        """sync.py's own run with its own sync_canvas: Canvas lists `listed` (or cannot be reached
        when None), and reading a course in `broken` fails."""
        def get_all(cv, path, **params):
            if listed is None:
                raise urllib.error.HTTPError("https://canvas.invalid", 401, "Unauthorized", None, None)
            return [{"id": cid, "name": f"Course {cid}"} for cid in listed]

        def read(cv, course, folder, store, now):
            if course["id"] in broken:
                raise urllib.error.HTTPError("https://canvas.invalid", 500, "Internal Server Error", None, None)
            return self.a_course(course["id"], name=course["name"] + " (read now)")
        patches = [mock.patch.object(sync.Canvas, "get_all", get_all), mock.patch.object(sync, "sync_canvas_course", read)]
        if gradescope:
            cfg = json.loads((self.hub / "config.json").read_text())
            cfg["gradescope"] = {"email": "someone@example.edu", "password": "not-a-real-password"}
            (self.hub / "config.json").write_text(json.dumps(cfg))
            patches.append(mock.patch.dict(sys.modules, {"gradescope_source": types.SimpleNamespace(sync=gradescope)}))
        with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            for p in patches:
                stack.enter_context(p)
            sync.main()
        data = json.loads((self.hub / "data.js").read_text().split("=", 1)[1].strip().rstrip(";"))
        return data, {c["id"]: c for c in data["courses"]}

    def test_canvas_out_of_reach_keeps_the_last_good_copy_of_its_courses(self):
        # It used to write a data.js with no Canvas course at all, and that now reaches an open
        # page and the public site by itself, minutes after the lid opens.
        self.last_data([self.a_course(1), self.a_course(2), self.a_course(7, source="gradescope")])
        data, by_id = self.real_sync(listed=None)
        self.assertEqual(sorted(by_id), ["canvas:1", "canvas:2"])     # (no Gradescope login in this config: not a source)
        self.assertEqual([by_id["canvas:1"]["stale"], by_id["canvas:2"]["stale"]], [True, True])
        self.assertEqual(by_id["canvas:1"]["assignments"][0]["name"], "HW 1")
        # Still not a good sync: it is tried again soon, and the page says what is wrong.
        self.assertIs(data["complete"], False)
        self.assertIn("Canvas: couldn't list courses", data["errors"][0])
        self.assertEqual(autosync.last_sync(self.hub / "data.js")[1], False)
        # The retry that gets through shows them fresh again.
        data, by_id = self.real_sync(listed=[1, 2])
        self.assertEqual([data["complete"], by_id["canvas:1"].get("stale"), by_id["canvas:1"]["name"]], [True, None, "Course 1 (read now)"])

    def test_one_course_that_fails_keeps_its_last_good_copy(self):
        self.last_data([self.a_course(1), self.a_course(2), self.a_course(9)])
        data, by_id = self.real_sync(listed=[1, 2, 3], broken={2, 3})
        # Read now; kept from the last sync; never read before, so nothing to keep; and a course
        # Canvas no longer lists is gone, as before.
        self.assertEqual(sorted(by_id), ["canvas:1", "canvas:2"])
        self.assertEqual([by_id["canvas:1"].get("stale"), by_id["canvas:1"]["name"]], [None, "Course 1 (read now)"])
        self.assertEqual([by_id["canvas:2"].get("stale"), by_id["canvas:2"]["name"]], [True, "Course 2"])
        self.assertIs(data["complete"], False)
        self.assertEqual(len(data["errors"]), 2)

    def test_gradescope_failing_keeps_its_own_classes_and_never_shows_one_twice(self):
        def down(gs, root, store, canvas_courses, now):
            raise RuntimeError("login failed")
        self.last_data([self.a_course(1), self.a_course(7, source="gradescope")])
        data, by_id = self.real_sync(listed=[1], gradescope=down)
        self.assertEqual(sorted(by_id), ["canvas:1", "gradescope:7"])
        self.assertEqual([by_id["canvas:1"].get("stale"), by_id["gradescope:7"]["stale"]], [None, True])
        self.assertEqual([data["complete"], data["errors"]], [False, ["Gradescope: login failed"]])
        # Canvas out of reach while Gradescope answers: Gradescope is given the kept Canvas
        # courses to merge into, as on any day, so it makes no second copy of a class.
        given = []

        def up(gs, root, store, canvas_courses, now):
            given.append(sorted(c["id"] for c in canvas_courses))
            return []
        self.last_data([self.a_course(1), self.a_course(2)])
        data, by_id = self.real_sync(listed=None, gradescope=up)
        self.assertEqual(given, [["canvas:1", "canvas:2"]])
        self.assertEqual(sorted(by_id), ["canvas:1", "canvas:2"])

    # ---- what a sync noticed stays for a day ----

    def test_a_date_that_moved_stays_marked_for_a_day_not_until_the_next_sync(self):
        first, moved = "2026-12-01T05:00:00+00:00", "2026-12-03T05:00:00+00:00"
        due = {"at": first, "fail": False}

        def canvas(cv, cfg, store, errors, now, previous=None):
            if due["fail"]:
                errors.append("Canvas Other: HTTP Error 500")
            return [self.a_course(1, due=due["at"])]
        hw = lambda data: data["courses"][0]["assignments"][0]  # noqa: E731
        data, _, _ = self.run_sync(canvas)
        self.assertNotIn("due_changed_from", hw(data))
        # The sync that notices the move also leaves something unread, so it is tried again in 5 minutes.
        due.update(at=moved, fail=True)
        data, out, _ = self.run_sync(canvas)
        self.assertEqual([hw(data)["due_changed_from"], data["complete"]], [first, False])
        noticed = hw(data)["due_changed_at"]
        self.assertEqual(noticed, data["generated_at"])
        self.assertIn("📅 C1: HW 1 moved from", out)
        # The retry sees the same date as five minutes ago: the mark stays, and is not announced twice.
        due["fail"] = False
        data, out, _ = self.run_sync(canvas)
        self.assertEqual([hw(data)["due_changed_from"], hw(data)["due_changed_at"], data["complete"]], [first, noticed, True])
        self.assertNotIn("📅", out)
        # A day after it was noticed it goes (the file's times are set back, in place of waiting).
        old = (autosync.datetime.fromisoformat(noticed) - sync.timedelta(hours=25)).isoformat()
        data["generated_at"] = hw(data)["due_changed_at"] = old
        (self.hub / "data.js").write_text("window.SCHOOL_DATA = " + json.dumps(data) + ";\n")
        data, _, _ = self.run_sync(canvas)
        self.assertNotIn("due_changed_from", hw(data))
        self.assertNotIn("due_changed_at", hw(data))
        # A data.js from before the time was kept: noticed by the sync that wrote it.
        now = autosync.datetime.now(autosync.timezone.utc)
        course, before = self.a_course(1, due=moved), self.a_course(1, due=moved)
        before["assignments"][0]["due_changed_from"] = first
        sync.detect_changes([course], {"generated_at": (now - sync.timedelta(hours=2)).isoformat(), "courses": [before]}, now)
        self.assertEqual(course["assignments"][0]["due_changed_from"], first)
        course = self.a_course(1, due=moved)
        sync.detect_changes([course], {"generated_at": (now - sync.timedelta(hours=30)).isoformat(), "courses": [before]}, now)
        self.assertNotIn("due_changed_from", course["assignments"][0])

    def test_new_files_stay_counted_for_a_day(self):
        found = []

        def canvas(cv, cfg, store, errors, now, previous=None):
            store.new.extend(found)
            return []
        found[:] = ["/School/C1/a.pdf"]
        data, _, err = self.run_sync(canvas)
        self.assertEqual(data["new_files"], ["/School/C1/a.pdf"])
        since = data["new_files_since"]
        self.assertEqual(since, data["generated_at"])
        self.assertIn("1 new files", err)
        # The next sync, minutes or hours later, found one more: both are counted, the older first.
        found[:] = ["/School/C1/b.pdf"]
        data, _, err = self.run_sync(canvas)
        self.assertEqual([data["new_files"], data["new_files_since"]], [["/School/C1/a.pdf", "/School/C1/b.pdf"], since])
        self.assertIn("1 new files", err)          # the sync's own line says what this sync saved
        found[:] = []
        data, _, _ = self.run_sync(canvas)
        self.assertEqual(len(data["new_files"]), 2)
        # A day after the first of them was found, they go.
        data["new_files_since"] = (autosync.datetime.fromisoformat(since) - sync.timedelta(hours=25)).isoformat()
        (self.hub / "data.js").write_text("window.SCHOOL_DATA = " + json.dumps(data) + ";\n")
        data, _, _ = self.run_sync(canvas)
        self.assertEqual(data["new_files"], [])
        # A data.js from before, or one with nothing to tell the time by, is handled.
        now = autosync.datetime.now(autosync.timezone.utc)
        recent = (now - sync.timedelta(hours=3)).isoformat()
        self.assertEqual(sync.new_files(["b"], {"generated_at": recent, "new_files": ["a", "b"]}, now), (["a", "b"], recent))
        self.assertEqual(sync.new_files(["b"], {"new_files": ["a"]}, now), (["b"], now.isoformat()))
        self.assertEqual(sync.new_files([], {"generated_at": "not a time", "new_files": ["a"]}, now), ([], now.isoformat()))

    def test_one_sync_at_a_time(self):
        lock = self.hub / "state" / "sync.lock"
        with open(lock, "w") as other:  # another sync holds it
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(SystemExit) as stopped:
                self.run_sync()
            self.assertEqual(str(stopped.exception), "Another sync is already running; this one stops here.")
            self.assertFalse((self.hub / "data.js").exists())
        # It has ended: the next one runs, and each lets go when it is done.
        self.run_sync()
        self.run_sync()
        self.assertTrue((self.hub / "data.js").is_file())


class FakeProcess:
    """A process as server.py starts one: what it was started with, and what was done to it."""

    def __init__(self, argv, world, **options):
        self.argv, self.options, self.world = [str(a) for a in argv], options, world
        self.pid = 4242 + len(world.started)
        self.returncode = None
        self.done = []
        world.started.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.done.append("waited")
        return False

    def communicate(self, timeout=None):
        self.done.append(f"communicate {timeout}")
        if self.world.hangs:
            raise server.subprocess.TimeoutExpired(self.argv, timeout)
        self.returncode = self.world.exit
        return "[schoolhub] 9 courses\n", ""

    def kill(self):
        self.done.append("killed")

    def terminate(self):
        self.done.append("terminated")

    def wait(self, timeout=None):
        self.done.append("reaped")


class KeepAwakeTest(unittest.TestCase):
    """While the server runs a sync, the Mac is kept from idle sleep by macOS's own caffeinate, held
    beside the sync (never around it: the 30-minute limit must still stop sync.py itself). No
    process is started here."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tool = Path(tmp.name) / "caffeinate"
        self.tool.write_text("")
        self.started, self.hangs, self.exit = [], False, 0
        for name, value in (("Popen", lambda argv, **options: FakeProcess(argv, self, **options)),):
            p = mock.patch.object(server.subprocess, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(server, "CAFFEINATE", self.tool)
        p.start()
        self.addCleanup(p.stop)

    def test_the_sync_is_started_as_ever_and_caffeinate_waits_on_it(self):
        self.assertEqual(server.sync_py(), (True, "[schoolhub] 9 courses"))
        sync_process, keeper = self.started
        self.assertEqual(sync_process.argv, [sys.executable, str(server.HUB / "sync.py")])
        self.assertEqual(sync_process.done, ["communicate 1800", "waited"])
        # No idle sleep (-i) for as long as that process lives (-w), and nothing else.
        self.assertEqual(keeper.argv, [str(self.tool), "-i", "-w", str(sync_process.pid)])
        self.assertEqual(keeper.done, ["terminated", "reaped"])
        # The tool is macOS's own, by its full path (stood in for here by an empty file).
        self.assertIn('CAFFEINATE = Path("/usr/bin/caffeinate")', (REPO / "server.py").read_text())

    def test_without_caffeinate_the_sync_runs_all_the_same(self):
        self.tool.unlink()
        self.assertEqual(server.sync_py(), (True, "[schoolhub] 9 courses"))
        self.assertEqual(len(self.started), 1)
        # Or with one that cannot be started.
        self.tool.write_text("")
        real = server.subprocess.Popen

        def no_tool(argv, **options):
            if str(argv[0]) == str(self.tool):
                raise OSError("cannot run")
            return real(argv, **options)
        with mock.patch.object(server.subprocess, "Popen", no_tool):
            self.assertEqual(server.sync_py(), (True, "[schoolhub] 9 courses"))

    def test_a_sync_that_fails_or_runs_out_of_time(self):
        self.exit = 1
        self.assertEqual(server.sync_py(), (False, "[schoolhub] 9 courses"))
        # Thirty minutes: sync.py itself is stopped (not only what keeps the Mac awake), and
        # nothing is left running.
        self.started.clear()
        self.hangs = True
        ok, out = server.sync_py()
        self.assertFalse(ok)
        self.assertIn("timed out after 1800 seconds", out)
        sync_process, keeper = self.started
        self.assertEqual(sync_process.done, ["communicate 1800", "killed", "waited"])
        self.assertEqual(keeper.done, ["terminated", "reaped"])


if __name__ == "__main__":
    unittest.main()
