"""Checks that sync.py shares each new data.js through the Turso database when state/cloud.env names
one, and that a failure there never fails the sync. Standard library only, against the stand-in for
Turso (fake_turso.py), in a throwaway SchoolHub folder: never Canvas, never your config.json,
state/ or data.js, never the real database.

    python3 -m unittest discover tests
"""
import contextlib
import io
import json
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(REPO))
from fake_turso import STRICT_OK, FakeTurso, load_cloud  # noqa: E402

import sync  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(STRICT_OK, "this Python's SQLite is older than 3.37 (no STRICT tables)")
class ShareDataTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        hub = self.root / "SchoolHub"
        (hub / "state").mkdir(parents=True)
        self.hub = hub
        self.env = hub / "state" / "cloud.env"
        self.fake = FakeTurso()
        self.addCleanup(self.fake.close)
        # sync.py imports cloud when it runs; give it cloud.py reading this folder's cloud.env.
        patches = [mock.patch.dict(sys.modules, {"cloud": load_cloud(self.env)}),
                   mock.patch.object(sys, "argv", ["sync.py"])]
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

    def use_turso(self, token=None, url=None):
        self.env.write_text(f'TURSO_DATABASE_URL="{url or self.fake.url}"\nTURSO_AUTH_TOKEN="{token or self.fake.token}"\n')

    def shared(self):
        return self.fake.query("SELECT data_js, synced_at FROM school_data")

    # ---- share_data on its own ----

    def test_saved_to_school_data(self):
        self.use_turso()
        now, errors = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc), []
        sync.share_data({"courses": []}, now, errors)
        self.assertEqual(errors, [])
        self.assertEqual(self.shared(), [('window.SCHOOL_DATA = {"courses": []};\n', int(now.timestamp() * 1000))])

    def test_the_shared_copy_names_no_path_and_carries_no_file_token(self):
        self.use_turso()
        home = str(Path.home())
        data = {
            "errors": [f"Couldn't read {home}/School/x.pdf"],
            "new_files": ["/Users/someone/Desktop/School/HW/a.pdf"],
            "courses": [{"folder": f"{home}/Desktop/School/Math", "assignments": [{
                "name": "HW 1", "score": 9, "comments": ["Good work."],
                "files": [{"name": "a.pdf", "path": f"{home}/Desktop/School/Math/a.pdf", "size": 3}],
                "description_html": '<a href="https://canvas.example.edu/courses/1/files/2/download?verifier=SECRET&amp;wrap=1">a</a>'
                                    ' <img src="https://canvas.example.edu/files/3/preview?verifier=SECRET2">'
                                    ' and https://example.com/Users/page?x=1&verifier=S3',
            }]}],
        }
        sync.share_data(data, datetime.now(timezone.utc), [])
        (text, _), = self.shared()
        self.assertNotIn("SECRET", text)
        self.assertNotIn("S3", text)
        self.assertNotIn(home, text)
        self.assertNotIn("/Users/someone", text)
        shared = json.loads(text.split("=", 1)[1].strip().rstrip(";"))
        a = shared["courses"][0]["assignments"][0]
        self.assertEqual(shared["courses"][0]["folder"], "~/Desktop/School/Math")
        self.assertEqual(a["files"][0], {"name": "a.pdf", "path": "~/Desktop/School/Math/a.pdf", "size": 3})
        self.assertEqual(shared["new_files"], ["~/Desktop/School/HW/a.pdf"])
        self.assertEqual(shared["errors"], ["Couldn't read ~/School/x.pdf"])
        self.assertIn('download?wrap=1">a</a>', a["description_html"])
        self.assertIn('files/3/preview">', a["description_html"])
        # A path in a web address is not a path on this computer.
        self.assertIn("https://example.com/Users/page?x=1", a["description_html"])
        # What the dashboard needs is all there: grades, feedback, names.
        self.assertEqual((a["name"], a["score"], a["comments"]), ("HW 1", 9, ["Good work."]))
        # The local data.js is the sync's own business: the copy leaves the original alone.
        self.assertIn("verifier=SECRET", data["courses"][0]["assignments"][0]["description_html"])

    def test_nothing_without_turso(self):
        for env in (None, 'KV_REST_API_URL="http://127.0.0.1:1"\nKV_REST_API_TOKEN="t"\n'):
            with self.subTest(env=env):
                if env:
                    self.env.write_text(env)
                errors = []
                sync.share_data({}, datetime.now(timezone.utc), errors)
                self.assertEqual(errors, [])  # Upstash keeps marks and tasks only: nothing is sent
        self.assertEqual(self.shared(), [])
        self.assertEqual(self.fake.pipelines, [])

    def test_an_unreadable_cloud_env_is_not_the_syncs_problem(self):
        # Upstash users included: server.py already says when it cannot read the file.
        self.env.write_text('KV_REST_API_URL="http://127.0.0.1:1"\nKV_REST_API_TOKEN="t"\n')
        errors = []
        with mock.patch.object(sys.modules["cloud"], "connect", side_effect=PermissionError("denied")):
            sync.share_data({}, datetime.now(timezone.utc), errors)
        self.assertEqual(errors, [])

    def test_a_failure_is_reported_not_raised(self):
        for setup in (lambda: self.use_turso(token="wrong"), lambda: self.use_turso(url=f"http://127.0.0.1:{free_port()}"),
                      lambda: self.use_turso(url="http://school.example.com")):
            with self.subTest():
                setup()
                errors = []
                sync.share_data({}, datetime.now(timezone.utc), errors)
                self.assertEqual(len(errors), 1)
                self.assertTrue(errors[0].startswith("Couldn't save data.js to the Turso database: "), errors[0])
                self.assertNotIn(self.fake.token, errors[0])
        self.assertEqual(self.shared(), [])

    # ---- a whole sync (Canvas stood in for) ----

    def course(self, now):
        def assignment(aid, status, days):
            return {"id": aid, "name": f"HW {aid}", "due_at": (now + timedelta(days=days)).isoformat(), "points": 10,
                    "status": status, "score": None, "grade": None, "submitted_at": None, "late": False,
                    "platform": "Canvas", "verifiable": True, "url": None, "folder": None, "files": [],
                    "submitted_files": [], "description_html": "", "comments": []}
        return {"id": "canvas:1", "source": "canvas", "name": "Course", "short": "C1", "color": None, "url": None,
                "folder": None, "materials": [],
                "assignments": [assignment("canvas:11", "todo", 10), assignment("canvas:12", "submitted", -1)]}

    def run_sync(self):
        out, err = io.StringIO(), io.StringIO()
        canvas = lambda cv, cfg, store, errors, now: [self.course(now)]  # noqa: E731
        with mock.patch.object(sync, "sync_canvas", canvas), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            sync.main()
        return out.getvalue(), err.getvalue()

    def test_a_sync_shares_the_data_js_it_wrote(self):
        self.use_turso()
        # A mark made on another device, read back by the sync.
        self.fake.query("INSERT INTO school_kv VALUES ('marks', 'canvas:12', ?, 1)",
                        json.dumps({"marked_at": "2026-10-06T00:00:00+00:00"}))
        out, err = self.run_sync()
        self.assertEqual(out, "")  # nothing needs attention
        self.assertIn("0 errors", err)
        text = (self.hub / "data.js").read_text()
        data = json.loads(text.split("=", 1)[1].strip().rstrip(";"))
        # The shared copy is the data.js the sync wrote, made public (nothing here to change).
        self.assertEqual(self.shared(), [("window.SCHOOL_DATA = " + json.dumps(sync.public_copy(data)) + ";\n",
                                          int(datetime.fromisoformat(data["generated_at"]).timestamp() * 1000))])
        marked = {a["id"]: a.get("mark_check") for a in data["courses"][0]["assignments"]}
        self.assertEqual(marked, {"canvas:11": None, "canvas:12": "confirmed"})

    def test_a_sync_still_finishes_when_sharing_fails(self):
        self.use_turso(token="wrong")
        out, err = self.run_sync()
        self.assertTrue((self.hub / "data.js").is_file())
        self.assertIn("⚠️ Couldn't save data.js to the Turso database: Turso answered HTTP 401", out)
        self.assertIn("1 errors", err)
        self.assertEqual(self.shared(), [])

    def test_a_sync_without_turso_is_as_before(self):
        out, err = self.run_sync()
        self.assertEqual(out, "")
        self.assertIn("0 errors", err)
        self.assertTrue((self.hub / "data.js").is_file())
        self.assertEqual(self.fake.pipelines, [])


if __name__ == "__main__":
    unittest.main()
