"""Checks for publish.py's build of the phone site, standard library only. Builds into a throwaway
folder from made-up data; never deploys, never reads your config.json or data.js."""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import publish  # noqa: E402


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        hub = root / "hub"
        (hub / "vercel" / "api").mkdir(parents=True)
        for name in ("dashboard.html", "dashboard.js", "theme-init.js", "bar.js", "favicon.svg"):
            shutil.copy2(REPO / name, hub / name)
        shutil.copy2(REPO / "vercel" / "api" / "state.js", hub / "vercel" / "api" / "state.js")
        (hub / "data.js").write_text('window.SCHOOL_DATA = {"courses": []};\n')
        self.saved = publish.HUB, publish.SITE, publish.CONFIG
        publish.HUB, publish.SITE, publish.CONFIG = hub, root / "site", root / "config.json"
        self.site = root / "site"

    def tearDown(self):
        publish.HUB, publish.SITE, publish.CONFIG = self.saved
        self.tmp.cleanup()

    def test_build_copies_the_page_and_its_scripts(self):
        publish.build({"site": {"secret": "s3cret"}})
        page = self.site / "s3cret"
        for name in ("index.html", "dashboard.js", "theme-init.js", "bar.js", "data.js", "favicon.svg"):
            self.assertTrue((page / name).is_file(), name)
        self.assertEqual((page / "dashboard.js").read_bytes(), (REPO / "dashboard.js").read_bytes())
        self.assertTrue((self.site / "api" / "state.js").is_file())
        self.assertIn("noindex", json.loads((self.site / "vercel.json").read_text())["headers"][0]["headers"][0]["value"])

    def test_only_the_phone_site_is_marked(self):
        publish.build({"site": {"secret": "s3cret"}})
        html = (self.site / "s3cret" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count(publish.PHONE_MARK), 1)
        # First in <head>, before bar.js, which reads it while the page loads.
        self.assertLess(html.index(publish.PHONE_MARK), html.index('<script src="theme-init.js">'))
        self.assertNotIn(publish.PHONE_MARK, (REPO / "dashboard.html").read_text(encoding="utf-8"))
        # Everything else in the page is dashboard.html as it is.
        self.assertEqual(html.replace(publish.PHONE_MARK + "\n", ""), (REPO / "dashboard.html").read_text(encoding="utf-8"))

    def test_new_secret_is_saved_to_config(self):
        with contextlib.redirect_stdout(io.StringIO()):
            publish.build({"site": {}})
        secret = json.loads(publish.CONFIG.read_text())["site"]["secret"]
        self.assertTrue((self.site / secret / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
