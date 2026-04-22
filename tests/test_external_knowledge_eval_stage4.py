"""
Stage 4 test: offline quality/reliability evaluation and artifact export.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from external_knowledge.evaluation import OfflineExternalKnowledgeEvaluator


async def run_test():
    dataset_path = "/mldata/mcp_context_pipeline/eval_queries_v3.jsonl"
    if not Path(dataset_path).exists():
        dataset_path = "/mldata/mcp_context_pipeline/eval_queries_v2.jsonl"

    os.environ["EXTERNAL_KNOWLEDGE_USE_REDIS"] = "false"
    os.environ["EXTERNAL_MASK_PII_QUERIES"] = "true"
    os.environ["EVAL_RECORD_LIMIT"] = "80"
    os.environ["EVAL_MIN_RECALL_AT_K"] = "0.60"
    os.environ["EVAL_MIN_MRR"] = "0.45"
    os.environ["EVAL_MIN_SOURCE_COVERAGE"] = "0.95"
    os.environ["EVAL_MAX_NOT_FOUND_RATE"] = "0.20"
    os.environ["EVAL_MAX_P95_MS"] = "8000"
    os.environ["EVAL_MIN_CACHE_HIT_RATE"] = "0.20"
    os.environ["EVAL_MIN_PROVENANCE_COVERAGE"] = "0.95"
    os.environ["EVAL_MIN_FALLBACK_SUCCESS_RATE"] = "0.95"

    with tempfile.TemporaryDirectory() as tmpdir:
        evaluator = OfflineExternalKnowledgeEvaluator(
            dataset_path=dataset_path,
            top_k=5,
            record_limit=80,
            cache_warm_repeat=1,
        )
        report = await evaluator.run_and_export(output_dir=tmpdir)

        assert report["status"] == "pass", "Expected passing offline evaluation gates"
        assert report["quality"]["recall_at_k"] >= 0.60
        assert report["quality"]["mrr"] >= 0.45
        assert report["quality"]["source_coverage"] >= 0.95
        assert report["quality"]["provenance_coverage"] >= 0.95
        assert report["security"]["pii_masking"]["status"] == "ok"
        assert report["degradation"]["scenarios"], "Expected degradation scenarios in report"

        artifacts = report.get("artifacts", {})
        for key in ("json", "prometheus", "summary"):
            path = artifacts.get(key)
            assert path and Path(path).exists(), f"Missing artifact: {key}"

        loaded = json.loads(Path(artifacts["json"]).read_text(encoding="utf-8"))
        assert loaded["status"] == "pass"
        assert "external_knowledge_eval_recall_at_k" in Path(artifacts["prometheus"]).read_text(encoding="utf-8")

    print("[PASS] Stage 4 external knowledge offline eval test passed")


if __name__ == "__main__":
    asyncio.run(run_test())
