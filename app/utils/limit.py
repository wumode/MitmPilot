import functools
import inspect
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from app.log import logger
from app.schemas import LimitException, RateLimitExceededException


# Abstract base class
class BaseRateLimiter:
    """Base class for rate limiters, defining a common interface for subclasses to
    implement different rate limiting strategies.

    All rate limiters must implement can_call and reset methods.
    """

    def __init__(self, source: str = "", enable_logging: bool = True):
        """Initializes the BaseRateLimiter instance.

        :param source: Business source or context information, defaults to an empty
            string
        :param enable_logging: Whether to enable logging, defaults to True
        """
        self.source = source
        self.enable_logging = enable_logging
        self.lock = threading.Lock()

    @property
    def reset_on_success(self) -> bool:
        """Whether to automatically reset the rate limiter state upon a successful call,
        defaults to False."""
        return False

    def can_call(self) -> tuple[bool, str]:
        """Checks if a call can be made.

        :return: Returns True and an empty message if the call is allowed, otherwise
            returns False and a rate limit message
        """
        raise NotImplementedError

    def reset(self):
        """Resets the rate limit state."""
        raise NotImplementedError

    def trigger_limit(self):
        """Triggers the rate limit."""
        pass

    def record_call(self):
        """Records a call."""
        pass

    def format_log(self, message: str) -> str:
        """Formats a log message.

        :param message: Log content
        :return: The formatted log message
        """
        return f"[{self.source}] {message}" if self.source else message

    def log(self, level: str, message: str):
        """Logs messages based on the log level.

        :param level: Log level
        :param message: Log content
        """
        if self.enable_logging:
            log_method = getattr(logger, level, None)
            if not callable(log_method):
                log_method = logger.info
            log_method(self.format_log(message))

    def log_info(self, message: str):
        """Records an info log."""
        self.log("info", message)

    def log_warning(self, message: str):
        """Records a warning log."""
        self.log("warning", message)


# Exponential backoff rate limiter
class ExponentialBackoffRateLimiter(BaseRateLimiter):
    """Rate limiter based on exponential backoff, used to control the frequency of
    single calls.

    Each time a rate limit is triggered, the waiting time doubles until it reaches the
    maximum waiting time.
    """

    def __init__(
        self,
        base_wait: float = 60.0,
        max_wait: float = 600.0,
        backoff_factor: float = 2.0,
        source: str = "",
        enable_logging: bool = True,
    ):
        """Initializes the ExponentialBackoffRateLimiter instance.

        :param base_wait: Base waiting time (seconds), defaults to 60 seconds (1 minute)
        :param max_wait: Maximum waiting time (seconds), defaults to 600 seconds (10
            minutes)
        :param backoff_factor: Multiplier for increasing waiting time, defaults to 2.0,
            indicating exponential backoff
        :param source: Business source or context information, defaults to an empty
            string
        :param enable_logging: Whether to enable logging, defaults to True
        """
        super().__init__(source, enable_logging)
        self.next_allowed_time = 0.0
        self.current_wait = base_wait
        self.base_wait = base_wait
        self.max_wait = max_wait
        self.backoff_factor = backoff_factor
        self.source = source

    @property
    def reset_on_success(self) -> bool:
        """The exponential backoff rate limiter should reset the waiting time after a
        successful call."""
        return True

    def can_call(self) -> tuple[bool, str]:
        """Checks if a call can be made. If the current time exceeds the next allowed
        call time, the call is allowed.

        :return: Returns True and an empty message if the call is allowed, otherwise
            returns False and a rate limit message
        """
        current_time = time.time()
        with self.lock:
            if current_time >= self.next_allowed_time:
                return True, ""
            wait_time = self.next_allowed_time - current_time
            message = (
                f"Rate limited, skipping call. Will be allowed to continue in "
                f"{wait_time:.2f} seconds"
            )
            self.log_info(message)
            return False, self.format_log(message)

    def reset(self):
        """Resets the waiting time.

        Call this method upon a successful call to reset the current waiting time to the
        base waiting time.
        """
        with self.lock:
            if self.next_allowed_time != 0 or self.current_wait > self.base_wait:
                self.log_info(
                    f"Call successful, resetting rate limit waiting time to "
                    f"{self.base_wait} seconds"
                )
            self.next_allowed_time = 0.0
            self.current_wait = self.base_wait

    def trigger_limit(self):
        """Triggers the rate limit.

        Call this method when a rate limit exception is triggered to increase the next
        allowed call time and update the current waiting time.
        """
        current_time = time.time()
        with self.lock:
            self.next_allowed_time = current_time + self.current_wait
            self.current_wait = min(
                self.current_wait * self.backoff_factor, self.max_wait
            )
            wait_time = self.next_allowed_time - current_time
            self.log_warning(
                f"Rate limit triggered. Will be allowed to continue in "
                f"{wait_time:.2f} seconds"
            )


# Time window rate limiter
class WindowRateLimiter(BaseRateLimiter):
    """Rate limiter based on a time window, used to limit the number of calls within a
    specific time window.

    If the maximum allowed calls are exceeded, calls are rate-limited until the window
    ends.
    """

    def __init__(
        self,
        max_calls: int,
        window_seconds: float,
        source: str = "",
        enable_logging: bool = True,
    ):
        """Initializes the WindowRateLimiter instance.

        :param max_calls: Maximum number of calls allowed within the time window
        :param window_seconds: Duration of the time window (seconds)
        :param source: Business source or context information, defaults to an empty
            string
        :param enable_logging: Whether to enable logging, defaults to True
        """
        super().__init__(source, enable_logging)
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.call_times = deque()

    def can_call(self) -> tuple[bool, str]:
        """Checks if a call can be made. If the number of calls within the time window
        is less than the maximum allowed, the call is allowed.

        :return: Returns True and an empty message if the call is allowed, otherwise
            returns False and a rate limit message
        """
        current_time = time.time()
        with self.lock:
            # Clean up call records that are outside the time window
            while (
                self.call_times
                and current_time - self.call_times[0] > self.window_seconds
            ):
                self.call_times.popleft()

            if len(self.call_times) < self.max_calls:
                return True, ""
            else:
                wait_time = self.window_seconds - (current_time - self.call_times[0])
                message = (
                    f"Rate limited, skipping call. Will be allowed to continue "
                    f"in {wait_time:.2f} seconds"
                )
                self.log_info(message)
                return False, self.format_log(message)

    def reset(self):
        """Resets the call records within the time window.

        Call this method upon a successful call to clear the call records within the
        time window.
        """
        with self.lock:
            self.call_times.clear()

    def record_call(self):
        """Records the current timestamp for rate limit checking."""
        current_time = time.time()
        with self.lock:
            self.call_times.append(current_time)


# Composite rate limiter
class CompositeRateLimiter(BaseRateLimiter):
    """A composite rate limiter that combines multiple rate limiting strategies.

    If any of the combined rate limiting strategies trigger a limit, the call will be
    blocked.
    """

    def __init__(
        self,
        limiters: list[BaseRateLimiter],
        source: str = "",
        enable_logging: bool = True,
    ):
        """Initializes the CompositeRateLimiter instance.

        :param limiters: List of rate limiters to combine
        :param source: Business source or context information, defaults to an empty
            string
        :param enable_logging: Whether to enable logging, defaults to True
        """
        super().__init__(source, enable_logging)
        self.limiters = limiters

    def can_call(self) -> tuple[bool, str]:
        """Checks if a call can be made. If any of the combined rate limiters trigger a
        limit, the call is blocked.

        :return: Returns True and an empty message if all rate limiters allow the call,
            otherwise returns False and rate limit information.
        """
        for limiter in self.limiters:
            can_call, message = limiter.can_call()
            if not can_call:
                return False, message
        return True, ""

    def reset(self):
        """Resets the state of all combined rate limiters."""
        for limiter in self.limiters:
            limiter.reset()

    def record_call(self):
        """Records the call time for all combined rate limiters."""
        for limiter in self.limiters:
            limiter.record_call()


# Generic decorator: custom rate limiter instance
def rate_limit_handler(
    limiter: BaseRateLimiter, raise_on_limit: bool = False
) -> Callable:
    """Generic decorator that allows users to pass custom rate limiter instances to
    handle rate limiting logic. This decorator flexibly supports any rate limiter
    inheriting from BaseRateLimiter.

    :param limiter: Rate limiter instance, must inherit from BaseRateLimiter
    :param raise_on_limit: Controls whether to raise an exception when rate limited,
        defaults to False
    :return: Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any | None:
            # Check if the "raise_exception" parameter is passed, prioritize it,
            # otherwise use the default raise_on_limit value
            raise_exception = kwargs.get("raise_exception", raise_on_limit)

            # Check if the call can be made, call the limiter.can_call() method
            can_call, message = limiter.can_call()
            if not can_call:
                # If the call is restricted and raise_exception is True,
                # raise a RateLimitExceededException
                if raise_exception:
                    raise RateLimitExceededException(message)
                # If no exception is raised, return None to indicate skipping the call
                return None

            # If the call is allowed, execute the target function and record a call
            try:
                result = func(*args, **kwargs)
                limiter.record_call()
                if limiter.reset_on_success:
                    limiter.reset()
                return result
            except LimitException as e:
                # If the target function triggers a rate limit-related exception,
                # execute the limiter's trigger logic (e.g., increment waiting time)
                limiter.trigger_limit()
                logger.error(limiter.format_log(f"Rate limit triggered: {str(e)}"))
                # If raise_exception is True, raise the exception, otherwise return None
                if raise_exception:
                    raise e
                return None

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any | None:
            # Check if the "raise_exception" parameter is passed, prioritize it,
            # otherwise use the default raise_on_limit value
            raise_exception = kwargs.get("raise_exception", raise_on_limit)

            # Check if the call can be made, call the limiter.can_call() method
            can_call, message = limiter.can_call()
            if not can_call:
                # If the call is restricted and raise_exception is True,
                # raise a RateLimitExceededException
                if raise_exception:
                    raise RateLimitExceededException(message)
                # If no exception is raised, return None to indicate skipping the call
                return None

            # If the call is allowed, execute the target function and record a call
            try:
                result = await func(*args, **kwargs)
                limiter.record_call()
                if limiter.reset_on_success:
                    limiter.reset()
                return result
            except LimitException as e:
                # If the target function triggers a rate limit-related exception,
                # execute the limiter's trigger logic (e.g., increment waiting time)
                limiter.trigger_limit()
                logger.error(limiter.format_log(f"Rate limit triggered: {str(e)}"))
                # If raise_exception is True, raise the exception, otherwise return None
                if raise_exception:
                    raise e
                return None

        # Return the appropriate wrapper based on the function type
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return wrapper

    return decorator


# Decorator: exponential backoff rate limit
def rate_limit_exponential(
    base_wait: float = 60.0,
    max_wait: float = 600.0,
    backoff_factor: float = 2.0,
    raise_on_limit: bool = False,
    source: str = "",
    enable_logging: bool = True,
) -> Callable:
    """Decorator for applying an exponential backoff rate limiting strategy. Controls
    call frequency by gradually increasing the waiting time for calls. Each time a rate
    limit is triggered, the waiting time doubles until it reaches the maximum waiting
    time.

    :param base_wait: Base waiting time (seconds), defaults to 60 seconds (1 minute)
    :param max_wait: Maximum waiting time (seconds), defaults to 600 seconds (10
        minutes)
    :param backoff_factor: Multiplier for increasing waiting time, defaults to 2.0,
        indicating exponential backoff
    :param raise_on_limit: Controls whether to raise an exception when rate limited,
        defaults to False
    :param source: Business source or context information, defaults to an empty string
    :param enable_logging: Whether to enable logging, defaults to True
    :return: Decorator function
    """
    # Instantiate ExponentialBackoffRateLimiter with relevant parameters
    limiter = ExponentialBackoffRateLimiter(
        base_wait, max_wait, backoff_factor, source, enable_logging
    )
    # Wrap the rate limiter using the generic decorator logic
    return rate_limit_handler(limiter, raise_on_limit)


# Decorator: time window rate limit
def rate_limit_window(
    max_calls: int,
    window_seconds: float,
    raise_on_limit: bool = False,
    source: str = "",
    enable_logging: bool = True,
) -> Callable:
    """Decorator for applying a time window rate limiting strategy. Limits the number of
    calls within a fixed time window. When the number of calls exceeds the maximum, rate
    limiting is triggered until the time window ends.

    :param max_calls: Maximum number of calls allowed within the time window
    :param window_seconds: Duration of the time window (seconds)
    :param raise_on_limit: Controls whether to raise an exception when rate limited,
        defaults to False
    :param source: Business source or context information, defaults to an empty string
    :param enable_logging: Whether to enable logging, defaults to True
    :return: Decorator function
    """
    # Instantiate WindowRateLimiter with relevant parameters
    limiter = WindowRateLimiter(max_calls, window_seconds, source, enable_logging)
    # Wrap the rate limiter using the generic decorator logic
    return rate_limit_handler(limiter, raise_on_limit)
