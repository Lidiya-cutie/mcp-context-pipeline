"""
REST API quality evaluation runner.

Artifacts:
- rest_api_eval_report.json
- rest_api_eval.prom
- rest_api_eval_summary.txt
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

try:
    from src.rest_api_evaluator import RESTAPIEvaluator
except ImportError:
    from rest_api_evaluator import RESTAPIEvaluator


def _resolve_default_dataset() -> str:
    root = Path(__file__).resolve().parent
    candidates = [
        "data/rest_api_eval_good.jsonl",
        "data/rest_api_eval_poor.jsonl",
        "rest_api_eval.jsonl",
    ]
    for candidate in candidates:
        path = root / candidate
        if path.exists():
            return str(path)
    return str(root / "data/rest_api_eval_good.jsonl")


async def main() -> int:
    load_dotenv()
    dataset_path = os.getenv("REST_API_EVAL_DATASET", _resolve_default_dataset())
    output_dir = os.getenv("REST_API_EVAL_OUTPUT", "artifacts/rest_api_eval")
    record_limit_raw = os.getenv("REST_API_EVAL_RECORD_LIMIT", "").strip()
    record_limit = int(record_limit_raw) if record_limit_raw else None

    evaluator = RESTAPIEvaluator(
        dataset_path=dataset_path,
        record_limit=record_limit,
    )
    report = await evaluator.run_and_export(output_dir=output_dir)

    print("=" * 72)
    print("REST API QUALITY EVAL")
    print("=" * 72)
    print(f"dataset: {dataset_path}")
    print(f"status: {report['status']}")
    print(f"endpoints: {report['quality']['count']}")
    print(f"resource_orientation: {report['quality']['resource_orientation']['score']:.4f}")
    print(f"pagination: {report['quality']['pagination']['score']:.4f}")
    print(f"versioning: {report['quality']['versioning']['score']:.4f}")
    print(f"error_codes: {report['quality']['error_codes']['score']:.4f}")
    print(f"structural_redundancy: {report['quality']['structural_redundancy']['score']:.4f}")
    print(f"overall_score: {report['quality']['overall_score']:.4f}")
    print("-" * 72)
    print("gate_checks:")
    for check in report["gates"]["checks"]:
        status_icon = "PASS" if check["status"] == "pass" else "FAIL"
        print(f"  {check['name']}: {check['value']:.4f} (target: {check['threshold']}) [{status_icon}]")
    print("-" * 72)
    print("artifacts:")
    artifacts = report.get("artifacts", {})
    print(f"  json: {artifacts.get('json', '')}")
    print(f"  prom: {artifacts.get('prom', '')}")
    print(f"  summary: {artifacts.get('summary', '')}")
    print("=" * 72)

    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
