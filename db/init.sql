-- Postgres runs every .sql file in /docker-entrypoint-initdb.d once, the first time the data
-- directory is empty. On later starts the volume already holds a database, so this never reruns
-- and nothing here overwrites data you created.

CREATE TABLE IF NOT EXISTS tasks (
    id    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title TEXT    NOT NULL CHECK (btrim(title) <> ''),
    done  BOOLEAN NOT NULL DEFAULT FALSE
);

-- GET /tasks?search=milk runs `title ILIKE '%milk%'`. A plain btree index cannot answer that:
-- a leading wildcard has no prefix to seek on, so Postgres reads every row. Trigram indexes can,
-- because they index three-character fragments rather than whole values.
-- See the README for the EXPLAIN ANALYZE numbers behind this choice.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS tasks_title_trgm_idx ON tasks USING gin (title gin_trgm_ops);

INSERT INTO tasks (title, done) VALUES
    ('Read the assignment', TRUE),
    ('Build the Task API', FALSE),
    ('Push to GitHub', FALSE);
