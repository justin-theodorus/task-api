from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI()

TASKS = [
    {"id": 1, "title": "Read the assignment", "done": True},
    {"id": 2, "title": "Build the Task API", "done": False},
    {"id": 3, "title": "Push to GitHub", "done": False},
]


# FastAPI renders errors as {"detail": ...}; this API's contract is {"error": ...}.
@app.exception_handler(HTTPException)
def render_error(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


def find_task(task_id: int):
    for task in TASKS:
        if task["id"] == task_id:
            return task
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found")


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
    return find_task(task_id)
