"""
Redis Connection Manager.

Управляет постоянным подключением к Redis для использования в async функциях.
"""

import redis
from typing import Optional
import os


"""
Redis Connection Manager.

Управляет постоянным подключением к Redis для использования в async функциях.
"""

import redis
from typing import Optional
import os
from concurrent.futures import ThreadPoolExecutor


class RedisManager:
    """Менеджер для Redis соединения."""

    def __init__(self):
        """Инициализация менеджера."""
        self._client: Optional[redis.Redis] = None
        self._url = os.getenv("REDIS_URL", "redis://localhost:6379")
        self._executor = ThreadPoolExecutor(max_workers=1)

    def get_client(self) -> Optional[redis.Redis]:
        """Получить или создать Redis клиент."""
        if self._client is None:
            try:
                self._client = redis.Redis(
                    host='localhost',
                    port=6379,
                    db=0,
                    decode_responses=True,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                    health_check_interval=30
                )
                self._client.ping()
                print(f"[INFO] Connected to Redis at {self._url}")
            except Exception as e:
                print(f"[ERROR] Failed to connect to Redis: {e}")
                self._client = None
        return self._client

    def is_available(self) -> bool:
        """Проверить доступен ли Redis."""
        return self._client is not None


# Глобальный экземпляр менеджера
_redis_manager: Optional[RedisManager] = None


def get_redis_manager() -> RedisManager:
    """Получить или создать менеджер."""
    global _redis_manager
    if _redis_manager is None:
        _redis_manager = RedisManager()
    return _redis_manager


# Синхронные функции Redis (для asyncio.to_thread)
def redis_sync_set(key: str, value: str, ttl: int = 86400):
    """Синхронная установка значения."""
    manager = get_redis_manager()
    client = manager.get_client()
    if client:
        client.set(key, value)
        if ttl > 0:
            client.expire(key, ttl)


def redis_sync_get(key: str):
    """Синхронное получение значения."""
    manager = get_redis_manager()
    client = manager.get_client()
    if client:
        return client.get(key)
    return None


def redis_sync_hset(key: str, mapping: dict, ttl: int = 86400):
    """Синхронная установка хэша."""
    manager = get_redis_manager()
    client = manager.get_client()
    if client:
        client.hset(key, mapping=mapping)
        if ttl > 0:
            client.expire(key, ttl)


def redis_sync_hgetall(key: str):
    """Синхронное получение хэша."""
    manager = get_redis_manager()
    client = manager.get_client()
    if client:
        return client.hgetall(key)
    return []


def redis_sync_exists(key: str):
    """Синхронная проверка существования."""
    manager = get_redis_manager()
    client = manager.get_client()
    if client:
        return client.exists(key)
    return False


def redis_sync_hlen(key: str):
    """Синхронное получение длины хэша."""
    manager = get_redis_manager()
    client = manager.get_client()
    if client:
        return client.hlen(key)
    return 0


def redis_sync_ping():
    """Синхронный пинг Redis."""
    manager = get_redis_manager()
    client = manager.get_client()
    if client:
        return client.ping()
    return False
