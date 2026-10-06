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
  // One setting with QuantPrep: localStorage qp.theme, System, Light or Dark. System follows the
  // operating system while the page is open, and a choice made in another tab applies here at once.
  const THEME_KEY = 'qp.theme';
  const THEME_CHOICES = ['system', 'light', 'dark'];
  const THEME_LABEL = {system: 'System', light: 'Light', dark: 'Dark'};
  // A screen for System, a sun for Light, a moon for Dark: QuantPrep's icons.
  const THEME_ICON = {
    system: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    light: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
    dark: '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>',
  };
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
  const resolveTheme = choice => choice === 'system' ? (darkQuery?.matches ? 'dark' : 'light') : choice;
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
    const btn = $('#themeBtn');
    if (!btn) return false;
    // "Theme: System (dark). Switch to Light": the choice, the palette it gives, and the next one.
    const label = `Theme: ${choice === 'system' ? `System (${THEME_LABEL[theme].toLowerCase()})` : THEME_LABEL[choice]}. Switch to ${THEME_LABEL[nextTheme(choice)]}`;
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

  // ---- the view on show ----
  // dashboard.js keeps these in step; marked here too so the current view is lit from the start.
  let view = 'upcoming';
  try { view = JSON.parse(localStorage.getItem('sh:view')) === 'courses' ? 'courses' : 'upcoming'; } catch {}
  whenParsed(() => {
    for (const b of document.querySelectorAll('#views button[data-view]'))
      if (!b.hasAttribute('aria-pressed')) b.setAttribute('aria-pressed', String(b.dataset.view === view));
    return !!$('#views + *');  // the views are complete once the parser is past them
  });

  // ---- the sync status ----
  // Beside the theme button where the bar has room, as QuantPrep keeps Asked there; above the lists
  // on narrow screens. One element, moved.
  const wideBar = typeof matchMedia === 'function' ? matchMedia('(min-width: 781px)') : null;
  // dashboard.html has it in the bar; it moves once the toolbar has been read.
  function placeSync(){
    const box = $('#syncbox'), end = $('.bar-end'), toolbar = $('.toolbar');
    if (!box || !end || !toolbar) return false;
    if (wideBar?.matches) { if (box.parentNode !== end) end.prepend(box); }
    else if (box.parentNode !== toolbar) toolbar.append(box);
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
  const SWITCH_KEY = 'o';                           // QuantPrep's key for the other app, the same in both
  const PLATFORM_KEY = 'qp.platform';
  // A platform description, or null. Links must be paths on this address: never another site.
  function validApps(apps){
    const ok = Array.isArray(apps) && apps.length > 1 && apps.length <= 8 && apps.every(a => a
      && typeof a.id === 'string' && /^[a-z][a-z0-9-]{0,30}$/.test(a.id)
      && typeof a.name === 'string' && a.name.trim() && a.name.length <= 40
      && typeof a.href === 'string' && /^\/(?![/\\])[\w\-./]*$/.test(a.href));
    return ok && apps.some(a => a.id === SELF_APP) ? apps.map(a => ({id: a.id, name: a.name, href: a.href})) : null;
  }
  const readPlatform = () => { try { return validApps(JSON.parse(localStorage.getItem(PLATFORM_KEY))?.apps); } catch { return null; } };
  const keepPlatform = apps => { try { apps ? localStorage.setItem(PLATFORM_KEY, JSON.stringify({apps})) : localStorage.removeItem(PLATFORM_KEY); } catch {} };
  let platformApps = LOCAL_FILES || PHONE ? null : readPlatform();
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
    const links = apps.map(a => a.id === SELF_APP
      ? `<a href="${esc(a.href)}" aria-current="true" title="${esc(a.name)}: your assignments">${esc(a.name)}</a>`
      : `<a href="${esc(a.href)}" title="Switch to ${esc(a.name)} (${SWITCH_KEY.toUpperCase()})">${esc(a.name)}</a>`).join('');
    const t = document.createElement('template');
    t.innerHTML = `<nav class="app-switch" aria-label="Switch app"><svg class="brand-mark" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7"/><path d="M8 21l5-6 4 3 7-9" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg><span class="app-seg">${links}</span></nav><h1 class="sr-only">SchoolHub</h1>`;
    // The title is replaced as an element, never by rewriting the slot: if the browser is still
    // reading it, the rest of its text goes into the detached title, not beside the switch.
    if (title) title.replaceWith(t.content); else slot.replaceChildren(t.content);
    return true;
  }
  whenParsed(drawSwitch);
  if (!LOCAL_FILES && !PHONE) {
    fetch('platform.json', {cache: 'no-store'}).then(async r => {
      // No platform (SchoolHub's own server answers 204): the plain title. Any other failure keeps
      // what is shown.
      const body = await r.text();
      const apps = r.status === 200 ? validApps(JSON.parse(body)?.apps) : r.status === 204 || r.status === 404 ? null : undefined;
      if (apps === undefined) return;
      platformApps = apps;
      keepPlatform(apps);
      drawSwitch();
    }).catch(() => {});
  }
  // O opens the other app, as in QuantPrep; never while typing, nor with the drawer or a dialog open.
  document.addEventListener('keydown', e => {
    if (String(e.key).toLowerCase() !== SWITCH_KEY || !platformApps || e.defaultPrevented || e.repeat) return;
    if (e.metaKey || e.ctrlKey || e.altKey || typingIn(document.activeElement)) return;
    if (document.querySelector('dialog[open], [aria-modal="true"]:not([hidden])')) return;
    const other = platformApps.find(a => a.id !== SELF_APP);
    if (other) { e.preventDefault(); location.assign(other.href); }
  });
})();
