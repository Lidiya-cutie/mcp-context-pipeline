"""
Тесты этапа 2: реальные HTTP-провайдеры внешних знаний (через моки).
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from external_knowledge.providers import TavilyProvider, ExaProvider, FirecrawlProvider


async def test_tavily_provider():
    provider = TavilyProvider()
    provider.enabled = True
    provider.api_key = "fake-key"

    async def fake_post_json(url, payload, headers=None):
        return {
            "results": [
                {
                    "title": "Tavily JWT Guide",
                    "url": "https://example.com/tavily-jwt",
                    "content": "JWT authentication in FastAPI with best practices.",
                    "score": 0.93,
                }
            ]
        }

    provider._post_json = fake_post_json  # type: ignore[attr-defined]
    chunks = await provider.search("fastapi jwt", limit=3)
    assert len(chunks) == 1, f"Expected 1 chunk, got {len(chunks)}"
    assert chunks[0].source == "tavily"
    assert "JWT" in chunks[0].content


async def test_exa_provider():
    provider = ExaProvider()
    provider.enabled = True
    provider.api_key = "fake-key"

    async def fake_post_json(url, payload, headers=None):
        return {
            "results": [
                {
                    "title": "Exa Redis Patterns",
                    "url": "https://example.com/exa-redis",
                    "text": "Redis caching patterns for high load APIs.",
                    "score": 0.88,
                }
            ]
        }

    provider._post_json = fake_post_json  # type: ignore[attr-defined]
    chunks = await provider.search("redis caching", limit=2)
    assert len(chunks) == 1, f"Expected 1 chunk, got {len(chunks)}"
    assert chunks[0].source == "exa"
    assert "Redis" in chunks[0].content


async def test_firecrawl_provider():
    provider = FirecrawlProvider()
    provider.enabled = True
    provider.api_key = "fake-key"

    async def fake_post_json(url, payload, headers=None):
        return {
            "data": [
                {
                    "title": "Firecrawl FastAPI Security",
                    "url": "https://example.com/firecrawl-fastapi",
                    "markdown": "Security middleware and auth flow for FastAPI services.",
                    "score": 0.84,
                }
            ]
        }

    provider._post_json = fake_post_json  # type: ignore[attr-defined]
    chunks = await provider.search("fastapi security", limit=2)
    assert len(chunks) == 1, f"Expected 1 chunk, got {len(chunks)}"
    assert chunks[0].source == "firecrawl"
    assert "Security" in chunks[0].content


async def run_all():
    await test_tavily_provider()
    await test_exa_provider()
    await test_firecrawl_provider()
    print("[PASS] Stage 2 provider tests passed")


if __name__ == "__main__":
    asyncio.run(run_all())
