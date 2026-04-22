"""
Тест этапа 3: маскирование PII в запросах перед внешними SaaS-провайдерами.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from external_knowledge.base import BaseExternalKnowledgeProvider, KnowledgeChunk
from external_knowledge.router import ExternalKnowledgeRouter


class CapturingSaaSProvider(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("tavily")
        self.last_query = None

    async def search(self, query, context=None, limit=5):
        self.last_query = query
        return [
            KnowledgeChunk(
                title="Stub Result",
                content="stub",
                source=self.name,
                score=0.5,
            )
        ]


async def run_test():
    os.environ["EXTERNAL_KNOWLEDGE_USE_REDIS"] = "false"
    os.environ["EXTERNAL_MASK_PII_QUERIES"] = "true"

    provider = CapturingSaaSProvider()
    router = ExternalKnowledgeRouter(providers=[provider], cache_ttl_seconds=30)

    raw_query = "Найди интеграцию fastapi для user@example.com с jwt"
    await router.search(raw_query, context={"domain": "python"}, limit=2)

    assert provider.last_query is not None, "Provider did not receive query"
    assert "user@example.com" not in provider.last_query, "PII email leaked to external provider query"

    print("[PASS] Stage 3 PII masking test passed")


if __name__ == "__main__":
    asyncio.run(run_test())
