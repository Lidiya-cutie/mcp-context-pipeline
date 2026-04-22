from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

try:
    from src.external_knowledge.evaluation import OfflineExternalKnowledgeEvaluator
    from src.rest_api_evaluator import RESTAPIEvaluator
except ImportError:
    from external_knowledge.evaluation import OfflineExternalKnowledgeEvaluator
    from rest_api_evaluator import RESTAPIEvaluator


class UnifiedEvaluator:
    def __init__(
        self,
        external_knowledge_dataset: Optional[str] = None,
        rest_api_dataset: Optional[str] = None,
        record_limit: Optional[int] = None,
    ):
        load_dotenv()

        self.external_knowledge_dataset = external_knowledge_dataset or os.getenv(
            "EVAL_DATASET_PATH", ""
        )
        self.rest_api_dataset = rest_api_dataset or os.getenv("REST_API_EVAL_DATASET", "")
        self.record_limit = record_limit or (
            int(os.getenv("EVAL_RECORD_LIMIT", ""))
            if os.getenv("EVAL_RECORD_LIMIT", "").strip()
            else None
        )

    async def run_external_knowledge_eval(self) -> Optional[Dict[str, Any]]:
        if not self.external_knowledge_dataset or not Path(self.external_knowledge_dataset).exists():
            return None

        evaluator = OfflineExternalKnowledgeEvaluator(
            dataset_path=self.external_knowledge_dataset,
            top_k=int(os.getenv("EVAL_TOP_K", "5")),
            record_limit=self.record_limit,
            cache_warm_repeat=int(os.getenv("EVAL_CACHE_WARM_REPEAT", "1")),
        )
        return await evaluator.run()

    async def run_rest_api_eval(self) -> Optional[Dict[str, Any]]:
        if not self.rest_api_dataset or not Path(self.rest_api_dataset).exists():
            return None

        evaluator = RESTAPIEvaluator(
            dataset_path=self.rest_api_dataset,
            record_limit=self.record_limit,
        )
        return await evaluator.run()

    async def run(self) -> Dict[str, Any]:
        ext_knowledge_report, rest_api_report = await asyncio.gather(
            self.run_external_knowledge_eval(),
            self.run_rest_api_eval(),
        )

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "external_knowledge": ext_knowledge_report,
            "rest_api": rest_api_report,
            "overall_status": "pass",
        }

        if ext_knowledge_report and ext_knowledge_report.get("status") == "fail":
            report["overall_status"] = "fail"
        if rest_api_report and rest_api_report.get("status") == "fail":
            report["overall_status"] = "fail"

        if ext_knowledge_report is None and rest_api_report is None:
            report["overall_status"] = "unknown"
            report["error"] = "No evaluation datasets found"

        return report

    async def run_and_export(self, output_dir: str) -> Dict[str, Any]:
        report = await self.run()
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        json_path = output_path / "unified_eval_report.json"
        summary_path = output_path / "unified_eval_summary.txt"

        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        summary_lines = [
            "=" * 72,
            "UNIFIED EVALUATION REPORT",
            "=" * 72,
            f"timestamp: {report['timestamp']}",
            f"overall_status: {report.get('overall_status', 'unknown')}",
        ]

        if report.get("external_knowledge"):
            ek = report["external_knowledge"]
            summary_lines.extend([
                "-" * 72,
                "External Knowledge Evaluation:",
                f"  status: {ek.get('status', 'unknown')}",
                f"  records: {ek.get('quality', {}).get('count', 0)}",
                f"  recall@k: {ek.get('quality', {}).get('recall_at_k', 0):.4f}",
                f"  mrr: {ek.get('quality', {}).get('mrr', 0):.4f}",
                f"  latency_p95_ms: {ek.get('quality', {}).get('latency_ms_p95', 0):.2f}",
                f"  cache_hit_rate: {ek.get('quality', {}).get('cache_hit_rate', 0):.4f}",
            ])

        if report.get("rest_api"):
            ra = report["rest_api"]
            summary_lines.extend([
                "-" * 72,
                "REST API Evaluation:",
                f"  status: {ra.get('status', 'unknown')}",
                f"  endpoints: {ra.get('quality', {}).get('count', 0)}",
                f"  resource_orientation: {ra.get('quality', {}).get('resource_orientation', {}).get('score', 0):.4f}",
                f"  pagination: {ra.get('quality', {}).get('pagination', {}).get('score', 0):.4f}",
                f"  versioning: {ra.get('quality', {}).get('versioning', {}).get('score', 0):.4f}",
                f"  error_codes: {ra.get('quality', {}).get('error_codes', {}).get('score', 0):.4f}",
                f"  structural_redundancy: {ra.get('quality', {}).get('structural_redundancy', {}).get('score', 0):.4f}",
                f"  overall_score: {ra.get('quality', {}).get('overall_score', 0):.4f}",
            ])

        summary_lines.append("=" * 72)
        summary_path.write_text("\n".join(summary_lines), encoding="utf-8")

        report["artifacts"] = {
            "json": str(json_path),
            "summary": str(summary_path),
        }
        return report


async def main() -> int:
    evaluator = UnifiedEvaluator()
    report = await evaluator.run_and_export("artifacts/unified_eval")

    print("=" * 72)
    print("UNIFIED EVALUATION")
    print("=" * 72)
    print(f"overall_status: {report.get('overall_status', 'unknown')}")
    print()

    if report.get("external_knowledge"):
        ek = report["external_knowledge"]
        print("External Knowledge:")
        print(f"  status: {ek.get('status', 'unknown')}")
        print(f"  recall@k: {ek.get('quality', {}).get('recall_at_k', 0):.4f}")
        print(f"  mrr: {ek.get('quality', {}).get('mrr', 0):.4f}")
        print()

    if report.get("rest_api"):
        ra = report["rest_api"]
        print("REST API:")
        print(f"  status: {ra.get('status', 'unknown')}")
        print(f"  overall_score: {ra.get('quality', {}).get('overall_score', 0):.4f}")
        print()

    print("artifacts:")
    for artifact_type, path in report.get("artifacts", {}).items():
        print(f"  {artifact_type}: {path}")
    print("=" * 72)

    return 0 if report.get("overall_status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
