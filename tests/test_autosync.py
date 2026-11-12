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

    def test_the_wait_after_failures_grows_to_an_hour_and_no_further(self):
        self.assertEqual([autosync.retry_delay(n) for n in range(9)],
                         [0, 300, 600, 1200, 2400, 3600, 3600, 3600, 3600])

    def test_after_a_failure_the_next_try_waits(self):
        for failures, wait in ((1, 300), (2, 600), (3, 1200), (4, 2400), (5, 3600), (40, 3600)):
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
        expected = self.tries(120, [300, 600, 1200, 2400] + [3600] * 8)
        self.assertEqual(self.starts, [t for t in expected if t <= 6 * HOUR])
        self.assertEqual(expected[:6], [120, 480, 1140, 2400, 4860, 8520])  # 5, 10, 20 and 40 minutes, then hourly
        self.assertEqual(len(self.starts), 9)  # in six hours of failing: not one a minute
        status = self.state()
        self.assertEqual((status["state"], status["failures"]), ("retrying", 9))
        self.assertEqual(status["next_at"], stamp(T0 + self.starts[-1] + 45 + 3600))
        self.assertIn("sync failed (1 in a row): the next try by itself is in 5 min at the earliest", self.logged)

    def test_a_sync_that_could_not_read_canvas_counts_as_a_failure(self):
        write_data(self.hub, T0 - 13 * HOUR)
        self.outcome = "incomplete"  # sync.py ran to the end and wrote a data.js without the Canvas courses
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

        def tick(now):
            calls.append(now)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return real(now)
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
        canvas = canvas or (lambda cv, cfg, store, errors, now: [])
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
        def one_course_down(cv, cfg, store, errors, now):
            errors.append("Canvas Calculus: HTTP Error 500")
            return []
        data, out, err = self.run_sync(one_course_down)
        self.assertIs(data["complete"], False)
        self.assertEqual(data["errors"], ["Canvas Calculus: HTTP Error 500"])
        self.assertIn("1 errors", err)

    def test_a_file_that_could_not_be_saved_leaves_it_complete(self):
        # Too big, or a link that answers 403: it would fail the same way at every sync.
        def one_file_skipped(cv, cfg, store, errors, now):
            store.errors.append("Skipped lecture.mov: 300 MB is over the size limit")
            return []
        data, out, err = self.run_sync(one_file_skipped)
        self.assertIs(data["complete"], True)
        self.assertEqual(data["errors"], ["Skipped lecture.mov: 300 MB is over the size limit"])
        self.assertIn("⚠️ Skipped lecture.mov", out)
        self.assertIn("1 errors", err)

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


if __name__ == "__main__":
    unittest.main()
