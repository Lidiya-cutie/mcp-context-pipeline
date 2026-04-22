"""
Тест этапа 2.2: персистентный кэш в Redis между инстансами роутера.
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from external_knowledge.base import BaseExternalKnowledgeProvider, KnowledgeChunk
from external_knowledge.router import ExternalKnowledgeRouter


class CountingProvider(BaseExternalKnowledgeProvider):
    def __init__(self, name: str = "counting"):
        super().__init__(name)
        self.calls = 0

    async def search(self, query, context=None, limit=5):
        self.calls += 1
        return [
            KnowledgeChunk(
                title="Redis Cache Test",
                content=f"query={query}",
                source=self.name,
                score=0.5
            )
        ]


async def run_test():
    os.environ["EXTERNAL_KNOWLEDGE_USE_REDIS"] = "true"
    os.environ["REDIS_URL"] = os.getenv("REDIS_URL", "redis://localhost:6379")
    prefix = f"extk_test_{int(time.time())}"
    os.environ["EXTERNAL_KNOWLEDGE_REDIS_PREFIX"] = prefix

    # 1) Первый роутер: кэшируется в Redis
    provider1 = CountingProvider()
    router1 = ExternalKnowledgeRouter([provider1], cache_ttl_seconds=120)
    result1 = await router1.search("redis persistent cache", context={"domain": "python"}, limit=3)
    assert result1["cached"] is False, "First call must be non-cached"
    assert provider1.calls == 1, f"Expected provider call count 1, got {provider1.calls}"

    # 2) Новый инстанс роутера: должен взять результат из Redis без вызова провайдера
    provider2 = CountingProvider()
    router2 = ExternalKnowledgeRouter([provider2], cache_ttl_seconds=120)
    result2 = await router2.search("redis persistent cache", context={"domain": "python"}, limit=3)
    assert result2["cached"] is True, "Expected Redis cache hit in second router instance"
    assert provider2.calls == 0, f"Provider must not be called on Redis cache hit, got {provider2.calls}"

    history = await router2.get_metrics_history(limit=10)
    assert len(history) >= 1, "Expected at least one metrics history record from Redis persistence"

    metrics2 = router2.get_metrics()
    assert metrics2["cache_hits"] >= 1, "Expected cache hit metric increment"
    assert metrics2["hit_rate"] > 0.0, "Expected positive hit_rate"
    assert metrics2["redis_cache_enabled"] is True, "Expected Redis cache enabled metric"

    print("[PASS] Redis persistent cache test passed")
    print(f"cache_hits={metrics2['cache_hits']} hit_rate={metrics2['hit_rate']:.2f}")


if __name__ == "__main__":
    asyncio.run(run_test())
