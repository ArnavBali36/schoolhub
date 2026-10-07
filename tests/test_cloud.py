"""Checks for cloud.py's Turso backend, standard library only, against a stand-in for Turso's HTTP API
(fake_turso.py: the same protocol over a SQLite file made from turso-schema.sql). Never the real
database, never your state/cloud.env.

    python3 -m unittest discover tests
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_turso import STRICT_OK, FakeTurso, load_cloud  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class EnvTest(unittest.TestCase):
    """Which database state/cloud.env chooses."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Path(self.tmp.name) / "cloud.env"
        self.cloud = load_cloud(self.env)

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self, text=None):
        if text is not None:
            self.env.write_text(text)
        return self.cloud.connect()

    def test_no_file_or_no_credentials_means_local_files(self):
        self.assertIsNone(self.connect())
        self.assertIsNone(self.connect("# nothing here\nOTHER=1\n"))

    def test_upstash_as_before(self):
        db = self.connect('KV_REST_API_URL="https://x.upstash.io"\nKV_REST_API_TOKEN="t"\n')
        self.assertIsInstance(db, self.cloud.Cloud)
        self.assertEqual((db.url, db.token), ("https://x.upstash.io", "t"))

    def test_turso_when_both_its_variables_are_there(self):
        # As `vercel env pull` writes them: quoted.
        db = self.connect('TURSO_DATABASE_URL="libsql://school-me.turso.io"\nTURSO_AUTH_TOKEN="tok"\n')
        self.assertIsInstance(db, self.cloud.Turso)
        self.assertEqual((db.endpoint, db.token), ("https://school-me.turso.io/v2/pipeline", "tok"))

    def test_turso_wins_over_upstash(self):
        db = self.connect('KV_REST_API_URL="https://x.upstash.io"\nKV_REST_API_TOKEN="t"\n'
                          'TURSO_DATABASE_URL="libsql://school-me.turso.io"\nTURSO_AUTH_TOKEN="tok"\n')
        self.assertIsInstance(db, self.cloud.Turso)

    def test_half_of_turso_is_not_turso(self):
        self.assertIsNone(self.connect('TURSO_DATABASE_URL="libsql://school-me.turso.io"\n'))
        self.assertIsNone(self.connect('TURSO_AUTH_TOKEN="tok"\n'))
        db = self.connect('TURSO_DATABASE_URL="libsql://school-me.turso.io"\nTURSO_AUTH_TOKEN=""\n'
                          'UPSTASH_REDIS_REST_URL="https://x.upstash.io"\nUPSTASH_REDIS_REST_TOKEN="t"\n')
        self.assertIsInstance(db, self.cloud.Cloud)


class PipelineUrlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cloud = load_cloud(Path(self.tmp.name) / "cloud.env")

    def tearDown(self):
        self.tmp.cleanup()

    def test_database_urls(self):
        url = self.cloud.pipeline_url
        for given, want in [
            ("libsql://school-me.turso.io", "https://school-me.turso.io/v2/pipeline"),
            ("LIBSQL://school-me.turso.io/", "https://school-me.turso.io/v2/pipeline"),
            ("https://school-me.turso.io", "https://school-me.turso.io/v2/pipeline"),
            ("wss://school-me.turso.io", "https://school-me.turso.io/v2/pipeline"),
            ("libsql://school-me.turso.io?authToken=secret", "https://school-me.turso.io/v2/pipeline"),
            (" libsql://school-me.turso.io:443 ", "https://school-me.turso.io:443/v2/pipeline"),
            # A libSQL server on this computer may be plain http.
            ("http://127.0.0.1:8080", "http://127.0.0.1:8080/v2/pipeline"),
            ("http://localhost:8080/", "http://localhost:8080/v2/pipeline"),
            ("ws://[::1]:8080", "http://[::1]:8080/v2/pipeline"),
            # Turso's other scheme, and libSQL's own way of asking for plain http (here only).
            ("turso://school-me.turso.io", "https://school-me.turso.io/v2/pipeline"),
            ("libsql://127.0.0.1:8080?tls=0", "http://127.0.0.1:8080/v2/pipeline"),
            ("libsql://school-me.turso.io?tls=1", "https://school-me.turso.io/v2/pipeline"),
        ]:
            with self.subTest(given=given):
                self.assertEqual(url(given), want)

    def test_not_database_urls(self):
        # Plain http anywhere but this computer would send the token in clear.
        for given in ("http://school-me.turso.io", "http://10.0.0.5:8080", "ftp://school-me.turso.io",
                      "file:///tmp/x.db", "school-me.turso.io", "libsql://", "https://user:pw@school-me.turso.io",
                      "libsql://school-me.turso.io:99999", "libsql://school-me.turso.io?tls=0", "", None):
            with self.subTest(given=given):
                self.assertIsNone(self.cloud.pipeline_url(given))

    def test_a_bad_url_fails_every_call_without_a_request(self):
        db = self.cloud.Turso("http://school-me.turso.io", "tok")
        for call in (lambda: db.get_all("marks"), lambda: db.put("marks", "a", {}), lambda: db.remove("tasks", "t"),
                     lambda: db.save_data("x", 1)):
            with self.assertRaisesRegex(RuntimeError, "TURSO_DATABASE_URL"):
                call()


@unittest.skipUnless(STRICT_OK, "this Python's SQLite is older than 3.37 (no STRICT tables)")
class TursoTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeTurso()
        self.tmp = tempfile.TemporaryDirectory()
        self.cloud = load_cloud(Path(self.tmp.name) / "cloud.env")
        self.db = self.cloud.Turso(self.fake.url, self.fake.token)

    def tearDown(self):
        self.fake.close()
        self.tmp.cleanup()

    def rows(self):
        return self.fake.query("SELECT name, key, value_json, updated_at, typeof(updated_at) FROM school_kv ORDER BY name, key")

    def test_marks_and_tasks_round_trip(self):
        mark = {"marked_at": "2026-10-07T12:00:00+00:00", "name": "HW 3 — “proofs”", "course": "15-122"}
        task = {"id": "task:abcdef012345", "name": "Read ch. 4", "course_id": "personal", "due_at": None}
        before = int(time.time() * 1000)
        self.db.put("marks", "canvas:1", mark)
        self.db.put("tasks", task["id"], task)
        after = int(time.time() * 1000)
        self.assertEqual(self.db.get_all("marks"), {"canvas:1": mark})
        self.assertEqual(self.db.get_all("tasks"), {task["id"]: task})
        # The rows as the other app sharing the database reads them.
        (n1, k1, v1, u1, t1), (n2, k2, v2, u2, t2) = self.rows()
        self.assertEqual((n1, k1, json.loads(v1)), ("marks", "canvas:1", mark))
        self.assertEqual((n2, k2, json.loads(v2)), ("tasks", task["id"], task))
        for updated, kind in ((u1, t1), (u2, t2)):
            self.assertEqual(kind, "integer")
            self.assertTrue(before <= updated <= after, (before, updated, after))  # milliseconds

    def test_put_replaces_and_remove_takes_only_its_own(self):
        self.db.put("marks", "a", {"v": 1})
        self.db.put("tasks", "a", {"v": "task"})
        first = self.rows()[0][3]
        time.sleep(0.005)
        self.db.put("marks", "a", {"v": 2})
        self.assertEqual(self.db.get_all("marks"), {"a": {"v": 2}})
        self.assertEqual(len(self.rows()), 2)
        self.assertGreater(self.rows()[0][3], first)
        self.db.remove("marks", "a")
        self.db.remove("marks", "never-there")
        self.assertEqual(self.db.get_all("marks"), {})
        self.assertEqual(self.db.get_all("tasks"), {"a": {"v": "task"}})

    def test_oldest_change_first(self):
        # The order a hosted copy reading school_kv answers in (updated_at, then key).
        self.db.put("tasks", "task:bbbbbbbb", {"n": 1})
        time.sleep(0.005)
        self.db.put("tasks", "task:aaaaaaaa", {"n": 2})
        self.fake.query("INSERT INTO school_kv VALUES ('tasks', 'task:cccccccc', '{\"n\": 3}', 1)")
        self.assertEqual(list(self.db.get_all("tasks")), ["task:cccccccc", "task:bbbbbbbb", "task:aaaaaaaa"])

    def test_only_marks_and_tasks(self):
        for call in (lambda: self.db.get_all("grades"), lambda: self.db.put("grades", "a", {}), lambda: self.db.remove("x", "a")):
            with self.assertRaises(KeyError):
                call()
        self.assertEqual(self.fake.pipelines, [])

    def test_a_row_that_is_not_json_is_skipped(self):
        self.fake.query("INSERT INTO school_kv VALUES ('marks', 'bad', '{not json', 1)")
        self.db.put("marks", "good", {"ok": True})
        self.assertEqual(self.db.get_all("marks"), {"good": {"ok": True}})

    def test_the_protocol(self):
        self.db.put("marks", "a", {"x": 1})
        self.db.get_all("marks")
        self.db.remove("marks", "a")
        self.db.save_data("window.SCHOOL_DATA = {};\n", 1759838400000)
        for headers in self.fake.headers:
            self.assertEqual(headers["Authorization"], f"Bearer {self.fake.token}")
            self.assertEqual(headers["Content-Type"], "application/json")
        for body in self.fake.pipelines:
            # Each call: one statement, then close. Values typed, an integer's as a string.
            self.assertEqual([r["type"] for r in body["requests"]], ["execute", "close"])
            for arg in body["requests"][0]["stmt"]["args"]:
                self.assertIn(arg["type"], ("text", "integer"))
                self.assertIsInstance(arg["value"], str)
        put = self.fake.pipelines[0]["requests"][0]["stmt"]["args"]
        self.assertEqual([a["type"] for a in put], ["text", "text", "text", "integer"])

    def test_seed_copies_what_the_database_lacks(self):
        self.cloud.seed(self.db, "marks", {"a": {"m": 1}, "b": {"m": 2}})
        self.assertEqual(self.db.get_all("marks"), {"a": {"m": 1}, "b": {"m": 2}})
        # A key the database has is left as it is (the phone may have changed it); c is added.
        self.cloud.seed(self.db, "marks", {"a": {"m": 9}, "c": {"m": 3}})
        self.assertEqual(self.db.get_all("marks"), {"a": {"m": 1}, "b": {"m": 2}, "c": {"m": 3}})
        self.cloud.seed(self.db, "tasks", {"task:aaaaaaaa": {"name": "x"}})  # tasks are their own
        self.assertEqual(self.db.get_all("tasks"), {"task:aaaaaaaa": {"name": "x"}})
        calls = len(self.fake.pipelines)
        self.cloud.seed(self.db, "tasks", {})
        self.assertEqual(len(self.fake.pipelines), calls)  # nothing to copy: no request

    def test_save_data(self):
        text = "window.SCHOOL_DATA = " + json.dumps({"courses": [], "note": "é ✓ “quotes” 📅", "pad": "x" * 400_000}) + ";\n"
        self.db.save_data(text, 1759838400000)
        self.assertEqual(self.fake.query("SELECT id, data_js, synced_at, typeof(synced_at) FROM school_data"),
                         [(1, text, 1759838400000, "integer")])
        self.db.save_data("newer", 1759838500000)
        self.assertEqual(self.fake.query("SELECT data_js, synced_at FROM school_data"), [("newer", 1759838500000)])
        # A sync that started earlier but finished later never replaces the newer copy.
        self.db.save_data("older", 1759838400000)
        self.assertEqual(self.fake.query("SELECT data_js FROM school_data"), [("newer",)])

    def test_describe_says_what_the_database_holds(self):
        self.assertEqual(self.cloud.describe(self.db),
                         "Turso (127.0.0.1): 0 marks, 0 tasks; no data.js yet (it goes up with the next sync).")
        self.db.put("marks", "canvas:1", {"m": 1})
        self.db.put("marks", "canvas:2", {"m": 2})
        self.db.put("tasks", "task:aaaaaaaa", {"name": "x"})
        self.db.save_data("x" * 4096, 1759838400000)
        calls = len(self.fake.pipelines)
        said = self.cloud.describe(self.db)
        self.assertEqual(said, "Turso (127.0.0.1): 2 marks, 1 tasks; data.js from the sync of 2025-10-07 12:00 UTC (4 KB).")
        self.assertNotIn(self.fake.token, said)
        # Read only: three selects, nothing written.
        self.assertEqual(len(self.fake.pipelines), calls + 3)
        for body in self.fake.pipelines[calls:]:
            self.assertTrue(body["requests"][0]["stmt"]["sql"].startswith("SELECT"))
        self.assertIn("No shared database", self.cloud.describe(None))

    def test_describe_is_the_command(self):
        # python3 cloud.py, from a SchoolHub folder whose state/cloud.env names the fake.
        hub = Path(self.tmp.name) / "SchoolHub"
        (hub / "state").mkdir(parents=True)
        shutil.copy2(REPO / "cloud.py", hub / "cloud.py")
        run = lambda: subprocess.run([sys.executable, str(hub / "cloud.py")], cwd=hub, capture_output=True, text=True, timeout=30)
        p = run()
        self.assertEqual((p.returncode, p.stdout.strip()), (0, "No shared database in state/cloud.env: marks and tasks stay in state/ on this computer."))
        (hub / "state" / "cloud.env").write_text(f'TURSO_DATABASE_URL="{self.fake.url}"\nTURSO_AUTH_TOKEN="{self.fake.token}"\n')
        p = run()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(p.stdout.startswith("Turso (127.0.0.1): 0 marks, 0 tasks"), p.stdout)
        (hub / "state" / "cloud.env").write_text(f'TURSO_DATABASE_URL="{self.fake.url}"\nTURSO_AUTH_TOKEN="wrong-token"\n')
        p = run()
        self.assertEqual(p.returncode, 1)
        self.assertIn("did not answer: Turso answered HTTP 401", p.stderr)
        self.assertNotIn("wrong-token", p.stdout + p.stderr)

    def assertFails(self, call, kinds=(RuntimeError,), says=None):
        with self.assertRaises(kinds) as ctx:
            call()
        # server.py turns these two into "couldn't reach the cloud database".
        self.assertIsInstance(ctx.exception, (OSError, RuntimeError))
        self.assertNotIn(self.fake.token, str(ctx.exception))
        if says:
            self.assertIn(says, str(ctx.exception))
        return ctx.exception

    def test_errors_are_what_server_py_catches(self):
        wrong = self.cloud.Turso(self.fake.url, "not-the-token")
        self.assertFails(lambda: wrong.get_all("marks"), says="HTTP 401: Unauthorized")
        self.fake.answer = (500, {"error": "internal error"})
        self.assertFails(lambda: self.db.put("marks", "a", {}), says="HTTP 500: internal error")
        self.fake.answer = (200, b"<html>not json</html>", {"Content-Type": "text/html"})
        self.assertFails(lambda: self.db.get_all("marks"), says="could not be read")
        self.fake.answer = (200, {"results": []})
        self.assertFails(lambda: self.db.get_all("marks"), says="could not be read")
        self.fake.answer = (200, {"results": [{"type": "ok", "response": {"type": "execute", "result": {"rows": [[{"type": "integer", "value": "1"}]]}}},
                                              {"type": "ok", "response": {"type": "close"}}]})
        self.assertFails(lambda: self.db.get_all("marks"), says="could not be read")  # one column, not two
        self.fake.answer = None

    def test_a_missing_table_is_reported(self):
        with FakeTurso(schema=False) as bare:
            db = self.cloud.Turso(bare.url, bare.token)
            self.assertFails(lambda: db.put("marks", "a", {}), says="no such table: school_kv")
            self.assertFails(lambda: db.save_data("x", 1), says="no such table: school_data")

    def test_the_database_down_is_an_os_error(self):
        db = self.cloud.Turso(f"http://127.0.0.1:{free_port()}", "tok")
        self.assertFails(lambda: db.get_all("marks"), kinds=(OSError,))

    def test_a_redirect_is_not_followed(self):
        # The token must never go where a redirect points.
        with FakeTurso() as elsewhere:
            for code in (301, 302, 303, 307, 308):
                with self.subTest(code=code):
                    self.fake.answer = (code, b"", {"Location": elsewhere.url + "/v2/pipeline"})
                    self.assertFails(lambda: self.db.get_all("marks"), says=f"HTTP {code}")
            self.assertEqual(elsewhere.headers, [])


@unittest.skipUnless(STRICT_OK, "this Python's SQLite is older than 3.37 (no STRICT tables)")
class ServerWithTursoTest(unittest.TestCase):
    """server.py itself, run from a throwaway SchoolHub folder whose state/cloud.env names the fake."""

    PAGE_FILES = ("server.py", "cloud.py", "dashboard.html", "dashboard.js", "theme-init.js", "bar.js", "favicon.svg")

    @classmethod
    def setUpClass(cls):
        cls.fake = FakeTurso()
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name).resolve()
        hub = root / "SchoolHub"
        (hub / "state").mkdir(parents=True)
        for name in cls.PAGE_FILES:
            shutil.copy2(REPO / name, hub / name)
        (hub / "data.js").write_text('window.SCHOOL_DATA = {"generated_at": "2026-01-01T00:00:00+00:00", "errors": [], "new_files": [], "courses": []};\n')
        (hub / "config.json").write_text(json.dumps({"school_root": str(root), "canvas_token": "not-a-real-token"}))
        # Made before the database was connected: copied up when the server starts.
        (hub / "state" / "marks.json").write_text(json.dumps({"canvas:9": {"marked_at": "2026-10-01T00:00:00+00:00"}}))
        (hub / "state" / "tasks.json").write_text(json.dumps({}))
        (hub / "state" / "cloud.env").write_text(f'TURSO_DATABASE_URL="{cls.fake.url}"\nTURSO_AUTH_TOKEN="{cls.fake.token}"\n')
        cls.hub = hub
        cls.port = free_port()
        env = {**os.environ, "SCHOOLHUB_PORT": str(cls.port)}
        cls.proc = subprocess.Popen([sys.executable, str(hub / "server.py")], cwd=hub, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 15
        while True:
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                break
            except OSError:
                if time.time() > deadline or cls.proc.poll() is not None:
                    cls.tearDownClass()
                    raise RuntimeError("server.py did not start")
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
            cls.proc.wait()
        cls.fake.close()
        cls.tmp.cleanup()

    def request(self, method, path, body=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": f"127.0.0.1:{self.port}"}
        if body is not None:
            headers.update({"Content-Type": "application/json", "X-SchoolHub": "1"})
        conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=headers)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, (json.loads(data) if r.status == 200 else data)

    def kv(self, name):
        return {k: json.loads(v) for k, v in self.fake.query("SELECT key, value_json FROM school_kv WHERE name = ?", name)}

    def test_marks_made_before_are_copied_up_at_start(self):
        self.assertIn("canvas:9", self.kv("marks"))

    def test_marks_and_tasks_live_in_school_kv(self):
        status, marks = self.request("POST", "/api/mark", {"id": "canvas:1", "done": True, "name": "HW", "course": "15-122"})
        self.assertEqual(status, 200)
        self.assertEqual(self.kv("marks")["canvas:1"]["name"], "HW")
        self.assertIn("canvas:1", marks)
        # Reads come from the database: a mark made on another device shows here.
        self.fake.query("INSERT INTO school_kv VALUES ('marks', 'canvas:2', ?, 1)", json.dumps({"marked_at": "2026-10-07T00:00:00+00:00"}))
        self.assertIn("canvas:2", self.request("GET", "/api/marks")[1])
        status, out = self.request("POST", "/api/task", {"name": "Read ch. 4"})
        self.assertEqual(status, 200)
        tid = out["task"]["id"]
        self.assertEqual(self.kv("tasks")[tid]["name"], "Read ch. 4")
        self.assertIn(tid, self.request("GET", "/api/tasks")[1]["tasks"])
        self.assertEqual(self.request("POST", "/api/task/delete", {"id": tid})[0], 200)
        self.assertNotIn(tid, self.kv("tasks"))
        self.request("POST", "/api/mark", {"id": "canvas:1", "done": False})
        self.assertNotIn("canvas:1", self.kv("marks"))
        # The local copy follows, for offline reads and the nightly sync.
        self.assertIn("canvas:2", json.loads((self.hub / "state" / "marks.json").read_text()))

    def test_database_unreachable(self):
        token, self.fake.token = self.fake.token, "rotated"
        try:
            # A save says it failed; reading falls back to the local copy.
            self.assertEqual(self.request("POST", "/api/mark", {"id": "canvas:3", "done": True})[0], 502)
            self.assertEqual(self.request("GET", "/api/marks")[0], 200)
        finally:
            self.fake.token = token
        self.assertNotIn("canvas:3", self.kv("marks"))


if __name__ == "__main__":
    unittest.main()
