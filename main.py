from typing import Annotated

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, BaseModel

app = FastAPI(
    title="Task API",
    version="1.0",
    description="A small to-do API with in-memory storage. Data resets when the server restarts.",
)

TASKS = [
    {"id": 1, "title": "Read the assignment", "done": True},
    {"id": 2, "title": "Build the Task API", "done": False},
    {"id": 3, "title": "Push to GitHub", "done": False},
]


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


# Pydantic rejects a bad body with 422; the API contract calls for 400.
@app.exception_handler(RequestValidationError)
def render_validation_error(request: Request, exc: RequestValidationError):
    first = exc.errors()[0]
    field = first["loc"][-1]
    message = f"Invalid request body: '{field}' {first['msg'].removeprefix('Value error, ')}"
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


def find_index(task_id: int) -> int:
    for index, task in enumerate(TASKS):
        if task["id"] == task_id:
            return index
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found")


def next_id() -> int:
    # max + 1, not len + 1, so ids stay unique after a delete.
    return max((task["id"] for task in TASKS), default=0) + 1


@app.get("/", summary="Describe this API")
def read_root():
    return {"name": "Task API", "version": "1.0", "endpoints": ["/tasks"]}


@app.get("/health", summary="Check the server is alive")
def read_health():
    return {"status": "ok"}


@app.get("/tasks", response_model=list[Task], summary="List every task")
def list_tasks():
    return TASKS


@app.get(
    "/tasks/{task_id}",
    response_model=Task,
    responses=NOT_FOUND,
    summary="Get one task by id",
)
def read_task(task_id: int):
    return TASKS[find_index(task_id)]


@app.post(
    "/tasks",
    response_model=Task,
    status_code=status.HTTP_201_CREATED,
    responses=BAD_BODY,
    summary="Create a task",
)
def create_task(payload: TaskCreate):
    task = {"id": next_id(), "title": payload.title, "done": False}
    TASKS.append(task)
    return task


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
            status_code=400, detail="Invalid request body: provide 'title' and/or 'done'"
        )
    index = find_index(task_id)
    TASKS[index] = {**TASKS[index], **changes}
    return TASKS[index]


@app.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_FOUND,
    summary="Delete a task",
)
def delete_task(task_id: int):
    index = find_index(task_id)
    TASKS.pop(index)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
