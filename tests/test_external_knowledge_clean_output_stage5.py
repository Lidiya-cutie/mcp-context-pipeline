"""
Stage 5: clean output filters and SHIVA prioritization for project queries.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from external_knowledge.base import BaseExternalKnowledgeProvider, KnowledgeChunk
from external_knowledge.router import ExternalKnowledgeRouter


class KBFallbackProvider(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("knowledge_bridge")

    async def search(self, query, context=None, limit=5):
        return [
            KnowledgeChunk(
                title="Knowledge Bridge standard: project",
                content="[Context 7]: No specific standard found for 'query' in 'project'. Use general best practices.",
                source=self.name,
                score=0.99,
            )
        ]


class DocfusionHtmlProvider(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("docfusion")

    async def search(self, query, context=None, limit=5):
        return [
            KnowledgeChunk(
                title="DocFusion: shell",
                content="<!doctype html><html><body><div id=\"app\"></div></body></html>",
                source=self.name,
                score=0.98,
                url="https://docfusion.example",
            )
        ]


class ShivaSummaryProvider(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("shiva")

    async def search(self, query, context=None, limit=5):
        return [
            KnowledgeChunk(
                title="SHIVA: shiva_get_prjct_summary",
                content="Project Data Science. Total tasks: 724. Team Data Science.",
                source=self.name,
                score=0.70,
                url="https://shiva.imbalanced.tech/shiva-mcp/v0",
                metadata={"tool": "shiva_get_prjct_summary", "project_id": 44},
            )
        ]


class UsefulGenericProvider(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("github")

    async def search(self, query, context=None, limit=5):
        return [
            KnowledgeChunk(
                title="Useful non-noise chunk",
                content="Implementation details for query.",
                source=self.name,
                score=0.65,
                url="https://github.com/example/repo/blob/main/file.py",
            )
        ]


class ErrorChunkProvider(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("shiva")

    async def search(self, query, context=None, limit=5):
        return [
            KnowledgeChunk(
                title="SHIVA error",
                content="Error: SHIVA API error 401: invalid token",
                source=self.name,
                score=0.9,
                url="https://shiva.imbalanced.tech/shiva-mcp/v0",
            )
        ]


async def run_test():
    router = ExternalKnowledgeRouter(
        providers=[
            KBFallbackProvider(),
            DocfusionHtmlProvider(),
            ShivaSummaryProvider(),
        ],
        cache_ttl_seconds=60,
    )

    result = await router.search(
        "покажи сводку по проекту data science",
        context={"domain": "project", "project_id": 44},
        limit=5,
    )
    assert result["count"] == 1, f"Expected only SHIVA chunk, got {result['count']}"
    assert result["chunks"][0]["source"] == "shiva", "Expected SHIVA chunk prioritized for project query"

    router2 = ExternalKnowledgeRouter(
        providers=[
            KBFallbackProvider(),
            DocfusionHtmlProvider(),
            UsefulGenericProvider(),
        ],
        cache_ttl_seconds=60,
    )
    result2 = await router2.search(
        "jwt middleware",
        context={"domain": "python"},
        limit=5,
    )
    assert result2["count"] == 1, f"Expected noise chunks filtered out, got {result2['count']}"
    assert result2["chunks"][0]["source"] == "github", "Expected only useful non-noise chunk"

    router3 = ExternalKnowledgeRouter(
        providers=[ErrorChunkProvider()],
        cache_ttl_seconds=60,
    )
    result3 = await router3.search(
        "покажи сводку по проекту",
        context={"domain": "project", "project_id": 44},
        limit=5,
    )
    assert result3["count"] == 0, "Expected error-only chunks to be excluded"
    assert "shiva" in result3["provider_errors"], "Expected provider_errors to include SHIVA error chunk"

    print("[PASS] Stage 5 clean output filtering test passed")


if __name__ == "__main__":
    asyncio.run(run_test())
