# Task API

A small to-do API built with FastAPI. It supports the four CRUD operations (create, read, update,
delete) over a list of tasks, and documents itself with Swagger UI.

Tasks are stored in **Postgres**, running in Docker with a volume, so they survive a restart. The
original in-memory store is still in the codebase and still works: which one runs is decided by a
single environment variable. See [Swapping the store](#swapping-the-store) and
[Proving it persists](#proving-it-persists).

A task looks like this:

```json
{ "id": 1, "title": "Read the assignment", "done": false }
```

## Run the whole stack with one command

Requires Docker.

```bash
cp .env.example .env
docker compose up
```

That builds the app image and starts three containers: the API, Postgres, and Redis. The API waits
for the database to report healthy before it starts, so the first request always works.

- API: `http://localhost:8001`
- Interactive docs: `http://localhost:8001/docs`
- Postgres, from your machine: `psql postgresql://tasks:...@localhost:5433/tasks`

Stop it with `docker compose down`. Your tasks survive that. To throw the data away as well, use
`docker compose down -v`, which deletes the volume.

### About the ports

Inside Docker the services always listen on their standard ports (Postgres 5432, Redis 6379, the app
8000), and they reach each other by service name on compose's private network. The app finds the
database at `db:5432` no matter what your machine is doing.

The only numbers that can clash with programs already on your computer are the **published** ports,
the left-hand side of each mapping in `docker-compose.yml`. They default to 5433, 6379 and 8001, and
`.env` can change them. 5433 is deliberate: a Postgres already running locally usually owns 5432, and
publishing on 5433 leaves it alone.

### Running the app outside Docker

The database can stay in Docker while the app runs on your machine, which is nicer for editing code:

```bash
docker compose up -d db
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload --port 8001
```

This is why `.env` contains a `DATABASE_URL` pointing at `localhost:5433`: it is the address of the
container's published port as seen from your machine. Inside compose, the app service overrides that
variable with the `db:5432` internal address.

## Configuration

`.env` is **gitignored** and never committed, because a connection string is a credential.
`.env.example` is committed and documents every variable, so a stranger runs `cp .env.example .env`
and has a working setup.

| Variable | What it does |
|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Credentials compose uses to create the database on first run |
| `DATABASE_URL` | Where the app looks for tasks. **Unset it and the app falls back to in-memory storage.** |
| `REDIS_URL` | Where the app pings Redis. Unset it and `/health` simply omits Redis. |
| `POSTGRES_HOST_PORT`, `REDIS_HOST_PORT`, `APP_HOST_PORT` | Published ports, for avoiding clashes |

## Endpoints

| Method | Path | What it does | Success | Errors |
|---|---|---|---|---|
| GET | `/` | Describe this API | 200 | |
| GET | `/health` | Check the server, its store, and Redis | 200 | |
| GET | `/tasks` | List tasks | 200 | 400 bad query |
| GET | `/tasks/{id}` | Get one task | 200 | 404 unknown id |
| POST | `/tasks` | Create a task | 201 | 400 missing or empty title |
| PUT | `/tasks/{id}` | Update a task's title and/or done | 200 | 400 empty body, 404 unknown id |
| DELETE | `/tasks/{id}` | Delete a task | 204 (no body) | 404 unknown id |
| GET | `/stats` | Count tasks by state | 200 | |
| POST | `/reset` | Restore the three example tasks | 200 | |

Every error returns JSON in one shape, so a client only ever parses one thing:

```json
{ "error": "Task 99 not found" }
```

`/health` reports which store is live, which is the quickest way to tell whether you are talking to
Postgres or to a list:

```console
$ curl -s http://localhost:8001/health
{"status":"ok","storage":"postgres","redis":"ok"}
```

### Filtering and searching

`GET /tasks` takes two optional query parameters, and they combine:

| Request | Returns |
|---|---|
| `/tasks?done=true` | only finished tasks |
| `/tasks?search=milk` | tasks whose title contains "milk", case-insensitive |
| `/tasks?done=false&search=api` | unfinished tasks matching "api" |

### Validation rules

The server never trusts the client:

- `title` must be present and must not be empty or only whitespace.
- `PUT` needs at least one of `title` or `done`; an empty body `{}` is rejected.
- A bad value anywhere (`?done=maybe`, `/tasks/abc`) is a 400, and the message names the offending
  parameter.

## A real request cycle

Pasted verbatim from a terminal, showing the full create, read, update, delete cycle and both error
codes:

```console
$ curl -i -X POST http://localhost:8001/tasks -H "Content-Type: application/json" -d '{"title":"Buy milk"}'
HTTP/1.1 201 Created
date: Fri, 17 Jul 2026 01:29:48 GMT
server: uvicorn
content-length: 40
content-type: application/json

{"id":4,"title":"Buy milk","done":false}

$ curl -i http://localhost:8001/tasks/4
HTTP/1.1 200 OK
date: Fri, 17 Jul 2026 01:29:48 GMT
server: uvicorn
content-length: 40
content-type: application/json

{"id":4,"title":"Buy milk","done":false}

$ curl -i -X PUT http://localhost:8001/tasks/4 -H "Content-Type: application/json" -d '{"done":true}'
HTTP/1.1 200 OK
date: Fri, 17 Jul 2026 01:29:48 GMT
server: uvicorn
content-length: 39
content-type: application/json

{"id":4,"title":"Buy milk","done":true}

$ curl -i -X DELETE http://localhost:8001/tasks/4
HTTP/1.1 204 No Content
date: Fri, 17 Jul 2026 01:29:48 GMT
server: uvicorn

$ curl -i http://localhost:8001/tasks/4
HTTP/1.1 404 Not Found
date: Fri, 17 Jul 2026 01:29:48 GMT
server: uvicorn
content-length: 28
content-type: application/json

{"error":"Task 4 not found"}

$ curl -i -X POST http://localhost:8001/tasks -H "Content-Type: application/json" -d '{}'
HTTP/1.1 400 Bad Request
date: Fri, 17 Jul 2026 01:29:48 GMT
server: uvicorn
content-length: 56
content-type: application/json

{"error":"Invalid request body: 'title' Field required"}
```

## Swagger UI

FastAPI generates an OpenAPI description from the code, and Swagger UI turns it into a page where
every endpoint has a "Try it out" button that sends a real request. Open
`http://localhost:8001/docs`:

![Swagger UI listing every endpoint of the Task API](docs/swagger.jpg)

## Swapping the store

This is the part the architecture is supposed to make boring, so here is exactly what happened,
including the part that does not flatter the design.

`repository.py` defines `TaskRepository`: seven methods, no HTTP, no SQL. Two classes implement it,
`InMemoryTaskRepository` and `PostgresTaskRepository`, and one function in `main.py` picks between
them:

```python
def build_repository() -> TaskRepository:
    connection_string = os.getenv("DATABASE_URL")
    if not connection_string:
        return InMemoryTaskRepository()
    from postgres_repository import PostgresTaskRepository
    return PostgresTaskRepository(connection_string)
```

**Honestly: the routes did change, once.** The previous version had no repository layer at all. The
route handlers read and wrote a module-level `TASKS` list directly, and a 404 was raised from a
helper that walked that list. There was no interface to swap, so the first commit of this stage
extracted one and pointed the routes at it. That refactor changed every route.

**After that, adding Postgres changed no route.** The Postgres work touched `postgres_repository.py`
(new), `db/init.sql` (new), and the `build_repository` function. Not one route handler, not one
Pydantic model, not one status code. The `git log` shows the two commits separately so you can check.

The lesson is the honest version of the assignment's claim: layering does make "switch storage" a
one-file change, but only once the layer exists. It is not free, it is paid for in advance.

You can watch the swap happen. The `/health` endpoint reports the live store, so with the database up:

```console
$ curl -s http://localhost:8001/health
{"status":"ok","storage":"postgres","redis":"ok"}

$ DATABASE_URL= REDIS_URL= .venv/bin/uvicorn main:app --port 8003
$ curl -s http://localhost:8003/health
{"status":"ok","storage":"memory"}
```

Same code, same routes, different store.

## Proving it persists

The A2 version of this project lost everything on restart, because the tasks lived in a Python list
inside the process. This is the same experiment, run against Postgres. Verbatim:

```console
### 1. Create two tasks
$ curl -s -X POST http://localhost:8001/tasks -H "Content-Type: application/json" -d '{"title":"Survive the restart"}'
{"id":4,"title":"Survive the restart","done":false}
$ curl -s -X POST http://localhost:8001/tasks -H "Content-Type: application/json" -d '{"title":"Prove it with psql"}'
{"id":5,"title":"Prove it with psql","done":false}

### 2. Destroy the app AND the database container
$ docker compose down
 Container crud-app-1  Removed
 Container crud-db-1  Removed
 Container crud-redis-1  Removed
 Network crud_default  Removed

### 3. Start again from scratch
$ docker compose up -d

### 4. Still there
$ curl -s http://localhost:8001/tasks
[{"id":1,...},{"id":2,...},{"id":3,...},{"id":4,"title":"Survive the restart","done":false},{"id":5,"title":"Prove it with psql","done":false}]

### 5. Confirmed in the database itself, bypassing the app
$ docker compose exec db psql -U tasks -d tasks -c "SELECT id, title, done FROM tasks ORDER BY id;"
 id |        title        | done
----+---------------------+------
  1 | Read the assignment | t
  2 | Build the Task API  | f
  3 | Push to GitHub      | f
  4 | Survive the restart | f
  5 | Prove it with psql  | f
(5 rows)
```

The containers were removed, not just stopped, and the rows came back anyway. They live in the
`pgdata` named volume, which Docker keeps independently of any container. That is the whole point of
a volume: containers are disposable, the volume is not.

`docker compose down -v` does delete the volume, and then the data really is gone. Postgres runs
`db/init.sql` only when the data directory is empty, so the next `up` builds the table and seeds the
three example tasks again, exactly like a new machine.

## Why there is an index

`GET /tasks?search=milk` runs `title ILIKE '%milk%'`. Seeded with 200,000 rows, that read every
single one.

The obvious move is a btree index on `title`. Measured with `EXPLAIN ANALYZE`, it looks spectacular
on an exact match:

```console
-- before: no index
Seq Scan on tasks (actual time=6.557..8.573 rows=1 loops=1)
  Filter: (title = 'Seeded task number 154321'::text)
  Rows Removed by Filter: 200003
Execution Time: 8.607 ms

-- after: CREATE INDEX tasks_title_idx ON tasks (title);
Index Scan using tasks_title_idx on tasks (actual time=0.033..0.033 rows=1 loops=1)
  Index Cond: (title = 'Seeded task number 154321'::text)
Execution Time: 0.082 ms
```

8.607 ms to 0.082 ms, about 105x faster.

**Except that index does nothing for this app.** It only helps `title = 'exact value'`, and no
endpoint here ever does that. Running the query the app actually issues, with the btree index in
place:

```console
-- title ILIKE '%154321%', WITH the btree index available
Gather Merge (actual time=30.198..31.216 rows=1 loops=1)
  Workers Planned: 1
  ->  Parallel Seq Scan on tasks
Execution Time: 31.216 ms
```

Still a sequential scan. A btree stores whole values in sorted order, so it can seek to a known
prefix, and `'%milk%'` has no prefix to seek to. Postgres ignored the index because it was useless,
not because it was misconfigured.

The index that does work is a trigram index, which indexes every three-character fragment instead of
whole values, so an unanchored substring becomes something the database can look up:

```console
-- after: CREATE EXTENSION pg_trgm;
--        CREATE INDEX tasks_title_trgm_idx ON tasks USING gin (title gin_trgm_ops);
Bitmap Heap Scan on tasks (actual time=0.054..0.054 rows=1 loops=1)
  Recheck Cond: (title ~~* '%154321%'::text)
  ->  Bitmap Index Scan on tasks_title_trgm_idx
        Index Cond: (title ~~* '%154321%'::text)
Execution Time: 0.128 ms
```

31.2 ms to 0.128 ms, roughly 240x, on the query this API really runs. That is the one in
`db/init.sql`. The btree stayed out of the schema: an index nothing queries still costs disk and
slows every write.

The lesson is that an index is not a speed setting you switch on. It has to match the shape of the
question being asked, and `EXPLAIN ANALYZE` is how you find out whether it does.

## Redis

Redis is in the compose file and nothing caches to it yet. It is wired up early because W4 needs it,
and because a dependency that is merely declared is not proven. `/health` pings it on every call, so
a broken connection shows up immediately rather than next week:

```console
$ curl -s http://localhost:8001/health
{"status":"ok","storage":"postgres","redis":"ok"}
```

If Redis is down, `/health` reports `"redis":"unavailable"` and logs a warning, but still returns
200. A dead cache is not a dead server, and the health check should not lie in either direction.

## How it is built

| File | Job |
|---|---|
| `main.py` | HTTP only: routes, validation, status codes, error shape. Picks a store, never touches one. |
| `repository.py` | The `TaskRepository` interface. Knows nothing about HTTP or SQL. |
| `memory_repository.py` | Tasks in a Python list. |
| `postgres_repository.py` | Tasks in Postgres, via a psycopg connection pool. |
| `seed.py` | The three example tasks, shared by both stores. |
| `db/init.sql` | Table, extension, index, seed rows. Runs once, on an empty volume. |
| `docker-compose.yml` | app + Postgres + Redis, with the volume and the healthchecks. |

Reading order: `repository.py` tells you what a store must do, `main.py` tells you what HTTP does
with it, and the two repository implementations are just two answers to the same question.

Two details in `main.py` are worth knowing, because they are not obvious. FastAPI reports errors as
`{"detail": ...}` and rejects invalid input with a 422, but this API promises `{"error": ...}` and a
400; two exception handlers translate between them. And because those handlers mean a 422 can never
actually reach a client, the OpenAPI schema is post-processed to stop advertising one.
