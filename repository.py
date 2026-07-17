from abc import ABC, abstractmethod


class TaskRepository(ABC):
    """Storage for tasks.

    Implementations decide where tasks live. Nothing here knows about HTTP: a missing task is
    reported as None or False, and the route layer turns that into a 404.
    """

    def connect(self) -> None:
        """Acquire whatever the implementation needs. Called once at startup."""

    def close(self) -> None:
        """Release it again. Called once at shutdown."""

    @abstractmethod
    def list_tasks(self, done: bool | None = None, search: str | None = None) -> list[dict]:
        """Every task, filtered by done state and/or a case-insensitive title match."""

    @abstractmethod
    def get_task(self, task_id: int) -> dict | None:
        """One task, or None if no task has that id."""

    @abstractmethod
    def create_task(self, title: str) -> dict:
        """Store a new task with done=False and return it, id included."""

    @abstractmethod
    def update_task(self, task_id: int, changes: dict) -> dict | None:
        """Apply changes to a task and return it, or None if no task has that id."""

    @abstractmethod
    def delete_task(self, task_id: int) -> bool:
        """Remove a task. True if it existed, False otherwise."""

    @abstractmethod
    def count_tasks(self) -> dict:
        """Totals as {"total": int, "done": int, "open": int}."""

    @abstractmethod
    def reset_tasks(self) -> list[dict]:
        """Discard everything, restore the example tasks, and return them."""
