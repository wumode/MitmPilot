import asyncio
import importlib
import inspect
import random
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from queue import Empty, PriorityQueue
from typing import Any

from fastapi.concurrency import run_in_threadpool

from app.core.ctx import Context
from app.helper.thread import ThreadHelper
from app.log import logger
from app.schemas import ChainEventData
from app.schemas.types import ChainEventType, EventType
from app.utils.limit import ExponentialBackoffRateLimiter
from app.utils.singleton import Singleton

DEFAULT_EVENT_PRIORITY = 10  # Default priority for events
MIN_EVENT_CONSUMER_THREADS = 1  # Minimum number of event consumer threads
INITIAL_EVENT_QUEUE_IDLE_TIMEOUT_SECONDS = (
    1  # Initial timeout in seconds when the event queue is idle
)
MAX_EVENT_QUEUE_IDLE_TIMEOUT_SECONDS = (
    5  # Maximum timeout in seconds when the event queue is idle
)


class Event:
    """Event class, encapsulating basic event information."""

    def __init__(
        self,
        event_type: EventType | ChainEventType,
        event_data: dict | ChainEventData | None = None,
        priority: int = DEFAULT_EVENT_PRIORITY,
    ):
        """
        :param event_type: The type of the event
        :param event_data: Optional, data carried by the event, defaults to an empty
                           dictionary
        :param priority: Optional, the priority of the event, defaults to 10
        """
        self.event_id = str(uuid.uuid4())  # Event ID
        self.event_type = event_type  # Event type
        self.event_data = event_data or {}  # Event data
        self.priority: int = priority  # Event priority

    def __repr__(self) -> str:
        """Overrides the __repr__ method to return detailed event information, including
        event type, event ID, and priority."""
        event_kind = Event.get_event_kind(self.event_type)
        return (
            f"<{event_kind}: {self.event_type.value}, ID: {self.event_id}, "
            f"Priority: {self.priority}>"
        )

    def __lt__(self, other):
        """Defines the comparison rule for event objects based on priority.

        Events with lower priority are considered "smaller", and events with higher
        priority are considered "larger".
        """
        return self.priority < other.priority

    @staticmethod
    def get_event_kind(event_type: EventType | ChainEventType) -> str:
        """Determines whether an event is a broadcast event or a chain event based on
        its type.

        :param event_type: The event type
        :return: Returns "Broadcast Event" or "Chain Event"
        """
        return "Broadcast Event" if isinstance(event_type, EventType) else "Chain Event"


class EventManager(metaclass=Singleton):
    """EventManager is responsible for managing and dispatching broadcast and chain
    events, including subscribing, sending, and processing events."""

    def __init__(self):
        # Dynamic thread pool for consuming events
        self.__executor = ThreadHelper()
        # Used to store started event consumer threads
        self.__consumer_threads = []
        # Priority queue
        self.__event_queue = PriorityQueue()
        # Subscribers for broadcast events
        self.__broadcast_subscribers: dict[EventType, dict[str, Callable]] = {}
        # Subscribers for chain events
        self.__chain_subscribers: dict[
            ChainEventType, dict[str, tuple[int, Callable]]
        ] = {}
        # Set of disabled event handlers
        self.__disabled_handlers = set()
        # Set of disabled event handler classes
        self.__disabled_classes = set()
        # Thread lock
        self.__lock = threading.Lock()
        # Exit event
        self.__event = threading.Event()

    def start(self):
        """Starts the broadcast event processing threads."""
        # Start consumer threads to process broadcast events
        self.__event.set()
        for _ in range(MIN_EVENT_CONSUMER_THREADS):
            thread = threading.Thread(
                target=self.__broadcast_consumer_loop, daemon=True
            )
            thread.start()
            self.__consumer_threads.append(thread)  # Save the thread object to the list

    def stop(self):
        """Stops the broadcast event processing threads."""
        logger.info("Stopping event processing...")
        self.__event.clear()  # Stop broadcast event processing
        try:
            # Wait for the saved threads to complete by iterating through them
            for consumer_thread in self.__consumer_threads:
                consumer_thread.join()
            logger.info("Event processing stopped.")
        except Exception as e:
            logger.error(
                f"Error stopping event processing threads: "
                f"{str(e)} - {traceback.format_exc()}"
            )

    def check(self, etype: EventType | ChainEventType) -> bool:
        """Checks if there are any enabled event handlers that can respond to a specific
        event type.

        :param etype: The event type
        :return: True if there are available handlers, otherwise False
        """
        if isinstance(etype, ChainEventType):
            handlers = self.__chain_subscribers.get(etype, {})
            return any(
                self.__is_handler_enabled(handler) for _, handler in handlers.values()
            )
        else:
            handlers = self.__broadcast_subscribers.get(etype, {})
            return any(
                self.__is_handler_enabled(handler) for handler in handlers.values()
            )

    def send_event(
        self,
        etype: EventType | ChainEventType,
        data: dict | ChainEventData | None = None,
        priority: int = DEFAULT_EVENT_PRIORITY,
    ) -> Event | None:
        """Sends an event, determining whether it is a broadcast or chain event based on
        its type.

        :param etype: The event type
        :param data: Optional, event data
        :param priority: Priority for broadcast events, defaults to 10
        :return: The processed event data if it is a chain event; otherwise, None
        """
        event = Event(etype, data, priority)
        if isinstance(etype, EventType):
            return self.__trigger_broadcast_event(event)
        elif isinstance(etype, ChainEventType):
            return self.__trigger_chain_event(event)
        else:
            logger.error(f"Unknown event type: {etype}")
        return None

    async def async_send_event(
        self,
        etype: EventType | ChainEventType,
        data: dict | ChainEventData | None = None,
        priority: int = DEFAULT_EVENT_PRIORITY,
    ) -> Event | None:
        """Asynchronously sends an event, determining whether it is a broadcast or chain
        event based on its type.

        :param etype: The event type (EventType or ChainEventType)
        :param data: Optional, event data
        :param priority: Priority for broadcast events, defaults to 10
        :return: The processed event data if it is a chain event; otherwise, None
        """
        event = Event(etype, data, priority)
        if isinstance(etype, EventType):
            return self.__trigger_broadcast_event(event)
        elif isinstance(etype, ChainEventType):
            return await self.__trigger_chain_event_async(event)
        else:
            logger.error(f"Unknown event type: {etype}")
        return None

    def add_event_listener(
        self,
        event_type: EventType | ChainEventType,
        handler: Callable,
        priority: int = DEFAULT_EVENT_PRIORITY,
    ):
        """Registers an event handler by adding it to the corresponding event
        subscription list.

        :param event_type: The event type (EventType or ChainEventType)
        :param handler: The handler
        :param priority: Optional, priority for chain events, defaults to 10; not needed
            for broadcast events
        """
        with self.__lock:
            handler_identifier = self.__get_handler_identifier(handler)

            if isinstance(event_type, ChainEventType):
                # Chain event, sorted by priority
                if event_type not in self.__chain_subscribers:
                    self.__chain_subscribers[event_type] = {}
                handlers = self.__chain_subscribers[event_type]
                if handler_identifier in handlers:
                    handlers.pop(handler_identifier)
                else:
                    logger.debug(
                        f"Subscribed to chain event: {event_type.value}, "
                        f"Priority: {priority} - {handler_identifier}"
                    )
                handlers[handler_identifier] = (priority, handler)
                # Sort by priority
                self.__chain_subscribers[event_type] = dict(
                    sorted(
                        self.__chain_subscribers[event_type].items(),
                        key=lambda x: x[1][0],
                    )
                )
            else:
                # Broadcast event
                if event_type not in self.__broadcast_subscribers:
                    self.__broadcast_subscribers[event_type] = {}
                handlers = self.__broadcast_subscribers[event_type]
                if handler_identifier in handlers:
                    handlers.pop(handler_identifier)
                else:
                    logger.debug(
                        f"Subscribed to broadcast event: "
                        f"{event_type.value} - {handler_identifier}"
                    )
                handlers[handler_identifier] = handler

    def remove_event_listener(
        self, event_type: EventType | ChainEventType, handler: Callable
    ):
        """Removes an event handler by deleting it from the corresponding event's
        subscription list.

        :param event_type: The event type (EventType or ChainEventType)
        :param handler: The handler to be removed
        """
        with self.__lock:
            handler_identifier = self.__get_handler_identifier(handler)

            if (
                isinstance(event_type, ChainEventType)
                and event_type in self.__chain_subscribers
            ):
                self.__chain_subscribers[event_type].pop(handler_identifier, None)
                logger.debug(
                    f"Unsubscribed from chain event: "
                    f"{event_type.value} - {handler_identifier}"
                )
            elif (
                isinstance(event_type, EventType)
                and event_type in self.__broadcast_subscribers
            ):
                self.__broadcast_subscribers[event_type].pop(handler_identifier, None)
                logger.debug(
                    f"Unsubscribed from broadcast event: "
                    f"{event_type.value} - {handler_identifier}"
                )

    def disable_event_handler(self, target: Callable | type):
        """Disables the specified event handler or event handler class.

        :param target: The handler function or class
        """
        identifier = self.__get_handler_identifier(target)
        if (
            identifier in self.__disabled_handlers
            or identifier in self.__disabled_classes
        ):
            return
        if isinstance(target, type):
            self.__disabled_classes.add(identifier)
            logger.debug(f"Disabled event handler class - {identifier}")
        else:
            self.__disabled_handlers.add(identifier)
            logger.debug(f"Disabled event handler - {identifier}")

    def enable_event_handler(self, target: Callable | type):
        """Enables the specified event handler or event handler class.

        :param target: The handler function or class
        """
        identifier = self.__get_handler_identifier(target)
        if isinstance(target, type):
            self.__disabled_classes.discard(identifier)
            logger.debug(f"Enabled event handler class - {identifier}")
        else:
            self.__disabled_handlers.discard(identifier)
            logger.debug(f"Enabled event handler - {identifier}")

    def visualize_handlers(self) -> list[dict]:
        """Visualizes all event handlers, including their disabled status.

        :return: A list of handlers, including event type, handler identifier, priority
            (if any), and status
        """

        def parse_handler_data(data):
            """Parses handler data to determine if it includes a priority.

            :param data: Subscriber data, which can be a tuple or a single value
            :return: (priority, handler), or (None, handler) if no priority is present
            """
            if isinstance(data, tuple) and len(data) == 2:
                return data
            return None, data

        handler_info = []
        # Uniformly handle broadcast and chain events
        for event_type, subscribers in {
            **self.__broadcast_subscribers,
            **self.__chain_subscribers,
        }.items():
            for handler_identifier, handler_data in subscribers.items():
                # Parse priority and handler
                priority, handler = parse_handler_data(handler_data)
                # Check the handler's enabled status
                status = "enabled" if self.__is_handler_enabled(handler) else "disabled"
                # Build the handler information dictionary
                handler_dict = {
                    "event_type": event_type.value,
                    "handler_identifier": handler_identifier,
                    "status": status,
                }
                if priority is not None:
                    handler_dict["priority"] = priority
                handler_info.append(handler_dict)
        return handler_info

    @classmethod
    def __get_handler_identifier(cls, target: Callable | type) -> str:
        """Gets the unique identifier for a handler or handler class, including module
        name and class/method name.

        :param target: The handler function or class
        :return: The unique identifier
        """
        # Uniformly use inspect.getmodule to get the module name
        module = inspect.getmodule(target)
        module_name = module.__name__ if module else "unknown_module"

        # Use __qualname__ to get the qualified name of the target
        qualname = target.__qualname__
        return f"{module_name}.{qualname}"

    @classmethod
    def __get_class_from_callable(cls, handler: Callable) -> str | None:
        """Gets the unique identifier of the class to which a callable object belongs.

        :param handler: The callable object (function, method, etc.)
        :return: The unique identifier of the class
        """
        # For bound methods, get the class via __self__.__class__
        if inspect.ismethod(handler) and hasattr(handler, "__self__"):
            return cls.__get_handler_identifier(handler.__self__.__class__)

        # For class instances (implementing the __call__ method)
        if not inspect.isfunction(handler) and callable(handler):
            handler_cls = handler.__class__  # noqa
            return cls.__get_handler_identifier(handler_cls)

        # For unbound methods, static methods, class methods, extract class
        # information using __qualname__
        qualname_parts = handler.__qualname__.split(".")
        if len(qualname_parts) > 1:
            class_name = ".".join(qualname_parts[:-1])
            module = inspect.getmodule(handler)
            module_name = module.__name__ if module else "unknown_module"
            return f"{module_name}.{class_name}"
        return None

    def __is_handler_enabled(self, handler: Callable) -> bool:
        """Checks if a handler is enabled (not disabled).

        :param handler: The handler function
        :return: True if the handler is enabled, otherwise False
        """
        # Get the unique identifier of the handler
        handler_id = self.__get_handler_identifier(handler)

        # Get the unique identifier of the class to which the handler belongs
        class_id = self.__get_class_from_callable(handler)

        # Check if the handler or its class is disabled; returns False if either is disabled
        if handler_id in self.__disabled_handlers or (
            class_id is not None and class_id in self.__disabled_classes
        ):
            return False

        return True

    def __trigger_chain_event(self, event: Event) -> Event | None:
        """Triggers a chain event, calling subscribed handlers in order and recording
        processing time."""
        logger.debug(f"Triggering synchronous chain event: {event}")
        dispatch = self.__dispatch_chain_event(event)
        return event if dispatch else None

    async def __trigger_chain_event_async(self, event: Event) -> Event | None:
        """Asynchronously triggers a chain event, calling subscribed handlers in order
        and recording processing time."""
        logger.debug(f"Triggering asynchronous chain event: {event}")
        dispatch = await self.__dispatch_chain_event_async(event)
        return event if dispatch else None

    def __trigger_broadcast_event(self, event: Event):
        """Triggers a broadcast event by inserting it into the priority queue.

        :param event: The event object to be processed
        """
        logger.debug(f"Triggering broadcast event: {event}")
        self.__event_queue.put((event.priority, event))

    def __dispatch_chain_event(self, event: Event) -> bool:
        """Synchronously dispatches a chain event, calling event handlers one by one in
        priority order and recording the processing time for each handler.

        :param event: The event object to be dispatched
        """
        assert isinstance(event.event_type, ChainEventType)
        handlers = self.__chain_subscribers.get(event.event_type, {})
        if not handlers:
            logger.debug(f"No handlers found for chain event: {event}")
            return False

        # Filter for enabled handlers
        enabled_handlers = {
            handler_id: (priority, handler)
            for handler_id, (priority, handler) in handlers.items()
            if self.__is_handler_enabled(handler)
        }

        if not enabled_handlers:
            logger.debug(
                f"No enabled handlers found for chain event: {event}. "
                f"Skipping execution."
            )
            return False

        self.__log_event_lifecycle(event, "Started")
        for _, (priority, handler) in enabled_handlers.items():
            start_time = time.time()
            self.__safe_invoke_handler(handler, event)
            logger.debug(
                f"{self.__get_handler_identifier(handler)} (Priority: {priority}), "
                f"completed in {time.time() - start_time:.3f}s for event: {event}"
            )
        self.__log_event_lifecycle(event, "Completed")
        return True

    async def __dispatch_chain_event_async(self, event: Event) -> bool:
        """Asynchronously dispatches a chain event, calling event handlers one by one in
        priority order and recording the processing time for each handler.

        :param event: The event object to be dispatched
        """
        assert isinstance(event.event_type, ChainEventType)
        handlers = self.__chain_subscribers.get(event.event_type, {})
        if not handlers:
            logger.debug(f"No handlers found for chain event: {event}")
            return False

        # Filter for enabled handlers
        enabled_handlers = {
            handler_id: (priority, handler)
            for handler_id, (priority, handler) in handlers.items()
            if self.__is_handler_enabled(handler)
        }

        if not enabled_handlers:
            logger.debug(
                f"No enabled handlers found for chain event: {event}. "
                f"Skipping execution."
            )
            return False

        self.__log_event_lifecycle(event, "Started")
        for _, (priority, handler) in enabled_handlers.items():
            start_time = time.time()
            await self.__safe_invoke_handler_async(handler, event)
            logger.debug(
                f"{self.__get_handler_identifier(handler)} (Priority: {priority}), "
                f"completed in {time.time() - start_time:.3f}s for event: {event}"
            )
        self.__log_event_lifecycle(event, "Completed")
        return True

    def __dispatch_broadcast_event(self, event: Event):
        """Asynchronously dispatches a broadcast event by calling event handlers one by
        one via a thread pool.

        :param event: The event object to be dispatched
        """
        assert isinstance(event.event_type, EventType)
        handlers = self.__broadcast_subscribers.get(event.event_type, {})
        if not handlers:
            logger.debug(f"No handlers found for broadcast event: {event}")
            return
        # Provide each handler with an independent event instance to prevent modifications
        # to event_data by one handler from affecting others.
        for _, handler in handlers.items():
            # Shallow copy only the top-level dictionary to avoid unnecessary deep copy overhead;
            # this isolates key-level replacements/assignments.
            if isinstance(event.event_data, dict):
                event_data_copy = event.event_data.copy()
            else:
                event_data_copy = event.event_data
            isolated_event = Event(
                event_type=event.event_type,
                event_data=event_data_copy,
                priority=event.priority,
            )
            if inspect.iscoroutinefunction(handler):
                # For asynchronous functions, run them directly in the event loop
                asyncio.run_coroutine_threadsafe(
                    self.__safe_invoke_handler_async(handler, isolated_event),
                    Context.loop,
                )
            else:
                # For synchronous functions, run them in the thread pool
                self.__executor.submit(
                    self.__safe_invoke_handler, handler, isolated_event
                )

    def __safe_invoke_handler(self, handler: Callable, event: Event):
        """Invokes a handler to process a chain or broadcast event.

        :param handler: The handler
        :param event: The event object
        """
        if not self.__is_handler_enabled(handler):
            logger.debug(
                f"Handler {self.__get_handler_identifier(handler)} is disabled. "
                f"Skipping execution"
            )
            return

        self.__invoke_handler_by_type_sync(handler, event)

    async def __safe_invoke_handler_async(self, handler: Callable, event: Event):
        """Asynchronously invokes a handler to process a chain event.

        :param handler: The handler
        :param event: The event object
        """
        if not self.__is_handler_enabled(handler):
            logger.debug(
                f"Handler {self.__get_handler_identifier(handler)} is disabled. "
                f"Skipping execution"
            )
            return

        await self.__invoke_handler_by_type_async(handler, event)

    def __invoke_handler_by_type_sync(self, handler: Callable, event: Event):
        """Synchronously invokes the appropriate method based on the handler type.

        :param handler: The handler
        :param event: The event object to be processed
        """
        class_name, method_name = self.__parse_handler_names(handler)

        from app.core.addon import AddonManager
        from app.core.module import ModuleManager

        addon_manager = AddonManager()
        module_manager = ModuleManager()

        if class_name in addon_manager.get_addon_ids():
            # Plugin handler
            plugin = addon_manager.running_addons.get(class_name)
            if not plugin:
                return
            method = getattr(plugin, method_name, None)
            if not method:
                return
            try:
                method(event)
            except Exception as e:
                self.__handle_event_error(
                    event=event,
                    module_name=plugin.addon_name,
                    class_name=class_name,
                    method_name=method_name,
                    e=e,
                )
        elif class_name in module_manager.get_module_ids():
            # Module handler
            module = module_manager.get_running_module(class_name)
            if not module:
                return
            method = getattr(module, method_name, None)
            if not method:
                return
            try:
                method(event)
            except Exception as e:
                self.__handle_event_error(
                    event=event,
                    module_name=module.get_name(),
                    class_name=class_name,
                    method_name=method_name,
                    e=e,
                )
        else:
            # Global handler
            class_obj = self.__get_class_instance(class_name)
            if not class_obj or not hasattr(class_obj, method_name):
                return
            method = getattr(class_obj, method_name, None)
            if not method:
                return
            try:
                method(event)
            except Exception as e:
                self.__handle_event_error(
                    event=event,
                    module_name=class_name,
                    class_name=class_name,
                    method_name=method_name,
                    e=e,
                )

    async def __invoke_handler_by_type_async(self, handler: Callable, event: Event):
        """Asynchronously invokes the appropriate method based on the handler type.

        :param handler: The handler
        :param event: The event object to be processed
        """
        class_name, method_name = self.__parse_handler_names(handler)

        addon_manager = Context.addonmanager
        module_manager = Context.modulemanager

        if class_name in addon_manager.get_addon_ids():
            await self.__invoke_plugin_method_async(class_name, method_name, event)
        elif class_name in module_manager.get_module_ids():
            await self.__invoke_module_method_async(
                module_manager, class_name, method_name, event
            )
        else:
            await self.__invoke_global_method_async(class_name, method_name, event)

    @staticmethod
    def __parse_handler_names(handler: Callable) -> tuple[str, str]:
        """Parses the class name and method name of a handler.

        :param handler: The handler
        :return: (class_name, method_name)
        """
        names = handler.__qualname__.split(".")
        return names[0], names[1]

    async def __invoke_plugin_method_async(
        self, class_name: str, method_name: str, event: Event
    ):
        """Asynchronously invokes a plugin method."""
        plugin = Context.addonmanager.running_addons.get(class_name)
        if not plugin:
            return
        method: Callable | None = getattr(plugin, method_name, None)
        if not method:
            return
        try:
            if inspect.iscoroutinefunction(method):
                await method(event)
            else:
                # Run synchronous plugin functions in an async environment to
                # avoid blocking
                await run_in_threadpool(method, event)
        except Exception as e:
            self.__handle_event_error(
                event=event,
                e=e,
                module_name=plugin.addon_name,
                class_name=class_name,
                method_name=method_name,
            )

    async def __invoke_module_method_async(
        self, handler: Any, class_name: str, method_name: str, event: Event
    ):
        """Asynchronously invokes a module method."""
        module = handler.get_running_module(class_name)
        if not module:
            return
        method = getattr(module, method_name, None)
        if not method:
            return
        try:
            if inspect.iscoroutinefunction(method):
                await method(event)
            else:
                method(event)
        except Exception as e:
            self.__handle_event_error(
                event=event,
                module_name=module.get_name(),
                class_name=class_name,
                method_name=method_name,
                e=e,
            )

    async def __invoke_global_method_async(
        self, class_name: str, method_name: str, event: Event
    ):
        """Asynchronously invokes a global object method."""
        class_obj = self.__get_class_instance(class_name)
        if not class_obj:
            return
        method = getattr(class_obj, method_name, None)
        if not method:
            return
        try:
            if inspect.iscoroutinefunction(method):
                await method(event)
            else:
                method(event)
        except Exception as e:
            self.__handle_event_error(
                event=event,
                module_name=class_name,
                class_name=class_name,
                method_name=method_name,
                e=e,
            )

    @staticmethod
    def __get_class_instance(class_name: str):
        """Gets a class instance by class name, first checking if the class exists in
        globals, and if not, attempting to dynamically import the module.

        :param class_name: The name of the class
        :return: An instance of the class
        """
        # Check if the class is in globals
        if class_name in globals():
            try:
                class_obj = globals()[class_name]()
                return class_obj
            except Exception as e:
                logger.error(
                    f"Event processing error: failed to create global class instance: "
                    f"{str(e)} - {traceback.format_exc()}"
                )
                return None

        # If the class is not in globals, try to dynamically import the module and
        # create an instance
        try:
            if class_name.endswith("Manager"):
                module_name = f"app.core.{class_name[:-7].lower()}"
                module = importlib.import_module(module_name)
            elif class_name.endswith("Chain"):
                module_name = f"app.chain.{class_name[:-5].lower()}"
                module = importlib.import_module(module_name)
            elif class_name.endswith("Helper"):
                # Special handling for Async classes
                if class_name.startswith("Async"):
                    module_name = f"app.helper.{class_name[5:-6].lower()}"
                else:
                    module_name = f"app.helper.{class_name[:-6].lower()}"
                module = importlib.import_module(module_name)
            else:
                module_name = f"app.{class_name.lower()}"
                module = importlib.import_module(module_name)
            if hasattr(module, class_name):
                class_obj = getattr(module, class_name)()
                return class_obj
            else:
                logger.debug(
                    f"Event processing error: class {class_name} not found in "
                    f"module {module_name}"
                )
        except Exception as e:
            logger.debug(f"Event processing error: {str(e)} - {traceback.format_exc()}")
        return None

    def __broadcast_consumer_loop(self):
        """A background broadcast consumer thread that continuously extracts events from
        the queue."""
        jitter_factor = 0.1
        rate_limiter = ExponentialBackoffRateLimiter(
            base_wait=INITIAL_EVENT_QUEUE_IDLE_TIMEOUT_SECONDS,
            max_wait=MAX_EVENT_QUEUE_IDLE_TIMEOUT_SECONDS,
            backoff_factor=2.0,
            source="BroadcastConsumer",
            enable_logging=False,
        )
        while self.__event.is_set():
            try:
                priority, event = self.__event_queue.get(
                    timeout=rate_limiter.current_wait
                )
                rate_limiter.reset()
                self.__dispatch_broadcast_event(event)
            except Empty:
                rate_limiter.current_wait = rate_limiter.current_wait * random.uniform(
                    1, 1 + jitter_factor
                )
                rate_limiter.trigger_limit()

    @staticmethod
    def __log_event_lifecycle(event: Event, stage: str):
        """Logs the lifecycle of an event."""
        logger.debug(f"{stage} - {event}")

    def __handle_event_error(
        self,
        event: Event,
        module_name: str,
        class_name: str,
        method_name: str,
        e: Exception,
    ):
        """Global error handler for handling exceptions in event processing."""
        logger.error(
            f"{module_name} event processing error: {str(e)} - {traceback.format_exc()}"
        )

        # Send a system error notification
        from app.helper.message import MessageHelper

        MessageHelper().put(
            title=f"Error processing event {event.event_type} in {module_name}",
            message=f"{class_name}.{method_name}：{str(e)}",
            role="system",
        )
        self.send_event(
            EventType.SystemError,
            {
                "type": "event",
                "event_type": event.event_type,
                "event_handle": f"{class_name}.{method_name}",
                "error": str(e),
                "traceback": traceback.format_exc(),
            },
        )

    def register(
        self,
        etype: EventType | ChainEventType | list[EventType | ChainEventType] | type,
        priority: int = DEFAULT_EVENT_PRIORITY,
    ):
        """Event registration decorator to register a function as an event handler.

        :param etype:
            - A single event type member (e.g., EventType.MetadataScrape,
              ChainEventType.PluginAction)
            - An event type class (EventType, ChainEventType)
            - Or a list of event type members
        :param priority: Optional, priority for chain events,
                         defaults to DEFAULT_EVENT_PRIORITY
        """

        def decorator(f: Callable):
            # Uniformly convert the input event type to a list format
            if isinstance(etype, list):
                # If it's already a list, use it directly
                event_list = etype
            else:
                # Otherwise, wrap it in a single-element list
                event_list = [etype]

            # Iterate through the list and process each event type
            for event in event_list:
                if isinstance(event, (EventType, ChainEventType)):
                    self.add_event_listener(event, f, priority)
                elif isinstance(event, type) and issubclass(
                    event, (EventType, ChainEventType)
                ):
                    # If it's an EventType or ChainEventType class,
                    # extract all members of that class
                    for et in event.__members__.values():
                        self.add_event_listener(et, f, priority)
                else:
                    raise ValueError(f"Invalid event type: {event}")

            return f

        return decorator


eventmanager = EventManager()
