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
})();
