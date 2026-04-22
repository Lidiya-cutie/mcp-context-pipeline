"""
Stage 5 test: internal MCP providers (SHIVA + DocFusion) integration.
"""

import asyncio
import os
import sys
from typing import List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from external_knowledge.providers import ShivaProvider, DocFusionProvider


async def test_shiva_provider() -> None:
    os.environ["ENABLE_SHIVA_PROVIDER"] = "true"
    os.environ["SHIVA_MCP_URL"] = "https://shiva.imbalanced.tech/shiva-mcp/v0"
    os.environ["SHIVA_MCP_TOKEN"] = "test-token"
    os.environ["SHIVA_DEFAULT_PROJECT_ID"] = "44"

    provider = ShivaProvider()
    calls: List[Tuple[str, dict]] = []

    async def fake_call_tool_text(tool_name: str, arguments=None) -> str:
        calls.append((tool_name, arguments or {}))
        return f"tool={tool_name} args={arguments or {}}"

    provider._call_tool_text = fake_call_tool_text  # type: ignore[attr-defined]

    chunks = await provider.search("Покажи сводку по проекту", context={"project_id": 44}, limit=3)
    assert chunks, "Expected SHIVA chunks for project context"
    assert chunks[0].source == "shiva"
    assert chunks[0].url == os.environ["SHIVA_MCP_URL"]
    assert any(name == "shiva_get_prjct_summary" for name, _ in calls), "Expected project summary tool call"

    calls.clear()
    provider.default_project_id = ""
    chunks = await provider.search("Покажи список команд", context={}, limit=2)
    assert chunks, "Expected SHIVA chunks for team query"
    assert any(name == "shiva_list_teams" for name, _ in calls), "Expected list teams tool call"


async def test_docfusion_provider() -> None:
    os.environ["ENABLE_DOCFUSION_PROVIDER"] = "true"
    os.environ["DOCFUSION_TOKEN"] = "test-token"
    os.environ["DOCFUSION_KB_URLS"] = "https://doc1.local,https://doc2.local"

    provider = DocFusionProvider()

    async def fake_fetch(url: str) -> str:
        if "doc1" in url:
            return "Architecture standards and release regulations for document catalog."
        return "Unrelated text"

    provider._fetch_url_text = fake_fetch  # type: ignore[attr-defined]

    chunks = await provider.search("release regulations document", limit=2)
    assert chunks, "Expected DocFusion chunks for matching query"
    assert chunks[0].source == "docfusion"
    assert chunks[0].url == "https://doc1.local"
    assert "release regulations" in chunks[0].content.lower()


async def run_all() -> None:
    await test_shiva_provider()
    await test_docfusion_provider()
    print("[PASS] Stage 5 internal MCP providers test passed")


if __name__ == "__main__":
    asyncio.run(run_all())
