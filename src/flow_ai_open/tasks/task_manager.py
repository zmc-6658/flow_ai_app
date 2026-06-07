from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from enum import StrEnum
from typing import Any, Callable
from uuid import uuid4

from flow_ai.contracts.error_codes import ErrorCode
from flow_ai.contracts.status_shell import StatusShell


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskInfo:
    __slots__ = ("task_id", "status", "result", "error", "message")

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.status: TaskStatus = TaskStatus.PENDING
        self.result: Any = None
        self.error: ErrorCode | None = None
        self.message: str = ""


class TaskManager:

    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: dict[str, TaskInfo] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        task_id = str(uuid4())
        info = TaskInfo(task_id)
        with self._lock:
            self._tasks[task_id] = info

        def _run() -> None:
            info.status = TaskStatus.RUNNING
            try:
                info.result = fn(*args, **kwargs)
                info.status = TaskStatus.COMPLETED
            except Exception as exc:
                info.status = TaskStatus.FAILED
                info.error = ErrorCode.INTERNAL_ERROR
                info.message = str(exc)

        self._executor.submit(_run)
        return task_id

    def get_status(self, task_id: str) -> StatusShell[TaskInfo]:
        with self._lock:
            info = self._tasks.get(task_id)
        if info is None:
            return StatusShell(
                data=None,
                error_code=ErrorCode.TASK_NOT_FOUND,
                message=f"任务不存在: {task_id}",
            )
        return StatusShell(data=info)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)
