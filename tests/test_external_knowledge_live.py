"""
Live интеграционный тест внешних провайдеров (без моков).

Запуск:
  python3 tests/test_external_knowledge_live.py

Опционально строгий режим:
  LIVE_EXTERNAL_TEST_STRICT=true python3 tests/test_external_knowledge_live.py
"""

import asyncio
import os
import sys
from typing import List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from external_knowledge.providers import TavilyProvider, ExaProvider, FirecrawlProvider
from external_knowledge.router import ExternalKnowledgeRouter


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


async def _run_provider_test(name: str, provider, query: str) -> Tuple[str, int, str]:
    chunks = await provider.search(query=query, context={"domain": "python"}, limit=3)
    if not chunks:
        return name, 0, "no_results"
    return name, len(chunks), "ok"


async def run_live_tests() -> int:
    strict = _is_true(os.getenv("LIVE_EXTERNAL_TEST_STRICT", "false"))
    query = os.getenv("LIVE_EXTERNAL_TEST_QUERY", "fastapi jwt authentication middleware")

    providers = []
    skipped = []

    tavily = TavilyProvider()
    if tavily.enabled and tavily.api_key:
        providers.append(("tavily", tavily))
    else:
        skipped.append("tavily")

    exa = ExaProvider()
    if exa.enabled and exa.api_key:
        providers.append(("exa", exa))
    else:
        skipped.append("exa")

    firecrawl = FirecrawlProvider()
    if firecrawl.enabled and firecrawl.api_key:
        providers.append(("firecrawl", firecrawl))
    else:
        skipped.append("firecrawl")

    if not providers:
        message = "No live providers configured. Set at least one API key: TAVILY_API_KEY / EXA_API_KEY / FIRECRAWL_API_KEY"
        if strict:
            print(f"[FAIL] {message}")
            return 1
        print(f"[SKIP] {message}")
        return 0

    print(f"[INFO] Running live provider tests for query: {query}")
    for provider_name in skipped:
        print(f"[SKIP] {provider_name}: disabled or API key not set")

    failed = 0
    for provider_name, provider in providers:
        name, count, status = await _run_provider_test(provider_name, provider, query)
        if status == "ok":
            print(f"[PASS] {name}: {count} chunks")
        else:
            print(f"[FAIL] {name}: no results")
            failed += 1

    router = ExternalKnowledgeRouter(
        providers=[provider for _, provider in providers],
        cache_ttl_seconds=60
    )
    aggregated = await router.search(query=query, context={"domain": "python"}, limit=5)
    print(f"[INFO] Aggregated count: {aggregated['count']}, providers_used: {aggregated['providers_used']}")

    for idx, chunk in enumerate(aggregated["chunks"], 1):
        meta = chunk.get("metadata") or {}
        rerank_score = meta.get("rerank_score")
        source_weight = meta.get("source_weight")
        print(f"[INFO] #{idx} source={chunk['source']} rerank_score={rerank_score} source_weight={source_weight}")

    if aggregated["count"] == 0:
        print("[FAIL] Router returned zero chunks in live mode")
        failed += 1

    if strict and skipped:
        print(f"[FAIL] Strict mode enabled, but providers skipped: {', '.join(skipped)}")
        failed += 1

    if failed > 0:
        print(f"[FAIL] Live tests completed with {failed} failure(s)")
        return 1

    print("[PASS] Live external knowledge tests passed")
    return 0


if __name__ == "__main__":
    code = asyncio.run(run_live_tests())
    raise SystemExit(code)
