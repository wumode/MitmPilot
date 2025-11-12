import json
import pickle
from collections.abc import AsyncGenerator, Generator
from typing import Any
from urllib.parse import quote

import redis
from redis.asyncio import Redis

from app.core.config import settings
from app.core.event import Event, eventmanager
from app.log import logger
from app.schemas import ConfigChangeEventData
from app.schemas.types import EventType
from app.utils.singleton import Singleton

# Type cache collection, for non-container simple types
_complex_serializable_types = set()
_simple_serializable_types = set()

# Default connection parameters
_socket_timeout = 30
_socket_connect_timeout = 5
_health_check_interval = 60


def serialize(value: Any) -> bytes:
    """Serializes the value into binary data, identifying the format based on the
    serialization method."""

    def _is_container_type(t):
        """Checks if it is a container type."""
        return t in (list, dict, tuple, set)

    vt = type(value)
    # Use caching strategy for non-container types
    if not _is_container_type(vt):
        # If known to require complex serialization
        if vt in _complex_serializable_types:
            return b"PICKLE" + b"\x00" + pickle.dumps(value)
        # If known to be simply serializable
        if vt in _simple_serializable_types:
            json_data = json.dumps(value).encode("utf-8")
            return b"JSON" + b"\x00" + json_data
        # For unknown non-container types, try simple serialization; if it throws an
        # exception, then use complex serialization
        try:
            json_data = json.dumps(value).encode("utf-8")
            _simple_serializable_types.add(vt)
            return b"JSON" + b"\x00" + json_data
        except TypeError:
            _complex_serializable_types.add(vt)
            return b"PICKLE" + b"\x00" + pickle.dumps(value)
    else:
        # For container types, always try simple serialization, do not use cache
        try:
            json_data = json.dumps(value).encode("utf-8")
            return b"JSON" + b"\x00" + json_data
        except TypeError:
            return b"PICKLE" + b"\x00" + pickle.dumps(value)


def deserialize(value: bytes) -> Any:
    """Deserializes binary data back to its original value, distinguishing the
    serialization method by format identifier."""
    format_marker, data = value.split(b"\x00", 1)
    if format_marker == b"JSON":
        return json.loads(data.decode("utf-8"))
    elif format_marker == b"PICKLE":
        return pickle.loads(data)
    else:
        raise ValueError("Unknown serialization format")


class RedisHelper(metaclass=Singleton):
    """Redis connection and operation helper class, singleton pattern.

    Features:
    - Manages Redis connection pool and client
    - Provides serialization and deserialization functions
    - Supports memory limit and eviction policy settings
    - Provides key generation and region management functions
    """

    def __init__(self):
        """Initializes the Redis helper instance."""
        self.redis_url = settings.CACHE_BACKEND_URL
        self.client = None

    def _connect(self):
        """Establishes a Redis connection."""
        try:
            if self.client is None:
                self.client = redis.Redis.from_url(
                    self.redis_url,
                    decode_responses=False,
                    socket_timeout=_socket_timeout,
                    socket_connect_timeout=_socket_connect_timeout,
                    health_check_interval=_health_check_interval,
                )
                # Test connection to ensure Redis is available
                self.client.ping()
                logger.info(f"Successfully connected to Redis：{self.redis_url}")
                self.set_memory_limit()
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.client = None
            raise RuntimeError("Redis connection failed") from e

    @eventmanager.register(EventType.ConfigChanged)
    def handle_config_changed(self, event: Event):
        """Handles configuration change events, updates Redis settings.

        :param event: Event object
        """
        if not event:
            return
        event_data: ConfigChangeEventData = event.event_data
        if event_data.key not in [
            "CACHE_BACKEND_TYPE",
            "CACHE_BACKEND_URL",
            "CACHE_REDIS_MAXMEMORY",
        ]:
            return
        logger.info("Configuration changed, reconnecting to Redis...")
        self.close()
        self._connect()

    def set_memory_limit(self, policy: str | None = "allkeys-lru"):
        """Dynamically sets Redis max memory and eviction policy.

        :param policy: Eviction policy (e.g., 'allkeys-lru')
        """
        try:
            # If there is an explicit value, use it directly. If it is 0,
            # it means no limit. If not configured, it is "1024mb"
            # when LARGE_MEMORY_MODE is enabled, and "256mb" when not enabled.
            maxmemory = settings.CACHE_REDIS_MAXMEMORY or (
                "1024mb" if settings.LARGE_MEMORY_MODE else "256mb"
            )
            self.client.config_set("maxmemory", maxmemory)
            self.client.config_set("maxmemory-policy", policy)
            logger.debug(f"Redis maxmemory set to {maxmemory}, policy: {policy}")
        except Exception as e:
            logger.error(f"Failed to set Redis maxmemory or policy: {e}")

    @staticmethod
    def __get_region(region: str | None = None):
        """Gets the cached region."""
        return f"region:{quote(region)}" if region else "region:DEFAULT"

    def __make_redis_key(self, region: str, key: str) -> str:
        """Gets the cache key."""
        # Use region as part of the cache key
        region = self.__get_region(region)
        return f"{region}:key:{quote(key)}"

    @staticmethod
    def __get_original_key(redis_key: str | bytes) -> str:
        """Extracts the original key from the Redis key."""
        if isinstance(redis_key, bytes):
            redis_key = redis_key.decode("utf-8")
        try:
            parts = redis_key.split(":key:")
            return parts[-1]
        except Exception as e:
            logger.warn(f"Failed to parse redis key: {redis_key}, error: {e}")
            return redis_key

    def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        region: str = "DEFAULT",
        **kwargs,
    ) -> None:
        """Sets the cache.

        :param key: Cache key
        :param value: Cache value
        :param ttl: Cache time-to-live, in seconds
        :param region: Cache region
        :param kwargs: Other parameters
        """
        try:
            self._connect()
            redis_key = self.__make_redis_key(region, key)
            # Serialize the value
            serialized_value = serialize(value)
            kwargs.pop("maxsize", None)
            self.client.set(redis_key, serialized_value, ex=ttl, **kwargs)
        except Exception as e:
            logger.error(f"Failed to set key: {key} in region: {region}, error: {e}")

    def exists(self, key: str, region: str = "DEFAULT") -> bool:
        """Checks if the cache key exists.

        :param key: Cache key
        :param region: Cache region
        :return: True if exists, False otherwise
        """
        try:
            self._connect()
            redis_key = self.__make_redis_key(region, key)
            return self.client.exists(redis_key) == 1
        except Exception as e:
            logger.error(f"Failed to exists key: {key} region: {region}, error: {e}")
            return False

    def get(self, key: str, region: str = "DEFAULT") -> Any | None:
        """Gets the cache value.

        :param key: Cache key
        :param region: Cache region
        :return: Returns the cached value, or None if the cache does not exist
        """
        try:
            self._connect()
            redis_key = self.__make_redis_key(region, key)
            value = self.client.get(redis_key)
            if value is not None:
                return deserialize(value)
            return None
        except Exception as e:
            logger.error(f"Failed to get key: {key} in region: {region}, error: {e}")
            return None

    def delete(self, key: str, region: str = "DEFAULT") -> None:
        """Deletes the cache.

        :param key: Cache key
        :param region: Cache region
        """
        try:
            self._connect()
            redis_key = self.__make_redis_key(region, key)
            self.client.delete(redis_key)
        except Exception as e:
            logger.error(f"Failed to delete key: {key} in region: {region}, error: {e}")

    def clear(self, region: str | None = None) -> None:
        """Clears the cache for the specified region or all cache.

        :param region: Cache region
        """
        try:
            self._connect()
            if region:
                cache_region = self.__get_region(region)
                redis_key = f"{cache_region}:key:*"
                with self.client.pipeline() as pipe:
                    for key in self.client.scan_iter(redis_key):
                        pipe.delete(key)
                    pipe.execute()
                logger.debug(f"Cleared Redis cache for region: {region}")
            else:
                self.client.flushdb()
                logger.info("All Redis cache Cleared！")
        except Exception as e:
            logger.error(f"Failed to clear cache, region: {region}, error: {e}")

    def items(self, region: str | None = None) -> Generator[tuple[str, Any]]:
        """Gets all cached key-value pairs for the specified region.

        :param region: Cache region
        :return: Returns a key-value pair generator
        """
        try:
            self._connect()
            if region:
                cache_region = self.__get_region(region)
                redis_key = f"{cache_region}:key:*"
                for key in self.client.scan_iter(redis_key):
                    value = self.client.get(key)
                    if value is not None:
                        yield self.__get_original_key(key), deserialize(value)
            else:
                for key in self.client.scan_iter("*"):
                    value = self.client.get(key)
                    if value is not None:
                        yield self.__get_original_key(key), deserialize(value)
        except Exception as e:
            logger.error(
                f"Failed to get items from Redis, region: {region}, error: {e}"
            )

    def test(self) -> bool:
        """Tests Redis connectivity."""
        try:
            self._connect()
            return True
        except Exception as e:
            logger.error(f"Redis connection test failed: {e}")
            return False

    def close(self) -> None:
        """Closes the Redis client's connection pool."""
        if self.client:
            self.client.close()
            self.client = None
            logger.debug("Redis connection closed")


class AsyncRedisHelper(metaclass=Singleton):
    """Asynchronous Redis connection and operation helper class, singleton pattern.

    Features:
    - Manages asynchronous Redis connection pool and client
    - Provides serialization and deserialization functions
    - Supports memory limit and eviction policy settings
    - Provides key generation and region management functions
    - All operations are asynchronous
    """

    def __init__(self):
        """Initializes the asynchronous Redis helper instance."""
        self.redis_url = settings.CACHE_BACKEND_URL
        self.client: Redis | None = None

    async def _connect(self):
        """Establishes an asynchronous Redis connection."""
        try:
            if self.client is None:
                self.client = Redis.from_url(
                    self.redis_url,
                    decode_responses=False,
                    socket_timeout=_socket_timeout,
                    socket_connect_timeout=_socket_connect_timeout,
                    health_check_interval=_health_check_interval,
                )
                # Test connection to ensure Redis is available
                await self.client.ping()
                logger.info(
                    f"Successfully connected to Redis (async)：{self.redis_url}"
                )
                await self.set_memory_limit()
        except Exception as e:
            logger.error(f"Failed to connect to Redis (async): {e}")
            self.client = None
            raise RuntimeError("Redis async connection failed") from e

    @eventmanager.register(EventType.ConfigChanged)
    async def handle_config_changed(self, event: Event):
        """Handles configuration change events, updates Redis settings.

        :param event: Event object
        """
        if not event:
            return
        event_data: ConfigChangeEventData = event.event_data
        if event_data.key not in [
            "CACHE_BACKEND_TYPE",
            "CACHE_BACKEND_URL",
            "CACHE_REDIS_MAXMEMORY",
        ]:
            return
        logger.info("Configuration changed, reconnecting to Redis (async)...")
        await self.close()
        await self._connect()

    async def set_memory_limit(self, policy: str = "allkeys-lru"):
        """Dynamically sets Redis max memory and eviction policy.

        :param policy: Eviction policy (e.g., 'allkeys-lru')
        """
        try:
            # If there is an explicit value, use it directly. If it is 0, it means no
            # limit. If not configured, it is "1024mb" when LARGE_MEMORY_MODE is
            # enabled, and "256mb" when not enabled.
            maxmemory = settings.CACHE_REDIS_MAXMEMORY or (
                "1024mb" if settings.LARGE_MEMORY_MODE else "256mb"
            )
            await self.client.config_set("maxmemory", maxmemory)
            await self.client.config_set("maxmemory-policy", policy)
            logger.debug(
                f"Redis maxmemory set to {maxmemory}, policy: {policy} (async)"
            )
        except Exception as e:
            logger.error(f"Failed to set Redis maxmemory or policy (async): {e}")

    @staticmethod
    def __get_region(region: str | None = "DEFAULT"):
        """Gets the cached region."""
        return f"region:{region}" if region else "region:default"

    def __make_redis_key(self, region: str, key: str) -> str:
        """Gets the cache key."""
        # Use region as part of the cache key
        region = self.__get_region(region)
        return f"{region}:key:{quote(key)}"

    @staticmethod
    def __get_original_key(redis_key: str | bytes) -> str:
        """Extracts the original key from the Redis key."""
        if isinstance(redis_key, bytes):
            redis_key = redis_key.decode("utf-8")
        try:
            parts = redis_key.split(":key:")
            return parts[-1]
        except Exception as e:
            logger.warn(f"Failed to parse redis key: {redis_key}, error: {e}")
            return redis_key

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        region: str = "DEFAULT",
        **kwargs,
    ) -> None:
        """Asynchronously sets the cache.

        :param key: Cache key
        :param value: Cache value
        :param ttl: Cache time-to-live, in seconds
        :param region: Cache region
        :param kwargs: Other parameters
        """
        try:
            await self._connect()
            redis_key = self.__make_redis_key(region, key)
            # Serialize the value
            serialized_value = serialize(value)
            kwargs.pop("maxsize", None)
            await self.client.set(redis_key, serialized_value, ex=ttl, **kwargs)
        except Exception as e:
            logger.error(
                f"Failed to set key (async): {key} in region: {region}, error: {e}"
            )

    async def exists(self, key: str, region: str = "DEFAULT") -> bool:
        """Asynchronously checks if the cache key exists.

        :param key: Cache key
        :param region: Cache region
        :return: True if exists, False otherwise
        """
        try:
            await self._connect()
            redis_key = self.__make_redis_key(region, key)
            result = await self.client.exists(redis_key)
            return result == 1
        except Exception as e:
            logger.error(
                f"Failed to exists key (async): {key} region: {region}, error: {e}"
            )
            return False

    async def get(self, key: str, region: str = "DEFAULT") -> Any | None:
        """Asynchronously gets the cache value.

        :param key: Cache key
        :param region: Cache region
        :return: Returns the cached value, or None if the cache does not exist
        """
        try:
            await self._connect()
            redis_key = self.__make_redis_key(region, key)
            value = await self.client.get(redis_key)
            if value is not None:
                return deserialize(value)
            return None
        except Exception as e:
            logger.error(
                f"Failed to get key (async): {key} in region: {region}, error: {e}"
            )
            return None

    async def delete(self, key: str, region: str = "DEFAULT") -> None:
        """Asynchronously deletes the cache.

        :param key: Cache key
        :param region: Cache region
        """
        try:
            await self._connect()
            redis_key = self.__make_redis_key(region, key)
            await self.client.delete(redis_key)
        except Exception as e:
            logger.error(
                f"Failed to delete key (async): {key} in region: {region}, error: {e}"
            )

    async def clear(self, region: str | None = None) -> None:
        """Asynchronously clears the cache for the specified region or all cache.

        :param region: Cache region
        """
        try:
            await self._connect()
            if region:
                cache_region = self.__get_region(region)
                redis_key = f"{cache_region}:key:*"
                async with self.client.pipeline() as pipe:
                    async for key in self.client.scan_iter(redis_key):
                        await pipe.delete(key)
                    await pipe.execute()
                logger.debug(f"Cleared Redis cache for region (async): {region}")
            else:
                await self.client.flushdb()
                logger.info("Cleared all Redis cache (async)")
        except Exception as e:
            logger.error(f"Failed to clear cache (async), region: {region}, error: {e}")

    async def items(self, region: str | None = None) -> AsyncGenerator[tuple[str, Any]]:
        """Gets all cached key-value pairs for the specified region.

        :param region: Cache region
        :return: Returns a key-value pair generator
        """
        try:
            await self._connect()
            if region:
                cache_region = self.__get_region(region)
                redis_key = f"{cache_region}:key:*"
                async for key in self.client.scan_iter(redis_key):
                    value = await self.client.get(key)
                    if value is not None:
                        yield self.__get_original_key(key), deserialize(value)
            else:
                async for key in self.client.scan_iter("*"):
                    value = await self.client.get(key)
                    if value is not None:
                        yield self.__get_original_key(key), deserialize(value)
        except Exception as e:
            logger.error(
                f"Failed to get items from Redis, region: {region}, error: {e}"
            )

    async def test(self) -> bool:
        """Asynchronously tests Redis connectivity."""
        try:
            await self._connect()
            return True
        except Exception as e:
            logger.error(f"Redis async connection test failed: {e}")
            return False

    async def close(self) -> None:
        """Closes the asynchronous Redis client's connection pool."""
        if self.client:
            await self.client.close()
            self.client = None
            logger.debug("Redis async connection closed")
