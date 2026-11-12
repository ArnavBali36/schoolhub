// SchoolHub's dashboard. Loaded by dashboard.html, from a file rather than inline so the page runs
// under a Content-Security-Policy of script-src 'self'. data.js (the last sync) is asked for by the
// page too, without waiting for it: when it is here first the page starts from it, and otherwise
// from the copy kept from the last visit ("kept for the next visit", "starting"). The app bar
// (theme, app switch, the O key) is bar.js's, drawn before the first paint, and the day planner is
// planner.js's, loaded after this file (it uses window.SchoolHub, at the end).
//
// Every request to SchoolHub's own server uses a relative URL (api/marks, file?p=…), so the page
// works at http://localhost:8722/ and under a path prefix such as /school/ on a platform that
// forwards to it. Only the phone site's cloud API (/api/state/) is absolute.
let D = window.SCHOOL_DATA || null;                // the last sync: data.js, or until it comes the copy kept of it ("starting")
const $ = s => document.querySelector(s);
let LIVE = false;                                   // true once server.py answers: file opening, Sync now
// Reached from another device through a platform (platform.json says "remote": true): files and
// folders never open on the Mac's screen from here. Set together with LIVE.
let REMOTE = false;
// A public copy of a platform on the internet (platform.json says "public": true): it saves marks and
// tasks but has none of your files and runs no syncs. Like REMOTE, with files by name only (as on the
// phone site) and no Sync now: LIVE stays false.
let PUBLIC = false;
let WRITE = null;                                   // where ✓ marks and tasks save: 'local' (your Mac) or 'cloud' (phone site)
// Still asking where the page is (platform.json and api/marks, below): no read-only banner yet, so a
// slow first answer does not show one on a page that can save.
let PROBING = false;
// publish.py marks the phone site's page; only there is the first path segment its secret.
const PHONE = document.querySelector('meta[name="schoolhub-site"]')?.content === 'phone';
const SITE_KEY = PHONE ? location.pathname.split('/').filter(Boolean)[0] || '' : '';
const LOCAL_FILES = location.protocol === 'file:';  // opened straight off disk: file:// links work
const UNDO_MS = 6000;
const COURSE_COLORS = 10;                           // --course-1 … --course-10 in dashboard.html
const mem = {
  get(k, d){ try { const v = localStorage.getItem('sh:' + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v){ try { localStorage.setItem('sh:' + k, JSON.stringify(v)); } catch {} },
};

// ---- kept for the next visit ----
// What the server last answered is kept in this browser (localStorage), so the next visit draws the
// page at once and asks quietly, where a load used to wait for each answer in turn: the last sync's
// data ('data', what data.js holds), the marks and tasks with where the page saves ('state'), and
// the planner's days ('plan', planner.js). A copy is only ever shown. Nothing is saved from one: a
// change made while one shows waits for the server's own answer (sending, below), and that answer
// takes the copy's place, on the page too where it differs. One copy per place: the kind of site
// (the phone site or a server) and the page's path. Each carries the time it was kept: older than
// KEPT_DAYS, longer than KEPT_MAX or not what it should hold, it is not used. Where the browser
// keeps nothing (a private window, a full disk) the page loads as it did before there were copies.
const KEPT = 'sh:kept:1:';                         // 1: the form of the copies. Another form, another number, and these are never read.
const KEPT_DAYS = 3;
const KEPT_MAX = {data: 1500000, state: 200000, plan: 200000};   // characters
const keptKey = what => `${KEPT}${what}:${PHONE ? 'phone' : 'server'}:${location.pathname}`;
const kept = {
  // A copy as kept: {at, text} (text is JSON), or null. Never from a file on disk.
  get(what){
    if (LOCAL_FILES) return null;
    try {
      const v = localStorage.getItem(keptKey(what)), cut = v ? v.indexOf('\n') : -1;
      const at = cut > 0 ? Number(v.slice(0, cut)) : NaN, age = Date.now() - at;
      return age >= 0 && age < KEPT_DAYS * 864e5 ? {at, text: v.slice(cut + 1)} : null;
    } catch { return null; }
  },
  read(what){ try { return JSON.parse(this.get(what)?.text ?? null); } catch { return null; } },
  // Keeps text, and answers whether it did. Too long, or refused by the browser, the copy before it
  // goes too, so an older one is never taken for the last.
  write(what, text){
    if (LOCAL_FILES) return false;
    try {
      if (typeof text !== 'string' || text.length > KEPT_MAX[what]) throw new Error('not kept');
      localStorage.setItem(keptKey(what), Date.now() + '\n' + text);
      return true;
    } catch { this.drop(what); return false; }
  },
  drop(what){ try { localStorage.removeItem(keptKey(what)); } catch {} },
  // Copies no visit will read again go: those of another form, and those past their time.
  tidy(){
    try {
      for (let i = localStorage.length - 1; i >= 0; i--) {
        const k = localStorage.key(i);
        if (!k?.startsWith('sh:kept:')) continue;
        const age = k.startsWith(KEPT) ? Date.now() - parseInt(localStorage.getItem(k), 10) : NaN;
        if (!(age >= 0 && age < KEPT_DAYS * 864e5)) localStorage.removeItem(k);
      }
    } catch {}
  },
};
const isMap = v => !!v && typeof v === 'object' && !Array.isArray(v);
// The last sync's data as the page needs it: courses, each with its assignments.
const dataShaped = d => isMap(d) && Array.isArray(d.courses)
  && d.courses.every(c => isMap(c) && typeof c.id === 'string' && Array.isArray(c.assignments) && c.assignments.every(a => isMap(a) && typeof a.id === 'string'));
// The marks and tasks kept from the last visit, with where the page saved then (at; none on the
// phone site, which saves in one place), or null.
function keptState(){
  const c = kept.read('state');
  return isMap(c) && isMap(c.marks) && Object.values(c.marks).every(m => isMap(m) && typeof m.marked_at === 'string')
    && isMap(c.tasks) && Object.entries(c.tasks).every(([id, t]) => isMap(t) && t.id === id && typeof t.name === 'string')
    && (PHONE || (isMap(c.at) && typeof c.at.remote === 'boolean' && typeof c.at.public === 'boolean')) ? c : null;
}
// The marks and the tasks as the server last gave them, each whole. Every answer that holds all of
// one, a read or a save, is noted here (heard) and kept for the next visit: the server's own
// answers, never what the page shows, which may hold a ✓ not saved yet. Kept only once the server
// itself has said where the page saves (placed, "starting"), never on the word of a copy.
const server = {marks: null, tasks: null};
let placed = false;
function keepState(){
  if (!placed || !server.marks || !server.tasks) return;
  kept.write('state', JSON.stringify({at: PHONE ? null : {remote: REMOTE, public: PUBLIC}, marks: server.marks, tasks: server.tasks}));
}
function heard(path, r){
  const got = path === 'cloud' ? r : path === 'api/marks' || path === 'api/mark' ? {marks: r}
    : path === 'api/tasks' || path === 'api/task' || path === 'api/task/delete' ? {tasks: r?.tasks} : null;
  if (isMap(got?.marks)) server.marks = got.marks;
  if (isMap(got?.tasks)) server.tasks = got.tasks;
  if (isMap(got?.marks) || isMap(got?.tasks)) keepState();
  return r;
}
// ---- end of kept for the next visit ----

const VIEWS = ['upcoming', 'courses', 'day'];
const state = { view: VIEWS.includes(mem.get('view', 'upcoming')) ? mem.get('view', 'upcoming') : 'upcoming', showDone: mem.get('showDone', false), course: mem.get('course', null) };
const now = new Date();
// From 1100 px the planner has a column of its own beside the list; narrower, it is the Day view.
const WIDE = matchMedia('(min-width: 1100px)');
// Whether the page has the planner: 'unknown' until planner.js knows (it asks api/plan once the
// page knows where it saves), then 'on' or 'off'. Never on the phone site or from disk.
let plannerState = PHONE || LOCAL_FILES ? 'off' : 'unknown';
// Day only where it is offered: a remembered Day shows Upcoming beside the planner's own column,
// and wherever there is no planner.
const shownView = () => state.view === 'day' && (WIDE.matches || plannerState === 'off') ? 'upcoming' : state.view;

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const typingIn = el => !!el && (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable);

// The app switch's own option, clicked: back to the top of the dashboard without a page load
// (QuantPrep's goes to Today). A middle click or Cmd-click still opens it in a new tab.
$('#brand').addEventListener('click', e => {
  if (!e.target.closest('a[aria-current]') || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  if (D) closeDrawer();
  window.scrollTo(0, 0);
});

// ---- the dashboard ----
const num = n => n == null ? '' : (Math.round(n * 100) / 100).toString();
const size = b => b > 1e6 ? (b / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1e3)) + ' KB';
const sod = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const dayDiff = d => Math.round((sod(d) - sod(now)) / 864e5);
// ---- asking and saving ----
// Nothing is sent to be saved before the server itself has said where the page saves (known,
// settled in "starting"). A page drawn from the copy kept from the last visit shows its ✓ buttons
// at once, and a change made in that moment waits here: then it goes as it would have, or fails as
// any save does when the server turns out not to answer. While it waits its toast says so (UNSENT).
//
// With one exception: the page put away before that answer (leaving: the tab hidden or closed,
// the phone locked, another page opened). A change still waiting then would be lost with the page,
// after it had shown as made. So what waits is sent at that moment, to where the copy says the
// page saves, in a request that outlives the page (keepalive). The server takes it or refuses it
// as it would any save, and where there turns out to be none it fails as any save does.
let nowKnown, nowLeaving;
const known = new Promise(done => { nowKnown = done; });
const leaving = new Promise(done => { nowLeaving = done; });
let answered = false;      // the server has said where the page saves (or has not answered)
let held = true;           // until then, and until the page is put away, saves wait
known.then(() => { answered = true; });
const UNSENT = ' · waiting to save';
Promise.race([known, leaving]).then(() => { held = false; $('#toast')?.querySelector('.unsent')?.remove(); });
// It answers whether the save leaves early: before the server's own answer.
const sending = to => Promise.race([known, leaving]).then(() => { if (WRITE !== to) throw new Error('nowhere to save'); return !answered; });
document.addEventListener('visibilitychange', () => { if (document.hidden) nowLeaving(); });
window.addEventListener('pagehide', () => nowLeaving());
const answer = r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); };
// Counts every save of a mark or a task as it is sent and as it is answered: marks and tasks read
// before either moment may be older than the save's own answer, which holds them all, and are not
// taken (reloadState).
let saves = 0;
const saved = (path, sent) => {
  if (!/^(api\/(mark|task)|cloud)\b/.test(path)) return sent;
  saves++;
  return sent.finally(() => { saves++; });
};
const api = (path, body) => sending('local').then(early => saved(path, fetch(path, {
  method: 'POST', headers: {'Content-Type': 'application/json', 'X-SchoolHub': '1'}, body: JSON.stringify(body), keepalive: early,
}))).then(answer).then(r => heard(path, r));
const getJson = path => fetch(path).then(answer).then(r => heard(path, r));
const cloudApi = body => {
  const ask = early => fetch('/api/state/', {
    method: body ? 'POST' : 'GET',
    headers: {'Content-Type': 'application/json', 'X-SchoolHub-Key': SITE_KEY},
    body: body ? JSON.stringify(body) : undefined,
    keepalive: !!early,
  });
  return (body ? sending('cloud').then(early => saved('cloud', ask(early))) : ask()).then(answer).then(r => heard('cloud', r));
};
// Two saves of one thing (a ✓ and its taking back, a task saved twice) go in the order they were
// made, the second once the first is answered. Sent together, as two that waited for the server's
// first answer would be, either could arrive last, and the last to arrive is what stays. Only a
// page being put away sends them at once (leaving): the second could not wait for an answer the
// page will not be there to hear.
const turns = {};
function inTurn(id, send){
  if (!id) return send();
  const mine = turns[id] = Promise.race([turns[id], leaving]).then(send, send);
  const done = () => { if (turns[id] === mine) delete turns[id]; };
  mine.then(done, done);
  return mine;
}
// ---- end of asking and saving ----
// Same calls whether saving through your Mac's server or the phone site's cloud database.
const backend = {
  // as: a mark an undo puts back as it was, with its own time and names (a server that does not take
  // the time gives it the time of the undo).
  async mark(id, done, a, as){
    const body = {id, done, name: as?.name ?? a?.name, course: as?.course ?? a?.course?.short};
    if (done && as?.marked_at) body.marked_at = as.marked_at;
    return inTurn(id, async () => WRITE === 'cloud' ? (await cloudApi({action: 'mark', ...body})).marks : api('api/mark', body));
  },
  saveTask: body => inTurn(body.id, () => WRITE === 'cloud' ? cloudApi({action: 'task', ...body}) : api('api/task', body)),
  deleteTask: id => inTurn(id, () => WRITE === 'cloud' ? cloudApi({action: 'deleteTask', id}) : api('api/task/delete', {id})),
  // What is stored now: an undo asks before it changes anything (see "undo and redo").
  marks: async () => WRITE === 'cloud' ? (await cloudApi()).marks : getJson('api/marks'),
  tasks: async () => WRITE === 'cloud' ? (await cloudApi()).tasks : (await getJson('api/tasks')).tasks,
};

// ---- files and folders ----
// Through the local server when live. On the Mac, PDFs, pictures and text open in a tab, everything
// else in its Mac app (api/open), and folders in Finder. From another device (REMOTE) nothing opens
// on the Mac's screen: what the browser shows opens in a tab, anything else downloads, and a folder
// is only named ("On your Mac: …"). Opened from disk, file:// links; on the phone site, names only,
// and on a public copy (PUBLIC) names only, with folders named as from another device.
const VIEWABLE = /\.(pdf|png|jpe?g|gif|svg|txt|md)$/i;
// Through the server the file's name sits in the path too (file/<name>?p=…), so a PDF's tab is
// titled with it; the server only reads p. A backslash, which a forwarding server may refuse in a
// path, is left out of that name.
const baseName = p => p.split('/').pop().replace(/\\/g, '_') || 'file';
const fileUrl = p => LIVE
  ? 'file/' + encodeURIComponent(baseName(p)) + '?p=' + encodeURIComponent(p)
  : 'file://' + p.split('/').map(encodeURIComponent).join('/');
const openOnMac = p => `href="#" data-open="${esc(p)}"`;
// A file saved to the device the page is on, marked so (a small ↓ and a tooltip) before the tap.
const downloads = p => `href="${fileUrl(p)}" download="${esc(baseName(p))}" class="dl" title="Downloads to this device"`;
function fileAttrs(p){
  if (LIVE) {
    if (VIEWABLE.test(p)) return `href="${fileUrl(p)}" target="_blank"`;
    return REMOTE ? downloads(p) : openOnMac(p);
  }
  if (LOCAL_FILES) return `href="${fileUrl(p)}"`;
  return null;  // read-only view: the file only exists on your Mac
}
const folderAttrs = p => LIVE ? (REMOTE ? null : openOnMac(p)) : LOCAL_FILES ? `href="${fileUrl(p)}"` : null;
// A course's saved instructions page (Instructions.html): opened in the Mac's browser, or from disk.
// From another device the drawer's own copy of the instructions is the one to read.
const instructionsAttrs = p => LIVE ? (REMOTE ? null : openOnMac(p)) : LOCAL_FILES ? `href="${fileUrl(p)}"` : null;
const onMac = p => 'On your Mac: ' + p.replace(/^\/Users\/[^/]+(?=\/|$)/, '~');
const linked = (inner, path) => {
  const attrs = fileAttrs(path);
  return attrs ? `<a ${attrs}>${inner}</a>` : `<span class="offsite" title="On your Mac: ${esc(path)}">${inner}</span>`;
};
// A folder: Open folder where it can open, its place on the Mac as plain text from another device.
function folderLink(p, cls){
  const attrs = folderAttrs(p);
  if (attrs) return `<a${cls ? ` class="${cls}"` : ''} ${attrs}>Open folder</a>`;
  return REMOTE ? `<span class="where">${esc(onMac(p))}</span>` : '';
}
// Where platform.json's answer says the page is: reached from another device (remote), or a public
// copy of the platform (public, which is remote too). SchoolHub's own server answers 204 (no platform:
// this Mac). Any other answer, or one that cannot be read, counts as another device, so the page then
// offers only what works from anywhere.
async function platformMode(r){
  if (r.status !== 200) return {remote: r.status !== 204 && r.status !== 404, public: false};
  const p = await r.json(), isPublic = p?.public === true;
  return {remote: p?.remote === true || isPublic, public: isPublic};
}
// ---- end of files and folders ----
function siteName(url){
  if (!url) return '';
  if (url.includes('gradescope')) return 'Gradescope';
  if (url.includes('autolab')) return 'Autolab';
  if (url.includes('instructure') || url.includes('canvas')) return 'Canvas';
  return 'course site';
}

function fmtDue(iso, long, allDay){
  if (!iso) return 'No due date';
  const d = new Date(iso), days = dayDiff(d);
  const t = allDay ? '' : d.toLocaleTimeString([], {hour:'numeric', minute:'2-digit'});
  if (long) return d.toLocaleDateString([], {weekday:'long', month:'short', day:'numeric'}) + (t ? ', ' + t : '');
  if (days === 0) return ('Today ' + t).trim();
  if (days === 1) return ('Tomorrow ' + t).trim();
  if (days === -1) return ('Yesterday ' + t).trim();
  if (days > 1 && days <= 7) return (d.toLocaleDateString([], {weekday:'short'}) + ' ' + t).trim();
  return d.toLocaleDateString([], {month:'short', day:'numeric', year: d.getFullYear() !== now.getFullYear() ? 'numeric' : undefined});
}
function ago(iso){
  const h = (Date.now() - new Date(iso)) / 36e5;
  return h < 1 ? Math.max(1, Math.round(h * 60)) + ' min ago' : h < 48 ? Math.round(h) + 'h ago' : Math.round(h / 24) + 'd ago';
}

// Your own tasks, live from server.py. null means use the copy the last sync baked into data.js.
let tasks = null;
// Whether a task stays at the top: its own choice, or, for one saved before the choice existed,
// having no date (as all undated tasks were then).
const pinnedTask = t => typeof t.pinned === 'boolean' ? t.pinned : !t.due_at;
let courses = [], all = [], byId = {};
function taskItem(t){
  const due = t.due_at ? new Date(t.due_at) : null;
  return {id: t.id, name: t.name, due_at: t.due_at, all_day: !!t.all_day, points: null,
    status: due && due < now ? 'overdue' : 'todo', score: null, grade: null, submitted_at: null, late: false,
    platform: 'My task', verifiable: false, url: null, folder: null, files: [], submitted_files: [],
    description_html: '', comments: [], notes: t.notes || '', is_task: true, course_id: t.course_id || 'personal',
    created_at: t.created_at || '', pinned: pinnedTask(t)};
}
// A course's dot: the color set for it in config.json if any, else one of the theme's course colors.
// The theme's own is kept too (slot): Night's red uses it in place of a set color, which may be blue.
const courseSlot = (c, i) => c.id === 'personal' ? 'var(--course-personal)' : `var(--course-${i % COURSE_COLORS + 1})`;
const courseColor = (c, i) => c.id === 'personal' ? courseSlot(c) : c.color || courseSlot(c, i);
function rebuild(){
  let base = D.courses;
  if (tasks) base = base.filter(c => c.id !== 'personal').map(c => ({...c, assignments: c.assignments.filter(a => !a.is_task)}));
  courses = base.map((c, i) => ({...c, color: courseColor(c, i), slot: courseSlot(c, i), assignments: [...c.assignments]}));
  if (tasks) {
    const personal = {id: 'personal', source: 'personal', name: 'Personal tasks', short: 'Personal', color: courseColor({id: 'personal'}), slot: courseSlot({id: 'personal'}),
                      assignments: [], materials: []};
    // In the order they were made, wherever the store keeps them: a task an undo puts back is stored
    // last, and still shows where it was.
    const made = t => Date.parse(t.created_at) || 0;
    for (const t of Object.values(tasks).sort((x, y) => made(x) - made(y))) (courses.find(c => c.id === t.course_id) || personal).assignments.push(taskItem(t));
    if (personal.assignments.length) courses.push(personal);
  }
  all = courses.flatMap(c => c.assignments.map(a => ({...a, course: c})));
  byId = Object.fromEntries(all.map(a => [a.id, a]));
}
const dot = c => `<i class="dot" style="--dot:${esc(c.color)};--dot-theme:${esc(c.slot || c.color)}"></i>`;

// Marks as of the last sync (syncedMarks, once its data is here); replaced by the live copy from
// server.py when available.
const syncedMarks = () => Object.fromEntries(all.filter(a => a.marked_done).map(a => [a.id, {marked_at: a.marked_done}]));
let marks = {};

const SOURCE_DONE = ['submitted','graded','excused'];
const past = a => a.due_at && new Date(a.due_at) < now;
function eff(a){
  const m = marks[a.id];
  if (m && !SOURCE_DONE.includes(a.status)) {
    // The last sync's check of a mark only applies if it saw this exact mark.
    return a.marked_done === m.marked_at && a.mark_check === 'not_found' ? 'flagged' : 'marked';
  }
  if (a.status === 'todo' && a.due_at && new Date(a.due_at) - now < 48 * 36e5) return 'soon';
  return a.status;
}
// Your ✓ is your word: a mark the last sync could not confirm ('flagged') still counts as done,
// with a note on the item, rather than sitting in Needs attention. A check-in or a paper hand-in
// leaves nothing on Canvas to find.
const isDone = a => { const s = eff(a); return [...SOURCE_DONE, 'expired', 'marked', 'flagged'].includes(s) || (s === 'offline' && (!a.due_at || past(a))); };
const needsAttention = a => ['missing','overdue','check'].includes(eff(a));
const canMark = a => WRITE && !SOURCE_DONE.includes(a.status);

function pillText(a, s){
  if (s === 'graded' && a.score != null) return num(a.score) + (a.points ? ' / ' + num(a.points) : '');
  if (s === 'graded' && a.grade) return a.grade;
  return {missing:'Missing', soon:'Due soon', todo:'To do', submitted:'Submitted', graded:'Graded', offline:'Offline',
          excused:'Excused', expired:'Old', marked:'Done ✓', flagged:'Done ✓', check:'Confirm', overdue:'Overdue'}[s];
}
const PILL_TIP = {
  flagged: 'Marked done by you. The last sync found no submission, which is fine if it was handed in another way',
  check: "SchoolHub can't see this course's submissions yet. If you turned it in, click ✓",
  marked: 'Marked done by you',
};

// An open item can be dragged onto the planner (planner.js reads the drag), with a grip on hover.
const GRIP = '<span class="grip" aria-hidden="true" title="Drag onto the planner"><svg viewBox="0 0 6 14" fill="currentColor"><circle cx="1" cy="1.5" r="1"/><circle cx="5" cy="1.5" r="1"/><circle cx="1" cy="7" r="1"/><circle cx="5" cy="7" r="1"/><circle cx="1" cy="12.5" r="1"/><circle cx="5" cy="12.5" r="1"/></svg></span>';
const draggable = a => plannerState === 'on' && !isDone(a);
function row(a){
  const s = eff(a), nf = (a.files?.length || 0), m = !!marks[a.id], drag = draggable(a);
  return `<div class="row" data-id="${esc(a.id)}"${drag ? ' draggable="true"' : ''}>${drag ? GRIP : ''}
    <span class="chip">${dot(a.course)}${esc(a.course.short || a.course.name)}</span>
    <button type="button" class="name" data-drawer="${esc(a.id)}">${esc(a.name)}${nf ? `<small>📎 ${nf}</small>` : ''}${a.late ? '<small>late</small>' : ''}${a.due_changed_from ? '<small>📅 date changed</small>' : ''}</button>
    <span class="plat">${esc(a.platform)}</span>
    <span class="due">${fmtDue(a.due_at, false, a.all_day)}</span>
    <span class="pill s-${s}" title="${esc(PILL_TIP[s] || '')}">${esc(pillText(a, s))}</span>
    ${canMark(a) ? `<button class="check ${m ? 'on' : ''}" data-mark="${esc(a.id)}" title="${m ? 'Unmark' : 'Mark as done'}" aria-label="${m ? 'Unmark' : 'Mark as done'}">✓</button>` : '<span></span>'}
  </div>`;
}

const byDue = (x, y) => (x.due_at ? new Date(x.due_at) : Infinity) - (y.due_at ? new Date(y.due_at) : Infinity);
// Your own tasks you chose to keep at the top stay there, under My tasks, by date and then in the
// order you added them; the rest go in the list by date like any other item.
const pinnedItem = a => a.is_task && pinnedTask(a);
const listOrder = (x, y) => (pinnedItem(y) - pinnedItem(x)) || byDue(x, y)
  || (pinnedItem(x) ? String(x.created_at).localeCompare(String(y.created_at)) : 0);

function visible(){
  return a => state.showDone || !isDone(a) || needsAttention(a);
}
// Show done, quietly at the end of a list: "Show 8 done" for the done items it leaves out of it,
// "Hide done" once they show. Nothing when there are none to show.
function doneToggle(items){
  const hidden = items.filter(a => isDone(a) && !needsAttention(a)).length;
  if (!state.showDone && !hidden) return '';
  return `<button type="button" class="done-toggle" id="doneToggle">${state.showDone ? 'Hide done' : `Show ${hidden} done`}</button>`;
}

function upcomingView(vis){
  const order = ['My tasks','Needs attention','Today','Tomorrow','Next 7 days','Later','No due date','Earlier'];
  const G = Object.fromEntries(order.map(k => [k, []]));
  for (const a of all.filter(vis)) {
    if (pinnedItem(a)) { G['My tasks'].push(a); continue; }
    if (needsAttention(a)) { G['Needs attention'].push(a); continue; }
    if (!a.due_at) { G['No due date'].push(a); continue; }
    const d = dayDiff(new Date(a.due_at));
    G[d < 0 ? 'Earlier' : d === 0 ? 'Today' : d === 1 ? 'Tomorrow' : d <= 7 ? 'Next 7 days' : 'Later'].push(a);
  }
  G['Needs attention'].sort((x, y) => byDue(y, x));
  G['Earlier'].sort((x, y) => byDue(y, x));
  G['My tasks'].sort(listOrder);
  for (const k of ['Today','Tomorrow','Next 7 days','Later']) G[k].sort(byDue);
  const html = order.filter(k => G[k].length).map(k =>
    `<section class="group"><h2>${k} · ${G[k].length}</h2><div class="list">${G[k].map(row).join('')}</div></section>`).join('');
  // Before a hosted copy's first sync there is nothing to be caught up on: the banner says why.
  return (html || (D.generated_at ? '<p class="empty">Nothing to show. You’re all caught up 🎉</p>' : '')) + doneToggle(all);
}

function coursesView(vis){
  const cur = courses.find(c => c.id === state.course) || courses[0];
  const left = courses.map(c => {
    const open = all.filter(a => a.course === c && !isDone(a)).length;
    return `<button type="button" data-course="${esc(c.id)}" class="${c === cur ? 'on' : ''}"${c === cur ? ' aria-current="true"' : ''}>${dot(c)}<span>${esc(c.short || c.name)}</span><span class="n">${open || ''}</span></button>`;
  }).join('');
  const list = all.filter(a => a.course === cur && vis(a)).sort(listOrder);
  const mats = (cur.materials || []).map(m => `<details class="mod"><summary>${esc(m.name)} <span class="muted">· ${m.items.length}</span></summary><ul>${
    m.items.map(it => it.path
      ? `<li>${linked(esc(it.name), it.path)} <span class="muted">${size(it.size)}</span></li>`
      : `<li><a href="${esc(it.url || '#')}" target="_blank">${esc(it.name)}</a> <span class="muted">${esc(it.type)}</span></li>`).join('')
  }</ul></details>`).join('');
  return `<div class="courses"><nav class="clist" aria-label="Courses">${left}</nav><div>
    <div class="chead"><h2>${esc(cur.name)}</h2>${cur.stale ? '<span class="note warn">Showing the last good copy (the last sync could not read it; see the issue above)</span>' : ''}
      ${cur.url ? `<a href="${esc(cur.url)}" target="_blank">Open ${siteName(cur.url)} ↗</a>` : ''}
      ${cur.folder ? folderLink(cur.folder) : ''}</div>
    ${list.length ? `<div class="list">${list.map(row).join('')}</div>` : '<p class="empty">No assignments to show.</p>'}
    ${doneToggle(all.filter(a => a.course === cur))}
    ${mats ? `<div class="sub">Course materials</div><div class="mat">${mats}</div>` : ''}
  </div></div>`;
}

function stats(){
  const open = all.filter(a => !isDone(a));
  const attention = all.filter(needsAttention).length;
  const soon = open.filter(a => eff(a) === 'soon').length;
  const week = open.filter(a => a.due_at && !past(a) && dayDiff(new Date(a.due_at)) <= 7).length;
  // The Mac app (desktop/School.swift) shows what needs you on its Dock icon: these two tiles' sum.
  try { window.webkit?.messageHandlers?.schoolhub?.postMessage({badge: attention + soon}); } catch {}
  const banner = LIVE || WRITE || PROBING ? '' : LOCAL_FILES
    ? `<div class="banner">To mark assignments done and open files in their apps, use <a href="http://localhost:8722">localhost:8722</a>.</div>`
    : `<div class="banner">Read-only view. Your files and the ✓ buttons live on your Mac; this page shows the last sync.</div>`;
  const none = D.generated_at ? '' : '<div class="banner">No assignments yet: your Mac sends them with its next sync.</div>';
  // A newer sync's data.js that could not be read ("a sync that ran by itself"): yours to load.
  const newer = unread ? '<div class="banner">New data · <button type="button" class="linkish" id="newData">Refresh</button></div>' : '';
  const errs = D.errors?.length ? `<div class="errors"><b>Last sync had ${D.errors.length} issue(s)</b><ul>${D.errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul></div>` : '';
  return banner + none + newer + errs + `<div class="stats">
    <div class="stat ${attention ? 'red' : ''}"><b>${attention}</b><span>Need attention</span></div>
    <div class="stat ${soon ? 'amber' : ''}"><b>${soon}</b><span>Due in the next 48h</span></div>
    <div class="stat"><b>${week}</b><span>Due in the next 7 days</span></div>
    <div class="stat"><b>${D.new_files?.length || 0}</b><span>New files in the last day</span></div>
  </div>`;
}

// The control with keyboard focus, as selectors that find it again once it is drawn anew: itself,
// else (it went, say an assignment just marked done) the same control on the next row, or the last.
const FOCUS_KEYS = ['data-mark', 'data-drawer', 'data-course', 'data-edit-task', 'data-delete-task', 'id'];
function focusKey(within){
  const el = document.activeElement;
  if (!el || el === document.body || !within.contains(el)) return null;
  const attr = FOCUS_KEYS.find(k => el.hasAttribute(k));
  if (!attr) return null;
  const sel = el => `[${attr}="${CSS.escape(el.getAttribute(attr))}"]`;
  const all = [...within.querySelectorAll(`[${attr}]`)], at = all.indexOf(el);
  return [sel(el), ...all.slice(at + 1).map(sel), ...all.slice(0, at).reverse().map(sel)];
}
// Nothing scrolls for it: the control is where the one before it was, in view or not, and a page
// drawn anew while you read further down (a sync's new data, another device's ✓) stays where it is.
function refocus(within, keys){
  for (const key of keys || []) {
    const el = within.querySelector(key);
    if (el) return el.focus({preventScroll: true});
  }
}

// When the data on show was synced, by its own time: said anew with each drawing, and when the page
// is asked again with nothing to draw (reloadState).
function showSynced(){
  // A public copy gives data with no sync time before the Mac's first sync has reached it.
  // (By the time it is now, not the time the page was opened: a page may stay open for days.)
  const hrs = D.generated_at ? (Date.now() - new Date(D.generated_at)) / 36e5 : Infinity;
  $('#sync').textContent = D.generated_at ? 'Synced ' + ago(D.generated_at) : 'Not synced yet';
  // Its tooltip: the time itself, and when the Mac syncs next by itself ("the next sync").
  $('#sync').title = [D.generated_at ? new Date(D.generated_at).toLocaleString() : '', noteHere()].filter(Boolean).join('\n');
  $('#sync').classList.toggle('stale', hrs > 30);
}
function render(){
  if (!D) return;   // not started: data.js has not come, and there is no copy of it ("starting")
  const view = shownView();
  document.querySelectorAll('#views button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === view)));
  // Day is offered once the planner is known to be there (or while Day is the view on show, as
  // bar.js drew it); dashboard.html's styles hide it where the planner has its own column.
  $('#views [data-view="day"]').hidden = plannerState === 'off' || (plannerState === 'unknown' && view !== 'day');
  $('.page').dataset.view = view;
  $('.page').dataset.plan = plannerState;
  showSynced();
  const vis = visible(), main = $('#main'), key = focusKey(main);
  // The page stays where it was scrolled to. WebKit (Safari, the Mac app) moves it when the rows
  // are drawn anew in place: a ✓ far down the list sent the page back to its top.
  const x = window.scrollX, y = window.scrollY;
  main.innerHTML = stats() + (view === 'courses' ? coursesView(vis) : upcomingView(vis));
  markEmoji(main);
  refocus(main, key);
  if (window.scrollY !== y || window.scrollX !== x) window.scrollTo(x, y);
  emit('render');
}

// Emoji are drawn in their own colors whatever the theme's, so Night (red from 9 PM, bar.js) would
// leave a green 📗 in an assignment's name. Each run of emoji in what the page has just drawn goes in
// a <span class="emo">, which Night sends through the same red filter as pictures (dashboard.html);
// other themes show it as it is. It runs right after each part is drawn, never by watching the page,
// so it cannot start a loop with code that redraws. Text in a form control is skipped: an input's
// value or an <option> cannot hold a span (a known limit of Night, as are the system's own menus
// and tooltips).
// Only what is drawn as a color emoji: a flag (two regional letters), a keycap (1️⃣ #️⃣), a character
// shown as emoji by default (📗, not one asking for text with U+FE0E), or a symbol asking for emoji
// with U+FE0F (❤️, not ↗ © ™ ✔, which stay text in the theme's color). Each may carry a skin tone,
// tag letters (🏴󠁧󠁢󠁥󠁮󠁧󠁿) and further emoji joined by U+200D (👨‍👩‍👧, 🏳️‍🌈).
const EMOJI_ONE = String.raw`(?:\p{Regional_Indicator}{2}|[#*0-9]\uFE0F?\u20E3|(?:\p{Emoji_Presentation}(?!\uFE0E)|\p{Extended_Pictographic}\uFE0F)(?:\p{Emoji_Modifier}|\uFE0F|\u20E3|[\u{E0020}-\u{E007E}]+\u{E007F})*(?:\u200D\p{Extended_Pictographic}(?:\p{Emoji_Modifier}|\uFE0F)*)*)`;
const EMOJI = new RegExp(`${EMOJI_ONE}+`, 'gu');
// Only for asking whether a text has any: not global, so it keeps no place between calls (a global
// regex's lastIndex, left by test(), would make matchAll below start partway in and skip emoji).
const HAS_EMOJI = new RegExp(EMOJI_ONE, 'u');
const NO_EMO = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'OPTION', 'SELECT', 'TITLE']);
function markEmoji(root){
  if (!root) return root;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const found = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const parent = n.parentElement;
    if (parent && !NO_EMO.has(parent.tagName) && !parent.closest('.emo') && HAS_EMOJI.test(n.data)) found.push(n);
  }
  for (const n of found) {
    // In a flex or grid box the text was one item; split into text and spans it would become several,
    // each with the box's gap between them. So there the pieces stay together in one plain span.
    const display = n.parentElement.isConnected ? getComputedStyle(n.parentElement).display : '';
    const holder = /flex|grid/.test(display) ? document.createElement('span') : document.createDocumentFragment();
    let last = 0;
    for (const m of n.data.matchAll(new RegExp(EMOJI))) {
      if (m.index > last) holder.append(n.data.slice(last, m.index));
      holder.append(Object.assign(document.createElement('span'), {className: 'emo', textContent: m[0]}));
      last = m.index + m[0].length;
    }
    if (last < n.data.length) holder.append(n.data.slice(last));
    n.replaceWith(holder);
  }
  return root;
}

// Instructions are written for a white page, often with colored text and highlights: shown as they
// are, black text vanishes on the dark theme and the theme's light text on a yellow highlight. So
// their colors become the theme's: colored text keeps its hue as one of the theme's text colors, a
// highlight keeps its hue as a soft fill, and black, grey and white are left to the theme.
const colorProbe = document.createElement('canvas').getContext('2d');
function hueOf(value){
  if (!colorProbe || !value) return null;
  colorProbe.fillStyle = '#010203';
  colorProbe.fillStyle = value;  // the browser reads any CSS color and gives it back as #rrggbb or rgba()
  const v = colorProbe.fillStyle;
  const hex = /^#(..)(..)(..)$/.exec(v), rgba = /^rgba\((\d+), (\d+), (\d+), ([\d.]+)\)$/.exec(v);
  const [r, g, b, alpha] = hex ? [...hex.slice(1).map(x => parseInt(x, 16)), 1] : rgba ? rgba.slice(1).map(Number) : [];
  if (r === undefined || alpha < 0.2) return null;
  const max = Math.max(r, g, b), d = max - Math.min(r, g, b);
  if (d < 40) return null;  // black, grey, white
  const h = (60 * (max === r ? (g - b) / d : max === g ? (b - r) / d + 2 : (r - g) / d + 4) + 360) % 360;
  return h < 15 || h >= 330 ? 'red' : h < 70 ? 'yellow' : h < 170 ? 'green' : 'blue';
}
function themeColors(el){
  const text = hueOf(el.style?.color || el.getAttribute('color'));
  const fill = hueOf(el.style?.backgroundColor || el.getAttribute('bgcolor'));
  el.style?.removeProperty('color');
  el.style?.removeProperty('background');
  el.style?.removeProperty('background-color');
  el.removeAttribute('color');
  el.removeAttribute('bgcolor');
  if (el.getAttribute('style')?.trim() === '') el.removeAttribute('style');
  if (fill) el.classList.add('hl-' + fill);
  if (text) el.classList.add('tc-' + text);
}

// Instructions come from course pages, so strip anything executable before showing them inline.
function safeHtml(html){
  const doc = new DOMParser().parseFromString(html, 'text/html');
  // base would re-point every relative URL on the page (on the phone site, its cloud API calls).
  doc.querySelectorAll('script,style,iframe,object,embed,form,input,button,link,meta,base,animate,set').forEach(el => el.remove());
  for (const el of doc.querySelectorAll('*')) {
    for (const attr of [...el.attributes]) {
      // Browsers ignore tabs, newlines and control characters inside a URL scheme ("java\tscript:").
      const name = attr.name.toLowerCase(), value = attr.value.replace(/[\u0000-\u0020]/g, '').toLowerCase();
      const isUrl = ['href','src','xlink:href','action'].includes(name);
      if (name.startsWith('on') || (isUrl && (value.startsWith('javascript:') || value.startsWith('data:text/html'))))
        el.removeAttribute(attr.name);
    }
    if (el.tagName === 'A') { el.target = '_blank'; el.rel = 'noopener noreferrer'; }
    themeColors(el);
  }
  return doc.body.innerHTML;
}

function fileList(title, files){
  if (!files?.length) return '';
  return `<h4>${title}</h4><div class="files">${files.map(f =>
    linked(`📄 ${esc(f.name)}<span class="sz">${size(f.size)}</span>`, f.path)).join('')}</div>`;
}

function markNote(a, s){
  const m = marks[a.id];
  if (a.is_task) return m ? `<div class="note">Done ${ago(m.marked_at)}.</div>` : '';
  if (!m) return s === 'check'
    ? `<div class="note warn">SchoolHub can't see ${esc(a.platform)} submissions for this course (no Gradescope login yet), so it can't confirm this on its own. If you turned it in, mark it done.</div>`
    : '';
  if (s === 'flagged') return `<div class="note warn">You marked this done ${ago(m.marked_at)}. ${esc(a.platform)} shows no submission, which is fine if it was handed in another way (in person, on paper, by email). If it wasn't, undo the mark and turn it in.</div>`;
  if (!a.verifiable) return `<div class="note">Marked done ${ago(m.marked_at)}. SchoolHub can't see ${esc(a.platform)} submissions, so this one is on your word.</div>`;
  if (a.marked_done === m.marked_at && a.mark_check === 'confirmed') return '<div class="note">Confirmed by the last sync.</div>';
  return `<div class="note">Marked done ${ago(m.marked_at)}. The next sync will double-check ${esc(a.platform)} for your submission.</div>`;
}

// The drawer is a modal dialog: the page behind it is inert while it is open, focus starts in it
// (on Close when it was opened from the keyboard), and goes back to the assignment it was opened
// from when it closes.
let drawerId = null, drawerOpener = null;
const BEHIND_DRAWER = ['.topbar', 'main', '#fab'];
function openDrawer(id, fromKeyboard = false){
  const a = byId[id]; if (!a) return;
  const drawer = $('#drawer'), first = drawerId === null;
  const key = first ? null : focusKey(drawer);
  // Drawn again for the same item (a mark, or newer answers from the server), it stays where it was read.
  const top = drawerId === id ? drawer.scrollTop : 0;
  if (first) drawerOpener = document.activeElement;
  drawerId = id;
  const s = eff(a), m = marks[a.id];
  const instructions = a.folder && a.description_html ? `${a.folder}/Instructions.html` : null;
  drawer.innerHTML = `<button type="button" class="close" id="close" aria-label="Close">×</button>
    <span class="chip">${dot(a.course)}${esc(a.course.name)}</span>
    <h3 id="drawerTitle">${esc(a.name)}</h3>
    <div class="meta"><span class="pill s-${s}">${esc(pillText(a, s))}</span>
      <span>${a.due_at ? (a.all_day ? 'On ' : 'Due ') + esc(fmtDue(a.due_at, true, a.all_day)) : 'No due date'}</span>
      ${a.due_changed_from ? `<span>· moved from ${esc(fmtDue(a.due_changed_from, true, a.all_day))}</span>` : ''}<span>· ${esc(a.platform)}</span>${a.points ? `<span>· ${num(a.points)} pts</span>` : ''}${a.late ? '<span>· Late</span>' : ''}</div>
    <div class="actions">
      ${canMark(a) ? `<button type="button" class="btn ${m ? '' : 'primary'}" data-mark="${esc(a.id)}">${m ? 'Unmark done' : '✓ Mark as done'}</button>` : ''}
      ${a.is_task && WRITE ? `<button type="button" class="btn" data-edit-task="${esc(a.id)}">Edit</button><button type="button" class="btn" data-delete-task="${esc(a.id)}">Delete</button>` : ''}
      ${plannerState === 'on' && !isDone(a) ? `<button type="button" class="btn" data-plan-it="${esc(a.id)}" title="Add it to the next deep work block today">Plan it</button>` : ''}
      ${a.url ? `<a class="btn" href="${esc(a.url)}" target="_blank">Open on ${siteName(a.url)} ↗</a>` : ''}
      ${a.gradescope_url ? `<a class="btn" href="${esc(a.gradescope_url)}" target="_blank">Open on Gradescope ↗</a>` : ''}
      ${a.folder && folderAttrs(a.folder) ? folderLink(a.folder, 'btn') : ''}
      ${instructions && instructionsAttrs(instructions) ? `<a class="btn" ${instructionsAttrs(instructions)}>Offline instructions</a>` : ''}
    </div>
    ${a.folder && REMOTE ? `<div class="note">${folderLink(a.folder)}</div>` : ''}
    ${markNote(a, s)}
    ${a.is_task && a.notes ? `<h4>Notes</h4><div class="comment">${esc(a.notes)}</div>` : ''}
    ${a.submitted_at ? `<h4>Submission</h4><div>Submitted ${esc(fmtDue(a.submitted_at, true))}${a.late ? ' (late)' : ''}</div>` : ''}
    ${fileList('Your submitted files', a.submitted_files)}
    ${a.comments?.length ? `<h4>Feedback</h4>${a.comments.map(c => `<div class="comment"><b>${esc(c.author)}</b> · <span class="muted">${esc(fmtDue(c.at))}</span>\n${esc(c.text)}</div>`).join('')}` : ''}
    ${fileList('Assignment files', a.files)}
    ${a.description_html ? `<h4>Instructions</h4><div class="doc">${safeHtml(a.description_html)}</div>` : ''}`;
  markEmoji(drawer);
  drawer.hidden = $('#scrim').hidden = false;
  drawer.scrollTop = top;
  $('#close').onclick = closeDrawer;
  for (const sel of BEHIND_DRAWER) { const el = $(sel); if (el) el.inert = true; }
  if (first) (fromKeyboard ? $('#close') : drawer).focus(); else refocus(drawer, key);
}
function closeDrawer(){
  if (drawerId === null) return;
  const id = drawerId;
  drawerId = null;
  $('#drawer').hidden = $('#scrim').hidden = true;
  for (const sel of BEHIND_DRAWER) { const el = $(sel); if (el) el.inert = false; }
  // Back to where it was opened from; the list may have been drawn anew meanwhile.
  const back = drawerOpener?.isConnected ? drawerOpener : document.querySelector(`[data-drawer="${CSS.escape(id)}"]`);
  drawerOpener = null;
  back?.focus?.();
}

// ---- mark as done, with undo ----
let toastTimer = null;
// action: what the toast's button does, named by label (Undo, unless said). ms: how long it stays.
// wait: it only says that something is on its way ("Undoing…"), until what came of it takes its place.
function toast(msg, action, {label = 'Undo', ms = UNDO_MS, wait = false} = {}){
  clearTimeout(toastTimer);
  $('#toast')?.remove();
  const el = document.createElement('div');
  el.className = 'toast'; el.id = 'toast'; el.setAttribute('role', 'status');
  // A button for a step of the undo history (offerStep) goes when the next change is made.
  if (action?.step) el.dataset.step = '1';
  if (wait) el.dataset.wait = '1';
  // A change made before the server's first answer has not been sent yet ("asking and saving"):
  // its toast says so, until it is.
  const unsent = held && action?.step ? `<span class="unsent">${esc(UNSENT)}</span>` : '';
  el.innerHTML = `<span>${esc(msg)}${unsent}</span>${action ? `<button type="button">${esc(label)}</button>` : ''}<i class="timer" style="animation-duration:${ms}ms"></i>`;
  markEmoji(el);
  document.body.append(el);
  if (action) el.querySelector('button').onclick = () => { clearTimeout(toastTimer); el.remove(); action(); };
  toastTimer = setTimeout(() => el.remove(), ms);
}
// as: a mark put back as it was (an undo's or a redo's), in place of one made now. It answers the
// marks as the server has them after the save, or false when it failed.
async function setMark(id, done, as){
  const a = byId[id], prev = marks[id];
  if (done) marks[id] = as ? {...as} : {marked_at: new Date().toISOString()}; else delete marks[id];
  refresh();
  try {
    const stored = marks = await backend.mark(id, done, a, as);
    refresh();
    return stored;
  } catch {
    if (prev) marks[id] = prev; else delete marks[id];
    refresh();
    toast("Couldn't save. Check your connection and try again.");
    return false;
  }
}
const unsavedMark = {};   // id → the step of a ✓ whose save has not answered yet
function toggleMark(id){
  const done = !marks[id], a = byId[id], was = marks[id] || null, before = unsavedMark[id];
  // The step and the toast's Undo are there right away (an undo asked for before the server answers
  // waits for it); setMark swaps in an error toast if the save fails, and the step goes.
  const saved = setMark(id, done);
  const step = unsavedMark[id] = addStep(markStep(done ? `marked “${a.name}” done` : `unmarked “${a.name}”`, id, was), saved.then(async stored => {
    step.now = stored && stored[id] || null;
    if (unsavedMark[id] === step) delete unsavedMark[id];
    // The ✓ clicked again before its first save answered: the mark before this step is the one that
    // save left on the server (or, if it failed, the one before it), not the page's stand-in for it.
    if (before) step.was = await before.settled ? before.now : before.was;
    return !!stored;
  }));
  toast(done ? `Marked “${a.name}” done` : `Unmarked “${a.name}”`, offerStep(step));
}
function refresh(){ render(); if (drawerId) openDrawer(drawerId); }

document.addEventListener('click', e => {
  const mk = e.target.closest('[data-mark]');
  if (mk) { e.preventDefault(); e.stopPropagation(); return toggleMark(mk.dataset.mark); }
  const et = e.target.closest('[data-edit-task]'); if (et) { e.preventDefault(); return openTaskForm(et.dataset.editTask); }
  const dt = e.target.closest('[data-delete-task]'); if (dt) { e.preventDefault(); return deleteTask(dt.dataset.deleteTask); }
  const op = e.target.closest('[data-open]');
  // Never from another device: what opens there would open on the Mac's screen.
  // (Asked again once the server has said where the page is: a link drawn from the last visit's copy.)
  if (op) { e.preventDefault(); if (REMOTE) return; return known.then(() => REMOTE || api('api/open', {path: op.dataset.open})).catch(() => toast("Couldn't open that file.")); }
  // A click the keyboard made (Enter or Space on a name) has no click count.
  const r = e.target.closest('.row'); if (r) return openDrawer(r.dataset.id, e.detail === 0);
  // (Pressed by you: the page never loads again by itself for new data.)
  if (e.target.closest('#newData')) return location.reload();
  if (e.target.closest('#doneToggle')) { state.showDone = !state.showDone; mem.set('showDone', state.showDone); return render(); }
  const c = e.target.closest('[data-course]'); if (c) { state.course = c.dataset.course; mem.set('course', state.course); render(); }
  const v = e.target.closest('#views button'); if (v) { state.view = v.dataset.view; mem.set('view', state.view); render(); }
});
$('#scrim').onclick = closeDrawer;
// A modal dialog open (a task's, or the planner's) has Escape and the keys to itself. The planner's
// details card beside a block is not modal: it leaves them to the page.
const dialogOpen = () => [...document.querySelectorAll('dialog[open]')].some(d => d.matches(':modal'));
document.addEventListener('keydown', e => {
  const typing = typingIn(document.activeElement);
  if (e.key === 'Escape' && !dialogOpen()) closeDrawer();
  if (e.key === 'n' && WRITE && !typing && !dialogOpen() && !e.metaKey && !e.ctrlKey) { e.preventDefault(); openTaskForm(); }
});
WIDE.addEventListener('change', () => render());
// ---- your own tasks ----
const taskDialog = $('#taskDialog');
let editingTask = null;
let taskForms = 0;          // counts the form's openings: a save's answer closes only the form it was pressed in
let savingTask = false;     // Save was pressed and has not been answered: pressed again, nothing more is sent
const pad = n => String(n).padStart(2, '0');
function openTaskForm(id){
  const t = id ? tasks?.[id] : null;
  editingTask = t ? t.id : null;
  taskForms++;
  $('#taskHeading').textContent = t ? 'Edit task' : 'New task';
  const preferred = t?.course_id || (state.view === 'courses' && state.course) || 'personal';
  $('#tCourse').innerHTML = [['personal', 'Personal'], ...courses.filter(c => c.id !== 'personal').map(c => [c.id, c.short || c.name])]
    .map(([value, label]) => `<option value="${esc(value)}"${value === preferred ? ' selected' : ''}>${esc(label)}</option>`).join('');
  const d = t?.due_at ? new Date(t.due_at) : null;
  $('#tName').value = t?.name || '';
  $('#tDate').value = d ? `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` : '';
  $('#tTime').value = d && !t.all_day ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : '';
  $('#tNotes').value = t?.notes || '';
  // A new task is kept at the top until you choose otherwise.
  $('#tPinned').checked = t ? pinnedTask(t) : true;
  taskDialog.showModal();
  $('#tName').focus();
}
function refreshTasks(next){
  tasks = next;
  rebuild();
  // The open drawer's task is gone (an undo took it away, or another device deleted it): it closes.
  if (drawerId !== null && !byId[drawerId]) closeDrawer();
  refresh();
}
// The marks and tasks as the server has them now (asked at the start, and on coming back to the
// tab), taken in place. A ✓ whose save is still on its way stays as the page shows it: its own
// answer follows. When nothing differs from what is on show, nothing is drawn again. It answers
// whether anything was.
function took(m, t){
  const next = {...m};
  for (const id in unsavedMark) { if (marks[id]) next[id] = marks[id]; else delete next[id]; }
  const changed = !same(marks, next) || !same(tasks, t);
  marks = next;
  if (changed) refreshTasks(t); else tasks = t;
  return changed;
}
// Save shows that it is on its way and takes no second press until it is answered (the answer may
// be a while coming: on a slow connection, and for as long as the server's first answer is awaited).
// Pressed twice it would make the task twice.
function taskSaving(on){
  savingTask = on;
  const btn = $('#taskForm button[type="submit"]');
  if (btn) { btn.disabled = on; btn.textContent = on ? 'Saving…' : 'Save'; }
}
async function saveTask(e){
  e.preventDefault();
  if (savingTask) return;
  const name = $('#tName').value.trim();
  if (!name) return $('#tName').focus();
  const date = $('#tDate').value, time = $('#tTime').value;
  const body = {name, course_id: $('#tCourse').value, notes: $('#tNotes').value,
    due_at: date ? new Date(`${date}T${time || '23:59'}`).toISOString() : null, all_day: !!date && !time,
    pinned: $('#tPinned').checked};
  // The task and the form this Save is for: the answer may come after another form was opened.
  const editing = editingTask, form = taskForms;
  if (editing) body.id = editing;
  const was = editing && tasks?.[editing] || null;
  taskSaving(true);
  try {
    const r = await backend.saveTask(body);
    if (taskForms === form) taskDialog.close();
    refreshTasks(r.tasks);
    // One step for undo, unless Save changed nothing.
    const step = sameTask(was, r.task) ? null : addStep(taskStep(was ? taskEdit(was, r.task) : `added “${name}”`, r.task.id, was, r.task));
    toast(editing ? `Saved “${name}”` : `Added “${name}”`, offerStep(step));
  } catch {
    toast("Couldn't save the task. Check your connection and try again.");
  } finally { taskSaving(false); }
}
function deleteTask(id){
  const removed = tasks?.[id];
  if (!removed) return;
  // The step is there at once, so an undo asked for before the server answers waits for the delete.
  const saved = backend.deleteTask(id).then(r => {
    if (drawerId === id) closeDrawer();
    refreshTasks(r.tasks);
    toast(`Deleted “${removed.name}”`, offerStep(step));
    return true;
  }, () => { toast("Couldn't delete the task."); return false; });
  const step = addStep(taskStep(`deleted “${removed.name}”`, id, removed, null), saved);
}
$('#taskForm').addEventListener('submit', saveTask);
$('#taskCancel').onclick = () => taskDialog.close();
taskDialog.addEventListener('click', e => { if (e.target === taskDialog) taskDialog.close(); });
$('#fab').onclick = () => openTaskForm();

// ---- undo and redo ----
// Every change you make to your marks, tasks and plan is a step here. Cmd+Z (Ctrl+Z) takes the last
// one back and Shift+Cmd+Z (Shift+Ctrl+Z, Ctrl+Y) makes it again: about a hundred steps, for as long
// as the page is open. The view and the theme are not changes to your data, so they are not steps.
//
// A step is {label, undo(), redo()}. label says what was done, as the toast names it ("moved Lunch
// to 3:00 PM"). undo and redo save through the same paths as the change itself (backend here, the
// plan's queue in planner.js) and answer {ok: true}, or {ok: false, why}:
//   'failed'    the save did not go through: nothing changed, and the step stays to try again;
//   'conflict'  what is stored is no longer what the step left (changed on another device, say), and
//               taking the step back would overwrite that: nothing changes, the step goes, and the
//               toast says so.
// Before it changes anything a step asks the server what is stored now, so it never goes by a copy
// the page has had for a while.
const UNDO_STEPS = 100;
const steps = {undo: [], redo: []};
let stepsMade = 0, travelling = Promise.resolve();
let travels = 0;    // ways back asked for and not done with yet: the one running, and those waiting behind it
const holds = [];   // while one of these answers true (a drag on the planner), the keys do nothing
// Equal as stored: the same values whatever the order of an object's keys. Nothing there is null.
function same(a, b){
  if (a == null || b == null) return a == null && b == null;
  if (typeof a !== 'object' || typeof b !== 'object') return a === b;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a)) return a.length === b.length && a.every((x, i) => same(x, b[i]));
  const keys = o => Object.keys(o).filter(k => o[k] !== undefined);
  const ka = keys(a), kb = keys(b);
  return ka.length === kb.length && ka.every(k => b[k] !== undefined && same(a[k], b[k]));
}
// A change just made, as a step. saved: a promise of whether its save went through; a change whose
// save failed was never made, so its step goes.
function addStep(step, saved = true){
  steps.undo.push(step);
  if (steps.undo.length > UNDO_STEPS) steps.undo.shift();
  steps.redo.length = 0;
  stepsMade++;
  // A toast still offering an earlier step goes: that one is no longer the next.
  const old = $('#toast');
  if (old?.dataset.step) { clearTimeout(toastTimer); old.remove(); }
  const settle = ok => {
    if (ok !== false) return true;
    for (const list of [steps.undo, steps.redo]) { const i = list.indexOf(step); if (i >= 0) list.splice(i, 1); }
    return false;
  };
  step.settled = Promise.resolve(saved).then(settle, () => settle(false));
  return step;
}
// A toast's button for a step: Undo (or Redo), for as long as that step is the next one. The button
// goes with its toast, so the step is asked to give focus a place (refocus).
function offerStep(step, dir = 'undo'){
  return step ? Object.assign(() => { if (steps[dir][steps[dir].length - 1] === step) travel(dir, {refocus: true}); }, {step: true}) : null;
}
const DID = {undo: 'Undid', redo: 'Redid'}, DOING = {undo: 'Undoing…', redo: 'Redoing…'}, BACK = {undo: 'redo', redo: 'undo'};
const WAIT_MS = 30000;      // "Undoing…" stays this long at most, should nothing ever come of it
// The toast that says a way back is on its way goes, where nothing has taken its place.
const endWait = () => { const el = $('#toast'); if (el?.dataset.wait) { clearTimeout(toastTimer); el.remove(); } };
// One step back (or forward again). They run one at a time, in the order asked. o: {refocus} from a
// toast's button.
function travel(dir, o){
  travels++;
  return travelling = travelling.then(async () => {
    try {
      const from = steps[dir], to = steps[BACK[dir]], step = from.pop(), at = from.length, toAt = to.length, made = stepsMade;
      if (!step) return toast(`Nothing to ${dir}`, null, {ms: 2000});
      // Said at once. The step waits for its own save and asks the server what is stored before it
      // changes anything, and with a slow server the page would show nothing of the request until
      // then (which invites a second press, and that one takes back an older step).
      toast(DOING[dir], null, {ms: WAIT_MS, wait: true});
      let r;
      try { r = await step.settled ? await step[dir](o) : {ok: false, why: 'gone'}; }
      catch (err) { console.error(err); r = {ok: false, why: 'failed'}; }
      // A change made while this ran is the newest step: it cleared what could be redone.
      const newest = made === stepsMade;
      if (r.ok) {
        if (dir === 'redo') to.splice(Math.min(toAt, to.length), 0, step);
        else if (newest) to.push(step);
        toast(`${DID[dir]}: ${step.label}`, newest ? offerStep(step, BACK[dir]) : null, {label: dir === 'undo' ? 'Redo' : 'Undo'});
      } else if (r.why === 'failed') {
        if (dir === 'undo' || newest) from.splice(Math.min(at, from.length), 0, step);
        toast(`Couldn't ${dir} that. Check your connection and try again.`);
      } else if (r.why === 'conflict') {
        toast(`Can't ${dir}: ${step.label}. It was changed somewhere else since.`);
      } else endWait();     // the change itself was never saved, and has said so
    } finally { travels--; }
  });
}
// Where the keys are the field's own undo while typing: text, not a checkbox or a button.
const NOT_TEXT = new Set(['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file', 'image']);
const editingText = el => !!el && (!!el.isContentEditable || el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && !NOT_TEXT.has(el.type)));
// Undo or redo, asked by the keys or by the Mac app's Edit menu (SchoolHub.undo, SchoolHub.redo).
// true: the page took it: it did it, or left it out on purpose (a form is open over the page, and
// nothing changes underneath an open form). false: typing in a field, where it is the field's own.
// Each step asks the server before it changes anything, so with a slow one requests could pile up
// and the page go on undoing for seconds after the keys were up, into steps nobody meant. So at
// most one waits behind the one that is running (MAX_TRAVELS), and the rest are left out; a key
// held down (again: the keyboard's own repeat) asks once.
const MAX_TRAVELS = 2;
function requestStep(dir, again){
  if (editingText(document.activeElement)) return false;
  if (!again && travels < MAX_TRAVELS && !document.querySelector('dialog[open] form') && !holds.some(fn => fn())) travel(dir);
  return true;
}
document.addEventListener('keydown', e => {
  if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
  const k = String(e.key).toLowerCase();
  const dir = k === 'z' ? (e.shiftKey ? 'redo' : 'undo') : k === 'y' && e.ctrlKey && !e.metaKey && !e.shiftKey ? 'redo' : '';
  if (dir && requestStep(dir, e.repeat)) e.preventDefault();
});
// Focus for a step taken back or made again from a toast's button, which went with its toast: the
// thing's own ✓ (in the open drawer first: the list behind a drawer takes no focus), else other
// (a selector), without scrolling. Never moved from where you put it meanwhile.
function focusMark(id, other){
  const sel = `[data-mark="${CSS.escape(id)}"]`;
  for (const s of ['#drawer:not([hidden]) ' + sel, sel, other]) {
    if (document.activeElement !== document.body) return;
    if (s) document.querySelector(s)?.focus({preventScroll: true});
  }
}

// A ✓ made or taken away. was: the mark before (null for none); now: the one the step left, known
// once its save has answered. A mark is stored on its own under the assignment's id, so the way
// back touches only that one: it takes away the mark the step made, or puts back the one it took
// away, with the time it had (where the server takes it), so the last sync's answer for that
// mark still applies. Only while the stored mark is still the one the step left.
function markStep(label, id, was){
  const step = {label, id, was, now: null};
  const go = async (to, from, side, o) => {
    let stored;
    try { stored = await backend.marks(); } catch { return {ok: false, why: 'failed'}; }
    marks = stored;
    if ((stored[id]?.marked_at || null) !== (from?.marked_at || null)) { refresh(); return {ok: false, why: 'conflict'}; }
    const left = await setMark(id, !!to, to);
    if (!left) return {ok: false, why: 'failed'};
    step[side] = left[id] || null;   // as the server keeps it now, for the way back
    // A toast's button went with the toast: focus goes to the assignment's ✓.
    if (o?.refocus) focusMark(id);
    return {ok: true};
  };
  step.undo = o => go(step.was, step.now, 'was', o);
  step.redo = o => go(step.now, step.was, 'now', o);
  return step;
}
// A task added, edited or deleted. was and now: the task before and after (null for none). A task
// is stored on its own under its id, so the way back touches only that one: it saves the task as
// it was under the same id (after a delete too: the server keeps the id and the time it was made,
// and the ✓ of a deleted task was never taken away), or deletes the one the step added. Only while
// the stored task is still as the step left it. The server stamps each save (updated_at), which is
// not something you set, so it is not compared.
const TASK_FIELDS = ['name', 'course_id', 'due_at', 'all_day', 'notes', 'created_at'];
const sameTask = (a, b) => !a || !b ? !a && !b : pinnedTask(a) === pinnedTask(b) && TASK_FIELDS.every(k => same(a[k], b[k]));
const taskEdit = (was, now) => sameTask({...was, pinned: pinnedTask(now)}, now)
  ? `${pinnedTask(now) ? 'pinned' : 'unpinned'} “${now.name}”` : `edited “${now.name}”`;
function taskStep(label, id, was, now){
  const step = {label, id, was, now};
  const go = async (to, from, side, o) => {
    let stored;
    try { stored = await backend.tasks(); } catch { return {ok: false, why: 'failed'}; }
    if (!sameTask(stored?.[id], from)) { refreshTasks(stored || {}); return {ok: false, why: 'conflict'}; }
    let r;
    try { r = to ? await backend.saveTask(to) : await backend.deleteTask(id); } catch { return {ok: false, why: 'failed'}; }
    refreshTasks(r.tasks);
    step[side] = to ? r.task : null;   // as the server keeps it now, for the way back
    // A toast's button went with the toast: focus goes to the task's ✓ where it is there again,
    // else to the + button, never left on <body>.
    if (o?.refocus) focusMark(id, '#fab');
    return {ok: true};
  };
  step.undo = o => go(step.was, step.now, 'was', o);
  step.redo = o => go(step.now, step.was, 'now', o);
  return step;
}
// ---- end of undo and redo ----

// ---- sync now ----
// Never on a public copy: syncs run on the Mac, which has your Canvas login.
const syncBtn = $('#syncBtn');
function showSyncing(on){
  syncBtn.disabled = on;
  syncBtn.textContent = on ? 'Syncing…' : 'Sync now';
  if (on) hideSyncNote();
}
// Sync now pressed on this page (pressed): the page waits for that sync, and when it ends takes its
// data in place, as it does for a sync that ran by itself (heardSync, below), and says how it
// went. The page is not loaded again for it: a form being filled in and the undo history stay.
let pressed = false;
// How a sync went, in a line, from api/sync's answer.
function syncSaid(s){
  const lines = (s.output || '').split('\n');
  const summary = lines.find(l => l.startsWith('[schoolhub]'))?.replace('[schoolhub] ', '') || '';
  const issues = lines.filter(l => /^(⚠️|🔎|❌)/.test(l)).length;
  return s.ok ? `Sync finished${summary ? ' · ' + summary : ''}${issues ? ` · ${issues} alert(s)` : ''}` : 'Sync failed. See state/sync.log';
}
async function pollSync(){
  let s;
  try { s = await getJson('api/sync'); } catch {
    pressed = false;
    showSyncing(false);
    watchSync();
    return toast("Couldn't reach the SchoolHub server.");
  }
  if (s.running) { showSyncing(true); return setTimeout(pollSync, 2000); }
  pressed = running = false;
  showSyncing(false);
  // The new data.js, if the sync left one (a failed one may have, too).
  try { await heardSync(s); } catch (err) { console.error(err); }
  toast(syncSaid(s));
  watchSync();
}

// The next sync. The Mac's server syncs by itself once the last good sync is over 12 hours old
// (server.py, autosync.py) and says in api/sync's answer when it will (auto). One quiet line says
// it on the page: in the tooltip of "Synced 2h ago" (showSynced), and in the page's own tooltip
// (#syncNote in dashboard.html, the surface of the planner's previews) under Sync now while the
// pointer rests on that button or the keyboard's focus is on it. The same element describes the
// button to a screen reader. No line where the server does not sync by itself (auto.state "off")
// or while a sync runs, and never on a public copy or the phone site: neither asks api/sync.
const clockTime = iso => {
  const d = iso ? new Date(iso) : null;
  return d && !isNaN(d) ? d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'}) : '';
};
function nextSyncNote(s){
  const auto = s?.auto, at = clockTime(auto?.next_at);
  if (!auto || s.running) return '';
  if (auto.state === 'waiting') return `Syncs by itself every ${auto.every_hours || 12} hours` + (at ? ` · next around ${at}` : '');
  if (auto.state === 'retrying') return "Last sync didn't finish · trying again " + (at ? `at ${at}` : 'soon');
  if (auto.state === 'settling' || auto.state === 'due') return 'Syncing in a moment';
  if (auto.state === 'offline') return 'Will sync when the network is back';
  return '';
}
const noteEl = $('#syncNote');
let syncNote = '';
// The line as it may be said here: only where your Mac's own server answers the page.
const noteHere = () => LIVE && !PUBLIC && !PHONE ? syncNote : '';
// In its element: one line of the previews' own kind, small and quiet (.ptip .pd-line).
const noteHtml = note => note ? `<div class="pd-line">${esc(note)}</div>` : '';
function setSyncNote(note){
  if (note === syncNote) return;
  syncNote = note;
  if (noteEl) noteEl.innerHTML = noteHtml(note);
  if (note) syncBtn.setAttribute('aria-describedby', 'syncNote'); else syncBtn.removeAttribute('aria-describedby');
  if (!note) hideSyncNote();
  if (D) showSynced();
}
const NOTE_REST_MS = 350;      // the pointer rests on Sync now this long before the line shows (as the planner's previews)
const NOTE_GAP = 8;            // px between the line and the button, and kept to the window's edges
let noteTimer = 0;
function showSyncNote(){
  const tip = noteEl, note = noteHere();
  clearTimeout(noteTimer);
  noteTimer = 0;
  if (!tip || !note || syncBtn.hidden || syncBtn.disabled) return;
  tip.innerHTML = noteHtml(note);
  // One line wherever the window has the width for it (a preview is no wider than 300 px).
  Object.assign(tip.style, {left: '', top: '', maxWidth: `calc(100vw - ${2 * NOTE_GAP}px)`});
  tip.hidden = false;
  // Measured at its own size, then put under the button with their right edges in line (over it
  // where there is no room under), wholly in the window.
  const b = syncBtn.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
  const vw = document.documentElement.clientWidth, vh = window.innerHeight;
  const under = b.bottom + NOTE_GAP + h <= vh - NOTE_GAP;
  tip.dataset.side = under ? 'below' : 'above';
  Object.assign(tip.style, {left: Math.round(Math.max(NOTE_GAP, Math.min(b.right - w, vw - NOTE_GAP - w))) + 'px',
    top: Math.round(under ? b.bottom + NOTE_GAP : Math.max(NOTE_GAP, b.top - NOTE_GAP - h)) + 'px'});
}
function hideSyncNote(){
  if (!noteTimer && noteEl?.hidden !== false) return;    // nothing shows or waits (every scroll asks)
  clearTimeout(noteTimer);
  noteTimer = 0;
  if (noteEl) noteEl.hidden = true;
}
syncBtn.addEventListener('pointerenter', e => {
  if (e.pointerType === 'touch') return;
  clearTimeout(noteTimer);
  noteTimer = setTimeout(showSyncNote, NOTE_REST_MS);
});
syncBtn.addEventListener('pointerleave', hideSyncNote);
// The keyboard's focus only: a click puts focus on the button too, and is not asking to read.
syncBtn.addEventListener('focus', () => { if (syncBtn.matches(':focus-visible')) showSyncNote(); });
syncBtn.addEventListener('blur', hideSyncNote);
syncBtn.addEventListener('click', hideSyncNote);
document.addEventListener('keydown', e => { if (e.key === 'Escape') hideSyncNote(); });
window.addEventListener('scroll', hideSyncNote, {passive: true});
window.addEventListener('resize', hideSyncNote);

// A sync that ran by itself. One may run while the page is open: the server's own every 12 hours,
// one started in Terminal, or Sync now pressed in another window. So where your Mac's server
// answers the page (LIVE: never a public copy, never the phone site) it asks api/sync about once a
// minute while it is on show, and when it comes back on show ("back on show"); never while it is
// hidden, when no timer runs. While a sync runs, Sync now says so. When the data on the Mac is no
// longer the data on the page (data_at is not its generated_at), data.js is asked for again and
// taken in place (takeData, as when data.js follows the copy a visit opened from): the list, the
// planner's chips and an open drawer are drawn from it, and where you had scrolled to, an open
// form and the undo history stay as they were. The page never loads again by itself for it. Only a
// data.js that cannot be read leaves the page as it is, with a quiet "New data · Refresh" above
// the list (stats) for you to press.
const WATCH_MS = 60000;           // between two looks
const WATCH_SOON_MS = 3000;       // while a sync runs (to see it end), or a drag holds new data back
let watchTimer = 0, looking = false, running = false, soon = false;
let unread = null;                // the data_at of a data.js that could not be read: "New data · Refresh"
const watches = () => LIVE && !PUBLIC && !PHONE && !pressed && !document.hidden;
// The next look, a while from now: none while the page is hidden, or where it does not watch.
function watchSync(){
  clearTimeout(watchTimer);
  watchTimer = watches() ? setTimeout(lookAtSync, running || soon ? WATCH_SOON_MS : WATCH_MS) : 0;
}
async function lookAtSync(){
  clearTimeout(watchTimer);
  watchTimer = 0;
  if (looking || !watches()) return;
  looking = true;
  let s = null;
  try { s = await getJson('api/sync'); } catch {}
  try {
    if (s) await heardSync(s);
    // No answer: Sync now is not left saying "Syncing…" for a sync nobody can see end.
    else if (running && !pressed) { running = false; showSyncing(false); }
    // "Synced 2h ago" is said for now at every look: a page left open keeps its data across syncs
    // (it is not loaded again), and the label is what says how old that data is.
    if (D) showSynced();
  } catch (err) { console.error(err); }
  looking = false;
  watchSync();
}
async function heardSync(s){
  setSyncNote(nextSyncNote(s));
  if (pressed) return;            // Sync now's own wait is on, and takes the data itself when it ends (pollSync)
  soon = false;
  if (s.running) { running = true; return showSyncing(true); }
  if (running) { running = false; showSyncing(false); }
  // Not before data.js itself has come (or failed): until then the page may show the copy kept of
  // an older sync, and data.js is on its way already. Not in the middle of a drag: soon after.
  if (!dataSeen || !D || !s.data_at || s.data_at === D.generated_at || s.data_at === unread) return;
  if (holds.some(fn => fn())) { soon = true; return; }
  await newData(s.data_at);
}
// data.js as text is one statement, `window.SCHOOL_DATA = {…};` (sync.py): what it holds, or null.
function readData(text){
  try {
    const d = JSON.parse(text.slice(text.indexOf('=') + 1).trim().replace(/;$/, ''));
    return dataShaped(d) ? d : null;
  } catch { return null; }
}
// at: the data_at that told of it.
async function newData(at){
  let text;
  try {
    const r = await fetch('data.js', {cache: 'no-store'});
    if (!r.ok) return;            // not answered: asked again at the next look
    text = await r.text();
  } catch { return; }
  const fresh = readData(text), was = D;
  if (fresh && fresh.generated_at === was.generated_at) return;
  try {
    if (!fresh) throw new Error('data.js could not be read');
    unread = null;                // (before it is drawn: an offer made for an earlier sync goes)
    takeData(fresh);
  } catch (err) {
    // Not taken: the page stays on the data it had, and offers the load.
    console.error(err);
    unread = at;
    if (D !== was) { D = was; rebuild(); }
    return refresh();
  }
  keepData(JSON.stringify(fresh));
  // The sync also checked your ✓ marks: what is stored now follows, as on coming back to the tab.
  reloadState();
}

// (The tasks are asked for with the marks, in "starting". Called again when the server's answer
// names another place than the copy the page was drawn from: Sync now comes or goes.)
function enableServerFeatures(){
  $('#fab').hidden = false;
  syncBtn.hidden = PUBLIC;
  if (PUBLIC || syncBtn.onclick) return;
  syncBtn.onclick = () => api('api/sync', {}).then(() => { pressed = true; watchSync(); showSyncing(true); setTimeout(pollSync, 1500); })
    .catch(() => toast("Couldn't start a sync. Is the SchoolHub server running?"));
  // Whether a sync is running now and when the next will; from here on, whether one ran.
  lookAtSync();
}
// ---- end of sync now ----

// Pick up changes made on your other device when you come back to this tab.
async function reloadState(tries = 3){
  try {
    const before = saves;
    let s = null;
    if (WRITE === 'cloud') s = await cloudApi();
    else if (WRITE === 'local') s = {marks: await getJson('api/marks'), tasks: (await getJson('api/tasks')).tasks};
    // A save went out or came back meanwhile: its answer is the newer one, and this one is left.
    // (Asked once or twice more: on your Mac a save's own answer holds the marks or the tasks, not both.)
    if (s && before !== saves) { if (tries > 1) return reloadState(tries - 1); }
    // Nothing changed: nothing is drawn again, but "Synced 2h ago" is said for now.
    else if (s && !took(s.marks, s.tasks)) showSynced();
  } catch {}
  emit('reload');
}

// ---- back on show ----
// Back in view (the tab, the Mac app's window or its School view): what changed meanwhile is taken
// in quietly, the marks and tasks from your other devices (reloadState; the planner follows it)
// and a sync that ran (lookAtSync, "sync now"). The same when the browser brings the page back from
// its back/forward cache (pageshow, persisted): it is shown as it was left, however long ago, and
// would say nothing of it. Asked once though both events tell of one return.
let returning = null;
function backOnShow(){
  if (!returning) returning = reloadState().finally(() => { returning = null; });
  lookAtSync();
}
document.addEventListener('visibilitychange', () => { if (document.hidden) watchSync(); else backOnShow(); });
window.addEventListener('pageshow', e => { if (e.persisted) backOnShow(); });
// ---- end of back on show ----

// ---- what planner.js uses ----
// The day planner reads the list, opens the drawer and saves through this small namespace rather
// than reaching into this file, and hears of changes through on(): 'render' after each drawing of
// the list (marks, tasks, the view), 'reload' after reloadState, and 'ready' once the page knows
// where it saves. 'ready' is kept: a handler added after it ran is called at once, since planner.js
// may load after the first answer.
const hooks = {render: [], reload: [], ready: []};
let readied = false;
function emit(name){
  if (name === 'ready') readied = true;
  for (const fn of hooks[name]) try { fn(); } catch (err) { console.error(err); }
}
window.SchoolHub = {
  get items(){ return all; },
  byId: id => byId[id],
  get mode(){ return {WRITE, LIVE, REMOTE, PUBLIC, PHONE, LOCAL_FILES}; },
  get view(){ return shownView(); },
  get plannerState(){ return plannerState; },
  // planner.js says whether the page has the planner ('on' or 'off'): the Day view, the rows' drag
  // and the drawer's Plan it follow.
  setPlanner(next){
    if (next === plannerState) return;
    plannerState = next;
    refresh();
  },
  isDone, needsAttention, fmtDue, esc, dot, typingIn, toast, openDrawer, api, markEmoji,
  drawerOpen: () => drawerId !== null,
  // Undo and redo ("undo and redo", above). planner.js adds the plan's changes as steps (addStep,
  // offerStep for a toast's button, same to compare values) and holds the keys during a drag
  // (holdUndo). undo() and redo() are also for the Mac app's Edit menu: each answers true when the
  // page took the request and false when it is the focused field's own (typing).
  same, addStep, offerStep, holdUndo: fn => { holds.push(fn); },
  undo: () => requestStep('undo'),
  redo: () => requestStep('redo'),
  // The copies kept for the next visit ("kept for the next visit"): planner.js keeps the plan there.
  kept,
  on(name, fn){ hooks[name].push(fn); if (name === 'ready' && readied) fn(); },
};
// planner.js not there at all (a server that does not serve it): no planner, rather than a Day view
// that never fills in.
window.addEventListener('load', () => { if (!window.SchoolHub.plannerLoaded && plannerState === 'unknown') window.SchoolHub.setPlanner('off'); });
// ---- end of what planner.js uses ----

// ---- starting ----
// The page starts once it has the last sync's data. dashboard.html asks for data.js without waiting
// for it (async): here already, the page starts from it; not yet, from the copy kept of it at the
// last visit, and data.js takes the copy's place when it comes (dataHere); with neither (a first
// visit) the page starts when data.js arrives, as it always did.
//
// Then your Mac's server or a platform is asked where the page is and what is stored (the phone
// site: its cloud database), unless the page is a file on disk. With the answers kept from the last
// visit the page is drawn from those at once, ✓ buttons, tasks, planner and all, and the server's
// own answer follows quietly: the same as the copy, nothing is drawn again; different, the page
// takes it in place (took). Without a copy the list shows as of the last sync meanwhile.

// Where the page is, by platform.json's answer or the copy kept of it; no answer (at is null): a
// page that does not save. A public copy serves no files (LIVE stays false).
function setPlace(at){
  REMOTE = !!at?.remote;
  PUBLIC = !!at?.public;
  LIVE = !!at && !PUBLIC;
  WRITE = at ? 'local' : null;
}
// The first drawing: the list as of the last sync, or (copy) with the marks and tasks kept from the
// last visit and the ✓ buttons where the page saved then.
function drawFirst(copy){
  tasks = copy ? copy.tasks : null;
  rebuild();
  marks = copy ? copy.marks : syncedMarks();
  if (PHONE) WRITE = copy ? 'cloud' : null; else setPlace(copy?.at);
  // Your Mac's server or a platform is asked below, unless the page is the phone site or a file on
  // disk: no read-only banner meanwhile.
  PROBING = !PHONE && !LOCAL_FILES;
  render();
}
// The last sync shows once it is known whether Sync now goes with it, so the two appear together.
const showSyncbox = () => { $('#syncbox').hidden = false; };
function start(){
  let copy = keptState();
  try { drawFirst(copy); } catch (err) {
    // A copy that cannot be drawn is no copy: as on a first visit.
    if (!copy) throw err;
    console.error(err);
    kept.drop('state');
    drawFirst(copy = null);
  }
  setTimeout(() => kept.tidy(), 3000);
  if (PHONE || LOCAL_FILES) { showSyncbox(); emit('ready'); }
  if (LOCAL_FILES) return nowKnown();
  // Drawn from the copy: what goes with a page that saves shows with it.
  if (copy && PHONE) $('#fab').hidden = false;
  if (copy && !PHONE) { enableServerFeatures(); showSyncbox(); emit('ready'); }
  // The phone site: the cloud database saves marks and tasks when it is connected; without it the
  // page stays a read-only view. Anywhere else your Mac's server answers api/marks and api/tasks,
  // at / on its own port or under a platform's prefix, and a platform says in platform.json
  // whether the page was reached from another device or is public.
  const where = PHONE ? null : fetch('platform.json', {cache: 'no-store'}).then(platformMode).catch(() => ({remote: true, public: false}));
  // (The tasks not answering alone leaves those of the last sync, as it always did.)
  const asked = PHONE ? cloudApi()
    : Promise.all([getJson('api/marks'), where, getJson('api/tasks').catch(() => null)]).then(([m, at, t]) => ({marks: m, tasks: t?.tasks ?? null, at}));
  const sent = saves;      // (a save leaves before the answer only when the page is put away: "asking and saving")
  asked.then(got => {
    // Another place than the copy's (or no copy): the page is drawn again whatever the marks are.
    const moved = !copy || (!PHONE && !same(copy.at, got.at));
    if (PHONE) WRITE = 'cloud'; else setPlace(got.at);
    placed = true;
    keepState();
    PROBING = false;
    if (PHONE) $('#fab').hidden = false; else enableServerFeatures();
    // A save that left before this answer may be newer than the marks and tasks in it, as on
    // coming back to a tab: they are asked for again (reloadState) rather than taken.
    if (saves !== sent) { if (moved) refresh(); reloadState(); }
    else if (!took(got.marks, got.tasks) && moved) refresh();
  }, () => {
    // Asked, and not answered: drawn again without the banner's wait, so a page that cannot save
    // says so. One drawn from a copy goes back to what it is without it.
    PROBING = false;
    if (copy) forgetCopy(); else render();
  }).finally(() => {
    if (!copy && !PHONE) { showSyncbox(); emit('ready'); }
    nowKnown();
  });
}
// The server did not answer after all: the page as it is without the copy, which cannot save (a
// change made meanwhile fails as a save does, and is put back). The copy goes: the next visit asks
// first, as a first visit does.
function forgetCopy(){
  kept.drop('state');
  tasks = null;
  rebuild();
  marks = syncedMarks();
  if (PHONE) WRITE = null; else setPlace(null);
  $('#fab').hidden = syncBtn.hidden = true;
  if (drawerId !== null && !byId[drawerId]) closeDrawer();
  plannerState = PHONE ? plannerState : 'off';
  refresh();
}

// data.js: here before this file ran, or awaited (its script's load or error, or the window's load
// when that was missed). Its text, as JSON, is what is kept, and what tells a new sync from the copy.
let shownData = null;      // the kept copy's text, while the page shows that copy
let dataSeen = false;
function keepData(text){
  const had = kept.get('data');
  // (Kept again once a day though nothing changed, so a copy in use does not run out of time.)
  if (had?.text === text && Date.now() - had.at < 864e5) return;
  if (dataShaped(D)) kept.write('data', text); else kept.drop('data');
}
// Another sync's data than the page shows, taken in place: the list is built and drawn from it with
// the marks and tasks the page has, and an open drawer stays unless its item is gone. For data.js
// when it follows the copy a visit opened from (dataHere), and for a sync that ran while the page
// was open ("sync now": newData).
function takeData(fresh){
  D = fresh;
  rebuild();
  if (!WRITE) marks = syncedMarks();
  if (drawerId !== null && !byId[drawerId]) closeDrawer();
  refresh();
}
function dataHere(){
  if (dataSeen) return;
  dataSeen = true;
  const fresh = window.SCHOOL_DATA;
  if (!fresh) {
    // No data.js to be had. A page drawn from the copy stays as it is, under the copy's own sync
    // time; with nothing to draw, it says what to do.
    if (!D) $('#main').innerHTML = '<p class="empty">No data yet. Run <code>python3 sync.py</code> in the SchoolHub folder.</p>';
    return;
  }
  const text = LOCAL_FILES ? '' : JSON.stringify(fresh);
  if (!D) { D = fresh; start(); }
  // A newer sync than the copy the page was drawn from.
  else if (D !== fresh && text !== shownData) takeData(fresh);
  shownData = null;
  if (!LOCAL_FILES) keepData(text);
}
if (!D) {
  const had = LOCAL_FILES ? null : kept.get('data');
  let copy = null;
  try { copy = had && JSON.parse(had.text); } catch {}
  if (dataShaped(copy)) {
    D = copy;
    shownData = had.text;
    try { start(); } catch (err) {
      // A copy that cannot be drawn is no copy: the page waits for data.js, as on a first visit.
      console.error(err);
      kept.drop('data');
      D = shownData = null;
      $('#main').innerHTML = '';
    }
  }
  const script = document.querySelector('script[src="data.js"]');
  script?.addEventListener('load', dataHere);
  script?.addEventListener('error', dataHere);
  if (document.readyState === 'complete') dataHere(); else window.addEventListener('load', dataHere);
} else {
  start();
  // Kept for the next visit once the page is drawn.
  setTimeout(dataHere, 0);
}
