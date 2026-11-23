// SchoolHub's app bar: the theme button, the app switch and its O key, the view on show, and where
// the sync status sits. Loaded in <head> right after theme-init.js, so it fills the bar in as the
// browser reads it, before the bar is first painted: no plain title that turns into the switch a
// moment later, no empty theme button, no view that lights up late. dashboard.js, which needs the
// synced data (data.js), does the rest. A file of its own, not inline, so the page runs under a
// Content-Security-Policy of script-src 'self'.
(() => {
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const typingIn = el => !!el && (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable);
  // publish.py marks the phone site's page right after <head>, so the mark is already read here.
  const PHONE = $('meta[name="schoolhub-site"]')?.content === 'phone';
  const LOCAL_FILES = location.protocol === 'file:';

  // ---- the glance ----
  // The page opened at #glance is today's plan to be read at a glance and nothing else: the Mac
  // app shows it in a small window under its menu bar icon (docs/planner.md, "The glance"). The
  // mark goes on <html> here, before anything is painted, and the page's CSS and planner.js do the
  // rest. Nothing is changed from a glance, so no key does anything in it: the page's own keys
  // (B for a block, N for a task, the views, O for the next app) would act on parts that are not
  // on show.
  if (location.hash === '#glance') {
    document.documentElement.classList.add('glance');
    window.addEventListener('keydown', e => { e.stopImmediatePropagation(); }, true);
  }

  // ---- filling the bar in as it is read ----
  // A MutationObserver's callback runs after the browser adds elements and before it next paints,
  // so each part is filled in the moment it exists. A fill returns true once its part is complete.
  const fills = [];
  const runFills = () => { for (let i = fills.length - 1; i >= 0; i--) if (fills[i]()) fills.splice(i, 1); };
  const observer = new MutationObserver(() => { runFills(); if (!fills.length) observer.disconnect(); });
  const whenParsed = fill => { if (!fill()) fills.push(fill); };
  observer.observe(document, {childList: true, subtree: true});
  document.addEventListener('DOMContentLoaded', () => { runFills(); fills.length = 0; observer.disconnect(); });

  // ---- light and dark ----
  // One setting with QuantPrep: localStorage qp.theme, System, Light, Dark or Night. System follows
  // the operating system while the page is open, and a choice made in another tab applies here at
  // once. Night is School's own: the system's colors, except from 9 PM to midnight, when every color
  // on the page is a shade of red with no blue in it, so the screen keeps no one awake. QuantPrep,
  // which does not know Night, shows System for it.
  const THEME_KEY = 'qp.theme';
  const THEME_CHOICES = ['system', 'light', 'dark', 'night'];
  const THEME_LABEL = {system: 'System', light: 'Light', dark: 'Dark', night: 'Night', red: 'Red'};
  const NIGHT_FROM = 21, NIGHT_TO = 24;  // hours of the day, local time
  const nightNow = () => { const h = new Date().getHours(); return h >= NIGHT_FROM && h < NIGHT_TO; };
  // A screen for System, a sun for Light, a moon for Dark: QuantPrep's icons.
  const THEME_ICON = {
    system: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    light: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
    dark: '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>',
    // The moon with a Z: Dark, and asleep.
    night: '<path d="M18 15.5A7 7 0 0 1 8.5 6 7 7 0 1 0 18 15.5z"/><path d="M15 3h5l-5 5.5h5"/>',
  };
  // The tab's icon at night: SchoolHub's tick on red, with no blue.
  const ICON_DAY = 'favicon.svg';
  const ICON_RED = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#5c1000"/><path d="M9 16.5l4.5 4.5L23 11.5" fill="none" stroke="#ff4800" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>');
  // The colour a phone gives its own bar above the page, in each palette: School's bar's (--titlebar
  // in dashboard.html), as theme-init.js writes it before the first paint.
  const BAR_COLOR = {light: '#fcfcfd', dark: '#17181e', red: '#150100'};
  const darkQuery = typeof matchMedia === 'function' ? matchMedia('(prefers-color-scheme: dark)') : null;
  const READ_FAILED = {};
  const readTheme = () => { try { return localStorage.getItem(THEME_KEY); } catch { return READ_FAILED; } };
  // A choice the browser refused to store (a private window), with what storage held then. It holds
  // for this page until storage holds something else, such as a choice made in another tab.
  let unsavedTheme = null;
  function themeChoice(){
    const v = readTheme();
    if (unsavedTheme && (v === unsavedTheme.over || v === READ_FAILED)) return unsavedTheme.choice;
    unsavedTheme = null;
    return THEME_CHOICES.includes(v) ? v : 'system';
  }
  const systemTheme = () => darkQuery?.matches ? 'dark' : 'light';
  const resolveTheme = choice =>
    choice === 'night' ? (nightNow() ? 'red' : systemTheme()) : choice === 'system' ? systemTheme() : choice;
  const choiceText = (choice, theme) =>
    choice === 'system' ? `System (${THEME_LABEL[theme].toLowerCase()})`
      : choice === 'night' ? (theme === 'red' ? 'Night (red until 12 AM)' : `Night (${THEME_LABEL[theme].toLowerCase()}, red from 9 PM to 12 AM)`)
      : THEME_LABEL[choice];
  const nextTheme = choice => THEME_CHOICES[(THEME_CHOICES.indexOf(choice) + 1) % THEME_CHOICES.length];
  function applyTheme(choice = themeChoice()){
    const theme = resolveTheme(choice), root = document.documentElement;
    if (root.getAttribute('data-theme') !== theme) {
      // Every color changes at once: the stylesheet turns transitions off while this is set.
      root.setAttribute('data-theme-switching', '');
      root.setAttribute('data-theme', theme);
      root.getBoundingClientRect();
      root.removeAttribute('data-theme-switching');
    }
    const icon = $('link[rel="icon"]');
    const href = theme === 'red' ? ICON_RED : ICON_DAY;
    if (icon && icon.getAttribute('href') !== href) icon.setAttribute('href', href);
    const bar = $('meta[name="theme-color"]');
    if (bar && bar.getAttribute('content') !== BAR_COLOR[theme]) bar.setAttribute('content', BAR_COLOR[theme]);
    const btn = $('#themeBtn');
    if (!btn) return false;
    // "Theme: System (dark). Switch to Light": the choice, the palette it gives, and the next one.
    const label = `Theme: ${choiceText(choice, theme)}. Switch to ${THEME_LABEL[nextTheme(choice)]}`;
    btn.title = label;
    btn.setAttribute('aria-label', label);
    if (btn.dataset.choice !== choice) {
      btn.dataset.choice = choice;
      btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${THEME_ICON[choice]}</svg>`;
    }
    return true;
  }
  function setTheme(choice){
    const over = readTheme();
    try { localStorage.setItem(THEME_KEY, choice); unsavedTheme = null; } catch { unsavedTheme = {choice, over}; }
    applyTheme(choice);
  }
  document.addEventListener('click', e => { if (e.target.closest?.('#themeBtn')) setTheme(nextTheme(themeChoice())); });
  darkQuery?.addEventListener?.('change', () => applyTheme());
  window.addEventListener('storage', e => { if (e.key === THEME_KEY || e.key === null) applyTheme(); });
  whenParsed(() => applyTheme());
  // Night turns red at 9 PM and back at midnight while the page stays open: checked every half
  // minute, and at once when the page comes back from the background or the computer wakes.
  setInterval(() => { if (themeChoice() === 'night') applyTheme(); }, 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) applyTheme(); });
  window.addEventListener('focus', () => applyTheme());

  // ---- the view on show ----
  // dashboard.js keeps these in step; marked here too so the current view is lit from the start.
  // Day (the planner alone) is a view only below 1100 px, where the planner has no column of its
  // own, and never on the phone site or from disk, which have no planner: there a remembered Day
  // shows Upcoming. Its button stays hidden until dashboard.js knows the planner is there, unless
  // Day is the view on show.
  const dayOffered = !PHONE && !LOCAL_FILES && !(typeof matchMedia === 'function' && matchMedia('(min-width: 1100px)').matches);
  let view = 'upcoming';
  try {
    const kept = JSON.parse(localStorage.getItem('sh:view'));
    view = kept === 'courses' ? 'courses' : kept === 'day' && dayOffered ? 'day' : 'upcoming';
  } catch {}
  whenParsed(() => {
    for (const b of document.querySelectorAll('#views button[data-view]')) {
      if (!b.hasAttribute('aria-pressed')) b.setAttribute('aria-pressed', String(b.dataset.view === view));
      if (b.dataset.view === 'day' && view === 'day') b.hidden = false;
    }
    return !!$('#views + *');  // the views are complete once the parser is past them
  });

  // ---- the sync status ----
  // Beside the theme button where the bar has room, as QuantPrep keeps Asked there; on a row of its
  // own above the page on narrow screens. One element, moved.
  const wideBar = typeof matchMedia === 'function' ? matchMedia('(min-width: 781px)') : null;
  // dashboard.html has it in the bar; it moves once the row has been read.
  function placeSync(){
    const box = $('#syncbox'), end = $('.bar-end'), row = $('#syncrow');
    if (!box || !end || !row) return false;
    if (wideBar?.matches) { if (box.parentNode !== end) end.prepend(box); }
    else if (box.parentNode !== row) row.append(box);
    return true;
  }
  wideBar?.addEventListener?.('change', placeSync);
  whenParsed(placeSync);

  // ---- the app switch ----
  // Part of a platform (SchoolHub under /school/ next to QuantPrep), the page finds platform.json
  // next to itself and draws the switch in place of the plain title: the platform's mark, then the
  // apps as a segmented control with this one raised, each a real link. Opened on its own server,
  // from disk or as the phone site there is no platform, and the plain title stays. The platform's
  // last answer is kept (in qp.platform, which QuantPrep keeps too), so the switch is drawn from the
  // first paint, not a moment later.
  const SELF_APP = 'school';
  const SWITCH_KEY = 'o';                           // the platform's key for the next app, the same in every app
  const PLATFORM_KEY = 'qp.platform';
  const MAC_APP_KEYS = {quant: '⌘1', school: '⌘2', dash: '⌘3'};   // the Mac app's View menu (PrepSchool.swift)
  // A platform description, or null. Links must be paths on this address: never another site.
  function validApps(apps){
    const ok = Array.isArray(apps) && apps.length > 1 && apps.length <= 8 && apps.every(a => a
      && typeof a.id === 'string' && /^[a-z][a-z0-9-]{0,30}$/.test(a.id)
      && typeof a.name === 'string' && a.name.trim() && a.name.length <= 40
      && typeof a.href === 'string' && /^\/(?![/\\])[\w\-./]*$/.test(a.href));
    return ok && apps.some(a => a.id === SELF_APP) ? apps.map(a => ({id: a.id, name: a.name, href: a.href})) : null;
  }
  const readPlatform = () => { try { return validApps(JSON.parse(localStorage.getItem(PLATFORM_KEY))?.apps); } catch { return null; } };
  // Kept with the answer's marks: QuantPrep reads the same key, and tells the public site by its
  // "public" (and another device by "remote") before its own answer comes. Each only as a plain true.
  const keepPlatform = (apps, p) => {
    try {
      if (!apps) return localStorage.removeItem(PLATFORM_KEY);
      localStorage.setItem(PLATFORM_KEY, JSON.stringify({apps, ...(p?.public === true ? {public: true} : {}), ...(p?.remote === true ? {remote: true} : {})}));
    } catch {}
  };
  let platformApps = LOCAL_FILES || PHONE ? null : readPlatform();
  // The app after this one in the switch's order, the first after the last (QuantPrep's otherApp).
  const nextApp = apps => apps[(apps.findIndex(a => a.id === SELF_APP) + 1) % apps.length];
  let drawn;  // the apps the brand slot was last drawn from (null: the plain title)
  function drawSwitch(){
    const slot = $('#brand');
    const title = slot?.querySelector('h1.brand');  // the plain title, as dashboard.html has it
    if (!slot || (!title && !slot.querySelector('.app-switch'))) return false;  // not read yet
    const apps = platformApps;
    if (drawn !== undefined && JSON.stringify(drawn) === JSON.stringify(apps)) return true;
    drawn = apps;
    if (!apps) {
      if (!title) slot.innerHTML = '<h1 class="brand">SchoolHub</h1>';
      return true;
    }
    // The O key leads to the next app in the switch's order, and that app's tooltip says so. In
    // the Mac app every app has a key of its own (⌘1, ⌘2, ⌘3), and each tooltip names that one.
    const next = nextApp(apps), mac = document.documentElement.classList.contains('in-mac-app');
    const key = a => mac && MAC_APP_KEYS[a.id] ? ` (${MAC_APP_KEYS[a.id]})` : !mac && a === next ? ` (${SWITCH_KEY.toUpperCase()})` : '';
    // (Each link carries its app's id, which the page's list of keys reads: dashboard.js keyGroups.)
    const links = apps.map(a => a.id === SELF_APP
      ? `<a href="${esc(a.href)}" data-app="${esc(a.id)}" aria-current="true" title="${esc(a.name)}: your assignments">${esc(a.name)}</a>`
      : `<a href="${esc(a.href)}" data-app="${esc(a.id)}" title="Switch to ${esc(a.name)}${key(a)}">${esc(a.name)}</a>`).join('');
    const t = document.createElement('template');
    t.innerHTML = `<nav class="app-switch" aria-label="Switch app"><svg class="brand-mark" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7"/><path d="M8 21l5-6 4 3 7-9" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg><span class="app-seg">${links}</span></nav><h1 class="sr-only">SchoolHub</h1>`;
    // The title is replaced as an element, never by rewriting the slot: if the browser is still
    // reading it, the rest of its text goes into the detached title, not beside the switch.
    if (title) title.replaceWith(t.content); else slot.replaceChildren(t.content);
    return true;
  }
  whenParsed(drawSwitch);
  // It answers a copy of the answer (dashboard.js reads it: "starting"), taken before this reads it.
  let platformFailed = false;
  function askPlatform(){
    const asked = fetch('platform.json', {cache: 'no-store'});
    const copy = asked.then(r => r.clone());
    copy.catch(() => {});
    asked.then(async r => {
      // No platform (SchoolHub's own server answers 204): the plain title. Any other failure keeps
      // what is shown.
      const body = await r.text();
      const p = r.status === 200 ? JSON.parse(body) : null;
      const apps = r.status === 200 ? validApps(p?.apps) : r.status === 204 || r.status === 404 ? null : undefined;
      platformFailed = apps === undefined;
      if (platformFailed) return;
      platformApps = apps;
      keepPlatform(apps, p);
      drawSwitch();
    }).catch(() => { platformFailed = true; });
    return copy;
  }
  if (!LOCAL_FILES && !PHONE) {
    // dashboard.js asks where the page is by the same answer, so a load asks once.
    window.schoolHubPlatform = askPlatform();
    // Not answered (the app opened with no signal): asked again once dashboard.js has reached the
    // server after all ("asked again"), so the switch is drawn then and not only at the next load.
    window.addEventListener('qp:placed', () => { if (platformFailed) askPlatform(); });
  }
  // O opens the next app, as in QuantPrep; never while typing, nor with the drawer or a dialog open.
  document.addEventListener('keydown', e => {
    if (String(e.key).toLowerCase() !== SWITCH_KEY || !platformApps || e.defaultPrevented || e.repeat) return;
    if (e.metaKey || e.ctrlKey || e.altKey || typingIn(document.activeElement)) return;
    if (document.querySelector('dialog[open], [aria-modal="true"]:not([hidden])')) return;
    const other = nextApp(platformApps);
    if (other && other.id !== SELF_APP) { e.preventDefault(); location.assign(other.href); }
  });

  // ---- the page under the bar, before the data ----
  // dashboard.js draws the list once it has the last sync, which on a first visit (nothing kept
  // from an earlier one) is when data.js arrives: on a phone's connection a while. Until then a
  // quiet line says the page is on its way, rather than a blank page under the bar.
  whenParsed(() => {
    const main = $('#main');
    if (!main) return false;
    if (!main.firstChild && !window.SCHOOL_DATA) main.innerHTML = '<p class="empty">Loading…</p>';
    return true;
  });

  // ---- the installed app ----
  // The site opened from its icon on a phone's Home Screen, as an app of its own (QuantPrep's
  // lib/installed.ts, docs/15). Two things a browser's own controls did are the page's to do there.
  // Where it opens: the app starts at Prep each time the phone has put it away, and goes on to the
  // app that was open last (QuantPrep's theme-init.js reads qp.last), so School notes itself.
  // Staying current: there is no reload control, and a phone brings a page back exactly as it was
  // left, for days. dashboard.js takes in what changed on each return ("back on show"); and a page
  // that comes back into sight after more than an hour away loads itself again, as the Mac app does
  // for its own views, which is also how a new version of the page reaches it. Never while
  // something is open or being typed in that a reload would take away.
  const INSTALLED = (() => {
    try { return navigator.standalone === true || matchMedia('(display-mode: standalone)').matches; } catch { return false; }
  })();
  if (INSTALLED && !LOCAL_FILES) {
    const AWAY_MS = 60 * 60000;
    // The launch has happened, too, once a page of the app is shown: QuantPrep's theme-init.js goes
    // on to qp.last only at the first page of a launch (qp.launched, kept as long as the launch).
    // A launch that started here (an icon added at /school/, or the app brought back here) would
    // otherwise send the first tap on Prep back to School.
    const rememberApp = () => {
      if (PHONE || !/^\/school(\/|$)/.test(location.pathname)) return;   // only School under the platform
      try { localStorage.setItem('qp.last', '/school/'); } catch {}
      try { sessionStorage.setItem('qp.launched', '1'); } catch {}
    };
    // A dialog (a task's form, Notes, a block's details), the drawer, a field with the focus, or an
    // undo on its way.
    const busy = () => !!document.querySelector('dialog[open], #drawer:not([hidden]), #toast[data-wait]') || typingIn(document.activeElement);
    let hiddenAt = document.hidden ? Date.now() : null;
    const seen = () => {
      if (document.hidden) { hiddenAt = Date.now(); return; }
      rememberApp();
      const away = hiddenAt === null ? 0 : Date.now() - hiddenAt;
      hiddenAt = null;
      if (away > AWAY_MS && !busy()) location.reload();
    };
    rememberApp();
    document.addEventListener('visibilitychange', seen);
    window.addEventListener('pageshow', e => { if (e.persisted) seen(); });
  }

  // ---- what a pointer reads on hover, on a tap ----
  // A screen worked by touch alone never shows a title. Two say what the page does not: the exact
  // time of the last sync, with when the next is due ("Synced 2h ago"), and where a file the page
  // cannot open is ("On your Mac: ~/…"). There a tap on either says it in the page's toast; the tap
  // on the sync time also asks for what is new (dashboard.js, "back on show"), as the app on a
  // phone has no reload. A Mac and a desktop browser keep the tooltips as they were.
  const TOUCH = typeof matchMedia === 'function' ? matchMedia('(hover: none) and (pointer: coarse)') : null;
  document.addEventListener('click', e => {
    if (!TOUCH?.matches) return;
    const el = e.target.closest?.('#sync, .offsite');
    const words = el?.getAttribute('title');
    if (!words || !window.SchoolHub?.toast) return;
    window.SchoolHub.toast((el.id === 'sync' ? 'Synced ' : '') + words.split('\n').join(' · '), null);
    if (el.id === 'sync') window.dispatchEvent(new Event('qp:look'));
  });
})();
