#!/usr/bin/env python3
"""Build (and optionally deploy) the read-only phone view of SchoolHub.

Your assignments, grades and feedback are private, but a hosted page has no login, so the
site is published under one unguessable path segment and asks search engines to stay away:

    https://<your-project>.vercel.app/<secret>/

Anyone with that link can read your data, so treat the link like a password.

    python3 publish.py            # build ./schoolhub-site
    python3 publish.py --deploy   # build, then deploy to Vercel (needs `npx vercel login` first)
"""
import json
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parent
SITE = HUB / "schoolhub-site"
CONFIG = HUB / "config.json"

PLACEHOLDER = """<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex,nofollow">
<title>Nothing here</title>
<style>body{font:15px -apple-system,sans-serif;margin:25vh auto;max-width:28rem;text-align:center;color:#777}</style>
<p>Nothing to see here.</p>
"""

VERCEL_JSON = {
    "trailingSlash": True,   # so /<secret> redirects to /<secret>/ instead of 404ing
    "headers": [
        {"source": "/(.*)", "headers": [
            {"key": "X-Robots-Tag", "value": "noindex, nofollow"},
            {"key": "Referrer-Policy", "value": "no-referrer"},
        ]},
        {"source": "/(.*)/data.js", "headers": [{"key": "Cache-Control", "value": "no-store"}]},
    ]
}


def build(cfg):
    site = cfg.setdefault("site", {})
    if not site.get("secret"):
        site["secret"] = secrets.token_urlsafe(18)
        CONFIG.write_text(json.dumps(cfg, indent=2) + "\n")
        print(f"Generated secret path: /{site['secret']}/")
    page = SITE / site["secret"]
    page.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HUB / "dashboard.html", page / "index.html")
    shutil.copy2(HUB / "data.js", page / "data.js")
    (SITE / "index.html").write_text(PLACEHOLDER)
    (SITE / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    # Without this the CLI falls back to the repo's .gitignore, which excludes data.js.
    (SITE / ".vercelignore").write_text("# Upload everything in this folder.\n")
    (SITE / "vercel.json").write_text(json.dumps(VERCEL_JSON, indent=2) + "\n")
    return site


def production_url(fallback=None):
    """The stable https://<project>.vercel.app address, not the per-deploy one."""
    try:
        name = json.loads((SITE / ".vercel" / "project.json").read_text()).get("projectName")
        if name:
            return f"https://{name}.vercel.app"
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        pass
    return fallback


def deploy(site):
    npx = shutil.which("npx") or next((p for p in ("/opt/homebrew/bin/npx", "/usr/local/bin/npx")
                                        if Path(p).exists()), None)
    if not npx:
        raise RuntimeError("npx not found; install Node.js or add it to PATH")
    cmd = [npx, "--yes", "vercel@latest", "deploy", "--prod", "--yes"]
    if site.get("vercel_token"):
        cmd += ["--token", site["vercel_token"]]
    result = subprocess.run(cmd, cwd=SITE, capture_output=True, text=True, timeout=900)
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError("deploy failed: " + output[-600:])
    # npm chatter can share a line with the URL, so take the first URL-looking token.
    urls = [word for line in output.splitlines() for word in line.split()
            if word.startswith("https://") and ".vercel.app" in word]
    deployed = urls[-1].split(".vercel.app")[0] + ".vercel.app" if urls else None
    return production_url(deployed)


def main():
    cfg = json.loads(CONFIG.read_text())
    site = build(cfg)
    print(f"Built {SITE}")
    if "--deploy" in sys.argv:
        try:
            url = deploy(site)
        except RuntimeError as e:
            sys.exit(f"{e}\n\nRun `npx vercel login` first, or set site.vercel_token in config.json.")
        if url:
            site["url"] = url
            CONFIG.write_text(json.dumps(cfg, indent=2) + "\n")
            print(f"\nYour page: {url}/{site['secret']}/")


if __name__ == "__main__":
    main()
