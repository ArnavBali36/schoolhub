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
    """The get_all / put / remove contract of cloud.Turso and cloud.Cloud, in memory."""

    endpoint = "fake://shared"

    def __init__(self, marks=None, tasks=None, fail_puts=0, broken=()):
        self.data = {"marks": dict(marks or {}), "tasks": dict(tasks or {}), "plan": {}}
        self.fail_puts = fail_puts
        self.broken = set(broken)  # names whose every call fails, as the plan's before its table exists

    def check(self, name):
        if name in self.broken:
            raise RuntimeError(f"Turso refused a statement: SQLite error: no such table: school_{name}")

    def get_all(self, name):
        self.check(name)
        return json.loads(json.dumps(self.data[name]))

    def put(self, name, key, obj):
        self.check(name)
        if self.fail_puts:
            self.fail_puts -= 1
            raise OSError("the database did not answer")
        self.data[name][key] = obj

    def remove(self, name, key):
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
