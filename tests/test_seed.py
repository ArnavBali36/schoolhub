"""The first copy of this Mac's marks and tasks into the shared database, standard library only.
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

    def __init__(self, marks=None, tasks=None, fail_puts=0):
        self.data = {"marks": dict(marks or {}), "tasks": dict(tasks or {})}
        self.fail_puts = fail_puts

    def get_all(self, name):
        return json.loads(json.dumps(self.data[name]))

    def put(self, name, key, obj):
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
        server.FILES = {"marks": state / "marks.json", "tasks": state / "tasks.json"}
        server.SEEDED_FILE = state / "cloud-seeded.json"
        server.BACKUPS = state / "backups"
        server.SEEDED = {"marks": False, "tasks": False}
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
        server.SEEDED = {"marks": False, "tasks": False}
        server.write_state(server.FILES["marks"], self.local)
        self.assertTrue(server.ensure_seeded("marks"))
        self.assertNotIn("b", server.CLOUD.data["marks"])

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
