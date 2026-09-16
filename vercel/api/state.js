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
      const existing = await redis('HGET', TASKS, id);
      const task = {
        id,
        name,
        course_id: clip(body.course_id, 80) || 'personal',
        due_at: due,
        all_day: Boolean(due) && Boolean(body.all_day),
        notes: clip(body.notes, 5000),
        created_at: (existing && JSON.parse(existing).created_at) || body.created_at || now,
        updated_at: now,
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
