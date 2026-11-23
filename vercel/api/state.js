// SchoolHub phone API: your ✓ marks and your own tasks, stored in Upstash Redis (free tier).
//
// GET  /api/state/                         -> {marks, tasks}
// POST /api/state/ {action: "mark", ...}    -> {marks, tasks}
// POST /api/state/ {action: "task", ...}    -> {task, marks, tasks}
// POST /api/state/ {action: "deleteTask"}   -> {removed, marks, tasks}
//
// Every request must send the site's secret path segment as X-SchoolHub-Key. The Redis token stays
// on the server; the browser never sees it.
const crypto = require('crypto');

const DB_URL = process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL;
const DB_TOKEN = process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN;
const SECRET = process.env.SCHOOLHUB_SECRET || '';
const MARKS = 'schoolhub:marks';
const TASKS = 'schoolhub:tasks';
const TASK_ID = /^task:[a-z0-9]{8,32}$/;

async function redis(...command) {
  const response = await fetch(DB_URL, {
    method: 'POST',
    headers: {Authorization: `Bearer ${DB_TOKEN}`, 'Content-Type': 'application/json'},
    body: JSON.stringify(command),
  });
  const data = await response.json();
  if (data.error) throw new Error(data.error);
  return data.result;
}

async function readHash(key) {
  const flat = (await redis('HGETALL', key)) || [];
  const out = {};
  for (let i = 0; i < flat.length; i += 2) {
    try { out[flat[i]] = JSON.parse(flat[i + 1]); } catch { /* skip a corrupt entry */ }
  }
  return out;
}

const readState = async () => ({marks: await readHash(MARKS), tasks: await readHash(TASKS)});

function authorized(req) {
  const given = Buffer.from(String(req.headers['x-schoolhub-key'] || ''));
  const expected = Buffer.from(SECRET);
  return SECRET.length > 0 && given.length === expected.length && crypto.timingSafeEqual(given, expected);
}

const clip = (value, max) => String(value ?? '').trim().slice(0, max);

// ---- daily tasks: the door ----
// A task that repeats has a ✓ a day, a mark under "<task id>@<day>"; the days the Mac's server has
// folded away are in its ledger, the mark "<task id>@done", which only that server writes
// (server.py, "daily tasks: the days done, kept for good"). What a mark request may do is decided
// as server.py's daily_guard decides it, by this server's own day (UTC), and tests/daily_vectors.json
// holds both to the same cases:
//   'bad id'   the ledger: no request makes it or takes it away;
//   'bad day'  a daily ✓ for a day that is none, more than 7 days past or more than 2 ahead;
//   'keep'     taking away a daily ✓ of a day more than 7 days past: it is history, nothing changes;
//   null       any other mark: stored, or removed.
const DAILY_MARK = /^(task:[a-z0-9]{8,32})@([0-9]{4}-[0-9]{2}-[0-9]{2})$/;
const utcDay = (y, m, d) => new Date(Date.UTC(y, m - 1, d)).toISOString().slice(0, 10);
const dayPlus = (day, n) => utcDay(+day.slice(0, 4), +day.slice(5, 7), +day.slice(8, 10) + n);
const realDay = s => /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(s) && s >= '2000-01-01' && dayPlus(s, 0) === s;
function dailyGuard(id, done, today) {
  if (id.endsWith('@done')) return 'bad id';
  const m = DAILY_MARK.exec(id);
  if (!m) return null;
  const day = m[2], cut = dayPlus(today, -7);
  if (done) return realDay(day) && day >= cut && day <= dayPlus(today, 2) ? null : 'bad day';
  return realDay(day) && day < cut ? 'keep' : null;
}

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  if (!authorized(req)) return res.status(401).json({error: 'unauthorized'});
  if (!DB_URL || !DB_TOKEN) return res.status(503).json({error: 'database not connected'});

  try {
    if (req.method === 'GET') return res.json(await readState());
    if (req.method !== 'POST') return res.status(405).json({error: 'method not allowed'});

    const body = req.body && typeof req.body === 'object' ? req.body : JSON.parse(req.body || '{}');
    const now = new Date().toISOString();

    if (body.action === 'mark') {
      const id = clip(body.id, 200);
      if (!id) return res.status(400).json({error: 'missing id'});
      // Decided on the id as it will be stored (trimmed and cut), never as it was sent.
      const guard = dailyGuard(id, Boolean(body.done), now.slice(0, 10));
      if (guard === 'bad id' || guard === 'bad day') return res.status(400).json({error: guard});
      if (guard === 'keep') return res.json(await readState());
      if (body.done) {
        await redis('HSET', MARKS, id, JSON.stringify({
          marked_at: now, name: clip(body.name, 200) || null, course: clip(body.course, 80) || null,
        }));
      } else {
        await redis('HDEL', MARKS, id);
      }
      return res.json(await readState());
    }

    if (body.action === 'task') {
      const id = body.id ? String(body.id) : `task:${crypto.randomBytes(6).toString('hex')}`;
      if (!TASK_ID.test(id)) return res.status(400).json({error: 'bad task id'});
      const name = clip(body.name, 200);
      if (!name) return res.status(400).json({error: 'a task needs a name'});
      const due = body.due_at ? String(body.due_at) : null;
      if (due && Number.isNaN(Date.parse(due))) return res.status(400).json({error: 'due_at must be an ISO date'});
      // A task that repeats (server.py clean_repeat): weekdays 0 (Sunday) to 6, and its last day.
      let repeat = null;
      if (body.repeat) {
        const r = body.repeat, days = r && r.days, until = (r && r.until) || null;
        if (typeof r !== 'object' || Array.isArray(r)) return res.status(400).json({error: 'repeat must be an object'});
        if (!Array.isArray(days) || !days.length || days.some(d => !Number.isInteger(d) || d < 0 || d > 6))
          return res.status(400).json({error: 'repeat needs days, each a weekday from 0 (Sunday) to 6'});
        if (until !== null && (typeof until !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(until) || Number.isNaN(Date.parse(until + 'T00:00:00Z')) || new Date(until + 'T00:00:00Z').toISOString().slice(0, 10) !== until))
          return res.status(400).json({error: "repeat's until must be a date written YYYY-MM-DD"});
        repeat = {days: [...new Set(days)].sort((a, b) => a - b), until};
      }
      const existing = await redis('HGET', TASKS, id);
      const task = {
        id,
        name,
        course_id: clip(body.course_id, 80) || 'personal',
        due_at: repeat ? null : due,
        all_day: !repeat && Boolean(due) && Boolean(body.all_day),
        // Kept at the top, or in the list by date; without the choice, pinned when it has no date.
        pinned: 'pinned' in body ? Boolean(body.pinned) : !due || !!repeat,
        notes: clip(body.notes, 5000),
        created_at: (existing && JSON.parse(existing).created_at) || body.created_at || now,
        updated_at: now,
        ...(repeat ? {repeat} : {}),
      };
      await redis('HSET', TASKS, id, JSON.stringify(task));
      return res.json({task, ...(await readState())});
    }

    if (body.action === 'deleteTask') {
      const id = String(body.id || '');
      const existing = await redis('HGET', TASKS, id);
      await redis('HDEL', TASKS, id);
      return res.json({removed: existing ? JSON.parse(existing) : null, ...(await readState())});
    }

    return res.status(400).json({error: 'unknown action'});
  } catch (error) {
    return res.status(502).json({error: 'database error'});
  }
};
// For the tests (tests/test_state_api.py): the door on its own.
module.exports.dailyGuard = dailyGuard;
