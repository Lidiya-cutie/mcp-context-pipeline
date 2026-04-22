"""
Тесты роутера внешних знаний (этап 1).
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from external_knowledge.base import BaseExternalKnowledgeProvider, KnowledgeChunk
from external_knowledge.router import ExternalKnowledgeRouter


class FakeProviderA(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("fake_a")

    async def search(self, query, context=None, limit=5):
        return [
            KnowledgeChunk(
                title="A-1",
                content=f"Result for {query}",
                source=self.name,
                score=0.9,
                url="https://example.com/a1"
            ),
            KnowledgeChunk(
                title="A-dup",
                content="Duplicate payload",
                source=self.name,
                score=0.7
            )
        ]


class FakeProviderB(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("fake_b")

    async def search(self, query, context=None, limit=5):
        return [
            KnowledgeChunk(
                title="B-1",
                content="Unique payload",
                source=self.name,
                score=0.8,
                url="https://example.com/b1"
            ),
            KnowledgeChunk(
                title="A-dup",
                content="Duplicate payload",
                source="fake_a",
                score=0.5
            )
        ]


class FakeGitHubProvider(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("github")

    async def search(self, query, context=None, limit=5):
        return [
            KnowledgeChunk(
                title="GitHub JWT Middleware",
                content=f"Implementation details for {query} in repository source code.",
                source=self.name,
                score=0.4,
                url="https://github.com/example/repo/blob/main/auth.py"
            )
        ]


class ErrorProvider(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("broken")

    async def search(self, query, context=None, limit=5):
        raise RuntimeError("provider failure")


async def run_test():
    router = ExternalKnowledgeRouter(
        providers=[FakeProviderA(), FakeProviderB(), FakeGitHubProvider(), ErrorProvider()],
        cache_ttl_seconds=60
    )

    first = await router.search("jwt auth", context={"domain": "python"}, limit=5)
    assert first["count"] == 4, f"Expected 4 chunks after dedup, got {first['count']}"
    assert "broken" in first["provider_errors"], "Expected provider error to be captured"
    assert first["chunks"][0]["source"] == "github", "Expected source-priority rerank to place github first"
    assert "rerank_score" in (first["chunks"][0].get("metadata") or {}), "Expected rerank metadata in chunk"

    second = await router.search("jwt auth", context={"domain": "python"}, limit=5)
    assert second["count"] == first["count"], "Cached result count mismatch"
    assert second["cached"] is True, "Expected cached response flag"

    metrics = router.get_metrics()
    assert metrics["requests_total"] >= 2, "Expected requests_total >= 2"
    assert metrics["cache_hits"] >= 1, "Expected at least one cache hit"
    assert metrics["hit_rate"] > 0.0, "Expected positive hit rate"
    assert metrics["latency_ms_p95"] >= 0.0, "Expected p95 latency metric"
    assert "github" in metrics["source_distribution"], "Expected github in source distribution"
    provider_health = await router.get_provider_health()
    assert "broken" in provider_health, "Expected broken provider in health state"
    assert provider_health["broken"]["status"] == "error", "Expected error status for broken provider"

    print("[PASS] External knowledge router test passed")
    print(f"Chunks: {first['count']}, Providers used: {first['providers_used']}")
    print(f"Metrics: hit_rate={metrics['hit_rate']:.2f}, p95={metrics['latency_ms_p95']:.2f}ms")


if __name__ == "__main__":
    asyncio.run(run_test())
