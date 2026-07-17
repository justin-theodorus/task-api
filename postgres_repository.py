from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from repository import TaskRepository
from seed import SEED

COLUMNS = sql.SQL("id, title, done")


class PostgresTaskRepository(TaskRepository):
    """Tasks in a Postgres table. Slower to set up than a list, but it outlives the process."""

    name = "postgres"

    def __init__(self, connection_string: str) -> None:
        # open=False so importing this module never blocks on a database that is still booting.
        self._pool = ConnectionPool(
            connection_string,
            min_size=1,
            open=False,
            kwargs={"row_factory": dict_row},
        )

    def connect(self) -> None:
        self._pool.open(wait=True, timeout=30)

    def close(self) -> None:
        self._pool.close()

    def list_tasks(
        self, done: bool | None = None, search: str | None = None
    ) -> list[dict]:
        query = sql.SQL("SELECT {columns} FROM tasks").format(columns=COLUMNS)
        conditions = []
        params: list = []
        if done is not None:
            conditions.append(sql.SQL("done = %s"))
            params.append(done)
        if search:
            # ILIKE is the case-insensitive match; %s binds the value, so the % wildcards
            # belong to the parameter, not the query text.
            conditions.append(sql.SQL("title ILIKE %s"))
            params.append(f"%{search}%")
        if conditions:
            query = query + sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
        query = query + sql.SQL(" ORDER BY id")

        with self._pool.connection() as conn:
            return conn.execute(query, params).fetchall()

    def get_task(self, task_id: int) -> dict | None:
        with self._pool.connection() as conn:
            query = sql.SQL("SELECT {columns} FROM tasks WHERE id = %s").format(
                columns=COLUMNS
            )
            return conn.execute(query, [task_id]).fetchone()

    def create_task(self, title: str) -> dict:
        with self._pool.connection() as conn:
            query = sql.SQL(
                "INSERT INTO tasks (title, done) VALUES (%s, FALSE) RETURNING {columns}"
            ).format(columns=COLUMNS)
            return conn.execute(query, [title]).fetchone()

    def update_task(self, task_id: int, changes: dict) -> dict | None:
        # changes only ever holds 'title' and/or 'done' (TaskUpdate rejects anything else), but
        # compose the column names as identifiers rather than trusting that from down here.
        assignments = [
            sql.SQL("{column} = %s").format(column=sql.Identifier(column))
            for column in changes
        ]
        query = sql.SQL(
            "UPDATE tasks SET {assignments} WHERE id = %s RETURNING {columns}"
        ).format(
            assignments=sql.SQL(", ").join(assignments),
            columns=COLUMNS,
        )
        with self._pool.connection() as conn:
            return conn.execute(query, [*changes.values(), task_id]).fetchone()

    def delete_task(self, task_id: int) -> bool:
        with self._pool.connection() as conn:
            return (
                conn.execute("DELETE FROM tasks WHERE id = %s", [task_id]).rowcount > 0
            )

    def count_tasks(self) -> dict:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT count(*) AS total, count(*) FILTER (WHERE done) AS done FROM tasks"
            ).fetchone()
        return {
            "total": row["total"],
            "done": row["done"],
            "open": row["total"] - row["done"],
        }

    def reset_tasks(self) -> list[dict]:
        with self._pool.connection() as conn:
            # RESTART IDENTITY so a reset database looks exactly like a fresh one, ids included.
            conn.execute("TRUNCATE tasks RESTART IDENTITY")
            query = sql.SQL(
                "INSERT INTO tasks (title, done) VALUES (%s, %s) RETURNING {columns}"
            ).format(columns=COLUMNS)
            return [
                conn.execute(query, [task["title"], task["done"]]).fetchone()
                for task in SEED
            ]
