import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated

import redis
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, BaseModel

from memory_repository import InMemoryTaskRepository
from repository import TaskRepository

load_dotenv()


def build_repository() -> TaskRepository:
    """The only place that decides where tasks are stored.

    Set DATABASE_URL and tasks live in Postgres and survive a restart. Leave it unset and they
    live in a list and do not. Nothing below this function knows the difference.
    """
    connection_string = os.getenv("DATABASE_URL")
    if not connection_string:
        return InMemoryTaskRepository()

    from postgres_repository import PostgresTaskRepository

    return PostgresTaskRepository(connection_string)


repository: TaskRepository = build_repository()

logger = logging.getLogger("uvicorn.error")

# Nothing is cached in Redis yet. It is wired up now so /health proves the connection works
# before anything depends on it.
redis_url = os.getenv("REDIS_URL")
redis_client = redis.from_url(redis_url) if redis_url else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    repository.connect()
    yield
    repository.close()


app = FastAPI(
    title="Task API",
    version="1.0",
    description="A small to-do API. Tasks live in Postgres when DATABASE_URL is set, in memory otherwise.",
    lifespan=lifespan,
)


def not_blank(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("title must not be empty")
    return cleaned


Title = Annotated[str, AfterValidator(not_blank)]


class Task(BaseModel):
    id: int
    title: str
    done: bool


class TaskCreate(BaseModel):
    title: Title


class TaskUpdate(BaseModel):
    title: Title | None = None
    done: bool | None = None


class ErrorResponse(BaseModel):
    error: str


NOT_FOUND = {404: {"model": ErrorResponse, "description": "No task has that id"}}
BAD_BODY = {400: {"model": ErrorResponse, "description": "The request body is invalid"}}


# FastAPI renders errors as {"detail": ...}; this API's contract is {"error": ...}.
@app.exception_handler(HTTPException)
def render_error(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


LOCATIONS = {
    "body": "request body",
    "query": "query parameter",
    "path": "path parameter",
}


# Pydantic rejects bad input with 422; the API contract calls for 400.
@app.exception_handler(RequestValidationError)
def render_validation_error(request: Request, exc: RequestValidationError):
    first = exc.errors()[0]
    location = first["loc"]
    where = LOCATIONS.get(location[0], "request")
    reason = first["msg"].removeprefix("Value error, ")
    # loc is ("body",) when the body is missing entirely, ("body", "title") when a field is at fault.
    if len(location) > 1:
        message = f"Invalid {where}: '{location[-1]}' {reason}"
    else:
        message = f"Invalid {where}: {reason}"
    return JSONResponse(status_code=400, content={"error": message})


# FastAPI documents a 422 on every route, but render_validation_error turns those into 400s,
# so a 422 can never reach a client. Drop it rather than publish a response the API never sends.
def openapi_without_422():
    if not app.openapi_schema:
        app.openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        for operations in app.openapi_schema["paths"].values():
            for operation in operations.values():
                operation["responses"].pop("422", None)
        schemas = app.openapi_schema["components"]["schemas"]
        for orphan in ("HTTPValidationError", "ValidationError"):
            schemas.pop(orphan, None)
    return app.openapi_schema


app.openapi = openapi_without_422


def task_or_404(task: dict | None, task_id: int) -> dict:
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@app.get("/", summary="Describe this API")
def read_root():
    return {"name": "Task API", "version": "1.0", "endpoints": ["/tasks"]}


@app.get("/health", summary="Check the server and its dependencies are alive")
def read_health():
    health = {"status": "ok", "storage": repository.name}
    if redis_client is None:
        return health
    try:
        redis_client.ping()
        health["redis"] = "ok"
    except redis.RedisError as exc:
        # A dead cache must not make the server look dead, but it must not pass silently either.
        logger.warning("Redis ping failed: %s", exc)
        health["redis"] = "unavailable"
    return health


@app.get("/tasks", response_model=list[Task], summary="List tasks, optionally filtered")
def list_tasks(
    done: Annotated[
        bool | None, Query(description="Only tasks with this done state")
    ] = None,
    search: Annotated[
        str | None, Query(description="Only tasks whose title contains this")
    ] = None,
):
    return repository.list_tasks(done=done, search=search)


@app.get("/stats", summary="Count tasks by state")
def read_stats():
    return repository.count_tasks()


@app.post("/reset", response_model=list[Task], summary="Restore the example tasks")
def reset_tasks():
    return repository.reset_tasks()


@app.get(
    "/tasks/{task_id}",
    response_model=Task,
    responses=NOT_FOUND,
    summary="Get one task by id",
)
def read_task(task_id: int):
    return task_or_404(repository.get_task(task_id), task_id)


@app.post(
    "/tasks",
    response_model=Task,
    status_code=status.HTTP_201_CREATED,
    responses=BAD_BODY,
    summary="Create a task",
)
def create_task(payload: TaskCreate):
    return repository.create_task(payload.title)


@app.put(
    "/tasks/{task_id}",
    response_model=Task,
    responses=NOT_FOUND | BAD_BODY,
    summary="Update a task's title and/or done flag",
)
def update_task(task_id: int, payload: TaskUpdate):
    # Drop unset fields and explicit nulls, so {"title": null} reads as invalid, not as a blank title.
    changes = {
        field: value
        for field, value in payload.model_dump(exclude_unset=True).items()
        if value is not None
    }
    if not changes:
        raise HTTPException(
            status_code=400,
            detail="Invalid request body: provide 'title' and/or 'done'",
        )
    return task_or_404(repository.update_task(task_id, changes), task_id)


@app.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_FOUND,
    summary="Delete a task",
)
def delete_task(task_id: int):
    if not repository.delete_task(task_id):
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
