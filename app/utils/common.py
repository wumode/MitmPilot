import inspect
import time
from typing import Any

from app.schemas import ImmediateException


def retry(
    exception_to_check: Any,
    tries: int = 3,
    delay: int = 3,
    backoff: int = 2,
    logger: Any = None,
):
    """
    :param exception_to_check: The exception to catch
    :param tries: Number of retries
    :param delay: Delay time
    :param backoff: Delay multiplier
    :param logger: Logger object
    """

    def deco_retry(f):
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except ImmediateException:
                    raise
                except exception_to_check as e:
                    msg = f"{str(e)}, retrying in {mdelay} seconds..."
                    if logger:
                        logger.warn(msg)
                    else:
                        print(msg)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)

        async def async_f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return await f(*args, **kwargs)
                except ImmediateException:
                    raise
                except exception_to_check as e:
                    msg = f"{str(e)}, retrying in {mdelay} seconds..."
                    if logger:
                        logger.warn(msg)
                    else:
                        print(msg)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return await f(*args, **kwargs)

        # Returns the appropriate wrapper based on the function type.
        if inspect.iscoroutinefunction(f):
            return async_f_retry
        else:
            return f_retry

    return deco_retry
