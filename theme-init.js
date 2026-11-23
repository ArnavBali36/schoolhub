// Light or dark before the first paint, so the page never flashes the other one. The choice lives in
// localStorage "qp.theme" (system, light, dark or night), the same key QuantPrep uses, so under one address
// the two apps share it; dashboard.js keeps it in step afterwards. This is a file of its own, not
// inline in dashboard.html, so the page also runs under a Content-Security-Policy of script-src 'self'.
(() => {
  let t = "system";
  try {
    t = localStorage.getItem("qp.theme") || "system";
  } catch {}
  // Night follows the system, except from 9 PM to midnight, when the page turns red (bar.js).
  const night = t === "night";
  if (t !== "light" && t !== "dark")
    t = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  if (night && new Date().getHours() >= 21) t = "red";
  document.documentElement.setAttribute("data-theme", t);
  // The colour a phone gives its own bar above the page: School's bar's in this theme (--titlebar in
  // dashboard.html; red has no blue). Written here, not as a tag in the page, so it is right from the
  // first paint in every theme; bar.js keeps it in step when the theme changes.
  try {
    let bar = document.querySelector('meta[name="theme-color"]');
    if (!bar) {
      bar = document.createElement("meta");
      bar.name = "theme-color";
      document.head.appendChild(bar);
    }
    bar.setAttribute("content", { light: "#fcfcfd", dark: "#17181e", red: "#150100" }[t]);
  } catch {}
  // Part of the platform (the page at /school/, next to Prep and the Dashboard): the platform's one
  // manifest and Home Screen icon, at the site's root, so an icon added from School is the same app
  // as one added from Prep and the app switch stays inside it. Never files beside this page: a
  // manifest whose scope were /school/ would open Prep and the Dashboard in a browser over the app.
  // SchoolHub on its own server, from disk or as the phone site has no platform, and adds nothing.
  try {
    if (/^\/school(\/|$)/.test(location.pathname))
      for (const [rel, href] of [["manifest", "/manifest.webmanifest"], ["apple-touch-icon", "/apple-touch-icon.png"]]) {
        if (document.querySelector(`link[rel="${rel}"]`)) continue;
        const link = document.createElement("link");
        link.rel = rel;
        link.href = href;
        document.head.appendChild(link);
      }
  } catch {}
})();
