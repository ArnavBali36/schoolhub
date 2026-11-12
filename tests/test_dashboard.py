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
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
JS = (REPO / "dashboard.js").read_text(encoding="utf-8")
HTML = (REPO / "dashboard.html").read_text(encoding="utf-8")
BAR = (REPO / "bar.js").read_text(encoding="utf-8")
PLANNER = (REPO / "planner.js").read_text(encoding="utf-8")
# planner.js's constants, time helpers and cleaning, which need nothing from the page.
PLAN_START, PLAN_END = "  const MIN_HOUR_PX = 22;", "  // ---- the plan, loaded and saved ----"
SHOWS_START, SHOWS_END = "  // ---- what shows on a date ----", "  // ---- drawing ----"
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

    def test_no_read_only_banner_while_the_page_asks_where_it_is(self):
        # A slow first answer (a cold public site) once showed "Read-only view" on a page that saves.
        self.assertIn("const banner = LIVE || WRITE || PROBING ? '' : LOCAL_FILES", JS)
        self.assertIn("PROBING = !PHONE && !LOCAL_FILES;\nrender();", JS)
        # Asked, answered or not: drawn again without it, so a page that cannot save still says so.
        self.assertRegex(JS, r"\.catch\(\(\) => \{\}\)\.finally\(\(\) => \{\s*PROBING = false;\s*render\(\);\s*showSyncbox\(\);")

    def test_a_task_is_kept_at_the_top_or_in_the_list_as_chosen(self):
        html = (REPO / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn('<input id="tPinned" type="checkbox">', html)
        # A new task starts pinned; an existing one shows its own choice.
        self.assertIn("$('#tPinned').checked = t ? pinnedTask(t) : true;", JS)
        self.assertIn("pinned: $('#tPinned').checked}", JS)
        # Pinned ones go under My tasks whatever their date; the rest go in the list by date.
        self.assertIn("if (pinnedItem(a)) { G['My tasks'].push(a); continue; }", JS)
        # One saved before the choice existed: pinned when it has no date, as it was.
        self.assertIn("const pinnedTask = t => typeof t.pinned === 'boolean' ? t.pinned : !t.due_at;", JS)

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


class PlannerPageTest(unittest.TestCase):
    """The day planner's page (docs/planner.md, section 3): the list on the left, the planner on
    the right or as the Day view, no search, and Show done at the end of the list."""

    def test_search_is_gone(self):
        self.assertNotIn('id="q"', HTML)
        self.assertNotIn("Search assignments", HTML)
        self.assertNotIn("input[type=search]", HTML)
        self.assertNotIn("state.q", JS)
        self.assertNotIn("$('#q')", JS)
        # No key that only focused it.
        self.assertNotIn("e.key === '/'", JS)

    def test_show_done_is_a_quiet_button_at_the_end_of_the_list(self):
        # The toolbar and its checkbox are gone.
        self.assertNotIn('id="showDone"', HTML)
        self.assertNotIn('class="toolbar"', HTML)
        self.assertNotIn(".toolbar", BAR)
        # "Show 8 done" or "Hide done", after the lists of both views, in the muted color.
        self.assertIn("`<button type=\"button\" class=\"done-toggle\" id=\"doneToggle\">${state.showDone ? 'Hide done' : `Show ${hidden} done`}</button>`", JS)
        self.assertIn("+ doneToggle(all);", JS)
        self.assertIn("${doneToggle(all.filter(a => a.course === cur))}", JS)
        self.assertRegex(HTML, r"\.done-toggle\{[^}]*color:var\(--muted\)")
        # Still remembered.
        self.assertIn("if (e.target.closest('#doneToggle')) { state.showDone = !state.showDone; mem.set('showDone', state.showDone); return render(); }", JS)

    def test_planner_js_loads_last(self):
        scripts = re.findall(r'<script src="([^"]+)"></script>', HTML)
        self.assertEqual(scripts[-2:], ["dashboard.js", "planner.js"])
        # Its dialogs are in the page, and nothing in it runs inline.
        for dialog in ('id="blockDialog"', 'id="weekDialog"'):
            self.assertIn(dialog, HTML)
        self.assertNotRegex(PLANNER, r"\bon(click|change|submit)=\"")

    def test_two_columns_from_1100_px_and_the_day_view_below(self):
        # The page column widens to 1440 px beside the planner; the bar keeps QuantPrep's 1040 px.
        self.assertIn('.page:is([data-plan="on"],[data-plan="unknown"]){max-width:calc(1440px + 2 * var(--gutter))}', HTML)
        self.assertIn("--content:1040px", HTML)
        self.assertIn(".bar{display:flex;align-items:center;gap:20px;max-width:calc(var(--content) + 2 * var(--gutter))", HTML)
        self.assertIn("grid-template-columns:minmax(0,3fr) minmax(0,2fr)", HTML)
        self.assertRegex(HTML, r"\.planner\{position:sticky;top:calc\(var\(--bar-height\) \+ 32px\);height:calc\(100vh")
        # Day is offered only below 1100 px, and starts hidden until the planner is known to be there.
        self.assertIn('<button type="button" data-view="day" hidden>Day</button>', HTML)
        self.assertIn('@media (min-width:1100px){', HTML)
        self.assertIn('.views [data-view="day"]{display:none}', HTML)
        self.assertIn("const WIDE = matchMedia('(min-width: 1100px)');", JS)
        self.assertIn("const shownView = () => state.view === 'day' && (WIDE.matches || plannerState === 'off') ? 'upcoming' : state.view;", JS)
        self.assertIn("const VIEWS = ['upcoming', 'courses', 'day'];", JS)
        # bar.js lights a remembered Day only where it is offered.
        self.assertIn("const dayOffered = !PHONE && !LOCAL_FILES && !(typeof matchMedia === 'function' && matchMedia('(min-width: 1100px)').matches);", BAR)
        self.assertIn("view = kept === 'courses' ? 'courses' : kept === 'day' && dayOffered ? 'day' : 'upcoming';", BAR)
        # The sync status's narrow-screen place is a row of its own now.
        self.assertIn('<div class="syncrow" id="syncrow"></div>', HTML)
        self.assertIn("row = $('#syncrow')", BAR)

    def test_planner_namespace_and_hooks(self):
        self.assertIn("window.SchoolHub = {", JS)
        self.assertIn("let plannerState = PHONE || LOCAL_FILES ? 'off' : 'unknown';", JS)
        # Told when the list is drawn, when marks and tasks are fetched again, and once the page knows
        # where it saves (kept, for a planner.js that loads after the answer).
        self.assertIn("  refocus(main, key);\n  emit('render');\n}", JS)
        self.assertRegex(JS, r"catch \{\}\n  emit\('reload'\);\n\}")
        self.assertRegex(JS, r"\.finally\(\(\) => \{\s*PROBING = false;\s*render\(\);\s*showSyncbox\(\);\s*emit\('ready'\);")
        self.assertIn("if (PHONE || LOCAL_FILES) { showSyncbox(); emit('ready'); }", JS)
        self.assertIn("on(name, fn){ hooks[name].push(fn); if (name === 'ready' && readied) fn(); },", JS)
        # A server that does not serve planner.js: no planner rather than an empty Day view.
        self.assertIn("if (!window.SchoolHub.plannerLoaded && plannerState === 'unknown') window.SchoolHub.setPlanner('off');", JS)
        # Rows drag and the drawer offers Plan it only with the planner, and only for open items.
        self.assertIn("const draggable = a => plannerState === 'on' && !isDone(a);", JS)
        self.assertIn("${plannerState === 'on' && !isDone(a) ? `<button type=\"button\" class=\"btn\" data-plan-it=", JS)

    def test_planner_hides_where_it_cannot_save(self):
        # Only through SchoolHub's own server (the Mac or the public site), never the phone site's
        # store or a file on disk, and not with a server from before the planner (404).
        self.assertIn("if (m.PHONE || m.LOCAL_FILES || m.WRITE !== 'local') return SH.setPlanner('off');", PLANNER)
        self.assertIn("if (r?.status === 404 && !plan) return SH.setPlanner('off');", PLANNER)
        self.assertIn('.page:not([data-plan="on"],[data-plan="unknown"]) .planner{display:none}', HTML)

    def test_planner_saves_like_tasks(self):
        # Relative, so it works under /school/, and through dashboard.js's api (the X-SchoolHub header).
        self.assertIn("fetch(`api/plan?from=${from}&to=${to}`, {cache: 'no-store'})", PLANNER)
        self.assertIn("SH.api('api/plan', {key, value})", PLANNER)
        self.assertNotRegex(PLANNER, r"""['"`]/api/""")
        self.assertIn('SH.toast("Couldn\'t save the plan")', PLANNER)
        # The shown date ±7 days.
        self.assertIn("const from = addDays(center, -7), to = addDays(center, 7)", PLANNER)

    def test_planner_scale_and_keys(self):
        # The fixed 48 px an hour is gone: the hour is fitted to the room (docs/planner.md, "the whole
        # day always in view"), never under 22 px, blocks at least 20 px, words under 70 px a column.
        self.assertNotIn("HOUR_PX = 48", PLANNER)
        self.assertNotRegex(PLANNER, r"\bHOUR_PX\b")
        self.assertIn("const MIN_HOUR_PX = 22;", PLANNER)
        self.assertIn("const DENSE_HOUR_PX = 30;", PLANNER)
        self.assertIn("const MIN_BLOCK_PX = 20;", PLANNER)
        self.assertIn("const NARROW_COL_PX = 70;", PLANNER)
        self.assertIn("const SNAP = 15;", PLANNER)
        self.assertIn("const CLICK_PX = 4;", PLANNER)
        self.assertIn("const DEFAULT_SETTINGS = {day_start: 5, day_end: 24};", PLANNER)
        self.assertIn("const DEFAULT_MEALS = {breakfast: ['11:00', '12:00'], lunch: ['16:00', '17:00'], dinner: ['18:00', '19:00']};", PLANNER)
        # [ and ] only when not typing and nothing covers the planner; Esc puts a drag back.
        self.assertIn("if (SH.typingIn(document.activeElement) || document.querySelector('dialog[open]') || SH.drawerOpen()) return;", PLANNER)
        self.assertIn("if (drag && e.key === 'Escape') { e.preventDefault(); return endDrag(true); }", PLANNER)
        # A touch screen keeps vertical scrolling on empty time; a drag starts after a long press.
        self.assertIn("touch-action:pan-y", HTML)
        self.assertIn("grid.addEventListener('touchmove', e => { if (drag?.armed) e.preventDefault(); }, {passive: false});", PLANNER)

    def test_the_whole_day_fits_the_planner(self):
        # The hour's height comes from the room under the header, again on resize (the window, the
        # phone's visible area, the strip or the header taking another line) and with the settings.
        self.assertIn("const room = els.scroll.clientHeight;", PLANNER)
        self.assertIn("({px: hourPx, scroll: scrolling} = fitHour(", PLANNER)
        self.assertIn("if (typeof ResizeObserver === 'function') new ResizeObserver(refit).observe(els.scroll);", PLANNER)
        self.assertIn("window.visualViewport?.addEventListener('resize', refit);", PLANNER)
        self.assertIn("if (hours) { save('settings', {day_start: ds, day_end: de}); scrolledFor = null; render(); }", PLANNER)
        # It scrolls only when the hour would be under 22 px, and then to now; fitted, it stays at the top.
        self.assertIn("if (!scrolling) { el.scrollTop = 0; return true; }", PLANNER)
        self.assertIn("if (scrolling !== wasScrolling) scrolledFor = null;", PLANNER)
        # The grid's lines follow the hour (--hour); under 30 px the half-hour lines go.
        self.assertIn("0 0/100% var(--hour,48px)", HTML)
        self.assertIn("0 calc(var(--hour,48px) / 2)/100% var(--hour,48px)", HTML)
        self.assertIn(".pgrid.dense::before{display:none}", HTML)
        self.assertNotIn("100% 48px", HTML)
        self.assertNotIn("margin:12px 0 76px", HTML)
        # The + button never covers the end of the day: beside the planner it moves into the list's
        # column, the Day view leaves it out, and where it would still cover the timeline room is left.
        self.assertIn('.page:is([data-plan="on"],[data-plan="unknown"]) ~ .fab{', HTML)
        self.assertIn('.page[data-view="day"] ~ .fab{display:none}', HTML)
        self.assertIn("padBottom = fab ? fab + 4 : 7;", PLANNER)
        # The Day view fills the window under the bar, and the strip keeps to one line.
        self.assertIn('.page[data-view="day"] .planner{flex:1;min-height:360px}', HTML)
        self.assertRegex(HTML, r"\.pstrip\{display:flex;[^}]*overflow-x:auto")
        self.assertNotRegex(HTML, r"\.pstrip\{[^}]*flex-wrap:wrap")

    def test_every_block_stays_visible_and_readable(self):
        # Short blocks are one line ("Lunch · Chipotle · 4–5 PM"), a narrow column shows the kind's
        # initial with its name in the label, and a block cut by the hours shown is marked so.
        self.assertIn("const INITIAL = {meal: 'M', deep: 'D', social: 'S', other: 'B'};", PLANNER)
        self.assertIn("body = `<span class=\"pb-ini\">${INITIAL[e.kind]}</span>`;", PLANNER)
        self.assertIn('aria-label="${esc(spoken(e))}"${tip}', PLANNER)
        self.assertIn("e.cutTop && 'cut-top', e.cutBottom && 'cut-bottom'", PLANNER)
        self.assertIn(".pblock.cut-top{border-top:2px dashed var(--pb-edge)", HTML)
        self.assertIn('<span class="pb-n">+${rest}</span>', PLANNER)
        # Hour labels thin out under 30 px an hour.
        self.assertIn(".filter(i => (s.day_start + i) % step === 0)", PLANNER)
        # Flags keep a lane of their own, so none covers a block; the name shows on hover or focus.
        self.assertIn("const lane = timed.length ? FLAG_LANE_PX : 0;", PLANNER)
        self.assertIn("left:calc((100% - var(--lane, 0px)) * ${left / 100} + 2px)", PLANNER)
        self.assertIn(".pflag-wrap:is(:hover,:focus-within) .pf-name{display:inline}", HTML)

    def test_a_click_on_a_block_opens_its_details(self):
        # A click (under 4 px of movement) shows the details, not the editor; the keyboard's click and
        # a chip in the strip too. A block just made still opens the editor at once.
        self.assertIn("if (!d.moved) return openDetails(d.entry, d.el);", PLANNER)
        self.assertIn("return entry && openDetails(entry, open.closest('.pblock') || open);", PLANNER)
        self.assertIn("return openEditor(shown, null, {start, end});", PLANNER)
        self.assertNotIn("if (!d.moved) return openEditor(shown, d.entry);", PLANNER)
        # The card: beside the block on wide screens, a bottom sheet on narrow ones.
        self.assertIn('<dialog class="pdetail" id="planDetail" aria-labelledby="pdTitle"></dialog>', HTML)
        self.assertIn("const SHEET = matchMedia('(max-width: 780px)');", PLANNER)
        self.assertIn("if (SHEET.matches) card.showModal(); else card.show();", PLANNER)
        self.assertIn("dialog.pdetail.sheet{inset:auto 0 0 0;", HTML)
        # What it shows: the time and length, repeats or changed, the items with their checkboxes, and
        # for work its course, due date, status and a link to its drawer.
        self.assertIn("${esc(range(e.start, e.end))} · ${esc(duration(e.end - e.start))}", PLANNER)
        self.assertIn("if (e.repeat) notes.push(`Repeats every ${wdN}`);", PLANNER)
        self.assertIn("for ${thisDay(shown)} only`);", PLANNER)
        self.assertIn('data-pd-item="${esc(it.id)}"', PLANNER)
        self.assertIn('data-pd-open="${esc(a.id)}"', PLANNER)
        self.assertIn("SH.openDrawer(open.dataset.pdOpen, e.detail === 0);", PLANNER)
        # Its buttons: Edit (the editor), Delete / Skip today / No lunch today, Close.
        self.assertIn("if (t.closest('[data-pd-edit]')) { closeDetails(); return openEditor(shown, entry); }", PLANNER)
        self.assertIn("if (t.closest('[data-pd-del]')) {", PLANNER)
        self.assertIn("        const back = neighbourSel(entry.ref);\n        closeDetails(false);\n        removeEntry(shown, entry);\n        return refocus(back);", PLANNER)
        self.assertIn("const removeLabel = (e, date) => e.kind === 'meal' ? `No ${e.meal} ${thisDay(date)}` : e.repeat ? `Skip ${thisDay(date)}` : 'Delete';", PLANNER)
        # Esc and a click outside close it; focus goes into it and back to the block.
        self.assertIn("if (det && e.key === 'Escape' && !card.matches(':modal') && !SH.drawerOpen()) { e.preventDefault(); return closeDetails(); }", PLANNER)
        self.assertIn("card.addEventListener('cancel', e => { e.preventDefault(); closeDetails(); });", PLANNER)
        self.assertIn("if (!det || card.matches(':modal') || card.contains(e.target)) return;", PLANNER)
        self.assertIn("    card.focus();\n", PLANNER)
        self.assertIn("if (restore) root.querySelector(back)?.focus();", PLANNER)
        # Assignment flags still open the drawer.
        self.assertIn("if (due) return SH.openDrawer(due.dataset.planDue, e.detail === 0);", PLANNER)

    def test_review_fixes_of_2026_11_08(self):
        # Resize and move go by the pointer's change since the press, and only the change is kept
        # within the hours: a handle drawn away from its time never jumps, a cut block never snaps in.
        self.assertIn("const delta = m - d.anchor;", PLANNER)
        self.assertIn("Math.max(Math.min(0, lo - e.start), Math.min(Math.max(0, hi - e.end), snap(e.start + delta) - e.start))", PLANNER)
        self.assertIn("d.start = Math.max(Math.min(lo, e.start), Math.min(e.end - MIN_LEN, snap(e.start + delta)));", PLANNER)
        self.assertIn("d.end = Math.min(Math.max(hi, e.end), Math.max(e.start + MIN_LEN, snap(e.end + delta)));", PLANNER)
        self.assertIn("else SH.toast(`Moved “${entry.title}” to ${range(start, end)}`, undo);", PLANNER)
        # The strip is set before the hour is measured, and the sizes are recorded where they are read.
        self.assertLess(PLANNER.index("els.strip.hidden = !chips.length;"), PLANNER.index("    measure();\n    if (scrolling !== wasScrolling)"))
        self.assertIn("    fitted = sizeKey();\n    return true;", PLANNER)
        # A repeating block skipped for the day can come back from the strip.
        self.assertIn('data-prepeat-on="${esc(e.id)}"', PLANNER)
        self.assertIn("editDay(shown, v => { delete holder(v, ref).skip; });", PLANNER)
        # Plan it says when the plan could not load, and waits for saves before loading.
        self.assertIn("if (!plan) { SH.toast(\"Couldn't load the plan\"); loadFailed = false; render(); return load(shown); }", PLANNER)
        self.assertIn("while (pending) await chain;", PLANNER)
        # Focus never falls to <body>: the editor's and the weekly form's close, Use this time.
        self.assertIn("F.blockDialog.addEventListener('close', () => { if (focusLost() || F.blockDialog.contains(document.activeElement)) refocus(ed?.back); });", PLANNER)
        self.assertIn("F.weekDialog.addEventListener('close', () => { if (focusLost() || F.weekDialog.contains(document.activeElement)) refocus(wk?.back, els.week); });", PLANNER)
        self.assertIn("F.bChanged.hidden = true;\n    F.bStart.focus();", PLANNER)
        # The card beside a block closes when focus leaves it, and the page's keys ignore it.
        self.assertIn("if (det && !card.matches(':modal') && !card.contains(e.target)) closeDetails(false);", PLANNER)
        self.assertIn("const dialogOpen = () => [...document.querySelectorAll('dialog[open]')].some(d => d.matches(':modal'));", JS)
        # One-line blocks write the kind (a tag, else its initial), and the title gives way to the time.
        self.assertIn('<span class="pb-ki">${INITIAL[e.kind]}</span>', PLANNER)
        self.assertIn(".pb-head .pb-title{flex:0 1000 auto;min-width:2.5em}", HTML)
        self.assertIn(".pb-head .pb-time{flex:0 1 auto;min-width:0}", HTML)
        # Dark: the card's overdue status and links keep 4.5:1 on the page's surface.
        self.assertIn(':root:is([data-theme="dark"],[data-theme="red"]) dialog.pdetail{background:var(--surface)}', HTML)
        # A meal's place set for one day says so.
        self.assertIn("else if (meal && e.placeChanged) notes.push(`Place changed for ${thisDay(shown)} only`);", PLANNER)

    def test_block_kinds_use_the_theme_tokens(self):
        for kind, fill, edge in (("meal", "--warn-soft", "--warn"), ("deep", "--accent-soft", "--accent"),
                                 ("social", "--good-soft", "--good"), ("other", "--surface-3", "--border-strong")):
            self.assertIn(f".k-{kind}{{--pb-fill:var({fill});--pb-edge:var({edge})}}", HTML)
        self.assertIn("border-top:2px solid var(--bad)", HTML)  # the now line


def _lum(hex6):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex6[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(a, b):
    x, y = sorted((_lum(a), _lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


class NightThemeTest(unittest.TestCase):
    """Night (2026-11-11): the system's colors, and from 9 PM to midnight every color a shade of red
    with no blue in it, still readable."""

    RED = re.search(r':root\[data-theme="red"\]\{(.*?)\n\}', HTML, re.S).group(1)
    TOKENS = dict(re.findall(r"--([\w-]+):#([0-9a-f]{6})", RED))

    def test_every_color_has_no_blue(self):
        self.assertGreater(len(self.TOKENS), 30)
        for name, value in self.TOKENS.items():
            self.assertEqual(value[4:], "00", name)
        # Colors written another way (rgb()) carry no blue either.
        for r, g, b in re.findall(r"rgb\((\d+) (\d+) (\d+)", self.RED):
            self.assertEqual(b, "0")

    def test_text_stays_readable(self):
        # Every text color on every surface and fill (an overdue pill is --bad on --bad-soft).
        fills = ["bg", "surface", "surface-2", "surface-3", "surface-raised", "accent-soft", "good-soft", "bad-soft", "warn-soft"]
        for text in ["text", "muted", "faint", "accent", "good", "bad", "warn"]:
            for fill in fills:
                self.assertGreaterEqual(_contrast(self.TOKENS[text], self.TOKENS[fill]), 4.5, (text, fill))
        self.assertGreaterEqual(_contrast(self.TOKENS["on-accent"], self.TOKENS["accent"]), 4.5)
        for fill in ["bg", "surface", "surface-2", "surface-3"]:
            self.assertGreaterEqual(_contrast(self.TOKENS["border-input"], self.TOKENS[fill]), 3)
        for n in [*range(1, 11), "personal"]:
            for fill in ["bg", "surface", "surface-2", "surface-3", "surface-raised"]:
                self.assertGreaterEqual(_contrast(self.TOKENS[f"course-{n}"], self.TOKENS[fill]), 3, (n, fill))

    def test_pictures_and_icon_turn_red(self):
        self.assertIn('<filter id="redshift"', HTML)
        self.assertIn('0 0 0 0 0  0 0 0 1 0"/>', HTML)  # no blue out
        self.assertIn(':root[data-theme="red"] :is(img,video,canvas,iframe,object,embed,picture,.emo,.doc svg){filter:url(#redshift)}', HTML)
        self.assertIn('markEmoji(main);', JS)
        self.assertIn('SH.markEmoji?.(grid);', PLANNER)
        self.assertNotIn('MutationObserver', JS)
        icon = re.search(r"const ICON_RED = .*$", BAR, re.M).group(0)
        for color in re.findall(r"#([0-9a-f]{6})", icon):
            self.assertEqual(color[4:], "00")

    def test_controls_and_dots_turn_red(self):
        # Radio buttons follow the theme as ticks do; off, both are drawn in Night's reds, not grey.
        self.assertIn("input:is([type=checkbox],[type=radio]){accent-color:var(--accent)}", HTML)
        self.assertIn(':root[data-theme="red"] input:is([type=checkbox],[type=radio]){appearance:none;', HTML)
        # The date and time fields' icons sit in the control's shadow tree: the filter is written out.
        picker = re.search(r':root\[data-theme="red"\] ::-webkit-calendar-picker-indicator\{filter:url\("data:image/svg\+xml,(.*?)#r"\)\}', HTML).group(1)
        self.assertIn("values='0.2126 0.7152 0.0722 0 0 0.04 0.13 0.01 0 0 0 0 0 0 0 0 0 0 1 0'", picker)
        # The browser's blue highlight on the part of a date or time being typed: no blue comes out.
        self.assertIn(':root[data-theme="red"] :is(input:not([type=checkbox],[type=radio]),textarea,select){filter:url(#redkeep)}', HTML)
        self.assertIn('<filter id="redkeep" color-interpolation-filters="sRGB"><feColorMatrix type="matrix" values="1 0 1 0 0  0 0.5 0 0 0  0 0 0 0 0  0 0 0 1 0"/>', HTML)
        self.assertNotRegex(HTML, r":is\([^)]*::")  # a pseudo-element inside :is() matches nothing
        # A course's set color gives way to the theme's own course red.
        self.assertIn(':root[data-theme="red"] .dot{background:var(--dot-theme)}', HTML)
        self.assertIn('style="--dot:${esc(c.color)};--dot-theme:${esc(c.slot || c.color)}"', JS)
        self.assertIn(".doc hr{border:0;border-top:1px solid var(--border-strong)", HTML)

    def _mark(self, cases):
        """Runs dashboard.js's markEmoji on a small stand-in for the page: each case is a list of text
        nodes, each in its own <span>, and the result is each node as text with [emoji] for a span."""
        start = JS.index("const EMOJI_ONE = ")
        end = JS.index("\n}\n", JS.index("function markEmoji")) + 3
        return run_node(JS[start:end] + """
class El {
  constructor(tag, kids = []){ this.tagName = tag; this.kids = []; this.className = ''; this.isConnected = false; for (const k of kids) this.append(k); }
  append(...xs){ for (let x of xs) { if (typeof x === 'string') x = new Text(x); if (x.frag) { for (const k of x.kids) this.append(k); continue; } x.parentElement = this; this.kids.push(x); } }
  closest(){ return this.className === 'emo' ? this : null; }
  set textContent(t){ this.kids = []; this.append(t); }
  show(){ return this.kids.map(k => k instanceof Text ? k.data : k.className === 'emo' ? `[${k.show()}]` : k.show()).join(''); }
}
class Text { constructor(d){ this.data = d; } replaceWith(x){ const p = this.parentElement, i = p.kids.indexOf(this); const tmp = new El('X'); tmp.append(x); for (const k of tmp.kids) k.parentElement = p; p.kids.splice(i, 1, ...tmp.kids); } }
const texts = el => el.kids.flatMap(k => k instanceof Text ? [k] : texts(k));
globalThis.NodeFilter = {SHOW_TEXT: 4};
globalThis.document = {
  createTreeWalker(root){ const all = texts(root); let i = 0; return {nextNode: () => all[i++] || null}; },
  createDocumentFragment(){ const f = new El('#fragment'); f.frag = true; return f; },
  createElement: tag => new El(tag.toUpperCase()),
};
const cases = %s;
console.log(JSON.stringify(cases.map(nodes => {
  const root = new El('DIV', nodes.map(t => new El('SPAN', [t])));
  markEmoji(root);
  return root.kids.map(k => k.show());
})));
""" % json.dumps(cases))

    @unittest.skipUnless(NODE, "Node is not installed")
    def test_every_emoji_is_marked(self):
        # The last text drawn ending in an emoji once left a global regex part way along, and every
        # emoji before that point stayed in color.
        out = self._mark([
            ["📗 Biology lab", "Good luck! 🍀"],
            ["a ✅"],
            ["Study 📗", "Hang out 🎉", "· 11/11 Research Proposal Essay due 📗📙"],
            ["Flag 🇺🇸 key 1️⃣ #️⃣", "🏴󠁧󠁢󠁥󠁮󠁧󠁿 👍🏽 👨‍👩‍👧 🏳️‍🌈 ❤️"],
            # Symbols shown as text stay text, in the theme's color.
            ["Open on Canvas ↗", "© ™ ✔ ▶ ‼ ℹ ❤︎ 12 #3"],
        ])
        self.assertEqual(out, [
            ["[📗] Biology lab", "Good luck! [🍀]"],
            ["a [✅]"],
            ["Study [📗]", "Hang out [🎉]", "· 11/11 Research Proposal Essay due [📗📙]"],
            ["Flag [🇺🇸] key [1️⃣] [#️⃣]", "[🏴󠁧󠁢󠁥󠁮󠁧󠁿] [👍🏽] [👨‍👩‍👧] [🏳️‍🌈] [❤️]"],
            ["Open on Canvas ↗", "© ™ ✔ ▶ ‼ ℹ ❤︎ 12 #3"],
        ])
        # Whether a text has emoji is asked of a regex that keeps no place between calls.
        self.assertIsNone(re.search(r"(?<!HAS_)EMOJI\.test\(", JS))
        self.assertIn("const HAS_EMOJI = new RegExp(EMOJI_ONE, 'u');", JS)

    @unittest.skipUnless(NODE, "Node is not installed")
    def test_night_is_a_choice_and_turns_red_on_time(self):
        self.assertIn("const THEME_CHOICES = ['system', 'light', 'dark', 'night'];", BAR)
        init = (REPO / "theme-init.js").read_text(encoding="utf-8")
        out = run_node("""
const init = %s;
const results = {};
for (const [choice, hour, dark] of [['night', 21, false], ['night', 23, true], ['night', 20, true], ['night', 0, false], ['night', 4, false], ['system', 22, true], ['dark', 22, false], ['light', 23, true]]) {
  const attrs = {};
  const RealDate = Date;
  globalThis.Date = class extends RealDate { getHours(){ return hour; } };
  globalThis.localStorage = {getItem: () => choice};
  globalThis.matchMedia = () => ({matches: dark});
  globalThis.document = {documentElement: {setAttribute: (k, v) => { attrs[k] = v; }}};
  new Function(init)();
  globalThis.Date = RealDate;
  results[`${choice} ${hour} ${dark}`] = attrs['data-theme'];
}
console.log(JSON.stringify(results));
""" % json.dumps(init))
        self.assertEqual(out, {
            "night 21 false": "red", "night 23 true": "red", "night 20 true": "dark", "night 0 false": "light",
            "night 4 false": "light", "system 22 true": "dark", "dark 22 false": "dark", "light 23 true": "light",
        })
        # bar.js keeps the same hours, and looks again while the page stays open.
        self.assertIn("const NIGHT_FROM = 21, NIGHT_TO = 24;", BAR)
        self.assertIn("setInterval(() => { if (themeChoice() === 'night') applyTheme(); }, 30000);", BAR)


@unittest.skipUnless(NODE, "Node is not installed")
class PlannerCleaningTest(unittest.TestCase):
    """planner.js cleans every value by the server's rules before saving it: run on every value in
    tests/plan_vectors.json (good and bad alike), its result must always pass plan.py."""

    @classmethod
    def setUpClass(cls):
        vectors = json.loads((REPO / "tests" / "plan_vectors.json").read_text(encoding="utf-8"))
        cls.vectors = [v for v in vectors if isinstance(v.get("key"), str)]
        start, end = PLANNER.index(PLAN_START), PLANNER.index(PLAN_END)
        script = PLANNER[start:end] + f"""
const out = [];
for (const v of {json.dumps(cls.vectors)}) {{
  const kind = v.key.split(':')[0];
  // A date's repeats are kept only for blocks in its week: give it a week with all of them.
  const ids = Object.keys(v.value?.repeats && typeof v.value.repeats === 'object' ? v.value.repeats : {{}});
  const week = cleanWeek({{blocks: ids.map(id => ({{id, type: 'deep', start: '09:00', end: '11:00'}}))}});
  try {{
    out.push({{key: v.key, value: kind === 'settings' ? cleanSettings(v.value) : kind === 'week' ? cleanWeek(v.value) : kind === 'day' ? cleanDay(v.value, week) : null}});
  }} catch (e) {{ out.push({{key: v.key, threw: String(e)}}); }}
}}
console.log(JSON.stringify(out));
"""
        cls.out = run_node(script)

    def test_cleaned_values_always_pass_the_server(self):
        import sys
        sys.path.insert(0, str(REPO))
        import plan
        self.assertGreater(len(self.out), 100)
        for vector, got in zip(self.vectors, self.out):
            with self.subTest(note=vector.get("note"), key=vector["key"]):
                self.assertNotIn("threw", got)
                if not plan.KEY.fullmatch(vector["key"]) or (vector["key"].startswith("day:") and "real date" in str(plan.clean_plan(vector["key"], {})[1])):
                    continue  # a bad key: the page never makes one
                _, error = plan.clean_plan(vector["key"], got["value"])
                self.assertIsNone(error)

    def test_a_good_value_comes_through_as_the_server_cleans_it(self):
        # Where the server takes a value, the page's cleaning gives the same (dates drop what equals
        # their week, which the page compares against the defaults here).
        for vector, got in zip(self.vectors, self.out):
            if vector["ok"] and vector["key"].startswith(("settings", "week:")) and vector["value"] is not None:
                with self.subTest(note=vector.get("note"), key=vector["key"]):
                    self.assertEqual(got["value"], vector["cleaned"])


@unittest.skipUnless(NODE, "Node is not installed")
class PlannerDayTest(unittest.TestCase):
    """What the planner shows on a date: meals (date over week over defaults), the week's repeating
    blocks with the date's changes, the date's own blocks; overlapping blocks side by side."""

    @classmethod
    def setUpClass(cls):
        week_sun = {"meals": {"lunch": {"start": "16:00", "end": "17:00", "place": "Chipotle"}},
                    "blocks": [{"id": "r1aaaaaaaa", "type": "deep", "title": "Deep work", "start": "09:00", "end": "11:00"},
                               {"id": "r2aaaaaaaa", "type": "social", "title": "Lunch run", "start": "13:00", "end": "14:00"}]}
        day = {"meals": {"lunch": {"start": "16:30", "end": "17:30", "items": [{"id": "i1aaaaaaaa", "kind": "own", "text": "Call home", "done": False}]},
                         "dinner": {"off": True}},
               "repeats": {"r1aaaaaaaa": {"start": "09:30", "end": "11:30"}, "r2aaaaaaaa": {"skip": True},
                           "goneaaaaaa": {"start": "08:00", "end": "09:00"}},
               "blocks": [{"id": "b1aaaaaaaa", "type": "other", "title": "Gym", "start": "10:00", "end": "11:00", "items": []}]}
        start, end = PLANNER.index(PLAN_START), PLANNER.index(PLAN_END)
        shows = PLANNER[PLANNER.index(SHOWS_START):PLANNER.index(SHOWS_END)]
        script = PLANNER[start:end] + f"""
const SH = {{items: [], byId: () => null, isDone: () => false}};
let shown = '2026-11-08';
const plan = {{settings: {{day_start: 5, day_end: 24}}, week: {{sun: cleanWeek({json.dumps(week_sun)})}}, days: {{}}}};
plan.days['2026-11-08'] = cleanDay({json.dumps(day)}, plan.week.sun);
const weekOf = wd => plan.week[wd] || cleanWeek(null);
{shows}
const pick = list => Object.fromEntries(list.map(e => [e.ref, {{start: e.start, end: e.end, place: e.place, off: e.off, skip: e.skip, changed: !!e.changed, items: e.items.length}}]));
const today = entriesOn('2026-11-08'), next = entriesOn('2026-11-15'), monday = entriesOn('2026-11-09');
const shownToday = today.filter(e => !e.off && !e.skip && e.start < 720);
layout(shownToday);
console.log(JSON.stringify({{
  stored: plan.days['2026-11-08'], today: pick(today), next: pick(next), monday: pick(monday),
  cols: Object.fromEntries(shownToday.map(e => [e.ref, [e.col, e.cols]])),
  same: cleanDay({{meals: {{lunch: {{start: '16:00', end: '17:00', place: 'Chipotle'}}}}}}, plan.week.sun),
  times: [range(960, 1020), range(660, 720), range(1380, 1440), range(570, 690, ' to '), hourLabel(5), hourLabel(12), hourLabel(24)],
  spoken: spoken(today.find(e => e.ref === 'meal:lunch')),
  placeOnly: (() => {{
    plan.days['2026-11-22'] = cleanDay({{meals: {{lunch: {{place: 'Thai place'}}, dinner: {{place: ''}}}}}}, plan.week.sun);
    const on = entriesOn('2026-11-22'), at = ref => on.find(e => e.ref === ref);
    return [at('meal:lunch').changed, at('meal:lunch').placeChanged, at('meal:dinner').placeChanged, today.find(e => e.ref === 'meal:lunch').placeChanged];
  }})(),
}}));
"""
        cls.out = run_node(script)
        # The pure layout functions (the whole day in view): the hour's height, labels, where each
        # block is drawn and in which form, and the compact times.
        busy = [{"ref": "early", "start": 240, "end": 360}, {"ref": "deep", "start": 540, "end": 660},
                {"ref": "pset", "start": 600, "end": 750}, {"ref": "call", "start": 780, "end": 795},
                {"ref": "next", "start": 795, "end": 855}, {"ref": "late", "start": 1380, "end": 1440},
                {"ref": "last", "start": 1425, "end": 1440}]
        layout_script = PLANNER[start:end] + shows + f"""
const pick = list => Object.fromEntries(list.map(e => [e.ref, {{top: Math.round(e.top * 10) / 10, h: Math.round(e.h * 10) / 10, col: e.col, cols: e.cols, cutTop: e.cutTop, cutBottom: e.cutBottom}}]));
console.log(JSON.stringify({{
  fit: [fitHour(700, 19), fitHour(418, 19), fitHour(417, 19), fitHour(437 - 15, 19), fitHour(300, 19)],
  steps: [labelStep(48), labelStep(30), labelStep(29), labelStep(22), labelStep(17)],
  placed22: pick(place({json.dumps(busy)}, 300, 1440, 22)),
  placed36: pick(place({json.dumps(busy)}, 300, 1440, 36)),
  forms: [blockForm(20, 300), blockForm(25, 300), blockForm(26, 300), blockForm(39, 300), blockForm(40, 300), blockForm(50, 120), blockForm(63, 200), blockForm(64, 200), blockForm(200, 69), blockForm(20, 70)],
  fits: [itemsFit(20, 'xs', 3), itemsFit(50, 'md', 3), itemsFit(53, '', 1), itemsFit(100, '', 2), itemsFit(100, '', 5), itemsFit(150, '', 1)],
  short: [shortRange(960, 1020), shortRange(990, 1050), shortRange(660, 720), shortRange(1380, 1440), shortRange(780, 795), shortRange(0, 60)],
  lengths: [duration(15), duration(60), duration(90), duration(150), duration(1440)],
  timeFits: [timeFits(300, 'Lunch · Chipotle', '4–5 PM', 0), timeFits(86, 'Study group', '4:30–5:30 PM', 1), timeFits(148, 'Lunch · Chipotle', '4–5 PM', 1),
             timeFits(148, 'Lunch · Chipotle', '4–5 PM', 1, tagPx('Deep work')), timeFits(300, 'Study group', '4–5 PM', 0, tagPx('Socialize'))],
}}));
"""
        cls.lay = run_node(layout_script)

    def test_meals_merge_date_over_week_over_defaults(self):
        today, nxt, monday = self.out["today"], self.out["next"], self.out["monday"]
        self.assertEqual(today["meal:lunch"], {"start": 990, "end": 1050, "place": "Chipotle", "off": False, "changed": True, "items": 1})
        self.assertTrue(today["meal:dinner"]["off"])
        self.assertEqual(today["meal:breakfast"]["start"], 660)
        # Next Sunday has the week's place and time; a Monday with no week is the defaults.
        self.assertEqual((nxt["meal:lunch"]["start"], nxt["meal:lunch"]["place"], nxt["meal:lunch"]["changed"]), (960, "Chipotle", False))
        self.assertEqual({k: (v["start"], v["end"], v["place"]) for k, v in monday.items()},
                         {"meal:breakfast": (660, 720, ""), "meal:lunch": (960, 1020, ""), "meal:dinner": (1080, 1140, "")})

    def test_repeating_blocks_take_the_dates_changes(self):
        today, nxt = self.out["today"], self.out["next"]
        self.assertEqual((today["repeat:r1aaaaaaaa"]["start"], today["repeat:r1aaaaaaaa"]["changed"]), (570, True))
        self.assertTrue(today["repeat:r2aaaaaaaa"]["skip"])
        self.assertEqual(nxt["repeat:r1aaaaaaaa"]["start"], 540)
        self.assertFalse(nxt["repeat:r2aaaaaaaa"]["skip"])
        # A change to a block no longer in the week is dropped when the date is saved.
        self.assertNotIn("goneaaaaaa", self.out["stored"]["repeats"])
        self.assertIn("block:b1aaaaaaaa", today)
        self.assertNotIn("block:b1aaaaaaaa", nxt)

    def test_a_place_set_for_one_day_counts_as_changed_for_it(self):
        # Lunch's place set for one date: its time is the week's, its place is that day's only. A place
        # equal to the week's (dinner's empty one) is no change.
        self.assertEqual(self.out["placeOnly"], [False, True, False, False])

    def test_a_date_keeps_only_what_differs_from_its_week(self):
        self.assertIsNone(self.out["same"])
        self.assertEqual(self.out["stored"]["meals"]["dinner"], {"off": True})

    def test_overlapping_blocks_share_the_width(self):
        # Deep work 9:30-11:30 and Gym 10:00-11:00 overlap; breakfast at 11:00 starts as Gym ends but
        # still overlaps Deep work.
        self.assertEqual(self.out["cols"], {"repeat:r1aaaaaaaa": [0, 2], "block:b1aaaaaaaa": [1, 2], "meal:breakfast": [1, 2]})

    def test_the_hour_fits_the_room_and_never_drops_under_22_px(self):
        # Whole pixels of the room over the hours; under 22 px it stays 22 and the timeline scrolls.
        self.assertEqual(self.lay["fit"], [{"px": 36, "scroll": False}, {"px": 22, "scroll": False}, {"px": 22, "scroll": True},
                                           {"px": 22, "scroll": False}, {"px": 22, "scroll": True}])
        # Labels every hour from 30 px, every 2 hours under it (every 3 when shorter still).
        self.assertEqual(self.lay["steps"], [1, 1, 2, 2, 3])

    def test_every_block_is_drawn_inside_the_day_and_at_least_20_px(self):
        for name, px in (("placed22", 22), ("placed36", 36)):
            placed, H = self.lay[name], (24 - 5) * px
            with self.subTest(px=px):
                for ref, p in placed.items():
                    self.assertGreaterEqual(p["h"], 20, ref)
                    self.assertGreaterEqual(p["top"], 0, ref)
                    self.assertLessEqual(p["top"] + p["h"], H, ref)
                # A block starting before the day is cut at its top; 23:00-24:00 ends at the bottom.
                self.assertEqual((placed["early"]["top"], placed["early"]["cutTop"], placed["early"]["cutBottom"]), (0, True, False))
                self.assertEqual(placed["late"]["top"], 18 * px)
                # A block whose drawn height would run past the end of the day moves up to end there.
                self.assertAlmostEqual(placed["last"]["top"] + placed["last"]["h"], H, delta=0.1)
        placed = self.lay["placed22"]
        # A 15-minute block (1:00-1:15) is drawn 20 px tall, over the start of the next block
        # (1:15-2:15): the two share the width though their times do not overlap.
        self.assertEqual(placed["call"]["h"], 20)
        self.assertEqual([placed["call"]["cols"], placed["next"]["cols"]], [2, 2])
        self.assertNotEqual(placed["call"]["col"], placed["next"]["col"])
        # 11:45-midnight moved up over 11 PM-midnight: side by side too.
        self.assertEqual([placed["late"]["cols"], placed["last"]["cols"]], [2, 2])
        # Overlapping times share the width as before.
        self.assertEqual([placed["deep"]["cols"], placed["pset"]["cols"]], [2, 2])

    def test_a_block_takes_the_form_its_size_allows(self):
        # One line under 40 px (xs under 26), title and time on one line where wide enough, the
        # kind's initial in a column under 70 px.
        self.assertEqual(self.lay["forms"], ["xs", "xs", "sm", "sm", "md", "", "md", "", "nar", "xs"])
        # Items only where they fit, "+N more" after the time where its own line does not fit.
        self.assertEqual(self.lay["fits"], [{"fit": 0, "inline": False}, {"fit": 1, "inline": True}, {"fit": 0, "inline": True},
                                            {"fit": 2, "inline": False}, {"fit": 2, "inline": False}, {"fit": 1, "inline": False}])
        # The compact times, and the lengths the details show.
        self.assertEqual(self.lay["short"], ["4–5 PM", "4:30–5:30 PM", "11 AM–12 PM", "11 PM–12 AM", "1–1:15 PM", "12–1 AM"])
        self.assertEqual(self.lay["lengths"], ["15 min", "1 hr", "1 hr 30 min", "2 hr 30 min", "24 hr"])
        # A one-line block too narrow for its time leaves it out rather than showing a sliver of it.
        self.assertEqual(self.lay["timeFits"], [True, False, True, False, True])

    def test_times_read_as_the_page_writes_them(self):
        self.assertEqual(self.out["times"], ["4:00–5:00 PM", "11:00 AM–12:00 PM", "11:00 PM–12:00 AM", "9:30 to 11:30 AM", "5 AM", "12 PM", "12 AM"])
        # A date's own change is named for it: "today", or "this day" for any other.
        day = "today" if date.today().isoformat() == "2026-11-08" else "this day"
        self.assertEqual(self.out["spoken"], f"Lunch, 4:30 to 5:30 PM, at Chipotle, 1 thing to get done, changed for {day}")


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

    def test_a_failed_sync_points_to_the_sync_log(self):
        # The server adds each sync's output to state/sync.log (server.py run_sync); the toast says so.
        start, end = JS.index(SYNC_START), JS.index(SYNC_END)
        script = f"""
const els = {{'#syncBtn': {{hidden: true, disabled: false, textContent: 'Sync now', onclick: null}}, '#fab': {{hidden: true}}}};
const $ = s => els[s];
const getJson = path => Promise.resolve(path === 'api/tasks' ? {{tasks: {{}}}} : {{running: false}});
const api = () => Promise.resolve({{}});
const toasts = [];
const toast = m => toasts.push(m), refreshTasks = () => {{}};
const sessionStorage = {{getItem: () => JSON.stringify({{ok: false, output: 'Traceback: boom'}}), setItem(){{}}, removeItem(){{}}}};
const PUBLIC = false;
{JS[start:end]}
enableServerFeatures();
console.log(JSON.stringify(toasts));
"""
        self.assertEqual(run_node(script), ["Sync failed. See state/sync.log"])


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(NODE, "needs Node to run dashboard.js")
class MarkTest(unittest.TestCase):
    """A ✓ the nightly check could not confirm still counts as done, not as needing attention."""

    def test_an_unconfirmed_mark_counts_as_done(self):
        want = ("const SOURCE_DONE", "const past", "function eff", "const isDone", "const needsAttention")
        lines = []
        for name in want:
            # A function runs to its closing brace at the start of a line; a const to the next line.
            tail = r".*?^\}$" if name.startswith("function") else r".*?$"
            m = re.search(r"^" + re.escape(name) + tail, JS, re.M | re.S)
            self.assertIsNotNone(m, name)
            lines.append(m.group(0))
        script = "const now = new Date('2026-10-07T12:00:00Z');\n" + "\n".join(lines) + """
const at = '2026-10-06T11:38:16Z';
let marks = {checkin: {marked_at: at}, sent: {marked_at: at}};
const items = {
  checkin: {id: 'checkin', status: 'missing', due_at: '2026-10-05T03:59:59Z', marked_done: at, mark_check: 'not_found'},
  sent: {id: 'sent', status: 'submitted', due_at: '2026-10-05T03:59:59Z', marked_done: at, mark_check: 'confirmed'},
  late: {id: 'late', status: 'missing', due_at: '2026-10-05T03:59:59Z'},
};
console.log(JSON.stringify(Object.fromEntries(Object.entries(items).map(([k, a]) =>
  [k, {state: eff(a), done: isDone(a), attention: needsAttention(a)}]))));
"""
        out = run_node(script)
        self.assertEqual(out["checkin"], {"state": "flagged", "done": True, "attention": False})
        self.assertEqual(out["sent"]["attention"], False)
        self.assertEqual(out["late"], {"state": "missing", "done": False, "attention": True})


# ---- undo and redo (dashboard.js "undo and redo", planner.js "undo") ----
UNDO_START, UNDO_END = "// ---- undo and redo ----", "// ---- end of undo and redo ----"
PLAN_KEPT_START, PLAN_KEPT_END = "  // ---- the plan, loaded and saved ----", "  // ---- what shows on a date ----"


def source_of(name):
    """A top-level function or object of dashboard.js: from its first line to its closing brace."""
    m = re.search(r"^" + re.escape(name) + r".*?^\}[;]?$", JS, re.M | re.S)
    assert m, name
    return m.group(0)


# The page's undo history with the page stood in for: toasts are collected, the focused element and
# an open form are set by the test, and the keydown handler is kept to be called.
UNDO_PAGE = """
const toasts = [];
let toastTimer = null, lastAction = null;
const $ = () => null;
const toast = (msg, action, o = {}) => { toasts.push(msg + (action ? ' [' + (o.label || 'Undo') + ']' : '')); lastAction = action; };
const page = {focus: {tagName: 'BODY'}, form: false, keydown: null};
const document = {get activeElement(){ return page.focus; }, body: {tagName: 'BODY'}, addEventListener: (type, fn) => { page[type] = fn; },
  querySelector: sel => sel === 'dialog[open] form' && page.form ? {} : null};
const CSS = {escape: s => s};
const console = {error(){}, log: (...a) => globalThis.console.log(...a)};
const pinnedTask = t => typeof t.pinned === 'boolean' ? t.pinned : !t.due_at;
const refresh = () => {};
let marks = {}, tasks = {};
const refreshTasks = next => { tasks = next; };
"""


def undo_section():
    return JS[JS.index(UNDO_START):JS.index(UNDO_END)]


class UndoSourceTest(unittest.TestCase):
    """Undo and redo for everything the page changes: where the keys go, and that no change is made
    without a step."""

    def test_the_keys(self):
        # Cmd+Z and Ctrl+Z undo; with Shift, and Ctrl+Y, redo. Typing in a field keeps the field's own.
        self.assertIn("const dir = k === 'z' ? (e.shiftKey ? 'redo' : 'undo') : k === 'y' && e.ctrlKey && !e.metaKey && !e.shiftKey ? 'redo' : '';", JS)
        self.assertIn("if (dir && requestStep(dir)) e.preventDefault();", JS)
        self.assertIn("if (editingText(document.activeElement)) return false;", JS)
        # Nothing changes underneath an open form, or during a drag on the planner.
        self.assertIn("if (!document.querySelector('dialog[open] form') && !holds.some(fn => fn())) travel(dir);", JS)
        self.assertIn("SH.holdUndo?.(() => !!drag);", PLANNER)
        # The forms are the three dialogs with a form; the details card has none, so it follows an undo.
        self.assertEqual(len(re.findall(r"<dialog[^>]*>\s*<form", HTML)), 3)
        self.assertIn('<dialog class="pdetail" id="planDetail" aria-labelledby="pdTitle"></dialog>', HTML)

    def test_the_mac_app_can_ask(self):
        # Its Edit menu calls these: true when the page took the request, false when it is the field's.
        self.assertIn("  undo: () => requestStep('undo'),\n  redo: () => requestStep('redo'),", JS)
        self.assertIn("same, addStep, offerStep, holdUndo: fn => { holds.push(fn); },", JS)

    def test_about_a_hundred_steps(self):
        self.assertIn("const UNDO_STEPS = 100;", JS)
        self.assertIn("if (steps.undo.length > UNDO_STEPS) steps.undo.shift();", JS)

    def test_toasts_name_the_step_and_offer_the_way_back(self):
        self.assertIn("toast(`${DID[dir]}: ${step.label}`, newest ? offerStep(step, BACK[dir]) : null, {label: dir === 'undo' ? 'Redo' : 'Undo'});", JS)
        self.assertIn("if (!step) return toast(`Nothing to ${dir}`, null, {ms: 2000});", JS)
        # Announced as every toast is.
        self.assertIn("el.className = 'toast'; el.id = 'toast'; el.setAttribute('role', 'status');", JS)
        # Deleting a task or a block offers Undo on its own toast.
        self.assertIn("toast(`Deleted “${removed.name}”`, offerStep(step));", JS)
        self.assertIn("      SH.toast(`Deleted “${name}”`, undo);", PLANNER)

    def test_marks_and_tasks_are_steps(self):
        # Every save of a mark or a task from the page's own controls makes a step, or is one's way back.
        self.assertIn("const step = unsavedMark[id] = addStep(markStep(done ? `marked “${a.name}” done` : `unmarked “${a.name}”`, id, was), saved.then(async stored => {", JS)
        self.assertIn("const step = sameTask(was, r.task) ? null : addStep(taskStep(was ? taskEdit(was, r.task) : `added “${name}”`, r.task.id, was, r.task));", JS)
        self.assertIn("const step = addStep(taskStep(`deleted “${removed.name}”`, id, removed, null), saved);", JS)
        outside = JS[:JS.index(UNDO_START)] + JS[JS.index(UNDO_END):]
        self.assertEqual(len(re.findall(r"backend\.(saveTask|deleteTask)\(", outside)), 2)
        self.assertEqual(len(re.findall(r"\bsetMark\(", outside)), 2)   # its definition, and toggleMark
        self.assertEqual(len(re.findall(r"backend\.mark\(", JS)), 1)     # setMark
        # A mark put back carries its own time, and the way back first asks what is stored now.
        self.assertIn("if (done && as?.marked_at) body.marked_at = as.marked_at;", JS)
        self.assertIn("try { stored = await backend.marks(); } catch { return {ok: false, why: 'failed'}; }", JS)
        self.assertIn("try { stored = await backend.tasks(); } catch { return {ok: false, why: 'failed'}; }", JS)

    def test_every_change_to_the_plan_is_a_step(self):
        # save() is the only way to the server, and outside the step's own way back it is only
        # reached inside record(): a change added later without one fails here.
        self.assertEqual(len(re.findall(r"SH\.api\('api/plan'", PLANNER)), 1)
        self.assertNotIn("snapshot(", PLANNER)
        lines = PLANNER.splitlines()
        own = ("function save(", "function editDay(", "function editWeek(", "sent.push(save(key, none ? null : v));",
               "save('day:' + date, cleanDay(v, weekOf(wdOf(date))));", "save('week:' + wd, cleanWeek(v));")
        checked = 0
        for i, line in enumerate(lines):
            if not re.search(r"\b(save|editDay|editWeek)\(", line) or line.lstrip().startswith("//") or any(x in line for x in own):
                continue
            checked += 1
            # Going up from the call, record( comes before the start of the function or handler it is in.
            for j in range(i, -1, -1):
                if "record(" in lines[j]:
                    break
                self.assertNotRegex(lines[j], r"^  (async )?function |^  \S.*addEventListener\(", f"line {i + 1} saves outside record(): {line.strip()}")
        self.assertGreaterEqual(checked, 20)

    def test_a_failed_save_of_the_plan_is_put_back(self):
        self.assertIn("for (const [k, v] of confirmed) setKey(k, v);", PLANNER)
        self.assertIn("return SH.offerStep(SH.addStep(step, Promise.all(rec.sent).then(all => all.every(Boolean))));", PLANNER)

    def test_tasks_show_in_the_order_they_were_made(self):
        # A task an undo puts back is stored last; it still shows where it was.
        self.assertIn("for (const t of Object.values(tasks).sort((x, y) => made(x) - made(y)))", JS)


@unittest.skipUnless(NODE, "Node is not installed")
class UndoHistoryTest(unittest.TestCase):
    """dashboard.js's undo history, run under Node with the page stood in for."""

    @classmethod
    def setUpClass(cls):
        script = UNDO_PAGE + "const backend = {};\nasync function setMark(){ return true; }\n" + undo_section() + """
const out = {};
const log = [];
const mk = (label, how = {}) => ({label, undo: async o => { log.push('undo ' + label + (o?.refocus ? ' (refocus)' : '')); return how.undo || {ok: true}; },
  redo: async () => { log.push('redo ' + label); return how.redo || {ok: true}; }});
const reset = () => { steps.undo.length = steps.redo.length = toasts.length = log.length = 0; };
(async () => {
  // In reverse order; a new change clears what could be redone.
  for (const l of ['a', 'b', 'c']) addStep(mk(l));
  await travel('undo'); await travel('undo'); await travel('redo');
  addStep(mk('d'));
  await travel('redo'); await travel('undo'); await travel('undo'); await travel('undo'); await travel('undo');
  out.order = {log: [...log], toasts: [...toasts]};
  // About a hundred steps.
  reset();
  for (let i = 1; i <= 105; i++) addStep(mk('s' + i));
  for (let i = 0; i < 101; i++) await travel('undo');
  out.cap = {undone: log.length, first: log[0], last: log[log.length - 1], end: toasts[toasts.length - 1], redo: steps.redo.length};
  // A way back that could not be saved stays, to try again; one that would overwrite another change goes.
  reset();
  addStep(mk('kept')); addStep(mk('offline', {undo: {ok: false, why: 'failed'}}));
  await travel('undo'); await travel('undo');
  out.failed = {log: [...log], toasts: [...toasts], left: steps.undo.map(s => s.label)};
  reset();
  addStep(mk('kept')); addStep(mk('moved Lunch to 3:00 PM', {undo: {ok: false, why: 'conflict'}}));
  await travel('undo'); await travel('undo');
  out.conflict = {log: [...log], toasts: [...toasts], left: steps.undo.map(s => s.label), redo: steps.redo.map(s => s.label)};
  // A change whose own save failed was never made: its step goes. One that throws counts as failed.
  reset();
  addStep(mk('kept')); addStep(mk('never saved'), Promise.resolve(false)); addStep(mk('rejected'), Promise.reject(new Error('x')));
  await travel('undo');
  addStep({label: 'throws', undo: async () => { throw new Error('boom'); }, redo: async () => ({ok: true})});
  await travel('undo');
  out.gone = {log: [...log], toasts: [...toasts], left: steps.undo.map(s => s.label)};
  // A toast's button is for its own step, while that is the next one; it asks for focus to be placed.
  reset();
  const first = addStep(mk('first')), offerFirst = offerStep(first);
  const second = addStep(mk('second')), offerSecond = offerStep(second);
  offerFirst(); await travelling;
  const before = [...log];
  offerSecond(); await travelling;
  out.offer = {before, after: [...log], isStepButton: offerFirst.step === true, none: offerStep(null)};
  // The keys and SchoolHub.undo(): typing keeps the field's own; a form open or a drag swallows it.
  reset();
  addStep(mk('k1')); addStep(mk('k2')); addStep(mk('k3'));
  const key = async (k, mods, focus, form) => {
    page.focus = focus || {tagName: 'BODY'}; page.form = !!form;
    let prevented = false;
    page.keydown({key: k, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, ...mods, preventDefault(){ prevented = true; }});
    await travelling;
    return prevented;
  };
  const field = type => ({tagName: 'INPUT', type});
  out.keys = {
    typingText: await key('z', {metaKey: true}, field('text')),
    typingTime: await key('z', {ctrlKey: true}, field('time')),
    typingArea: await key('Z', {metaKey: true, shiftKey: true}, {tagName: 'TEXTAREA'}),
    editable: await key('z', {metaKey: true}, {tagName: 'DIV', isContentEditable: true}),
    formOpenOnButton: await key('z', {metaKey: true}, {tagName: 'BUTTON'}, true),
    plain: await key('z', {}), alt: await key('z', {metaKey: true, altKey: true}), cmdY: await key('y', {metaKey: true}),
    ctrlShiftY: await key('y', {ctrlKey: true, shiftKey: true}), other: await key('x', {metaKey: true}),
    nothingYet: [...log],
    cmdZ: await key('z', {metaKey: true}), onCheckbox: await key('z', {ctrlKey: true}, field('checkbox')),
    shiftCmdZ: await key('Z', {metaKey: true, shiftKey: true}), ctrlY: await key('y', {ctrlKey: true}), shiftCtrlZ: await key('z', {ctrlKey: true, shiftKey: true}),
    log: [...log],
  };
  holds.push(() => true);
  page.focus = {tagName: 'BODY'}; page.form = false;
  const held = requestStep('undo'); await travelling;
  holds.length = 0;
  out.keys.heldDuringDrag = [held, log.length];
  page.focus = field('search');
  out.keys.apiWhileTyping = requestStep('undo');
  console.log(JSON.stringify(out));
})();
"""
        cls.out = run_node(script)

    def test_steps_go_back_in_reverse_and_a_new_change_clears_redo(self):
        o = self.out["order"]
        self.assertEqual(o["log"], ["undo c", "undo b", "redo b", "undo d", "undo b", "undo a"])
        self.assertEqual(o["toasts"], ["Undid: c [Redo]", "Undid: b [Redo]", "Redid: b [Undo]", "Nothing to redo",
                                       "Undid: d [Redo]", "Undid: b [Redo]", "Undid: a [Redo]", "Nothing to undo"])

    def test_about_a_hundred_steps_are_kept(self):
        self.assertEqual(self.out["cap"], {"undone": 100, "first": "undo s105", "last": "undo s6", "end": "Nothing to undo", "redo": 100})

    def test_a_way_back_that_fails_stays_and_one_that_conflicts_goes(self):
        f = self.out["failed"]
        self.assertEqual(f["log"], ["undo offline", "undo offline"])
        self.assertEqual(f["toasts"], ["Couldn't undo that. Check your connection and try again."] * 2)
        self.assertEqual(f["left"], ["kept", "offline"])
        c = self.out["conflict"]
        self.assertEqual(c["log"], ["undo moved Lunch to 3:00 PM", "undo kept"])
        self.assertEqual(c["toasts"], ["Can't undo: moved Lunch to 3:00 PM. It was changed somewhere else since.", "Undid: kept [Redo]"])
        self.assertEqual((c["left"], c["redo"]), ([], ["kept"]))

    def test_a_change_that_was_never_saved_is_no_step(self):
        g = self.out["gone"]
        self.assertEqual(g["log"], ["undo kept"])
        self.assertEqual(g["toasts"], ["Undid: kept [Redo]", "Couldn't undo that. Check your connection and try again."])
        self.assertEqual(g["left"], ["throws"])

    def test_a_toasts_button_is_for_its_own_step(self):
        o = self.out["offer"]
        self.assertEqual(o["before"], [])                       # the first step is no longer the next one
        self.assertEqual(o["after"], ["undo second (refocus)"])
        self.assertTrue(o["isStepButton"])
        self.assertIsNone(o["none"])

    def test_the_keys_and_what_the_mac_app_is_told(self):
        k = self.out["keys"]
        # Typing in a field: not taken (the field's own undo runs), and nothing is undone.
        self.assertEqual([k["typingText"], k["typingTime"], k["typingArea"], k["editable"]], [False] * 4)
        # A form open with focus on a button: taken, and nothing is undone underneath it.
        self.assertTrue(k["formOpenOnButton"])
        # Not the page's keys at all.
        self.assertEqual([k["plain"], k["alt"], k["cmdY"], k["ctrlShiftY"], k["other"]], [False] * 5)
        self.assertEqual(k["nothingYet"], [])
        # Cmd+Z, Ctrl+Z (a checkbox is no text field); Shift+Cmd+Z, Ctrl+Y, Shift+Ctrl+Z.
        self.assertEqual([k["cmdZ"], k["onCheckbox"], k["shiftCmdZ"], k["ctrlY"], k["shiftCtrlZ"]], [True] * 5)
        self.assertEqual(k["log"], ["undo k3", "undo k2", "redo k2", "redo k3"])
        self.assertEqual(k["heldDuringDrag"], [True, 4])
        self.assertFalse(k["apiWhileTyping"])


@unittest.skipUnless(NODE, "Node is not installed")
class UndoMarksAndTasksTest(unittest.TestCase):
    """A ✓ and a task taken back: dashboard.js's own store calls and steps against a stand-in for
    server.py's routes (a mark is stamped with the time given or now, a task with updated_at)."""

    @classmethod
    def setUpClass(cls):
        script = UNDO_PAGE + """
let WRITE = 'local', clock = 0, down = false;
const server = {marks: {}, tasks: {}}, sent = [];
const copy = v => JSON.parse(JSON.stringify(v));
const stamp = () => '2026-11-11T10:00:0' + (clock++) + '+00:00';
const api = async (path, body) => {
  if (down) throw new Error('down');
  sent.push([path, copy(body)]);
  if (path === 'api/mark') {
    if (body.done) server.marks[body.id] = {marked_at: body.marked_at || stamp(), name: body.name ?? null, course: body.course ?? null}; else delete server.marks[body.id];
    return copy(server.marks);
  }
  if (path === 'api/task') {
    const id = body.id || 'task:new' + clock, old = server.tasks[id];
    const task = {id, name: body.name, course_id: body.course_id || 'personal', due_at: body.due_at || null, all_day: !!body.all_day,
      pinned: 'pinned' in body ? !!body.pinned : !body.due_at, notes: body.notes || '', created_at: old?.created_at || body.created_at || stamp(), updated_at: stamp()};
    delete server.tasks[id]; server.tasks[id] = task;
    return {task: copy(task), tasks: copy(server.tasks)};
  }
  const removed = server.tasks[body.id] || null; delete server.tasks[body.id];
  return {removed, tasks: copy(server.tasks)};
};
const getJson = async path => { if (down) throw new Error('down'); return copy(path === 'api/marks' ? server.marks : {tasks: server.tasks}); };
const cloudApi = async () => { throw new Error('not here'); };
const byId = {'canvas:1': {id: 'canvas:1', name: 'HW 1', course: {short: '15-122'}}};
""" + source_of("const backend = {") + "\n" + source_of("async function setMark(id, done, as){") + "\n" + source_of("const unsavedMark = {};") + "\n" + undo_section() + """
const out = {};
(async () => {
  // The ✓ clicked twice before the first save answers: two steps, and both go back.
  byId['canvas:2'] = {id: 'canvas:2', name: 'Lab 2', course: {short: '15-122'}};
  toggleMark('canvas:2'); toggleMark('canvas:2');
  await Promise.all(steps.undo.map(s => s.settled));
  out.twice = {steps: steps.undo.map(s => s.label), marked: 'canvas:2' in server.marks};
  await travel('undo');
  out.twice.first = [toasts[toasts.length - 1], 'canvas:2' in server.marks];
  await travel('undo');
  out.twice.second = [toasts[toasts.length - 1], 'canvas:2' in server.marks];
  steps.undo.length = steps.redo.length = 0;
  // A mark made long ago, taken away, and put back by undo: the same mark, with its own time.
  server.marks['canvas:1'] = {marked_at: '2026-10-01T09:00:00.123456+00:00', name: 'HW 1 (old name)', course: '15-122'};
  marks = copy(server.marks);
  const was = marks['canvas:1'];
  const saved = setMark('canvas:1', false);
  const step = addStep(markStep('unmarked “HW 1”', 'canvas:1', was), saved.then(stored => { step.now = stored && stored['canvas:1'] || null; return !!stored; }));
  await saved;
  out.unmarked = copy(server.marks);
  await travel('undo');
  out.markBack = copy(server.marks);
  out.markSent = sent[sent.length - 1];
  await travel('redo');
  out.markRedone = copy(server.marks);
  await travel('undo');
  // Another device takes the mark away and makes it again: no longer the mark the step left.
  server.marks['canvas:1'] = {marked_at: stamp(), name: 'HW 1', course: '15-122'};
  const n = sent.length;
  await travel('redo');
  out.markConflict = {toast: toasts[toasts.length - 1], wrote: sent.length - n, local: marks['canvas:1'].marked_at === server.marks['canvas:1'].marked_at};
  // The server cannot be asked: nothing changes, and the step stays.
  steps.undo.length = steps.redo.length = 0;
  const had = copy(server.marks['canvas:1']), made = setMark('canvas:1', false);
  const s2 = addStep(markStep('unmarked “HW 1”', 'canvas:1', had), made.then(stored => { s2.now = null; return !!stored; }));
  await made;
  down = true;
  await travel('undo');
  out.markDown = {toast: toasts[toasts.length - 1], left: steps.undo.length, marked: 'canvas:1' in server.marks};
  down = false;
  await travel('undo');
  out.markUp = {toast: toasts[toasts.length - 1], marked: 'canvas:1' in server.marks};

  // A task from before the pinned choice, deleted and put back: same id, fields and time made.
  steps.undo.length = steps.redo.length = 0;
  const old = {id: 'task:abc12345', name: 'Buy milk', course_id: 'personal', due_at: null, all_day: false, notes: '2%', created_at: '2026-09-16T14:20:24+00:00', updated_at: '2026-09-16T14:20:24+00:00'};
  server.tasks = {[old.id]: copy(old), 'task:zzz99999': {id: 'task:zzz99999', name: 'Other', course_id: 'personal', due_at: null, all_day: false, pinned: true, notes: '', created_at: '2026-09-17T00:00:00+00:00', updated_at: '2026-09-17T00:00:00+00:00'}};
  tasks = copy(server.tasks);
  await backend.deleteTask(old.id).then(r => refreshTasks(r.tasks));
  addStep(taskStep('deleted “Buy milk”', old.id, copy(old), null));
  await travel('undo');
  out.taskBack = {toast: toasts[toasts.length - 1], task: copy(server.tasks[old.id]), sentId: sent[sent.length - 1][1].id, sentPinned: 'pinned' in sent[sent.length - 1][1], local: !!tasks[old.id]};
  await travel('redo');
  out.taskRedone = {toast: toasts[toasts.length - 1], gone: !(old.id in server.tasks)};
  await travel('undo');
  // An edit, then the same task edited on another device: the edit is not taken back over it.
  const before = copy(server.tasks[old.id]);
  const r = await backend.saveTask({...before, name: 'Buy oat milk', pinned: false, due_at: '2026-11-13T20:00:00.000Z'});
  refreshTasks(r.tasks);
  out.editLabel = taskEdit(before, r.task);
  out.pinLabel = [taskEdit(before, {...before, pinned: false}), taskEdit({...before, pinned: false}, {...before, pinned: true})];
  addStep(taskStep(out.editLabel, old.id, before, r.task));
  // The server's stamp alone moving (a save that changed nothing) is no other change.
  await api('api/task', copy(server.tasks[old.id]));
  await travel('undo');
  out.editUndone = {toast: toasts[toasts.length - 1], name: server.tasks[old.id].name, due: server.tasks[old.id].due_at};
  await travel('redo');
  server.tasks[old.id].notes = 'written on the phone';
  const m = sent.length;
  await travel('undo');
  out.taskConflict = {toast: toasts[toasts.length - 1], wrote: sent.length - m, name: server.tasks[old.id].name, localNotes: tasks[old.id].notes};
  out.sameTask = [sameTask(null, null), sameTask(null, old), sameTask(old, {...old, updated_at: 'later'}), sameTask(old, {...old, pinned: true}), sameTask(old, {...old, pinned: false}), sameTask(old, {...old, notes: ''})];
  console.log(JSON.stringify(out));
})();
"""
        cls.out = run_node(script)

    def test_a_mark_put_back_is_the_same_mark(self):
        o = self.out
        self.assertEqual(o["unmarked"], {})
        mark = {"marked_at": "2026-10-01T09:00:00.123456+00:00", "name": "HW 1 (old name)", "course": "15-122"}
        self.assertEqual(o["markBack"], {"canvas:1": mark})
        self.assertEqual(o["markSent"], ["api/mark", {"id": "canvas:1", "done": True, **mark}])
        self.assertEqual(o["markRedone"], {})

    def test_a_check_clicked_twice_before_the_server_answers(self):
        self.assertEqual(self.out["twice"], {"steps": ["marked “Lab 2” done", "unmarked “Lab 2”"], "marked": False,
                                             "first": ["Undid: unmarked “Lab 2” [Redo]", True], "second": ["Undid: marked “Lab 2” done [Redo]", False]})

    def test_a_mark_changed_elsewhere_is_left_alone(self):
        self.assertEqual(self.out["markConflict"], {"toast": "Can't redo: unmarked “HW 1”. It was changed somewhere else since.", "wrote": 0, "local": True})

    def test_a_mark_is_not_taken_back_blind(self):
        self.assertEqual(self.out["markDown"], {"toast": "Couldn't undo that. Check your connection and try again.", "left": 1, "marked": False})
        self.assertEqual(self.out["markUp"], {"toast": "Undid: unmarked “HW 1” [Redo]", "marked": True})

    def test_a_deleted_task_comes_back_as_it_was(self):
        b = self.out["taskBack"]
        self.assertEqual(b["toast"], "Undid: deleted “Buy milk” [Redo]")
        self.assertEqual((b["sentId"], b["sentPinned"], b["local"]), ("task:abc12345", False, True))
        # Every field it had; the store's own additions are the stamp of the save and the pin it
        # already meant (it had no due date).
        self.assertEqual({k: v for k, v in b["task"].items() if k not in ("updated_at", "pinned")},
                         {"id": "task:abc12345", "name": "Buy milk", "course_id": "personal", "due_at": None, "all_day": False, "notes": "2%",
                          "created_at": "2026-09-16T14:20:24+00:00"})
        self.assertTrue(b["task"]["pinned"])
        self.assertEqual(self.out["taskRedone"], {"toast": "Redid: deleted “Buy milk” [Undo]", "gone": True})

    def test_a_task_edit_is_taken_back_unless_it_changed_elsewhere(self):
        o = self.out
        self.assertEqual(o["editLabel"], "edited “Buy oat milk”")
        self.assertEqual(o["pinLabel"], ["unpinned “Buy milk”", "pinned “Buy milk”"])
        self.assertEqual(o["editUndone"], {"toast": "Undid: edited “Buy oat milk” [Redo]", "name": "Buy milk", "due": None})
        self.assertEqual(o["taskConflict"], {"toast": "Can't undo: edited “Buy oat milk”. It was changed somewhere else since.", "wrote": 0,
                                             "name": "Buy oat milk", "localNotes": "written on the phone"})
        # The server's stamp is not compared; a task saved before the pinned choice counts as what it meant.
        self.assertEqual(o["sameTask"], [True, False, True, True, False, False])


@unittest.skipUnless(NODE, "Node is not installed")
class UndoPlanTest(unittest.TestCase):
    """The planner's steps: planner.js's own save(), record() and the way back, with dashboard.js's
    history, against a stand-in for /api/plan (one value per key, null removes it)."""

    @classmethod
    def setUpClass(cls):
        plan_pure = PLANNER[PLANNER.index(PLAN_START):PLANNER.index(PLAN_END)]
        plan_kept = PLANNER[PLANNER.index(PLAN_KEPT_START):PLANNER.index(PLAN_KEPT_END)]
        cls.pure = "const backend = {};\nasync function setMark(){ return true; }\n" + UNDO_PAGE + undo_section() + plan_pure
        script = cls.pure + """
const store = {}, posts = [];
let down = false, refuse = false, renders = 0, scrolledFor = 'x', wentTo = null, focusGone = false, refocused = null;
const copy = v => v == null ? null : JSON.parse(JSON.stringify(v));
const SH = {same, addStep, offerStep, toast, setPlanner(){}, plannerState: 'on',
  api: async (path, body) => {
    if (down || refuse) throw new Error('refused');
    posts.push(body.key + (body.value === null ? ' removed' : ''));
    if (body.value === null) delete store[body.key]; else store[body.key] = copy(body.value);
    return {key: body.key, value: copy(body.value)};
  }};
const fetch = async () => {
  if (down) throw new Error('down');
  const days = {}, week = {};
  for (const k of Object.keys(store)) if (k.startsWith('day:')) days[k.slice(4)] = copy(store[k]);
  for (const wd of WD) week[wd] = copy(store['week:' + wd]);
  return {ok: true, status: 200, json: async () => ({settings: copy(store.settings), week, days})};
};
function render(){ renders++; }
const focusLost = () => focusGone, refSel = ref => ref, refocus = sel => { refocused = sel; };
""" + plan_kept + """
function setDate(d){ wentTo = d; shown = d; }
const D = '2026-11-11', K = 'day:' + D;                     // a Wednesday
const idle = async () => { while (pending) await chain; await new Promise(r => setTimeout(r, 0)); };
const blockOf = (v, id) => (v?.blocks || []).find(b => b.id === id);
const out = {};
(async () => {
  shown = D;
  store['week:wed'] = cleanWeek({meals: {lunch: {start: '15:00', end: '16:00', place: 'Chipotle'}}, blocks: [{id: 'weekly0001', type: 'deep', title: 'Lab', start: '09:00', end: '10:00'}]});
  store[K] = {blocks: [{id: 'blockaaaa1', type: 'social', title: 'Pickleball', start: '19:00', end: '20:15', items: []},
    {id: 'blockbbbb2', type: 'other', title: 'Errands', start: '07:00', end: '08:00', items: [
      {id: 'itemaaaaa1', kind: 'own', text: 'one', done: true}, {id: 'itembbbbb2', kind: 'work', text: 'HW 9', ref: 'canvas:9', course: '21-127', done: false}, {id: 'itemccccc3', kind: 'own', text: 'three', done: false}]},
    {id: 'blockcccc3', type: 'deep', title: 'Concepts', start: '20:15', end: '22:00', items: []}]};
  await load(D);
  const start = copy(store);

  // 1. A block moved, taken back and made again: the stored value exactly as it was each time.
  const undoMove = record('moved “Pickleball” to 7:30 PM', D, 'block:blockaaaa1', () => editDay(D, v => { Object.assign(blockOf(v, 'blockaaaa1'), {start: '19:30', end: '20:45'}); }));
  await idle();
  const moved = copy(store);
  await travel('undo');
  out.move = {offered: typeof undoMove, isStep: undoMove.step, undone: same(store, start), toast: toasts[toasts.length - 1]};
  await travel('redo');
  out.move.redone = same(store, moved); out.move.toast2 = toasts[toasts.length - 1];
  await travel('undo');

  // 2. A deleted block comes back with its id, fields, items and their ticks, in its place.
  record('deleted “Errands”', D, 'block:blockbbbb2', () => editDay(D, v => { v.blocks = v.blocks.filter(b => b.id !== 'blockbbbb2'); }));
  await idle();
  out.deleted = {gone: !blockOf(store[K], 'blockbbbb2')};
  await travel('undo');
  out.deleted.back = same(store, start); out.deleted.order = store[K].blocks.map(b => b.id);

  // 3. One action that saves the week and the date is one step, and the week is saved first both ways.
  posts.length = 0;
  record('removed “Lab” from every Wednesday', D, 'repeat:weekly0001', () => {
    editDay(D, v => { (v.repeats ||= {}).weekly0001 = {items: [{id: 'itemddddd4', kind: 'own', text: 'bring goggles', done: false}]}; });
  });
  await idle();
  const withItems = copy(store);
  const stepsBefore = steps.undo.length;
  record('removed “Lab” from every Wednesday', D, 'repeat:weekly0001', () => {
    editWeek('wed', w => { w.blocks = w.blocks.filter(b => b.id !== 'weekly0001'); });
    editDay(D, () => {});
  });
  await idle();
  out.both = {oneStep: steps.undo.length - stepsBefore, dropped: !store[K].repeats, posts: [...posts]};
  posts.length = 0;
  await travel('undo');
  out.both.back = same(store, withItems); out.both.undoPosts = [...posts];
  await travel('undo');
  out.both.allBack = same(store, start);

  // 4. Another device added a block to the same date: only my move is taken back.
  record('moved “Pickleball” to 7:30 PM', D, 'block:blockaaaa1', () => editDay(D, v => { Object.assign(blockOf(v, 'blockaaaa1'), {start: '19:30', end: '20:45'}); }));
  await idle();
  store[K].blocks.push({id: 'phoneblock', type: 'other', title: 'From my phone', start: '05:00', end: '05:45', items: []});
  await travel('undo');
  out.other = {toast: toasts[toasts.length - 1], mine: [blockOf(store[K], 'blockaaaa1').start, blockOf(store[K], 'blockaaaa1').end], theirs: !!blockOf(store[K], 'phoneblock'), local: !!blockOf(plan.days[D], 'phoneblock')};
  // ...and moved the very block I moved: nothing is saved, and the page shows what is stored.
  await travel('redo');
  Object.assign(blockOf(store[K], 'blockaaaa1'), {start: '21:00', end: '22:15'});
  posts.length = 0;
  await travel('undo');
  out.clash = {toast: toasts[toasts.length - 1], posts: [...posts], stored: blockOf(store[K], 'blockaaaa1').start, shown: blockOf(plan.days[D], 'blockaaaa1').start, left: steps.undo.length + steps.redo.length};

  // 5. The settings back to the defaults are stored as no key, as before their first change.
  record('changed the hours shown', null, null, () => { save('settings', {day_start: 7, day_end: 23}); });
  await idle();
  out.settings = {saved: copy(store.settings)};
  scrolledFor = 'x'; posts.length = 0;
  await travel('undo');
  out.settings.undone = ['settings' in store, copy(plan.settings), [...posts], scrolledFor];
  await travel('redo');
  out.settings.redone = copy(store.settings);
  await travel('undo');

  // 6. A change whose save fails is put back on the page and is no step.
  const kept = copy(plan.days[D]), n = steps.undo.length;
  refuse = true;
  record('moved “Concepts” to 9:00 PM', D, 'block:blockcccc3', () => editDay(D, v => { Object.assign(blockOf(v, 'blockcccc3'), {start: '21:00', end: '22:45'}); }));
  out.fail = {shownAtOnce: blockOf(plan.days[D], 'blockcccc3').start};
  await idle();
  refuse = false;
  await idle();
  out.fail.putBack = same(plan.days[D], kept); out.fail.steps = steps.undo.length - n; out.fail.toast = toasts.includes("Couldn't save the plan");

  // 7. The server cannot be asked: the way back changes nothing and the step stays.
  record('moved “Concepts” to 9:00 PM', D, 'block:blockcccc3', () => editDay(D, v => { Object.assign(blockOf(v, 'blockcccc3'), {start: '21:00', end: '22:45'}); }));
  await idle();
  const there = copy(plan.days[D]);
  down = true; posts.length = 0;
  await travel('undo');
  out.down = {toast: toasts[toasts.length - 1], same: same(plan.days[D], there), posts: posts.length, top: steps.undo[steps.undo.length - 1].label};
  down = false;
  // ...and when only the write fails: put back to what the server has, and the step stays.
  refuse = true;
  await travel('undo');
  refuse = false;
  await idle();
  out.refused = {toast: toasts[toasts.length - 1], same: same(plan.days[D], there), top: steps.undo[steps.undo.length - 1].label};
  await travel('undo');
  out.retried = {toast: toasts[toasts.length - 1], start: blockOf(store[K], 'blockcccc3').start};

  // 8. Another day is shown: the way back shows the day of the change; focus lost on the way is placed.
  record('moved “Concepts” to 9:00 PM', D, 'block:blockcccc3', () => editDay(D, v => { Object.assign(blockOf(v, 'blockcccc3'), {start: '21:00', end: '22:45'}); }));
  await idle();
  shown = '2026-11-12'; wentTo = null; refocused = null;
  await travel('undo');
  out.where = {wentTo, refocused};
  focusGone = true;
  await steps.redo[steps.redo.length - 1].redo({refocus: true});
  out.where.refocused = refocused;

  // 9. Nothing changed, nothing to take back; a step inside a step is the outer one's.
  const m = steps.undo.length;
  out.none = record('edited “Concepts”', D, 'block:blockcccc3', () => editDay(D, () => {}));
  await idle();
  const outer = record('outer', D, null, () => {
    out.inner = record('inner', D, null, () => editDay(D, v => { blockOf(v, 'blockcccc3').title = 'Concepts 2'; }));
    editDay(D, v => { blockOf(v, 'blockcccc3').title = 'Concepts 3'; });
  });
  await idle();
  out.nested = {steps: steps.undo.length - m, label: steps.undo[steps.undo.length - 1].label, outer: typeof outer};
  await travel('undo');
  out.nested.title = blockOf(store[K], 'blockcccc3').title;
  out.labels = [
    changeLabel({kind: 'meal', title: 'Lunch', start: 900, end: 960, place: 'Chipotle', items: []}, {start: 930, end: 990, place: 'Chipotle', items: []}),
    changeLabel({kind: 'meal', title: 'Lunch', start: 900, end: 960, place: 'Chipotle', items: []}, {start: 900, end: 960, place: 'Thai place', items: []}),
    changeLabel({kind: 'deep', title: 'Lab', start: 540, end: 600, items: []}, {title: 'Lab', kind: 'deep', start: 540, end: 630, items: []}),
    changeLabel({kind: 'deep', title: 'Lab', start: 540, end: 600, items: []}, {title: 'Lab 2', kind: 'deep', start: 540, end: 600, items: []}),
    changeLabel({kind: 'deep', title: 'Lab', start: 540, end: 600, items: []}, {title: 'Lab', kind: 'deep', start: 540, end: 600, items: [{id: 'a', text: 'goggles', done: false}]}),
    changeLabel({kind: 'deep', title: 'Lab', start: 540, end: 600, items: [{id: 'a', text: 'goggles', done: false}]}, {title: 'Lab', kind: 'deep', start: 540, end: 600, items: [{id: 'a', text: 'goggles', done: true}]}),
    changeLabel({kind: 'deep', title: 'Lab', start: 540, end: 600, items: [{id: 'a', text: 'goggles', done: false}, {id: 'b', text: 'notes', done: false}]}, {title: 'Lab', kind: 'deep', start: 540, end: 600, items: []}),
    changeLabel({kind: 'deep', title: 'Lab', start: 540, end: 600, items: []}, {title: 'Lab 2', kind: 'social', start: 600, end: 660, items: []}),
  ];
  console.log(JSON.stringify(out));
})();
"""
        cls.out = run_node(script)
        cls.merge = run_node(cls.pure + """
const B = (id, start, items) => ({id, type: 'deep', title: id, start, end: '23:00', ...(items ? {items} : {})});
const I = (id, done = false) => ({id, kind: 'own', text: id, done});
const show = v => v === CONFLICT ? 'CONFLICT' : v;
const left = {blocks: [B('a', '09:00'), B('b', '10:00', [I('i1'), I('i2')]), B('c', '11:00')]};
const moved = {blocks: [B('a', '09:30'), B('b', '10:00', [I('i1'), I('i2')]), B('c', '11:00')]};
console.log(JSON.stringify({
  // nothing else changed: the value before, itself
  exact: rebase(moved, moved, left) === left,
  untouched: rebase(left, moved, left) === moved,
  // a block added elsewhere stays; mine goes back
  added: show(rebase(moved, {blocks: [...moved.blocks, B('z', '05:00')]}, left)).blocks.map(b => b.id + '@' + b.start),
  // the block I moved was moved again, or is gone
  movedAgain: show(rebase(moved, {blocks: [B('a', '12:00'), moved.blocks[1], moved.blocks[2]]}, left)),
  goneElsewhere: show(rebase(moved, {blocks: [moved.blocks[1], moved.blocks[2]]}, left)),
  // an item ticked elsewhere in another block stays
  tickElsewhere: show(rebase(moved, {blocks: [moved.blocks[0], B('b', '10:00', [I('i1', true), I('i2')]), moved.blocks[2]]}, left)).blocks.map(b => b.start + (b.items || []).map(i => +i.done).join('')),
  // a block I deleted goes back in its place, between what is still there, with what was added elsewhere kept
  restored: show(rebase({blocks: [left.blocks[0], left.blocks[2]]}, {blocks: [left.blocks[0], B('z', '05:00'), left.blocks[2]]}, left)).blocks.map(b => b.id),
  restoredFirst: show(rebase({blocks: [left.blocks[1]]}, {blocks: [left.blocks[1], B('z', '05:00')]}, {blocks: [left.blocks[0], left.blocks[1]]})).blocks.map(b => b.id),
  itemBack: show(rebase({blocks: [B('b', '10:00', [I('i1'), I('i3')])]}, {blocks: [B('b', '10:00', [I('i1'), I('i3', true)])]}, {blocks: [B('b', '10:00', [I('i1'), I('i2'), I('i3')])]})).blocks[0].items.map(i => i.id + +i.done),
  // taking back an add: only the block as I left it
  addUndone: show(rebase({blocks: [B('a', '09:00'), B('n', '13:00', [])]}, {blocks: [B('a', '09:00'), B('n', '13:00', []), B('z', '05:00')]}, {blocks: [B('a', '09:00')]})).blocks.map(b => b.id),
  addChanged: show(rebase({blocks: [B('n', '13:00', [])]}, {blocks: [B('n', '13:00', [I('x')])]}, null)),
  // a date that had nothing, and a meal's change beside another meal's
  toNothing: show(rebase({blocks: [B('n', '13:00', [])]}, {blocks: [B('n', '13:00', [])], meals: {lunch: {off: true}}}, null)),
  meals: show(rebase({meals: {lunch: {start: '15:30', end: '16:30'}}}, {meals: {lunch: {start: '15:30', end: '16:30'}, dinner: {off: true}}}, null)),
  mealClash: show(rebase({meals: {lunch: {start: '15:30', end: '16:30'}}}, {meals: {lunch: {start: '14:00', end: '15:00'}}}, null)),
  mealItems: show(rebase({meals: {lunch: {start: '15:30', end: '16:30'}}}, {meals: {lunch: {start: '15:30', end: '16:30', items: [I('call')]}}}, null)),
  // the settings: one hour each
  hours: [show(rebase({day_start: 7, day_end: 24}, {day_start: 7, day_end: 23}, {day_start: 5, day_end: 24})), show(rebase({day_start: 7, day_end: 24}, {day_start: 8, day_end: 24}, {day_start: 5, day_end: 24}))],
  same: [same({a: 1, b: [1, {c: 2}]}, {b: [1, {c: 2}], a: 1}), same({a: 1}, {a: 1, b: undefined}), same([1, 2], [2, 1]), same(null, undefined), same({}, null), same('5', 5)],
}));
""")

    def test_a_step_goes_back_and_forth_exactly(self):
        self.assertEqual(self.out["move"], {"offered": "function", "isStep": True, "undone": True, "toast": "Undid: moved “Pickleball” to 7:30 PM [Redo]",
                                            "redone": True, "toast2": "Redid: moved “Pickleball” to 7:30 PM [Undo]"})

    def test_a_deleted_block_comes_back_in_its_place(self):
        self.assertEqual(self.out["deleted"], {"gone": True, "back": True, "order": ["blockaaaa1", "blockbbbb2", "blockcccc3"]})

    def test_one_action_is_one_step_whatever_it_saves(self):
        b = self.out["both"]
        self.assertEqual(b["oneStep"], 1)
        self.assertTrue(b["dropped"])
        # The week lands before the date that depends on it, on the way back too.
        self.assertEqual(b["posts"][-2:], ["week:wed", "day:2026-11-11"])
        self.assertEqual(b["undoPosts"], ["week:wed", "day:2026-11-11"])
        self.assertTrue(b["back"])
        self.assertTrue(b["allBack"])

    def test_another_devices_change_is_never_overwritten(self):
        self.assertEqual(self.out["other"], {"toast": "Undid: moved “Pickleball” to 7:30 PM [Redo]", "mine": ["19:00", "20:15"], "theirs": True, "local": True})
        self.assertEqual(self.out["clash"], {"toast": "Can't undo: moved “Pickleball” to 7:30 PM. It was changed somewhere else since.", "posts": [],
                                             "stored": "21:00", "shown": "21:00", "left": 0})

    def test_the_defaults_go_back_to_no_key(self):
        s = self.out["settings"]
        self.assertEqual(s["saved"], {"day_start": 7, "day_end": 23})
        self.assertEqual(s["undone"], [False, {"day_start": 5, "day_end": 24}, ["settings removed"], None])
        self.assertEqual(s["redone"], {"day_start": 7, "day_end": 23})

    def test_a_failed_save_is_put_back_and_is_no_step(self):
        self.assertEqual(self.out["fail"], {"shownAtOnce": "21:00", "putBack": True, "steps": 0, "toast": True})

    def test_the_way_back_fails_safely(self):
        fail = "Couldn't undo that. Check your connection and try again."
        self.assertEqual(self.out["down"], {"toast": fail, "same": True, "posts": 0, "top": "moved “Concepts” to 9:00 PM"})
        self.assertEqual(self.out["refused"], {"toast": fail, "same": True, "top": "moved “Concepts” to 9:00 PM"})
        self.assertEqual(self.out["retried"], {"toast": "Undid: moved “Concepts” to 9:00 PM [Redo]", "start": "20:15"})

    def test_the_way_back_shows_where_it_happened(self):
        self.assertEqual(self.out["where"], {"wentTo": "2026-11-11", "refocused": "block:blockcccc3"})

    def test_no_change_no_step_and_a_step_inside_a_step(self):
        self.assertIsNone(self.out["none"])
        self.assertIsNone(self.out["inner"])
        self.assertEqual(self.out["nested"], {"steps": 1, "label": "outer", "outer": "function", "title": "Concepts"})

    def test_the_editors_save_is_named_for_what_it_changed(self):
        self.assertEqual(self.out["labels"], [
            "moved Lunch to 3:30 PM", "set Lunch’s place to “Thai place”", "changed “Lab” to 9:00–10:30 AM", "renamed “Lab” to “Lab 2”",
            "added “goggles” to “Lab”", "ticked “goggles” in “Lab”", "removed 2 things from “Lab”", "edited “Lab 2”"])

    def test_only_the_steps_own_change_is_taken_back(self):
        m = self.merge
        self.assertTrue(m["exact"])
        self.assertTrue(m["untouched"])
        self.assertEqual(m["added"], ["a@09:00", "b@10:00", "c@11:00", "z@05:00"])
        self.assertEqual((m["movedAgain"], m["goneElsewhere"]), ("CONFLICT", "CONFLICT"))
        self.assertEqual(m["tickElsewhere"], ["09:00", "10:0010", "11:00"])
        self.assertEqual(m["restored"], ["a", "b", "z", "c"])
        self.assertEqual(m["restoredFirst"], ["a", "b", "z"])
        self.assertEqual(m["itemBack"], ["i10", "i20", "i31"])
        self.assertEqual(m["addUndone"], ["a", "z"])
        self.assertEqual(m["addChanged"], "CONFLICT")
        self.assertEqual(m["toNothing"], {"meals": {"lunch": {"off": True}}})
        self.assertEqual(m["meals"], {"meals": {"dinner": {"off": True}}})
        self.assertEqual(m["mealClash"], "CONFLICT")
        self.assertEqual(m["mealItems"], {"meals": {"lunch": {"items": [{"id": "call", "kind": "own", "text": "call", "done": False}]}}})
        self.assertEqual(m["hours"], [{"day_start": 5, "day_end": 23}, "CONFLICT"])
        self.assertEqual(m["same"], [True, True, False, True, False, False])
