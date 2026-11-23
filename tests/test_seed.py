"""The first copy of this Mac's marks, tasks and plan into the shared database, standard library only.
Until every one has arrived, the server keeps serving its own files: a partial set read back from
the database would replace them (it did once, on 2026-10-07). No real database is contacted.
"""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
_spec = importlib.util.spec_from_file_location("cloud_under_test", REPO / "cloud.py")
cloud_real = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cloud_real)
# server.py connects to the optional cloud database when it is imported; the tests never do.
sys.modules.setdefault("cloud", types.SimpleNamespace(connect=lambda: None, seed=lambda *a: None))
# A copy of its own, so the other test files still import server.py with their own port.
_server_spec = importlib.util.spec_from_file_location("server_under_seed_test", REPO / "server.py")
server = importlib.util.module_from_spec(_server_spec)
_server_spec.loader.exec_module(server)


class FakeDb:
    """The get_all / put / remove / remove_many contract of cloud.Turso and cloud.Cloud, in memory."""

    endpoint = "fake://shared"

    def __init__(self, marks=None, tasks=None, fail_puts=0, broken=(), fail_removes=0, reads=None):
        self.data = {"marks": dict(marks or {}), "tasks": dict(tasks or {}), "plan": {}}
        self.fail_puts = fail_puts
        self.fail_removes = fail_removes  # this many removals of several keys fail
        self.reads = reads                # this many reads work, then they fail; None: all work
        self.broken = set(broken)  # names whose every call fails, as the plan's before its table exists
        self.calls = []            # what was asked, in order: ("get_all", name), ("put", key), ...

    def check(self, name):
        if name in self.broken:
            raise RuntimeError(f"Turso refused a statement: SQLite error: no such table: school_{name}")

    def get_all(self, name):
        self.check(name)
        self.calls.append(("get_all", name))
        if self.reads is not None:
            if self.reads == 0:
                raise OSError("the database did not answer")
            self.reads -= 1
        return json.loads(json.dumps(self.data[name]))

    def put(self, name, key, obj):
        self.check(name)
        self.calls.append(("put", key))
        if self.fail_puts:
            self.fail_puts -= 1
            raise OSError("the database did not answer")
        self.data[name][key] = obj

    def remove(self, name, key):
        self.calls.append(("remove", key))
        self.data[name].pop(key, None)

    def remove_many(self, name, keys):
        self.calls.append(("remove_many", tuple(keys)))
        if self.fail_removes:
            self.fail_removes -= 1
            raise OSError("the database did not answer")
        for key in keys:
            self.data[name].pop(key, None)


class SeedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        state = Path(self.tmp.name) / "state"
        state.mkdir()
        self.saved = {k: getattr(server, k) for k in ("CLOUD", "FILES", "SEEDED_FILE", "BACKUPS", "SEEDED", "cloud")}
        server.FILES = {name: state / f"{name}.json" for name in ("marks", "tasks", "plan")}
        server.SEEDED_FILE = state / "cloud-seeded.json"
        server.BACKUPS = state / "backups"
        server.SEEDED = {"marks": False, "tasks": False, "plan": False}
        server.cloud = types.SimpleNamespace(
            seed=lambda db, name, local: cloud_real.seed(db, name, local, pause=0),
            identity=cloud_real.identity,
        )
        self.local = {"a": {"name": "A"}, "b": {"name": "B"}, "c": {"name": "C"}}
        server.write_state(server.FILES["marks"], self.local)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(server, k, v)
        self.tmp.cleanup()

    def test_a_copy_that_keeps_failing_leaves_the_local_file_in_charge(self):
        server.CLOUD = FakeDb(marks={"a": {"name": "A"}}, fail_puts=100)
        self.assertFalse(server.ensure_seeded("marks"))
        self.assertEqual(server.load("marks"), self.local)  # not the database's one mark
        self.assertEqual(server.read_state(server.FILES["marks"]), self.local)
        self.assertFalse(server.SEEDED_FILE.exists())

    def test_a_short_failure_is_retried(self):
        server.CLOUD = FakeDb(fail_puts=1)
        self.assertTrue(server.ensure_seeded("marks"))
        self.assertEqual(server.CLOUD.data["marks"], self.local)

    def test_once_complete_the_database_is_read_and_the_copy_never_runs_again(self):
        server.CLOUD = FakeDb(marks={"a": {"name": "A, changed on the phone"}})
        self.assertTrue(server.ensure_seeded("marks"))
        self.assertEqual(server.CLOUD.data["marks"]["a"], {"name": "A, changed on the phone"})
        self.assertEqual(set(server.CLOUD.data["marks"]), {"a", "b", "c"})
        self.assertEqual(server.load("marks")["a"], {"name": "A, changed on the phone"})
        # The phone deletes b; a restart must not bring it back from the local file.
        server.CLOUD.remove("marks", "b")
        server.SEEDED = {"marks": False, "tasks": False, "plan": False}
        server.write_state(server.FILES["marks"], self.local)
        self.assertTrue(server.ensure_seeded("marks"))
        self.assertNotIn("b", server.CLOUD.data["marks"])

    def test_the_plan_is_copied_once_like_marks(self):
        local = {"week:sun": {"meals": {}, "blocks": []}, "settings": {"day_start": 6, "day_end": 23}}
        server.write_state(server.FILES["plan"], local)
        server.CLOUD = FakeDb()
        server.CLOUD.data["plan"]["settings"] = {"day_start": 7, "day_end": 22}  # changed on the website
        self.assertTrue(server.ensure_seeded("plan"))
        self.assertEqual(server.CLOUD.data["plan"], {**local, "settings": {"day_start": 7, "day_end": 22}})
        self.assertEqual(json.loads(server.SEEDED_FILE.read_text()), {"fake://shared": {"plan": True}})
        self.assertEqual(server.load("plan")["settings"], {"day_start": 7, "day_end": 22})
        # Deleted on the website; a restart must not bring it back.
        server.CLOUD.remove("plan", "week:sun")
        server.SEEDED = {"marks": False, "tasks": False, "plan": False}
        self.assertTrue(server.ensure_seeded("plan"))
        self.assertNotIn("week:sun", server.CLOUD.data["plan"])

    def test_a_plan_that_cannot_be_copied_never_holds_up_marks_and_tasks(self):
        # The database lacks the plan's table (QuantPrep's migration 0008 not yet run).
        server.write_state(server.FILES["plan"], {"settings": {"day_start": 6, "day_end": 23}})
        server.CLOUD = FakeDb(broken={"plan"})

        class Stop(Exception):
            pass

        def sleep(seconds):
            raise Stop  # one round of seed_loop, then out
        saved, server.time = server.time, types.SimpleNamespace(sleep=sleep)
        try:
            with self.assertRaises(Stop):
                server.seed_loop()
        finally:
            server.time = saved
        self.assertEqual(server.SEEDED, {"marks": True, "tasks": True, "plan": False})
        self.assertEqual(server.CLOUD.data["marks"], self.local)
        self.assertEqual(json.loads(server.SEEDED_FILE.read_text()), {"fake://shared": {"marks": True, "tasks": True}})
        # Until it is, the plan is read from the local file.
        self.assertEqual(server.load("plan"), {"settings": {"day_start": 6, "day_end": 23}})

    def test_a_shrinking_set_keeps_a_dated_copy_of_the_local_file(self):
        server.CLOUD = FakeDb(marks=self.local)
        self.assertTrue(server.ensure_seeded("marks"))
        server.CLOUD.remove("marks", "c")
        self.assertEqual(set(server.load("marks")), {"a", "b"})
        copies = list(server.BACKUPS.glob("marks-*.json"))
        self.assertEqual(len(copies), 1)
        self.assertEqual(json.loads(copies[0].read_text()), self.local)
        server.load("marks")  # nothing lost this time: no second copy
        self.assertEqual(len(list(server.BACKUPS.glob("marks-*.json"))), 1)


class FoldTest(unittest.TestCase):
    """Folding a daily task's old ✓ marks into its ledger (server.py tidy_daily), against a shared
    database that can stop answering part way. Whatever fails, no day the task was done is lost,
    and nothing is thrown: the ✓ that set the fold off is stored already."""

    TID = "task:fold00000002"
    TODAY = date(2026, 12, 20)
    OLD = ["2026-11-23", "2026-11-24", "2026-11-25"]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        state = Path(self.tmp.name) / "state"
        state.mkdir()
        self.saved = {k: getattr(server, k) for k in ("CLOUD", "FILES", "SEEDED_FILE", "BACKUPS", "SEEDED", "log")}
        server.FILES = {name: state / f"{name}.json" for name in ("marks", "tasks", "plan")}
        server.SEEDED_FILE = state / "cloud-seeded.json"
        server.BACKUPS = state / "backups"
        server.SEEDED = {"marks": True, "tasks": True, "plan": True}
        self.logged = []
        server.log = self.logged.append
        self.days = [*self.OLD, "2026-12-18"]
        self.marks = {f"{self.TID}@{d}": {"marked_at": d + "T20:00:00+00:00"} for d in self.days}
        self.marks["canvas:1"] = {"marked_at": "2026-12-01T10:00:00+00:00"}

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(server, k, v)
        self.tmp.cleanup()

    def use(self, db, local=None):
        server.CLOUD = db
        server.write_state(server.FILES["marks"], self.marks if local is None else local)
        return db

    def done_days(self, marks):
        """Every day the task was ticked, as the page reads it: the ledger's days and the marks'."""
        days = set(server.ledger_days(marks, self.TID))
        return sorted(days | {k.split("@")[1] for k in marks if server.DAILY_MARK.fullmatch(k)})

    def folded(self, marks):
        return {"canvas:1": self.marks["canvas:1"], f"{self.TID}@2026-12-18": self.marks[f"{self.TID}@2026-12-18"],
                self.TID + "@done": {**marks[self.TID + "@done"], "days": ["2026-11-23..2026-11-25"]}}

    def test_the_ledger_is_written_and_read_back_and_then_the_marks_go_in_one_request(self):
        db = self.use(FakeDb(marks=self.marks))
        server.tidy_daily(self.TODAY)
        self.assertEqual(db.data["marks"], self.folded(db.data["marks"]))
        self.assertEqual(self.done_days(db.data["marks"]), self.days)
        self.assertEqual([c[0] for c in db.calls], ["get_all", "put", "get_all", "remove_many"])
        self.assertEqual(db.calls[1], ("put", self.TID + "@done"))
        self.assertEqual(db.calls[3], ("remove_many", tuple(f"{self.TID}@{d}" for d in self.OLD)))
        # The local file is the database's again, and nothing was said.
        self.assertEqual(server.read_state(server.FILES["marks"]), db.data["marks"])
        self.assertEqual(self.logged, [])
        # Again: nothing is left to fold, and nothing is written.
        db.calls.clear()
        server.tidy_daily(self.TODAY)
        self.assertEqual(db.calls, [("get_all", "marks")])

    def test_marks_that_cannot_be_removed_stay_beside_the_ledger_until_the_next_fold(self):
        db = self.use(FakeDb(marks=self.marks, fail_removes=1))
        server.tidy_daily(self.TODAY)          # never raises
        left = db.data["marks"]
        # The three old days are in the ledger already, and all their marks are still there too.
        self.assertEqual(left[self.TID + "@done"]["days"], ["2026-11-23..2026-11-25"])
        self.assertEqual(sum(1 for k in left if server.DAILY_MARK.fullmatch(k)), 4)
        # A day in both is one day, and no day is lost.
        self.assertEqual(self.done_days(left), self.days)
        self.assertEqual(len(self.logged), 1)
        self.assertIn("they stay as they are", self.logged[0])
        # The next fold, once the database answers, finishes the job.
        server.tidy_daily(self.TODAY)
        self.assertEqual(db.data["marks"], self.folded(db.data["marks"]))
        self.assertEqual(self.done_days(db.data["marks"]), self.days)
        self.assertEqual(server.read_state(server.FILES["marks"]), db.data["marks"])

    def test_a_ledger_that_cannot_be_written_leaves_every_mark(self):
        db = self.use(FakeDb(marks=self.marks, fail_puts=1))
        server.tidy_daily(self.TODAY)
        self.assertEqual(db.data["marks"], self.marks)
        self.assertNotIn("remove_many", [c[0] for c in db.calls])

    def test_a_ledger_that_cannot_be_read_back_leaves_every_mark(self):
        db = self.use(FakeDb(marks=self.marks, reads=1))
        server.tidy_daily(self.TODAY)
        self.assertEqual([c[0] for c in db.calls], ["get_all", "put", "get_all"])
        self.assertEqual(self.done_days(db.data["marks"]), self.days)
        self.assertEqual(sum(1 for k in db.data["marks"] if server.DAILY_MARK.fullmatch(k)), 4)

    def test_only_the_marks_of_days_the_ledger_then_holds_are_removed(self):
        # The ledger read back lacks a day it was sent (another writer, a database gone wrong):
        # that day's mark stays.
        class Forgetful(FakeDb):
            def put(self, name, key, obj):
                super().put(name, key, {**obj, "days": ["2026-11-23", "2026-11-25"]} if key.endswith("@done") else obj)
        db = self.use(Forgetful(marks=self.marks))
        server.tidy_daily(self.TODAY)
        self.assertEqual(db.calls[-1], ("remove_many", (f"{self.TID}@2026-11-23", f"{self.TID}@2026-11-25")))
        self.assertIn(f"{self.TID}@2026-11-24", db.data["marks"])
        self.assertEqual(self.done_days(db.data["marks"]), self.days)

    def test_nothing_is_folded_from_the_local_copy(self):
        # The database does not answer: the local file has the old marks, but it may be behind the
        # database's ledger, so nothing is written from it.
        db = self.use(FakeDb(marks=self.marks, reads=0))
        server.tidy_daily(self.TODAY)
        self.assertEqual(db.calls, [("get_all", "marks")])
        self.assertEqual(db.data["marks"], self.marks)
        # Nor before the database holds everything this Mac had: it is not read at all then.
        db = self.use(FakeDb(marks=self.marks))
        server.SEEDED = {"marks": False, "tasks": True, "plan": True}
        server.tidy_daily(self.TODAY)
        self.assertEqual(db.calls, [])
        self.assertEqual(server.load("marks"), self.marks)      # served from the local file, as ever

    def test_the_ledger_joined_is_the_databases_not_the_local_copys(self):
        # The local file is behind: its ledger lacks days the database's has.
        there = {**self.marks, self.TID + "@done": {"marked_at": "x", "days": ["2026-10-01..2026-10-31", "2026-11-22"]}}
        here = {**self.marks, self.TID + "@done": {"marked_at": "x", "days": ["2026-10-01"]}}
        db = self.use(FakeDb(marks=there), local=here)
        server.tidy_daily(self.TODAY)
        self.assertEqual(db.data["marks"][self.TID + "@done"]["days"], ["2026-10-01..2026-10-31", "2026-11-22..2026-11-25"])
        self.assertEqual(server.read_state(server.FILES["marks"]), db.data["marks"])

    def test_with_no_shared_database_the_local_file_is_the_store(self):
        self.use(None)
        server.tidy_daily(self.TODAY)
        marks = server.load("marks")
        self.assertEqual(marks, self.folded(marks))
        self.assertEqual(self.done_days(marks), self.days)

    def test_whatever_the_marks_hold_nothing_is_thrown(self):
        odd = {**self.marks, self.TID + "@done": "no ledger", "task:fold00000003@2026-11-01": None, "x": 7}
        db = self.use(FakeDb(marks=odd), local=odd)
        server.tidy_daily(self.TODAY)
        self.assertEqual(self.done_days({k: v for k, v in db.data["marks"].items() if k.startswith(self.TID)}), self.days)

        class Broken(FakeDb):
            def get_all(self, name):
                return ["not", "a", "map"]
        self.use(Broken(marks=self.marks))
        server.tidy_daily(self.TODAY)
        self.assertEqual(len(self.logged), 1)

    def test_what_was_folded_is_not_a_loss_to_back_up_and_a_ledger_that_lost_days_is(self):
        # The local file still has the day marks, the database has them in the ledger (a fold
        # whose last step did not reach this file). Nothing is lost, so no dated copy is kept.
        there = {"canvas:1": self.marks["canvas:1"], self.TID + "@2026-12-18": self.marks[self.TID + "@2026-12-18"],
                 self.TID + "@done": {"marked_at": "2026-12-19T09:00:00+00:00", "days": ["2026-11-23..2026-11-25"]}}
        self.use(FakeDb(marks=there))
        self.assertEqual(server.load("marks"), there)
        copies = lambda: len(list(server.BACKUPS.glob("marks-*.json"))) if server.BACKUPS.exists() else 0
        self.assertEqual(copies(), 0)
        self.assertTrue(server.folded(self.TID + "@2026-11-24", there))
        self.assertFalse(server.folded(self.TID + "@2026-12-10", there))
        # A ✓ that vanished with its day in no ledger is a loss, as before.
        del server.CLOUD.data["marks"]["canvas:1"]
        server.load("marks")
        self.assertEqual(copies(), 1)
        # A ledger that holds fewer days there than here is one too, unless the days are marks there.
        for copy in server.BACKUPS.glob("marks-*.json"):   # (copies are named to the second)
            copy.unlink()
        server.CLOUD.data["marks"][self.TID + "@done"]["days"] = ["2026-11-23"]
        self.assertTrue(server.lost_days(self.TID + "@done", server.read_state(server.FILES["marks"]), server.CLOUD.data["marks"]))
        server.load("marks")
        self.assertEqual(copies(), 1)
        kept = json.loads(next(server.BACKUPS.glob("marks-*.json")).read_text())
        self.assertEqual(kept[self.TID + "@done"]["days"], ["2026-11-23..2026-11-25"])
        local = server.read_state(server.FILES["marks"])
        back = {**local, self.TID + "@2026-11-22": {"marked_at": "x"}}
        self.assertFalse(server.lost_days(self.TID + "@done", local, back))
        self.assertFalse(server.lost_days("canvas:1", {"canvas:1": {"days": ["2026-11-23"]}}, {}))
        self.assertFalse(server.lost_days(self.TID + "@done", {self.TID + "@done": {"days": ["2026-11-23"]}},
                                          {self.TID + "@2026-11-23": {"marked_at": "x"}}))
        self.assertTrue(server.lost_days(self.TID + "@done", {self.TID + "@done": {"days": ["2026-11-23"]}}, {}))


if __name__ == "__main__":
    unittest.main()


class PinnedTaskTest(unittest.TestCase):
    """A task is kept at the top (pinned) or goes in the list by its date, as chosen in its form."""

    def test_the_choice_is_kept_either_way(self):
        for pinned, due in [(True, "2026-11-10"), (False, None), (True, None), (False, "2026-11-10")]:
            task, error = server.clean_task({"name": "Read", "due_at": due, "pinned": pinned}, None)
            self.assertIsNone(error)
            self.assertIs(task["pinned"], pinned)

    def test_without_the_choice_an_undated_task_is_pinned_as_before(self):
        self.assertIs(server.clean_task({"name": "Read"}, None)[0]["pinned"], True)
        self.assertIs(server.clean_task({"name": "Read", "due_at": "2026-11-10"}, None)[0]["pinned"], False)
