"""
Тест этапа 2.3: история метрик, JSON/Prometheus экспорт и алерты деградации.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from external_knowledge.base import BaseExternalKnowledgeProvider, KnowledgeChunk
from external_knowledge.router import ExternalKnowledgeRouter


class MetricsProvider(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("context7")

    async def search(self, query, context=None, limit=5):
        return [
            KnowledgeChunk(
                title="Metrics Result",
                content=f"Result for {query}",
                source=self.name,
                score=0.6,
                metadata={}
            )
        ]


async def run_test():
    os.environ["EXTERNAL_KNOWLEDGE_USE_REDIS"] = "false"
    os.environ["EXTERNAL_ALERT_MIN_REQUESTS"] = "1"
    os.environ["EXTERNAL_ALERT_HIT_RATE_MIN"] = "0.9"
    os.environ["EXTERNAL_ALERT_P95_MAX_MS"] = "0.01"

    router = ExternalKnowledgeRouter(
        providers=[MetricsProvider()],
        cache_ttl_seconds=120
    )

    # miss + hit для формирования hit_rate и истории
    first = await router.search("jwt metrics test", context={"domain": "python"}, limit=3)
    second = await router.search("jwt metrics test", context={"domain": "python"}, limit=3)
    assert first["cached"] is False
    assert second["cached"] is True

    history = await router.get_metrics_history(limit=10)
    assert len(history) >= 2, f"Expected at least 2 history points, got {len(history)}"
    assert any(item.get("cached") is True for item in history), "Expected cached history entry"
    assert any(item.get("cached") is False for item in history), "Expected non-cached history entry"

    metrics_json = await router.export_metrics_json(history_limit=10)
    assert "current" in metrics_json and "history" in metrics_json and "alerts" in metrics_json
    assert "provider_health" in metrics_json, "Missing provider_health in JSON export"
    assert metrics_json["current"]["requests_total"] >= 2

    alerts = router.get_alerts(current_metrics=metrics_json["current"])
    assert any(a["name"] == "hit_rate_degradation" for a in alerts), "Missing hit_rate alert"
    assert any(a["name"] == "p95_latency_degradation" for a in alerts), "Missing p95 alert"
    assert any(a["status"] == "firing" for a in alerts), "Expected at least one firing alert"

    prom = router.export_metrics_prometheus()
    assert "external_knowledge_requests_total" in prom
    assert "external_knowledge_hit_rate" in prom
    assert "external_knowledge_latency_ms_p95" in prom
    assert "external_knowledge_alert_status" in prom

    print("[PASS] Stage 2.3 metrics test passed")


if __name__ == "__main__":
    asyncio.run(run_test())
