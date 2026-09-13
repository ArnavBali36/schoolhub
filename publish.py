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
    (SITE / "vercel.json").write_text(json.dumps(VERCEL_JSON, indent=2) + "\n")
    return site


def deploy(site):
    cmd = ["npx", "--yes", "vercel@latest", "deploy", "--prod", "--yes"]
    if site.get("vercel_token"):
        cmd += ["--token", site["vercel_token"]]
    result = subprocess.run(cmd, cwd=SITE, capture_output=True, text=True, timeout=600)
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        print(output[-1500:], file=sys.stderr)
        sys.exit("Deploy failed. Run `npx vercel login` first, or put a token in config.json "
                 "under site.vercel_token.")
    urls = [ln.strip() for ln in output.splitlines() if ln.strip().startswith("https://")]
    return urls[-1] if urls else None


def main():
    cfg = json.loads(CONFIG.read_text())
    site = build(cfg)
    print(f"Built {SITE}")
    if "--deploy" in sys.argv:
        url = deploy(site)
        if url:
            print(f"\nYour page: {url}/{site['secret']}/")


if __name__ == "__main__":
    main()
