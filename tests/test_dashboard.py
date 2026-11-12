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
        # Checked at the click, and again once the server itself has said where the page is: a link
        # drawn from the last visit's copy is not sent on that copy's word.
        self.assertRegex(JS, r"if \(op\) \{ e\.preventDefault\(\); if \(REMOTE\) return; return known\.then\(\(\) => REMOTE \|\| api\('api/open'")

    def test_remote_and_public_come_from_platform_json_and_unknown_counts_as_remote(self):
        self.assertIn("fetch('platform.json', {cache: 'no-store'}).then(platformMode).catch(() => ({remote: true, public: false}))", JS)
        # Set with LIVE in one place (setPlace), before the page is drawn with the server's features.
        # A public copy serves no files (LIVE stays false); everywhere else LIVE is true, as before.
        # No answer (null) is a page that does not save.
        self.assertIn("function setPlace(at){\n  REMOTE = !!at?.remote;\n  PUBLIC = !!at?.public;\n  LIVE = !!at && !PUBLIC;\n  WRITE = at ? 'local' : null;\n}", JS)
        # The marks, the place and the tasks are asked for together; the answer sets the place, then
        # the server's features, then the marks and tasks.
        self.assertIn("Promise.all([getJson('api/marks'), where, getJson('api/tasks').catch(() => null)]).then(([m, at, t]) => ({marks: m, tasks: t?.tasks ?? null, at}));", JS)
        self.assertRegex(JS, r"if \(PHONE\) WRITE = 'cloud'; else setPlace\(got\.at\);\s*placed = true;\s*keepState\(\);\s*PROBING = false;\s*"
                             r"if \(PHONE\) \$\('#fab'\)\.hidden = false; else enableServerFeatures\(\);\s*"
                             r"if \(!took\(got\.marks, got\.tasks\) && moved\) refresh\(\);")
        # Set nowhere else (besides their declarations).
        self.assertEqual(len(re.findall(r"^\s+PUBLIC = ", JS, re.M)), 1)
        self.assertEqual(len(re.findall(r"^\s+LIVE = ", JS, re.M)), 1)

    def test_no_read_only_banner_while_the_page_asks_where_it_is(self):
        # A slow first answer (a cold public site) once showed "Read-only view" on a page that saves.
        self.assertIn("const banner = LIVE || WRITE || PROBING ? '' : LOCAL_FILES", JS)
        self.assertIn("  PROBING = !PHONE && !LOCAL_FILES;\n  render();\n}", JS)
        # Asked, answered or not: drawn again without it, so a page that cannot save still says so.
        # (Answered, it is drawn by took or refresh, above; one drawn from a copy goes back to what
        # it is without the copy.)
        self.assertRegex(JS, r"\}, \(\) => \{\s*(//[^\n]*\s*)*PROBING = false;\s*if \(copy\) forgetCopy\(\); else render\(\);\s*\}\)\.finally\(\(\) => \{\s*"
                             r"if \(!copy && !PHONE\) \{ showSyncbox\(\); emit\('ready'\); \}")

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
        # Once the server has answered, or at once when the page is drawn from the last visit's copy
        # of its answer; never twice.
        self.assertRegex(JS, r"\.finally\(\(\) => \{\s*if \(!copy && !PHONE\) \{ showSyncbox\(\); emit\('ready'\); \}")
        self.assertIn("if (copy && !PHONE) { enableServerFeatures(); showSyncbox(); emit('ready'); }", JS)
        self.assertEqual(JS.count("emit('ready')"), 3)
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
        # icon with its name in the label, and a block cut by the hours shown is marked so.
        self.assertIn('aria-label="${esc(spoken(e))}"></button>', PLANNER)
        self.assertIn("e.cutTop && 'cut-top', e.cutBottom && 'cut-bottom'", PLANNER)
        self.assertIn(".pblock.cut-top{border-top:2px dashed var(--pb-edge)", HTML)
        # Items a block does not show are counted: "+N" in a chip of its own.
        self.assertRegex(PLANNER, r"\['pb-n', '\+' \+ n\]")
        # The kind's letter is gone from the bars (2026-11-11): every block has its kind's icon, drawn
        # by the page's CSS, alone in the middle of a column too narrow for words.
        self.assertNotRegex(PLANNER + HTML, r"\bINITIAL\b|\bpb-ini\b|\bpb-ki\b")
        self.assertRegex(HTML, r"\.pblock\.nar::after\{left:50%;top:50%;[^}]*mask-size:12px 12px\}")
        self.assertRegex(HTML, r"\.pblock::after\{background:currentColor;-webkit-mask:var\(--pb-icon\)")
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
        # Changed 2026-11-11: a title is no longer cut to make room. The head is one line that wraps
        # and shows its first line only, so the chip goes first, then the time, then the title is cut;
        # in a drag, where the time is what is watched, the title gives way to it as before.
        head = re.search(r"^\.pb-head\{[^}]*\}", HTML, re.M).group(0)
        for part in ("flex-wrap:wrap", "overflow:hidden", "height:1lh"):
            self.assertIn(part, head)
        self.assertRegex(HTML, r"(?m)^\.pb-head \.pb-title\{flex:0 1 auto\}")
        self.assertRegex(HTML, r"(?m)^\.pb-head \.pb-time\{flex:none\}")
        self.assertRegex(HTML, r"(?m)^\.pblock\.dragging \.pb-head\{flex-wrap:nowrap\}")
        self.assertRegex(HTML, r"(?m)^\.pblock\.dragging \.pb-head \.pb-title\{flex-shrink:\d{4,};min-width:2\.5em\}")
        # Dark: the card's overdue status and links keep 4.5:1 on the page's surface.
        self.assertIn(':root:is([data-theme="dark"],[data-theme="red"]) dialog.pdetail{background:var(--surface)}', HTML)
        # A meal's place set for one day says so.
        self.assertIn("else if (meal && e.placeChanged) notes.push(`Place changed for ${thisDay(shown)} only`);", PLANNER)

    def test_block_kinds_use_the_theme_tokens(self):
        # Soft cells, vivid bars (2026-11-11): each kind of block is a bar in its own gradient with
        # its own ink, an edge colour and an icon, all from the theme's tokens.
        for kind in ("meal", "deep", "social", "other"):
            panel = "--k-deep-panel" if kind == "deep" else "--k-panel"
            self.assertIn(f".k-{kind}{{--pb-a:var(--k-{kind}-a);--pb-b:var(--k-{kind}-b);--pb-ink:var(--k-{kind}-ink);"
                          f"--pb-ink2:var(--k-{kind}-ink2);--pb-edge:var(--k-{kind}-edge);--pb-panel:var({panel});--pb-icon:var(--ic-{kind})}}", HTML)
        block = re.search(r"\.pblock\{[^}]*\}", HTML).group(0)
        self.assertIn("background:var(--pb-gloss),linear-gradient(100deg,var(--pb-a),var(--pb-b));color:var(--pb-ink);", block)
        # Nothing a drag moves every frame is blurred.
        self.assertNotIn("backdrop-filter", block)
        self.assertNotIn("blur(", block)
        # The now line: dashed, in the accent, under the bars, from a pill that says the time.
        self.assertIn(".pnow{position:absolute;left:0;right:0;z-index:-1;height:2px;margin-top:-1px;border-radius:1px;"
                      "background:repeating-linear-gradient(90deg,var(--accent) 0 7px,transparent 7px 12px);", HTML)
        self.assertIn(".pnow::before{content:attr(data-now);", HTML)
        self.assertIn("el.dataset.now = clock(m, false);", PLANNER)

    def test_the_hours_are_soft_cells_and_the_past_is_hatched(self):
        # A cell an hour, from gradients alone, in the theme's --cell; the same shape masks the
        # hatching of today's hours gone by, which ends at --now (set with the now line, today only).
        self.assertIn("background:var(--cell-shape);", HTML)
        self.assertIn("calc(100% - 2px - var(--cr)),transparent 0) 0 0/100% var(--hour,48px),", HTML)   # the band between the corners
        self.assertEqual(HTML.count(" var(--hour,48px) repeat-y"), 5)   # the band between the sides, and four corners
        self.assertIn("height:min(var(--now,0px),100%)", HTML)
        self.assertIn("-webkit-mask:var(--cell-shape);mask:var(--cell-shape)", HTML)
        self.assertIn("if (on) grid.style.setProperty('--now', nowTop() + 'px'); else grid.style.removeProperty('--now');", PLANNER)
        # The block that is on now says so, each minute.
        self.assertIn("for (const b of grid.querySelectorAll('.pblock[data-ref]')) b.classList.toggle('now', live.has(b.dataset.ref));", PLANNER)
        self.assertIn('.pblock.now .pb-head::after{content:"\\2022\\00a0Now";margin-left:auto}', HTML)
        # The hour label the now line's pill sits on gives way to it; one it would only touch steps
        # aside (planner.js says which, each minute; the page's CSS does it).
        self.assertRegex(PLANNER, r"const NOW_HIDE_PX = 9;")
        self.assertRegex(PLANNER, r"const NOW_CLEAR_PX = 16;")
        self.assertRegex(PLANNER, r"h\.dataset\.now = Math\.abs\(d\) < NOW_HIDE_PX \? 'at' : Math\.abs\(d\) < NOW_CLEAR_PX \? d < 0 \? 'above' : 'below' : '';")
        self.assertRegex(HTML, r'\.phour\[data-now="at"\][^{]*\{visibility:hidden\}')
        self.assertRegex(HTML, r'\.phour\[data-now="above"\]\{--dy:-\d+px\}\.phour\[data-now="below"\]\{--dy:\d+px\}')
        self.assertNotIn("near-now", PLANNER + HTML)

    def test_the_week_strip_shows_and_picks_a_day(self):
        # Seven buttons, made once and kept: only their date and state change, so one that has the
        # focus keeps it with nothing found again after a redraw.
        self.assertRegex(PLANNER, r'<div class="ph-week" id="planDays" role="group" aria-label="The week of this day">\$\{WD_NAME\.map\(n => `<button type="button" class="pday">')
        self.assertRegex(PLANNER, r"const dayPills = \[\.\.\.els\.days\.children\];")
        self.assertNotRegex(PLANNER, r"els\.days\.innerHTML")
        self.assertRegex(PLANNER, r"const sun = addDays\(shown, -fromIso\(shown\)\.getDay\(\)\);")
        self.assertRegex(PLANNER, r"b\.dataset\.pday = d;")
        # A click on one shows its day, through the planner's one click handler.
        self.assertRegex(PLANNER, r"const day = t\.closest\('\[data-pday\]'\);")
        self.assertRegex(PLANNER, r"if \(day\) \{ scrolledFor = null; return setDate\(day\.dataset\.pday\); \}")
        # One stop for Tab, on the day on show, which is the current date for a screen reader; each is
        # read as its full date, today said so; today is marked by more than colour.
        self.assertRegex(PLANNER, r"b\.tabIndex = on \? 0 : -1;")
        self.assertRegex(PLANNER, r"if \(on\) b\.setAttribute\('aria-current', 'date'\); else b\.removeAttribute\('aria-current'\);")
        self.assertRegex(PLANNER, r"b\.setAttribute\('aria-label', longDate\(d\) \+ \(today \? ', today' : ''\)\);")
        self.assertNotIn("aria-pressed", PLANNER[PLANNER.index("const dayPills"):PLANNER.index("const FOCUS_KEYS")])
        self.assertIn('.pday.today::after{content:"";', HTML)
        # The same controls as before, each still a button with its name.
        for control in ('data-pstep="-1" aria-label="Previous day"', 'data-pstep="1" aria-label="Next day"', 'id="planToday"',
                        'id="planWeek"', 'id="planAdd" aria-label="Add a block"', 'id="planDate" aria-live="polite"'):
            self.assertIn(control, PLANNER)

    def test_the_two_apps_cross_fade(self):
        # QuantPrep's three rules exactly (its styles.css, and its docs/13 section 5.1.2), so the two
        # pages pair up: only for those who have not asked for less motion, and one copy of each.
        block = re.search(r"^@media \(prefers-reduced-motion: no-preference\)\{\n(.*?)\n\}$", HTML, re.M | re.S).group(1)
        self.assertEqual([line.strip() for line in block.splitlines()], [
            "@view-transition{navigation:auto}",
            ".topbar{view-transition-name:app-bar}",
            "::view-transition-group(*),::view-transition-old(*),::view-transition-new(*){animation-duration:160ms}"])
        self.assertEqual(HTML.count("@view-transition"), 1)
        self.assertEqual(HTML.count("view-transition-name"), 1)
        self.assertEqual(HTML.count("::view-transition-"), 3)
        self.assertNotIn("navigation: none", HTML)
        # The bar that holds still is the page's one header.
        self.assertEqual(HTML.count('<header class="topbar">'), 1)

    def test_the_bar_sits_where_preps_does(self):
        # Prep always keeps the scroll bar's room; without the same rule a School page too short to
        # scroll would sit half a scroll bar off Prep's bar where scroll bars take room.
        self.assertRegex(HTML, r"(?m)^html\{overflow-y:scroll;")

    def test_the_grid_keeps_the_border_the_fit_counts(self):
        # planner.js fits the day into the room less TIME_PAD: the timeline's two margins and the
        # grid's 1 px border, which is not drawn.
        self.assertIn("const TIME_PAD = 15;           // the timeline's margins above and below (.ptime) and the grid's border", PLANNER)
        self.assertIn(".ptime{position:relative;margin:7px 0}", HTML)
        self.assertRegex(HTML, r"(?m)^\.pgrid\{[^}]*;border-bottom:1px solid transparent;")


def _lum(hex6):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex6[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(a, b):
    x, y = sorted((_lum(a), _lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def _rgba(value):
    """A token's colour as (r, g, b, alpha): #rrggbb or rgb(r g b / a)."""
    value = value.strip()
    if value.startswith("#"):
        return (*(int(value[i:i + 2], 16) for i in (1, 3, 5)), 1.0)
    r, g, b, a = re.fullmatch(r"rgb\((\d+) (\d+) (\d+)(?: / ([\d.]+))?\)", value).groups()
    return int(r), int(g), int(b), float(a or 1)


def _over(top, bottom):
    """top (with its alpha) drawn over an opaque bottom, as a hex string."""
    a = top[3]
    return "".join(f"{round(t * a + b * (1 - a)):02x}" for t, b in zip(top[:3], bottom[:3]))


def _theme_tokens(theme):
    """Every --token of a theme: light's, with the theme's own on top."""
    light = HTML[HTML.index(":root{"):HTML.index(':root[data-theme="dark"]{')]
    text = light
    if theme != "light":
        start = HTML.index(f':root[data-theme="{theme}"]{{')
        text += HTML[start:HTML.index("\n}", start)]
    return {name: value.strip() for name, value in re.findall(r"--([\w-]+):([^;]+);", text)}


class BarColorsTest(unittest.TestCase):
    """Soft cells, vivid bars (2026-11-11): in light, dark and red, what is written on a bar keeps
    4.5:1 on both ends of its gradient, under the sheen at its strongest and on its nested panel."""

    def test_ink_stays_readable_on_every_bar(self):
        for theme in ("light", "dark", "red"):
            t = _theme_tokens(theme)
            gloss = re.search(r"rgb\([^)]*\)", t["pb-gloss"])
            gloss = _rgba(gloss.group(0)) if gloss else (0, 0, 0, 0.0)
            for kind in ("meal", "deep", "social", "other"):
                panel = _rgba(t["k-deep-panel" if kind == "deep" else "k-panel"])
                for end in ("a", "b"):
                    fill = _rgba(t[f"k-{kind}-{end}"])
                    grounds = {"fill": _over(fill, fill), "sheen": _over(gloss, fill), "panel": _over(panel, fill)}
                    for ink in ("ink", "ink2"):
                        color = t[f"k-{kind}-{ink}"].lstrip("#")
                        for where, ground in grounds.items():
                            self.assertGreaterEqual(_contrast(color, ground), 4.5, (theme, kind, end, ink, where))
            # The chip on a bar, the day on show in the week strip, and the hour labels on the tray.
            self.assertGreaterEqual(_contrast(t["pb-chip-ink"].lstrip("#"), t["pb-chip"].lstrip("#")), 4.5, theme)
            self.assertGreaterEqual(_contrast(t["on-ink-pill"].lstrip("#"), t["ink-pill"].lstrip("#")), 4.5, theme)
            for text in ("text", "muted"):
                for ground in ("tray", "cell"):
                    self.assertGreaterEqual(_contrast(t[text].lstrip("#"), t[ground].lstrip("#")), 4.5, (theme, text, ground))

    def test_red_bars_have_no_blue(self):
        t = _theme_tokens("red")
        mine = [name for name in t if name.startswith(("k-", "pb-", "cell", "hatch", "tray", "neu", "ink-pill", "on-ink-pill"))]
        self.assertGreater(len(mine), 35)
        for name in mine:
            for value in re.findall(r"#[0-9a-f]{6}|rgb\([^)]*\)", t[name]):
                self.assertEqual(_rgba(value)[2], 0, (name, value))
            self.assertNotIn("white", t[name])


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
        # Four blocks with 90, 120 and 120 minutes free between them.
        spaced = [{"ref": "a", "start": 540, "end": 630}, {"ref": "b", "start": 720, "end": 780},
                  {"ref": "c", "start": 900, "end": 960}, {"ref": "d", "start": 1080, "end": 1140}]
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
  timeFits: [timeFits(300, 'Lunch · Chipotle', '· 4–5 PM', iconPx(300)), timeFits(197, 'Coffee with Sam', '· 4:30–5:30 PM', iconPx(197)),
             timeFits(197, 'Gym', '4:00–5:30 PM', iconPx(197)), timeFits(197, 'Laundry and pack', '· 10:30–11:30 PM', iconPx(197) + chipPx(['pb-n', '+2'])),
             timeFits(87, '', '4:00–5:30 PM', iconPx(87)), timeFits(400, 'Review notes', '8:30–10:15 AM', iconPx(400))],
  room: [iconPx(275), iconPx(276), chipPx(null), chipPx(['pb-n', '+2']), chipPx(['pb-st', '1 of 3 done'])],
  free36: freeGaps(place({json.dumps(spaced)}, 300, 1440, 36)),
  freeLater: freeGaps(place({json.dumps(spaced)}, 300, 1440, 36), 781),
  free22: freeGaps(place({json.dumps(spaced)}, 300, 1440, 22)).map(g => [g.from, g.to, g.h >= 22]),
  freeUnder: freeGaps(place({json.dumps(spaced + [{"ref": "long", "start": 540, "end": 1050}])}, 300, 1440, 36)),
  freeShort: freeGaps(place([{{ref: 'a', start: 540, end: 600}}, {{ref: 'b', start: 689, end: 749}}], 300, 1440, 36)),
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
        # A line has its time only where the whole title, the icon and the chip leave it room: a
        # title is never cut for it (2026-11-11). A narrow tall block writes its time in the compact form.
        self.assertEqual(self.lay["timeFits"], [True, False, True, False, False, True])
        # The icon's room (alone up to 275 px of block, in its bubble past that) and a chip's.
        self.assertEqual(self.lay["room"], [17, 27, 0, 32, 94])

    def test_a_free_stretch_between_two_blocks_gets_a_card(self):
        # An hour and a half or more between two blocks: the card lies between them, 5 px under the
        # one before and 4 px over the one after. Nothing before the first block or after the last.
        self.assertIn("const FREE_MIN = 90;", PLANNER)
        self.assertEqual(self.lay["free36"], [{"from": 630, "to": 720, "top": 201, "h": 47}, {"from": 780, "to": 900, "top": 291, "h": 65},
                                              {"from": 960, "to": 1080, "top": 399, "h": 65}])
        # Today, only time still to come: a stretch that began before now has none.
        self.assertEqual([g["from"] for g in self.lay["freeLater"]], [960])
        self.assertRegex(PLANNER, r"freeGaps\(inView, isToday\(shown\) \? minutesNow\(\) : -Infinity\)")
        self.assertRegex(PLANNER, r"for \(const f of grid\.querySelectorAll\('\.pfree'\)\) f\.hidden = isToday\(shown\) && \+f\.dataset\.from < m;")
        # At the least hour (22 px) a card still has room for its words; a block lying over a gap
        # leaves none, and 89 minutes are not a stretch.
        self.assertEqual(self.lay["free22"], [[630, 720, True], [780, 900, True], [960, 1080, True]])
        self.assertEqual(self.lay["freeUnder"], [])
        self.assertEqual(self.lay["freeShort"], [])
        # Decoration only: no role, hidden from screen readers, and the pointer goes through it, so a
        # click or a drag on free time still makes a block.
        self.assertRegex(PLANNER, r'<div class="pfree" aria-hidden="true" data-from="\$\{g\.from\}"')
        rule = re.search(r"^\.pfree\{[^}]*\}", HTML, re.M).group(0)
        self.assertIn("pointer-events:none", rule)
        self.assertIn("border:1.5px dashed var(--free-line)", rule)
        self.assertNotIn(".pfree::", HTML)   # no arcs: nothing crosses its words

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


# The page's sync controls with the page stood in for: Sync now and its line, the label, timers
# that are listed instead of run (later), and api/sync answering what the test says (answers).
SYNC_PAGE = """
const control = () => ({hidden: true, onclick: null, disabled: false, textContent: '', title: '', attrs: {}, on: {}, focusVisible: false, style: {}, dataset: {},
  classList: {toggle(){}}, addEventListener(type, fn){ this.on[type] = fn; }, setAttribute(k, v){ this.attrs[k] = v; }, removeAttribute(k){ delete this.attrs[k]; },
  matches(sel){ return sel === ':focus-visible' && this.focusVisible; }, getBoundingClientRect: () => ({left: 1150, right: 1234, top: 12, bottom: 44})});
const els = {'#syncBtn': control(), '#fab': control(), '#sync': control(), '#syncNote': Object.assign(control(), {offsetWidth: 300, offsetHeight: 40})};
const $ = s => els[s] || null;
const later = [];
let timers = 0;
const setTimeout = (fn, ms) => { later.push({fn, ms, id: ++timers}); return timers; };
const clearTimeout = id => { const i = later.findIndex(l => l.id === id); if (i >= 0) later.splice(i, 1); };
const page = {hidden: false, on: {}};
const document = {get hidden(){ return page.hidden; }, documentElement: {clientWidth: 1280}, addEventListener(type, fn){ (page.on[type] = page.on[type] || []).push(fn); }};
const window = {innerHeight: 800, on: {}, addEventListener(type, fn){ this.on[type] = fn; }};
const calls = [], toasts = [];
let answers = {running: false}, kept = null;
const getJson = path => { calls.push('GET ' + path); return Promise.resolve(path === 'api/tasks' ? {tasks: {}} : JSON.parse(JSON.stringify(answers))); };
const api = path => { calls.push('POST ' + path); return Promise.resolve({}); };
const toast = m => toasts.push(m), refreshTasks = () => {};
const sessionStorage = {getItem: () => kept, setItem(){}, removeItem(){}};
const location = {reload(){ calls.push('load'); }};
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise(r => globalThis.setTimeout(r, 0)); };
let LIVE = true, PUBLIC = false, PHONE = false, D = {generated_at: '2026-11-10T12:00:00+00:00'}, dataSeen = true;
const holds = [], now = new Date('2026-11-10T14:00:00Z'), ago = () => '2h ago';
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
const asLine = text => text ? '<div class="pd-line">' + text + '</div>' : '';
"""


def sync_page(body):
    """dashboard.js's own Sync now section and the label's drawing, on that page."""
    return run_node(SYNC_PAGE + source_of("function showSynced(){") + "\n" + JS[JS.index(SYNC_START):JS.index(SYNC_END)]
                    + "\nconst out = {};\n(async () => {\n" + body + "\nconsole.log(JSON.stringify(out));\n})();\n")


@unittest.skipUnless(NODE, "Node is not installed")
class SyncNowTest(unittest.TestCase):
    """dashboard.js's Sync now, run under Node with the page's elements and requests stood in for."""

    @classmethod
    def setUpClass(cls):
        cls.out = sync_page("""
for (const [name, pub] of [['mac', false], ['public', true]]) {
  PUBLIC = pub; LIVE = !pub;
  calls.length = 0;
  Object.assign(els['#syncBtn'], {hidden: true, onclick: null});
  els['#fab'].hidden = true;
  enableServerFeatures();
  out[name] = {syncShown: !els['#syncBtn'].hidden, syncClick: !!els['#syncBtn'].onclick, fabShown: !els['#fab'].hidden, calls: [...calls]};
  await settle();
  out[name].later = later.map(l => l.ms);
  later.length = 0;
}
""")

    def test_on_the_mac_and_from_another_device_as_before(self):
        # (The tasks are asked for with the marks, at the start: see BootTest.)
        self.assertEqual(self.out["mac"], {"syncShown": True, "syncClick": True, "fabShown": True,
                                           "calls": ["GET api/sync"], "later": [60000]})

    def test_a_public_copy_has_no_sync_now(self):
        # Marks and tasks work (the + button, the tasks); nothing asks for a sync or its state, then
        # or later.
        self.assertEqual(self.out["public"], {"syncShown": False, "syncClick": False, "fabShown": True,
                                              "calls": [], "later": []})

    def test_a_failed_sync_points_to_the_sync_log(self):
        # The server adds each sync's output to state/sync.log (server.py run_sync); the toast says so.
        out = sync_page("kept = JSON.stringify({ok: false, output: 'Traceback: boom'}); enableServerFeatures(); out.toasts = toasts;")
        self.assertEqual(out["toasts"], ["Sync failed. See state/sync.log"])

    def test_sync_now_waits_for_its_sync_and_then_loads_the_page(self):
        # The one load the page makes without being asked to: after Sync now, pressed on this page.
        out = sync_page("""
enableServerFeatures(); await settle();
later.length = 0; calls.length = 0;
els['#syncBtn'].onclick(); await settle();
out.pressed = {calls: [...calls], later: later.map(l => l.ms), button: [els['#syncBtn'].disabled, els['#syncBtn'].textContent]};
// Its own wait is the only one asking from here on: the minute's look stands down.
answers = {running: true};
later.shift().fn(); await settle();
out.running = {calls: [...calls], later: later.map(l => l.ms)};
answers = {running: false, ok: true, output: '[schoolhub] 3 new'};
later.shift().fn(); await settle();
out.done = {calls: [...calls], later: later.map(l => l.ms)};
""")
        self.assertEqual(out["pressed"], {"calls": ["POST api/sync"], "later": [1500], "button": [True, "Syncing…"]})
        self.assertEqual(out["running"], {"calls": ["POST api/sync", "GET api/sync"], "later": [2000]})
        self.assertEqual(out["done"], {"calls": ["POST api/sync", "GET api/sync", "GET api/sync", "load"], "later": []})


@unittest.skipUnless(NODE, "Node is not installed")
class NextSyncNoteTest(unittest.TestCase):
    """One quiet line says when the Mac syncs next by itself (api/sync's `auto`): in the tooltip of
    "Synced 2h ago", and under Sync now for the pointer, the keyboard and a screen reader."""

    AT = "2026-11-10T21:34:00+00:00"

    @classmethod
    def setUpClass(cls):
        cls.out = sync_page("""
const AT = '2026-11-10T21:34:00+00:00';
out.time = new Date(AT).toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
const auto = (state, next_at = null) => ({running: state === 'running', data_at: D.generated_at, auto: {on: state !== 'off', every_hours: 12, state, next_at, last_good_at: null, failures: 0}});
out.lines = {};
for (const state of ['waiting', 'retrying', 'settling', 'due', 'offline', 'running', 'off', 'something new']) out.lines[state] = nextSyncNote(auto(state, ['waiting', 'retrying', 'settling', 'due'].includes(state) ? AT : null));
// A server from before it said (no auto), and a time that cannot be read.
out.lines.none = [nextSyncNote({running: false}), nextSyncNote(null), nextSyncNote(undefined)];
out.lines.noTime = [nextSyncNote(auto('waiting')), nextSyncNote(auto('retrying', 'soon'))];

// On the page: asked with the first look, said in the label's tooltip and for the button.
const btn = els['#syncBtn'], tip = els['#syncNote'], label = els['#sync'];
answers = auto('waiting', AT);
enableServerFeatures(); await settle();
const line = out.lines.waiting;
out.said = {title: label.title.split('\\n'), label: label.textContent, describes: btn.attrs['aria-describedby'], tipText: tip.innerHTML === asLine(line), tipHidden: tip.hidden};
// The keyboard's focus shows it at once, under the button and inside the window; Esc, and the focus leaving, send it away.
btn.focusVisible = true; btn.on.focus();
out.focused = {hidden: tip.hidden, text: tip.innerHTML === asLine(line), left: tip.style.left, top: tip.style.top, side: tip.dataset.side, maxWidth: tip.style.maxWidth};
page.on.keydown.forEach(fn => fn({key: 'a'})); out.otherKey = tip.hidden;
page.on.keydown.forEach(fn => fn({key: 'Escape'})); out.esc = tip.hidden;
btn.on.focus(); btn.on.blur(); out.blurred = tip.hidden;
// Focus a click gave is not the keyboard's.
btn.focusVisible = false; btn.on.focus(); out.clicked = tip.hidden;
// The pointer rests a moment first; leaving sooner shows nothing; a touch never does.
const n = later.length;
btn.on.pointerenter({pointerType: 'mouse'});
out.rest = [later.slice(n).map(l => l.ms), tip.hidden];
later.pop().fn(); out.rested = tip.hidden;
btn.on.pointerleave(); out.left = tip.hidden;
btn.on.pointerenter({pointerType: 'mouse'}); btn.on.pointerleave(); out.leftEarly = [later.slice(n).map(l => l.ms), tip.hidden];
btn.on.pointerenter({pointerType: 'touch'}); out.touch = later.slice(n).map(l => l.ms);
// A press, a scroll and the window's size changing send it away too.
for (const [name, go] of [['click', () => btn.on.click()], ['scroll', () => window.on.scroll()], ['resize', () => window.on.resize()]]) { btn.focusVisible = true; btn.on.focus(); const shown = !tip.hidden; go(); out[name] = [shown, tip.hidden]; }
// Near the window's edges it stays inside; with no room under the button it goes over it.
btn.getBoundingClientRect = () => ({left: 20, right: 104, top: 760, bottom: 792});
btn.on.focus(); out.edge = {left: tip.style.left, top: tip.style.top, side: tip.dataset.side}; btn.on.blur();

// Each look says it anew: another state, another line; none while a sync runs or where it is off.
const look = async a => { answers = a; later.splice(0).filter(l => l.ms >= 3000).forEach(l => l.fn()); await settle(); return {title: label.title.split('\\n').length, tipText: tip.innerHTML, describes: btn.attrs['aria-describedby'] || null}; };
out.retrying = await look(auto('retrying', AT));
btn.on.focus(); out.running = [!tip.hidden, await look(auto('running')), tip.hidden, btn.disabled];
out.off = await look(auto('off'));
btn.on.focus(); out.offFocus = tip.hidden;
// Never on a public copy or the phone site, even with a line in hand.
out.waitingAgain = await look(auto('waiting', AT));
PUBLIC = true; LIVE = false; showSynced(); btn.on.focus(); out.publicCopy = [label.title.split('\\n').length, tip.hidden];
PUBLIC = false; LIVE = false; PHONE = true; showSynced(); btn.on.focus(); out.phone = [label.title.split('\\n').length, tip.hidden];
""")

    def test_the_line_for_each_state(self):
        lines, t = self.out["lines"], self.out["time"]
        self.assertRegex(t, r"^\d{1,2}:34")
        self.assertEqual(lines["waiting"], f"Syncs by itself every 12 hours · next around {t}")
        self.assertEqual(lines["retrying"], f"Last sync didn't finish · trying again at {t}")
        self.assertEqual([lines["settling"], lines["due"]], ["Syncing in a moment"] * 2)
        self.assertEqual(lines["offline"], "Will sync when the network is back")
        # Nothing where the server does not sync by itself, while a sync runs (the button says so),
        # for a state the page does not know, or with a server that says nothing of it.
        self.assertEqual([lines["off"], lines["running"], lines["something new"], lines["none"]], ["", "", "", ["", "", ""]])
        self.assertEqual(lines["noTime"], ["Syncs by itself every 12 hours", "Last sync didn't finish · trying again soon"])

    def test_it_is_said_with_the_label_and_for_the_button(self):
        said, line = self.out["said"], self.out["lines"]["waiting"]
        # The label reads as before; its tooltip keeps the time itself and adds the line.
        self.assertEqual(said["label"], "Synced 2h ago")
        self.assertEqual(len(said["title"]), 2)
        self.assertEqual(said["title"][1], line)
        # Sync now is described by the line's own element (a screen reader reads it with the
        # button), which holds the line though it does not show: one line of the previews' kind.
        self.assertIn("const noteHtml = note => note ? `<div class=\"pd-line\">${esc(note)}</div>` : '';", JS)
        self.assertIn(".ptip .pd-line{margin:1px 0;font-size:12.5px}", HTML)
        self.assertEqual([said["describes"], said["tipText"], said["tipHidden"]], ["syncNote", True, True])
        self.assertIn('<div class="ptip" id="syncNote" role="tooltip" hidden></div>', HTML)
        self.assertIn('<span id="sync" class="sync"></span><button type="button" class="btn small" id="syncBtn" hidden>Sync now</button>', HTML)

    def test_the_keyboard_and_the_pointer_both_show_it(self):
        out = self.out
        # Under the button, their right edges in line (1234 - 300), 8 px below it (44 + 8).
        self.assertEqual(out["focused"], {"hidden": False, "text": True, "left": "934px", "top": "52px", "side": "below", "maxWidth": "calc(100vw - 16px)"})
        self.assertEqual([out["otherKey"], out["esc"], out["blurred"], out["clicked"]], [False, True, True, True])
        self.assertEqual(out["rest"], [[350], True])
        self.assertEqual([out["rested"], out["left"]], [False, True])
        self.assertEqual(out["leftEarly"], [[], True])
        self.assertEqual(out["touch"], [])
        for name in ("click", "scroll", "resize"):
            self.assertEqual(out[name], [True, True], name)
        # At the left edge and the bottom of the window: 8 px in, and over the button (760 - 8 - 40).
        self.assertEqual(out["edge"], {"left": "8px", "top": "712px", "side": "above"})

    def test_it_follows_each_answer_and_goes_where_there_is_none(self):
        out, t = self.out, self.out["time"]
        self.assertEqual(out["retrying"], {"title": 2, "tipText": f"""<div class="pd-line">Last sync didn't finish · trying again at {t}</div>""", "describes": "syncNote"})
        # A sync running: the line goes (shown or not), and the button says Syncing…
        self.assertEqual(out["running"], [True, {"title": 1, "tipText": "", "describes": None}, True, True])
        self.assertEqual(out["off"], {"title": 1, "tipText": "", "describes": None})
        self.assertTrue(out["offFocus"])

    def test_never_on_a_public_copy_or_the_phone_site(self):
        self.assertEqual(self.out["waitingAgain"]["title"], 2)
        self.assertEqual(self.out["publicCopy"], [1, True])
        self.assertEqual(self.out["phone"], [1, True])
        # Neither asks api/sync at all: only enableServerFeatures starts the looks, it stops at a
        # public copy, and the phone site never calls it.
        self.assertIn("  if (PUBLIC || syncBtn.onclick) return;", JS)
        self.assertIn("if (PHONE) $('#fab').hidden = false; else enableServerFeatures();", JS)
        self.assertIn("const watches = () => LIVE && !PUBLIC && !PHONE && !pressed && !document.hidden;", JS)
        self.assertIn("const noteHere = () => LIVE && !PUBLIC && !PHONE ? syncNote : '';", JS)


class SyncWordsTest(unittest.TestCase):
    """The sync runs by itself every 12 hours, and whenever you ask: nothing calls it nightly."""

    def test_nothing_says_nightly(self):
        for name in ("dashboard.js", "planner.js", "bar.js", "dashboard.html", "server.py", "README.md"):
            self.assertNotIn("nightly", (REPO / name).read_text(encoding="utf-8").lower(), name)

    def test_marks_speak_of_the_last_and_the_next_sync(self):
        self.assertIn("flagged: 'Marked done by you. The last sync found no submission, which is fine if it was handed in another way',", JS)
        self.assertIn("""return '<div class="note">Confirmed by the last sync.</div>';""", JS)
        self.assertIn("The next sync will double-check ${esc(a.platform)} for your submission.</div>`;", JS)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(NODE, "needs Node to run dashboard.js")
class MarkTest(unittest.TestCase):
    """A ✓ the last sync could not confirm still counts as done, not as needing attention."""

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
const SH = {same, addStep, offerStep, toast, setPlanner(){}, plannerState: 'on', mode: {WRITE: 'local'},
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


# ---- a preview on hover (planner.js "what the details say", "a preview on hover") ----
SAYS_START, SAYS_END = "  // ---- what the details say ----", "  // ---- the details card ----"
TIP_START, TIP_END = "  // ---- a preview on hover ----", "  // ---- the weekly form ----"


def tip_section():
    return PLANNER[PLANNER.index(TIP_START):PLANNER.index(TIP_END)]


def _texts(html):
    """The pieces of text in a piece of HTML, and the names given with aria-label."""
    return [t.strip() for t in re.split(r"<[^>]*>", html) if t.strip()]


class PreviewSourceTest(unittest.TestCase):
    """Resting the pointer on a block, a flag or their chips (or focusing one from the keyboard)
    shows its details beside it: where that is wired, and what it must never do."""

    def test_one_element_only_to_read(self):
        self.assertIn('<div class="ptip" id="planTip" role="tooltip" hidden></div>', HTML)
        rule = re.search(r"^\.ptip\{.*?\}$", HTML, re.M | re.S).group(0)
        # It never takes the pointer, floats over the page, and stays within the window.
        self.assertIn("pointer-events:none", rule)
        self.assertIn("position:fixed", rule)
        self.assertIn("max-width:min(300px,calc(100vw - 16px))", rule)
        self.assertIn(".ptip[hidden]{display:none}", HTML)
        # Described while it shows, by the block's own button; focus never moves into it.
        tip = tip_section()
        self.assertIn("tipButton(el)?.setAttribute('aria-describedby', 'planTip');", tip)
        self.assertIn("root.querySelector('[aria-describedby=\"planTip\"]')?.removeAttribute('aria-describedby')", tip)
        self.assertNotIn(".focus(", tip)
        self.assertNotIn("tabindex", tip.lower())
        self.assertIn("SH.markEmoji?.(tipEl);", tip)

    def test_what_has_a_preview_has_no_title(self):
        # A block, a flag and the chips of both carry the preview's key, and no title to say it twice.
        self.assertEqual(PLANNER.count("""data-tip="${esc('b:' + e.ref)}\""""), 2)   # a block, and its chip in the strip
        self.assertEqual(PLANNER.count("""data-tip="${esc('d:' + a.id)}\""""), 2)    # a flag, and a chip of something due
        drawn = [line for line in PLANNER.splitlines() if "data-tip=" in line or "data-open-ref=" in line or "data-plan-due=" in line and "<button" in line]
        self.assertGreaterEqual(len(drawn), 5)
        for line in drawn:
            self.assertNotIn(" title=", line)
        self.assertNotIn("const tip = ` title=", PLANNER)

    def test_the_card_and_the_preview_are_written_by_the_same_code(self):
        says = PLANNER[PLANNER.index(SAYS_START):PLANNER.index(SAYS_END)]
        self.assertIn("${detailsHtml(e, false)}", PLANNER[PLANNER.index(SAYS_END):PLANNER.index(TIP_START)])
        self.assertIn("return e && !e.off && !e.skip ? detailsHtml(e, true) : '';", tip_section())
        self.assertIn("return a ? dueHtml(a) : '';", tip_section())
        # Each fact is written in one place only.
        for fact in ("${esc(range(e.start, e.end))} · ${esc(duration(e.end - e.start))}", "'At ' + esc(e.place)", "notes.push(`Repeats every ${wdN}`)",
                     "'Due ' + esc(SH.fmtDue(a.due_at, true, a.all_day))", "const [st, cls] = workStatus(a);"):
            self.assertEqual(PLANNER.count(fact), 1, fact)
            self.assertIn(fact, says)

    def test_listeners_are_on_the_planner_and_the_page_and_one_timer_runs(self):
        # Blocks are drawn anew often: nothing is added to a block, and nothing is left running.
        tip = tip_section()
        added = re.findall(r"([\w.]+)\.addEventListener\('(\w+)'", tip)
        self.assertEqual(sorted(added), sorted([("root", "pointermove"), ("root", "pointerleave"), ("root", "focusin"), ("root", "focusout"),
                                                ("document", "pointerdown"), ("document", "keydown"), ("document", "focusin"),
                                                ("window", "scroll"), ("window", "resize"), ("window", "blur")]))
        self.assertEqual(tip.count("setTimeout("), tip.count("tipTimer = setTimeout("))
        self.assertEqual(tip.count("setTimeout("), 2)   # the wait before it shows, and before it goes
        for banned in ("setInterval", "requestAnimationFrame", "MutationObserver", "mouseover", "pointerover", ".onpointer", ".onmouse"):
            self.assertNotIn(banned, tip)
        self.assertNotIn("MutationObserver", PLANNER)
        self.assertIn("    clearTimeout(tipTimer);\n    tipTimer = 0;\n    aim = null;\n    if (!tip) return;", tip)

    def test_when_it_goes_and_when_it_never_comes(self):
        tip = tip_section()
        # No touch, no button down, nothing dragged, nothing open over the page.
        self.assertIn("if (e.pointerType === 'touch' || e.buttons) return;", tip)
        self.assertIn("const tipBlocked = () => !tipEl || SH.plannerState !== 'on' || !plan || !!drag || SH.drawerOpen() || !!document.querySelector('dialog[open]');", tip)
        # A press anywhere (seen before the timeline's own handler), Esc, a scroll, focus going elsewhere.
        self.assertIn("document.addEventListener('pointerdown', e => { tabbed = false; quietTip(tipKey(e.target)); }, true);", tip)
        self.assertIn("if (e.key === 'Escape' && (tip || aim)) quietTip((tip || aim).key);", tip)
        self.assertIn("window.addEventListener('scroll', () => { at = null; if (aim?.by !== 'focus') hideTip(); }, true);", tip)
        self.assertIn("      if (tip && !root.contains(e.target)) hideTip();", tip)
        # The keyboard's focus only, brought by Tab onto the block's own button: never focus the page
        # itself puts back (a redraw, a dialog closing, the window coming back to the front).
        self.assertIn("rest(back || (own && tabbed) ? on : null, 'focus');", tip)
        self.assertIn("      tabbed = e.key === 'Tab';", tip)
        self.assertIn("window.addEventListener('blur', () => { at = null; tabbed = false; hideTip(); });", tip)
        # The card and the drawer opening send it away; a redraw keeps it with the plan.
        self.assertIn("    if (det) closeDetails(false);\n    quietTip('b:' + entry.ref);", PLANNER)
        self.assertIn("    if (due) quietTip('d:' + due.dataset.planDue);\n    if (due) return SH.openDrawer(due.dataset.planDue, e.detail === 0);", PLANNER)
        self.assertIn("    syncDetails();\n    syncTip();\n  }", PLANNER)
        self.assertIn("const HOVER_MS = 350;", tip)

    def test_its_look_follows_the_theme_motion_and_transparency(self):
        rules = "\n".join(re.findall(r"^[^\n{]*\.(?:ptip|pd-tick|pd-rest|pd-notes)[^\n{]*\{[^}]*\}", HTML, re.M))
        self.assertIn("background:var(--glass-thick)", rules)
        self.assertIn("backdrop-filter:var(--glass-blur-thick)", rules)
        # Every color is a token, so Night's stay red (no blue) and reduced transparency makes it
        # solid (the glass tokens), as for the details card.
        self.assertNotRegex(rules, r"#[0-9a-fA-F]{3,8}\b")
        self.assertNotRegex(rules, r"rgba?\(|hsla?\(|(?<![-\w])(?:white|black|blue)(?![-\w])")
        self.assertIn(':root:is([data-theme="dark"],[data-theme="red"]) .ptip{background:var(--surface);border-color:var(--border-strong);-webkit-backdrop-filter:none;backdrop-filter:none}', HTML)
        self.assertRegex(HTML, r"@media \(prefers-reduced-transparency:reduce\)\{:root,:root\[data-theme\]\{--glass:var\(--surface\);--glass-thick:var\(--surface\);--glass-blur:none;--glass-blur-thick:none\}\}")
        # Nothing moves for those who ask for less motion.
        self.assertIn("animation:sh-tip-in var(--dur-1) var(--ease-out)", rules)
        self.assertIn("aside,dialog.task[open],dialog.pdetail[open],.ptip{animation:none}", HTML)


@unittest.skipUnless(NODE, "Node is not installed")
class PreviewFactsTest(unittest.TestCase):
    """What the preview says is what the details card says: planner.js's own detailsHtml and dueHtml,
    with the list stood in for."""

    @classmethod
    def setUpClass(cls):
        plan_pure = PLANNER[PLANNER.index(PLAN_START):PLANNER.index(PLAN_END)]
        says = PLANNER[PLANNER.index(SAYS_START):PLANNER.index(SAYS_END)]
        script = esc_source() + plan_pure + """
const at = (days, h) => { const d = new Date(); d.setDate(d.getDate() + days); d.setHours(h, 0, 0, 0); return d.toISOString(); };
const list = {
  'canvas:9': {id: 'canvas:9', name: 'HW 9 <proofs>', course: {name: '21-127 Concepts', short: '21-127'}, due_at: at(1, 12)},
  'canvas:8': {id: 'canvas:8', name: 'HW 8', course: {short: '21-127'}, due_at: at(-1, 12)},
  'canvas:7': {id: 'canvas:7', name: 'HW 7', course: {name: '21-127 Concepts'}, due_at: at(-3, 12)},
  'task:1': {id: 'task:1', is_task: true, name: 'Call home', notes: 'After 6\\nBring the <form>', course: {name: 'Personal'}, due_at: null},
};
const done = new Set(['canvas:7']);
const SH = {byId: id => list[id], isDone: a => done.has(a.id), dot: c => '<span class="dot"></span>', fmtDue: (iso, long, allDay) => 'the ' + new Date(iso).getDate() + 'th'};
let shown = todayIso(), can = true;
const settings = () => ({day_start: 5, day_end: 24}), editable = () => can;
""" + says + """
const own = (n, isDone) => ({id: 'own' + n, kind: 'own', text: 'To-do ' + n, done: isDone});
const block = {ref: 'block:b1', kind: 'deep', title: 'Concepts <review>', start: 1215, end: 1320, repeat: true, changed: true, items: [
  own(1, true), {id: 'w9', kind: 'work', ref: 'canvas:9', text: 'old name', course: '21-127', done: false},
  {id: 'w8', kind: 'work', ref: 'canvas:8', text: 'HW 8', course: '21-127', done: true}, {id: 'gone', kind: 'work', ref: 'canvas:1', text: 'Dropped quiz', course: '15-122', done: false},
  {id: 'w7', kind: 'work', ref: 'canvas:7', text: 'HW 7', course: '', done: false}, own(6, false), own(7, false), own(8, true)]};
const lunch = {ref: 'meal:lunch', kind: 'meal', meal: 'lunch', title: 'Lunch', start: 900, end: 960, place: 'Chipotle & Co', items: []};
const early = {ref: 'block:b2', kind: 'other', title: 'Run', start: 240, end: 330, items: [own(1, false)]};
console.log(JSON.stringify({
  card: detailsHtml(block, false), tip: detailsHtml(block, true),
  lunchCard: detailsHtml(lunch, false), lunchTip: detailsHtml(lunch, true),
  noPlace: detailsHtml({...lunch, place: '', placeChanged: false}, true),
  earlyCard: detailsHtml(early, false), earlyTip: detailsHtml(early, true),
  locked: (() => { can = false; const h = detailsHtml(early, false); can = true; return h; })(),
  due: dueHtml(list['canvas:9']), late: dueHtml(list['canvas:8']), finished: dueHtml(list['canvas:7']), task: dueHtml(list['task:1']),
  wd: wdName(shown), items: TIP_ITEMS,
}));
"""
        cls.out = run_node(script)

    def test_the_preview_says_what_the_card_says(self):
        o = self.out
        for card, tip in ((o["card"], o["tip"]), (o["lunchCard"], o["lunchTip"]), (o["earlyCard"], o["earlyTip"])):
            card_texts = _texts(card)
            for text in _texts(tip):
                if not re.fullmatch(r"\+\d+ more", text):
                    self.assertIn(text, card_texts)
        texts = _texts(o["tip"])
        self.assertEqual(texts[:4], ["Deep work", "Concepts &lt;review&gt;", "8:15–10:00 PM · 1 hr 45 min", f"Repeats every {o['wd']} · changed for today only"])
        self.assertEqual(texts[4], "Things to get done")
        # A work item: its name as the list has it now, its course, due date and status.
        self.assertIn("HW 9 &lt;proofs&gt;", texts)
        self.assertNotIn("old name", texts)
        at = texts.index("HW 9 &lt;proofs&gt;")
        self.assertEqual(texts[at + 1:at + 4], ["21-127 Concepts", "Due the " + texts[at + 2].split(" the ")[1], "Due tomorrow"])
        self.assertEqual(texts[texts.index("HW 8") + 1:texts.index("HW 8") + 4][::2], ["21-127", "Overdue"])
        self.assertEqual(texts[texts.index("HW 7") + 3], "Done")
        self.assertEqual(texts[texts.index("Dropped quiz") + 1:texts.index("Dropped quiz") + 3], ["15-122", "No longer in your list"])
        self.assertEqual(_texts(o["lunchTip"]), ["Meal", "Lunch", "3:00–4:00 PM · 1 hr", "At Chipotle &amp; Co", f"Same every {o['wd']}"])
        self.assertIn("No place set", _texts(o["noPlace"]))
        self.assertIn("Runs past the hours shown", _texts(o["earlyTip"]))

    def test_the_preview_is_only_read(self):
        o = self.out
        for html in (o["tip"], o["lunchTip"], o["earlyTip"], o["due"], o["task"]):
            for control in ("<input", "<button", "<a ", "<label", " id=", "data-pd-", "tabindex", "aria-labelledby"):
                self.assertNotIn(control, html)
        # The card keeps its boxes to press and its ids; a plan still loading locks them.
        self.assertEqual(o["card"].count('<input type="checkbox" data-pd-item='), 8)
        self.assertIn('<h3 id="pdTitle">', o["card"])
        self.assertIn('data-pd-open="canvas:9"', o["card"])
        self.assertIn(" disabled>", o["locked"])
        # The preview draws each item's tick, and names it for a screen reader.
        self.assertEqual(o["items"], 6)
        self.assertEqual(o["tip"].count('<span class="pd-tick'), 6)
        self.assertEqual(re.findall(r'<span class="pd-tick( on)?" role="img" aria-label="(Done|To do)">', o["tip"]),
                         [(" on", "Done"), ("", "To do"), (" on", "Done"), ("", "To do"), ("", "To do"), ("", "To do")])
        self.assertEqual(o["tip"].count('<li class="pd-item done">'), 2)
        # Six items, then how many more; the card lists them all.
        self.assertIn('<li class="pd-rest">+2 more</li>', o["tip"])
        self.assertNotIn("To-do 7", o["tip"])
        self.assertIn("To-do 8", o["card"])
        self.assertNotIn("pd-rest", o["card"])
        # A block holding nothing says so on the card, where Edit is at hand.
        self.assertNotIn("Things to get done", o["lunchTip"])
        self.assertIn("Nothing yet. Edit the block", o["lunchCard"])

    def test_what_is_due_says_its_course_when_and_how_it_stands(self):
        o = self.out
        self.assertEqual(_texts(o["due"])[0], "HW 9 &lt;proofs&gt;")
        self.assertEqual(_texts(o["due"])[1], "21-127 Concepts")
        self.assertRegex(_texts(o["due"])[2], r"^Due the \d+th$")
        self.assertEqual(_texts(o["due"])[3], "Due tomorrow")
        self.assertIn('<span class="pd-st warn">Due tomorrow</span>', o["due"])
        self.assertIn('<span class="pd-st bad">Overdue</span>', o["late"])
        self.assertIn('<span class="pd-st good">Done</span>', o["finished"])
        self.assertNotIn("pd-notes", o["due"])
        # A task's notes, escaped.
        # With no due date that is said once, not again as its status.
        self.assertEqual(_texts(o["task"]), ["Call home", "Personal", "No due date", "After 6\nBring the &lt;form&gt;"])
        self.assertIn('<p class="pd-line pd-notes">', o["task"])


# The planner's page stood in for, for the preview: elements with a box, a data-tip and a button; the
# listeners planner.js adds, kept to be fired; and a clock the test moves.
TIP_PAGE = """
const timers = [];
let now = 0, seq = 0;
const setTimeout = (fn, ms) => { timers.push({id: ++seq, at: now + ms, fn}); return seq; };
const clearTimeout = id => { const i = timers.findIndex(t => t.id === id); if (i >= 0) timers.splice(i, 1); };
function tick(ms){
  const end = now + ms;
  for (;;) {
    const due = timers.filter(t => t.at <= end).sort((a, b) => a.at - b.at)[0];
    if (!due) break;
    timers.splice(timers.indexOf(due), 1);
    now = due.at;
    due.fn();
  }
  now = end;
}
class El {
  constructor(name, tip, rect, isButton){ Object.assign(this, {name, dataset: tip ? {tip} : {}, rect, isButton: !!isButton, attrs: {}, kids: []}); }
  add(kid){ kid.parent = this; this.kids.push(kid); return kid; }
  closest(sel){ if (sel !== '[data-tip]') throw new Error(sel); for (let e = this; e; e = e.parent) if (e.dataset.tip) return e; return null; }
  matches(sel){ if (sel === 'button') return this.isButton; if (sel === '.pflag-wrap') return this.name === 'flag'; throw new Error(sel); }
  querySelector(sel){ if (sel !== 'button') throw new Error(sel); return this.kids.find(k => k.isButton) || null; }
  getBoundingClientRect(){ return this.rect; }
  setAttribute(k, v){ this.attrs[k] = v; }
  removeAttribute(k){ delete this.attrs[k]; }
}
const box = (left, top, w, h) => ({left, top, right: left + w, bottom: top + h, width: w, height: h});
const page = {els: [], dialog: false, drawer: false, focus: null, on: {root: {}, document: {}, window: {}}, vw: 1400, vh: 900};
const listen = where => (type, fn) => { (page.on[where][type] ||= []).push(fn); };
const fire = (where, type, e = {}) => { for (const fn of page.on[where][type] || []) fn(e); };
const blank = new El('the timeline', null, box(840, 150, 440, 700));       // the planner where nothing is
const elsewhere = new El('the list', null, box(40, 150, 700, 700));        // outside the planner
const all = () => page.els.flatMap(e => [e, ...e.kids]);
const root = {addEventListener: listen('root'), contains: el => el === blank || all().includes(el),
  querySelector(sel){
    const m = /^\\[data-tip="(.*)"\\]$/.exec(sel);
    if (m) return page.els.find(e => e.dataset.tip === m[1]) || null;
    if (sel === '[aria-describedby="planTip"]') return all().find(e => e.attrs['aria-describedby'] === 'planTip') || null;
    throw new Error(sel);
  }};
const tipNode = {hidden: true, innerHTML: '', style: {}, dataset: {}, offsetWidth: 240, offsetHeight: 120};
const document = {addEventListener: listen('document'), getElementById: id => id === 'planTip' ? tipNode : null, get activeElement(){ return page.focus; },
  querySelector: sel => sel === 'dialog[open]' && page.dialog ? {} : null, documentElement: {get clientWidth(){ return page.vw; }}};
const window = {addEventListener: listen('window'), get innerHeight(){ return page.vh; }};
const CSS = {escape: s => s};
let marked = 0;
const SH = {plannerState: 'on', drawerOpen: () => page.drawer, byId: id => id === 'gone' ? null : {id}, markEmoji(){ marked++; }};
let plan = {}, drag = null;
const facts = {};
const entryByRef = ref => facts[ref] || null;
const detailsHtml = (e, preview) => `${preview ? 'preview' : 'card'} of ${e.title}`;
const dueHtml = a => `due ${a.id}`;
"""


@unittest.skipUnless(NODE, "Node is not installed")
class PreviewBehaviourTest(unittest.TestCase):
    """planner.js's own preview code against a stand-in for the page: when it shows, when it goes,
    where it is put, and that nothing is left waiting."""

    @classmethod
    def setUpClass(cls):
        script = TIP_PAGE + tip_section() + """
// Two blocks one under the other, a flag in the lane and a chip in the strip. draw() draws them anew
// as render() does: new elements, focus put back on the one that had it, then syncTip().
function draw(boxes = {}){
  const block = (name, ref, r) => { const el = new El(name, 'b:' + ref, r); el.add(new El(name + "'s button", null, r, true)); el.add(new El(name + "'s checkbox", null, r)); return el; };
  const flag = new El('flag', 'd:hw9', boxes.flag || box(1290, 800, 82, 22));
  flag.add(new El("flag's button", null, flag.rect, true));
  const had = page.focus?.name;
  page.els = [block('Lunch', 'meal:lunch', boxes.lunch || box(906, 500, 363, 20)), block('Gym', 'block:gym', boxes.gym || box(906, 522, 363, 60)), flag,
    new El('chip', 'b:block:late', box(860, 160, 120, 26), true)].filter(e => !(boxes.without || []).includes(e.name));
  if (had) { page.focus = el(had) || null; if (page.focus) arrive(page.focus); }
  syncTip();
}
Object.assign(facts, {'meal:lunch': {title: 'Lunch'}, 'block:gym': {title: 'Gym'}, 'block:late': {title: 'Late'}});
function el(name){ return all().find(e => e.name === name); }
const move = (target, x, y, o = {}) => fire('root', 'pointermove', {target, clientX: x, clientY: y, pointerType: 'mouse', buttons: 0, ...o});
const onto = (name, o) => { const t = el(name), r = t.rect; move(t.kids[0] || t, (r.left + r.right) / 2, (r.top + r.bottom) / 2, o); };
const off = () => move(blank, 1000, 300);
const press = (name, o = {}) => fire('document', 'pointerdown', {target: name ? el(name).kids[0] || el(name) : elsewhere, pointerType: 'mouse', ...o});
// Focus comes onto an element as in a page: the planner hears focusin first, then the document. tab:
// the Tab key brought it; without, a click or the page put it there.
const key = k => fire('document', 'keydown', {key: k});
const arrive = t => { page.focus = t; if (root.contains(t)) fire('root', 'focusin', {target: t}); fire('document', 'focusin', {target: t}); };
const focus = (name, {tab = true} = {}) => { const t = el(name); if (tab) key('Tab'); arrive(t); };
const blur = to => { const from = page.focus; page.focus = to || null; fire('root', 'focusout', {target: from, relatedTarget: to || null}); if (to) fire('document', 'focusin', {target: to}); };
const described = () => all().filter(e => e.attrs['aria-describedby'] === 'planTip').map(e => e.name);
const see = () => tipNode.hidden ? 'hidden' + (described().length ? ', yet described: ' + described() : '') : tipNode.innerHTML + ' beside ' + (described().join(' and ') || 'nothing');
const waiting = () => timers.length;
// Each case starts from a page just drawn, with nothing shown, nothing waiting and the clock at rest.
function fresh(){
  fire('window', 'blur');
  quiet = null;
  Object.assign(page, {dialog: false, drawer: false, focus: null, vw: 1400, vh: 900});
  drag = null; plan = {}; SH.plannerState = 'on';
  Object.assign(tipNode, {offsetWidth: 240, offsetHeight: 120});
  draw();
  tick(5000);
  if (timers.length || !tipNode.hidden) throw new Error('not at rest');
}
const cases = {
  rests(){ onto('Lunch'); const a = see(); tick(349); const b = see(); tick(1); return [a, b, see(), waiting()]; },
  leaves(){ onto('Lunch'); tick(350); off(); const a = see(); tick(119); const b = see(); tick(1); return [a, b, see(), waiting()]; },
  leavesThePlanner(){ onto('Lunch'); tick(350); fire('root', 'pointerleave', {pointerType: 'mouse'}); tick(120); return [see(), waiting()]; },
  passesOver(){ onto('Lunch'); tick(200); off(); tick(2000); return [see(), waiting()]; },
  movesAboutOnIt(){ onto('Lunch'); tick(200); move(el("Lunch's checkbox"), 1001, 511); tick(100); move(el("Lunch's button"), 1003, 512); const a = see(); tick(50); return [a, see()]; },
  nextAtOnce(){ onto('Lunch'); tick(350); onto('Gym'); const a = see(); tick(2000); onto('flag'); return [a, see(), waiting()]; },
  backBeforeItGoes(){ onto('Lunch'); tick(350); off(); tick(100); onto('Lunch'); tick(2000); return [see(), waiting()]; },
  press(){ onto('Lunch'); tick(350); press('Lunch'); const a = [see(), waiting()]; move(el("Lunch's button"), 1000, 512); tick(2000); const b = see(); off(); onto('Lunch'); tick(350); return [...a, b, see()]; },
  pressWhileWaiting(){ onto('Lunch'); tick(200); press('Lunch'); const n = waiting(); tick(2000); return [see(), n]; },
  pressElsewhere(){ onto('Lunch'); tick(350); press(null); return [see(), waiting()]; },
  pressAfterAScroll(){ onto('Lunch'); tick(350); fire('window', 'scroll'); press('Lunch'); move(el("Lunch's button"), 1001, 511); tick(2000); const a = see(); off(); onto('Lunch'); tick(350); return [a, see(), waiting()]; },
  buttonDown(){ onto('Lunch', {buttons: 1}); tick(2000); const a = see(); onto('Gym', {buttons: 1}); tick(2000); return [a, see(), waiting()]; },
  dragging(){ drag = {}; onto('Lunch'); tick(2000); return [see(), waiting()]; },
  afterADrag(){ onto('Lunch'); tick(350); press('Lunch'); onto('Lunch', {buttons: 1}); move(blank, 1000, 700, {buttons: 1}); draw({lunch: box(906, 690, 363, 20)}); move(el("Lunch's button"), 1000, 700); tick(2000); return [see(), waiting()]; },
  touch(){ onto('Lunch', {pointerType: 'touch'}); tick(2000); const a = see(); press('Lunch', {pointerType: 'touch'}); tick(2000); return [a, see(), waiting()]; },
  pen(){ onto('Lunch', {pointerType: 'pen'}); tick(350); return [see()]; },
  escape(){ onto('Lunch'); tick(350); key('Escape'); const a = [see(), waiting()]; move(el("Lunch's checkbox"), 1001, 511); tick(2000); const b = see(); off(); onto('Lunch'); tick(350); return [...a, b, see()]; },
  otherKeys(){ onto('Lunch'); tick(350); key('z'); return [see()]; },
  scroll(){ onto('Lunch'); tick(350); fire('window', 'scroll'); const a = [see(), waiting()]; tick(2000); const b = see(); move(el("Lunch's button"), 1001, 511); tick(350); return [...a, b, see()]; },
  scrollWhileWaiting(){ onto('Lunch'); tick(100); fire('window', 'scroll'); const n = waiting(); tick(2000); return [see(), n]; },
  resize(){ onto('Lunch'); tick(350); fire('window', 'resize'); return [see(), waiting()]; },
  dialogOpens(){ onto('Lunch'); tick(350); page.dialog = true; fire('document', 'focusin', {target: elsewhere}); const a = [see(), waiting()]; off(); onto('Gym'); tick(2000); return [...a, see(), waiting()]; },
  dialogOpensWhileWaiting(){ onto('Lunch'); tick(100); page.dialog = true; tick(2000); return [see(), waiting()]; },
  drawerOpen(){ page.drawer = true; onto('Lunch'); tick(2000); return [see(), waiting()]; },
  cardOpens(){ onto('Lunch'); tick(350); quietTip('b:meal:lunch'); const a = [see(), waiting()]; move(el("Lunch's button"), 1001, 511); tick(2000); return [...a, see()]; },
  plannerOff(){ SH.plannerState = 'off'; onto('Lunch'); tick(2000); const a = see(); SH.plannerState = 'on'; plan = null; off(); onto('Lunch'); tick(2000); return [a, see(), waiting()]; },
  drawnAnew(){ onto('Lunch'); tick(350); const before = el("Lunch's button"); facts['meal:lunch'] = {title: 'Lunch at noon'}; draw(); const a = [see(), all().filter(e => e.attrs['aria-describedby']).length, el("Lunch's button") !== before];
    facts['meal:lunch'] = {title: 'Lunch'}; draw({lunch: box(906, 300, 363, 20)}); const b = [see(), waiting()]; return [...a, ...b]; },
  drawnAnewWithoutIt(){ onto('Lunch'); tick(350); draw({without: ['Lunch']}); return [see(), waiting()]; },
  mealTakenOff(){ onto('Lunch'); tick(350); facts['meal:lunch'] = {title: 'Lunch', off: true}; draw(); const a = see(); facts['meal:lunch'] = {title: 'Lunch'}; return [a, waiting()]; },
  drawnUnderAStillPointer(){ off(); draw({gym: box(906, 280, 363, 60)}); tick(2000); return [see(), waiting()]; },
  movedAwayWhileWaiting(){ onto('Lunch'); tick(200); draw({lunch: box(906, 300, 363, 20)}); tick(2000); return [see(), waiting()]; },
  flag(){ onto('flag'); tick(350); return [see(), tipNode.dataset.side, tipNode.style.left, tipNode.style.top]; },
  chip(){ onto('chip'); tick(350); return [see()]; },
  goneFromTheList(){ const f = el('flag'); f.dataset.tip = 'd:gone'; onto('flag'); tick(350); return [see(), waiting()]; },
  focus(){ focus("Gym's button"); const a = see(); tick(350); const b = see(); blur(elsewhere); return [a, b, see(), waiting()]; },
  focusMovesOn(){ focus("Gym's button"); tick(350); const from = page.focus; focus("flag's button"); const a = see(); blur(); tick(119); const b = see(); tick(1); return [a, b, see(), waiting()]; },
  focusFromAClick(){ key('Tab'); press('Gym'); focus("Gym's button", {tab: false}); off(); tick(2000); return [see(), waiting()]; },
  focusPutThereByThePage(){ key('Enter'); focus("Gym's button", {tab: false}); tick(2000); const a = see(); key('Tab'); press(null); focus("Gym's button", {tab: false}); tick(2000); return [a, see(), waiting()]; },
  windowComesBack(){ focus("Gym's button"); tick(350); const a = see(); fire('window', 'blur'); const b = see(); arrive(page.focus); tick(2000); return [a, b, see(), waiting()]; },
  drawnAnewWhileThePointerIsElsewhere(){ focus("Gym's button"); tick(350); onto('Lunch'); const a = see(); draw(); tick(2000); return [a, see(), waiting()]; },
  escapeOnTheFocused(){ focus("Gym's button"); tick(350); key('Escape'); const a = see(); draw(); tick(2000); const b = see(); focus("Lunch's button"); focus("Gym's button"); tick(350); return [a, b, see()]; },
  focusOnACheckbox(){ focus("Gym's checkbox"); tick(2000); return [see(), waiting()]; },
  focusOnTheChip(){ focus('chip'); tick(350); return [see()]; },
  focusScrollsIntoView(){ focus("Gym's button"); tick(16); fire('window', 'scroll'); tick(334); return [see()]; },
  focusBackFromTheCard(){ focus("Gym's button"); tick(350); key('Enter'); quietTip('b:block:gym'); blur(elsewhere); tick(1000); key('Escape'); focus("Gym's button", {tab: false}); tick(2000); const a = see(); focus("Lunch's button"); tick(350); return [a, see()]; },
  focusLostAndPutBack(){ focus("Gym's button"); tick(350); const t = page.focus; blur(); tick(60); arrive(t); tick(2000); const a = see(); blur(); tick(120); return [a, see(), waiting()]; },
  focusKeptThroughADraw(){ focus("Gym's button"); tick(350); const before = page.focus; facts['block:gym'] = {title: 'Gym, ticked'}; draw(); const a = [see(), page.focus !== before];
    facts['block:gym'] = {title: 'Gym'}; draw({without: ['Gym']}); return [...a, see(), waiting()]; },
  pointerLeavesTheFocused(){ focus("Gym's button"); tick(350); onto('Lunch'); const a = see(); off(); tick(120); return [a, see(), waiting()]; },
  emojiMarked(){ const n = marked; onto('Lunch'); tick(350); return [marked - n]; },
  windowLeft(){ onto('Lunch'); tick(350); fire('window', 'blur'); return [see(), waiting()]; },
};
const out = {};
for (const [name, run] of Object.entries(cases)) { fresh(); out[name] = run(); }

// Where it is put: tipPlace(the block's box, the preview's width and height, the window's).
const put = (r, w, h, vw, vh, under) => { const p = tipPlace(r, w, h, vw, vh, under); return p && [p.side, p.left, p.top, p.maxW, p.maxH]; };
out.put = {
  left: put(box(906, 371, 363, 36), 240, 120, 1400, 900),
  lowDown: put(box(906, 840, 363, 20), 240, 300, 1400, 900),
  right: put(box(60, 300, 200, 40), 240, 120, 1400, 900),
  below: put(box(70, 200, 290, 20), 300, 120, 375, 812),
  above: put(box(70, 700, 290, 20), 300, 120, 375, 812),
  farRight: put(box(300, 200, 60, 20), 300, 120, 375, 812),
  cutBelow: put(box(70, 300, 290, 300), 300, 400, 375, 812),
  cutBeside: put(box(300, 0, 900, 900), 400, 300, 1400, 900),
  noRoom: put(box(40, 40, 300, 700), 300, 200, 375, 812),
  tiny: put(box(600, 400, 20, 20), 60, 30, 700, 500),
  // A flag in the lane on the right, at rest and grown to the left to show its name; and the day's last.
  flag: put(box(1286, 634, 75, 22), 300, 165, 1400, 900, true),
  flagGrown: put(box(1098, 634, 263, 22), 300, 165, 1400, 900, true),
  flagLast: put(box(1279, 857, 82, 22), 300, 85, 1400, 900, true),
  flagBeside: put(box(700, 60, 82, 22), 300, 165, 800, 150, true),
};
// Whatever the block and the window, the preview is wholly in the window and never over the block.
const bad = [];
let tried = 0, placed = 0;
for (const [vw, vh] of [[1400, 900], [1100, 700], [800, 514], [375, 812], [320, 480]])
  for (const [w, h] of [[168, 96], [240, 160], [300, 420], [300, 900]])
    for (let x = -40; x < vw; x += Math.round(vw / 9))
      for (let y = -40; y < vh; y += Math.round(vh / 9))
        for (const [bw, bh] of [[20, 20], [82, 22], [363, 20], [363, 300], [vw - 90, 20], [vw - 90, vh - 200]]) for (const under of [false, true]) {
          const r = box(x, y, bw, bh), tw = Math.min(w, vw - 16), p = tipPlace(r, tw, h, vw, vh, under);
          tried++;
          if (!p) continue;
          placed++;
          const pw = p.maxW || tw, ph = p.maxH || h, right = p.left + pw, bottom = p.top + ph;
          const inside = p.left >= 8 && p.top >= 8 && right <= vw - 8 && bottom <= vh - 8;
          const clear = right <= r.left - 8 || p.left >= r.right + 8 || bottom <= r.top - 8 || p.top >= r.bottom + 8;
          const whole = !p.maxW && !p.maxH;
          // A side with room in the window for all of it is never passed over for a cut.
          const beside = Math.max(Math.min(r.left - 8, vw - 8) - 8, vw - 8 - Math.max(r.right + 8, 8));
          const overUnder = Math.max(Math.min(r.top - 8, vh - 8) - 8, vh - 8 - Math.max(r.bottom + 8, 8));
          const fits = (beside >= tw && vh - 16 >= h) || overUnder >= h;
          // A flag's preview is in the same place whether the flag has grown to the left or not.
          const grown = under && tipPlace({...r, left: r.left - 200}, tw, h, vw, vh, true);
          const steady = !grown || !['below', 'above'].includes(p.side) || (grown.side === p.side && grown.left === p.left && grown.top === p.top);
          if (!inside || !clear || (fits && !whole) || !steady) bad.push([r, tw, h, vw, vh, under, p]);
        }
out.sweep = {tried, placed, bad: bad.slice(0, 5)};
// How it is put on the page: measured, placed, and described by the block's button.
fresh();
onto('Lunch'); tick(350);
out.shown = {style: {...tipNode.style}, side: tipNode.dataset.side, cut: tipNode.dataset.cut, hidden: tipNode.hidden};
fresh();
Object.assign(page, {vw: 375, vh: 812});
draw({lunch: box(70, 300, 290, 300)});
tipNode.offsetHeight = 400; tipNode.offsetWidth = 300;
onto('Lunch'); tick(350);
out.cut = {style: {...tipNode.style}, side: tipNode.dataset.side, cut: tipNode.dataset.cut};
fresh();
out.atRest = [see(), waiting(), tipNode.innerHTML];
console.log(JSON.stringify(out));
"""
        cls.out = run_node(script)

    def test_it_shows_after_the_pointer_rests_and_goes_soon_after_it_leaves(self):
        o = self.out
        lunch = "preview of Lunch beside Lunch's button"
        self.assertEqual(o["rests"], ["hidden", "hidden", lunch, 0])
        self.assertEqual(o["leaves"], [lunch, lunch, "hidden", 0])
        self.assertEqual(o["leavesThePlanner"], ["hidden", 0])
        self.assertEqual(o["passesOver"], ["hidden", 0])
        # The wait runs from when the pointer came onto the block, however it moves about on it.
        self.assertEqual(o["movesAboutOnIt"], ["hidden", lunch])
        # While one shows, the next shows at once; back on it before it goes, it stays.
        self.assertEqual(o["nextAtOnce"], ["preview of Gym beside Gym's button", "due hw9 beside flag's button", 0])
        self.assertEqual(o["backBeforeItGoes"], [lunch, 0])
        self.assertEqual(o["pen"], [lunch])
        # The flag, low in the day: its preview over it, their right edges in line.
        self.assertEqual(o["flag"], ["due hw9 beside flag's button", "above", f"{1290 + 82 - 240}px", f"{800 - 8 - 120}px"])
        self.assertEqual(o["chip"], ["preview of Late beside chip"])
        self.assertEqual(o["goneFromTheList"], ["hidden", 0])
        self.assertEqual(o["emojiMarked"], [1])
        self.assertEqual(o["atRest"], ["hidden", 0, ""])

    def test_a_press_a_drag_and_a_touch_never_show_it(self):
        o = self.out
        lunch = "preview of Lunch beside Lunch's button"
        # Gone at once on the press, nothing waiting, and none again until the pointer has left.
        self.assertEqual(o["press"], ["hidden", 0, "hidden", lunch])
        self.assertEqual(o["pressWhileWaiting"], ["hidden", 0])
        self.assertEqual(o["pressElsewhere"], ["hidden", 0])
        self.assertEqual(o["pressAfterAScroll"], ["hidden", lunch, 0])
        self.assertEqual(o["buttonDown"], ["hidden", "hidden", 0])
        self.assertEqual(o["dragging"], ["hidden", 0])
        self.assertEqual(o["afterADrag"], ["hidden", 0])
        self.assertEqual(o["touch"], ["hidden", "hidden", 0])

    def test_esc_a_scroll_and_anything_opening_send_it_away(self):
        o = self.out
        lunch = "preview of Lunch beside Lunch's button"
        self.assertEqual(o["escape"], ["hidden", 0, "hidden", lunch])
        self.assertEqual(o["otherKeys"], [lunch])
        # After a scroll it comes again once the pointer moves and rests.
        self.assertEqual(o["scroll"], ["hidden", 0, "hidden", lunch])
        self.assertEqual(o["scrollWhileWaiting"], ["hidden", 0])
        self.assertEqual(o["resize"], ["hidden", 0])
        self.assertEqual(o["windowLeft"], ["hidden", 0])
        self.assertEqual(o["dialogOpens"], ["hidden", 0, "hidden", 0])
        self.assertEqual(o["dialogOpensWhileWaiting"], ["hidden", 0])
        self.assertEqual(o["drawerOpen"], ["hidden", 0])
        self.assertEqual(o["cardOpens"], ["hidden", 0, "hidden"])
        self.assertEqual(o["plannerOff"], ["hidden", "hidden", 0])

    def test_it_follows_the_plan_when_the_planner_is_drawn_anew(self):
        o = self.out
        # The new block's button is described, the old one no longer; a block that moved from under
        # the pointer, went, or was taken off loses its preview; a still pointer brings none.
        self.assertEqual(o["drawnAnew"], ["preview of Lunch at noon beside Lunch's button", 1, True, "hidden", 0])
        self.assertEqual(o["drawnAnewWithoutIt"], ["hidden", 0])
        self.assertEqual(o["mealTakenOff"], ["hidden", 0])
        self.assertEqual(o["drawnUnderAStillPointer"], ["hidden", 0])
        self.assertEqual(o["movedAwayWhileWaiting"], ["hidden", 0])

    def test_the_keyboards_focus_shows_it_too(self):
        o = self.out
        gym = "preview of Gym beside Gym's button"
        self.assertEqual(o["focus"], ["hidden", gym, "hidden", 0])
        self.assertEqual(o["focusMovesOn"], ["due hw9 beside flag's button", "due hw9 beside flag's button", "hidden", 0])
        self.assertEqual(o["focusFromAClick"], ["hidden", 0])
        # Only Tab bringing it there counts: not focus put back by the page after another key or a
        # press, not the window coming back to the front, not a redraw (which must not take the
        # preview from the block the pointer is on).
        self.assertEqual(o["focusPutThereByThePage"], ["hidden", "hidden", 0])
        self.assertEqual(o["windowComesBack"], [gym, "hidden", "hidden", 0])
        self.assertEqual(o["drawnAnewWhileThePointerIsElsewhere"], ["preview of Lunch beside Lunch's button"] * 2 + [0])
        self.assertEqual(o["escapeOnTheFocused"], ["hidden", "hidden", gym])
        self.assertEqual(o["focusOnACheckbox"], ["hidden", 0])
        self.assertEqual(o["focusOnTheChip"], ["preview of Late beside chip"])
        self.assertEqual(o["focusScrollsIntoView"], [gym])
        # Back from the card it opened, the block shows none until focus has been elsewhere.
        self.assertEqual(o["focusBackFromTheCard"], ["hidden", "preview of Lunch beside Lunch's button"])
        self.assertEqual(o["focusKeptThroughADraw"], ["preview of Gym, ticked beside Gym's button", True, "hidden", 0])
        # Focus taken from the block and put straight back (the block was drawn anew) keeps it.
        self.assertEqual(o["focusLostAndPutBack"], [gym, "hidden", 0])
        self.assertEqual(o["pointerLeavesTheFocused"], ["preview of Lunch beside Lunch's button", "hidden", 0])

    def test_it_is_put_beside_the_block_in_the_window_and_never_over_it(self):
        put = self.out["put"]
        # Left of the block first, its top with the block's; lower down, moved up into the window.
        self.assertEqual(put["left"], ["left", 906 - 8 - 240, 371, 0, 0])
        self.assertEqual(put["lowDown"], ["left", 658, 900 - 8 - 300, 0, 0])
        self.assertEqual(put["right"], ["right", 268, 300, 0, 0])
        # No room beside it: under it, or over it near the bottom, kept within the window's width.
        self.assertEqual(put["below"], ["below", 67, 228, 0, 0])
        self.assertEqual(put["above"], ["above", 67, 700 - 8 - 120, 0, 0])
        self.assertEqual(put["farRight"], ["below", 67, 228, 0, 0])
        # Room for only part of it: cut to the side with the most room, still clear of the block.
        self.assertEqual(put["cutBelow"], ["above", 67, 8, 0, 284])
        self.assertEqual(put["cutBeside"], ["left", 8, 8, 300 - 16, 0])
        self.assertIsNone(put["noRoom"])
        self.assertEqual(put["tiny"], ["left", 532, 400, 0, 0])
        # A flag grows to the left while pointed at: its preview goes under it (over it at the end
        # of the day), right edges in line, so it is in the same place either way and never over
        # the name the flag then shows. Only with no room under or over it, beside it.
        self.assertEqual(put["flag"], ["below", 1361 - 300, 634 + 22 + 8, 0, 0])
        self.assertEqual(put["flagGrown"], put["flag"])
        self.assertEqual(put["flagLast"], ["above", 1361 - 300, 857 - 8 - 85, 0, 0])
        self.assertEqual(put["flagBeside"][0], "left")
        sweep = self.out["sweep"]
        self.assertGreater(sweep["tried"], 10000)
        self.assertGreater(sweep["placed"], sweep["tried"] * 0.9)
        self.assertEqual(sweep["bad"], [])

    def test_it_is_measured_then_placed(self):
        shown = self.out["shown"]
        self.assertEqual(shown, {"style": {"left": "658px", "top": "500px", "maxWidth": "", "maxHeight": ""}, "side": "left", "cut": "", "hidden": False})
        # A long block in a phone-sized window: over it, cut to the room there, and marked so (it fades).
        cut = self.out["cut"]
        self.assertEqual(cut, {"style": {"left": "67px", "top": "8px", "maxWidth": "", "maxHeight": "284px"}, "side": "above", "cut": "1"})
        self.assertIn('.ptip[data-cut="1"]::after{', HTML)


# ---- opening at once: the copies kept for the next visit (dashboard.js "kept for the next visit",
# ---- "asking and saving", "starting"; planner.js "the copy kept from the last visit") ----
KEPT_START, KEPT_END = "// ---- kept for the next visit ----", "// ---- end of kept for the next visit ----"
ASK_START, ASK_END = "// ---- asking and saving ----", "// ---- end of asking and saving ----"
BOOT_START = "// ---- starting ----"
BACK_START, BACK_END = "// ---- back on show ----", "// ---- end of back on show ----"
PLAN_COPY_START = "  // ---- the copy kept from the last visit ----"


def kept_section():
    return JS[JS.index(KEPT_START):JS.index(KEPT_END)]


class KeptSourceTest(unittest.TestCase):
    """The page opens from what the server last answered, kept in the browser, and asks quietly."""

    def test_data_js_does_not_hold_the_page_up(self):
        # Asked for as before, from the same place, but the page no longer waits for it.
        self.assertIn('<script src="data.js" async fetchpriority="high"></script>\n<script src="dashboard.js"></script>\n<script src="planner.js"></script>', HTML)
        self.assertIn("let D = window.SCHOOL_DATA || null;", JS)
        self.assertIn("  if (!D) return;   // not started", JS)
        # Its arrival is heard from its own script, or the window's load when that was missed.
        self.assertIn("const script = document.querySelector('script[src=\"data.js\"]');", JS)
        for event in ("script?.addEventListener('load', dataHere);", "script?.addEventListener('error', dataHere);", "window.addEventListener('load', dataHere);"):
            self.assertIn(event, JS)

    def test_nothing_new_is_fetched_and_no_service_worker(self):
        # The same requests to the same places as before the copies: only when they are made changed.
        # (One more since: data.js again, on the Mac only, once a sync has run while the page was
        # open. See WatchSyncTest.)
        self.assertEqual(sorted(re.findall(r"fetch\(([^,)]+)", JS)), ["'/api/state/'", "'data.js'", "'platform.json'", "path", "path"])
        self.assertEqual(sorted(set(re.findall(r"getJson\('([^']+)'\)", JS))), ["api/marks", "api/sync", "api/tasks"])
        self.assertEqual(re.findall(r"fetch\(([^,)]+)", PLANNER), ["`api/plan?from=${from}&to=${to}`"] * 2)
        self.assertEqual(re.findall(r"fetch\(([^,)]+)", BAR), ["'platform.json'"])
        for text in (JS, PLANNER, BAR, HTML):
            self.assertNotIn("serviceWorker", text)
            self.assertNotIn("indexedDB", text)
            self.assertNotIn("caches.", text)

    def test_the_copies_have_a_form_a_place_a_time_and_a_size(self):
        self.assertIn("const KEPT = 'sh:kept:1:';", JS)
        self.assertIn("const keptKey = what => `${KEPT}${what}:${PHONE ? 'phone' : 'server'}:${location.pathname}`;", JS)
        self.assertIn("const KEPT_DAYS = 3;", JS)
        self.assertIn("const KEPT_MAX = {data: 1500000, state: 200000, plan: 200000};", JS)
        self.assertIn("return age >= 0 && age < KEPT_DAYS * 864e5 ? {at, text: v.slice(cut + 1)} : null;", JS)
        self.assertIn("if (typeof text !== 'string' || text.length > KEPT_MAX[what]) throw new Error('not kept');", JS)

    def test_storage_is_only_touched_where_a_failure_is_caught(self):
        # localStorage in two places only, each call inside a try; the planner keeps its copy
        # through dashboard.js.
        outside = JS[:JS.index(KEPT_START)] + JS[JS.index(KEPT_END):]
        self.assertEqual(outside.count("localStorage"), 2)   # mem.get and mem.set, as before
        for line in JS.splitlines():
            if "localStorage." in line and "try" not in line:
                self.assertRegex(line, r"^\s{6,}", line)     # inside a method's try block
        section = kept_section()
        for method in ("get(what){", "write(what, text){", "drop(what){", "tidy(){"):
            body = section[section.index("  " + method):]
            body = body[:body.index("\n  },") if "\n  }," in body else len(body)]
            self.assertIn("try", body, method)
        self.assertNotIn("localStorage", PLANNER)
        self.assertIn("SH.kept?.write('plan', JSON.stringify({from: loaded.from, to: loaded.to, plan}));", PLANNER)
        self.assertIn("const c = SH.kept?.read('plan'), today = todayIso();", PLANNER)

    def test_nothing_is_saved_on_the_word_of_a_copy(self):
        # Every save waits for the server's own answer about where the page saves.
        self.assertIn("const sending = to => known.then(() => { if (WRITE !== to) throw new Error('nowhere to save'); });", JS)
        self.assertIn("const api = (path, body) => sending('local').then(() => saved(path, fetch(path, {", JS)
        self.assertIn("return (body ? sending('cloud').then(() => saved('cloud', ask())) : ask()).then(answer).then(r => heard('cloud', r));", JS)
        self.assertEqual(JS.count("nowKnown()"), 2)          # from disk at once; else when the server answered or did not
        self.assertRegex(JS, r"\}\)\.finally\(\(\) => \{\s*if \(!copy && !PHONE\) \{ showSyncbox\(\); emit\('ready'\); \}\s*nowKnown\(\);\s*\}\);")
        # What is kept is what the server said, once it has said where the page saves.
        self.assertIn("if (!placed || !server.marks || !server.tasks) return;", JS)
        self.assertEqual(len(re.findall(r"^\s*placed = true;", JS, re.M)), 1)
        # The plan: a copy is read, never changed, so nothing is saved from one.
        self.assertIn("const editable = () => !!plan && inRange(shown) && !copied;", PLANNER)
        self.assertIn("if (!plan || copied || !loaded || today < loaded.from || today > loaded.to) return;", PLANNER)
        self.assertIn("if (!editable()) { box.checked = !box.checked; return; }", PLANNER)
        # And the copy is drawn from at the start only.
        self.assertEqual(len(re.findall(r"\bkeptState\(\)", JS)), 2)   # its definition, and start
        self.assertEqual(len(re.findall(r"\bshowKept\(\)", PLANNER)), 2)

    def test_the_servers_answer_is_taken_in_place(self):
        # Equal to what is on show, nothing is drawn again; a ✓ not saved yet stays as shown.
        self.assertIn("for (const id in unsavedMark) { if (marks[id]) next[id] = marks[id]; else delete next[id]; }", JS)
        self.assertIn("if (changed) refreshTasks(t); else tasks = t;", JS)
        self.assertIn("if (s && before === saves && !took(s.marks, s.tasks)) showSynced();", JS)
        self.assertIn("const asShown = copied && same(plan, next) && same(loaded, {from, to});", PLANNER)
        self.assertIn("if (asShown) unlock(); else render();", PLANNER)
        # The drawer stays where it was read when it is drawn again for the same item.
        self.assertIn("const top = drawerId === id ? drawer.scrollTop : 0;", JS)
        self.assertIn("drawer.scrollTop = top;", JS)
        # No page load in any of it: only after Sync now, as before, and when you press Refresh.
        self.assertEqual(JS.count("location.reload()"), 2)
        self.assertIn("  try { sessionStorage.setItem('sh:synced', JSON.stringify({ok: s.ok, output: s.output})); } catch {}\n  location.reload();\n}", JS)
        self.assertIn("  if (e.target.closest('#newData')) return location.reload();", JS)

    def test_synced_ago_is_the_datas_own_time(self):
        start = JS.index("function showSynced(){")
        body = JS[start:JS.index("\n}\n", start)]
        self.assertIn("$('#sync').textContent = D.generated_at ? 'Synced ' + ago(D.generated_at) : 'Not synced yet';", body)
        self.assertIn("function render(){\n  if (!D) return;", JS)
        self.assertRegex(JS, r"\$\('\.page'\)\.dataset\.plan = plannerState;\n  showSynced\(\);")

    def test_a_copy_looks_like_the_plan_for_a_moment_then_shows_it_is_waiting(self):
        self.assertIn("const COPY_QUIET_MS = 1200;", PLANNER)
        self.assertIn("const locked = () => !editable() && !(copied && !waiting && inRange(shown));", PLANNER)
        self.assertIn("els.week.disabled = els.add.disabled = locked();", PLANNER)
        self.assertIn("grid.classList.toggle('loading', locked());", PLANNER)
        self.assertIn("quietTimer = setTimeout(() => { if (copied) { waiting = true; render(); } }, COPY_QUIET_MS);", PLANNER)
        # + Block and Every week pressed meanwhile are done once the plan is here.
        self.assertIn("if (t.closest('#planWeek')) return afterCopy(openWeek);", PLANNER)
        self.assertIn("if (t.closest('#planAdd')) return afterCopy(newBlockAt);", PLANNER)
        # The copy is drawn when the page knows where it saves, before the server is asked.
        self.assertRegex(PLANNER, r"return SH\.setPlanner\('off'\);\n    showKept\(\);\n    load\(shown\);")


# The kept copies with the browser's storage stood in for: `stored` is what it holds, and `broken`
# how it fails ('quota': nothing can be written; 'deny': every call throws; 'gone': reaching
# localStorage itself throws, as with site data blocked).
STORAGE_PAGE = """
const stored = new Map();
let broken = '';
const storage = {
  get length(){ if (broken === 'deny') throw new Error('denied'); return stored.size; },
  key: i => [...stored.keys()][i] ?? null,
  getItem: k => { if (broken === 'deny') throw new Error('denied'); return stored.has(k) ? stored.get(k) : null; },
  setItem: (k, v) => { if (broken) throw new Error('quota'); stored.set(k, String(v)); },
  removeItem: k => { if (broken === 'deny') throw new Error('denied'); stored.delete(k); },
};
Object.defineProperty(globalThis, 'localStorage', {configurable: true, get(){ if (broken === 'gone') throw new Error('SecurityError'); return storage; }});
const DAY = 864e5;
// A copy as the page keeps it, for a place (the kind of site and the path) and of an age in days.
const keep = (what, value, {place = 'server', path = '/school/', age = 0, text} = {}) =>
  stored.set(`sh:kept:1:${what}:${place}:${path}`, (Date.now() - age * DAY) + '\\n' + (text ?? JSON.stringify(value)));
const keptNow = (what, place = 'server', path = '/school/') => {
  const v = stored.get(`sh:kept:1:${what}:${place}:${path}`);
  return v === undefined ? null : JSON.parse(v.slice(v.indexOf('\\n') + 1));
};
let PHONE = false, LOCAL_FILES = false, REMOTE = false, PUBLIC = false, LIVE = false, WRITE = null, PROBING = false;
const location = {pathname: '/school/', reload(){}};
"""


@unittest.skipUnless(NODE, "Node is not installed")
class KeptStoreTest(unittest.TestCase):
    """dashboard.js's own store of copies, run under Node against a stand-in for localStorage."""

    @classmethod
    def setUpClass(cls):
        script = STORAGE_PAGE + kept_section() + """
const out = {};
const T = {'task:aaaaaaaa': {id: 'task:aaaaaaaa', name: 'Buy milk'}};
const M = {'canvas:1': {marked_at: '2026-11-10T10:00:00+00:00', name: 'HW 1', course: '15-122'}};
// Written with its time, under its form, the kind of site and the page's path; read back.
out.wrote = kept.write('plan', JSON.stringify({a: 1}));
out.keys = [...stored.keys()];
out.value = /^\\d{13}\\n\\{"a":1\\}$/.test(stored.get('sh:kept:1:plan:server:/school/'));
out.read = kept.read('plan');
out.got = typeof kept.get('plan').at;
// Another path, and the phone site at the same path, have their own.
location.pathname = '/school/dashboard.html'; out.otherPath = kept.read('plan');
location.pathname = '/school/'; PHONE = true; out.otherKind = kept.read('plan'); kept.write('plan', '{"b":2}'); out.phoneKey = [...stored.keys()].filter(k => k.includes('phone'));
PHONE = false;
// Its time: a few days at most, and never from the future (a clock set back).
keep('state', {x: 1}, {age: 2.9}); out.days29 = kept.read('state');
keep('state', {x: 1}, {age: 3.1}); out.days31 = kept.read('state');
keep('state', {x: 1}, {age: -0.1}); out.future = kept.read('state');
// Not what it should hold: no time, no JSON, cut short.
stored.set('sh:kept:1:state:server:/school/', '{"x":1}'); out.noTime = kept.read('state');
stored.set('sh:kept:1:state:server:/school/', 'soon\\n{"x":1}'); out.badTime = kept.read('state');
keep('state', null, {text: '{"x":'}); out.cutShort = kept.read('state');
keep('state', null, {text: ''}); out.empty = kept.read('state');
// Too long: not kept, and the copy before it goes too.
keep('state', {old: true});
out.tooLong = [kept.write('state', 'x'.repeat(200001)), stored.has('sh:kept:1:state:server:/school/')];
out.longEnough = kept.write('state', '"' + 'x'.repeat(199998) + '"');
out.dataRoom = [kept.write('data', '"' + 'x'.repeat(1499998) + '"'), kept.write('data', '"' + 'x'.repeat(1499999) + '"')];
out.notText = kept.write('state', {x: 1});
// A full disk: what is there can be read; a write fails quietly and the copy before it goes.
keep('state', {old: true}); broken = 'quota';
out.full = {read: kept.read('state'), wrote: kept.write('state', '{"new":true}'), left: stored.has('sh:kept:1:state:server:/school/')};
// Storage that throws at every call, or cannot be reached at all: nothing is kept, nothing throws.
for (const how of ['deny', 'gone']) {
  broken = '';
  keep('state', {old: true});
  broken = how;
  out[how] = [kept.get('state'), kept.read('state'), kept.write('state', '{}'), kept.drop('state') === undefined, kept.tidy() === undefined, keptState()];
}
broken = '';
// Tidying: other forms and copies past their time go, wherever they are from; the rest stays.
stored.clear();
keep('data', {x: 1}); keep('state', {x: 1}, {age: 5}); keep('plan', {x: 1}, {path: '/old/', age: 4}); keep('data', {x: 1}, {path: '/other/', age: 1});
stored.set('sh:kept:0:data:server:/school/', Date.now() + '\\n{}'); stored.set('sh:kept:1:data:server:/broken/', 'nonsense');
stored.set('sh:view', '"courses"'); stored.set('qp.theme', 'night'); stored.set('sh:keptish', 'x');
kept.tidy();
out.tidied = [...stored.keys()].sort();
// From a file on disk nothing is read or kept.
stored.clear(); keep('state', {x: 1}); LOCAL_FILES = true;
out.disk = [kept.get('state'), kept.read('state'), kept.write('plan', '{}'), stored.size];
LOCAL_FILES = false;
// The marks and tasks of the last visit are taken only as what they should be.
const state = (c, o) => { stored.clear(); keep('state', c, o); return !!keptState(); };
const at = {remote: false, public: false};
out.states = {
  good: state({at, marks: M, tasks: T}), empty: state({at, marks: {}, tasks: {}}),
  marksList: state({at, marks: [], tasks: T}), markNoTime: state({at, marks: {x: {name: 'HW'}}, tasks: T}), markNull: state({at, marks: {x: null}, tasks: T}),
  noTasks: state({at, marks: M, tasks: null}), taskOtherId: state({at, marks: M, tasks: {'task:bbbbbbbb': T['task:aaaaaaaa']}}), taskNoName: state({at, marks: M, tasks: {'task:aaaaaaaa': {id: 'task:aaaaaaaa'}}}),
  noPlace: state({marks: M, tasks: T}), placeWords: state({at: {remote: 'no', public: false}, marks: M, tasks: T}), notAMap: state([1, 2]), text: state('marks'),
};
PHONE = true;
out.phoneState = [state({at: null, marks: M, tasks: T}, {place: 'phone'}), state({at, marks: M, tasks: T})];   // its own kind only
PHONE = false;
out.shaped = [dataShaped({courses: []}), dataShaped({generated_at: 'x', courses: [{id: 'c', assignments: [{id: 'a'}]}]}), dataShaped({}), dataShaped(null), dataShaped([]),
  dataShaped({courses: [{id: 'c'}]}), dataShaped({courses: [{id: 'c', assignments: [{name: 'no id'}]}]}), dataShaped({courses: [null]})];
// What the server answers is what is kept, each of the marks and the tasks whole, once the server
// has said where the page saves; an answer that holds neither changes nothing.
stored.clear();
heard('api/marks', M); heard('api/tasks', {tasks: T});
out.beforePlaced = keptNow('state');
placed = true; REMOTE = true; PUBLIC = true;
heard('api/sync', {running: false}); heard('api/plan', {key: 'settings', value: null}); heard('api/open', {});
out.notTheirs = keptNow('state');
heard('api/mark', {...M, 'canvas:2': {marked_at: 'now', name: null, course: null}});
out.afterMark = keptNow('state');
heard('api/task/delete', {removed: T['task:aaaaaaaa'], tasks: {}});
out.afterDelete = keptNow('state');
heard('api/task', {task: T['task:aaaaaaaa'], tasks: T}); heard('api/marks', 'oops'); heard('api/tasks', {});
out.afterNonsense = keptNow('state');
PHONE = true; location.pathname = '/k/';
heard('cloud', {marks: M, tasks: T});
out.cloud = keptNow('state', 'phone', '/k/');
heard('cloud', {task: T['task:aaaaaaaa'], tasks: {}});
out.cloudTask = keptNow('state', 'phone', '/k/');
console.log(JSON.stringify(out));
"""
        cls.out = run_node(script)

    def test_a_copy_is_kept_with_its_time_per_place(self):
        out = self.out
        self.assertTrue(out["wrote"])
        self.assertEqual(out["keys"], ["sh:kept:1:plan:server:/school/"])
        self.assertTrue(out["value"])
        self.assertEqual(out["read"], {"a": 1})
        self.assertEqual(out["got"], "number")
        self.assertIsNone(out["otherPath"])
        self.assertIsNone(out["otherKind"])
        self.assertEqual(out["phoneKey"], ["sh:kept:1:plan:phone:/school/"])

    def test_an_old_or_broken_copy_is_not_used(self):
        out = self.out
        self.assertEqual(out["days29"], {"x": 1})
        for name in ("days31", "future", "noTime", "badTime", "cutShort", "empty"):
            self.assertIsNone(out[name], name)

    def test_a_copy_too_long_is_not_kept_and_leaves_none(self):
        out = self.out
        self.assertEqual(out["tooLong"], [False, False])
        self.assertTrue(out["longEnough"])
        self.assertEqual(out["dataRoom"], [True, False])
        self.assertFalse(out["notText"])

    def test_the_page_works_with_storage_full_or_unavailable(self):
        out = self.out
        self.assertEqual(out["full"], {"read": {"old": True}, "wrote": False, "left": False})
        for how in ("deny", "gone"):
            self.assertEqual(out[how], [None, None, False, True, True, None], how)
        self.assertEqual(out["disk"], [None, None, False, 1])

    def test_tidying_removes_only_copies_no_visit_will_read(self):
        self.assertEqual(self.out["tidied"], ["qp.theme", "sh:kept:1:data:server:/other/", "sh:kept:1:data:server:/school/", "sh:keptish", "sh:view"])

    def test_only_what_it_should_hold_is_taken(self):
        states = self.out["states"]
        self.assertEqual({k for k, v in states.items() if v}, {"good", "empty"})
        self.assertEqual(self.out["phoneState"], [True, False])
        self.assertEqual(self.out["shaped"], [True, True, False, False, False, False, False, False])

    def test_what_the_server_answers_is_what_is_kept(self):
        out = self.out
        self.assertIsNone(out["beforePlaced"])
        self.assertIsNone(out["notTheirs"])
        self.assertEqual(out["afterMark"]["at"], {"remote": True, "public": True})
        self.assertEqual(sorted(out["afterMark"]["marks"]), ["canvas:1", "canvas:2"])
        self.assertEqual(sorted(out["afterMark"]["tasks"]), ["task:aaaaaaaa"])
        self.assertEqual(out["afterDelete"]["tasks"], {})
        self.assertEqual(sorted(out["afterDelete"]["marks"]), ["canvas:1", "canvas:2"])
        self.assertEqual(sorted(out["afterNonsense"]["tasks"]), ["task:aaaaaaaa"])
        self.assertEqual(sorted(out["afterNonsense"]["marks"]), ["canvas:1", "canvas:2"])
        self.assertEqual(out["cloud"]["at"], None)
        self.assertEqual(sorted(out["cloud"]["marks"]), ["canvas:1"])
        self.assertEqual(out["cloudTask"]["tasks"], {})


# The page's start with the page, the network and the browser's storage stood in for. Every request
# waits until the test answers it (answerNow), from what the stand-in server (there) holds at that
# moment; draws lists every drawing of the list with what it was drawn from.
BOOT_PAGE = STORAGE_PAGE + """
const realTimeout = globalThis.setTimeout;
const tick = () => new Promise(r => realTimeout(r, 0));
const later = [];
let timers = 0;
const setTimeout = (fn, ms) => { later.push({fn, ms, id: ++timers}); return timers; };
const clearTimeout = id => { const i = later.findIndex(l => l.id === id); if (i >= 0) later.splice(i, 1); };
const copy = v => v == null ? v : JSON.parse(JSON.stringify(v));
const SITE_KEY = 'k';
const els = {};
// A control of the page: what the page sets on it, and the listeners it adds (on).
const control = () => ({hidden: true, onclick: null, disabled: false, textContent: '', attrs: {}, on: {}, focusVisible: false,
  addEventListener(type, fn){ this.on[type] = fn; }, setAttribute(k, v){ this.attrs[k] = v; }, removeAttribute(k){ delete this.attrs[k]; },
  matches(sel){ return sel === ':focus-visible' && this.focusVisible; }, getBoundingClientRect: () => ({left: 1150, right: 1234, top: 12, bottom: 44})});
for (const sel of ['#fab', '#syncbox', '#syncBtn']) els[sel] = control();
els['#main'] = {innerHTML: ''};
els['#syncNote'] = {hidden: true, innerHTML: '', style: {}, dataset: {}, offsetWidth: 300, offsetHeight: 40};
const esc = s => String(s);
const $ = sel => els[sel] || null;
const toasts = [];
let toastTimer = null;
const toast = (msg, action, o = {}) => { toasts.push(msg + (action ? ' [' + (o.label || 'Undo') + ']' : '')); };
const script = {on: {}, addEventListener(type, fn){ this.on[type] = fn; }};
const page = {focus: {tagName: 'BODY'}, on: {}, hidden: false};
const document = {readyState: 'loading', get activeElement(){ return page.focus; }, body: {tagName: 'BODY'}, documentElement: {clientWidth: 1280},
  get hidden(){ return page.hidden; }, addEventListener(type, fn){ (page.on[type] = page.on[type] || []).push(fn); },
  querySelector: sel => sel === 'script[src="data.js"]' ? script : null};
const window = {on: {}, innerHeight: 800, addEventListener(type, fn){ this.on[type] = fn; }, SCHOOL_DATA: undefined};
// The page goes out of view, or comes back into it.
const show = on => { page.hidden = !on; for (const fn of page.on.visibilitychange || []) fn(); };
const CSS = {escape: s => s};
const errors = [];
const console = {error: e => errors.push(String(e && e.message || e)), log: (...a) => globalThis.console.log(...a)};
const sessionStorage = {getItem: () => null, setItem(){}, removeItem(){}};
const pinnedTask = t => typeof t.pinned === 'boolean' ? t.pinned : !t.due_at;
const DATA = {generated_at: 'G1', errors: [], new_files: [], courses: [{id: 'c1', short: '15-122', assignments: [
  {id: 'a1', name: 'HW 1', marked_done: 'M0'}, {id: 'a2', name: 'HW 2'}, {id: 'a3', name: 'HW 3'}]}]};
const MARK = at => ({marked_at: at, name: null, course: null});
const TASK = (id, name) => ({id, name, course_id: 'personal', due_at: null, all_day: false, pinned: true, notes: '', created_at: 'C', updated_at: 'U'});

// The stand-in server, and every request made to it.
const there = {marks: {}, tasks: {}, platform: {status: 204}, down: false, sync: {running: false}, dataJs: null};
// data.js as sync.py writes it.
const asDataJs = data => 'window.SCHOOL_DATA = ' + JSON.stringify(data) + ';\\n';
const net = {log: [], waiting: []};
let stamp = 0;
function serve(q){
  if (there.down) return q.rej(new TypeError('Failed to fetch'));
  const ok = body => q.res({ok: true, status: 200, json: async () => copy(body)});
  const b = q.body || {};
  if (q.url === 'platform.json') return q.res({ok: there.platform.status === 200, status: there.platform.status, json: async () => copy(there.platform.body)});
  if (q.url === 'api/marks') return ok(there.marks);
  if (q.url === 'api/tasks') return ok({tasks: there.tasks});
  if (q.url === 'api/sync') return ok(there.sync);
  if (q.url === 'data.js') return q.res({ok: there.dataJs != null, status: there.dataJs != null ? 200 : 404, text: async () => there.dataJs});
  const mark = () => { if (b.done) there.marks[b.id] = MARK(b.marked_at || 'T' + (++stamp)); else delete there.marks[b.id]; };
  if (q.url === 'api/mark') { mark(); return ok(there.marks); }
  if (q.url === '/api/state/') { if (q.method === 'POST' && b.action === 'mark') mark(); return ok({marks: there.marks, tasks: there.tasks}); }
  return q.res({ok: false, status: 404, json: async () => ({})});
}
const fetch = (url, o = {}) => new Promise((res, rej) => {
  const q = {url, method: o.method || 'GET', body: o.body ? JSON.parse(o.body) : null, res, rej};
  net.log.push(q.method + ' ' + url);
  net.waiting.push(q);
});
const settle = async () => { for (let i = 0; i < 6; i++) await tick(); };
// Answers the requests that wait (all, or those that match), and lets the page take the answers in.
async function answerNow(match = () => true){
  const go = net.waiting.filter(match);
  net.waiting = net.waiting.filter(q => !go.includes(q));
  go.forEach(serve);
  await settle();
}
const posts = () => net.log.filter(l => l.startsWith('POST'));

// The page's own state and drawing.
let tasks = null, courses = [], all = [], byId = {}, drawerId = null, plannerState = 'unknown', cannotDraw = null;
const draws = [], events = [];
let closed = 0, synced = 0;
function rebuild(){
  all = D.courses.flatMap(c => c.assignments.map(a => ({...a, course: c})));
  for (const t of Object.values(tasks || {})) all.push({id: t.id, name: t.name, is_task: true});
  byId = Object.fromEntries(all.map(a => [a.id, a]));
}
function render(){
  if (!D) return;
  if (cannotDraw && cannotDraw()) throw new Error('cannot draw this');
  draws.push({data: D.generated_at, write: WRITE, live: LIVE, remote: REMOTE, pub: PUBLIC, probing: PROBING, plan: plannerState,
    marks: Object.keys(marks).sort().join(' '), tasks: tasks ? Object.keys(tasks).sort().join(' ') : null, items: all.length});
}
function refresh(){ render(); }
function closeDrawer(){ drawerId = null; closed++; }
function showSynced(){ synced++; }
const emit = name => { events.push(name); };
const shown = () => draws[draws.length - 1];
"""


def boot_sections():
    marks = re.search(r"^const syncedMarks = .*\nlet marks = \{\};$", JS, re.M).group(0)
    return "\n".join([
        "let D = window.SCHOOL_DATA || null;", kept_section(), JS[JS.index(ASK_START):JS.index(ASK_END)], source_of("const backend = {"),
        source_of("async function platformMode(r){"), marks, source_of("function refreshTasks(next){"), source_of("function took(m, t){"),
        source_of("async function setMark(id, done, as){"), source_of("const unsavedMark = {};"), undo_section(),
        JS[JS.index(SYNC_START):JS.index(SYNC_END)], source_of("async function reloadState(){"), JS[JS.index(BACK_START):JS.index(BACK_END)],
        JS[JS.index(BOOT_START):]])


def boot(setup, body):
    """One visit: setup says what the browser and the server hold before the page's scripts run,
    body what happens after."""
    return run_node(BOOT_PAGE + setup + boot_sections() + "\nconst out = {};\n(async () => {\n" + body + "\nconsole.log(JSON.stringify(out));\n})();\n")


# What the server holds in most visits, and the copy the last visit kept of it.
BOOT_SERVER = """
window.SCHOOL_DATA = DATA;
there.marks = {a2: MARK('S1')};
there.tasks = {'task:aaaaaaaa': TASK('task:aaaaaaaa', 'Buy milk')};
there.platform = {status: 200, body: {apps: [], public: true}};
"""
BOOT_COPY = BOOT_SERVER + "keep('state', {at: {remote: true, public: true}, marks: there.marks, tasks: there.tasks});\n"
BOOT_SEEN = """
out.atStart = {draws: draws.length, shown: shown(), asked: [...net.log], events: [...events], fab: !els['#fab'].hidden, syncbox: !els['#syncbox'].hidden, syncBtn: !els['#syncBtn'].hidden};
"""
BOOT_ANSWERED = """
await answerNow();
out.answered = {draws: draws.length, shown: shown(), events: [...events], fab: !els['#fab'].hidden, syncbox: !els['#syncbox'].hidden, syncBtn: !els['#syncBtn'].hidden,
  kept: keptNow('state'), placed, errors, later: later.map(l => l.ms)};
"""


@unittest.skipUnless(NODE, "Node is not installed")
class BootTest(unittest.TestCase):
    """How the page starts: dashboard.js's own "starting", requests and copies, run under Node. A
    first visit goes as it always did; a later one is drawn at once from what the last one kept,
    and the server's answer is taken quietly."""

    def test_a_first_visit_asks_then_draws_what_the_server_says(self):
        out = boot(BOOT_SERVER, BOOT_SEEN + BOOT_ANSWERED)
        start, done = out["atStart"], out["answered"]
        # The list as of the last sync, with no ✓ buttons and no read-only banner while it asks.
        self.assertEqual(start["draws"], 1)
        self.assertEqual(start["shown"], {"data": "G1", "write": None, "live": False, "remote": False, "pub": False, "probing": True,
                                          "plan": "unknown", "marks": "a1", "tasks": None, "items": 3})
        # Where it is, the marks and the tasks, asked for together; nothing else, and no save.
        self.assertEqual(start["asked"], ["GET platform.json", "GET api/marks", "GET api/tasks"])
        self.assertEqual([start["events"], start["fab"], start["syncbox"]], [[], False, False])
        # Answered: drawn once more, as a page that saves; the planner is told; the answers are kept.
        self.assertEqual(done["draws"], 2)
        self.assertEqual(done["shown"], {"data": "G1", "write": "local", "live": False, "remote": True, "pub": True, "probing": False,
                                         "plan": "unknown", "marks": "a2", "tasks": "task:aaaaaaaa", "items": 4})
        self.assertEqual([done["events"], done["fab"], done["syncbox"], done["syncBtn"]], [["ready"], True, True, False])
        self.assertEqual(done["kept"]["at"], {"remote": True, "public": True})
        self.assertEqual([sorted(done["kept"]["marks"]), sorted(done["kept"]["tasks"])], [["a2"], ["task:aaaaaaaa"]])
        self.assertTrue(done["placed"])
        self.assertEqual(done["errors"], [])

    def test_a_later_visit_is_drawn_at_once_and_not_again(self):
        out = boot(BOOT_COPY, BOOT_SEEN + BOOT_ANSWERED)
        start, done = out["atStart"], out["answered"]
        full = {"data": "G1", "write": "local", "live": False, "remote": True, "pub": True, "probing": True,
                "plan": "unknown", "marks": "a2", "tasks": "task:aaaaaaaa", "items": 4}
        # Before any answer: the ✓ buttons, the tasks, the + button, and the planner told to start.
        self.assertEqual(start["draws"], 1)
        self.assertEqual(start["shown"], full)
        self.assertEqual([start["events"], start["fab"], start["syncbox"], start["syncBtn"]], [["ready"], True, True, False])
        # The server is asked all the same (never less than a first visit asks).
        self.assertEqual(start["asked"], ["GET platform.json", "GET api/marks", "GET api/tasks"])
        # Its answer is the copy: nothing is drawn again, and the planner is not told twice.
        self.assertEqual(done["draws"], 1)
        self.assertEqual(done["events"], ["ready"])
        self.assertTrue(done["placed"])
        self.assertEqual(done["later"], [3000, 0])  # the tidying, and the data kept, once the page is up

    def test_a_copy_that_is_behind_gives_way_in_place(self):
        out = boot(BOOT_COPY + """
there.marks.a3 = MARK('S2'); delete there.marks.a2;
there.tasks['task:bbbbbbbb'] = TASK('task:bbbbbbbb', 'Added on the phone');
""", "drawerId = 'task:aaaaaaaa';" + BOOT_SEEN + BOOT_ANSWERED + "out.drawer = [drawerId, closed];")
        self.assertEqual(out["atStart"]["shown"]["marks"], "a2")
        done = out["answered"]
        # Drawn once more with what the server has, by the page's own redraw: no load, the open
        # drawer stays (its item is still there), and the copy is the server's now.
        self.assertEqual(done["draws"], 2)
        self.assertEqual([done["shown"]["marks"], done["shown"]["tasks"]], ["a3", "task:aaaaaaaa task:bbbbbbbb"])
        self.assertEqual(done["events"], ["ready"])
        self.assertEqual([sorted(done["kept"]["marks"]), sorted(done["kept"]["tasks"])], [["a3"], ["task:aaaaaaaa", "task:bbbbbbbb"]])
        self.assertEqual(out["drawer"], ["task:aaaaaaaa", 0])

    def test_the_drawer_closes_only_when_its_task_is_gone(self):
        out = boot(BOOT_COPY + "there.tasks = {};", "drawerId = 'task:aaaaaaaa';" + BOOT_ANSWERED + "out.drawer = [drawerId, closed];")
        self.assertEqual(out["drawer"], [None, 1])

    def test_the_place_is_the_servers_not_the_copys(self):
        # Kept as the public copy, answered as this Mac (the same address run another way): the
        # page is drawn again with files and Sync now, and that is what is kept.
        out = boot(BOOT_COPY + "there.platform = {status: 204};", BOOT_SEEN + BOOT_ANSWERED)
        self.assertEqual([out["atStart"]["shown"]["pub"], out["atStart"]["syncBtn"]], [True, False])
        done = out["answered"]
        self.assertEqual(done["draws"], 2)
        self.assertEqual([done["shown"]["live"], done["shown"]["remote"], done["shown"]["pub"], done["syncBtn"]], [True, False, False, True])
        self.assertEqual(done["kept"]["at"], {"remote": False, "public": False})
        # And the other way round: Sync now goes.
        out = boot(BOOT_SERVER + "there.platform = {status: 204}; keep('state', {at: {remote: false, public: false}, marks: there.marks, tasks: there.tasks});"
                   + "there.platform = {status: 200, body: {apps: [], public: true}};", BOOT_SEEN + BOOT_ANSWERED)
        self.assertEqual([out["atStart"]["shown"]["live"], out["atStart"]["syncBtn"]], [True, True])
        self.assertEqual([out["answered"]["shown"]["live"], out["answered"]["syncBtn"], out["answered"]["draws"]], [False, False, 2])

    def test_a_change_made_before_the_answer_waits_and_then_lands(self):
        out = boot(BOOT_COPY, """
toggleMark('a3');                              // the ✓ on HW 3, in the page's first moment
await settle();
out.held = {posts: posts(), shown: shown().marks, toast: toasts[toasts.length - 1]};
await answerNow(q => q.method === 'GET');      // the server's answers, which do not hold it yet
out.afterAnswer = {shown: shown().marks, marks: Object.keys(marks).sort().join(' '), posts: posts(), draws: draws.length};
await answerNow();                             // the save's own answer
await Promise.all(steps.undo.map(s => s.settled));
out.saved = {there: Object.keys(there.marks).sort().join(' '), shown: shown().marks, kept: Object.keys(keptNow('state').marks).sort().join(' '), steps: steps.undo.map(s => s.label), toasts};
""")
        # Shown at once, sent only once the server has said where the page saves.
        self.assertEqual(out["held"], {"posts": [], "shown": "a2 a3", "toast": "Marked “HW 3” done [Undo]"})
        # The server's marks did not hold it: it stays on the page all the same, and then it is sent.
        self.assertEqual(out["afterAnswer"]["marks"], "a2 a3")
        self.assertEqual(out["afterAnswer"]["posts"], ["POST api/mark"])
        self.assertEqual(out["afterAnswer"]["draws"], 2)      # the first, and the ✓: none for the answer
        self.assertEqual(out["saved"], {"there": "a2 a3", "shown": "a2 a3", "kept": "a2 a3", "steps": ["marked “HW 3” done"], "toasts": ["Marked “HW 3” done [Undo]"]})

    def test_a_change_made_before_a_different_answer_keeps_both(self):
        out = boot(BOOT_COPY + "there.marks.a1 = MARK('S9');", """
toggleMark('a3');
await answerNow(q => q.method === 'GET');
out.afterAnswer = shown().marks;
await answerNow();
out.saved = [Object.keys(there.marks).sort().join(' '), shown().marks];
toggleMark('a2');                              // and one taken away the same way, later
await settle();
out.unmarkShown = shown().marks;
await answerNow();
out.unmarked = [Object.keys(there.marks).sort().join(' '), shown().marks];
""")
        self.assertEqual(out["afterAnswer"], "a1 a2 a3")
        self.assertEqual(out["saved"], ["a1 a2 a3", "a1 a2 a3"])
        self.assertEqual(out["unmarkShown"], "a1 a3")
        self.assertEqual(out["unmarked"], ["a1 a3", "a1 a3"])

    def test_no_answer_after_a_copy_is_a_page_that_does_not_save(self):
        out = boot(BOOT_COPY + "there.down = true;", BOOT_SEEN + """
toggleMark('a3');
await settle();
out.clicked = shown().marks;
""" + BOOT_ANSWERED + """
await Promise.all(steps.undo.map(s => s.settled)).catch(() => {});
await settle();
out.after = {shown: shown(), posts: posts(), toasts, steps: steps.undo.length, plan: plannerState, waiting: net.waiting.length};
""")
        self.assertEqual(out["atStart"]["shown"]["write"], "local")
        self.assertEqual(out["clicked"], "a2 a3")
        done, after = out["answered"], out["after"]
        # As the page is without a copy when the server does not answer: the last sync's marks and
        # tasks, no ✓ buttons, no + button, no planner. The change was never sent; it is put back,
        # says so, and is no step. The copy goes.
        self.assertEqual(after["shown"], {"data": "G1", "write": None, "live": False, "remote": False, "pub": False, "probing": False,
                                          "plan": "off", "marks": "a1", "tasks": None, "items": 3})
        self.assertEqual([done["fab"], done["syncBtn"], after["plan"]], [False, False, "off"])
        self.assertEqual(after["posts"], [])
        self.assertEqual(after["toasts"][-1], "Couldn't save. Check your connection and try again.")
        self.assertEqual(after["steps"], 0)
        self.assertIsNone(done["kept"])
        self.assertEqual(done["events"], ["ready"])
        self.assertFalse(done["placed"])

    def test_no_answer_on_a_first_visit_is_as_before(self):
        out = boot(BOOT_SERVER + "there.down = true;", BOOT_SEEN + BOOT_ANSWERED)
        done = out["answered"]
        self.assertEqual(done["draws"], 2)
        self.assertEqual(done["shown"], {"data": "G1", "write": None, "live": False, "remote": False, "pub": False, "probing": False,
                                         "plan": "unknown", "marks": "a1", "tasks": None, "items": 3})
        self.assertEqual([done["events"], done["fab"], done["syncbox"]], [["ready"], False, True])
        self.assertIsNone(done["kept"])

    def test_the_tasks_not_answering_alone_leaves_the_last_syncs(self):
        out = boot(BOOT_SERVER, "await answerNow(q => q.url !== 'api/tasks'); net.waiting.forEach(q => q.rej(new Error('x'))); net.waiting = []; await settle();"
                   + "out.shown = shown(); out.kept = keptNow('state');")
        self.assertEqual([out["shown"]["write"], out["shown"]["marks"], out["shown"]["tasks"]], ["local", "a2", None])
        self.assertIsNone(out["kept"])      # only both together are kept

    def test_the_phone_site_starts_the_same_way(self):
        phone = "PHONE = true; location.pathname = '/k/'; window.SCHOOL_DATA = DATA; there.marks = {a2: MARK('S1')}; there.tasks = {'task:aaaaaaaa': TASK('task:aaaaaaaa', 'Buy milk')};\n"
        first = boot(phone, BOOT_SEEN + "await answerNow(); out.answered = {draws: draws.length, shown: shown(), events: [...events], fab: !els['#fab'].hidden, kept: keptNow('state', 'phone', '/k/')};")
        self.assertEqual(first["atStart"]["asked"], ["GET /api/state/"])
        self.assertEqual([first["atStart"]["shown"]["write"], first["atStart"]["shown"]["probing"], first["atStart"]["events"], first["atStart"]["fab"]], [None, False, ["ready"], False])
        self.assertEqual([first["answered"]["shown"]["write"], first["answered"]["shown"]["marks"], first["answered"]["fab"], first["answered"]["draws"]], ["cloud", "a2", True, 2])
        self.assertEqual(first["answered"]["events"], ["ready"])
        self.assertEqual(first["answered"]["kept"], {"at": None, "marks": {"a2": {"marked_at": "S1", "name": None, "course": None}},
                                                     "tasks": {"task:aaaaaaaa": first["answered"]["kept"]["tasks"]["task:aaaaaaaa"]}})
        later = boot(phone + "keep('state', {at: null, marks: there.marks, tasks: there.tasks}, {place: 'phone', path: '/k/'});", BOOT_SEEN + """
toggleMark('a3');
await settle();
out.held = posts();
await answerNow(q => q.method === 'GET');
out.sent = [posts(), draws.length, shown().marks];
await answerNow();
out.saved = [Object.keys(there.marks).sort().join(' '), Object.keys(keptNow('state', 'phone', '/k/').marks).sort().join(' ')];
""")
        self.assertEqual([later["atStart"]["shown"]["write"], later["atStart"]["shown"]["marks"], later["atStart"]["fab"]], ["cloud", "a2", True])
        self.assertEqual(later["held"], [])
        self.assertEqual(later["sent"], [["POST /api/state/"], 2, "a2 a3"])
        self.assertEqual(later["saved"], ["a2 a3", "a2 a3"])
        # A server's copy at the same path is not the phone site's, and the cloud not answering
        # after a copy leaves the read-only page it always was.
        other = boot(phone + "keep('state', {at: {remote: false, public: false}, marks: there.marks, tasks: there.tasks}, {path: '/k/'});", BOOT_SEEN)
        self.assertEqual(other["atStart"]["shown"]["write"], None)
        down = boot(phone + "keep('state', {at: null, marks: there.marks, tasks: there.tasks}, {place: 'phone', path: '/k/'}); there.down = true;",
                    "await answerNow(); out.shown = shown(); out.fab = !els['#fab'].hidden; out.kept = keptNow('state', 'phone', '/k/');")
        self.assertEqual([down["shown"]["write"], down["shown"]["marks"], down["shown"]["tasks"], down["fab"], down["kept"]], [None, "a1", None, False, None])

    def test_from_disk_nothing_is_asked_or_kept(self):
        out = boot("LOCAL_FILES = true; window.SCHOOL_DATA = DATA; keep('state', {at: {remote: false, public: false}, marks: {}, tasks: {}}); keep('data', {...DATA, generated_at: 'OLD'});",
                   BOOT_SEEN + "later.forEach(l => l.fn()); await settle(); out.kept = [...stored.keys()].sort(); out.draws = draws.length;")
        self.assertEqual(out["atStart"]["asked"], [])
        self.assertEqual([out["atStart"]["shown"]["data"], out["atStart"]["shown"]["write"], out["atStart"]["events"]], ["G1", None, ["ready"]])
        self.assertEqual(out["draws"], 1)
        self.assertEqual(len(out["kept"]), 2)      # (the two this test put there; tidying leaves them their time)

    def test_the_page_starts_without_storage(self):
        for how in ("gone", "deny", "quota"):
            with self.subTest(storage=how):
                out = boot(BOOT_COPY + f"broken = '{how}';", BOOT_SEEN + """
toggleMark('a3');
await answerNow(); await answerNow();
later.forEach(l => l.fn());
await settle();
out.end = {shown: shown(), there: Object.keys(there.marks).sort().join(' '), errors, events, state: stored.has('sh:kept:1:state:server:/school/')};
""")
                # Unreadable storage: a first visit. A full one: the copy is read, then goes, since
                # the newer answer could not be kept in its place.
                self.assertEqual(out["atStart"]["shown"]["write"], "local" if how == "quota" else None)
                self.assertEqual([out["end"]["shown"]["write"], out["end"]["shown"]["marks"], out["end"]["there"]], ["local", "a2 a3", "a2 a3"])
                self.assertEqual(out["end"]["errors"], [])
                self.assertEqual(out["end"]["events"], ["ready"])
                self.assertEqual(out["end"]["state"], how != "quota")

    def test_coming_back_to_the_tab_draws_only_what_changed(self):
        out = boot(BOOT_COPY, """
await answerNow();
const n = draws.length;
// Nothing changed: nothing is drawn, and "Synced … ago" is said for now.
let back = reloadState(); await settle(); await answerNow(); await answerNow(); await back;
out.same = [draws.length - n, synced, events.filter(e => e === 'reload').length];
// A mark made on another device: drawn once.
there.marks.a1 = MARK('S7');
back = reloadState(); await settle(); await answerNow(); await answerNow(); await back;
out.changed = [draws.length - n, shown().marks, synced];
// Marks read before a save of this page reached the server come back after the save's own
// answer: they are older, and are not taken.
back = reloadState(); await settle();
const read = net.waiting.find(q => q.url === 'api/marks'), old = copy(there.marks);
net.waiting = net.waiting.filter(q => q !== read);
toggleMark('a3');
await settle();
await answerNow(q => q.method === 'POST');
out.saved = [posts().length, Object.keys(unsavedMark).length];
read.res({ok: true, status: 200, json: async () => old});
await settle(); await answerNow(); await back;
out.stale = [shown().marks, Object.keys(there.marks).sort().join(' ')];
""")
        self.assertEqual(out["same"], [0, 1, 1])
        self.assertEqual(out["changed"], [1, "a1 a2", 1])
        self.assertEqual(out["saved"], [1, 0])      # the save is answered and done with before the old read comes in
        self.assertEqual(out["stale"], ["a1 a2 a3", "a1 a2 a3"])


# The last sync's data: data.js when it is here, else the copy kept of it.
DATA_SEEN = "out.atStart = {draws: draws.length, shown: shown() || null, waitsFor: [Object.keys(script.on).sort(), Object.keys(window.on).filter(k => k === 'load')], main: els['#main'].innerHTML, errors: [...errors]};\n"
DATA_ARRIVES = """
const arrive = async (data, by = () => script.on.load()) => { window.SCHOOL_DATA = data; by(); later.splice(0).forEach(l => l.fn()); await settle(); };
"""


@unittest.skipUnless(NODE, "Node is not installed")
class BootDataTest(unittest.TestCase):
    """data.js no longer holds the page up: here already, the page starts from it; not yet, from the
    copy kept of it; with neither, when it arrives. dashboard.js's own code under Node."""

    def test_here_already_the_page_starts_from_it_and_keeps_it(self):
        out = boot(BOOT_SERVER, DATA_SEEN + "later.forEach(l => l.fn()); out.kept = keptNow('data'); out.draws = draws.length;")
        self.assertEqual([out["atStart"]["draws"], out["atStart"]["shown"]["data"], out["atStart"]["waitsFor"]], [1, "G1", [[], []]])
        self.assertEqual(out["kept"]["generated_at"], "G1")
        self.assertEqual(out["draws"], 1)

    def test_not_here_yet_the_copy_is_drawn_and_the_same_data_changes_nothing(self):
        out = boot("there.marks = {}; keep('data', DATA);", DATA_SEEN + DATA_ARRIVES + """
const before = stored.get('sh:kept:1:data:server:/school/');
await arrive(copy(DATA));
out.same = {draws: draws.length, shown: shown().data, keptAgain: stored.get('sh:kept:1:data:server:/school/') !== before};
""")
        self.assertEqual([out["atStart"]["draws"], out["atStart"]["shown"]["data"], out["atStart"]["shown"]["marks"]], [1, "G1", "a1"])
        self.assertEqual(out["atStart"]["waitsFor"], [["error", "load"], ["load"]])
        self.assertEqual(out["same"], {"draws": 1, "shown": "G1", "keptAgain": False})

    def test_a_newer_sync_takes_the_copys_place_on_the_page(self):
        out = boot(BOOT_COPY.replace("window.SCHOOL_DATA = DATA;", "") + "keep('data', DATA);", DATA_ARRIVES + """
await answerNow();
drawerId = 'a3';
const n = draws.length;
const next = copy(DATA); next.generated_at = 'G2'; next.courses[0].assignments = next.courses[0].assignments.filter(a => a.id !== 'a3').concat({id: 'a4', name: 'HW 4'});
await arrive(next);
out.newer = {draws: draws.length - n, shown: shown(), kept: keptNow('data').generated_at, drawer: [drawerId, closed], events};
""")
        newer = out["newer"]
        # Drawn once more, with the server's marks and tasks as they were; "Synced" follows the data.
        self.assertEqual(newer["draws"], 1)
        self.assertEqual([newer["shown"]["data"], newer["shown"]["marks"], newer["shown"]["tasks"], newer["shown"]["write"]], ["G2", "a2", "task:aaaaaaaa", "local"])
        self.assertEqual(newer["kept"], "G2")
        self.assertEqual(newer["drawer"], [None, 1])     # its item is not in the new sync
        self.assertEqual(newer["events"], ["ready"])

    def test_with_no_server_the_last_syncs_marks_follow_the_data(self):
        out = boot("there.down = true; keep('data', DATA);", DATA_ARRIVES + """
await answerNow();
const next = copy(DATA); next.generated_at = 'G2'; next.courses[0].assignments[1].marked_done = 'M1';
await arrive(next);
out.shown = shown();
""")
        self.assertEqual([out["shown"]["data"], out["shown"]["write"], out["shown"]["marks"]], ["G2", None, "a1 a2"])

    def test_a_first_visit_waits_for_data_js_as_it_always_did(self):
        out = boot("there.marks = {a2: MARK('S1')};", DATA_SEEN + DATA_ARRIVES + """
out.asked = [...net.log];
await arrive(DATA);
out.started = {draws: draws.length, shown: shown(), asked: [...net.log], kept: keptNow('data')?.generated_at};
""")
        self.assertEqual([out["atStart"]["draws"], out["atStart"]["shown"], out["asked"]], [0, None, []])
        self.assertEqual([out["started"]["draws"], out["started"]["shown"]["data"], out["started"]["shown"]["probing"]], [1, "G1", True])
        self.assertEqual(out["started"]["asked"], ["GET platform.json", "GET api/marks", "GET api/tasks"])
        self.assertEqual(out["started"]["kept"], "G1")

    def test_its_arrival_is_not_missed(self):
        # The script's own events may have passed before this file ran: the window's load tells too.
        out = boot("", DATA_ARRIVES + "await arrive(DATA, () => window.on.load()); out.draws = draws.length; script.on.load(); script.on.error(); await settle(); out.again = draws.length;")
        self.assertEqual([out["draws"], out["again"]], [1, 1])

    def test_no_data_at_all_says_what_to_do(self):
        out = boot("", DATA_ARRIVES + "window.SCHOOL_DATA = undefined; script.on.error(); await settle(); out.main = els['#main'].innerHTML; out.draws = draws.length; out.asked = net.log;")
        self.assertEqual(out["main"], '<p class="empty">No data yet. Run <code>python3 sync.py</code> in the SchoolHub folder.</p>')
        self.assertEqual([out["draws"], out["asked"]], [0, []])
        # With a copy on show, the copy stays, under its own sync time.
        out = boot("there.marks = {}; keep('data', DATA);", "script.on.error(); await settle(); out.main = els['#main'].innerHTML; out.draws = draws.length; out.shown = shown().data; out.kept = !!keptNow('data');")
        self.assertEqual([out["main"], out["draws"], out["shown"], out["kept"]], ["", 1, "G1", True])

    def test_a_copy_that_is_old_misplaced_or_broken_is_not_drawn(self):
        cases = {"old": "keep('data', DATA, {age: 3.5});", "other path": "keep('data', DATA, {path: '/'});", "phone's": "keep('data', DATA, {place: 'phone'});",
                 "cut short": "keep('data', null, {text: JSON.stringify(DATA).slice(0, 80)});", "not data": "keep('data', {generated_at: 'G1', courses: 'none'});"}
        for name, setup in cases.items():
            with self.subTest(copy=name):
                out = boot(setup, DATA_SEEN)
                self.assertEqual([out["atStart"]["draws"], out["atStart"]["waitsFor"]], [0, [["error", "load"], ["load"]]])
                # Left alone for what it is, not tried and found undrawable.
                self.assertEqual(out["atStart"]["errors"], [])

    def test_a_copy_that_cannot_be_drawn_is_dropped(self):
        # The data's copy: the page waits for data.js, as on a first visit.
        out = boot("keep('data', {...DATA, generated_at: 'BAD'}); cannotDraw = () => D.generated_at === 'BAD';", DATA_SEEN + DATA_ARRIVES + """
out.dropped = [keptNow('data'), errors.length > 0, net.log.length];
await arrive(DATA);
out.started = [draws.length, shown().data, keptNow('data').generated_at];
""")
        self.assertEqual(out["atStart"]["draws"], 0)
        self.assertEqual(out["dropped"], [None, True, 0])
        self.assertEqual(out["started"], [1, "G1", "G1"])
        # The marks' and tasks' copy: the page starts without it, as on a first visit.
        out = boot(BOOT_COPY + "cannotDraw = () => WRITE === 'local' && !placed;", BOOT_SEEN + BOOT_ANSWERED)
        self.assertEqual([out["atStart"]["draws"], out["atStart"]["shown"]["write"], out["atStart"]["events"]], [1, None, []])
        self.assertEqual([out["answered"]["shown"]["write"], out["answered"]["events"]], ["local", ["ready"]])

    def test_data_too_long_to_keep_leaves_no_copy(self):
        out = boot("keep('data', DATA); window.SCHOOL_DATA = {...DATA, generated_at: 'G2', pad: 'x'.repeat(1500000)};",
                   "later.forEach(l => l.fn()); out.kept = keptNow('data'); out.shown = shown().data;")
        self.assertEqual([out["kept"], out["shown"]], [None, "G2"])


# ---- a sync that ran while the page was open (dashboard.js "sync now", "back on show") ----
# The page on your Mac's own server (platform.json answers 204), started and answered; `watch` lists
# the looks at api/sync that wait, and `minute` lets the next one happen.
BOOT_MAC = """
window.SCHOOL_DATA = DATA;
there.marks = {a2: MARK('S1')};
there.tasks = {'task:aaaaaaaa': TASK('task:aaaaaaaa', 'Buy milk')};
let loads = 0;
location.reload = () => { loads++; };
"""
WATCHING = """
const watch = () => later.filter(l => l.fn === lookAtSync).map(l => l.ms);
const minute = async () => { const i = later.findIndex(l => l.fn === lookAtSync); later.splice(i, 1)[0].fn(); await settle(); };
const asked = () => { const log = [...net.log]; net.log.length = 0; return log; };
const NEXT = copy(DATA);
NEXT.generated_at = 'G2';
NEXT.courses[0].assignments = NEXT.courses[0].assignments.filter(a => a.id !== 'a3').concat({id: 'a4', name: 'HW 4'});
const button = () => [els['#syncBtn'].disabled, els['#syncBtn'].textContent];
"""
WATCH_STARTED = WATCHING + """
await answerNow(); await answerNow();
// What the page does a moment after it is up (data.js noted as here and kept, the copies tidied).
for (const l of later.splice(0)) { if (l.fn === lookAtSync) later.push(l); else l.fn(); }
out.start = {asked: asked(), watch: watch()};
const n = draws.length;
"""


@unittest.skipUnless(NODE, "Node is not installed")
class WatchSyncTest(unittest.TestCase):
    """An open page notices a sync that ran by itself and takes its data in place: dashboard.js's own
    code under Node, with the page, its timers, the network and the browser's storage stood in for."""

    def test_it_looks_once_a_minute_and_only_while_on_show(self):
        out = boot(BOOT_MAC, WATCH_STARTED + """
await minute();
out.look = {asked: asked(), watch: watch()};
await answerNow();
out.answered = {watch: watch(), draws: draws.length - n};
// Out of view: the wait is over, and nothing is asked however a look comes about.
show(false);
out.hidden = watch();
lookAtSync(); watchSync(); await settle();
out.hiddenLook = {asked: asked(), watch: watch(), timers: later.length};
// Back on show: asked at once, with the marks and tasks as before.
show(true); await settle();
out.back = asked().sort();
await answerNow(); await answerNow();
out.backDone = {asked: asked(), watch: watch(), draws: draws.length - n, loads};
""")
        # At the start, as before: where the page is, the marks, the tasks, and the sync's state.
        self.assertEqual(out["start"], {"asked": ["GET platform.json", "GET api/marks", "GET api/tasks", "GET api/sync"], "watch": [60000]})
        self.assertEqual(out["look"], {"asked": ["GET api/sync"], "watch": []})
        self.assertEqual(out["answered"], {"watch": [60000], "draws": 0})
        self.assertEqual(out["hidden"], [])
        self.assertEqual(out["hiddenLook"], {"asked": [], "watch": [], "timers": 0})
        self.assertEqual(out["back"], ["GET api/marks", "GET api/sync"])
        self.assertEqual(out["backDone"], {"asked": ["GET api/tasks"], "watch": [60000], "draws": 0, "loads": 0})

    def test_new_data_is_taken_in_place(self):
        out = boot(BOOT_MAC, WATCH_STARTED + """
// What must survive: an open drawer, and a step in the undo history.
drawerId = 'a1';
toggleMark('a2'); await settle(); await answerNow(q => q.method === 'POST');
const before = {steps: steps.undo.length, label: steps.undo[0].label, draws: draws.length};
asked();
// A sync is running (the server's own, say): Sync now says so, and the page looks again soon.
there.sync = {running: true, data_at: 'G1'};
await minute(); await answerNow();
out.running = {asked: asked(), button: button(), watch: watch(), draws: draws.length - before.draws};
// It ended, and the data on the Mac is another sync's.
there.sync = {running: false, data_at: 'G2'}; there.dataJs = asDataJs(NEXT);
await minute(); await answerNow();
out.told = asked();
await answerNow();
out.taken = {button: button(), draws: draws.length - before.draws, shown: shown(), kept: keptNow('data').generated_at, drawer: [drawerId, closed],
  steps: [steps.undo.length, steps.undo[0].label === before.label, steps.redo.length], loads, toasts: toasts.length, errors};
await answerNow(); await answerNow();
out.after = {asked: asked(), draws: draws.length - before.draws, watch: watch(), reloads: events.filter(e => e === 'reload').length, unread};
// The same data at the next look: only the look itself, and nothing is drawn.
await minute(); await answerNow(); await answerNow();
out.same = {asked: asked(), draws: draws.length - before.draws, watch: watch()};
// The undo history still works on the new data.
SchoolHubUndo: { travel('undo'); await settle(); await answerNow(); await answerNow(); await answerNow(); }
out.undone = {marks: Object.keys(there.marks).sort().join(' '), steps: [steps.undo.length, steps.redo.length]};
""")
        self.assertEqual(out["running"], {"asked": ["GET api/sync"], "button": [True, "Syncing…"], "watch": [3000], "draws": 0})
        self.assertEqual(out["told"], ["GET api/sync", "GET data.js"])
        taken = out["taken"]
        # Drawn once from the new sync, with the marks and tasks the page had; Sync now is back.
        self.assertEqual([taken["button"], taken["draws"]], [[False, "Sync now"], 1])
        self.assertEqual(taken["shown"], {"data": "G2", "write": "local", "live": True, "remote": False, "pub": False, "probing": False,
                                          "plan": "unknown", "marks": "", "tasks": "task:aaaaaaaa", "items": 4})
        # Kept for the next visit; the drawer stays open on its item; the undo history is as it was.
        self.assertEqual(taken["kept"], "G2")
        self.assertEqual(taken["drawer"], ["a1", 0])
        self.assertEqual(taken["steps"], [1, True, 0])
        # No page load, nothing said, nothing gone wrong.
        self.assertEqual([taken["loads"], taken["errors"]], [0, []])
        self.assertEqual(taken["toasts"], 1)                 # the ✓'s own, from before
        # Then the marks and tasks as stored now (the sync checked the marks), and the minute's wait.
        self.assertEqual(out["after"], {"asked": ["GET api/marks", "GET api/tasks"], "draws": 1, "watch": [60000], "reloads": 1, "unread": None})
        self.assertEqual(out["same"], {"asked": ["GET api/sync"], "draws": 1, "watch": [60000]})
        self.assertEqual(out["undone"], {"marks": "a2", "steps": [0, 1]})

    def test_data_that_cannot_be_taken_leaves_the_page_and_offers_the_load(self):
        out = boot(BOOT_MAC, WATCH_STARTED + """
const state = () => ({asked: asked(), draws: draws.length - n, unread, data: D.generated_at, shown: shown().data, kept: keptNow('data').generated_at, watch: watch(), loads});
const look = async () => { await minute(); for (let i = 0; i < 5; i++) await answerNow(); return state(); };
// data.js not answered: nothing changes, and the next look asks again.
there.sync = {running: false, data_at: 'G2'};
out.unanswered = await look();
out.again = await look();
// Not what data.js holds: the page stays as it is, and offers the load (drawn again to show it).
there.dataJs = 'window.SCHOOL_DATA = {"generated_at": "G2", "courses": "none"};\\n';
out.notData = await look();
// Not asked again for the same sync.
out.notAgain = await look();
// Data the page cannot draw: back to what it had.
there.sync.data_at = 'G3'; there.dataJs = asDataJs({...NEXT, generated_at: 'G3'});
cannotDraw = () => D.generated_at === 'G3';
out.cannotDraw = await look();
out.logged = errors.length;
// The next sync's can be taken: the offer goes, and is not drawn with it.
const offered = [];
cannotDraw = () => { offered.push(unread); return false; };
there.sync.data_at = 'G4'; there.dataJs = asDataJs({...NEXT, generated_at: 'G4'});
out.next = await look();
out.offered = offered;
// How data.js is read.
out.read = [readData(asDataJs(DATA)).generated_at, readData('window.SCHOOL_DATA = ' + JSON.stringify(DATA)).generated_at, readData(JSON.stringify(DATA).slice(0, 80)), readData(''), readData('window.SCHOOL_DATA = null;')];
""")
        calm = {"asked": ["GET api/sync", "GET data.js"], "draws": 0, "unread": None, "data": "G1", "shown": "G1", "kept": "G1", "watch": [60000], "loads": 0}
        self.assertEqual(out["unanswered"], calm)
        self.assertEqual(out["again"], calm)
        self.assertEqual(out["notData"], {**calm, "draws": 1, "unread": "G2"})
        self.assertEqual(out["notAgain"], {**calm, "asked": ["GET api/sync"], "draws": 1, "unread": "G2"})
        self.assertEqual(out["cannotDraw"], {**calm, "draws": 2, "unread": "G3"})
        self.assertEqual(out["logged"], 2)
        self.assertEqual(out["next"], {"asked": ["GET api/sync", "GET data.js", "GET api/marks", "GET api/tasks"], "draws": 3, "unread": None,
                                       "data": "G4", "shown": "G4", "kept": "G4", "watch": [60000], "loads": 0})
        self.assertEqual(out["offered"], [None])
        self.assertEqual(out["read"], ["G1", "G1", None, None, None])
        # The offer: a quiet line above the list, and the only load is the one you press.
        self.assertIn("""const newer = unread ? '<div class="banner">New data · <button type="button" class="linkish" id="newData">Refresh</button></div>' : '';""", JS)
        self.assertIn('return banner + none + newer + errs + `<div class="stats">', JS)
        self.assertIn("  if (e.target.closest('#newData')) return location.reload();", JS)

    def test_not_before_data_js_has_come_and_not_in_the_middle_of_a_drag(self):
        # Opened from the copy of an older sync: data.js is on its way, and is not asked for twice.
        old = "there.platform = {status: 204}; there.sync = {running: false, data_at: 'G1'}; there.dataJs = asDataJs(DATA);\n" \
              "keep('data', {...DATA, generated_at: 'G0'}); keep('state', {at: {remote: false, public: false}, marks: {}, tasks: {}});\n"
        out = boot(old, WATCHING + DATA_ARRIVES + """
await answerNow(); await answerNow();
out.early = {asked: asked(), shown: shown().data, watch: watch()};
window.SCHOOL_DATA = DATA; script.on.load(); await settle();
out.came = {asked: asked(), shown: shown().data};
await minute(); await answerNow(); await answerNow();
out.later = {asked: asked(), shown: shown().data};
""")
        self.assertEqual(out["early"], {"asked": ["GET api/sync", "GET platform.json", "GET api/marks", "GET api/tasks"], "shown": "G0", "watch": [60000]})
        self.assertEqual(out["came"], {"asked": [], "shown": "G1"})
        self.assertEqual(out["later"], {"asked": ["GET api/sync"], "shown": "G1"})
        # A block being dragged on the planner (what holds undo's keys): the data waits, a moment.
        out = boot(BOOT_MAC, WATCH_STARTED + """
let dragging = true;
holds.push(() => dragging);
there.sync = {running: false, data_at: 'G2'}; there.dataJs = asDataJs(NEXT);
await minute(); await answerNow(); await answerNow();
out.held = {asked: asked(), shown: shown().data, watch: watch()};
dragging = false;
await minute(); await answerNow(); await answerNow();
out.dropped = {asked: asked(), shown: shown().data};
""")
        self.assertEqual(out["held"], {"asked": ["GET api/sync"], "shown": "G1", "watch": [3000]})
        self.assertEqual(out["dropped"], {"asked": ["GET api/sync", "GET data.js", "GET api/marks"], "shown": "G2"})

    def test_only_where_the_macs_own_server_answers(self):
        seen = WATCHING + """
for (let i = 0; i < 3; i++) await answerNow();
later.splice(0).forEach(l => l.fn()); await settle();
show(false); show(true); await settle();
for (let i = 0; i < 3; i++) await answerNow();
out.sync = net.log.filter(l => l.includes('sync') || l.includes('data.js'));
out.watch = watch();
out.live = LIVE;
"""
        # A public copy, the phone site and a file on disk: api/sync is never asked, and no look waits.
        public = boot(BOOT_SERVER + "there.sync = {running: false, data_at: 'G2'};", seen)
        phone = boot("PHONE = true; window.SCHOOL_DATA = DATA; there.sync = {running: false, data_at: 'G2'};", seen)
        disk = boot("LOCAL_FILES = true; window.SCHOOL_DATA = DATA;", seen)
        for name, got in (("public", public), ("phone", phone), ("disk", disk)):
            self.assertEqual([got["sync"], got["watch"], got["live"]], [[], [], False], name)
        # From another device through a platform, the Mac's server answers all the same.
        remote = boot(BOOT_MAC + "there.platform = {status: 200, body: {apps: [], remote: true}};", seen)
        self.assertEqual([set(remote["sync"]), remote["watch"], remote["live"]], [{"GET api/sync"}, [60000], True])

    def test_a_page_drawn_anew_does_not_scroll(self):
        # Focus is put back on the control that had it, and nothing scrolls for that: seen in a
        # browser, a plain focus() on a control of the planner (which sticks under the bar) sent a
        # scrolled window to the end of the page, and one on the drawer's Close sent the drawer to
        # its top.
        self.assertIn("    if (el) return el.focus({preventScroll: true});", JS)
        self.assertEqual(PLANNER.count("if (key) root.querySelector(key)?.focus({preventScroll: true});"), 2)
        self.assertNotIn("root.querySelector(key)?.focus();", PLANNER)
        # The drawer stays where it was read, and the list is drawn in its own box.
        self.assertIn("const top = drawerId === id ? drawer.scrollTop : 0;", JS)
        self.assertIn("  main.innerHTML = stats() + (view === 'courses' ? coursesView(vis) : upcomingView(vis));", JS)

    def test_sync_now_keeps_its_own_wait(self):
        out = boot(BOOT_MAC, WATCH_STARTED + """
els['#syncBtn'].onclick(); await settle(); await answerNow();
out.pressed = {asked: asked(), later: later.map(l => l.ms), button: button()};
// Nothing looks beside it, on a return to the tab either.
show(false); show(true); await settle(); await answerNow(); await answerNow();
out.back = asked().filter(l => l.includes('sync'));
""")
        self.assertEqual(out["pressed"], {"asked": ["POST api/sync"], "later": [1500], "button": [True, "Syncing…"]})
        self.assertEqual(out["back"], [])


@unittest.skipUnless(NODE, "Node is not installed")
class BackOnShowTest(unittest.TestCase):
    """A page the browser brings back from its back/forward cache is asked again, as a tab that
    comes back into view is: it is never shown as it was left without a word."""

    def test_a_page_brought_back_asks_again(self):
        out = boot(BOOT_MAC, WATCH_STARTED + """
// A first showing (not from the cache) is the page's own start: nothing more.
window.on.pageshow({persisted: false}); await settle();
out.first = asked();
// Brought back: the marks and tasks, and the sync's state.
there.marks.a1 = MARK('S9');
window.on.pageshow({persisted: true}); await settle();
out.restored = asked().sort();
// The tab's own event for the same return asks nothing more.
show(true); await settle();
out.both = asked();
await answerNow(); await answerNow();
out.done = {asked: asked(), draws: draws.length - n, marks: shown().marks, reloads: events.filter(e => e === 'reload').length, loads};
// The next return asks again.
window.on.pageshow({persisted: true}); await settle();
out.next = asked().sort();
""")
        self.assertEqual(out["first"], [])
        self.assertEqual(out["restored"], ["GET api/marks", "GET api/sync"])
        self.assertEqual(out["both"], [])
        self.assertEqual(out["done"], {"asked": ["GET api/tasks"], "draws": 1, "marks": "a1 a2", "reloads": 1, "loads": 0})
        self.assertEqual(out["next"], ["GET api/marks", "GET api/sync"])

    def test_a_public_copy_is_asked_again_too(self):
        out = boot(BOOT_SERVER, WATCHING + """
await answerNow(); asked();
window.on.pageshow({persisted: true}); await settle();
out.restored = asked();
""")
        self.assertEqual(out["restored"], ["GET api/marks"])        # (then the tasks; never api/sync)

    def test_where_it_is_wired(self):
        back = JS[JS.index(BACK_START):JS.index(BACK_END)]
        self.assertIn("document.addEventListener('visibilitychange', () => { if (document.hidden) watchSync(); else backOnShow(); });", back)
        self.assertIn("window.addEventListener('pageshow', e => { if (e.persisted) backOnShow(); });", back)
        # Nothing keeps the page out of that cache: no unload or beforeunload listener anywhere.
        for text in (JS, PLANNER, BAR):
            self.assertNotIn("'unload'", text)
            self.assertNotIn("beforeunload", text)


# The planner's plan with dashboard.js's namespace, its copies and /api/plan stood in for. gate, when
# set, is what a request waits for; timers lists what the planner asked to do later.
PLAN_COPY_PAGE = """
const store = {};
let down = false, refuse = false, missing = false, renders = 0, unlocks = 0, planner = 'unknown', saves = 'local', gate = null;
const copy = v => v == null ? null : JSON.parse(JSON.stringify(v));
const realTimeout = globalThis.setTimeout;
const timers = [];
const setTimeout = (fn, ms) => { timers.push({fn, ms, on: true}); return timers.length; };
const clearTimeout = id => { if (timers[id - 1]) timers[id - 1].on = false; };
const keptPlan = {text: null, writes: 0, drops: 0};
const SH = {same, addStep, offerStep, toast, get plannerState(){ return planner; }, setPlanner(next){ planner = next; }, get mode(){ return {WRITE: saves}; },
  kept: {read: () => { try { return JSON.parse(keptPlan.text); } catch { return null; } },
    write: (what, text) => { keptPlan.text = text; keptPlan.writes++; return true; }, drop: () => { keptPlan.text = null; keptPlan.drops++; }},
  api: async (path, body) => {
    if (down || refuse) throw new Error('refused');
    if (body.value === null) delete store[body.key]; else store[body.key] = copy(body.value);
    return {key: body.key, value: copy(body.value)};
  }};
const fetch = async () => {
  if (gate) await gate;
  if (down) throw new Error('down');
  if (missing) return {ok: false, status: 404, json: async () => ({})};
  const days = {}, week = {};
  for (const k of Object.keys(store)) if (k.startsWith('day:')) days[k.slice(4)] = copy(store[k]);
  for (const wd of WD) week[wd] = copy(store['week:' + wd]);
  return {ok: true, status: 200, json: async () => ({settings: copy(store.settings), week, days})};
};
function render(){ renders++; }
function unlock(){ unlocks++; }
const entriesOn = d => (plan.days[d]?.blocks || []).map(b => b.title);
const focusLost = () => false, refSel = ref => ref, refocus = () => {};
function setDate(d){ shown = d; }
"""
PLAN_COPY_BODY = """
const T = todayIso(), Y = addDays(T, -1);
const idle = async () => { while (pending) await chain; for (let i = 0; i < 4; i++) await new Promise(r => realTimeout(r, 0)); };
const LAB = {id: 'blockaaaa1', type: 'deep', title: 'Lab', start: '09:00', end: '10:00', items: []};
const GYM = {id: 'blockbbbb2', type: 'other', title: 'Gym', start: '18:00', end: '19:00', items: []};
// The copy a visit leaves of a day that holds these blocks (as keepPlan writes it).
const copyOf = (blocks, {from = addDays(T, -7), to = addDays(T, 7), day = T} = {}) =>
  JSON.stringify({from, to, plan: {settings: {day_start: 5, day_end: 24}, week: Object.fromEntries(WD.map(wd => [wd, cleanWeek(null)])), days: {[day]: {blocks}}}});
const state = () => ({plan: !!plan, copied, waiting, editable: editable(), planner, renders, unlocks, today: plan ? entriesOn(T) : null, failed: loadFailed});
const out = {};
"""


def plan_copy(body):
    """One visit of the planner: body runs after planner.js's own plan code is in place."""
    pure = PLANNER[PLANNER.index(PLAN_START):PLANNER.index(PLAN_END)]
    kept = PLANNER[PLANNER.index(PLAN_KEPT_START):PLANNER.index(PLAN_KEPT_END)]
    return run_node("const backend = {};\nasync function setMark(){ return true; }\n" + UNDO_PAGE + undo_section() + pure + PLAN_COPY_PAGE + kept
                    + PLAN_COPY_BODY + "(async () => {\n" + body + "\nconsole.log(JSON.stringify(out));\n})();\n")


@unittest.skipUnless(NODE, "Node is not installed")
class PlanCopyTest(unittest.TestCase):
    """The planner is drawn from the plan kept at the last visit and takes the server's quietly:
    planner.js's own load, save and copy code under Node. A copy is read, never changed."""

    def test_the_plan_is_kept_as_the_server_has_it(self):
        out = plan_copy("""
store['day:' + T] = {blocks: [LAB]};
await load(T);
out.loaded = [JSON.parse(keptPlan.text), keptPlan.writes];
// A change that went through is kept too; one that did not leaves what the server has.
record('renamed', T, 'block:blockaaaa1', () => editDay(T, v => { v.blocks[0].title = 'Lab report'; }));
await idle();
out.saved = JSON.parse(keptPlan.text).plan.days[T].blocks[0].title;
refuse = true;
record('renamed', T, 'block:blockaaaa1', () => editDay(T, v => { v.blocks[0].title = 'Never saved'; }));
await idle();
refuse = false;
out.refused = JSON.parse(keptPlan.text).plan.days[T].blocks[0].title;
// Dates that do not hold today are no use to the next visit: the copy stays as it was.
const far = addDays(T, 30), n = keptPlan.writes;
shown = far; await load(far);
out.far = [keptPlan.writes - n, JSON.parse(keptPlan.text).from];
""")
        kept, writes = out["loaded"]
        today = date.today()
        self.assertEqual(writes, 1)
        self.assertEqual([kept["from"], kept["to"]], [date.fromordinal(today.toordinal() - 7).isoformat(), date.fromordinal(today.toordinal() + 7).isoformat()])
        self.assertEqual(kept["plan"]["settings"], {"day_start": 5, "day_end": 24})
        self.assertEqual(sorted(kept["plan"]["week"]), ["fri", "mon", "sat", "sun", "thu", "tue", "wed"])
        self.assertEqual(kept["plan"]["days"], {today.isoformat(): {"blocks": [{"id": "blockaaaa1", "type": "deep", "title": "Lab", "start": "09:00", "end": "10:00", "items": []}]}})
        self.assertEqual([out["saved"], out["refused"]], ["Lab report", "Lab report"])
        self.assertEqual(out["far"], [0, kept["from"]])

    def test_a_copy_is_drawn_at_once_and_the_same_answer_draws_nothing(self):
        out = plan_copy("""
store['day:' + T] = {blocks: [LAB]};
keptPlan.text = copyOf([LAB]);
let free; gate = new Promise(r => { free = r; });
showKept(); const loading = load(shown);
out.shown = {...state(), timers: timers.filter(t => t.on).map(t => t.ms)};
// + Block pressed, and Plan it waiting, while the copy shows.
let pressed = 0; afterCopy(() => { pressed++; });
const waited = loadedPlan().then(() => 'loaded');
out.pressedEarly = pressed;
free(); await loading; await idle();
out.answered = {...state(), pressed, waited: await waited, timers: timers.filter(t => t.on).length, keptAgain: keptPlan.writes};
afterCopy(() => { pressed++; });
out.pressedLater = pressed;
""")
        # Drawn before the answer, not editable; it looks like the plan for 1.2 s.
        self.assertEqual(out["shown"], {"plan": True, "copied": True, "waiting": False, "editable": False, "planner": "on", "renders": 1, "unlocks": 0,
                                        "today": ["Lab"], "failed": False, "timers": [1200]})
        self.assertEqual(out["pressedEarly"], 0)
        # The server has the same: not drawn again, only made editable; what was pressed is done.
        self.assertEqual(out["answered"], {"plan": True, "copied": False, "waiting": False, "editable": True, "planner": "on", "renders": 1, "unlocks": 1,
                                           "today": ["Lab"], "failed": False, "pressed": 1, "waited": "loaded", "timers": 0, "keptAgain": 1})
        self.assertEqual(out["pressedLater"], 2)

    def test_a_different_answer_takes_the_copys_place(self):
        out = plan_copy("""
store['day:' + T] = {blocks: [LAB, GYM]};
keptPlan.text = copyOf([LAB]);
showKept();
out.shown = entriesOn(T);
await load(shown);
out.answered = state();
out.kept = JSON.parse(keptPlan.text).plan.days[T].blocks.map(b => b.title);
""")
        self.assertEqual(out["shown"], ["Lab"])
        self.assertEqual(out["answered"], {"plan": True, "copied": False, "waiting": False, "editable": True, "planner": "on", "renders": 2, "unlocks": 0,
                                           "today": ["Lab", "Gym"], "failed": False})
        self.assertEqual(out["kept"], ["Lab", "Gym"])

    def test_a_slow_answer_shows_the_copy_is_waiting(self):
        out = plan_copy("""
store['day:' + T] = {blocks: [LAB]};
keptPlan.text = copyOf([LAB]);
let free; gate = new Promise(r => { free = r; });
showKept(); const loading = load(shown);
timers[0].fn();                                 // 1.2 s on
out.slow = state();
free(); await loading; await idle();
out.answered = state();
timers[0].fn();                                 // (the timer itself changes nothing once the plan is here)
out.after = state();
""")
        self.assertEqual([out["slow"]["waiting"], out["slow"]["copied"], out["slow"]["editable"], out["slow"]["renders"]], [True, True, False, 2])
        self.assertEqual([out["answered"]["waiting"], out["answered"]["editable"], out["answered"]["unlocks"]], [False, True, 1])
        self.assertEqual(out["after"], out["answered"])

    def test_yesterdays_copy_shows_today_never_yesterday(self):
        out = plan_copy("""
store['day:' + T] = {blocks: [GYM]};
// Kept yesterday, around yesterday, with a block on yesterday and nothing yet for today.
keptPlan.text = copyOf([LAB], {from: addDays(Y, -7), to: addDays(Y, 7), day: Y});
let free; gate = new Promise(r => { free = r; });
showKept(); const loading = load(shown);
out.shown = {date: shown === T, today: entriesOn(T), yesterday: entriesOn(Y), copied};
free(); await loading;
out.answered = {today: entriesOn(T), renders, unlocks, range: [loaded.from === addDays(T, -7), loaded.to === addDays(T, 7)]};
""")
        self.assertEqual(out["shown"], {"date": True, "today": [], "yesterday": ["Lab"], "copied": True})
        self.assertEqual(out["answered"], {"today": ["Gym"], "renders": 2, "unlocks": 0, "range": [True, True]})

    def test_a_copy_that_does_not_hold_today_or_is_not_a_plan_is_not_drawn(self):
        out = plan_copy("""
const tries = {
  past: copyOf([LAB], {from: addDays(T, -20), to: addDays(T, -1)}), ahead: copyOf([LAB], {from: addDays(T, 1), to: addDays(T, 15)}),
  noDates: JSON.stringify({plan: JSON.parse(copyOf([LAB])).plan}), oddDates: copyOf([LAB], {from: 'last week', to: 'next week'}), numbers: copyOf([LAB], {from: 0, to: 99999999}),
  noPlan: JSON.stringify({from: addDays(T, -7), to: addDays(T, 7)}), planList: JSON.stringify({from: addDays(T, -7), to: addDays(T, 7), plan: []}),
  notJson: '{"from":', nothing: null, list: '[1,2]',
};
for (const [name, text] of Object.entries(tries)) { keptPlan.text = text; showKept(); out[name] = [!!plan, copied, planner, renders, timers.length]; }
// One whose days cannot be read is dropped, and the planner starts as without it.
keptPlan.text = JSON.stringify({from: addDays(T, -7), to: addDays(T, 7), plan: {days: {[T]: {blocks: 'none'}}}});
showKept();
out.unreadable = [!!plan, copied, planner, keptPlan.text, keptPlan.drops];
// A good one is drawn; a second call changes nothing.
keptPlan.text = copyOf([LAB]); showKept(); showKept();
out.good = [!!plan, copied, planner, renders, timers.length];
""")
        for name in ("past", "ahead", "noDates", "oddDates", "numbers", "noPlan", "planList", "notJson", "nothing", "list"):
            self.assertEqual(out[name], [False, False, "unknown", 0, 0], name)
        self.assertEqual(out["unreadable"], [False, False, "unknown", None, 1])
        self.assertEqual(out["good"], [True, True, "on", 1, 1])

    def test_no_answer_takes_the_copy_off_the_page(self):
        out = plan_copy("""
keptPlan.text = copyOf([LAB]);
down = true;
showKept();
let pressed = 0; afterCopy(() => { pressed++; });
const waited = loadedPlan().then(() => 'over');
await load(shown);
out.down = {...state(), pressed, waited: await waited, kept: !!keptPlan.text};
""")
        # "Couldn't load the plan. Try again", as without a copy; the copy itself stays for a later visit.
        self.assertEqual(out["down"], {"plan": False, "copied": False, "waiting": False, "editable": False, "planner": "on", "renders": 2, "unlocks": 0,
                                       "today": None, "failed": True, "pressed": 0, "waited": "over", "kept": True})
        out = plan_copy("keptPlan.text = copyOf([LAB]); missing = true; showKept(); await load(shown); out.missing = state();")
        self.assertEqual([out["missing"]["plan"], out["missing"]["copied"], out["missing"]["planner"]], [False, False, "off"])

    def test_a_page_that_turned_out_not_to_save_keeps_the_planner_off(self):
        # dashboard.js drew from its copy, the server did not answer, and it took the planner away:
        # the plan's own answer, or the lack of one, does not bring it back.
        for server in ("", "down = true;"):
            with self.subTest(server=server or "answers"):
                out = plan_copy("keptPlan.text = copyOf([LAB]); let free; gate = new Promise(r => { free = r; }); showKept(); const loading = load(shown);"
                                + "saves = null; planner = 'off'; const n = renders;" + server + "free(); await loading; out.end = [planner, renders - n, unlocks, keptPlan.writes];")
                self.assertEqual(out["end"], ["off", 0, 0, 0])

    def test_nothing_is_saved_from_a_copy(self):
        self.assertIn("const editable = () => !!plan && inRange(shown) && !copied;", PLANNER)
        # Every way to change the plan from the page asks editable() first (or is one of the forms,
        # which open only when it is): the planner's handlers that reach record().
        section = PLANNER[PLANNER.index(PLAN_COPY_START):]
        self.assertGreaterEqual(section.count("editable()"), 12)
        for guard in ("if (drag || !editable() || (e.pointerType === 'mouse' && e.button !== 0)) return;", "if (!hasItem(e) || !editable()) return;",
                      "if (back && editable()) {", "if (again && editable()) {", "if (!editable() || !F.blockDialog) return;", "if (!editable() || !F.weekDialog) return;",
                      "if (!box || !det || !editable()) return;", "if (!editable()) return SH.toast(\"Couldn't load the plan\");"):
            self.assertIn(guard, section)
        # The card's own buttons are off while nothing can be changed.
        self.assertIn('data-pd-edit="1"${can ? \'\' : \' disabled\'}', PLANNER)
        self.assertIn('data-pd-del="1"${can ? \'\' : \' disabled\'}', PLANNER)
        # Plan it waits for the plan itself.
        self.assertRegex(PLANNER, r"while \(pending\) await chain;\n    await loadedPlan\(\);\n    if \(!plan\) return SH\.toast\(\"Couldn't load the plan\"\);")
