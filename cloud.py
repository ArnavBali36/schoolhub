"""Optional shared database for your ✓ marks and your own tasks, so the phone view can change them too.

Uses Upstash Redis over its REST API (free tier), the same store the Vercel function in
vercel/api/state.js talks to. Credentials come from state/cloud.env, which
`npx vercel env pull` writes. Without that file, SchoolHub keeps marks and tasks in local
JSON files only.
"""
import json
import urllib.request
from pathlib import Path

try:
    # python.org Python ships without system CAs; use the macOS keychain.
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

HUB = Path(__file__).resolve().parent
ENV_FILE = HUB / "state" / "cloud.env"
KEYS = {"marks": "schoolhub:marks", "tasks": "schoolhub:tasks"}


def _read_env():
    values = {}
    try:
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"')
    except FileNotFoundError:
        pass
    return values


class Cloud:
    def __init__(self, url, token):
        self.url = url.rstrip("/")
        self.token = token

    def run(self, *command):
        req = urllib.request.Request(self.url, data=json.dumps(command).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {self.token}",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        if data.get("error"):
            raise RuntimeError(data["error"])
        return data.get("result")

    def get_all(self, name):
        flat = self.run("HGETALL", KEYS[name]) or []
        out = {}
        for field, value in zip(flat[::2], flat[1::2]):
            try:
                out[field] = json.loads(value)
            except json.JSONDecodeError:
                pass
        return out

    def put(self, name, field, obj):
        self.run("HSET", KEYS[name], field, json.dumps(obj))

    def remove(self, name, field):
        self.run("HDEL", KEYS[name], field)


def connect():
    """A Cloud client if state/cloud.env has Upstash credentials, else None."""
    env = _read_env()
    url = env.get("KV_REST_API_URL") or env.get("UPSTASH_REDIS_REST_URL")
    token = env.get("KV_REST_API_TOKEN") or env.get("UPSTASH_REDIS_REST_TOKEN")
    return Cloud(url, token) if url and token else None


def seed(db, name, local):
    """First connection: copy marks/tasks made before the database existed."""
    if local and not db.get_all(name):
        for field, obj in local.items():
            db.put(name, field, obj)
