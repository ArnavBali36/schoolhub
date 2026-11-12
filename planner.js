// SchoolHub's day planner (docs/planner.md, section 3): one day from 5 AM to midnight beside the
// list, with meals (where to eat comes from a weekly form), deep work, socializing and other blocks,
// each holding the work to get done in it. Loaded by dashboard.html after dashboard.js, whose small
// window.SchoolHub namespace gives it the list, the drawer, the toast and the requests. A file of its
// own, not inline, so the page runs under a Content-Security-Policy of script-src 'self'.
//
// It saves to api/plan, relative like every request to SchoolHub's own server so it works under
// /school/ too, one key per object: settings, week:<weekday> and day:<date>. Every value is cleaned
// here by the server's rules (plan.py) before it is sent, so a save never meets a 400 in normal use.
(() => {
  'use strict';
  const SH = window.SchoolHub;
  if (!SH) return;
  SH.plannerLoaded = true;
  const $ = s => document.querySelector(s);
  const esc = SH.esc;

  // The whole day fits the planner (docs/planner.md, "the whole day always in view"): an hour is the
  // timeline's room divided by the hours shown, never under MIN_HOUR_PX (only then does it scroll).
  const MIN_HOUR_PX = 22;
  const DENSE_HOUR_PX = 30;      // under this the hour labels thin out and the half-hour lines go
  const MIN_BLOCK_PX = 20;       // a block is never drawn shorter, whatever its length
  const NARROW_COL_PX = 70;      // a column narrower than this shows only the kind's initial
  const ITEM_PX = 21;            // an item's line on a block
  const FLAG_LANE_PX = 92;       // the lane on the right kept for flags of things due at a time
  const TIME_PAD = 15;           // the timeline's margins above and below (.ptime) and the grid's border
  const SNAP = 15;              // minutes a drag on the timeline snaps to
  const MIN_LEN = 15;            // the shortest block a drag makes or leaves
  const LEAST = 5;               // the shortest block there is: one step of the clock (plan.py MIN_MINUTES)
  const CLICK_PX = 4;            // a pointer that moves less than this clicked
  const LONG_PRESS_MS = 450;     // a touch held this long without moving starts a drag
  const TOUCH_SLOP = 8;          // a touch that moves this far before then is a scroll
  const LIMIT = {blocks: 40, items: 50, title: 120, place: 120, text: 200, course: 120, ref: 200};
  const WD = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
  const WD_NAME = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const MEALS = ['breakfast', 'lunch', 'dinner'];
  const MEAL_NAME = {breakfast: 'Breakfast', lunch: 'Lunch', dinner: 'Dinner'};
  const KINDS = ['deep', 'social', 'other'];
  const KIND_NAME = {deep: 'Deep work', social: 'Socialize', other: 'Block'};
  // What a column too narrow for words shows: the kind's initial (its colour and name go with it).
  const INITIAL = {meal: 'M', deep: 'D', social: 'S', other: 'B'};
  const DEFAULT_SETTINGS = {day_start: 5, day_end: 24};
  const DEFAULT_MEALS = {breakfast: ['11:00', '12:00'], lunch: ['16:00', '17:00'], dinner: ['18:00', '19:00']};
  // What a row of the list carries when dragged onto the timeline: the assignment's or task's id.
  const ITEM_TYPE = 'application/x-schoolhub-item';

  // ---- times and dates ----
  const pad = n => String(n).padStart(2, '0');
  const toMin = t => { const m = /^(\d{2}):(\d{2})/.exec(t || ''); return m ? +m[1] * 60 + +m[2] : NaN; };
  const toTime = m => pad(Math.floor(m / 60)) + ':' + pad(m % 60);
  const mer = m => Math.floor(m / 60) % 24 < 12 ? 'AM' : 'PM';
  // "4:00 PM"; midnight at either end of the day is 12:00 AM.
  const clock = (m, withMer = true) => `${Math.floor(m / 60) % 12 || 12}:${pad(m % 60)}` + (withMer ? ' ' + mer(m) : '');
  // "4:00–5:00 PM", or "11:00 AM–12:00 PM" across noon; sep ' to ' for screen readers.
  const range = (s, e, sep = '–') => mer(s) === mer(e) && e - s < 720 ? `${clock(s, false)}${sep}${clock(e)}` : `${clock(s)}${sep}${clock(e)}`;
  // The compact forms: "4", "4:30 PM"; "4–5 PM", "11 PM–12 AM".
  const shortClock = (m, withMer = true) => `${Math.floor(m / 60) % 12 || 12}${m % 60 ? ':' + pad(m % 60) : ''}` + (withMer ? ' ' + mer(m) : '');
  const shortRange = (s, e) => mer(s) === mer(e) && e - s < 720 ? `${shortClock(s, false)}–${shortClock(e)}` : `${shortClock(s)}–${shortClock(e)}`;
  // A length: "15 min", "1 hr", "1 hr 30 min".
  const duration = n => [Math.floor(n / 60) ? Math.floor(n / 60) + ' hr' : '', n % 60 ? n % 60 + ' min' : ''].filter(Boolean).join(' ') || '0 min';
  const hourLabel = h =>`${h % 12 || 12} ${h % 24 < 12 ? 'AM' : 'PM'}`;
  const isoDate = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const fromIso = s => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
  const addDays = (s, n) => { const d = fromIso(s); d.setDate(d.getDate() + n); return isoDate(d); };
  const todayIso = () => isoDate(new Date());
  const minutesNow = () => { const d = new Date(); return d.getHours() * 60 + d.getMinutes(); };
  const wdOf = s => WD[fromIso(s).getDay()];
  const wdName = s => WD_NAME[fromIso(s).getDay()];
  const longDate = s => fromIso(s).toLocaleDateString([], {weekday: 'long', month: 'long', day: 'numeric'});
  const shortDate = s => fromIso(s).toLocaleDateString([], {weekday: 'short', month: 'short', day: 'numeric'});
  const isToday = s => s === todayIso();
  // A day's own changes are named for it: "today", or "this day" for any other.
  const thisDay = s => isToday(s) ? 'today' : 'this day';
  const onDay = s => isToday(s) ? 'today' : 'on ' + shortDate(s);
  // A time input's value in minutes, rounded to the server's 5-minute steps, or null. A time input
  // cannot say 24:00, so an end of 00:00 is midnight at the end of the day.
  function readTime(input, isEnd){
    const m = toMin(input.value);
    if (isNaN(m)) return null;
    const r = Math.min(1440, Math.round(m / 5) * 5);
    return isEnd && r === 0 ? 1440 : r;
  }
  const timeValue = m => m >= 1440 ? '00:00' : toTime(m);
  function spanError(s, e){
    if (s == null || e == null) return 'Give a start and an end time.';
    if (e <= s) return 'The end must be after the start.';
    if (e - s < LEAST) return `A block lasts at least ${LEAST} minutes.`;
    return '';
  }

  // ---- cleaning, by the server's rules (plan.py) ----
  const ID_RE = /^[a-z0-9]{6,32}$/;
  const ID_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789';
  function newId(){
    const b = new Uint8Array(10);
    crypto.getRandomValues(b);
    return Array.from(b, x => ID_CHARS[x % 36]).join('');
  }
  // An id the server takes and has not seen in this value: the one given, else a new one.
  function fresh(id, seen){
    let v = typeof id === 'string' && ID_RE.test(id) && !seen.has(id) ? id : newId();
    while (seen.has(v)) v = newId();
    seen.add(v);
    return v;
  }
  const cut = (s, n) => String(s ?? '').trim().slice(0, n);
  const clone = v => v == null ? null : JSON.parse(JSON.stringify(v));
  const isObject = v => !!v && typeof v === 'object' && !Array.isArray(v);
  // off, done and skip as the server makes them true or false (plan.py _flag): true, a number other
  // than 0 or a string other than "" is true; anything else, a list or an object included, is false.
  const flag = v => v === true || (typeof v === 'number' && v !== 0) || (typeof v === 'string' && v !== '');
  // A value's blocks: only objects, at most the server's 40.
  const blocksOf = v => (Array.isArray(v?.blocks) ? v.blocks : []).filter(isObject).slice(0, LIMIT.blocks);
  // A start and end the server keeps: HH:MM in 5-minute steps within the day, the end at least 5
  // minutes after the start. The page's own checks come first; this only keeps a slip from a 400.
  function cleanSpan(start, end){
    let s = toMin(start), e = toMin(end);
    s = isNaN(s) ? 540 : Math.max(0, Math.min(1440 - LEAST, Math.round(s / 5) * 5));
    e = isNaN(e) ? s + 60 : Math.min(1440, Math.round(e / 5) * 5);
    if (e < s + LEAST) e = Math.min(1440, s + LEAST);
    return [toTime(s), toTime(e)];
  }
  function cleanItems(items, seen){
    const out = [];
    for (const it of Array.isArray(items) ? items : []) {
      if (out.length >= LIMIT.items) break;
      if (!it || typeof it !== 'object') continue;
      const kind = it.kind === 'work' ? 'work' : 'own', text = cut(it.text, LIMIT.text);
      if (kind === 'own' && !text) continue;
      const item = {id: fresh(it.id, seen), kind, text, done: flag(it.done)};
      if (kind === 'work') {
        // The server refuses a ref or course that is too long rather than cutting it.
        const ref = String(it.ref || '');
        if (!ref || ref.length > LIMIT.ref) continue;
        Object.assign(item, {ref, course: String(it.course || '').slice(0, LIMIT.course)});
      }
      out.push(item);
    }
    return out;
  }
  function cleanBlock(b, seen, dated){
    const type = KINDS.includes(b?.type) ? b.type : 'other';
    const [start, end] = cleanSpan(b.start, b.end);
    const out = {id: fresh(b.id, seen), type, title: cut(b.title, LIMIT.title) || KIND_NAME[type], start, end};
    if (dated) out.items = cleanItems(b.items, seen);
    return out;
  }
  function cleanSettings(v){
    const s = Number.isInteger(v?.day_start) && v.day_start >= 0 && v.day_start <= 23 ? v.day_start : DEFAULT_SETTINGS.day_start;
    const e = Number.isInteger(v?.day_end) && v.day_end >= 1 && v.day_end <= 24 ? v.day_end : DEFAULT_SETTINGS.day_end;
    return e - s >= 4 ? {day_start: s, day_end: e} : {...DEFAULT_SETTINGS};
  }
  // A weekday's template: all three meals, and its repeating blocks without items (items belong to
  // a date, never to the week).
  function cleanWeek(v){
    const meals = {};
    for (const m of MEALS) {
      const src = isObject(v?.meals?.[m]) ? v.meals[m] : {}, [ds, de] = DEFAULT_MEALS[m];
      const [start, end] = cleanSpan(src.start ?? ds, src.end ?? de);
      meals[m] = {start, end, place: cut(src.place, LIMIT.place), off: flag(src.off)};
    }
    const seen = new Set();
    return {meals, blocks: blocksOf(v).map(b => cleanBlock(b, seen, false))};
  }
  // A date's value with only what differs from its weekday kept, or null when nothing is left, which
  // deletes the key. A change to a block no longer in the week is dropped (the server ignores it).
  function cleanDay(v, week){
    const ids = new Set(week.blocks.map(b => b.id));
    // A repeat's key is a week block's id, never one of the value's own; kept apart all the same.
    const seen = new Set(ids), out = {}, meals = {}, repeats = {};
    const times = (src, base, o) => {
      if (src.start == null && src.end == null) return;
      const [s, e] = cleanSpan(src.start ?? base.start, src.end ?? base.end);
      if (s !== base.start || e !== base.end) Object.assign(o, {start: s, end: e});
    };
    for (const m of MEALS) {
      const src = v?.meals?.[m];
      if (!isObject(src)) continue;
      const base = week.meals[m], o = {};
      times(src, base, o);
      if (src.place != null && cut(src.place, LIMIT.place) !== base.place) o.place = cut(src.place, LIMIT.place);
      if (src.off != null && flag(src.off) !== base.off) o.off = flag(src.off);
      const items = cleanItems(src.items, seen);
      if (items.length) o.items = items;
      if (Object.keys(o).length) meals[m] = o;
    }
    if (Object.keys(meals).length) out.meals = meals;
    const blocks = blocksOf(v).map(b => cleanBlock(b, seen, true));
    if (blocks.length) out.blocks = blocks;
    for (const [id, src] of Object.entries(isObject(v?.repeats) ? v.repeats : {})) {
      if (!ids.has(id) || !isObject(src)) continue;
      const o = {};
      times(src, week.blocks.find(b => b.id === id), o);
      if (flag(src.skip)) o.skip = true;
      const items = cleanItems(src.items, seen);
      if (items.length) o.items = items;
      if (Object.keys(o).length) repeats[id] = o;
    }
    if (Object.keys(repeats).length) out.repeats = repeats;
    return Object.keys(out).length ? out : null;
  }

  // ---- the plan, loaded and saved ----
  let plan = null;               // {settings, week: {sun: …}, days: {date: value}}
  let loaded = null;             // the dates plan.days covers: {from, to}
  let loadFailed = false;        // the first load failed: the planner offers to try again
  let loadSeq = 0, needReload = false;
  let pending = 0, saveFailed = false, saveSerial = 0;
  let chain = Promise.resolve();
  const latest = {};             // key → the number of its latest save, so an older answer never wins
  let shown = todayIso();

  const settings = () => plan?.settings || DEFAULT_SETTINGS;
  const weekOf = wd => plan?.week?.[wd] || cleanWeek(null);
  const inRange = d => !!loaded && d >= loaded.from && d <= loaded.to;
  // The shown date's own value is known, so a change to it cannot lose what is stored.
  const editable = () => !!plan && inRange(shown);

  function getKey(key){
    if (key === 'settings') return plan.settings;
    if (key.startsWith('week:')) return weekOf(key.slice(5));
    return plan.days[key.slice(4)] || null;
  }
  function setKey(key, value){
    if (key === 'settings') plan.settings = cleanSettings(value);
    else if (key.startsWith('week:')) plan.week[key.slice(5)] = value || cleanWeek(null);
    else if (value) plan.days[key.slice(4)] = value;
    else delete plan.days[key.slice(4)];
  }
  // Changes show at once; the saves go one at a time, in order, so a week's change lands before the
  // date's change that depends on it. A failed save says so and loads the plan again.
  function save(key, value){
    setKey(key, value);
    const n = latest[key] = (latest[key] || 0) + 1;
    pending++;
    saveSerial++;
    chain = chain
      .then(() => SH.api('api/plan', {key, value}))
      .then(r => { if (latest[key] === n && r?.key === key) setKey(key, r.value); }, () => { saveFailed = true; })
      .then(() => {
        if (--pending) return;
        if (saveFailed) { saveFailed = false; SH.toast("Couldn't save the plan"); needReload = true; }
        if (needReload) load(shown); else render();
      });
    render();
  }
  // The values of some keys now, and a function that puts them back (a toast's Undo).
  function snapshot(keys){
    const old = keys.map(k => [k, clone(getKey(k))]);
    return () => { for (const [k, v] of old) save(k, v); };
  }
  function editDay(date, fn){
    const v = clone(plan.days[date]) || {};
    if (fn(v) === false) return false;
    save('day:' + date, cleanDay(v, weekOf(wdOf(date))));
    return true;
  }
  function editWeek(wd, fn){
    const v = clone(weekOf(wd));
    if (fn(v) === false) return false;
    save('week:' + wd, cleanWeek(v));
    return true;
  }
  // The object in a date's value that keeps an entry's changes and items, made when missing (null
  // for a one-off block that is gone).
  function holder(v, ref){
    const [type, id] = ref.split(':');
    if (type === 'meal') { v.meals ||= {}; return v.meals[id] ||= {}; }
    if (type === 'repeat') { v.repeats ||= {}; return v.repeats[id] ||= {}; }
    return (v.blocks || []).find(b => b.id === id) || null;
  }

  // The shown date ±7 days, again whenever the date leaves that range, and with the marks and tasks.
  // While a save is on its way an answer could be older than it, so the load waits for the saves.
  async function load(center = shown){
    if (pending) { needReload = true; return; }
    needReload = false;
    const from = addDays(center, -7), to = addDays(center, 7), n = ++loadSeq, serial = saveSerial;
    let r = null, body = null;
    try { r = await fetch(`api/plan?from=${from}&to=${to}`, {cache: 'no-store'}); } catch {}
    // A server from before the planner: no planner, rather than one that never saves.
    if (r?.status === 404 && !plan) return SH.setPlanner('off');
    if (r?.ok) try { body = await r.json(); } catch {}
    if (n !== loadSeq) return;
    if (!body || typeof body !== 'object') {
      if (!plan) { loadFailed = true; SH.setPlanner('on'); }
      return render();
    }
    if (pending || serial !== saveSerial) { needReload = true; if (!pending) load(shown); return; }
    plan = {settings: cleanSettings(body.settings), week: {}, days: {}};
    for (const wd of WD) plan.week[wd] = cleanWeek(body.week?.[wd]);
    for (const [d, v] of Object.entries(body.days || {})) if (v && typeof v === 'object') plan.days[d] = v;
    loaded = {from, to};
    loadFailed = false;
    SH.setPlanner('on');
    render();
  }

  // ---- what shows on a date ----
  // Meals (the date's change over the weekday's over the defaults), the weekday's repeating blocks
  // with the date's changes, and the date's own blocks. Each entry's ref says where it is kept.
  function entriesOn(date){
    const week = weekOf(wdOf(date)), day = plan?.days[date] || {}, out = [];
    for (const m of MEALS) {
      const b = week.meals[m], o = day.meals?.[m] || {};
      out.push({ref: 'meal:' + m, kind: 'meal', meal: m, title: MEAL_NAME[m], start: toMin(o.start ?? b.start), end: toMin(o.end ?? b.end),
        place: o.place ?? b.place, off: o.off ?? b.off, dayOff: o.off === true, items: o.items || [], changed: o.start != null || o.end != null,
        placeChanged: o.place != null && o.place !== b.place});
    }
    for (const b of week.blocks) {
      const r = day.repeats?.[b.id] || {};
      out.push({ref: 'repeat:' + b.id, kind: b.type, id: b.id, repeat: true, title: b.title, start: toMin(r.start ?? b.start),
        end: toMin(r.end ?? b.end), skip: !!r.skip, items: r.items || [], changed: r.start != null || r.end != null});
    }
    for (const b of day.blocks || [])
      out.push({ref: 'block:' + b.id, kind: b.type, id: b.id, title: b.title, start: toMin(b.start), end: toMin(b.end), items: b.items || []});
    return out;
  }
  const entryByRef = ref => entriesOn(shown).find(e => e.ref === ref) || null;
  const entryName = e => e.kind === 'meal' ? e.title : `${e.title}, ${range(e.start, e.end)}`;
  const workItem = a => ({id: newId(), kind: 'work', ref: a.id, text: cut(a.name, LIMIT.text),
    course: String(a.course?.short || a.course?.name || '').slice(0, LIMIT.course), done: false});
  const listDone = it => { const a = it.kind === 'work' && SH.byId(it.ref); return !!a && SH.isDone(a); };
  const dueOn = date => SH.items.filter(a => a.due_at && isoDate(new Date(a.due_at)) === date);
  const openItems = () => SH.items.filter(a => !SH.isDone(a) && a.id.length <= LIMIT.ref)
    .sort((x, y) => (x.due_at ? Date.parse(x.due_at) : Infinity) - (y.due_at ? Date.parse(y.due_at) : Infinity) || x.name.localeCompare(y.name));

  // Blocks that overlap share the width: each run of overlapping blocks gets as many columns as it
  // needs, and each block the first column free at its start. span gives a block's [from, to): its
  // times, or where it is drawn (place).
  function layout(list, span = e => [e.start, e.end]){
    const at = new Map(list.map(e => [e, span(e)]));
    list.sort((a, b) => at.get(a)[0] - at.get(b)[0] || at.get(b)[1] - at.get(a)[1]);
    let group = [], groupEnd = -Infinity;
    const flush = () => { const n = Math.max(...group.map(e => e.col)) + 1; for (const e of group) e.cols = n; group = []; groupEnd = -Infinity; };
    for (const e of list) {
      const [from, to] = at.get(e);
      if (group.length && from >= groupEnd) flush();
      const used = new Set(group.filter(g => at.get(g)[1] > from).map(g => g.col));
      let c = 0;
      while (used.has(c)) c++;
      e.col = c;
      group.push(e);
      groupEnd = Math.max(groupEnd, to);
    }
    if (group.length) flush();
  }
  // The hour's height for the room the timeline has: the room divided by the hours, in whole pixels
  // so the hour lines stay sharp. Under MIN_HOUR_PX the hour stays at that and the timeline scrolls.
  function fitHour(room, hours){
    const px = Math.floor(room / hours);
    return px >= MIN_HOUR_PX ? {px, scroll: false} : {px: MIN_HOUR_PX, scroll: true};
  }
  // Every how many hours a label is written: each hour, or every 2 (3) when the hours are short.
  const labelStep = px => px >= DENSE_HOUR_PX ? 1 : px >= 18 ? 2 : 3;
  // Where each block of the shown hours is drawn, in pixels from the top of the timeline. A block
  // running past the hours is cut at their edge (cutTop, cutBottom; its text keeps its real times),
  // none is shorter than MIN_BLOCK_PX, and one that would then run past the end of the day is moved
  // up to end there. Blocks share the width where they are drawn over each other, which a short
  // block drawn taller than its time can be.
  function place(list, lo, hi, px){
    const H = (hi - lo) / 60 * px, y = m => (Math.max(lo, Math.min(hi, m)) - lo) / 60 * px;
    for (const e of list) {
      const top = y(e.start);
      e.h = Math.max(MIN_BLOCK_PX, y(e.end) - top - 2);
      e.top = Math.max(0, Math.min(top, H - e.h));
      e.cutTop = e.start < lo;
      e.cutBottom = e.end > hi;
    }
    layout(list, e => [e.top, e.top + e.h + 1]);
    return list;
  }
  // How a block is drawn for its height and width: 'nar' (a column too narrow for words: the kind's
  // initial), 'xs' and 'sm' (one line, "Lunch · Chipotle · 4–5 PM"), 'md' (the title and the time
  // on one line, items under it, where the line is wide enough) or '' (the title, the time under
  // it, then items).
  const blockForm = (h, w) => w < NARROW_COL_PX ? 'nar' : h < 26 ? 'xs' : h < 40 ? 'sm' : h < 64 && w >= 160 ? 'md' : '';
  // Whether a one-line block has room for its time after the start of its title (about 6 px a
  // character): where it has not, the line is all title, and the time is in the details.
  // extra: the room something else on the line takes (the kind's name or initial).
  const timeFits = (w, title, time, badge, extra = 0) => w - 16 - (badge ? 26 : 0) - extra - (time.length * 6 + 10) >= Math.min(title.length * 6.6, 60);
  // The room the kind's name takes as a tag on a block's line ("DEEP WORK"), and its initial as a
  // badge before the title where the name does not fit.
  const tagPx = name => name.length * 7.5 + 8;
  const BADGE_PX = 24;
  // How many of a block's n items fit, and whether "+N more" goes after the time (where a line of
  // its own would cost an item, or does not fit). The one-line forms show none.
  function itemsFit(h, form, n){
    if (form !== 'md' && form !== '') return {fit: 0, inline: false};
    const room = h - (form === 'md' ? 23 : 40), all = Math.max(0, Math.floor(room / ITEM_PX));
    const below = Math.max(0, Math.floor((room - 16) / ITEM_PX)), inline = all < n && (below < all || room < 16);
    return {fit: all >= n ? n : inline ? all : below, inline};
  }
  // "Lunch, 4:00 to 5:00 PM, at Chipotle, 2 things to get done": a block as a screen reader reads it.
  function spoken(e){
    const name = e.kind === 'meal' || e.title === KIND_NAME[e.kind] ? e.title : `${KIND_NAME[e.kind]}: ${e.title}`;
    const parts = [name, range(e.start, e.end, ' to ')];
    if (e.kind === 'meal') parts.push(e.place ? 'at ' + e.place : 'no place set');
    const open = e.items.filter(i => !i.done).length;
    if (e.items.length) parts.push(open ? `${open} ${open === 1 ? 'thing' : 'things'} to get done` : 'all done');
    if (e.repeat) parts.push('repeats every ' + wdName(shown));
    if (e.changed) parts.push('changed for ' + thisDay(shown));
    return parts.join(', ');
  }

  // ---- drawing ----
  const root = $('#planner');
  if (!root) return;
  root.innerHTML = `<div class="ph">
      <div class="ph-nav">
        <button type="button" class="ph-step" data-pstep="-1" aria-label="Previous day" title="Previous day ([)">‹</button>
        <h2 class="ph-date" id="planDate" aria-live="polite"></h2>
        <button type="button" class="ph-step" data-pstep="1" aria-label="Next day" title="Next day (])">›</button>
      </div>
      <div class="ph-actions">
        <button type="button" class="btn small" id="planToday" hidden>Today</button>
        <button type="button" class="btn small" id="planWeek" title="Meals and repeating blocks for every week" disabled>Week…</button>
        <button type="button" class="btn small primary" id="planAdd" disabled>+ Block</button>
      </div>
    </div>
    <div class="pstrip" id="planStrip" role="group" aria-label="Also on this day" hidden></div>
    <div class="pscroll" id="planScroll">
      <p class="pmsg" id="planMsg">Loading the plan…</p>
      <div class="ptime" id="planTime" hidden>
        <div class="phours" id="planHours" aria-hidden="true"></div>
        <div class="pgrid" id="planGrid" role="list"></div>
      </div>
    </div>`;
  const els = {date: $('#planDate'), today: $('#planToday'), week: $('#planWeek'), add: $('#planAdd'), strip: $('#planStrip'),
    scroll: $('#planScroll'), msg: $('#planMsg'), time: $('#planTime'), hours: $('#planHours'), grid: $('#planGrid')};
  const grid = els.grid;
  const drawDate = () => { els.date.innerHTML = `<span class="long">${esc(longDate(shown))}</span><span class="short">${esc(shortDate(shown))}</span>`; };
  drawDate();

  // The focused control, found again once the planner is drawn anew.
  const FOCUS_KEYS = ['data-open-ref', 'data-pitem', 'data-plan-due', 'data-pedit', 'data-pmeal-on', 'data-prepeat-on', 'data-plan-retry', 'id'];
  function focusKey(){
    const el = document.activeElement;
    if (!el || !root.contains(el)) return null;
    const k = FOCUS_KEYS.find(a => el.hasAttribute(a));
    return k ? `[${k}="${CSS.escape(el.getAttribute(k))}"]` : null;
  }
  // Where focus goes once a dialog or the details close, or a block goes: the block (a selector,
  // looked up after the planner is drawn anew), else fallback (+ Block). Never left on <body>.
  const refSel = ref => ref ? `[data-open-ref="${CSS.escape(ref)}"],[data-pedit="${CSS.escape(ref)}"]` : null;
  const focusLost = () => !document.activeElement || document.activeElement === document.body;
  function refocus(sel, fallback = els.add){
    const el = sel && root.querySelector(sel);
    (el || (fallback && !fallback.disabled && fallback.getClientRects().length ? fallback : root.querySelector('.ph-step')))?.focus();
  }
  // The block after (else before) ref on the timeline, for focus once ref is gone.
  function neighbourSel(ref){
    const all = [...grid.querySelectorAll('[data-open-ref]')].map(b => b.dataset.openRef), i = all.indexOf(ref);
    return refSel(i < 0 ? all[0] : all[i + 1] ?? all[i - 1]);
  }

  // A block where place() put it, in a grid gridW pixels wide. Every block is drawn and readable
  // (blockForm): tall ones show their title, time and as many items as fit; short ones one line;
  // a narrow column only the kind's initial and colour, its name in the button's label.
  function blockHtml(e, gridW){
    const {top, h} = e, w = gridW / e.cols - 4;
    let form = blockForm(h, w);
    const meal = e.kind === 'meal';
    const title = meal ? `${esc(e.title)} · ${e.place ? esc(e.place) : '<i>set a place</i>'}` : esc(e.title);
    const plain = meal ? `${e.title} · ${e.place || 'set a place'}` : e.title;
    // The kind's name is written, so colour is never the only cue: a meal's is its title, and so is
    // a block's titled with it. Any other block shows the name as a tag on its line where there is
    // room for it beside the title (and the time, on one line), else the kind's initial as a badge
    // before the title. The tooltip and the label say it in full.
    const kindName = !meal && e.title !== KIND_NAME[e.kind] ? KIND_NAME[e.kind] : '';
    const items = e.items;
    let {fit, inline} = itemsFit(h, form, items.length), kindAt = kindName ? 'badge' : '';
    if (form === 'md') {
      // Title and time share a line where both fit (the title cut first); else the time goes on a
      // line of its own, as on a taller block.
      const long = range(e.start, e.end) + (inline ? ` · +${items.length - fit} more` : '');
      if (kindName && timeFits(w, plain, long, 0, tagPx(kindName))) kindAt = 'tag';
      else if (!timeFits(w, plain, long, 0, kindName ? BADGE_PX : 0)) {
        form = '';
        ({fit, inline} = itemsFit(h, form, items.length));
      }
    }
    if (form === '' && kindName && w >= 170) kindAt = 'tag';
    const rest = items.length - fit;
    const badge = kindAt === 'badge' && form !== 'nar' ? `<span class="pb-ki">${INITIAL[e.kind]}</span>` : '';
    let tag = kindAt === 'tag' ? `<span class="pb-kind">${KIND_NAME[e.kind]}</span>` : '';
    let body, list = '', more = '';
    if (form === 'nar') {
      body = `<span class="pb-ini">${INITIAL[e.kind]}</span>`;
    } else if (form === 'xs' || form === 'sm') {
      // One line, cut with an ellipsis: "Lunch · Chipotle · 4–5 PM", and "+N" for its items. The
      // title gives way to the time, which shows only where it fits whole.
      const short = shortRange(e.start, e.end);
      const withTag = kindName && timeFits(w, plain, short, rest, tagPx(kindName));
      tag = withTag ? `<span class="pb-kind">${KIND_NAME[e.kind]}</span>` : '';
      const time = withTag || timeFits(w, plain, short, rest, kindName ? BADGE_PX : 0) ? `<span class="pb-time" data-short="1">· ${esc(short)}</span>` : '';
      body = `<div class="pb-head">${withTag ? '' : badge}<span class="pb-title">${title}</span>${time}${tag}${rest ? `<span class="pb-n">+${rest}</span>` : ''}</div>`;
    } else {
      // As many items as fit under the title and the time, then "+2 more" on a line of its own, or
      // after the time when that line would cost an item.
      const after = inline ? ` · +${rest} more` : '';
      const time = `<span class="pb-time">${esc(range(e.start, e.end))}${after}</span>`;
      body = form === 'md' ? `<div class="pb-head">${badge}<span class="pb-title">${title}</span>${time}${tag}</div>`
        : `<div class="pb-head">${badge}<span class="pb-title">${title}</span>${tag}</div>${time}`;
      list = items.slice(0, fit).map(it => `<li><label class="pb-item${it.done ? ' done' : ''}"><input type="checkbox" data-pitem="${esc(it.id)}"${it.done ? ' checked' : ''}><span>${esc(it.text)}</span>${!it.done && listDone(it) ? '<small>done</small>' : ''}</label></li>`).join('');
      list = list ? `<ul class="pb-items">${list}</ul>` : '';
      if (rest > 0 && !after) more = `<div class="pb-more" aria-hidden="true">+${rest} more</div>`;
    }
    const left = e.col / e.cols * 100, width = 100 / e.cols;
    const cls = ['pblock', 'k-' + e.kind, form, e.cutTop && 'cut-top', e.cutBottom && 'cut-bottom', det?.ref === e.ref && 'shown'].filter(Boolean).join(' ');
    // Where words may be cut short, the whole of them on hover, the kind's name with them.
    const tip = ` title="${esc(`${kindName ? kindName + ': ' : ''}${meal ? e.title + (e.place ? ' · ' + e.place : '') : e.title} · ${range(e.start, e.end)}`)}"`;
    return `<div class="${cls}" role="listitem" data-ref="${esc(e.ref)}" style="top:${top}px;height:${h}px;left:calc((100% - var(--lane, 0px)) * ${left / 100} + 2px);width:calc((100% - var(--lane, 0px)) * ${width / 100} - 4px)">`
      + `<button type="button" class="pb-open" data-open-ref="${esc(e.ref)}" aria-label="${esc(spoken(e))}"${tip}></button>`
      + `<div class="pb-body" aria-hidden="true">${body}</div>${list}${more}`
      + '<span class="pb-rs top" data-edge="top" aria-hidden="true"></span><span class="pb-rs bottom" data-edge="bottom" aria-hidden="true"></span></div>';
  }
  function dueLabel(a, m){
    const when = a.all_day ? 'Due ' + onDay(shown) : 'Due ' + clock(m);
    return `${when}: ${a.name}, ${a.course?.short || a.course?.name || ''}${SH.isDone(a) ? ', done' : ''}`;
  }
  function flagHtml(a, m, top){
    return `<div class="pflag-wrap" role="listitem" style="top:${top}px"><button type="button" class="pflag${SH.isDone(a) ? ' done' : ''}" data-plan-due="${esc(a.id)}" aria-label="${esc(dueLabel(a, m))}" title="${esc(a.name)}">${SH.dot(a.course)}<span><b>${esc(clock(m))}</b><span class="pf-name"> · ${esc(a.name)}</span></span></button></div>`;
  }
  // The hour's height now, and whether the day fits (fit) or the timeline scrolls; set by measure().
  let hourPx = 48, scrolling = false, padBottom = 7;
  let fitted = '', refitting = 0;   // the sizes the hour was last fitted to (measure, refit)
  // The + button (add a task), where it would cover the bottom of the timeline: room under the last
  // hour, so nothing hides behind it. The page keeps it clear of the planner where it can.
  function fabRoom(){
    const fab = document.getElementById('fab');
    if (!fab || fab.hidden || !fab.getClientRects().length) return 0;
    const f = fab.getBoundingClientRect(), s = els.scroll.getBoundingClientRect();
    return f.left < s.right && f.right > s.left && f.top < s.bottom && f.bottom > s.top ? Math.ceil(s.bottom - f.top) : 0;
  }
  // The hour's height for the room under the header: the window's height on wide screens, the Day
  // view's on narrow ones (the planner's own height in CSS), less the strip and the margins.
  function measure(){
    const room = els.scroll.clientHeight;
    if (!room) return false;
    const fab = fabRoom(), s = settings();
    padBottom = fab ? fab + 4 : 7;
    ({px: hourPx, scroll: scrolling} = fitHour(room - TIME_PAD - (padBottom - 7), s.day_end - s.day_start));
    // The sizes this hour was fitted to: any change from them (the strip, the header, the window)
    // fits the day again (refit).
    fitted = sizeKey();
    return true;
  }
  const nowTop = () => (minutesNow() - settings().day_start * 60) / 60 * hourPx;
  function placeNow(){
    const line = grid.querySelector('.pnow'), s = settings(), m = minutesNow();
    const on = isToday(shown) && m >= s.day_start * 60 && m <= s.day_end * 60;
    if (!on) return line?.remove();
    const el = line || grid.appendChild(Object.assign(document.createElement('div'), {className: 'pnow'}));
    el.setAttribute('aria-hidden', 'true');
    el.style.top = nowTop() + 'px';
  }

  let scrolledFor = null;        // the date the timeline was last scrolled for
  let wasShown = false;          // a planner hidden (another view) loses its place: shown again, it scrolls again
  // The whole day fits: nothing to scroll. Only a window too short for that scrolls: today, the
  // current hour near the top; another day, its first block.
  function scrollToStart(){
    const el = els.scroll;
    if (!el.clientHeight || els.time.hidden) return false;
    if (!scrolling) { el.scrollTop = 0; return true; }
    const s = settings(), lo = s.day_start * 60;
    let m;
    if (isToday(shown)) m = minutesNow() - 45;
    else {
      const first = entriesOn(shown).filter(e => !e.off && !e.skip && e.end > lo).sort((a, b) => a.start - b.start)[0];
      m = (first ? first.start : 8 * 60) - 30;
    }
    el.scrollTop = Math.max(0, (m - lo) / 60 * hourPx);
    return true;
  }

  function render(){
    if (SH.plannerState !== 'on' || drag) return;
    const key = focusKey();
    drawDate();
    els.today.hidden = isToday(shown);
    els.week.disabled = els.add.disabled = !editable();
    if (!plan) {
      els.strip.hidden = els.time.hidden = true;
      els.msg.hidden = false;
      els.msg.innerHTML = loadFailed ? `Couldn't load the plan.<br><button type="button" class="btn small" data-plan-retry="1">Try again</button>` : 'Loading the plan…';
      if (key) root.querySelector(key)?.focus();
      return;
    }
    els.msg.hidden = true;
    els.time.hidden = false;
    const s = settings(), lo = s.day_start * 60, hi = s.day_end * 60;

    // Blocks and assignment flags in time order, so a screen reader reads the day as a list.
    const entries = entriesOn(shown), showing = entries.filter(e => !e.off && !e.skip);
    const inView = showing.filter(e => e.end > lo && e.start < hi), outside = showing.filter(e => !(e.end > lo && e.start < hi));
    const timed = [], untimed = [];
    for (const a of dueOn(shown)) {
      const d = new Date(a.due_at), m = d.getHours() * 60 + d.getMinutes();
      (!a.all_day && m >= lo && m <= hi ? timed : untimed).push({a, m});
    }
    timed.sort((p, q) => p.m - q.m);

    // The strip, first: it takes room from the timeline, which measure() then shares out. Due with
    // no time (or outside the hours shown), blocks outside the hours shown, and a meal taken off or
    // a repeating block skipped this day, which can come back.
    const chips = [];
    for (const {a, m} of untimed.sort((p, q) => p.m - q.m))
      chips.push(`<button type="button" class="pchip${SH.isDone(a) ? ' done' : ''}" data-plan-due="${esc(a.id)}" aria-label="${esc(dueLabel(a, m))}" title="${esc(a.name)}">${SH.dot(a.course)}<span>${a.all_day ? 'Due' : esc(clock(m))} · ${esc(a.name)}</span></button>`);
    for (const e of outside.sort((p, q) => p.start - q.start))
      chips.push(`<button type="button" class="pchip k-${e.kind}" data-pedit="${esc(e.ref)}" aria-label="${esc(spoken(e))}"><span>${esc(e.title)} · ${esc(range(e.start, e.end))}</span></button>`);
    for (const e of entries.filter(e => e.kind === 'meal' && e.dayOff))
      chips.push(`<button type="button" class="pchip" data-pmeal-on="${e.meal}"><span>No ${e.meal} ${thisDay(shown)} · <b>Bring it back</b></span></button>`);
    for (const e of entries.filter(e => e.repeat && e.skip))
      chips.push(`<button type="button" class="pchip" data-prepeat-on="${esc(e.id)}" aria-label="${esc(`${e.title} skipped ${thisDay(shown)}: bring it back`)}"><span>${esc(e.title)} skipped ${thisDay(shown)} · <b>Bring it back</b></span></button>`);
    els.strip.innerHTML = chips.join('');
    SH.markEmoji?.(els.strip);
    els.strip.hidden = !chips.length;

    const wasScrolling = scrolling;
    measure();
    if (scrolling !== wasScrolling) scrolledFor = null;   // a window now too short: scroll to now
    const H = (s.day_end - s.day_start) * hourPx;
    const y = m => (m - lo) / 60 * hourPx, step = labelStep(hourPx);
    els.time.style.height = H + 'px';
    els.time.style.marginBottom = padBottom + 'px';
    els.scroll.classList.toggle('fit', !scrolling);
    grid.style.height = H + 'px';
    grid.style.setProperty('--hour', hourPx + 'px');
    grid.classList.toggle('dense', hourPx < DENSE_HOUR_PX);
    els.hours.innerHTML = Array.from({length: s.day_end - s.day_start + 1}, (_, i) => i).filter(i => (s.day_start + i) % step === 0)
      .map(i => `<span class="phour" style="top:${i * hourPx}px">${hourLabel(s.day_start + i)}</span>`).join('');
    grid.setAttribute('aria-label', 'Plan for ' + longDate(shown));
    grid.classList.toggle('loading', !editable());

    // A day with things due at a time keeps a lane on the right for their flags, so no flag covers a
    // block; a flag shows its time there and its name too when pointed at or focused.
    const lane = timed.length ? FLAG_LANE_PX : 0;
    grid.style.setProperty('--lane', lane + 'px');
    place(inView, lo, hi, hourPx);
    const gridW = (grid.clientWidth || 400) - lane;
    const parts = inView.map(e => ({t: e.start, html: blockHtml(e, gridW)}));
    // Flags at the same time stack instead of covering each other: downwards, and upwards from the
    // end of the day where that would run past it (most things are due at 11:59 PM).
    let prev = -Infinity;
    for (const f of timed) prev = f.top = Math.max(Math.max(11, Math.min(H - 11, y(f.m))), prev + 24);
    let limit = H - 11;
    for (const f of [...timed].reverse()) limit = (f.top = Math.min(f.top, limit)) - 24;
    for (const f of timed) parts.push({t: f.m, html: flagHtml(f.a, f.m, f.top)});
    parts.sort((p, q) => p.t - q.t);
    grid.innerHTML = parts.map(p => p.html).join('');
    SH.markEmoji?.(grid);
    placeNow();

    const onScreen = root.getClientRects().length > 0;
    if (onScreen && !wasShown) scrolledFor = null;
    wasShown = onScreen;
    if (scrolledFor !== shown && scrollToStart()) scrolledFor = shown;
    if (key) root.querySelector(key)?.focus();
    syncDetails();
  }

  // The hour's height follows the room: on resize (the window, the phone's visible area, the strip or
  // the header taking another line) and when the settings change the range (render).
  const sizeKey = () => `${els.scroll.clientHeight}:${grid.clientWidth}:${fabRoom()}`;
  function refit(){
    if (refitting) return;
    refitting = requestAnimationFrame(() => {
      refitting = 0;
      if (SH.plannerState !== 'on' || !plan || drag || sizeKey() === fitted) return;
      render();
    });
  }
  if (typeof ResizeObserver === 'function') new ResizeObserver(refit).observe(els.scroll);
  window.addEventListener('resize', refit);
  window.visualViewport?.addEventListener('resize', refit);

  function setDate(d){
    shown = d;
    if (!inRange(d)) load(d);
    render();
  }

  // The now line moves each minute.
  (function tick(){
    if (SH.plannerState === 'on' && plan && !drag) placeNow();
    setTimeout(tick, 60000 - Date.now() % 60000 + 50);
  })();

  // ---- changes from the timeline ----
  function addWork(date, entry, a){
    const undo = snapshot(['day:' + date]);
    let outcome = 'added';
    editDay(date, v => {
      const h = holder(v, entry.ref);
      if (!h) { outcome = 'gone'; return false; }
      h.items ||= [];
      if (h.items.some(i => i.kind === 'work' && i.ref === a.id)) { outcome = 'there'; return false; }
      if (h.items.length >= LIMIT.items) { outcome = 'full'; return false; }
      h.items.push(workItem(a));
    });
    if (outcome === 'added') SH.toast(`Added “${a.name}” to ${entryName(entry)}`, undo);
    else if (outcome === 'there') SH.toast(`“${a.name}” is already in ${entryName(entry)}`);
    else if (outcome === 'full') SH.toast(`${entryName(entry)} already holds ${LIMIT.items} things`);
  }
  // A new one-hour Deep work block holding an assignment, at start or as near it as the day allows.
  function newBlockWith(date, start, a){
    const s = settings(), lo = s.day_start * 60, hi = s.day_end * 60;
    const begin = Math.max(Math.min(start, hi - 60, 1380), Math.min(lo, 1380)), end = Math.min(1440, begin + 60);
    if ((plan.days[date]?.blocks || []).length >= LIMIT.blocks) return SH.toast(`This day already has ${LIMIT.blocks} blocks of its own`);
    const undo = snapshot(['day:' + date]);
    editDay(date, v => { (v.blocks ||= []).push({id: newId(), type: 'deep', title: KIND_NAME.deep, start: toTime(begin), end: toTime(end), items: [workItem(a)]}); });
    SH.toast(`Added “${a.name}” to a new Deep work block, ${range(begin, end)}`, undo);
  }
  // A block's new time from a drag. A meal's or a repeating block's changes that date only.
  function commitTime(date, entry, start, end){
    const undo = snapshot(['day:' + date]);
    editDay(date, v => {
      const h = holder(v, entry.ref);
      if (!h) return false;
      Object.assign(h, {start: toTime(start), end: toTime(end)});
    });
    if (!entry.ref.startsWith('block:')) SH.toast(`${entry.title} changed for ${thisDay(date)} only`, undo);
    else SH.toast(`Moved “${entry.title}” to ${range(start, end)}`, undo);
  }
  // The drawer's Plan it: into the next deep work block today, or a new one at the next whole hour.
  async function planIt(id){
    const a = SH.byId(id);
    if (!a) return;
    // The first load failed: say so, and try again.
    if (!plan) { SH.toast("Couldn't load the plan"); loadFailed = false; render(); return load(shown); }
    const today = todayIso();
    if (shown !== today) { shown = today; scrolledFor = null; }
    // A load waits for the saves on their way (load), so wait for them first.
    while (pending) await chain;
    if (!inRange(today)) await load(today);
    if (!editable()) return SH.toast("Couldn't load the plan");
    const now = minutesNow();
    const next = entriesOn(today).filter(e => e.kind === 'deep' && !e.skip && e.end > now).sort((x, y) => x.start - y.start)[0];
    if (next) addWork(today, next, a);
    else newBlockWith(today, Math.min(1380, Math.ceil((now + 1) / 60) * 60), a);
    render();
  }

  // ---- mouse, pen and touch on the timeline ----
  // With a mouse or a pen a drag starts at once. On a touch screen a vertical swipe scrolls the
  // timeline (the grid leaves pan-y to the browser), so a drag starts only after a touch is held
  // still for a moment; from then on the touch's moves are kept from scrolling. A tap is a click.
  // The click that follows a pointer's release is swallowed until then (a time, since a browser may
  // send none, say once the editor covers the grid).
  let drag = null, suppressUntil = 0, ghost = null;
  const suppressClick = () => { suppressUntil = performance.now() + 400; };
  const minuteAt = clientY => settings().day_start * 60 + (clientY - grid.getBoundingClientRect().top) / hourPx * 60;
  const snap = (m, round = Math.round) => round(m / SNAP) * SNAP;
  function showGhost(start, end, kind, label){
    const s = settings(), y = m => (m - s.day_start * 60) / 60 * hourPx;
    if (!ghost) {
      ghost = document.createElement('div');
      ghost.setAttribute('aria-hidden', 'true');
    }
    ghost.className = `pblock k-${kind} ghost`;
    Object.assign(ghost.style, {top: y(start) + 'px', height: Math.max(MIN_BLOCK_PX, y(end) - y(start) - 2) + 'px', left: '2px', width: 'calc(100% - var(--lane, 0px) - 4px)'});
    ghost.innerHTML = `<div class="pb-body"><div class="pb-head"><span class="pb-title">${esc(label)}</span></div><span class="pb-time">${esc(range(start, end))}</span></div>`;
    SH.markEmoji?.(ghost);
    if (!ghost.isConnected) grid.append(ghost);
  }
  const hideGhost = () => ghost?.remove();

  function update(){
    const d = drag, s = settings(), lo = s.day_start * 60, hi = s.day_end * 60, m = minuteAt(d.lastY);
    if (d.mode === 'create') {
      const a = d.anchor;
      let start, end;
      if (m >= a) { start = snap(a, Math.floor); end = Math.max(start + SNAP, snap(m, Math.ceil)); }
      else { start = snap(m, Math.floor); end = Math.max(start + SNAP, snap(a, Math.ceil)); }
      d.start = Math.max(lo, start);
      d.end = Math.min(hi, end);
      if (d.end - d.start < MIN_LEN) d.start = d.end - MIN_LEN;
      return showGhost(d.start, d.end, 'deep', KIND_NAME.deep);
    }
    const e = d.entry;
    // By the pointer's change since the press, as a handle or a block may be drawn away from its
    // times (MIN_BLOCK_PX, a block moved up to end with the day, one cut at the hours shown). Only
    // the change is kept within the hours, so a block running past them moves only into them.
    const delta = m - d.anchor;
    if (d.mode === 'move') {
      const change = Math.max(Math.min(0, lo - e.start), Math.min(Math.max(0, hi - e.end), snap(e.start + delta) - e.start));
      d.start = e.start + change;
      d.end = e.end + change;
    } else if (d.mode === 'top') {
      d.start = Math.max(Math.min(lo, e.start), Math.min(e.end - MIN_LEN, snap(e.start + delta)));
      d.end = e.end;
    } else {
      d.end = Math.min(Math.max(hi, e.end), Math.max(e.start + MIN_LEN, snap(e.end + delta)));
      d.start = e.start;
    }
    const y = v => (v - lo) / 60 * hourPx, H = (hi - lo) / 60 * hourPx;
    const h = Math.max(MIN_BLOCK_PX, y(d.end) - y(d.start) - 2);
    d.el.classList.add('dragging');
    d.el.style.top = Math.max(0, Math.min(y(d.start), H - h)) + 'px';
    d.el.style.height = h + 'px';
    const time = d.el.querySelector('.pb-time');
    if (time) time.textContent = time.dataset.short ? '· ' + shortRange(d.start, d.end) : range(d.start, d.end);
  }
  // Near the top or bottom edge, the timeline scrolls under the drag.
  function edgeScroll(clientY){
    const r = els.scroll.getBoundingClientRect(), zone = 36;
    const v = clientY < r.top + zone ? -(r.top + zone - clientY) : clientY > r.bottom - zone ? clientY - (r.bottom - zone) : 0;
    drag.vy = Math.max(-14, Math.min(14, Math.round(v / 3)));
    if (drag.vy && !drag.raf) drag.raf = requestAnimationFrame(stepScroll);
  }
  function stepScroll(){
    if (!drag || !drag.vy) { if (drag) drag.raf = 0; return; }
    els.scroll.scrollTop += drag.vy;
    update();
    drag.raf = requestAnimationFrame(stepScroll);
  }
  function arm(){
    if (!drag) return;
    drag.armed = true;
    try { grid.setPointerCapture(drag.id); } catch {}
    if (drag.el) drag.el.classList.add('armed');
    else { drag.lastY = drag.y; drag.moved = true; update(); }
  }
  // Ends a drag. cancelled: put everything back as it was (Esc, or the browser took the pointer).
  function endDrag(cancelled){
    const d = drag;
    if (!d) return;
    clearTimeout(d.timer);
    if (d.raf) cancelAnimationFrame(d.raf);
    try { if (grid.hasPointerCapture(d.id)) grid.releasePointerCapture(d.id); } catch {}
    hideGhost();
    drag = null;
    if (cancelled) render();
  }
  grid.addEventListener('pointerdown', e => {
    if (drag || !editable() || (e.pointerType === 'mouse' && e.button !== 0)) return;
    if (e.target.closest('.pb-item, .pflag-wrap')) return;
    const el = e.target.closest('.pblock:not(.ghost)');
    const entry = el ? entryByRef(el.dataset.ref) : null;
    if (el && !entry) return;
    const touch = e.pointerType === 'touch';
    drag = {mode: entry ? e.target.closest('.pb-rs')?.dataset.edge || 'move' : 'create', id: e.pointerId, x: e.clientX, y: e.clientY,
      lastY: e.clientY, entry, el, touch, armed: !touch, moved: false, anchor: minuteAt(e.clientY), vy: 0, raf: 0};
    if (touch) drag.timer = setTimeout(arm, LONG_PRESS_MS);
    else {
      try { grid.setPointerCapture(e.pointerId); } catch {}
      e.preventDefault();  // no text selection while dragging
    }
  });
  grid.addEventListener('pointermove', e => {
    if (!drag || e.pointerId !== drag.id) return;
    const moved = Math.hypot(e.clientX - drag.x, e.clientY - drag.y);
    if (!drag.armed) { if (moved > TOUCH_SLOP) endDrag(false); return; }
    drag.lastY = e.clientY;
    if (!drag.moved && moved < CLICK_PX) return;
    drag.moved = true;
    edgeScroll(e.clientY);
    update();
  });
  grid.addEventListener('pointerup', e => {
    if (!drag || e.pointerId !== drag.id) return;
    const d = drag;
    if (d.mode === 'create') {
      // A plain click (or tap) makes a one-hour block there; a drag, the block drawn. Either opens
      // the editor, where the kind is chosen.
      const click = !d.moved;
      endDrag(false);
      if (!d.armed && !d.touch) return;
      let start = d.start, end = d.end;
      if (click) {
        const s = settings();
        start = Math.max(s.day_start * 60, Math.min(s.day_end * 60 - 60, snap(d.anchor, Math.floor)));
        end = start + 60;
      }
      suppressClick();
      return openEditor(shown, null, {start, end});
    }
    endDrag(false);
    // A click opens the block's details here rather than through its button: while the grid holds
    // the pointer, the browser sends the click to the grid. The keyboard's click still reaches it.
    suppressClick();
    if (!d.moved) return openDetails(d.entry, d.el);
    if (d.start !== d.entry.start || d.end !== d.entry.end) commitTime(shown, d.entry, d.start, d.end);
    else render();
  });
  grid.addEventListener('pointercancel', e => { if (drag && e.pointerId === drag.id) endDrag(true); });
  grid.addEventListener('touchmove', e => { if (drag?.armed) e.preventDefault(); }, {passive: false});
  grid.addEventListener('contextmenu', e => { if (drag) e.preventDefault(); });
  // The click that ends a drag does nothing more.
  grid.addEventListener('click', e => {
    if (performance.now() > suppressUntil) return;
    suppressUntil = 0;
    e.preventDefault();
    e.stopPropagation();
  }, true);
  grid.addEventListener('change', e => {
    const box = e.target.closest('[data-pitem]');
    const ref = box?.closest('.pblock')?.dataset.ref;
    if (!ref || !editable()) return;
    editDay(shown, v => {
      const it = holder(v, ref)?.items?.find(i => i.id === box.dataset.pitem);
      if (!it) return false;
      it.done = box.checked;
    });
  });

  // ---- dragging work in from the list ----
  const hasItem = e => [...(e.dataTransfer?.types || [])].includes(ITEM_TYPE);
  let dropHit = null;
  function setDropHit(el){
    if (dropHit === el) return;
    dropHit?.classList.remove('drop-hit');
    dropHit = el;
    el?.classList.add('drop-hit');
  }
  const clearDrop = () => { setDropHit(null); hideGhost(); };
  // An hour from where it is dropped, kept within the day.
  function dropStart(m){
    const s = settings();
    return Math.max(s.day_start * 60, Math.min(s.day_end * 60 - 60, snap(m, Math.floor)));
  }
  document.addEventListener('dragstart', e => {
    const row = e.target.closest?.('.row[draggable="true"]');
    const a = row && SH.byId(row.dataset.id);
    if (!a) return;
    e.dataTransfer.setData(ITEM_TYPE, a.id);
    e.dataTransfer.setData('text/plain', a.name);
    e.dataTransfer.effectAllowed = 'copy';
    row.classList.add('drag-src');
  });
  document.addEventListener('dragend', e => { e.target.closest?.('.row')?.classList.remove('drag-src'); clearDrop(); });
  grid.addEventListener('dragover', e => {
    if (!hasItem(e) || !editable()) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    const el = e.target.closest('.pblock:not(.ghost)');
    if (el) { setDropHit(el); hideGhost(); return; }
    setDropHit(null);
    const start = dropStart(minuteAt(e.clientY));
    showGhost(start, start + 60, 'deep', 'New Deep work block');
  });
  grid.addEventListener('dragleave', e => { if (!grid.contains(e.relatedTarget)) clearDrop(); });
  grid.addEventListener('drop', e => {
    if (!hasItem(e) || !editable()) return;
    e.preventDefault();
    const a = SH.byId(e.dataTransfer.getData(ITEM_TYPE)), el = e.target.closest('.pblock:not(.ghost)'), m = minuteAt(e.clientY);
    clearDrop();
    if (!a) return;
    const entry = el && entryByRef(el.dataset.ref);
    if (entry) addWork(shown, entry, a);
    else newBlockWith(shown, dropStart(m), a);
  });

  // ---- the planner's buttons ----
  function newBlockAt(){
    const s = settings(), lo = s.day_start * 60, hi = s.day_end * 60;
    const want = isToday(shown) ? Math.ceil((minutesNow() + 1) / 60) * 60 : 9 * 60;
    const start = Math.max(lo, Math.min(hi - 60, want));
    openEditor(shown, null, {start, end: start + 60});
  }
  root.addEventListener('click', e => {
    const t = e.target;
    const step = t.closest('[data-pstep]');
    if (step) return setDate(addDays(shown, +step.dataset.pstep));
    if (t.closest('#planToday')) { scrolledFor = null; return setDate(todayIso()); }
    if (t.closest('#planWeek')) return openWeek();
    if (t.closest('#planAdd')) return newBlockAt();
    if (t.closest('[data-plan-retry]')) { loadFailed = false; render(); return load(shown); }
    const open = t.closest('.pb-open, [data-pedit]');
    if (open) {
      const entry = entryByRef(open.dataset.openRef || open.dataset.pedit);
      return entry && openDetails(entry, open.closest('.pblock') || open);
    }
    const due = t.closest('[data-plan-due]');
    if (due) return SH.openDrawer(due.dataset.planDue, e.detail === 0);
    const back = t.closest('[data-pmeal-on]');
    if (back && editable()) {
      const m = back.dataset.pmealOn, undo = snapshot(['day:' + shown]);
      editDay(shown, v => { holder(v, 'meal:' + m).off = false; });
      SH.toast(`${MEAL_NAME[m]} is back ${onDay(shown)}`, undo);
      return refocus(refSel('meal:' + m));
    }
    // A repeating block skipped this day comes back (its skip goes; cleanDay drops what is left empty).
    const again = t.closest('[data-prepeat-on]');
    if (again && editable()) {
      const ref = 'repeat:' + again.dataset.prepeatOn, e = entryByRef(ref), undo = snapshot(['day:' + shown]);
      editDay(shown, v => { delete holder(v, ref).skip; });
      SH.toast(`“${e?.title || 'The block'}” is back ${onDay(shown)}`, undo);
      return refocus(refSel(ref));
    }
  });
  // The drawer's Plan it.
  document.addEventListener('click', e => {
    const b = e.target.closest?.('[data-plan-it]');
    if (b) { e.preventDefault(); planIt(b.dataset.planIt); }
  });
  // [ and ] for the day before and after, when not typing and nothing covers the planner. Esc puts
  // a drag back.
  document.addEventListener('keydown', e => {
    if (drag && e.key === 'Escape') { e.preventDefault(); return endDrag(true); }
    if (det && e.key === 'Escape' && !card.matches(':modal') && !SH.drawerOpen()) { e.preventDefault(); return closeDetails(); }
    if ((e.key !== '[' && e.key !== ']') || e.metaKey || e.ctrlKey || e.altKey) return;
    if (SH.typingIn(document.activeElement) || document.querySelector('dialog[open]') || SH.drawerOpen()) return;
    if (SH.plannerState !== 'on' || !root.getClientRects().length) return;
    e.preventDefault();
    setDate(addDays(shown, e.key === '[' ? -1 : 1));
  });

  // ---- the block editor ----
  const F = Object.fromEntries(['blockDialog', 'blockForm', 'bHeading', 'bKindField', 'bKind', 'bKindFixed', 'bTitleField', 'bTitle', 'bStart', 'bEnd',
    'bChanged', 'bChangedText', 'bUseWeek', 'bRepeatField', 'bRepeat', 'bRepeatText', 'bUnrepeat', 'bUnrepeatText', 'bSkipText', 'bRemoveText',
    'bPlaceField', 'bPlace', 'bPlaceHint', 'bPlaceWeek', 'bItems', 'bNewItem', 'bPick', 'bPicker', 'bErr', 'bDelete', 'bCancel',
    'weekDialog', 'weekForm', 'wDays', 'wBlocks', 'wStart', 'wEnd', 'wErr', 'wCancel'].map(id => [id, document.getElementById(id)]));
  let ed = null;   // the block being edited: {date, ref (null for a new one), kind, meal, repeat, items, back}

  function showErr(el, msg, focus){
    el.textContent = msg;
    el.hidden = !msg;
    focus?.focus();
    return false;
  }
  // init, for a new block: {start, end, items}.
  function openEditor(date, entry, init = {}){
    if (!editable() || !F.blockDialog) return;
    const e = entry || {ref: null, kind: 'deep', title: KIND_NAME.deep, start: init.start, end: init.end, items: init.items || []};
    const meal = e.kind === 'meal', wdN = wdName(date);
    // back: where focus goes when the editor closes (the block, once it is drawn anew).
    ed = {date, ref: e.ref, kind: e.kind, meal: e.meal, repeat: !!e.repeat, title: e.title, items: clone(e.items) || [], back: e.ref ? refSel(e.ref) : focusKey()};
    F.bHeading.textContent = !e.ref ? 'New block' : meal ? MEAL_NAME[e.meal] : 'Edit block';
    F.bKindField.hidden = meal;
    F.bKindFixed.hidden = !meal;
    F.bKind.value = meal ? 'deep' : e.kind;
    F.bTitleField.hidden = meal;
    // A title that is only the kind's name is left empty, so it follows the kind chosen.
    F.bTitle.value = meal || e.title === KIND_NAME[e.kind] ? '' : e.title;
    F.bTitle.placeholder = KIND_NAME[F.bKind.value];
    F.bStart.value = timeValue(e.start);
    F.bEnd.value = timeValue(e.end);
    F.bChanged.hidden = !e.changed;
    F.bChangedText.textContent = `Changed for ${thisDay(date)} only.`;
    F.bUseWeek.textContent = `Use this time every ${wdN}`;
    F.bRepeatField.hidden = meal;
    F.bRepeat.checked = ed.repeat;
    F.bRepeatText.textContent = `Repeat every ${wdN}`;
    F.bUnrepeat.hidden = true;
    F.bUnrepeatText.textContent = `It repeats every ${wdN}. Instead:`;
    F.bSkipText.textContent = `Only skip it ${thisDay(date)}`;
    F.bRemoveText.textContent = `Remove it from every ${wdN}`;
    F.blockForm.querySelector('input[name="bUnrep"][value="skip"]').checked = true;
    F.bPlaceField.hidden = !meal;
    F.bPlace.value = meal ? e.place : '';
    F.bPlaceHint.textContent = `For ${thisDay(date)} only.`;
    F.bPlaceWeek.textContent = `Change it for every ${wdN}`;
    F.bDelete.hidden = !e.ref;
    F.bDelete.textContent = removeLabel(e, date);
    F.bNewItem.value = '';
    togglePicker(false);
    showErr(F.bErr, '');
    edItems();
    F.blockDialog.showModal();
    (!e.ref ? F.bKind : meal ? F.bPlace : F.bTitle).focus();
  }
  function edItems(){
    F.bItems.innerHTML = ed.items.map(it => `<li class="b-item${it.done ? ' done' : ''}">
        <label class="pin-check"><input type="checkbox" data-ed-done="${esc(it.id)}"${it.done ? ' checked' : ''}> <span class="txt"><span>${esc(it.text)}</span>${it.kind === 'work' && it.course ? `<small>${esc(it.course)}</small>` : ''}${listDone(it) ? '<small class="b-done">done</small>' : ''}</span></label>
        <button type="button" class="b-rm" data-ed-rm="${esc(it.id)}" aria-label="Remove ${esc(it.text)}" title="Remove">×</button></li>`).join('')
      || '<li class="b-none">Nothing yet. Add a to-do, pick from your list, or drag an assignment onto the block.</li>';
    SH.markEmoji?.(F.bItems);
    if (!F.bPicker.hidden) pickerList();
  }
  function togglePicker(on){
    F.bPicker.hidden = !on;
    F.bPick.setAttribute('aria-expanded', String(on));
    if (on) pickerList();
  }
  // Open assignments and tasks by due date, leaving out those already in the block.
  function pickerList(){
    const there = new Set(ed.items.filter(i => i.kind === 'work').map(i => i.ref));
    const list = openItems().filter(a => !there.has(a.id));
    F.bPicker.innerHTML = list.map(a => `<button type="button" class="b-pick" data-ed-pick="${esc(a.id)}">${SH.dot(a.course)}<span class="nm">${esc(a.name)}</span><span class="dd">${esc(a.course?.short || a.course?.name || '')} · ${esc(SH.fmtDue(a.due_at, false, a.all_day))}</span></button>`).join('')
      || '<p class="b-none" style="margin:0;padding:10px">No open assignments or tasks to add.</p>';
    SH.markEmoji?.(F.bPicker);
  }
  function addEdItem(item){
    if (ed.items.length >= LIMIT.items) return showErr(F.bErr, `A block holds at most ${LIMIT.items} things.`);
    ed.items.push(item);
    showErr(F.bErr, '');
    edItems();
    return true;
  }

  // Saves the editor; false when something must be fixed first.
  function saveEditor(){
    const start = readTime(F.bStart, false), end = readTime(F.bEnd, true);
    const bad = spanError(start, end);
    if (bad) return showErr(F.bErr, bad, F.bEnd);
    const {date, ref, items} = ed, wd = wdOf(date), wdN = wdName(date), day = plan.days[date] || {};
    const times = {start: toTime(start), end: toTime(end)};
    if (ed.kind === 'meal') {
      editDay(date, v => { Object.assign(holder(v, ref), times, {place: cut(F.bPlace.value, LIMIT.place), items}); });
      return closeEditor(refSel(ref));
    }
    const type = F.bKind.value, title = cut(F.bTitle.value, LIMIT.title) || KIND_NAME[type], repeat = F.bRepeat.checked;
    let back = refSel(ref);
    const weekFull = () => weekOf(wd).blocks.length >= LIMIT.blocks && showErr(F.bErr, `${wdN} already has ${LIMIT.blocks} repeating blocks.`) === false;
    const dayFull = () => (day.blocks || []).length >= LIMIT.blocks && showErr(F.bErr, `This day already has ${LIMIT.blocks} blocks of its own.`) === false;
    if (!ref) {
      const id = newId();
      if (repeat) {
        if (weekFull()) return false;
        // The week first: the date's items for it are kept only once the block is in the week.
        editWeek(wd, w => { w.blocks.push({id, type, title, ...times}); });
        if (items.length) editDay(date, v => { (v.repeats ||= {})[id] = {items}; });
        back = refSel('repeat:' + id);
      } else {
        if (dayFull()) return false;
        editDay(date, v => { (v.blocks ||= []).push({id, type, title, ...times, items}); });
        back = refSel('block:' + id);
      }
    } else if (ref.startsWith('block:')) {
      const id = ref.slice(6);
      if (repeat) {
        // Ticking Repeat moves a one-off block into the week, keeping this date's items.
        if (weekFull()) return false;
        editWeek(wd, w => { w.blocks.push({id, type, title, ...times}); });
        editDay(date, v => {
          v.blocks = (v.blocks || []).filter(b => b.id !== id);
          if (items.length) (v.repeats ||= {})[id] = {items};
        });
        SH.toast(`“${title}” repeats every ${wdN} now`);
        back = refSel('repeat:' + id);
      } else {
        editDay(date, v => { const b = holder(v, ref); if (!b) return false; Object.assign(b, {type, title, ...times, items}); });
      }
    } else {
      const id = ref.slice(7);
      if (!repeat) {
        const undo = snapshot(['week:' + wd, 'day:' + date]);
        back = neighbourSel(ref);
        if (F.blockForm.querySelector('input[name="bUnrep"]:checked')?.value === 'remove') {
          editWeek(wd, w => { w.blocks = w.blocks.filter(b => b.id !== id); });
          editDay(date, () => {});  // drops this date's changes to it
          SH.toast(`Removed “${title}” from every ${wdN}`, undo);
        } else {
          editDay(date, v => { Object.assign(holder(v, ref), {skip: true, items}); });
          SH.toast(`Skipped “${title}” ${onDay(date)}`, undo);
        }
      } else {
        // The kind and title belong to the week; the time set here and the items, to this date.
        const wb = weekOf(wd).blocks.find(b => b.id === id);
        if (wb && (wb.type !== type || wb.title !== title))
          editWeek(wd, w => { Object.assign(w.blocks.find(b => b.id === id), {type, title}); });
        editDay(date, v => { Object.assign(holder(v, ref), times, {items}); });
      }
    }
    return closeEditor(back);
  }
  // Closes the editor with focus on back (the block saved, drawn anew), not left on <body>: the
  // dialog would give it back to the block's old button, which the save's redraw replaced.
  function closeEditor(back){
    ed.back = back;
    F.blockDialog.close();
    refocus(back);
    return true;
  }
  // Delete for a one-off block, skip this date for a repeating one, "No lunch today" for a meal; each
  // with the toast's Undo. From the editor or the details.
  const removeLabel = (e, date) => e.kind === 'meal' ? `No ${e.meal} ${thisDay(date)}` : e.repeat ? `Skip ${thisDay(date)}` : 'Delete';
  function removeEntry(date, e){
    const {ref} = e, putBack = snapshot(['day:' + date]);
    // Undo puts the block back and focus on it (the toast's button goes with the toast).
    const undo = () => { putBack(); if (focusLost()) refocus(refSel(ref)); };
    const name = e.kind === 'meal' ? MEAL_NAME[e.meal] : e.title;
    if (ref.startsWith('block:')) {
      editDay(date, v => { v.blocks = (v.blocks || []).filter(b => 'block:' + b.id !== ref); });
      SH.toast(`Deleted “${name}”`, undo);
    } else if (ref.startsWith('repeat:')) {
      editDay(date, v => { holder(v, ref).skip = true; });
      SH.toast(`Skipped “${name}” ${onDay(date)}`, undo);
    } else {
      editDay(date, v => { holder(v, ref).off = true; });
      SH.toast(`No ${e.meal} ${onDay(date)}`, undo);
    }
  }
  function deleteFromEditor(){
    const back = neighbourSel(ed.ref);
    removeEntry(ed.date, ed);
    closeEditor(back);
  }
  // "Use this time every Sunday": the time in the editor goes into the week, and this date's own
  // time goes, at once.
  function useForWeek(){
    const start = readTime(F.bStart, false), end = readTime(F.bEnd, true);
    const bad = spanError(start, end);
    if (bad) return showErr(F.bErr, bad, F.bEnd);
    const {date, ref} = ed, wd = wdOf(date), undo = snapshot(['week:' + wd, 'day:' + date]);
    editWeek(wd, w => {
      const t = ed.kind === 'meal' ? w.meals[ed.meal] : w.blocks.find(b => 'repeat:' + b.id === ref);
      if (!t) return false;
      Object.assign(t, {start: toTime(start), end: toTime(end)});
    });
    editDay(date, v => { const h = holder(v, ref); delete h.start; delete h.end; });
    // The button goes with the note: focus stays in the dialog, on the start time.
    F.bChanged.hidden = true;
    F.bStart.focus();
    showErr(F.bErr, '');
    SH.toast(`${ed.kind === 'meal' ? MEAL_NAME[ed.meal] : ed.title} is ${range(start, end)} every ${wdName(date)} now`, undo);
  }
  if (F.blockDialog) {
    F.blockForm.addEventListener('submit', e => { e.preventDefault(); saveEditor(); });
    F.bCancel.onclick = () => F.blockDialog.close();
    F.blockDialog.addEventListener('click', e => { if (e.target === F.blockDialog) F.blockDialog.close(); });
    // However it closed, focus is not left on <body> (a redraw meanwhile may have replaced the block):
    // focus still in the closed dialog falls to <body> once the page is next drawn.
    F.blockDialog.addEventListener('close', () => { if (focusLost() || F.blockDialog.contains(document.activeElement)) refocus(ed?.back); });
    F.bDelete.onclick = deleteFromEditor;
    F.bUseWeek.onclick = useForWeek;
    F.bKind.onchange = () => { F.bTitle.placeholder = KIND_NAME[F.bKind.value]; };
    F.bRepeat.onchange = () => { F.bUnrepeat.hidden = !(ed.repeat && !F.bRepeat.checked); };
    F.bPlaceWeek.onclick = () => { const m = ed.meal, wd = wdOf(ed.date); if (saveEditor()) openWeek(`wk-${wd}-${m}-place`); };
    F.bPick.onclick = () => togglePicker(F.bPicker.hidden);
    F.bNewItem.addEventListener('keydown', e => {
      if (e.key !== 'Enter' || e.isComposing) return;
      e.preventDefault();
      const text = cut(F.bNewItem.value, LIMIT.text);
      if (text && addEdItem({id: newId(), kind: 'own', text, done: false})) F.bNewItem.value = '';
    });
    F.blockDialog.addEventListener('click', e => {
      const rm = e.target.closest('[data-ed-rm]');
      if (rm) {
        const at = ed.items.findIndex(i => i.id === rm.dataset.edRm);
        ed.items.splice(at, 1);
        edItems();
        // Focus stays in the list: on the next item's remove button, else the to-do input.
        (F.bItems.querySelectorAll('[data-ed-rm]')[at] || F.bItems.querySelector('[data-ed-rm]:last-of-type') || F.bNewItem).focus();
        return;
      }
      const pick = e.target.closest('[data-ed-pick]');
      if (pick) {
        const a = SH.byId(pick.dataset.edPick), next = pick.nextElementSibling?.dataset.edPick;
        if (a && addEdItem(workItem(a))) (next && F.bPicker.querySelector(`[data-ed-pick="${CSS.escape(next)}"]`) || F.bPick).focus();
      }
    });
    F.bItems.addEventListener('change', e => {
      const box = e.target.closest('[data-ed-done]'), it = box && ed.items.find(i => i.id === box.dataset.edDone);
      if (!it) return;
      it.done = box.checked;
      box.closest('.b-item').classList.toggle('done', it.done);
    });
  }

  // ---- a block's details ----
  // Clicking a block (or its chip in the strip) shows what it holds: a card beside it on wide screens,
  // a bottom sheet on narrow ones. Edit opens the block editor. Esc and a click outside close it, and
  // focus goes back to the block.
  const card = document.getElementById('planDetail');
  const SHEET = matchMedia('(max-width: 780px)');
  let det = null;                // {ref, back: the selector of the block's button or chip}
  let closedAt = null;           // {ref, t}: a click outside closed it, so the same click does not reopen it

  // A work item's assignment as the list has it: "Done", "Overdue", "Due today", "Due in 2 days".
  function workStatus(a){
    if (SH.isDone(a)) return ['Done', 'good'];
    if (!a.due_at) return ['No due date', ''];
    const due = new Date(a.due_at), today = fromIso(todayIso());
    const days = Math.round((new Date(due.getFullYear(), due.getMonth(), due.getDate()) - today) / 864e5);
    if (days < 0 || (!a.all_day && due < new Date())) return ['Overdue', 'bad'];
    return [days === 0 ? 'Due today' : days === 1 ? 'Due tomorrow' : `Due in ${days} days`, days <= 1 ? 'warn' : ''];
  }
  function detailItem(it, can){
    const a = it.kind === 'work' ? SH.byId(it.ref) : null;
    let work = '';
    if (it.kind === 'work') {
      if (a) {
        const [st, cls] = workStatus(a);
        work = `<div class="pd-work">${SH.dot(a.course)}<span>${esc(a.course?.name || a.course?.short || it.course)}</span>`
          + `<span>${a.due_at ? 'Due ' + esc(SH.fmtDue(a.due_at, true, a.all_day)) : 'No due date'}</span>`
          + `<span class="pd-st ${cls}">${esc(st)}</span>`
          + `<button type="button" class="linkish" data-pd-open="${esc(a.id)}" aria-label="Open ${esc(a.name)}">Open</button></div>`;
      } else {
        work = `<div class="pd-work">${it.course ? `<span>${esc(it.course)}</span>` : ''}<span>No longer in your list</span></div>`;
      }
    }
    return `<li class="pd-item${it.done ? ' done' : ''}"><label class="pd-check"><input type="checkbox" data-pd-item="${esc(it.id)}"${it.done ? ' checked' : ''}${can ? '' : ' disabled'}>`
      + `<span class="pd-text">${esc(a ? a.name : it.text)}</span></label>${work}</li>`;
  }
  function fillDetails(e){
    const meal = e.kind === 'meal', wdN = wdName(shown), can = editable();
    const notes = [];
    if (e.repeat) notes.push(`Repeats every ${wdN}`);
    if (e.changed) notes.push(`${e.repeat ? 'changed' : 'Changed'} for ${thisDay(shown)} only`);
    else if (meal && e.placeChanged) notes.push(`Place changed for ${thisDay(shown)} only`);
    else if (meal) notes.push(`Same every ${wdN}`);
    const s = settings();
    const lo = s.day_start * 60, hi = s.day_end * 60;
    if (e.end <= lo || e.start >= hi) notes.push('Outside the hours shown');
    else if (e.start < lo || e.end > hi) notes.push('Runs past the hours shown');
    const items = e.items.map(it => detailItem(it, can)).join('');
    // Keeps the focused control across a redraw (a box ticked here redraws the planner and the card).
    const el = document.activeElement, keep = card.contains(el) && el !== card
      ? ['data-pd-item', 'data-pd-open', 'data-pd-edit', 'data-pd-del', 'data-pd-close'].find(k => el.hasAttribute(k)) : null;
    const keepSel = keep && `[${keep}="${CSS.escape(el.getAttribute(keep))}"]`;
    card.className = 'pdetail' + (SHEET.matches ? ' sheet' : '');
    card.innerHTML = `<button type="button" class="close" data-pd-close="x" aria-label="Close">×</button>
      <div class="pd-kind k-${e.kind}"><i aria-hidden="true"></i>${meal ? 'Meal' : KIND_NAME[e.kind]}</div>
      <h3 id="pdTitle">${esc(e.title)}</h3>
      <p class="pd-line pd-time">${esc(range(e.start, e.end))} · ${esc(duration(e.end - e.start))}</p>
      ${meal ? `<p class="pd-line">${e.place ? 'At ' + esc(e.place) : 'No place set'}</p>` : ''}
      ${notes.length ? `<p class="pd-line pd-note">${esc(notes.join(' · '))}</p>` : ''}
      <div class="pd-sec" id="pdItems">Things to get done</div>
      ${items ? `<ul class="pd-items" aria-labelledby="pdItems">${items}</ul>` : '<p class="pd-none">Nothing yet. Edit the block to add a to-do or something from your list.</p>'}
      <div class="pd-buttons">
        <button type="button" class="btn small danger" data-pd-del="1"${can ? '' : ' disabled'}>${esc(removeLabel(e, shown))}</button><span class="grow"></span>
        <button type="button" class="btn small" data-pd-close="1">Close</button>
        <button type="button" class="btn small primary" data-pd-edit="1"${can ? '' : ' disabled'}>Edit</button>
      </div>`;
    SH.markEmoji?.(card);
    if (keepSel) card.querySelector(keepSel)?.focus();
  }
  // Beside the block where there is room (left of it first: the planner is on the right), else
  // under or over it, always wholly on screen. On a narrow screen, a sheet at the bottom (CSS).
  function placeDetails(anchor){
    card.style.left = card.style.top = '';
    if (SHEET.matches || !anchor?.isConnected) return;
    const r = anchor.getBoundingClientRect(), vw = document.documentElement.clientWidth, vh = window.innerHeight, m = 8, gap = 8;
    const w = card.offsetWidth, h = card.offsetHeight, clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
    let left, top;
    if (r.left - gap - w >= m) left = r.left - gap - w;
    else if (r.right + gap + w <= vw - m) left = r.right + gap;
    if (left != null) top = clamp(r.top, m, vh - m - h);
    else {
      left = clamp(r.left, m, vw - m - w);
      top = r.bottom + gap + h <= vh - m ? r.bottom + gap : r.top - gap - h >= m ? r.top - gap - h : clamp(vh - m - h, m, vh);
    }
    card.style.left = Math.round(left) + 'px';
    card.style.top = Math.round(top) + 'px';
  }
  // The block whose details are open is outlined.
  const markShown = () => grid.querySelectorAll('.pblock[data-ref]').forEach(el => el.classList.toggle('shown', det?.ref === el.dataset.ref));
  const anchorOf = () => det && root.querySelector(det.back)?.closest('.pblock, .pchip');
  function openDetails(entry, anchor){
    if (!card) return openEditor(shown, entry);
    if (closedAt?.ref === entry.ref && performance.now() - closedAt.t < 400) { closedAt = null; return; }
    if (det) closeDetails(false);
    const chip = anchor?.matches?.('.pchip');
    det = {ref: entry.ref, back: chip ? `[data-pedit="${CSS.escape(entry.ref)}"]` : `[data-open-ref="${CSS.escape(entry.ref)}"]`};
    fillDetails(entry);
    markShown();
    if (SHEET.matches) card.showModal(); else card.show();
    placeDetails(anchor);
    card.focus();
  }
  function closeDetails(restore = true){
    if (!det) return;
    const back = det.back;
    det = null;
    markShown();
    if (card.open) card.close();
    if (restore) root.querySelector(back)?.focus();
  }
  // Called after every render: the card follows the plan (an item ticked, the block moved or gone).
  function syncDetails(){
    if (!det) return;
    const e = entryByRef(det.ref);
    if (!e || e.off || e.skip) return closeDetails(false);
    fillDetails(e);
    placeDetails(anchorOf());
  }
  if (card) {
    card.tabIndex = -1;
    // The sheet's Esc, and a click on its backdrop.
    card.addEventListener('cancel', e => { e.preventDefault(); closeDetails(); });
    card.addEventListener('click', e => {
      const t = e.target;
      if (t === card) {
        // The click that follows the tap which opened the sheet lands on its backdrop (a tap holds no
        // pointer capture): it does not close it again.
        if (performance.now() <= suppressUntil) { suppressUntil = 0; return; }
        const r = card.getBoundingClientRect();
        if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) closeDetails();
        return;
      }
      if (t.closest('[data-pd-close]')) return closeDetails();
      const entry = det && entryByRef(det.ref);
      if (!entry) return;
      if (t.closest('[data-pd-edit]')) { closeDetails(); return openEditor(shown, entry); }
      if (t.closest('[data-pd-del]')) {
        // Focus goes on to the next block, as this one goes.
        const back = neighbourSel(entry.ref);
        closeDetails(false);
        removeEntry(shown, entry);
        return refocus(back);
      }
      const open = t.closest('[data-pd-open]');
      if (open) {
        // The drawer's focus goes back to the block when it closes.
        closeDetails();
        SH.openDrawer(open.dataset.pdOpen, e.detail === 0);
      }
    });
    card.addEventListener('change', e => {
      const box = e.target.closest('[data-pd-item]');
      if (!box || !det || !editable()) return;
      const ref = det.ref;
      editDay(shown, v => {
        const it = holder(v, ref)?.items?.find(i => i.id === box.dataset.pdItem);
        if (!it) return false;
        it.done = box.checked;
      });
    });
    // A press anywhere outside the card closes it (on the block it came from too, which then stays
    // closed rather than opening again on release).
    document.addEventListener('pointerdown', e => {
      if (!det || card.matches(':modal') || card.contains(e.target)) return;
      const hit = e.target.closest?.('[data-ref], [data-pedit]'), ref = hit && (hit.dataset.ref || hit.dataset.pedit);
      closedAt = {ref: ref === det.ref ? ref : null, t: performance.now()};
      closeDetails(false);
    }, true);
    // The card beside a block is not modal: focus moving out of it (Tab, the drawer, another dialog)
    // closes it, so it never floats over what has focus.
    document.addEventListener('focusin', e => {
      if (det && !card.matches(':modal') && !card.contains(e.target)) closeDetails(false);
    });
    // It stays beside the block when the page or a timeline too short for the day scrolls.
    const follow = () => { if (det) placeDetails(anchorOf()); };
    window.addEventListener('resize', follow);
    window.addEventListener('scroll', follow, true);
    SHEET.addEventListener?.('change', () => closeDetails(false));
  }

  // ---- the weekly form ----
  let wk = null;   // {weeks: {sun: …}, removed: Set of "wd:id", back: where focus goes on close}
  function mealCell(wd, i, m){
    const v = wk.weeks[wd].meals[m], base = `wk-${wd}-${m}`, nm = `${WD_NAME[i]} ${m}`;
    return `<div class="wk-meal${v.off ? ' off' : ''}">
        <span class="wk-meal-name" aria-hidden="true">${MEAL_NAME[m]}</span>
        <div class="wk-line"><input class="wk-place" id="${base}-place" maxlength="120" placeholder="Place" aria-label="${nm} place" value="${esc(v.place)}">
          <label class="wk-off"><input type="checkbox" id="${base}-off"${v.off ? ' checked' : ''} aria-label="${nm} off"> Off</label></div>
        <div class="wk-line"><input type="time" step="300" id="${base}-start" aria-label="${nm} start" value="${timeValue(toMin(v.start))}"><span aria-hidden="true">–</span><input type="time" step="300" id="${base}-end" aria-label="${nm} end" value="${timeValue(toMin(v.end))}"></div>
      </div>`;
  }
  function weekBlocks(){
    const rows = [];
    WD.forEach((wd, i) => {
      for (const b of wk.weeks[wd].blocks) {
        const key = `${wd}:${b.id}`, gone = wk.removed.has(key);
        const what = b.title === KIND_NAME[b.type] ? b.title : `${b.title} (${KIND_NAME[b.type]})`;
        rows.push(`<li class="${gone ? 'removed' : ''}"><span>${WD_NAME[i]} · ${esc(what)} · ${esc(range(toMin(b.start), toMin(b.end)))}</span>`
          + `<button type="button" class="btn small" data-wk-rm="${esc(key)}" aria-label="${gone ? 'Keep' : 'Remove'} ${esc(what)} on ${WD_NAME[i]}s">${gone ? 'Keep' : 'Remove'}</button></li>`);
      }
    });
    F.wBlocks.innerHTML = rows.join('') || '<li class="b-none">None yet. Tick “Repeat every …” on a block to add one.</li>';
    SH.markEmoji?.(F.wBlocks);
  }
  function openWeek(focusId){
    if (!editable() || !F.weekDialog) return;
    wk = {weeks: Object.fromEntries(WD.map(wd => [wd, clone(weekOf(wd))])), removed: new Set(), back: focusKey()};
    F.wDays.innerHTML = WD.map((wd, i) => `<div class="wk-row" role="group" aria-labelledby="wk-${wd}"><div class="wk-day" id="wk-${wd}">${WD_NAME[i]}</div>${MEALS.map(m => mealCell(wd, i, m)).join('')}</div>`).join('');
    weekBlocks();
    const s = settings();
    const opt = (h, sel) => `<option value="${h}"${h === sel ? ' selected' : ''}>${h === 0 || h === 24 ? '12 AM (midnight)' : h === 12 ? '12 PM (noon)' : hourLabel(h)}</option>`;
    F.wStart.innerHTML = Array.from({length: 24}, (_, h) => opt(h, s.day_start)).join('');
    F.wEnd.innerHTML = Array.from({length: 24}, (_, h) => opt(h + 1, s.day_end)).join('');
    showErr(F.wErr, '');
    F.weekDialog.showModal();
    (focusId && document.getElementById(focusId) || F.wDays.querySelector('input')).focus();
  }
  function saveWeek(){
    const next = {};
    for (const [i, wd] of WD.entries()) {
      const w = clone(wk.weeks[wd]);
      for (const m of MEALS) {
        const at = f => document.getElementById(`wk-${wd}-${m}-${f}`);
        const start = readTime(at('start'), false), end = readTime(at('end'), true), bad = spanError(start, end);
        if (bad) return showErr(F.wErr, `${WD_NAME[i]} ${m}: ${bad[0].toLowerCase()}${bad.slice(1)}`, at(start == null ? 'start' : 'end'));
        w.meals[m] = {start: toTime(start), end: toTime(end), place: cut(at('place').value, LIMIT.place), off: at('off').checked};
      }
      w.blocks = w.blocks.filter(b => !wk.removed.has(`${wd}:${b.id}`));
      next[wd] = cleanWeek(w);
    }
    const ds = +F.wStart.value, de = +F.wEnd.value;
    if (de - ds < 4) return showErr(F.wErr, 'The day must be at least 4 hours long.', F.wEnd);
    const keys = WD.filter(wd => JSON.stringify(next[wd]) !== JSON.stringify(cleanWeek(weekOf(wd)))).map(wd => 'week:' + wd);
    const s = settings(), hours = ds !== s.day_start || de !== s.day_end;
    F.weekDialog.close();
    if (!keys.length && !hours) return;
    const undo = snapshot(hours ? [...keys, 'settings'] : keys);
    for (const k of keys) save(k, next[k.slice(5)]);
    if (hours) { save('settings', {day_start: ds, day_end: de}); scrolledFor = null; render(); }
    SH.toast('Saved your week', undo);
  }
  if (F.weekDialog) {
    F.weekForm.addEventListener('submit', e => { e.preventDefault(); saveWeek(); });
    F.wCancel.onclick = () => F.weekDialog.close();
    F.weekDialog.addEventListener('close', () => { if (focusLost() || F.weekDialog.contains(document.activeElement)) refocus(wk?.back, els.week); });
    F.weekDialog.addEventListener('click', e => {
      if (e.target === F.weekDialog) return F.weekDialog.close();
      const rm = e.target.closest('[data-wk-rm]');
      if (!rm) return;
      const key = rm.dataset.wkRm;
      if (wk.removed.has(key)) wk.removed.delete(key); else wk.removed.add(key);
      weekBlocks();
      F.wBlocks.querySelector(`[data-wk-rm="${CSS.escape(key)}"]`)?.focus();
    });
    F.wDays.addEventListener('change', e => {
      if (e.target.matches('input[type=checkbox]')) e.target.closest('.wk-meal').classList.toggle('off', e.target.checked);
    });
  }

  // ---- starting ----
  // Only where the page saves through SchoolHub's own server (on the Mac or the public site): not on
  // the phone site, from disk, or read-only.
  SH.on('ready', () => {
    const m = SH.mode;
    if (m.PHONE || m.LOCAL_FILES || m.WRITE !== 'local') return SH.setPlanner('off');
    load(shown);
  });
  SH.on('render', render);
  SH.on('reload', () => { if (SH.plannerState === 'on') load(shown); });
})();
