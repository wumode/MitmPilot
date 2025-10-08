import contextvars
import inspect
import shutil
import tempfile
import threading
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from functools import wraps
from pathlib import Path
from typing import Any, Literal

import aiofiles
import aioshutil
from anyio import Path as AsyncPath
from cachetools import LRUCache as MemoryLRUCache
from cachetools import TTLCache as MemoryTTLCache
from cachetools.keys import hashkey

from app.core.config import settings
from app.helper.redis import AsyncRedisHelper, RedisHelper
from app.log import logger
from app.schemas import CacheConfig

lock = threading.Lock()

# Context variable to control caching behavior
_fresh = contextvars.ContextVar("fresh", default=False)


class CacheBackend(ABC):
    """Base class for cache backends, defining common cache interfaces."""

    def __getitem__(self, key: str) -> Any:
        """Gets a cache item, similar to dict[key]"""
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        """Sets a cache item, similar to dict[key] = value."""
        self.set(key, value)

    def __delitem__(self, key: str) -> None:
        """Deletes a cache item, similar to del dict[key]"""
        if not self.exists(key):
            raise KeyError(key)
        self.delete(key)

    def __contains__(self, key: str) -> bool:
        """Checks if a key exists, similar to key in dict."""
        return self.exists(key)

    def __iter__(self):
        """Returns an iterator for the cache, similar to iter(dict)"""
        for key, _ in self.items():
            yield key

    def __len__(self) -> int:
        """Returns the number of cache items, similar to len(dict)"""
        return sum(1 for _ in self.items())

    @abstractmethod
    def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
        **kwargs,
    ) -> None:
        """Set cache.

        :param key: The key of the cache.
        :param value: The value of the cache.
        :param ttl: The time-to-live of the cache in seconds.
        :param region: The region of the cache.
        :param kwargs: Other parameters.
        """
        pass

    @abstractmethod
    def exists(self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> bool:
        """Check if a cache key exists.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: True if the key exists, otherwise False.
        """
        pass

    @abstractmethod
    def get(self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> Any:
        """Get cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: The value of the cache, or None if it does not exist.
        """
        pass

    @abstractmethod
    def delete(self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> None:
        """Delete cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        """
        pass

    @abstractmethod
    def clear(self, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> None:
        """Clear the cache in the specified region or all caches.

        :param region: The region of the cache. If None, clear all regions.
        """
        pass

    @abstractmethod
    def items(
        self, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> Generator[tuple[str, Any]]:
        """Get all cache items in the specified region.

        :param region: The region of the cache.
        :return: A generator of tuples, each containing a key-value pair.
        """
        pass

    def keys(self, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> Generator[str]:
        """Get all cache keys, similar to dict.keys()."""
        for key, _ in self.items(region=region):
            yield key

    def values(self, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> Generator[Any]:
        """Get all cache values, similar to dict.values()."""
        for _, value in self.items(region=region):
            yield value

    def update(
        self,
        other: dict[str, Any],
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
        ttl: int | None = None,
        **kwargs,
    ) -> None:
        """Update the cache, similar to dict.update()."""
        for key, value in other.items():
            self.set(key, value, ttl=ttl, region=region, **kwargs)

    def pop(
        self,
        key: str,
        default: Any = None,
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
    ) -> Any:
        """Pop a cache item, similar to dict.pop()."""
        value = self.get(key, region=region)
        if value is not None:
            self.delete(key, region=region)
            return value
        if default is not None:
            return default
        raise KeyError(key)

    def popitem(
        self, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> tuple[str, Any]:
        """Pop the last cache item, similar to dict.popitem()."""
        items = list(self.items(region=region))
        if not items:
            raise KeyError("popitem(): cache is empty")
        key, value = items[-1]
        self.delete(key, region=region)
        return key, value

    def setdefault(
        self,
        key: str,
        default: Any = None,
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
        ttl: int | None = None,
        **kwargs,
    ) -> Any:
        """Set a default value, similar to dict.setdefault()."""
        value = self.get(key, region=region)
        if value is None:
            self.set(key, default, ttl=ttl, region=region, **kwargs)
            return default
        return value

    @abstractmethod
    def close(self) -> None:
        """Close the cache connection."""
        pass

    @staticmethod
    def get_region(region: str = None) -> str:
        """Get the cache region."""
        return f"region:{region}" if region else "region:default"

    @staticmethod
    def is_redis() -> bool:
        """Check if the current cache backend is Redis."""
        return settings.CACHE_BACKEND_TYPE == "redis"


class AsyncCacheBackend(CacheBackend):
    """Base class for asynchronous cache backends, defining common asynchronous cache
    interfaces."""

    @abstractmethod
    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
        **kwargs,
    ) -> None:
        """Set cache.

        :param key: The key of the cache.
        :param value: The value of the cache.
        :param ttl: The time-to-live of the cache in seconds.
        :param region: The region of the cache.
        :param kwargs: Other parameters.
        """
        pass

    @abstractmethod
    async def exists(
        self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> bool:
        """Check if a cache key exists.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: True if the key exists, otherwise False.
        """
        pass

    @abstractmethod
    async def get(
        self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> Any:
        """Get cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: The value of the cache, or None if it does not exist.
        """
        pass

    @abstractmethod
    async def delete(
        self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> None:
        """Delete cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        """
        pass

    @abstractmethod
    async def clear(self, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> None:
        """Clear the cache in the specified region or all caches.

        :param region: The region of the cache. If None, clear all regions.
        """
        pass

    @abstractmethod
    async def items(
        self, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> AsyncGenerator[tuple[str, Any]]:
        """Get all cache items in the specified region.

        :param region: The region of the cache.
        :return: An async generator of tuples, each containing a key-value pair.
        """
        pass

    async def keys(
        self, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> AsyncGenerator[str]:
        """Get all cache keys, similar to dict.keys() (asynchronous)."""
        async for key, _ in await self.items(region=region):
            yield key

    async def values(
        self, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> AsyncGenerator[Any]:
        """Get all cache values, similar to dict.values() (asynchronous)."""
        async for _, value in await self.items(region=region):
            yield value

    async def update(
        self,
        other: dict[str, Any],
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
        ttl: int | None = None,
        **kwargs,
    ) -> None:
        """Update the cache, similar to dict.update() (asynchronous)."""
        for key, value in other.items():
            await self.set(key, value, ttl=ttl, region=region, **kwargs)

    async def pop(
        self,
        key: str,
        default: Any = None,
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
    ) -> Any:
        """Pop a cache item, similar to dict.pop() (asynchronous)."""
        value = await self.get(key, region=region)
        if value is not None:
            await self.delete(key, region=region)
            return value
        if default is not None:
            return default
        raise KeyError(key)

    async def popitem(
        self, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> tuple[str, Any]:
        """Pop the last cache item, similar to dict.popitem() (asynchronous)."""
        items = []
        async for item in await self.items(region=region):
            items.append(item)
        if not items:
            raise KeyError("popitem(): cache is empty")
        key, value = items[-1]
        await self.delete(key, region=region)
        return key, value

    async def setdefault(
        self,
        key: str,
        default: Any = None,
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
        ttl: int | None = None,
        **kwargs,
    ) -> Any:
        """Set a default value, similar to dict.setdefault() (asynchronous)."""
        value = await self.get(key, region=region)
        if value is None:
            await self.set(key, default, ttl=ttl, region=region, **kwargs)
            return default
        return value

    @abstractmethod
    async def close(self) -> None:
        """Close the cache connection."""
        pass


class MemoryBackend(CacheBackend):
    """Cache backend based on `cachetools.TTLCache`."""

    def __init__(
        self,
        cache_type: Literal["ttl", "lru"] = "ttl",
        maxsize: int | None = None,
        ttl: int | None = None,
    ):
        """Initialize the cache instance.

        :param cache_type: The type of cache, supports 'ttl' (default) and 'lru'.
        :param maxsize: The maximum number of entries in the cache.
        :param ttl: The default time-to-live of the cache in seconds.
        """
        self.cache_type = cache_type
        self.maxsize = maxsize or CacheConfig.DEFAULT_CACHE_SIZE
        self.ttl = ttl or CacheConfig.DEFAULT_CACHE_TTL
        # Store cache instances for each region, region -> TTLCache
        self._region_caches: dict[str, MemoryTTLCache | MemoryLRUCache] = {}

    def __get_region_cache(self, region: str) -> MemoryTTLCache | MemoryLRUCache | None:
        """Get the cache instance for the specified region, or None if it does not
        exist."""
        region = self.get_region(region)
        return self._region_caches.get(region)

    def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
        **kwargs,
    ) -> None:
        """Set a cache value, supporting independent TTL for each key.

        :param key: The key of the cache.
        :param value: The value of the cache.
        :param ttl: The time-to-live of the cache in seconds. If not provided, it will
            be cached permanently.
        :param region: The region of the cache.
        """
        ttl = ttl or self.ttl
        maxsize = kwargs.get("maxsize", self.maxsize)
        region = self.get_region(region)
        # Set the cache value
        with lock:
            # If there is no cache instance for this key, create a new TTLCache instance.
            region_cache = self._region_caches.setdefault(
                region,
                MemoryTTLCache(maxsize=maxsize, ttl=ttl)
                if self.cache_type == "ttl"
                else MemoryLRUCache(maxsize=maxsize),
            )
            region_cache[key] = value

    def exists(self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> bool:
        """Check if a cache key exists.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: True if the key exists, otherwise False.
        """
        region_cache = self.__get_region_cache(region)
        if region_cache is None:
            return False
        return key in region_cache

    def get(self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> Any:
        """Get the value of the cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: The value of the cache, or None if it does not exist.
        """
        region_cache = self.__get_region_cache(region)
        if region_cache is None:
            return None
        return region_cache.get(key)

    def delete(self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION):
        """Delete cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        """
        region_cache = self.__get_region_cache(region)
        if region_cache is None:
            return
        with lock:
            del region_cache[key]

    def clear(self, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> None:
        """Clear the cache in the specified region or all caches.

        :param region: The region of the cache. If None, clear all regions.
        """
        if region:
            # Clear the specified cache region
            region_cache = self.__get_region_cache(region)
            if region_cache:
                with lock:
                    region_cache.clear()
                logger.debug(f"Cleared cache for region: {region}")
        else:
            # Clear all cache regions
            for region_cache in self._region_caches.values():
                with lock:
                    region_cache.clear()
            logger.info("Cleared all cache")

    def items(
        self, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> Generator[tuple[str, Any]]:
        """Get all cache items in the specified region.

        :param region: The region of the cache.
        :return: A generator of tuples, each containing a key-value pair.
        """
        region_cache = self.__get_region_cache(region)
        if region_cache is None:
            yield from ()
            return
        # Use a lock to protect the iteration process to avoid modification of the
        # cache during iteration.
        with lock:
            # Create a snapshot to avoid concurrent modification issues.
            items_snapshot = list(region_cache.items())
        yield from items_snapshot

    def close(self) -> None:
        """Memory cache does not need to close resources."""
        pass


class AsyncMemoryBackend(AsyncCacheBackend):
    """Asynchronous cache backend based on `cachetools.TTLCache`."""

    def __init__(
        self,
        cache_type: Literal["ttl", "lru"] = "ttl",
        maxsize: int | None = None,
        ttl: int | None = None,
    ):
        """Initialize the cache instance.

        :param cache_type: The type of cache, supports 'ttl' (default) and 'lru'.
        :param maxsize: The maximum number of entries in the cache.
        :param ttl: The default time-to-live of the cache in seconds.
        """
        self.cache_type = cache_type
        self.maxsize = maxsize or CacheConfig.DEFAULT_CACHE_SIZE
        self.ttl = ttl or CacheConfig.DEFAULT_CACHE_TTL
        # Store cache instances for each region, region -> TTLCache
        self._region_caches: dict[str, MemoryTTLCache | MemoryLRUCache] = {}

    def __get_region_cache(self, region: str) -> MemoryTTLCache | MemoryLRUCache | None:
        """Get the cache instance for the specified region, or None if it does not
        exist."""
        region = self.get_region(region)
        return self._region_caches.get(region)

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
        **kwargs,
    ) -> None:
        """Set a cache value, supporting independent TTL for each key.

        :param key: The key of the cache.
        :param value: The value of the cache.
        :param ttl: The time-to-live of the cache in seconds. If not provided, it will
            be cached permanently.
        :param region: The region of the cache.
        """
        ttl = ttl or self.ttl
        maxsize = kwargs.get("maxsize", self.maxsize)
        region = self.get_region(region)
        # Set the cache value
        with lock:
            # If there is no cache instance for this key, create a new TTLCache instance.
            region_cache = self._region_caches.setdefault(
                region,
                MemoryTTLCache(maxsize=maxsize, ttl=ttl)
                if self.cache_type == "ttl"
                else MemoryLRUCache(maxsize=maxsize),
            )
            region_cache[key] = value

    async def exists(
        self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> bool:
        """Check if a cache key exists.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: True if the key exists, otherwise False.
        """
        region_cache = self.__get_region_cache(region)
        if region_cache is None:
            return False
        return key in region_cache

    async def get(
        self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> Any:
        """Get the value of the cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: The value of the cache, or None if it does not exist.
        """
        region_cache = self.__get_region_cache(region)
        if region_cache is None:
            return None
        return region_cache.get(key)

    async def delete(self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION):
        """Delete cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        """
        region_cache = self.__get_region_cache(region)
        if region_cache is None:
            return
        with lock:
            del region_cache[key]

    async def clear(self, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> None:
        """Clear the cache in the specified region or all caches.

        :param region: The region of the cache. If None, clear all regions.
        """
        if region:
            # Clear the specified cache region
            region_cache = self.__get_region_cache(region)
            if region_cache:
                with lock:
                    region_cache.clear()
                logger.debug(f"Cleared cache for region: {region}")
        else:
            # Clear all cache regions
            for region_cache in self._region_caches.values():
                with lock:
                    region_cache.clear()
            logger.info("All cache cleared！")

    async def items(
        self, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> AsyncGenerator[tuple[str, Any]]:
        """Get all cache items in the specified region.

        :param region: The region of the cache.
        :return: An async generator of tuples, each containing a key-value pair.
        """
        region_cache = self.__get_region_cache(region)
        if region_cache is None:
            return
        # Use a lock to protect the iteration process to avoid modification of the cache during iteration.
        with lock:
            # Create a snapshot to avoid concurrent modification issues.
            items_snapshot = list(region_cache.items())
        for item in items_snapshot:
            yield item

    async def close(self) -> None:
        """Memory cache does not need to close resources."""
        pass


class RedisBackend(CacheBackend):
    """Cache backend based on Redis, supporting caching through Redis."""

    def __init__(self, ttl: int | None = None):
        """Initialize the Redis cache instance.

        :param ttl: The time-to-live of the cache in seconds.
        """
        self.ttl = ttl
        self.redis_helper = RedisHelper()

    def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
        **kwargs,
    ) -> None:
        """Set cache.

        :param key: The key of the cache.
        :param value: The value of the cache.
        :param ttl: The time-to-live of the cache in seconds. If not provided, it will
            be cached permanently.
        :param region: The region of the cache.
        :param kwargs: kwargs
        """
        ttl = ttl or self.ttl
        self.redis_helper.set(key, value, ttl=ttl, region=region, **kwargs)

    def exists(self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> bool:
        """Check if a cache key exists.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: True if the key exists, otherwise False.
        """
        return self.redis_helper.exists(key, region=region)

    def get(
        self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> Any | None:
        """Get the value of the cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: The value of the cache, or None if it does not exist.
        """
        return self.redis_helper.get(key, region=region)

    def delete(self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> None:
        """Delete cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        """
        self.redis_helper.delete(key, region=region)

    def clear(self, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> None:
        """Clear the cache in the specified region or all caches.

        :param region: The region of the cache. If None, clear all regions.
        """
        self.redis_helper.clear(region=region)

    def items(
        self, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> Generator[tuple[str, Any]]:
        """Get all cache items in the specified region.

        :param region: The region of the cache.
        :return: A generator of tuples, each containing a key-value pair.
        """
        return self.redis_helper.items(region=region)

    def close(self) -> None:
        """Close the Redis client's connection pool."""
        self.redis_helper.close()


class AsyncRedisBackend(AsyncCacheBackend):
    """Asynchronous cache backend based on Redis, supporting caching through Redis."""

    def __init__(self, ttl: int | None = None):
        """Initialize the Redis cache instance.

        :param ttl: The time-to-live of the cache in seconds.
        """
        self.ttl = ttl
        self.redis_helper = AsyncRedisHelper()

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
        **kwargs,
    ) -> None:
        """Set cache.

        :param key: The key of the cache.
        :param value: The value of the cache.
        :param ttl: The time-to-live of the cache in seconds. If not provided, it will
            be cached permanently.
        :param region: The region of the cache.
        :param kwargs: kwargs
        """
        ttl = ttl or self.ttl
        await self.redis_helper.set(key, value, ttl=ttl, region=region, **kwargs)

    async def exists(
        self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> bool:
        """Check if a cache key exists.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: True if the key exists, otherwise False.
        """
        return await self.redis_helper.exists(key, region=region)

    async def get(
        self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> Any | None:
        """Get the value of the cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: The value of the cache, or None if it does not exist.
        """
        return await self.redis_helper.get(key, region=region)

    async def delete(
        self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> None:
        """Delete cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        """
        await self.redis_helper.delete(key, region=region)

    async def clear(self, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> None:
        """Clear the cache in the specified region or all caches.

        :param region: The region of the cache. If None, clear all regions.
        """
        await self.redis_helper.clear(region=region)

    async def items(
        self, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> AsyncGenerator[tuple[str, Any]]:
        """Get all cache items in the specified region.

        :param region: The region of the cache.
        :return: An async generator of tuples, each containing a key-value pair.
        """
        async for item in self.redis_helper.items(region=region):
            yield item

    async def close(self) -> None:
        """Close the Redis client's connection pool."""
        await self.redis_helper.close()


class FileBackend(CacheBackend):
    """Cache backend based on the file system."""

    def __init__(self, base: Path):
        """Initialize the file cache instance."""
        self.base = base
        if not self.base.exists():
            self.base.mkdir(parents=True, exist_ok=True)

    def set(
        self,
        key: str,
        value: Any,
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
        **kwargs,
    ) -> None:
        """Set cache.

        :param key: The key of the cache.
        :param value: The value of the cache.
        :param region: The region of the cache.
        :param kwargs: kwargs
        """
        cache_path = self.base / region / key
        # Ensure the cache directory exists.
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        # Serialize the value to a string for storage.
        with tempfile.NamedTemporaryFile(
            dir=cache_path.parent, delete=False
        ) as tmp_file:
            tmp_file.write(value)
            temp_path = Path(tmp_file.name)
        temp_path.replace(cache_path)

    def exists(self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> bool:
        """Check if a cache key exists.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: True if the key exists, otherwise False.
        """
        cache_path = self.base / region / key
        return cache_path.exists()

    def get(
        self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> Any | None:
        """Get the value of the cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: The value of the cache, or None if it does not exist.
        """
        cache_path = self.base / region / key
        if not cache_path.exists():
            return None
        with open(cache_path, "rb") as f:
            return f.read()

    def delete(self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> None:
        """Delete cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        """
        cache_path = self.base / region / key
        if cache_path.exists():
            cache_path.unlink()

    def clear(self, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> None:
        """Clear the cache in the specified region or all caches.

        :param region: The region of the cache. If None, clear all regions.
        """
        if region:
            # Clear the specified cache region.
            cache_path = self.base / region
            if cache_path.exists():
                for item in cache_path.iterdir():
                    if item.is_file():
                        item.unlink()
                    else:
                        shutil.rmtree(item, ignore_errors=True)
        else:
            # Clear all cache regions.
            for item in self.base.iterdir():
                if item.is_file():
                    item.unlink()
                else:
                    shutil.rmtree(item, ignore_errors=True)

    def items(
        self, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> Generator[tuple[str, Any]]:
        """Get all cache items in the specified region.

        :param region: The region of the cache.
        :return: A generator of tuples, each containing a key-value pair.
        """
        cache_path = self.base / region
        if not cache_path.exists():
            yield from ()
            return
        for item in cache_path.iterdir():
            if item.is_file():
                with open(item) as f:
                    yield item.as_posix(), f.read()

    def close(self) -> None:
        """File cache does not need to close resources."""
        pass


@contextmanager
def fresh(refresh: bool = True):
    """Whether to fetch new data (not using cached values).

    Usage:
    with fresh():
        result = some_cached_function()
    """
    token = _fresh.set(refresh)
    try:
        yield
    finally:
        _fresh.reset(token)


@asynccontextmanager
async def async_fresh(refresh: bool = True):
    """Whether to fetch new data (not using cached values).

    Usage:
    async with async_fresh():
        result = await some_async_cached_function()
    """
    token = _fresh.set(refresh)
    try:
        yield
    finally:
        _fresh.reset(token)


def is_fresh() -> bool:
    """Check if new data is being fetched."""
    try:
        return _fresh.get()
    except LookupError:
        return False


class AsyncFileBackend(AsyncCacheBackend):
    """Asynchronous cache backend based on the file system."""

    def __init__(self, base: Path):
        """Initialize the file cache instance."""
        self.base = base
        if not self.base.exists():
            self.base.mkdir(parents=True, exist_ok=True)

    async def set(
        self,
        key: str,
        value: Any,
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
        **kwargs,
    ) -> None:
        """Set cache.

        :param key: The key of the cache.
        :param value: The value of the cache.
        :param region: The region of the cache.
        :param kwargs: kwargs
        """
        cache_path = AsyncPath(self.base) / region / key
        # Ensure the cache directory exists.
        await cache_path.parent.mkdir(parents=True, exist_ok=True)
        # Save the file.
        async with aiofiles.tempfile.NamedTemporaryFile(
            dir=cache_path.parent, delete=False
        ) as tmp_file:
            await tmp_file.write(value)
            temp_path = AsyncPath(tmp_file.name)
        await temp_path.replace(cache_path)

    async def exists(
        self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> bool:
        """Check if a cache key exists.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: True if the key exists, otherwise False.
        """
        cache_path = AsyncPath(self.base) / region / key
        return await cache_path.exists()

    async def get(
        self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> Any | None:
        """Get the value of the cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        :return: The value of the cache, or None if it does not exist.
        """
        cache_path = AsyncPath(self.base) / region / key
        if not await cache_path.exists():
            return None
        async with aiofiles.open(cache_path, "rb") as f:
            return await f.read()

    async def delete(
        self, key: str, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> None:
        """Delete cache.

        :param key: The key of the cache.
        :param region: The region of the cache.
        """
        cache_path = AsyncPath(self.base) / region / key
        if await cache_path.exists():
            await cache_path.unlink()

    async def clear(self, region: str = CacheConfig.DEFAULT_CACHE_REGION) -> None:
        """Clear the cache in the specified region or all caches.

        :param region: The region of the cache. If None, clear all regions.
        """
        if region:
            # Clear the specified cache region.
            cache_path = AsyncPath(self.base) / region
            if await cache_path.exists():
                async for item in cache_path.iterdir():
                    if await item.is_file():
                        await item.unlink()
                    else:
                        await aioshutil.rmtree(item, ignore_errors=True)
        else:
            # Clear all cache regions.
            async for item in AsyncPath(self.base).iterdir():
                if await item.is_file():
                    await item.unlink()
                else:
                    await aioshutil.rmtree(item, ignore_errors=True)

    async def items(
        self, region: str = CacheConfig.DEFAULT_CACHE_REGION
    ) -> AsyncGenerator[tuple[str, Any]]:
        """Get all cache items in the specified region.

        :param region: The region of the cache.
        :return: An async generator of tuples, each containing a key-value pair.
        """
        cache_path = AsyncPath(self.base) / region
        if not await cache_path.exists():
            yield "", None
            return
        async for item in cache_path.iterdir():
            if await item.is_file():
                async with aiofiles.open(item) as f:
                    yield item.as_posix(), await f.read()

    async def close(self) -> None:
        """File cache does not need to close resources."""
        pass


def FileCache(base: Path = settings.TEMP_PATH, ttl: int | None = None) -> CacheBackend:
    """Get a file cache backend instance (Redis or file system).

    Thee `ttl` is only valid in a Redis environment.
    """
    if settings.CACHE_BACKEND_TYPE == "redis":
        # If using Redis, set the cache's time-to-live to the configured number of days converted to seconds.
        return RedisBackend(ttl=ttl or settings.TEMP_FILE_DAYS * 24 * 3600)
    else:
        # If using the file system, expired files will be automatically cleaned up when the service stops.
        return FileBackend(base=base)


def AsyncFileCache(
    base: Path = settings.TEMP_PATH, ttl: int | None = None
) -> AsyncCacheBackend:
    """Get an asynchronous file cache backend instance (Redis or file system).

    The `ttl` is only valid in a Redis environment.
    """
    if settings.CACHE_BACKEND_TYPE == "redis":
        # If using Redis, set the cache's time-to-live to the configured number of days converted to seconds.
        return AsyncRedisBackend(ttl=ttl or settings.TEMP_FILE_DAYS * 24 * 3600)
    else:
        # If using the file system, expired files will be automatically cleaned up when the service stops.
        return AsyncFileBackend(base=base)


def Cache(
    cache_type: Literal["ttl", "lru"] = "ttl",
    maxsize: int | None = None,
    ttl: int | None = None,
) -> CacheBackend:
    """Get a cache backend instance (memory or Redis) based on the configuration. The
    `maxsize` is only effective when Redis is not enabled.

    :param cache_type: The type of cache, only effective when using memory cache.
        Supports 'ttl' (default) and 'lru'.
    :param maxsize: The maximum number of entries in the cache, only effective when
        using cachetools.
    :param ttl: The default time-to-live of the cache in seconds.
    :return: Returns a cache backend instance.
    """
    if settings.CACHE_BACKEND_TYPE == "redis":
        return RedisBackend(ttl=ttl)
    else:
        # Use memory cache, maxsize needs to have a value.
        return MemoryBackend(cache_type=cache_type, maxsize=maxsize, ttl=ttl)


def AsyncCache(
    cache_type: Literal["ttl", "lru"] = "ttl",
    maxsize: int | None = None,
    ttl: int | None = None,
) -> AsyncCacheBackend:
    """Get an asynchronous cache backend instance (memory or Redis) based on the
    configuration. The `maxsize` is only effective when Redis is not enabled.

    :param cache_type: The type of cache, only effective when using memory cache.
        Supports 'ttl' (default) and 'lru'.
    :param maxsize: The maximum number of entries in the cache, only effective when
        using cachetools.
    :param ttl: The default time-to-live of the cache in seconds.
    :return: Returns an asynchronous cache backend instance.
    """
    if settings.CACHE_BACKEND_TYPE == "redis":
        return AsyncRedisBackend(ttl=ttl)
    else:
        # Use asynchronous memory cache, maxsize needs to have a value.
        return AsyncMemoryBackend(cache_type=cache_type, maxsize=maxsize, ttl=ttl)


def cached(
    region: str = None,
    maxsize: int | None = 1024,
    ttl: int | None = None,
    skip_none: bool | None = True,
    skip_empty: bool | None = False,
):
    """Custom cache decorator that supports dynamically passing maxsize and ttl for each
    key.

    :param region: The region of the cache.
    :param maxsize: The maximum number of entries in the cache.
    :param ttl: The time-to-live of the cache in seconds. If not provided, it will be
        cached permanently.
    :param skip_none: Skip caching None values, defaults to True.
    :param skip_empty: Skip caching empty values (e.g., None, [], {}, "", set()),
        defaults to False.
    :return: The decorator function.
    """

    def decorator(func):
        def should_cache(value: Any) -> bool:
            """Determine if the result should be cached. If the return value is None or
            empty, it will not be cached.

            :param value: The cache value to be checked.
            :return: Whether to cache the result.
            """
            if skip_none and value is None:
                return False
            # if skip_empty and value in [None, [], {}, "", set()]:
            if skip_empty and not value:
                return False
            return True

        def is_valid_cache_value(
            _cache_key: str, _cached_value: Any, _cache_region: str
        ) -> bool:
            """Check if the specified value is a valid cache value.

            :param _cache_key: The key of the cache.
            :param _cached_value: The value of the cache.
            :param _cache_region: The region of the cache.
            :return: True if the value is a valid cache value, otherwise False.
            """
            # If skip_none is False and the value is None, we need to check if the cache actually exists.
            if not skip_none and _cached_value is None:
                if not cache_backend.exists(key=_cache_key, region=_cache_region):
                    return False
            return True

        async def async_is_valid_cache_value(
            _cache_key: str, _cached_value: Any, _cache_region: str
        ) -> bool:
            """Check if the specified value is a valid cache value (asynchronous
            version).

            :param _cache_key: The key of the cache.
            :param _cached_value: The value of the cache.
            :param _cache_region: The region of the cache.
            :return: True if the value is a valid cache value, otherwise False.
            """
            if not skip_none and _cached_value is None:
                if not await cache_backend.exists(key=_cache_key, region=_cache_region):
                    return False
            return True

        def __get_cache_key(args, kwargs) -> str:
            """Generate a cache key based on the function and its arguments.

            :param args: Positional arguments.
            :param kwargs: Keyword arguments.
            :return: The cache key.
            """
            signature = inspect.signature(func)
            # Bind the incoming arguments and apply default values.
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            # Ignore the first argument if it is an instance (self) or a class (cls).
            parameters = list(signature.parameters.keys())
            if parameters and parameters[0] in ("self", "cls"):
                bound.arguments.pop(parameters[0], None)
            # Extract the list of argument values in the order of the function signature.
            keys = [
                bound.arguments[param]
                for param in signature.parameters
                if param in bound.arguments
            ]
            # Generate the cache key using the ordered arguments.
            return f"{func.__name__}_{hashkey(*keys)}"

        # Get the cache region.
        cache_region = (
            region if region is not None else f"{func.__module__}.{func.__name__}"
        )

        # Check if it is an asynchronous function.
        is_async = inspect.iscoroutinefunction(func)

        if is_async:
            # Asynchronous functions use the asynchronous cache backend.
            cache_backend = AsyncCache(
                cache_type="ttl" if ttl else "lru", maxsize=maxsize, ttl=ttl
            )

            # Cache decorator for asynchronous functions.
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                # Get the cache key.
                cache_key = __get_cache_key(args, kwargs)
                # Try to get the cache.
                if not is_fresh():
                    # Try to get the cache.
                    cached_value = await cache_backend.get(
                        cache_key, region=cache_region
                    )
                    if should_cache(cached_value) and await async_is_valid_cache_value(
                        cache_key, cached_value, cache_region
                    ):
                        return cached_value
                # Execute the asynchronous function and cache the result.
                result = await func(*args, **kwargs)
                # Determine if caching is needed.
                if not should_cache(result):
                    return result
                # Set the cache.
                # if maxsize and ttl are passed, they will override the default values.
                await cache_backend.set(
                    cache_key, result, ttl=ttl, maxsize=maxsize, region=cache_region
                )
                return result

            async def cache_clear():
                """Clear the cache region."""
                await cache_backend.clear(region=cache_region)

            async_wrapper.cache_region = cache_region
            async_wrapper.cache_clear = cache_clear
            return async_wrapper
        else:
            # Synchronous functions use the synchronous cache backend.
            cache_backend = Cache(
                cache_type="ttl" if ttl else "lru", maxsize=maxsize, ttl=ttl
            )

            # Cache decorator for synchronous functions.
            @wraps(func)
            def wrapper(*args, **kwargs):
                # Get the cache key.
                cache_key = __get_cache_key(args, kwargs)

                if not is_fresh():
                    # Try to get the cache.
                    cached_value = cache_backend.get(cache_key, region=cache_region)
                    if should_cache(cached_value) and is_valid_cache_value(
                        cache_key, cached_value, cache_region
                    ):
                        return cached_value
                # Execute the function and cache the result.
                result = func(*args, **kwargs)
                # Determine if caching is needed.
                if not should_cache(result):
                    return result
                # Set the cache .
                # if maxsize and ttl are passed, they will override the default values.
                cache_backend.set(
                    cache_key, result, ttl=ttl, maxsize=maxsize, region=cache_region
                )
                return result

            def cache_clear():
                """Clear the cache region."""
                cache_backend.clear(region=cache_region)

            wrapper.cache_region = cache_region
            wrapper.cache_clear = cache_clear
            return wrapper

    return decorator


class CacheProxy:
    """Cache proxy class that directly proxies cache backend methods to the instance."""

    def __init__(self, cache_backend: CacheBackend, region: str):
        """Initialize the cache proxy.

        :param cache_backend: The cache backend instance.
        :param region: The cache region.
        """
        self._cache_backend = cache_backend
        self._region = region

    def __getitem__(self, key):
        """Get a cache item."""
        value = self._cache_backend.get(key, region=self._region)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key, value):
        """Set a cache item."""
        kwargs = {"region": self._region}
        self._cache_backend.set(key, value, **kwargs)

    def __delitem__(self, key):
        """Delete a cache item."""
        if not self._cache_backend.exists(key, region=self._region):
            raise KeyError(key)
        self._cache_backend.delete(key, region=self._region)

    def __contains__(self, key):
        """Check if a key exists."""
        return self._cache_backend.exists(key, region=self._region)

    def __iter__(self):
        """Return an iterator for the cache."""
        for key, _ in self._cache_backend.items(region=self._region):
            yield key

    def __len__(self):
        """Return the number of cache items."""
        return sum(1 for _ in self._cache_backend.items(region=self._region))

    def is_redis(self) -> bool:
        """Check if the current cache backend is Redis."""
        return self._cache_backend.is_redis()

    def get(self, key: str, **kwargs) -> Any:
        """Get a cache value."""
        kwargs.setdefault("region", self._region)
        return self._cache_backend.get(key, **kwargs)

    def set(self, key: str, value: Any, **kwargs) -> None:
        """Set a cache value."""
        kwargs.setdefault("region", self._region)
        self._cache_backend.set(key, value, **kwargs)

    def delete(self, key: str, **kwargs) -> None:
        """Delete a cache value."""
        kwargs.setdefault("region", self._region)
        self._cache_backend.delete(key, **kwargs)

    def exists(self, key: str, **kwargs) -> bool:
        """Check if a cache key exists."""
        kwargs.setdefault("region", self._region)
        return self._cache_backend.exists(key, **kwargs)

    def clear(self, **kwargs) -> None:
        """Clear the cache."""
        kwargs.setdefault("region", self._region)
        self._cache_backend.clear(**kwargs)

    def items(self, **kwargs):
        """Get all cache items."""
        kwargs.setdefault("region", self._region)
        return self._cache_backend.items(**kwargs)

    def keys(self, **kwargs):
        """Get all cache keys."""
        kwargs.setdefault("region", self._region)
        return self._cache_backend.keys(**kwargs)

    def values(self, **kwargs):
        """Get all cache values."""
        kwargs.setdefault("region", self._region)
        return self._cache_backend.values(**kwargs)

    def update(self, other: dict[str, Any], **kwargs) -> None:
        """Update the cache."""
        kwargs.setdefault("region", self._region)
        self._cache_backend.update(other, **kwargs)

    def pop(self, key: str, default: Any = None, **kwargs) -> Any:
        """Pop a cache item."""
        kwargs.setdefault("region", self._region)
        return self._cache_backend.pop(key, default, **kwargs)

    def popitem(self, **kwargs) -> tuple[str, Any]:
        """Pop the last cache item."""
        kwargs.setdefault("region", self._region)
        return self._cache_backend.popitem(**kwargs)

    def setdefault(self, key: str, default: Any = None, **kwargs) -> Any:
        """Set a default value."""
        kwargs.setdefault("region", self._region)
        return self._cache_backend.setdefault(key, default, **kwargs)

    def close(self) -> None:
        """Close the cache connection."""
        self._cache_backend.close()


class TTLCache(CacheProxy):
    """TTL-based cache class, compatible with the cachetools.TTLCache interface.

    Uses the project's cache backend implementation, supporting Redis and memory
    caching.
    """

    def __init__(
        self,
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
        maxsize: int | None = CacheConfig.DEFAULT_CACHE_SIZE,
        ttl: int | None = CacheConfig.DEFAULT_CACHE_TTL,
    ):
        """Initialize the TTL cache.

        :param maxsize: The maximum number of entries in the cache.
        :param ttl: The time-to-live of the cache in seconds.
        :param region: The region of the cache. If None, the default region is used.
        """
        super().__init__(Cache(cache_type="ttl", maxsize=maxsize, ttl=ttl), region)


class LRUCache(CacheProxy):
    """LRU-based cache class, compatible with the cachetools.LRUCache interface.

    Uses the project's cache backend implementation, supporting Redis and memory
    caching.
    """

    def __init__(
        self,
        region: str = CacheConfig.DEFAULT_CACHE_REGION,
        maxsize: int | None = CacheConfig.DEFAULT_CACHE_SIZE,
    ):
        """Initialize the LRU cache.

        :param maxsize: The maximum number of entries in the cache.
        :param region: The region of the cache. If None, the default region is used.
        """
        super().__init__(Cache(cache_type="lru", maxsize=maxsize), region)
