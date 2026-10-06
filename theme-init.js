// Light or dark before the first paint, so the page never flashes the other one. The choice lives in
// localStorage "qp.theme" (system, light or dark), the same key QuantPrep uses, so under one address
// the two apps share it; dashboard.js keeps it in step afterwards. This is a file of its own, not
// inline in dashboard.html, so the page also runs under a Content-Security-Policy of script-src 'self'.
(() => {
  let t = "system";
  try {
    t = localStorage.getItem("qp.theme") || "system";
  } catch {}
  if (t !== "light" && t !== "dark")
    t = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", t);
})();
