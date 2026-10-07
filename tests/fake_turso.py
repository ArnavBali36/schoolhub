"""A stand-in for Turso's HTTP API, for the tests: POST /v2/pipeline over a SQLite file in a
throwaway folder, made from turso-schema.sql. Never the real database.

It speaks the part of the protocol SchoolHub uses, as strictly as Turso does: the token as a Bearer
token, a list of requests (execute with typed positional args, then close), typed values (an
integer's value is a string of digits), one result per request, and a statement's error as an error
result rather than a failed request. Each pipeline runs on its own connection, as a stream does.
"""
import base64
import json
import re
import sqlite3
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent.parent / "turso-schema.sql"
# STRICT tables came with SQLite 3.37.
STRICT_OK = sqlite3.sqlite_version_info >= (3, 37, 0)


class ProtocolError(Exception):
    """A request Turso would refuse whole (HTTP 400)."""


def decode(value):
    if not isinstance(value, dict):
        raise ProtocolError("a value must be an object")
    kind = value.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        v = value.get("value")
        if not isinstance(v, str) or not re.fullmatch(r"-?\d+", v):
            raise ProtocolError("an integer's value must be a string of digits")
        return int(v)
    if kind == "float":
        v = value.get("value")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ProtocolError("a float's value must be a number")
        return float(v)
    if kind == "text":
        if not isinstance(value.get("value"), str):
            raise ProtocolError("a text value must be a string")
        return value["value"]
    if kind == "blob":
        return base64.b64decode(value.get("base64") or "")
    raise ProtocolError(f"unknown value type {kind!r}")


def encode(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, bytes):
        return {"type": "blob", "base64": base64.b64encode(v).decode()}
    return {"type": "text", "value": v}


class FakeTurso:
    def __init__(self, token="fake-turso-token", schema=True):
        self.token = token
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "turso.db"
        db = sqlite3.connect(self.path)
        if schema:
            db.executescript(SCHEMA.read_text())
        db.close()
        self.pipelines = []      # every request body received, as JSON
        self.headers = []        # the headers of every request received, of any method
        self.answer = None       # (status, headers, body) to send instead of running the pipeline
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def send(self, status, body, headers=None):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                for k, v in (headers or {"Content-Type": "application/json"}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                fake.headers.append(dict(self.headers))
                self.send(405, {"error": "method not allowed"})

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                fake.headers.append(dict(self.headers))
                if self.path != "/v2/pipeline":
                    return self.send(404, {"error": "not found"})
                if fake.answer:
                    return self.send(*fake.answer)
                if self.headers.get("Authorization") != f"Bearer {fake.token}":
                    return self.send(401, {"error": "Unauthorized: the auth token is invalid"})
                try:
                    body = json.loads(raw)
                    fake.pipelines.append(body)
                    results = fake.run(body)
                except (ValueError, ProtocolError) as e:
                    return self.send(400, {"error": str(e)})
                self.send(200, {"baton": None, "base_url": None, "results": results})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def run(self, body):
        requests = body.get("requests") if isinstance(body, dict) else None
        if not isinstance(requests, list):
            raise ProtocolError("requests must be a list")
        db = sqlite3.connect(self.path, isolation_level=None)  # one stream: autocommit, as Turso's
        results, closed = [], False
        try:
            for req in requests:
                if closed:
                    raise ProtocolError("request after close")
                kind = req.get("type") if isinstance(req, dict) else None
                if kind == "close":
                    closed = True
                    results.append({"type": "ok", "response": {"type": "close"}})
                    continue
                if kind != "execute" or not isinstance(req.get("stmt"), dict):
                    raise ProtocolError(f"unsupported request {kind!r}")
                stmt = req["stmt"]
                if not isinstance(stmt.get("sql"), str):
                    raise ProtocolError("a statement needs its sql")
                args = [decode(a) for a in stmt.get("args") or []]
                try:
                    cur = db.execute(stmt["sql"], args)
                    rows = cur.fetchall()
                except sqlite3.Error as e:
                    results.append({"type": "error", "error": {"message": f"SQLite error: {e}", "code": "SQLITE_ERROR"}})
                    continue
                results.append({"type": "ok", "response": {"type": "execute", "result": {
                    "cols": [{"name": d[0], "decltype": None} for d in cur.description or []],
                    "rows": [[encode(v) for v in row] for row in rows],
                    "affected_row_count": max(cur.rowcount, 0),
                    "last_insert_rowid": str(cur.lastrowid) if cur.lastrowid else None,
                    "replication_index": None,
                }}})
        finally:
            db.close()
        return results

    def query(self, sql, *args):
        """Reads the database directly, as the other app sharing it would."""
        db = sqlite3.connect(self.path, isolation_level=None)
        try:
            return db.execute(sql, args).fetchall()
        finally:
            db.close()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def load_cloud(env_file):
    """A fresh copy of cloud.py that reads env_file instead of your state/cloud.env. (test_server.py
    puts a stand-in under the name cloud, so the real module is loaded from its file.)"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cloud_under_test", SCHEMA.parent / "cloud.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ENV_FILE = Path(env_file)
    return module
