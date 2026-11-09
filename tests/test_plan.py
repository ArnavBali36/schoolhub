"""Checks for the day planner's store (plan.py, and /api/plan in server.py), standard library only.

The cleaning is driven by tests/plan_vectors.json, which QuantPrep's schoolPublic.ts is checked
against too, so both servers keep and refuse the same values. The server runs from a throwaway folder
with no cloud database; test_cloud.py and test_seed.py cover the plan in Turso and Upstash.

    python3 -m unittest discover tests
"""
import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import types
import unittest
from datetime import date, timedelta
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
# server.py connects to the optional cloud database when it is imported; the tests never do.
sys.modules.setdefault("cloud", types.SimpleNamespace(connect=lambda: None, seed=lambda *a: None))

import plan  # noqa: E402

VECTORS = json.loads((REPO / "tests" / "plan_vectors.json").read_text(encoding="utf-8"))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def load_server(port):
    """A copy of server.py of its own, on its own port, so the other test files still import theirs."""
    saved = os.environ.get("SCHOOLHUB_PORT")
    os.environ["SCHOOLHUB_PORT"] = str(port)
    try:
        spec = importlib.util.spec_from_file_location("server_under_plan_test", REPO / "server.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is None:
            os.environ.pop("SCHOOLHUB_PORT", None)
        else:
            os.environ["SCHOOLHUB_PORT"] = saved
    return module


class VectorTest(unittest.TestCase):
    def test_every_vector(self):
        self.assertGreater(len(VECTORS), 100)
        for n, case in enumerate(VECTORS):
            with self.subTest(n=n, note=case["note"], key=case["key"]):
                cleaned, error = plan.clean_plan(case["key"], case["value"])
                if case["ok"]:
                    self.assertIsNone(error)
                    self.assertEqual(cleaned, case["cleaned"])
                else:
                    self.assertIsNone(cleaned)
                    self.assertIsNotNone(error)
                    self.assertIn(case["error_contains"], error)

    def test_vectors_are_well_formed(self):
        # The file is read by another language too: plain JSON, every case one of the two shapes.
        for case in VECTORS:
            self.assertLessEqual(set(case), {"note", "key", "value", "ok", "cleaned", "error_contains"})
            self.assertIsInstance(case["ok"], bool)
            self.assertEqual("cleaned" in case, case["ok"])
            self.assertEqual("error_contains" in case, not case["ok"])

    def test_cleaning_twice_changes_nothing(self):
        # The server cleans again on the way out (assemble), so a cleaned value must pass unchanged.
        for case in VECTORS:
            if case["ok"] and case["cleaned"] is not None:
                with self.subTest(note=case["note"]):
                    self.assertEqual(plan.clean_plan(case["key"], case["cleaned"]), (case["cleaned"], None))

    def test_the_input_is_never_changed(self):
        value = {"blocks": [{"id": "abcdef", "type": "deep", "title": "  x  ", "start": "09:00", "end": "10:00",
                             "items": [{"id": "ghijkl", "kind": "own", "text": " y ", "done": 1}]}]}
        before = json.dumps(value)
        plan.clean_plan("day:2026-11-08", value)
        self.assertEqual(json.dumps(value), before)


class RangeTest(unittest.TestCase):
    TODAY = date(2026, 11, 8)

    def range(self, **q):
        return plan.plan_range({k: [v] for k, v in q.items()}, self.TODAY)

    def refused(self, reason, **q):
        with self.assertRaises(plan.Refused) as ctx:
            self.range(**q)
        self.assertEqual(str(ctx.exception), reason)

    def test_without_a_range_today_plus_or_minus_seven(self):
        self.assertEqual(self.range(), (date(2026, 11, 1), date(2026, 11, 15)))

    def test_inclusive_and_at_most_62_days(self):
        self.assertEqual(self.range(**{"from": "2026-11-08", "to": "2026-11-08"}), (self.TODAY, self.TODAY))
        self.assertEqual(self.range(**{"from": "2026-11-01", "to": "2027-01-01"}), (date(2026, 11, 1), date(2027, 1, 1)))
        self.refused("bad range: at most 62 days", **{"from": "2026-11-01", "to": "2027-01-02"})

    def test_bad_ranges(self):
        self.refused("bad range: to is before from", **{"from": "2026-11-09", "to": "2026-11-08"})
        self.refused("bad range: give both from and to", **{"from": "2026-11-08"})
        self.refused("bad range: give both from and to", to="2026-11-08")
        for bad in ("", "2026-11-8", "2026-02-30", "11/08/2026", "2026-11-08T00:00", "2026-11-08\n", "today"):
            with self.subTest(bad=bad):
                self.refused("bad range: from and to are YYYY-MM-DD dates", **{"from": bad, "to": "2026-11-20"})
                self.refused("bad range: from and to are YYYY-MM-DD dates", **{"from": "2026-11-01", "to": bad})


class AssembleTest(unittest.TestCase):
    def test_defaults_when_nothing_is_stored(self):
        got = plan.assemble({}, date(2026, 11, 1), date(2026, 11, 15))
        self.assertEqual(got, {"settings": {"day_start": 5, "day_end": 24},
                               "week": {wd: plan.default_week() for wd in plan.WEEKDAYS}, "days": {}})
        self.assertEqual(plan.default_week()["meals"]["lunch"], {"start": "16:00", "end": "17:00", "place": "", "off": False})

    def test_stored_values_cleaned_and_days_in_range_only(self):
        stored = {
            "settings": {"day_start": 6, "day_end": 23, "old": 1},
            "week:sun": {"meals": {"lunch": {"place": "Chipotle"}}},
            "week:mon": {"meals": {"lunch": {"start": "nonsense"}}},  # no longer passes: the defaults
            "day:2026-10-31": {"meals": {}},
            "day:2026-11-01": {"blocks": [{"id": "abcdef", "type": "deep", "start": "09:00", "end": "10:00"}]},
            "day:2026-11-15": {"meals": {}},
            "day:2026-11-16": {"meals": {}},
            "day:2026-11-10": {"blocks": "broken"},  # left out
            "day:2026-02-30": {},  # not a date: never answered
            "nonsense": {},
        }
        got = plan.assemble(stored, date(2026, 11, 1), date(2026, 11, 15))
        self.assertEqual(got["settings"], {"day_start": 6, "day_end": 23})
        self.assertEqual(got["week"]["sun"]["meals"]["lunch"]["place"], "Chipotle")
        self.assertEqual(got["week"]["sun"]["meals"]["dinner"], plan.default_week()["meals"]["dinner"])
        self.assertEqual(got["week"]["mon"], plan.default_week())
        self.assertEqual(set(got["week"]), set(plan.WEEKDAYS))
        self.assertEqual(list(got["days"]), ["2026-11-01", "2026-11-15"])
        self.assertEqual(got["days"]["2026-11-01"]["blocks"][0]["title"], "Deep work")


class PlanServerTest(unittest.TestCase):
    """GET and POST /api/plan on server.py, with no cloud: the plan lives in state/plan.json."""

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = load_server(cls.port)
        cls.tmp = tempfile.TemporaryDirectory()
        hub = Path(cls.tmp.name).resolve() / "SchoolHub"
        (hub / "state").mkdir(parents=True)
        (hub / "planner.js").write_text("// the planner\n")
        cls.server.HUB = hub
        cls.server.FILES = {name: hub / "state" / f"{name}.json" for name in ("marks", "tasks", "plan")}
        cls.server.CLOUD = None
        cls.plan_file = hub / "state" / "plan.json"
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), cls.server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        self.plan_file.unlink(missing_ok=True)
        self.server.CLOUD = None

    def request(self, method, path, body=None, headers=None, host=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": host or f"127.0.0.1:{self.port}", **(headers or {})}
        data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        out = r.read()
        conn.close()
        return r.status, r.getheader("Content-Type") or "", out

    def save(self, key, value, **kw):
        status, _, out = self.request("POST", "/api/plan", {"key": key, "value": value}, {"X-SchoolHub": "1"}, **kw)
        return status, (json.loads(out) if status == 200 else out.decode())

    def get(self, query=""):
        status, ctype, out = self.request("GET", "/api/plan" + query)
        return status, (json.loads(out) if status == 200 else out.decode())

    def test_save_answers_the_cleaned_value_and_keeps_it_in_plan_json(self):
        status, out = self.save("week:sun", {"meals": {"lunch": {"place": "  Chipotle "}}, "extra": 1})
        self.assertEqual(status, 200)
        self.assertEqual(out["key"], "week:sun")
        self.assertEqual(out["value"]["meals"]["lunch"], {"start": "16:00", "end": "17:00", "place": "Chipotle", "off": False})
        self.assertNotIn("extra", out["value"])
        self.assertEqual(json.loads(self.plan_file.read_text()), {"week:sun": out["value"]})
        # Every Sunday shows it; the other weekdays keep the defaults.
        status, got = self.get("?from=2026-11-01&to=2026-11-14")
        self.assertEqual(status, 200)
        self.assertEqual(got["week"]["sun"], out["value"])
        self.assertEqual(got["week"]["mon"], plan.default_week())

    def test_null_deletes_and_brings_back_the_defaults(self):
        self.save("settings", {"day_start": 6, "day_end": 22})
        self.assertEqual(self.get()[1]["settings"], {"day_start": 6, "day_end": 22})
        self.assertEqual(self.save("settings", None), (200, {"key": "settings", "value": None}))
        self.assertEqual(self.get()[1]["settings"], {"day_start": 5, "day_end": 24})
        self.assertEqual(json.loads(self.plan_file.read_text()), {})
        # Deleting what is not there is fine too.
        self.assertEqual(self.save("day:2026-11-08", None)[0], 200)

    def test_a_whole_value_replaces_the_old_one(self):
        block = {"id": "b1a2b3c4d5", "type": "social", "start": "19:00", "end": "21:00"}
        self.save("day:2026-11-08", {"blocks": [block], "meals": {"lunch": {"place": "X"}}})
        self.save("day:2026-11-08", {"blocks": [block]})
        days = self.get("?from=2026-11-08&to=2026-11-08")[1]["days"]
        self.assertEqual(days, {"2026-11-08": {"blocks": [{**block, "title": "Socialize"}]}})

    def test_refusals_are_400_with_the_reason(self):
        for key, value, reason in [
            ("week:sunday", {}, "bad key"),
            ("day:2026-02-30", {}, "bad key: not a real date"),
            ("settings", {"day_start": 22}, "day_end must be at least 4 hours after day_start"),
            ("day:2026-11-08", {"blocks": [{"id": "abcdef", "type": "deep", "start": "09:00", "end": "23:57"}]},
             "times are HH:MM from 00:00 to 24:00 in 5-minute steps"),
            ("week:sun", [], "the value must be an object"),
        ]:
            with self.subTest(key=key):
                self.assertEqual(self.save(key, value), (400, reason))
        status, _, out = self.request("POST", "/api/plan", {"key": "settings"}, {"X-SchoolHub": "1"})
        self.assertEqual((status, out), (400, b"missing value"))  # never read as null, which deletes
        status, _, out = self.request("POST", "/api/plan", b"[]", {"X-SchoolHub": "1"})
        self.assertEqual(status, 400)
        self.assertFalse(self.plan_file.exists())

    def test_ranges(self):
        today = date.today()
        for offset in (-8, -7, 0, 7, 8):
            self.save(f"day:{today + timedelta(days=offset)}", {"meals": {"lunch": {"place": str(offset)}}})
        # Without a range: today ±7 on the server's clock, both ends included.
        status, got = self.get()
        self.assertEqual(status, 200)
        self.assertEqual(sorted(got["days"]), sorted(str(today + timedelta(days=d)) for d in (-7, 0, 7)))
        self.assertEqual(set(got), {"settings", "week", "days"})
        self.assertEqual(set(got["week"]), set(plan.WEEKDAYS))
        start, end = today - timedelta(days=8), today - timedelta(days=8) + timedelta(days=61)
        self.assertEqual(sorted(self.get(f"?from={start}&to={end}")[1]["days"]),
                         sorted(str(today + timedelta(days=d)) for d in (-8, -7, 0, 7, 8)))
        for query, reason in [(f"?from={start}&to={end + timedelta(days=1)}", "bad range: at most 62 days"),
                              (f"?from={today}&to={today - timedelta(days=1)}", "bad range: to is before from"),
                              (f"?from={today}", "bad range: give both from and to"),
                              ("?from=&to=", "bad range: from and to are YYYY-MM-DD dates"),
                              ("?from=2026-02-30&to=2026-03-02", "bad range: from and to are YYYY-MM-DD dates")]:
            with self.subTest(query=query):
                self.assertEqual(self.get(query), (400, reason))

    def test_writes_need_the_header_and_both_need_the_host(self):
        body = {"key": "settings", "value": {}}
        self.assertEqual(self.request("POST", "/api/plan", body)[0], 403)
        self.assertEqual(self.request("POST", "/api/plan", body, {"X-SchoolHub": "1"}, host="evil.example")[0], 403)
        self.assertEqual(self.request("GET", "/api/plan", host="evil.example")[0], 403)
        self.assertFalse(self.plan_file.exists())

    def test_a_cloud_failure_is_502_like_tasks(self):
        class Down:
            def put(self, *a):
                raise RuntimeError("Turso refused a statement: SQLite error: no such table: school_plan")

            remove = put

            def get_all(self, name):
                raise OSError("down")

        self.server.CLOUD = Down()
        self.assertEqual(self.save("settings", {}), (502, "couldn't reach the cloud database"))
        self.assertEqual(self.save("settings", None), (502, "couldn't reach the cloud database"))
        # Reading still answers, from the local file.
        self.assertEqual(self.get()[0], 200)

    def test_planner_js_is_served_and_plan_py_is_not(self):
        status, ctype, body = self.request("GET", "/planner.js")
        self.assertEqual((status, body), (200, b"// the planner\n"))
        self.assertTrue(ctype.startswith("text/javascript"))
        self.assertEqual(self.server.PAGES["/planner.js"], "planner.js")
        for path in ("/plan.py", "/state/plan.json"):
            self.assertEqual(self.request("GET", path)[0], 404)
        self.assertNotIn("plan.py", self.server.PAGES.values())


if __name__ == "__main__":
    unittest.main()
