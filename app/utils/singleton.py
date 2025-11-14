import abc
import threading
import weakref


class Singleton(abc.ABCMeta, type):
    """Class Singleton Pattern (by parameters)"""

    _instances: dict = {}

    def __call__(cls, *args, **kwargs):
        key = (cls, args, frozenset(kwargs.items()))
        if key not in cls._instances:
            cls._instances[key] = super().__call__(*args, **kwargs)
        return cls._instances[key]


class AbstractSingleton(abc.ABC, metaclass=Singleton):
    """Abstract Class Singleton Pattern."""

    pass


class SingletonClass(abc.ABCMeta, type):
    """Class Singleton Pattern (by class)"""

    _instances: dict = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class AbstractSingletonClass(abc.ABC, metaclass=SingletonClass):
    """Abstract Class Singleton Pattern (by class)"""

    pass


class WeakSingleton(abc.ABCMeta, type):
    """
    Weak Reference Singleton Pattern - automatically cleans up when there are no strong
    references.
    """

    _instances: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
    _lock = threading.RLock()

    def __call__(cls, *args, **kwargs):
        with cls._lock:
            if cls not in cls._instances:
                cls._instances[cls] = super().__call__(*args, **kwargs)
            return cls._instances[cls]
