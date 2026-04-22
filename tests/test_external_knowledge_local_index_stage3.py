"""
Тест этапа 3: локальный индекс (SQLite FTS5) как провайдер внешних знаний.
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from external_knowledge.providers import LocalIndexProvider


async def run_test():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "external_index.db")
        os.environ["ENABLE_LOCAL_INDEX_PROVIDER"] = "true"
        os.environ["EXTERNAL_LOCAL_INDEX_DB_PATH"] = db_path
        os.environ["EXTERNAL_LOCAL_INDEX_BOOTSTRAP_DIR"] = ""

        provider = LocalIndexProvider()
        assert provider.enabled, "LocalIndexProvider should be enabled"

        inserted = await provider.ingest_documents(
            [
                {
                    "title": "FastAPI JWT Guide",
                    "content": "How to implement jwt authentication middleware in FastAPI with dependencies.",
                    "source": "test_fixture",
                },
                {
                    "title": "Redis Cache Notes",
                    "content": "Redis cache invalidation strategy for external knowledge router.",
                    "source": "test_fixture",
                },
            ]
        )
        assert inserted == 2, f"Expected 2 inserted docs, got {inserted}"

        chunks = await provider.search("jwt authentication fastapi", limit=3)
        assert chunks, "Expected search results from local index"
        assert chunks[0].source == "local_index", "Unexpected provider source"
        assert "jwt" in chunks[0].content.lower(), "Expected JWT content in first chunk"

    print("[PASS] Stage 3 local index provider test passed")


if __name__ == "__main__":
    asyncio.run(run_test())
