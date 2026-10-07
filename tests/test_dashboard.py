"""Checks for the dashboard's file and folder actions (dashboard.js), wherever the page runs: on your
Mac, from another device through a platform (platform.json says "remote": true), as a public copy of
the platform ("public": true), from disk, and as the phone site. From another device nothing may open
on the Mac's screen; a public copy has no files and no Sync now.

    python3 -m unittest discover tests

The behaviour checks run dashboard.js's own code under Node when Node is installed, and are skipped
otherwise; the source checks always run.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
JS = (REPO / "dashboard.js").read_text(encoding="utf-8")
START, END = "// ---- files and folders ----", "// ---- end of files and folders ----"
SYNC_START, SYNC_END = "// ---- sync now ----", "// ---- end of sync now ----"
NODE = shutil.which("node")

PDF = "/Users/me/School/15-122/Assignments/hw3/handout.pdf"
ZIP = "/Users/me/School/15-122/Assignments/hw3/starter.zip"
ODD = '/Users/me/School/Notes/A "b" & <c>.docx'
FOLDER = "/Users/me/School/15-122/Assignments/hw3"
# As sync.py shares a path with the hosted copy (public_copy): from ~, with no user name.
SHARED = "~/School/15-122/Assignments/hw3"
# Where the page runs: (LIVE, REMOTE, LOCAL_FILES). A public copy is remote without LIVE.
MODES = {"mac": [True, False, False], "remote": [True, True, False], "public": [False, True, False],
         "disk": [False, False, True], "phone": [False, False, False]}


def block():
    """dashboard.js's files-and-folders section, which depends only on esc and the three modes."""
    start, end = JS.index(START), JS.index(END)
    return JS[start:end]


def esc_source():
    return re.search(r"^const esc = .*$", JS, re.M).group(0)


def run_node(script):
    out = subprocess.run([NODE, "-"], input=script, capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


class SourceTest(unittest.TestCase):
    def test_only_the_files_section_makes_open_on_mac_links(self):
        # Every link that asks the Mac to open something (data-open, sent to api/open) is made in one
        # place, which knows whether the page is on another device.
        start, end = JS.index(START), JS.index(END)
        outside = JS[:start] + JS[end:]
        self.assertNotIn("data-open=", outside)
        self.assertNotIn("api/reveal", JS)
        self.assertEqual(block().count("data-open="), 1)

    def test_the_open_click_does_nothing_from_another_device(self):
        self.assertRegex(JS, r"if \(op\) \{ e\.preventDefault\(\); if \(REMOTE\) return; return api\('api/open'")

    def test_remote_and_public_come_from_platform_json_and_unknown_counts_as_remote(self):
        self.assertIn("fetch('platform.json', {cache: 'no-store'}).then(platformMode).catch(() => ({remote: true, public: false}))", JS)
        # Set with LIVE, before the page is drawn with the server's features. A public copy serves no
        # files (LIVE stays false); everywhere else LIVE is true, as before.
        self.assertRegex(JS, r"Promise\.all\(\[getJson\('api/marks'\), where\]\)\.then\(\(\[m, at\]\) => \{\s*"
                             r"marks = m;\s*REMOTE = at\.remote;\s*PUBLIC = at\.public;\s*LIVE = !PUBLIC;\s*WRITE = 'local';\s*"
                             r"enableServerFeatures\(\);")
        # Set nowhere else (besides their declarations).
        self.assertEqual(len(re.findall(r"^\s+PUBLIC = ", JS, re.M)), 1)
        self.assertEqual(len(re.findall(r"^\s+LIVE = ", JS, re.M)), 1)

    def test_data_without_a_sync_time_says_so(self):
        # A hosted copy gives data with no generated_at until the Mac's first sync has reached it:
        # "Not synced yet" and a note, instead of a sync time from 1970.
        self.assertIn("$('#sync').textContent = D.generated_at ? 'Synced ' + ago(D.generated_at) : 'Not synced yet';", JS)
        self.assertIn("const none = D.generated_at ? '' : '<div class=\"banner\">No assignments yet: your Mac sends them with its next sync.</div>';", JS)

    def test_folder_text_and_download_mark_styles(self):
        html = (REPO / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn(".where{color:var(--muted);font-size:13px;overflow-wrap:anywhere;min-width:0}", html)
        # The arrow is decoration: screen readers get the tooltip, not "down arrow".
        self.assertIn('a.dl::after{content:"\\2193";content:"\\2193" / "";', html)


@unittest.skipUnless(NODE, "Node is not installed")
class BehaviourTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = f"""
{esc_source()}
let LIVE, REMOTE, LOCAL_FILES;
{block()}
const out = {{}};
for (const [name, mode] of Object.entries({json.dumps(MODES)})) {{
  [LIVE, REMOTE, LOCAL_FILES] = mode;
  out[name] = {{}};
  for (const p of {json.dumps([PDF, ZIP, ODD, FOLDER, SHARED])})
    out[name][p] = {{file: fileAttrs(p), linked: linked('x', p), folder: folderAttrs(p), folderLink: folderLink(p),
                    button: folderLink(p, 'btn'), instructions: instructionsAttrs(p)}};
}}
const answer = (status, body) => ({{status, json: async () => {{ if (body instanceof Error) throw body; return body; }}}});
const apps = [{{id: 'quant', name: 'QuantPrep', href: '/'}}, {{id: 'school', name: 'School', href: '/school/'}}];
Promise.all([
  platformMode(answer(200, {{apps, remote: true}})),
  platformMode(answer(200, {{apps}})),
  platformMode(answer(200, {{apps, remote: 'true'}})),
  platformMode(answer(204)),
  platformMode(answer(404)),
  platformMode(answer(500)),
  platformMode(answer(502)),
  platformMode(answer(200, new Error('not JSON'))).then(() => 'resolved', () => 'rejected'),
  platformMode(answer(200, {{apps, public: true}})),
  platformMode(answer(200, {{apps, public: true, remote: false}})),
  platformMode(answer(200, {{apps, public: 'true'}})),
  platformMode(answer(200, null)),
]).then(where => console.log(JSON.stringify({{...out, where}})));
"""
        cls.out = run_node(script)

    def test_on_the_mac_files_and_folders_open_there(self):
        mac = self.out["mac"]
        self.assertEqual(mac[PDF]["file"], 'href="file/handout.pdf?p=%2FUsers%2Fme%2FSchool%2F15-122%2FAssignments%2Fhw3%2Fhandout.pdf" target="_blank"')
        self.assertEqual(mac[ZIP]["file"], f'href="#" data-open="{ZIP}"')
        self.assertEqual(mac[FOLDER]["folder"], f'href="#" data-open="{FOLDER}"')
        self.assertEqual(mac[FOLDER]["button"], f'<a class="btn" href="#" data-open="{FOLDER}">Open folder</a>')
        self.assertEqual(mac[FOLDER]["instructions"], f'href="#" data-open="{FOLDER}"')

    def test_from_another_device_nothing_opens_on_the_mac(self):
        remote = self.out["remote"]
        self.assertNotIn("data-open", json.dumps(remote))
        # A file the browser shows opens in a tab, as on the Mac.
        self.assertEqual(remote[PDF]["file"], self.out["mac"][PDF]["file"])
        # Any other file downloads, under its own name, and says so before the tap (a small arrow
        # drawn by the dl class, and a tooltip).
        marked = ' class="dl" title="Downloads to this device"'
        self.assertEqual(remote[ZIP]["file"], 'href="file/starter.zip?p=%2FUsers%2Fme%2FSchool%2F15-122%2FAssignments%2Fhw3%2Fstarter.zip" download="starter.zip"' + marked)
        self.assertEqual(remote[ODD]["file"], 'href="file/A%20%22b%22%20%26%20%3Cc%3E.docx?p=%2FUsers%2Fme%2FSchool%2FNotes%2FA%20%22b%22%20%26%20%3Cc%3E.docx" download="A &quot;b&quot; &amp; &lt;c&gt;.docx"' + marked)
        self.assertTrue(remote[ZIP]["linked"].startswith('<a href="file/starter.zip?'))
        self.assertTrue(remote[ZIP]["linked"].endswith(marked + '>x</a>'))
        # Only downloads carry the mark: not a file that opens in a tab, and nothing on the Mac.
        self.assertNotIn('class="dl"', remote[PDF]["file"])
        self.assertNotIn('class="dl"', json.dumps(self.out["mac"]))
        # A folder is named, not opened.
        self.assertIsNone(remote[FOLDER]["folder"])
        self.assertEqual(remote[FOLDER]["folderLink"], '<span class="where">On your Mac: ~/School/15-122/Assignments/hw3</span>')
        self.assertEqual(remote[FOLDER]["button"], remote[FOLDER]["folderLink"])
        self.assertEqual(remote[ODD]["folderLink"], '<span class="where">On your Mac: ~/School/Notes/A &quot;b&quot; &amp; &lt;c&gt;.docx</span>')
        # The saved instructions page would open on the Mac; the drawer shows the instructions.
        self.assertIsNone(remote[FOLDER]["instructions"])

    def test_from_disk_and_on_the_phone_site_as_before(self):
        disk, phone = self.out["disk"], self.out["phone"]
        self.assertEqual(disk[ZIP]["file"], 'href="file:///Users/me/School/15-122/Assignments/hw3/starter.zip"')
        self.assertEqual(disk[FOLDER]["folderLink"], '<a href="file:///Users/me/School/15-122/Assignments/hw3">Open folder</a>')
        for p in (PDF, ZIP, FOLDER):
            self.assertIsNone(phone[p]["file"])
            self.assertIsNone(phone[p]["folder"])
            self.assertIsNone(phone[p]["instructions"])
            self.assertEqual(phone[p]["folderLink"], "")
            self.assertTrue(phone[p]["linked"].startswith('<span class="offsite" title="On your Mac: '))

    def test_remote_is_read_from_platform_json_as_before(self):
        # remote: true; no mark; a mark that is not true; SchoolHub's own 204; a 404; errors; and an
        # answer that is not JSON (the page's catch then counts it as remote, not public).
        where = self.out["where"][:8]
        self.assertEqual([w if w == "rejected" else w["remote"] for w in where],
                         [True, False, False, False, False, True, True, "rejected"])
        self.assertEqual([w["public"] for w in where[:7]], [False] * 7)

    def test_public_is_read_from_platform_json(self):
        # public: true (remote too, whatever remote says); a mark that is not true; a body of null.
        self.assertEqual(self.out["where"][8:], [{"remote": True, "public": True}, {"remote": True, "public": True},
                                                 {"remote": False, "public": False}, {"remote": False, "public": False}])

    def test_a_public_copy_names_files_only(self):
        public, phone, remote = self.out["public"], self.out["phone"], self.out["remote"]
        # No link to a file or a folder at all: the public copy has none of them.
        for word in ("data-open", "href", "file/", "file://", "download"):
            self.assertNotIn(word, json.dumps(public))
        for p in (PDF, ZIP, ODD, FOLDER):
            self.assertIsNone(public[p]["file"])
            self.assertIsNone(public[p]["folder"])
            self.assertIsNone(public[p]["instructions"])
            # A file by its name, as on the phone site; a folder named, as from another device.
            self.assertEqual(public[p]["linked"], phone[p]["linked"])
            self.assertEqual(public[p]["folderLink"], remote[p]["folderLink"])
            self.assertEqual(public[p]["button"], remote[p]["button"])
        self.assertEqual(public[FOLDER]["folderLink"], '<span class="where">On your Mac: ~/School/15-122/Assignments/hw3</span>')
        # A shared copy's path is already from ~, and reads the same.
        self.assertEqual(public[SHARED]["folderLink"], public[FOLDER]["folderLink"])
        self.assertNotIn("href", json.dumps(public[SHARED]))


@unittest.skipUnless(NODE, "Node is not installed")
class SyncNowTest(unittest.TestCase):
    """dashboard.js's Sync now, run under Node with the page's elements and requests stood in for."""

    @classmethod
    def setUpClass(cls):
        start, end = JS.index(SYNC_START), JS.index(SYNC_END)
        script = f"""
const els = {{'#syncBtn': {{hidden: true, disabled: false, textContent: 'Sync now', onclick: null}}, '#fab': {{hidden: true}}}};
const $ = s => els[s];
const calls = [];
const getJson = path => {{ calls.push('GET ' + path); return Promise.resolve(path === 'api/tasks' ? {{tasks: {{}}}} : {{running: false}}); }};
const api = path => {{ calls.push('POST ' + path); return Promise.resolve({{}}); }};
const toast = () => {{}}, refreshTasks = () => {{}};
const sessionStorage = {{getItem: () => null, setItem(){{}}, removeItem(){{}}}};
let PUBLIC;
{JS[start:end]}
const out = {{}};
for (const [name, pub] of [['mac', false], ['public', true]]) {{
  PUBLIC = pub;
  calls.length = 0;
  Object.assign(els['#syncBtn'], {{hidden: true, onclick: null}});
  els['#fab'].hidden = true;
  enableServerFeatures();
  out[name] = {{syncShown: !els['#syncBtn'].hidden, syncClick: !!els['#syncBtn'].onclick, fabShown: !els['#fab'].hidden, calls: [...calls]}};
}}
console.log(JSON.stringify(out));
"""
        cls.out = run_node(script)

    def test_on_the_mac_and_from_another_device_as_before(self):
        self.assertEqual(self.out["mac"], {"syncShown": True, "syncClick": True, "fabShown": True,
                                           "calls": ["GET api/tasks", "GET api/sync"]})

    def test_a_public_copy_has_no_sync_now(self):
        # Marks and tasks work (the + button, the tasks); nothing asks for a sync or its state.
        self.assertEqual(self.out["public"], {"syncShown": False, "syncClick": False, "fabShown": True,
                                              "calls": ["GET api/tasks"]})


if __name__ == "__main__":
    unittest.main()
