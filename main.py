from typing import Annotated

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, BaseModel

app = FastAPI()

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


class TaskCreate(BaseModel):
    title: Title


class TaskUpdate(BaseModel):
    title: Title | None = None
    done: bool | None = None


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


def find_index(task_id: int) -> int:
    for index, task in enumerate(TASKS):
        if task["id"] == task_id:
            return index
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found")


def next_id() -> int:
    # max + 1, not len + 1, so ids stay unique after a delete.
    return max((task["id"] for task in TASKS), default=0) + 1


@app.get("/")
def read_root():
    return {"name": "Task API", "version": "1.0", "endpoints": ["/tasks"]}


@app.get("/health")
def read_health():
    return {"status": "ok"}


@app.get("/tasks")
def list_tasks():
    return TASKS


@app.get("/tasks/{task_id}")
def read_task(task_id: int):
    return TASKS[find_index(task_id)]


@app.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate):
    task = {"id": next_id(), "title": payload.title, "done": False}
    TASKS.append(task)
    return task


@app.put("/tasks/{task_id}")
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


@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int):
    index = find_index(task_id)
    TASKS.pop(index)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
