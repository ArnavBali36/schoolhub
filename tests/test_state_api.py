"""The phone view's function (vercel/api/state.js), run in Node against a stand-in for its
database: what a mark request may do to a daily task's ✓ marks and its ledger. Standard library
only; no database is contacted."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
STATE = REPO / "vercel" / "api" / "state.js"

# The function's own handler, with fetch answered by a hash in memory as Upstash's REST API answers.
HARNESS = r"""
process.env.KV_REST_API_URL = 'https://db.invalid';
process.env.KV_REST_API_TOKEN = 't';
process.env.SCHOOLHUB_SECRET = 'secret';
const hashes = {}, sent = [];
globalThis.fetch = async (url, init) => {
  const [kind, key, ...rest] = JSON.parse(init.body);
  sent.push(kind);
  const h = hashes[key] ||= {};
  let result = null;
  if (kind === 'HSET') h[rest[0]] = rest[1];
  else if (kind === 'HDEL') delete h[rest[0]];
  else if (kind === 'HGET') result = h[rest[0]] ?? null;
  else if (kind === 'HGETALL') result = Object.entries(h).flat();
  return {json: async () => ({result})};
};
const handler = require(process.argv[1]);   // node -e: the arguments start at 1
const call = async (body, key = 'secret') => {
  let status = 200, answer = null;
  const res = {setHeader() {}, status(code) { status = code; return res; }, json(v) { answer = v; return res; }};
  await handler({method: body ? 'POST' : 'GET', headers: {'x-schoolhub-key': key}, body}, res);
  return [status, answer];
};
const plant = (id, value) => { (hashes['schoolhub:marks'] ||= {})[id] = JSON.stringify(value); };
"""


def run(script, *args):
    out = subprocess.run([NODE, "-e", HARNESS + script, str(STATE), *args], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "needs Node to run vercel/api/state.js")
class StateApiTest(unittest.TestCase):
    def test_the_door_decides_as_the_shared_vectors_say(self):
        vectors = json.loads((REPO / "tests" / "daily_vectors.json").read_text(encoding="utf-8"))["guard"]
        got = run("console.log(JSON.stringify(JSON.parse(process.argv[2]).map(v => handler.dailyGuard(v.id, v.done, v.today))));",
                  json.dumps(vectors))
        self.assertEqual(len(got), len(vectors))
        for v, answer in zip(vectors, got):
            with self.subTest(v["note"]):
                self.assertEqual(answer or ("store" if v["done"] else "remove"), v["want"])

    def test_a_daily_tick_is_made_and_taken_back_within_a_week_and_is_history_after(self):
        out = run(r"""
(async () => {
  const tid = 'task:ab12cd34ef56', now = Date.now();
  const day = n => new Date(now - n * 864e5).toISOString().slice(0, 10), tick = n => `${tid}@${day(n)}`;
  const out = {};
  // Today's: made, and taken back.
  out.made = await call({action: 'mark', id: tick(0), done: true, name: 'LeetCode', course: 'Personal'});
  out.madeKeys = Object.keys(out.made[1].marks);
  out.back = (await call({action: 'mark', id: tick(0), done: false}))[1].marks;
  // No tick for a day long past, far ahead or that is none; the ledger is neither made nor removed.
  plant(tid + '@done', {marked_at: 'x', days: ['2026-01-01']});
  const before = JSON.stringify(hashes['schoolhub:marks']);
  out.refused = [];
  for (const [id, done] of [[tick(8), true], [tick(-3), true], [tid + '@2026-02-30', true], [tid + '@done', true], [tid + '@done', false],
                            ['  ' + tid + '@done  ', false], ['x'.repeat(195) + '@done' + 'y'.repeat(20), true]])
    out.refused.push(await call({action: 'mark', id, done}));
  out.unchanged = JSON.stringify(hashes['schoolhub:marks']) === before;
  // A tick of a day long past is history: taking it away changes nothing, and answers the marks.
  plant(tick(30), {marked_at: 'x'}); plant(tick(7), {marked_at: 'x'});
  sent.length = 0;
  const kept = await call({action: 'mark', id: tick(30), done: false});
  out.kept = [kept[0], tick(30) in kept[1].marks, sent.includes('HDEL')];
  const gone = await call({action: 'mark', id: tick(7), done: false});
  out.gone = [gone[0], tick(7) in gone[1].marks];
  // An assignment's mark is as ever.
  await call({action: 'mark', id: 'canvas:1', done: true});
  out.plain = Object.keys((await call({action: 'mark', id: 'canvas:1', done: false}))[1].marks).includes('canvas:1');
  out.locked = (await call({action: 'mark', id: tick(0), done: true}, 'wrong'))[0];
  console.log(JSON.stringify(out));
})();
""")
        self.assertEqual(out["made"][0], 200)
        self.assertEqual(len(out["madeKeys"]), 1)
        self.assertEqual(out["back"], {})
        self.assertEqual(out["refused"], [[400, {"error": "bad day"}]] * 3 + [[400, {"error": "bad id"}]] * 4)
        self.assertTrue(out["unchanged"])
        self.assertEqual(out["kept"], [200, True, False])
        self.assertEqual(out["gone"], [200, False])
        self.assertFalse(out["plain"])
        self.assertEqual(out["locked"], 401)

    def test_the_function_never_writes_a_ledger(self):
        # Only the Mac's server folds (server.py, tidy_daily): this function has no request that does.
        source = STATE.read_text(encoding="utf-8")
        self.assertNotIn("foldMarks", source)
        self.assertEqual(source.count("redis('HSET', MARKS"), 1)
        self.assertIn("const guard = dailyGuard(id, Boolean(body.done), now.slice(0, 10));", source)


if __name__ == "__main__":
    unittest.main()
