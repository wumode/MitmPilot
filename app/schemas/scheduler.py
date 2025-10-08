from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field


class ScheduledTask(BaseModel):
    name: str
    provider_name: str | None = None
    running: bool = False
    pid: str | None = None
    kwargs: dict = Field(default_factory=dict)
    func: Callable[..., Any]
