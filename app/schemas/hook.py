from collections.abc import Callable, Coroutine
from typing import Any

from mitmproxy.http import HTTPFlow
from pydantic import BaseModel

from app.schemas.rule import RuleType


class HookData(BaseModel):
    condition_string: str | None = None
    # The hook function can be either sync or async
    func: Callable[[HTTPFlow], None] | Callable[[HTTPFlow], Coroutine[Any, Any, None]]
    priority: int | None = None
    ignore_rest: bool | None = False


class Hook(HookData):
    id: str
    priority: int
    rule: RuleType | None
    addon_state: Callable[[], bool]
