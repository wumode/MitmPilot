from typing import Any

from mitmproxy.http import HTTPFlow

from app.log import logger
from app.schemas import Hook
from app.schemas.types import HookEventType
from app.utils.rule import HttpFlowMatcher


class HookChainBase:
    def __init__(self):
        self.hooks: dict[HookEventType, list[Hook]] = {}
        for event in HookEventType:
            self.hooks.setdefault(event, [])

    def add_hook(self, event: HookEventType, event_hook: Hook):
        """Adds a hook to the chain for a specific event type. Hooks are inserted based
        on their priority, maintaining a sorted order (higher priority hooks come
        first).

        :param event: The type of event the hook should respond to.
        :param event_hook: The Hook object to add.
        """
        for index, hook in enumerate(self.hooks.setdefault(event, [])):
            if hook.priority < event_hook.priority:
                self.hooks[event].insert(index, event_hook)
                return
        self.hooks[event].append(event_hook)

    def remove_hooks_by_id(self, hook_id: str, event_type: HookEventType | None = None):
        """Removes hooks by their ID.

        :param hook_id: The ID of the hook(s) to remove.
        :param event_type: Optional. If provided, only hooks for this specific event
            type will be removed. If None, hooks with the given ID will be removed from
            all event types.
        """
        event_types = list(self.hooks.keys()) if event_type is None else [event_type]
        for event in event_types:
            self.hooks[event] = [
                hook for hook in self.hooks.get(event, []) if hook.id != hook_id
            ]


class HookChain(HookChainBase):
    def _execute_hooks(self, event: HookEventType, *args: Any, **kwargs: Any):
        """Generic hook executor that handles state checking, async calls, and
        priority."""
        if event not in self.hooks:
            return

        for hook in self.hooks[event]:
            # Check addon state before executing the hook.
            if not hook.addon_state():
                continue
            if hook.rule is not None and not HttpFlowMatcher.matches(
                hook.rule, *args, **kwargs
            ):
                return

            try:
                hook.func(*args, **kwargs)
            except Exception as e:
                logger.error(
                    f"Error executing hook for event '{event.value}' "
                    f"in addon '{hook.id}': {e}",
                    exc_info=True,
                )

            # If ignore_rest is set, stop processing further hooks for this event.
            if hook.ignore_rest:
                break

    def request(self, flow: HTTPFlow):
        self._execute_hooks(HookEventType.request, flow)

    def response(self, flow: HTTPFlow):
        self._execute_hooks(HookEventType.response, flow)


class AsyncHookChain(HookChainBase):
    async def _execute_hooks(self, event: HookEventType, *args: Any, **kwargs: Any):
        """Generic hook executor that handles state checking, async calls, and
        priority."""
        if event not in self.hooks:
            return

        for hook in self.hooks[event]:
            # Check the addon state before executing the hook.
            if not hook.addon_state():
                continue
            if hook.rule is not None and not HttpFlowMatcher.matches(
                hook.rule, *args, **kwargs
            ):
                return

            try:
                # Check if the hook function is async and await it if so.
                await hook.func(*args, **kwargs)
            except Exception as e:
                logger.error(
                    f"Error executing hook for event '{event.value}' "
                    f"in addon '{hook.id}': {e}",
                    exc_info=True,
                )

            # If ignore_rest is set, stop processing further hooks for this event.
            if hook.ignore_rest:
                break

    async def request(self, flow: HTTPFlow):
        await self._execute_hooks(HookEventType.request, flow)

    async def response(self, flow: HTTPFlow):
        await self._execute_hooks(HookEventType.response, flow)
