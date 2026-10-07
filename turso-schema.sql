-- SchoolHub's tables in a Turso database (README, "Marks, tasks and data.js in Turso").
--
-- Run it once on a database of your own: turso db shell <database> < turso-schema.sql
-- If another app owns the database and makes these tables with its own migrations, do not run
-- it there: that app's migration would then find the tables already made and fail.

-- Marks and tasks as SchoolHub keeps them (state/marks.json, state/tasks.json): name is 'marks'
-- or 'tasks', key the assignment id or task id, value_json the object.
CREATE TABLE school_kv (
  name        TEXT NOT NULL CHECK (name IN ('marks', 'tasks')),
  key         TEXT NOT NULL,
  value_json  TEXT NOT NULL,
  updated_at  INTEGER NOT NULL,
  PRIMARY KEY (name, key)
) STRICT;

-- The latest synced data.js, one row: the text sync.py writes (assignments, grades, feedback, and
-- each file's name and its place on your Mac; never the files themselves).
CREATE TABLE school_data (
  id          INTEGER PRIMARY KEY CHECK (id = 1),
  data_js     TEXT NOT NULL,
  synced_at   INTEGER NOT NULL
) STRICT;
