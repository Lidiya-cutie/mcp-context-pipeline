"""
Offline quality and reliability evaluation runner for external knowledge router.

Artifacts:
- external_knowledge_eval_report.json
- external_knowledge_eval.prom
- external_knowledge_eval_summary.txt
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

try:
    from src.external_knowledge.evaluation import OfflineExternalKnowledgeEvaluator
except ImportError:
    from external_knowledge.evaluation import OfflineExternalKnowledgeEvaluator


def _resolve_default_dataset() -> str:
    root = Path(__file__).resolve().parent
    for candidate in ("eval_queries_v3.jsonl", "eval_queries_v2.jsonl", "eval_queries_v1.jsonl"):
        path = root / candidate
        if path.exists():
            return str(path)
    return str(root / "eval_queries_v1.jsonl")


async def main() -> int:
    load_dotenv()
    dataset_path = os.getenv("EVAL_DATASET_PATH", _resolve_default_dataset())
    output_dir = os.getenv("EVAL_OUTPUT_DIR", "artifacts/external_knowledge_eval")
    top_k = int(os.getenv("EVAL_TOP_K", "5"))
    record_limit_raw = os.getenv("EVAL_RECORD_LIMIT", "").strip()
    record_limit = int(record_limit_raw) if record_limit_raw else None

    evaluator = OfflineExternalKnowledgeEvaluator(
        dataset_path=dataset_path,
        top_k=top_k,
        record_limit=record_limit,
        cache_warm_repeat=int(os.getenv("EVAL_CACHE_WARM_REPEAT", "1")),
    )
    report = await evaluator.run_and_export(output_dir=output_dir)

    print("=" * 72)
    print("EXTERNAL KNOWLEDGE OFFLINE EVAL")
    print("=" * 72)
    print(f"dataset: {dataset_path}")
    print(f"status: {report['status']}")
    print(f"records: {report['quality']['count']}")
    print(f"recall@k: {report['quality']['recall_at_k']:.4f}")
    print(f"mrr: {report['quality']['mrr']:.4f}")
    print(f"source_coverage: {report['quality']['source_coverage']:.4f}")
    print(f"not_found_rate: {report['quality']['not_found_rate']:.4f}")
    print(f"latency_p95_ms: {report['quality']['latency_ms_p95']:.2f}")
    print(f"cache_hit_rate: {report['quality']['cache_hit_rate']:.4f}")
    print("-" * 72)
    print("artifacts:")
    artifacts = report.get("artifacts", {})
    print(f"  json: {artifacts.get('json', '')}")
    print(f"  prom: {artifacts.get('prometheus', '')}")
    print(f"  summary: {artifacts.get('summary', '')}")
    print("=" * 72)

    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
