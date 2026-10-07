// SchoolHub's dashboard. Loaded by dashboard.html after data.js (the last sync), from a file rather
// than inline so the page runs under a Content-Security-Policy of script-src 'self'. The app bar
// (theme, app switch, the O key) is bar.js's, drawn before the first paint.
//
// Every request to SchoolHub's own server uses a relative URL (api/marks, file?p=…), so the page
// works at http://localhost:8722/ and under a path prefix such as /school/ on a platform that
// forwards to it. Only the phone site's cloud API (/api/state/) is absolute.
const D = window.SCHOOL_DATA;
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
const state = { view: mem.get('view', 'upcoming') === 'courses' ? 'courses' : 'upcoming', showDone: mem.get('showDone', false), course: mem.get('course', null), q: '' };
const now = new Date();

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
const api = (path, body) => fetch(path, {
  method: 'POST', headers: {'Content-Type': 'application/json', 'X-SchoolHub': '1'}, body: JSON.stringify(body),
}).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
const getJson = path => fetch(path).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
const cloudApi = body => fetch('/api/state/', {
  method: body ? 'POST' : 'GET',
  headers: {'Content-Type': 'application/json', 'X-SchoolHub-Key': SITE_KEY},
  body: body ? JSON.stringify(body) : undefined,
}).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
// Same calls whether saving through your Mac's server or the phone site's cloud database.
const backend = {
  async mark(id, done, a){
    const body = {id, done, name: a.name, course: a.course.short};
    return WRITE === 'cloud' ? (await cloudApi({action: 'mark', ...body})).marks : api('api/mark', body);
  },
  saveTask: body => WRITE === 'cloud' ? cloudApi({action: 'task', ...body}) : api('api/task', body),
  deleteTask: id => WRITE === 'cloud' ? cloudApi({action: 'deleteTask', id}) : api('api/task/delete', {id}),
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

if (!D) {
  $('#main').innerHTML = '<p class="empty">No data yet. Run <code>python3 sync.py</code> in the SchoolHub folder.</p>';
  throw new Error('no data');
}

// Your own tasks, live from server.py. null means use the copy the last sync baked into data.js.
let tasks = null;
let courses = [], all = [], byId = {};
function taskItem(t){
  const due = t.due_at ? new Date(t.due_at) : null;
  return {id: t.id, name: t.name, due_at: t.due_at, all_day: !!t.all_day, points: null,
    status: due && due < now ? 'overdue' : 'todo', score: null, grade: null, submitted_at: null, late: false,
    platform: 'My task', verifiable: false, url: null, folder: null, files: [], submitted_files: [],
    description_html: '', comments: [], notes: t.notes || '', is_task: true, course_id: t.course_id || 'personal',
    created_at: t.created_at || ''};
}
// A course's dot: the color set for it in config.json if any, else one of the theme's course colors.
const courseColor = (c, i) => c.id === 'personal' ? 'var(--course-personal)'
  : c.color || `var(--course-${i % COURSE_COLORS + 1})`;
function rebuild(){
  let base = D.courses;
  if (tasks) base = base.filter(c => c.id !== 'personal').map(c => ({...c, assignments: c.assignments.filter(a => !a.is_task)}));
  courses = base.map((c, i) => ({...c, color: courseColor(c, i), assignments: [...c.assignments]}));
  if (tasks) {
    const personal = {id: 'personal', source: 'personal', name: 'Personal tasks', short: 'Personal', color: courseColor({id: 'personal'}),
                      assignments: [], materials: []};
    for (const t of Object.values(tasks)) (courses.find(c => c.id === t.course_id) || personal).assignments.push(taskItem(t));
    if (personal.assignments.length) courses.push(personal);
  }
  all = courses.flatMap(c => c.assignments.map(a => ({...a, course: c})));
  byId = Object.fromEntries(all.map(a => [a.id, a]));
}
rebuild();
const dot = c => `<i class="dot" style="background:${esc(c.color)}"></i>`;

// Marks as of the last sync; replaced by the live copy from server.py when available.
let marks = Object.fromEntries(all.filter(a => a.marked_done).map(a => [a.id, {marked_at: a.marked_done}]));

const SOURCE_DONE = ['submitted','graded','excused'];
const past = a => a.due_at && new Date(a.due_at) < now;
function eff(a){
  const m = marks[a.id];
  if (m && !SOURCE_DONE.includes(a.status)) {
    // The nightly check result only applies if it saw this exact mark.
    return a.marked_done === m.marked_at && a.mark_check === 'not_found' ? 'flagged' : 'marked';
  }
  if (a.status === 'todo' && a.due_at && new Date(a.due_at) - now < 48 * 36e5) return 'soon';
  return a.status;
}
// Your ✓ is your word: a mark the nightly check could not confirm ('flagged') still counts as done,
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
  flagged: 'Marked done by you. The nightly check found no submission, which is fine if it was handed in another way',
  check: "SchoolHub can't see this course's submissions yet. If you turned it in, click ✓",
  marked: 'Marked done by you',
};

function row(a){
  const s = eff(a), nf = (a.files?.length || 0), m = !!marks[a.id];
  return `<div class="row" data-id="${esc(a.id)}">
    <span class="chip">${dot(a.course)}${esc(a.course.short || a.course.name)}</span>
    <button type="button" class="name" data-drawer="${esc(a.id)}">${esc(a.name)}${nf ? `<small>📎 ${nf}</small>` : ''}${a.late ? '<small>late</small>' : ''}${a.due_changed_from ? '<small>📅 date changed</small>' : ''}</button>
    <span class="plat">${esc(a.platform)}</span>
    <span class="due">${fmtDue(a.due_at, false, a.all_day)}</span>
    <span class="pill s-${s}" title="${esc(PILL_TIP[s] || '')}">${esc(pillText(a, s))}</span>
    ${canMark(a) ? `<button class="check ${m ? 'on' : ''}" data-mark="${esc(a.id)}" title="${m ? 'Unmark' : 'Mark as done'}" aria-label="${m ? 'Unmark' : 'Mark as done'}">✓</button>` : '<span></span>'}
  </div>`;
}

const byDue = (x, y) => (x.due_at ? new Date(x.due_at) : Infinity) - (y.due_at ? new Date(y.due_at) : Infinity);
// Your own tasks with no due date stay pinned to the top, in the order you added them.
const undatedTask = a => a.is_task && !a.due_at;
const listOrder = (x, y) => (undatedTask(y) - undatedTask(x)) || byDue(x, y)
  || (undatedTask(x) ? String(x.created_at).localeCompare(String(y.created_at)) : 0);

function visible(){
  const q = state.q.trim().toLowerCase();
  return a => (!q || `${a.name} ${a.course.short} ${a.course.name} ${a.platform}`.toLowerCase().includes(q))
    && (state.showDone || !isDone(a) || needsAttention(a));
}

function upcomingView(vis){
  const order = ['My tasks','Needs attention','Today','Tomorrow','Next 7 days','Later','No due date','Earlier'];
  const G = Object.fromEntries(order.map(k => [k, []]));
  for (const a of all.filter(vis)) {
    if (undatedTask(a)) { G['My tasks'].push(a); continue; }
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
  return html || (D.generated_at ? '<p class="empty">Nothing to show. You’re all caught up 🎉</p>' : '');
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
    <div class="chead"><h2>${esc(cur.name)}</h2>${cur.stale ? '<span class="note warn">Showing the last good copy (the site changed; see the issue above)</span>' : ''}
      ${cur.url ? `<a href="${esc(cur.url)}" target="_blank">Open ${siteName(cur.url)} ↗</a>` : ''}
      ${cur.folder ? folderLink(cur.folder) : ''}</div>
    ${list.length ? `<div class="list">${list.map(row).join('')}</div>` : '<p class="empty">No assignments to show.</p>'}
    ${mats ? `<div class="sub">Course materials</div><div class="mat">${mats}</div>` : ''}
  </div></div>`;
}

function stats(){
  const open = all.filter(a => !isDone(a));
  const attention = all.filter(needsAttention).length;
  const soon = open.filter(a => eff(a) === 'soon').length;
  const week = open.filter(a => a.due_at && !past(a) && dayDiff(new Date(a.due_at)) <= 7).length;
  const banner = LIVE || WRITE || PROBING ? '' : LOCAL_FILES
    ? `<div class="banner">To mark assignments done and open files in their apps, use <a href="http://localhost:8722">localhost:8722</a>.</div>`
    : `<div class="banner">Read-only view. Your files and the ✓ buttons live on your Mac; this page shows the last sync.</div>`;
  const none = D.generated_at ? '' : '<div class="banner">No assignments yet: your Mac sends them with its next sync.</div>';
  const errs = D.errors?.length ? `<div class="errors"><b>Last sync had ${D.errors.length} issue(s)</b><ul>${D.errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul></div>` : '';
  return banner + none + errs + `<div class="stats">
    <div class="stat ${attention ? 'red' : ''}"><b>${attention}</b><span>Need attention</span></div>
    <div class="stat ${soon ? 'amber' : ''}"><b>${soon}</b><span>Due in the next 48h</span></div>
    <div class="stat"><b>${week}</b><span>Due in the next 7 days</span></div>
    <div class="stat"><b>${D.new_files?.length || 0}</b><span>New files from last sync</span></div>
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
function refocus(within, keys){
  for (const key of keys || []) {
    const el = within.querySelector(key);
    if (el) return el.focus();
  }
}

function render(){
  document.querySelectorAll('#views button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === state.view)));
  $('#showDone').checked = state.showDone;
  // A public copy gives data with no sync time before the Mac's first sync has reached it.
  const hrs = D.generated_at ? (now - new Date(D.generated_at)) / 36e5 : Infinity;
  $('#sync').textContent = D.generated_at ? 'Synced ' + ago(D.generated_at) : 'Not synced yet';
  $('#sync').title = D.generated_at ? new Date(D.generated_at).toLocaleString() : '';
  $('#sync').classList.toggle('stale', hrs > 30);
  const vis = visible(), main = $('#main'), key = focusKey(main);
  main.innerHTML = stats() + (state.view === 'courses' ? coursesView(vis) : upcomingView(vis));
  refocus(main, key);
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
  if (a.marked_done === m.marked_at && a.mark_check === 'confirmed') return '<div class="note">Confirmed by the nightly check.</div>';
  return `<div class="note">Marked done ${ago(m.marked_at)}. The nightly sync will double-check ${esc(a.platform)} for your submission.</div>`;
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
  drawer.hidden = $('#scrim').hidden = false;
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
function toast(msg, undo){
  clearTimeout(toastTimer);
  $('#toast')?.remove();
  const el = document.createElement('div');
  el.className = 'toast'; el.id = 'toast'; el.setAttribute('role', 'status');
  el.innerHTML = `<span>${esc(msg)}</span>${undo ? '<button type="button">Undo</button>' : ''}<i class="timer" style="animation-duration:${UNDO_MS}ms"></i>`;
  document.body.append(el);
  if (undo) el.querySelector('button').onclick = () => { clearTimeout(toastTimer); el.remove(); undo(); };
  toastTimer = setTimeout(() => el.remove(), UNDO_MS);
}
async function setMark(id, done){
  const a = byId[id], prev = marks[id];
  if (done) marks[id] = {marked_at: new Date().toISOString()}; else delete marks[id];
  refresh();
  try {
    marks = await backend.mark(id, done, a);
    refresh();
    return true;
  } catch {
    if (prev) marks[id] = prev; else delete marks[id];
    refresh();
    toast("Couldn't save. Check your connection and try again.");
    return false;
  }
}
function toggleMark(id){
  const done = !marks[id], a = byId[id];
  // Show Undo right away; setMark swaps in an error toast if the save fails.
  // Undo puts focus back on the assignment's ✓ (the toast's button goes with the toast).
  toast(done ? `Marked “${a.name}” done` : `Unmarked “${a.name}”`,
    () => setMark(id, !done).then(() => { if (document.activeElement === document.body) document.querySelector(`[data-mark="${CSS.escape(id)}"]`)?.focus(); }));
  setMark(id, done);
}
function refresh(){ render(); if (drawerId) openDrawer(drawerId); }

document.addEventListener('click', e => {
  const mk = e.target.closest('[data-mark]');
  if (mk) { e.preventDefault(); e.stopPropagation(); return toggleMark(mk.dataset.mark); }
  const et = e.target.closest('[data-edit-task]'); if (et) { e.preventDefault(); return openTaskForm(et.dataset.editTask); }
  const dt = e.target.closest('[data-delete-task]'); if (dt) { e.preventDefault(); return deleteTask(dt.dataset.deleteTask); }
  const op = e.target.closest('[data-open]');
  // Never from another device: what opens there would open on the Mac's screen.
  if (op) { e.preventDefault(); if (REMOTE) return; return api('api/open', {path: op.dataset.open}).catch(() => toast("Couldn't open that file.")); }
  // A click the keyboard made (Enter or Space on a name) has no click count.
  const r = e.target.closest('.row'); if (r) return openDrawer(r.dataset.id, e.detail === 0);
  const c = e.target.closest('[data-course]'); if (c) { state.course = c.dataset.course; mem.set('course', state.course); render(); }
  const v = e.target.closest('#views button'); if (v) { state.view = v.dataset.view; mem.set('view', state.view); render(); }
});
$('#scrim').onclick = closeDrawer;
document.addEventListener('keydown', e => {
  const typing = typingIn(document.activeElement);
  if (e.key === 'Escape' && !taskDialog.open) closeDrawer();
  if (e.key === '/' && !typing) { e.preventDefault(); $('#q').focus(); }
  if (e.key === 'n' && WRITE && !typing && !taskDialog.open && !e.metaKey && !e.ctrlKey) { e.preventDefault(); openTaskForm(); }
});
$('#q').addEventListener('input', e => { state.q = e.target.value; render(); });
$('#showDone').addEventListener('change', e => { state.showDone = e.target.checked; mem.set('showDone', state.showDone); render(); });
// ---- your own tasks ----
const taskDialog = $('#taskDialog');
let editingTask = null;
const pad = n => String(n).padStart(2, '0');
function openTaskForm(id){
  const t = id ? tasks?.[id] : null;
  editingTask = t ? t.id : null;
  $('#taskHeading').textContent = t ? 'Edit task' : 'New task';
  const preferred = t?.course_id || (state.view === 'courses' && state.course) || 'personal';
  $('#tCourse').innerHTML = [['personal', 'Personal'], ...courses.filter(c => c.id !== 'personal').map(c => [c.id, c.short || c.name])]
    .map(([value, label]) => `<option value="${esc(value)}"${value === preferred ? ' selected' : ''}>${esc(label)}</option>`).join('');
  const d = t?.due_at ? new Date(t.due_at) : null;
  $('#tName').value = t?.name || '';
  $('#tDate').value = d ? `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` : '';
  $('#tTime').value = d && !t.all_day ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : '';
  $('#tNotes').value = t?.notes || '';
  taskDialog.showModal();
  $('#tName').focus();
}
function refreshTasks(next){ tasks = next; rebuild(); refresh(); }
async function saveTask(e){
  e.preventDefault();
  const name = $('#tName').value.trim();
  if (!name) return $('#tName').focus();
  const date = $('#tDate').value, time = $('#tTime').value;
  const body = {name, course_id: $('#tCourse').value, notes: $('#tNotes').value,
    due_at: date ? new Date(`${date}T${time || '23:59'}`).toISOString() : null, all_day: !!date && !time};
  if (editingTask) body.id = editingTask;
  try {
    const r = await backend.saveTask(body);
    taskDialog.close();
    refreshTasks(r.tasks);
    if (editingTask) toast(`Saved “${name}”`);
    else toast(`Added “${name}”`, () => backend.deleteTask(r.task.id).then(x => refreshTasks(x.tasks)));
  } catch {
    toast("Couldn't save the task. Check your connection and try again.");
  }
}
async function deleteTask(id){
  const removed = tasks?.[id];
  if (!removed) return;
  try {
    const r = await backend.deleteTask(id);
    if (drawerId === id) closeDrawer();
    refreshTasks(r.tasks);
    toast(`Deleted “${removed.name}”`, () => backend.saveTask(removed).then(x => refreshTasks(x.tasks)));
  } catch {
    toast("Couldn't delete the task.");
  }
}
$('#taskForm').addEventListener('submit', saveTask);
$('#taskCancel').onclick = () => taskDialog.close();
taskDialog.addEventListener('click', e => { if (e.target === taskDialog) taskDialog.close(); });
$('#fab').onclick = () => openTaskForm();

// ---- sync now ----
// Never on a public copy: syncs run on the Mac, which has your Canvas login.
const syncBtn = $('#syncBtn');
function showSyncing(on){ syncBtn.disabled = on; syncBtn.textContent = on ? 'Syncing…' : 'Sync now'; }
async function pollSync(){
  let s;
  try { s = await getJson('api/sync'); } catch { showSyncing(false); return toast("Couldn't reach the SchoolHub server."); }
  if (s.running) { showSyncing(true); return setTimeout(pollSync, 2000); }
  try { sessionStorage.setItem('sh:synced', JSON.stringify({ok: s.ok, output: s.output})); } catch {}
  location.reload();
}
function enableServerFeatures(){
  $('#fab').hidden = false;
  getJson('api/tasks').then(r => refreshTasks(r.tasks)).catch(() => {});
  if (PUBLIC) return;
  syncBtn.hidden = false;
  syncBtn.onclick = () => api('api/sync', {}).then(() => { showSyncing(true); setTimeout(pollSync, 1500); })
    .catch(() => toast("Couldn't start a sync. Is the SchoolHub server running?"));
  getJson('api/sync').then(s => { if (s.running) { showSyncing(true); pollSync(); } }).catch(() => {});
  let done = null;
  try { done = JSON.parse(sessionStorage.getItem('sh:synced')); sessionStorage.removeItem('sh:synced'); } catch {}
  if (done) {
    const summary = (done.output || '').split('\n').find(l => l.startsWith('[schoolhub]'))?.replace('[schoolhub] ', '') || '';
    const issues = (done.output || '').split('\n').filter(l => /^(⚠️|🔎|❌)/.test(l)).length;
    toast(done.ok ? `Sync finished${summary ? ' · ' + summary : ''}${issues ? ` · ${issues} alert(s)` : ''}` : 'Sync failed. See state/sync.log');
  }
}
// ---- end of sync now ----

// Pick up changes made on your other device when you come back to this tab.
async function reloadState(){
  try {
    if (WRITE === 'cloud') {
      const s = await cloudApi();
      marks = s.marks;
      refreshTasks(s.tasks);
    } else if (WRITE === 'local') {
      marks = await getJson('api/marks');
      refreshTasks((await getJson('api/tasks')).tasks);
    }
  } catch {}
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) reloadState(); });

// Your Mac's server or a platform is asked below, before the first render, unless the page is the
// phone site or a file on disk.
PROBING = !PHONE && !LOCAL_FILES;
render();
// The last sync shows once it is known whether Sync now goes with it, so the two appear together.
const showSyncbox = () => { $('#syncbox').hidden = false; };
if (PHONE || LOCAL_FILES) showSyncbox();
if (PHONE) {
  // The phone site: the cloud database saves marks and tasks when it is connected; without it the
  // page stays a read-only view.
  cloudApi().then(s => {
    marks = s.marks;
    WRITE = 'cloud';
    $('#fab').hidden = false;
    refreshTasks(s.tasks);
  }).catch(() => {});
} else if (!LOCAL_FILES) {
  // Your Mac's server answers api/marks, at / on its own port or under a platform's prefix, and a
  // platform says in platform.json whether the page was reached from another device or is public.
  const where = fetch('platform.json', {cache: 'no-store'}).then(platformMode).catch(() => ({remote: true, public: false}));
  Promise.all([getJson('api/marks'), where]).then(([m, at]) => {
    marks = m;
    REMOTE = at.remote;
    PUBLIC = at.public;
    LIVE = !PUBLIC;
    WRITE = 'local';
    enableServerFeatures();
  }).catch(() => {}).finally(() => {
    PROBING = false;
    render();
    showSyncbox();
  });
}
