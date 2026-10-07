"""Optional shared database for your ✓ marks and your own tasks, so the phone view can change them too.

Two backends, both spoken over HTTP with the standard library, chosen by what state/cloud.env holds:

- Turso (hosted libSQL), when it has TURSO_DATABASE_URL and TURSO_AUTH_TOKEN. Marks and tasks are
  rows of the school_kv table, and each sync also saves data.js in school_data (turso-schema.sql),
  so a hosted copy of the dashboard that reads the same database shows the same thing.
- Upstash Redis over its REST API (free tier), the same store the Vercel function in
  vercel/api/state.js talks to. `npx vercel env pull` writes its credentials.

Turso wins when both are there. Without either, SchoolHub keeps marks and tasks in local JSON files
only.
"""
import http.client
import json
import time
import urllib.error
import urllib.parse
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
    """Upstash Redis: marks and tasks as two hashes, one field per mark or task."""

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


# ---------- Turso ----------

# Plain http only to this computer (a libSQL server run locally); anywhere else the token would
# cross the network in clear.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
SCHEMES = {"libsql": "https", "turso": "https", "https": "https", "wss": "https", "http": "http", "ws": "http"}


def pipeline_url(url):
    """Turso's HTTP endpoint (<https url>/v2/pipeline) for a database URL, or None if it is not one.
    Turso gives libsql://<db>-<org>.turso.io (or turso://), which is spoken as https; libSQL's
    ?tls=0 asks for plain http, which is allowed only to this computer."""
    try:
        parts = urllib.parse.urlsplit(str(url or "").strip())
        scheme, host, _port = SCHEMES.get(parts.scheme.lower()), parts.hostname, parts.port
        tls = dict(urllib.parse.parse_qsl(parts.query)).get("tls")
    except ValueError:  # an invalid port, say
        return None
    if not scheme or not host or parts.username is not None or parts.password is not None:
        return None
    if tls == "0" and parts.scheme.lower() in ("libsql", "turso"):
        scheme = "http"
    if scheme == "http" and host not in LOCAL_HOSTS:
        return None
    # Anything after the path (a query such as ?authToken=…) is left out.
    return urllib.parse.urlunsplit((scheme, parts.netloc, parts.path.rstrip("/") + "/v2/pipeline", "", ""))


def _arg(value):
    """A statement argument as Turso's HTTP API types it: an integer's value is a string of digits."""
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        raise TypeError("a boolean is not a database value")
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    raise TypeError(f"{type(value).__name__} is not a database value")


def _value(cell):
    kind = cell["type"]
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
    if kind == "text":
        return cell["value"]
    raise ValueError(f"unexpected {kind} value")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Turso's API does not redirect. Following one would send the token wherever it pointed, so a
    redirect is an error (urllib raises HTTPError when this returns None)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_TURSO = urllib.request.build_opener(_NoRedirect)
# As Upstash's: server.py holds its one lock while it waits, so every other mark or task waits too.
TURSO_TIMEOUT = 15


def _kv(name):
    """school_kv's name for marks or tasks; anything else is a KeyError, as with Upstash."""
    if name not in KEYS:
        raise KeyError(name)
    return name


def _now_ms():
    return int(time.time() * 1000)


class Turso:
    """Turso (hosted libSQL): marks and tasks as rows of school_kv (name 'marks' or 'tasks', key the
    assignment or task id, value_json the object, updated_at in milliseconds), and the latest sync's
    data.js as the one row of school_data. The tables are made by turso-schema.sql or by the app that
    owns the database; SchoolHub never creates or changes them.

    Every call is one POST to /v2/pipeline: its statements, then close. Errors are RuntimeError (the
    database answered, but not with a result) or OSError (it could not be reached), as with Upstash."""

    def __init__(self, url, token):
        self.endpoint = pipeline_url(url)
        self.token = token

    def pipeline(self, *statements):
        """Runs (sql, args) statements in order on one stream, then closes it. Returns each
        statement's rows as lists of Python values."""
        if not self.endpoint:
            raise RuntimeError("TURSO_DATABASE_URL in state/cloud.env is not a libsql://, turso:// or https:// URL")
        requests = [{"type": "execute", "stmt": {"sql": sql, "args": [_arg(a) for a in args]}}
                    for sql, args in statements] + [{"type": "close"}]
        req = urllib.request.Request(self.endpoint, data=json.dumps({"requests": requests}).encode(),
                                     method="POST", headers={"Authorization": f"Bearer {self.token}",
                                                             "Content-Type": "application/json"})
        try:
            with _TURSO.open(req, timeout=TURSO_TIMEOUT) as resp:
                answer = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Turso answered HTTP {e.code}{_why(e)}") from None
        except (ValueError, http.client.HTTPException) as e:
            raise RuntimeError(f"Turso's answer could not be read ({type(e).__name__})") from None
        try:
            results = answer["results"]
            if len(results) != len(requests):
                raise ValueError("one result per request")
            out = []
            for result in results[:-1]:  # the last one is the close
                if result["type"] != "ok":
                    raise RuntimeError(f"Turso refused a statement: {(result.get('error') or {}).get('message') or 'no reason given'}")
                out.append([[_value(cell) for cell in row] for row in result["response"]["result"]["rows"]])
            return out
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise RuntimeError("Turso's answer could not be read") from None

    def get_all(self, name):
        # Oldest change first, as the local files keep them; a hosted copy reading the same table
        # answers in this order too, so both views list them alike.
        rows, = self.pipeline(("SELECT key, value_json FROM school_kv WHERE name = ? ORDER BY updated_at, key",
                               (_kv(name),)))
        # Never half an answer: the server keeps what this returns as its local copy.
        if any(len(row) != 2 or not isinstance(row[0], str) for row in rows):
            raise RuntimeError("Turso's answer could not be read")
        out = {}
        for key, value in rows:
            try:
                out[key] = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                pass
        return out

    def put(self, name, field, obj):
        self.pipeline(("INSERT INTO school_kv (name, key, value_json, updated_at) VALUES (?, ?, ?, ?) "
                       "ON CONFLICT (name, key) DO UPDATE SET value_json = excluded.value_json, "
                       "updated_at = excluded.updated_at", (_kv(name), field, json.dumps(obj), _now_ms())))

    def remove(self, name, field):
        self.pipeline(("DELETE FROM school_kv WHERE name = ? AND key = ?", (_kv(name), field)))

    def save_data(self, data_js, synced_at):
        """The text of a sync's data.js, made at synced_at (milliseconds), as school_data's one row.
        An older sync never replaces a newer one."""
        self.pipeline(("INSERT INTO school_data (id, data_js, synced_at) VALUES (1, ?, ?) "
                       "ON CONFLICT (id) DO UPDATE SET data_js = excluded.data_js, synced_at = excluded.synced_at "
                       "WHERE excluded.synced_at >= school_data.synced_at", (data_js, int(synced_at))))


def _why(error):
    """The reason in an HTTP error's JSON body, if it gives one, kept short. Best effort: an error
    without a readable body just has no reason."""
    try:
        body = json.loads(error.read(2000) or b"null")
        reason = (body.get("error") or body.get("message")) if isinstance(body, dict) else None
    except Exception:
        reason = None
    return f": {str(reason)[:200]}" if isinstance(reason, str) and reason else ""


def connect():
    """The shared database state/cloud.env names: Turso when it has TURSO_DATABASE_URL and
    TURSO_AUTH_TOKEN, else Upstash when it has Upstash credentials, else None (local files only)."""
    env = _read_env()
    if env.get("TURSO_DATABASE_URL") and env.get("TURSO_AUTH_TOKEN"):
        return Turso(env["TURSO_DATABASE_URL"], env["TURSO_AUTH_TOKEN"])
    url = env.get("KV_REST_API_URL") or env.get("UPSTASH_REDIS_REST_URL")
    token = env.get("KV_REST_API_TOKEN") or env.get("UPSTASH_REDIS_REST_TOKEN")
    return Cloud(url, token) if url and token else None


def seed(db, name, local):
    """First connection: copy marks/tasks made before the database existed."""
    if local and not db.get_all(name):
        for field, obj in local.items():
            db.put(name, field, obj)


def describe(db):
    """What `python3 cloud.py` says: the shared database state/cloud.env names and what it holds,
    read only. server.py falls back to the local files without a word when reading fails, so this
    is the way to see that it really reaches the database. Raises RuntimeError or OSError when the
    database does not answer."""
    if db is None:
        return "No shared database in state/cloud.env: marks and tasks stay in state/ on this computer."
    counts = f"{len(db.get_all('marks'))} marks, {len(db.get_all('tasks'))} tasks"
    if not isinstance(db, Turso):
        return f"Upstash ({urllib.parse.urlsplit(db.url).hostname}): {counts}."
    rows, = db.pipeline(("SELECT synced_at, length(data_js) FROM school_data WHERE id = 1", ()))
    if rows:
        at = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(rows[0][0]) / 1000))
        data = f"data.js from the sync of {at} ({round(int(rows[0][1]) / 1024)} KB)"
    else:
        data = "no data.js yet (it goes up with the next sync)"
    return f"Turso ({urllib.parse.urlsplit(db.endpoint).hostname}): {counts}; {data}."


if __name__ == "__main__":
    import sys
    try:
        print(describe(connect()))
    except (OSError, RuntimeError) as e:
        print(f"The shared database in state/cloud.env did not answer: {e}", file=sys.stderr)
        sys.exit(1)
