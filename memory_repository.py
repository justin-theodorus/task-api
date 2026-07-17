from repository import TaskRepository

SEED = [
    {"id": 1, "title": "Read the assignment", "done": True},
    {"id": 2, "title": "Build the Task API", "done": False},
    {"id": 3, "title": "Push to GitHub", "done": False},
]


class InMemoryTaskRepository(TaskRepository):
    """Tasks in a Python list. Fast, simple, and gone when the process stops."""

    def __init__(self) -> None:
        self._tasks = self._seed()

    @staticmethod
    def _seed() -> list[dict]:
        # Fresh dicts each time, so a reset cannot hand back mutated seed rows.
        return [dict(task) for task in SEED]

    def _find_index(self, task_id: int) -> int | None:
        for index, task in enumerate(self._tasks):
            if task["id"] == task_id:
                return index
        return None

    def _next_id(self) -> int:
        # max + 1, not len + 1, so ids stay unique after a delete.
        return max((task["id"] for task in self._tasks), default=0) + 1

    def list_tasks(self, done: bool | None = None, search: str | None = None) -> list[dict]:
        tasks = self._tasks
        if done is not None:
            tasks = [task for task in tasks if task["done"] == done]
        if search:
            needle = search.lower()
            tasks = [task for task in tasks if needle in task["title"].lower()]
        return tasks

    def get_task(self, task_id: int) -> dict | None:
        index = self._find_index(task_id)
        return self._tasks[index] if index is not None else None

    def create_task(self, title: str) -> dict:
        task = {"id": self._next_id(), "title": title, "done": False}
        self._tasks.append(task)
        return task

    def update_task(self, task_id: int, changes: dict) -> dict | None:
        index = self._find_index(task_id)
        if index is None:
            return None
        self._tasks[index] = {**self._tasks[index], **changes}
        return self._tasks[index]

    def delete_task(self, task_id: int) -> bool:
        index = self._find_index(task_id)
        if index is None:
            return False
        self._tasks.pop(index)
        return True

    def count_tasks(self) -> dict:
        done = sum(1 for task in self._tasks if task["done"])
        return {"total": len(self._tasks), "done": done, "open": len(self._tasks) - done}

    def reset_tasks(self) -> list[dict]:
        self._tasks = self._seed()
        return self._tasks
