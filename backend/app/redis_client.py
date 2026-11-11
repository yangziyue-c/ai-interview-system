"""缓存抽象：Redis 优先，不可用时自动降级为进程内缓存

用法：
    from app import redis_client
    await redis_client.get_cache().set("key", value, ttl=600)
"""
import logging
import time
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class CacheBase:
    """缓存统一接口"""

    async def get(self, key: str) -> Any | None:  # pragma: no cover
        raise NotImplementedError

    async def set(self, key: str, value: Any, ttl: int = 600) -> None:  # pragma: no cover
        raise NotImplementedError

    async def delete(self, key: str) -> None:  # pragma: no cover
        raise NotImplementedError


class MemoryCache(CacheBase):
    """进程内降级缓存：功能等价 Redis，重启即失"""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}

    async def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if item is None:
            return None
        value, expire_at = item
        if expire_at and time.time() > expire_at:
            self._store.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int = 600) -> None:
        self._store[key] = (value, time.time() + ttl)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


class RedisCache(CacheBase):
    """Redis 缓存（redis.asyncio）"""

    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis

        self._client = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> Any | None:
        import json

        raw = await self._client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw

    async def set(self, key: str, value: Any, ttl: int = 600) -> None:
        import json

        await self._client.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)


_cache: CacheBase | None = None


async def get_cache() -> CacheBase:
    """获取缓存单例：Redis 不可用时自动降级"""
    global _cache
    if _cache is not None:
        return _cache
    if settings.REDIS_URL:
        try:
            candidate = RedisCache(settings.REDIS_URL)
            await candidate.set("__healthcheck__", 1, ttl=5)
            _cache = candidate
            logger.info("Redis 缓存已启用: %s", settings.REDIS_URL)
        except Exception as exc:  # noqa: BLE001 - 任何异常都降级
            logger.warning("Redis 连接失败(%s)，降级为进程内缓存", exc)
            _cache = MemoryCache()
    else:
        logger.info("未配置 REDIS_URL，使用进程内缓存")
        _cache = MemoryCache()
    return _cache
