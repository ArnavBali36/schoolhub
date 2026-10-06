"""Checks for server.py and the dashboard page, standard library only:

    python3 -m unittest discover tests

They run against a throwaway folder with a made-up data.js and config.json, never your own
config.json, state/ or data.js, and never the cloud database.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from html.parser import HTMLParser
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
# server.py connects to the optional cloud database when it is imported; the tests never do.
NO_CLOUD = "import sys, types; sys.modules['cloud'] = types.SimpleNamespace(connect=lambda: None, seed=lambda *a: None)"
sys.modules["cloud"] = types.SimpleNamespace(connect=lambda: None, seed=lambda *a: None)

PAGE_FILES = ("dashboard.html", "dashboard.js", "theme-init.js", "bar.js", "favicon.svg")
FAKE_DATA = 'window.SCHOOL_DATA = {"generated_at": "2026-01-01T00:00:00+00:00", "errors": [], "new_files": [], "courses": []};\n'


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_hub(root):
    """A SchoolHub folder inside a School folder: the page's files, made-up data and config."""
    hub = root / "SchoolHub"
    hub.mkdir()
    for name in PAGE_FILES:
        shutil.copy2(REPO / name, hub / name)
    (hub / "data.js").write_text(FAKE_DATA)
    (hub / "config.json").write_text(json.dumps({"school_root": str(root), "canvas_token": "not-a-real-token"}))
    (hub / "state").mkdir()
    return hub


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        os.environ["SCHOOLHUB_PORT"] = str(cls.port)
        import server
        cls.server_mod = server
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name).resolve()
        hub = make_hub(cls.root)
        # Point the server at the throwaway folder.
        server.HUB = hub
        server.MARKS, server.TASKS = hub / "state" / "marks.json", hub / "state" / "tasks.json"
        server.FILES = {"marks": server.MARKS, "tasks": server.TASKS}
        server.CLOUD = None
        course = cls.root / "Some Course"
        course.mkdir()
        (course / "notes.txt").write_text("hello")
        (course / "handout.js").write_text("alert(1)")
        (course / "week1.pdf").write_bytes(b"%PDF-1.4\n")
        (course / "diagram.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>')
        (course / ".env").write_text("SECRET=1")
        (cls.root / ".git").mkdir()
        (cls.root / ".git" / "config").write_text("[core]")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()
        os.environ.pop("SCHOOLHUB_PORT", None)

    def request(self, method, path, body=None, headers=None, host=None, full=False):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": host or f"127.0.0.1:{self.port}", **(headers or {})}
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        if full:
            return r.status, {k.lower(): v for k, v in r.getheaders()}, data
        return r.status, r.getheader("Content-Type") or "", data

    def file(self, p, name=None):
        """GET /file?p=<p> (or /file/<name>?p=<p>, as the dashboard links them)."""
        return self.request("GET", ("/file/" + quote(name) if name else "/file") + "?p=" + quote(str(p)), full=True)

    def test_pages_served(self):
        for path, ctype in [("/", "text/html"), ("/dashboard.html", "text/html"), ("/dashboard.js", "text/javascript"),
                            ("/theme-init.js", "text/javascript"), ("/bar.js", "text/javascript"),
                            ("/data.js", "text/javascript"), ("/favicon.svg", "image/svg+xml")]:
            with self.subTest(path=path):
                status, got, body = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertTrue(got.startswith(ctype), got)
                self.assertTrue(body)

    def test_port_and_hosts_from_schoolhub_port(self):
        self.assertEqual(self.server_mod.PORT, self.port)
        self.assertEqual(self.server_mod.ALLOWED_HOSTS, {f"127.0.0.1:{self.port}", f"localhost:{self.port}"})
        status, _, _ = self.request("GET", "/", host=f"localhost:{self.port}")
        self.assertEqual(status, 200)

    def test_host_check(self):
        for host in ("evil.example", f"127.0.0.1:{self.port + 1}", "127.0.0.1:8722" if self.port != 8722 else "x"):
            with self.subTest(host=host):
                self.assertEqual(self.request("GET", "/", host=host)[0], 403)
                self.assertEqual(self.request("GET", "/api/marks", host=host)[0], 403)
                self.assertEqual(self.request("POST", "/api/mark", b"{}", {"X-SchoolHub": "1"}, host=host)[0], 403)

    def test_writes_need_the_schoolhub_header(self):
        body = json.dumps({"id": "a1", "done": True}).encode()
        self.assertEqual(self.request("POST", "/api/mark", body, {"Content-Type": "application/json"})[0], 403)
        status, _, data = self.request("POST", "/api/mark", body, {"Content-Type": "application/json", "X-SchoolHub": "1"})
        self.assertEqual(status, 200)
        self.assertIn("a1", json.loads(data))
        self.request("POST", "/api/mark", json.dumps({"id": "a1", "done": False}).encode(), {"X-SchoolHub": "1"})

    def test_config_and_own_folder_never_served(self):
        hub = self.server_mod.HUB
        for path in ("/config.json", "/state/marks.json", "/server.py", "/../config.json"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)
        for p in (hub / "config.json", hub / "data.js", hub, self.root / ".." / "etc" / "passwd", "/etc/passwd"):
            with self.subTest(file=str(p)):
                for prefix in ("/file?p=", "/file/notes.txt?p="):
                    status, _, body = self.request("GET", prefix + str(p).replace(" ", "%20"))
                    self.assertEqual(status, 404)
                    self.assertNotIn(b"not-a-real-token", body)

    def test_own_folder_never_served_by_another_spelling(self):
        # The Mac's disk ignores case: schoolhub/config.json is SchoolHub/config.json.
        for spelling in ("schoolhub", "SCHOOLHUB", "schoolHub", "./schoolhub", "Some Course/../schoolhub"):
            for rest in ("config.json", "state/marks.json", "server.py"):
                p = f"{self.root}/{spelling}/{rest}"
                with self.subTest(p=p):
                    for name in (None, "notes.txt"):
                        status, _, body = self.file(p, name)
                        self.assertEqual(status, 404)
                        self.assertNotIn(b"not-a-real-token", body)
        self.assertIsNone(self.server_mod.allowed_path(f"{self.root}/schoolhub"))
        self.assertIsNone(self.server_mod.allowed_path(""))
        self.assertIsNone(self.server_mod.allowed_path("a\x00b"))
        for wrong in (123, None, ["x"], {"p": "x"}):  # a JSON body can carry any type
            self.assertIsNone(self.server_mod.allowed_path(wrong))

    def test_open_and_reveal_refuse_the_own_folder(self):
        opened = []
        saved = self.server_mod.subprocess.run
        self.server_mod.subprocess.run = lambda args, **kw: opened.append(args)
        try:
            for path in ("/api/open", "/api/reveal"):
                for p in (f"{self.root}/schoolhub/config.json", f"{self.root}/SchoolHub", f"{self.root}/.git/config"):
                    with self.subTest(path=path, p=p):
                        body = json.dumps({"path": p}).encode()
                        self.assertEqual(self.request("POST", path, body, {"X-SchoolHub": "1"})[0], 404)
            self.assertEqual(opened, [])
            body = json.dumps({"path": str(self.root / "Some Course" / "notes.txt")}).encode()
            self.assertEqual(self.request("POST", "/api/open", body, {"X-SchoolHub": "1"})[0], 200)
            self.assertEqual(len(opened), 1)
        finally:
            self.server_mod.subprocess.run = saved

    def test_hidden_files_never_served(self):
        for p in (self.root / "Some Course" / ".env", self.root / ".git" / "config", self.root / ".git"):
            with self.subTest(p=str(p)):
                self.assertEqual(self.file(p)[0], 404)

    def test_writes_take_a_json_object(self):
        for body in (b"[]", b'"a1"', b"1", b"null"):
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/api/mark", body, {"X-SchoolHub": "1"})[0], 400)
        # The server is still answering.
        self.assertEqual(self.request("GET", "/api/marks")[0], 200)

    def test_security_headers(self):
        status, h, _ = self.request("GET", "/", full=True)
        self.assertEqual(status, 200)
        self.assertEqual(h["content-security-policy"], self.server_mod.PAGE_CSP)
        self.assertIn("script-src 'self';", h["content-security-policy"])
        self.assertEqual(h["x-content-type-options"], "nosniff")
        # Course files: shown, never run. A script is plain text; an SVG or HTML file is sandboxed.
        course = self.root / "Some Course"
        status, h, body = self.file(course / "handout.js", "handout.js")
        self.assertEqual((status, h["content-type"]), (200, "text/plain; charset=utf-8"))
        self.assertEqual(h["content-security-policy"], self.server_mod.FILE_CSP)
        status, h, _ = self.file(course / "diagram.svg", "diagram.svg")
        self.assertEqual((h["content-type"], h["content-security-policy"]), ("image/svg+xml", self.server_mod.FILE_CSP))
        self.assertTrue(self.server_mod.FILE_CSP.startswith("sandbox;"))
        self.assertNotIn("allow-scripts", self.server_mod.FILE_CSP)
        status, h, _ = self.file(course / "week1.pdf", "week1.pdf")
        self.assertEqual((h["content-type"], h["content-security-policy"]), ("application/pdf", self.server_mod.PDF_CSP))
        self.assertIn("script-src 'none'", self.server_mod.PDF_CSP)
        self.assertEqual(h["x-content-type-options"], "nosniff")

    def test_course_files_served(self):
        p = str(self.root / "Some Course" / "notes.txt").replace(" ", "%20")
        # The page links file/<name>?p=… so a browser tab shows the name; the name is not what is read.
        for path in ("/file?p=" + p, "/file/notes.txt?p=" + p, "/file/other.pdf?p=" + p):
            with self.subTest(path=path):
                status, ctype, body = self.request("GET", path)
                self.assertEqual((status, body), (200, b"hello"))
                self.assertTrue(ctype.startswith("text/plain"))

    def test_platform_json_is_not_schoolhubs(self):
        # On its own server SchoolHub is not part of a platform: the page keeps its plain title.
        # A 204 says so without the error a browser logs for a 404.
        status, _, body = self.request("GET", "/platform.json")
        self.assertEqual((status, body), (204, b""))


class DefaultPortTest(unittest.TestCase):
    def test_default_port(self):
        env = {k: v for k, v in os.environ.items() if k != "SCHOOLHUB_PORT"}
        code = f"{NO_CLOUD}; sys.path.insert(0, {str(REPO)!r}); import server; print(server.PORT)"
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "8722")


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts, self.handlers = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script":
            self.scripts.append(a.get("src"))
        self.handlers += [f"{tag} {k}" for k in a if k.lower().startswith("on")]


class PageTest(unittest.TestCase):
    """The page runs under a Content-Security-Policy of script-src 'self', at any path prefix."""

    def test_no_inline_script_or_handlers(self):
        parser = Scripts()
        html = (REPO / "dashboard.html").read_text(encoding="utf-8")
        parser.feed(html)
        self.assertEqual(parser.scripts, ["theme-init.js", "bar.js", "data.js", "dashboard.js"])
        self.assertEqual(parser.handlers, [])
        # The theme and the bar are drawn before the first paint: both scripts are in <head>.
        head = html[:html.index("</head>")]
        self.assertIn('<script src="theme-init.js"></script>', head)
        self.assertIn('<script src="bar.js"></script>', head)
        self.assertIn('<link rel="icon" href="favicon.svg"', head)

    def test_requests_to_its_own_server_are_relative(self):
        js = (REPO / "dashboard.js").read_text(encoding="utf-8")
        absolute = set(re.findall(r"""['"`](/(?:api|file|data\.js|platform\.json|dashboard)[^'"`]*)['"`]""", js))
        # Only the phone site's cloud API is absolute.
        self.assertEqual(absolute, {"/api/state/"})
        for path in ("api/mark", "api/task", "api/task/delete", "api/marks", "api/tasks", "api/sync", "api/open", "file/"):
            self.assertIn(f"'{path}", js)
        bar = (REPO / "bar.js").read_text(encoding="utf-8")
        self.assertIn("fetch('platform.json'", bar)
        self.assertEqual(set(re.findall(r"""['"`](/(?:api|file|platform\.json)[^'"`]*)['"`]""", bar)), set())

    def test_course_colors(self):
        html = (REPO / "dashboard.html").read_text(encoding="utf-8")
        light = html[html.index(":root{"):html.index(':root[data-theme="dark"]')]
        dark = html[html.index(':root[data-theme="dark"]'):]
        dark = dark[:dark.index("}")]
        count = int(re.search(r"const COURSE_COLORS = (\d+);", (REPO / "dashboard.js").read_text(encoding="utf-8")).group(1))
        self.assertEqual(count, 10)
        for block in (light, dark):
            self.assertEqual(sorted(int(n) for n in re.findall(r"--course-(\d+):", block)), list(range(1, count + 1)))

    def test_app_switch_widths_match_quantprep(self):
        # QuantPrep's styles.css narrows its switch at the same widths (SWITCH_TIGHT_MAX and
        # SWITCH_MARK_MIN in its server/src/school.ts), so the switch sits still between the apps.
        html = (REPO / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn("@media (min-width:641px) and (max-width:960px){.app-switch .brand-mark{display:none}", html)
        self.assertIn("@media (max-width:360px){.app-switch .brand-mark{display:none}}", html)

    def test_theme_tokens_for_both_themes(self):
        html = (REPO / "dashboard.html").read_text(encoding="utf-8")
        self.assertNotIn("prefers-color-scheme", html)  # System is followed by the scripts
        self.assertIn(':root[data-theme="dark"]', html)
        self.assertIn("qp.theme", (REPO / "theme-init.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
