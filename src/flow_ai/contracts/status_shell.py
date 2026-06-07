from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from flow_ai.contracts.error_codes import ErrorCode

T = TypeVar("T")


class StatusShell(BaseModel, Generic[T]):
    status: str = "success"
    schema_version: str = "v3"
    data: T | None = None
    error_code: ErrorCode | None = None
    message: str = ""
    recoverable: bool = True
