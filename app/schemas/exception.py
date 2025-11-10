class ImmediateException(Exception):
    """A special exception class for throwing exceptions immediately without retrying.

    This exception can be thrown when the retry mechanism is not desired.
    """

    pass


class LimitException(ImmediateException):
    """Base class for exceptions indicating local rate limiting or externally triggered
    rate limiting.

    This exception class can be used for local rate limiting logic or external rate
    limiting handling.
    """

    pass


class APIRateLimitException(LimitException):
    """Exception class for API rate limiting.

    This exception can be thrown when an API call triggers a rate limit to immediately
    terminate the operation and report an error.
    """

    pass


class RateLimitExceededException(LimitException):
    """Exception class for exceptions triggered by the local rate limiter.

    This exception can be thrown when the frequency of function calls exceeds the
    limiter's limit to stop the current operation and inform the caller of the rate
    limiting situation.

    This exception is usually used for local rate limiting logic (e.g., RateLimiter).
    When the system detects that the function call frequency is too high, it triggers
    the rate limit and throws this exception.
    """

    pass
