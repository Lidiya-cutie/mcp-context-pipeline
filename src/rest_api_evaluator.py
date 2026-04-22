from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .rest_api_metrics import RESTAPIMetrics, Endpoint
from .rest_api_metrics_formulas import evaluate_rest_api_quality


@dataclass
class RESTAPIEvalRecord:
    record_id: str
    method: str
    path: str
    version: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    response: Optional[Dict[str, Any]] = None
    status_code: Optional[int] = None
    headers: Optional[Dict[str, str]] = None


def load_rest_api_records(path: str, limit: Optional[int] = None) -> List[RESTAPIEvalRecord]:
    rows = Path(path).read_text(encoding="utf-8").splitlines()
    records: List[RESTAPIEvalRecord] = []
    for row in rows:
        data = json.loads(row)
        records.append(
            RESTAPIEvalRecord(
                record_id=str(data.get("id")),
                method=str(data.get("method", "GET")).upper(),
                path=str(data.get("path", "/")),
                version=data.get("version"),
                params=dict(data.get("params") or {}),
                response=dict(data.get("response") or {}),
                status_code=int(data.get("status_code")) if data.get("status_code") else None,
                headers=dict(data.get("headers") or {}),
            )
        )
        if limit and len(records) >= limit:
            break
    return records


class RESTAPIEvaluator:
    def __init__(self, dataset_path: str, record_limit: Optional[int] = None):
        self.dataset_path = dataset_path
        self.record_limit = record_limit

    def _thresholds(self) -> Dict[str, float]:
        return {
            "min_resource_orientation": 0.8,
            "min_pagination": 0.7,
            "min_versioning": 0.6,
            "min_error_codes": 0.7,
            "min_structural_redundancy": 0.6,
            "min_overall_score": 0.7,
        }

    async def _evaluate(self, records: List[RESTAPIEvalRecord]) -> Dict[str, Any]:
        metrics = RESTAPIMetrics()

        for record in records:
            metrics.add_endpoint(
                Endpoint(
                    method=record.method,
                    path=record.path,
                    version=record.version,
                    params=record.params,
                    response=record.response,
                    status_code=record.status_code,
                    headers=record.headers,
                )
            )

        detailed_metrics = metrics.compute_all_metrics()
        overall_score = metrics.compute_overall_score()

        quality = {
            "count": len(records),
            "resource_orientation": detailed_metrics["resource_orientation"],
            "pagination": detailed_metrics["pagination"],
            "versioning": detailed_metrics["versioning"],
            "error_codes": detailed_metrics["error_codes"],
            "structural_redundancy": detailed_metrics["structural_redundancy"],
            "overall_score": overall_score,
        }

        return quality

    def _apply_gates(self, report: Dict[str, Any]) -> Dict[str, Any]:
        thresholds = self._thresholds()
        quality = report["quality"]

        checks = [
            {
                "name": "resource_orientation",
                "value": quality["resource_orientation"]["score"],
                "threshold": thresholds["min_resource_orientation"],
                "status": "pass"
                if quality["resource_orientation"]["score"] >= thresholds["min_resource_orientation"]
                else "fail",
            },
            {
                "name": "pagination",
                "value": quality["pagination"]["score"],
                "threshold": thresholds["min_pagination"],
                "status": "pass"
                if quality["pagination"]["score"] >= thresholds["min_pagination"]
                else "fail",
            },
            {
                "name": "versioning",
                "value": quality["versioning"]["score"],
                "threshold": thresholds["min_versioning"],
                "status": "pass"
                if quality["versioning"]["score"] >= thresholds["min_versioning"]
                else "fail",
            },
            {
                "name": "error_codes",
                "value": quality["error_codes"]["score"],
                "threshold": thresholds["min_error_codes"],
                "status": "pass"
                if quality["error_codes"]["score"] >= thresholds["min_error_codes"]
                else "fail",
            },
            {
                "name": "structural_redundancy",
                "value": quality["structural_redundancy"]["score"],
                "threshold": thresholds["min_structural_redundancy"],
                "status": "pass"
                if quality["structural_redundancy"]["score"] >= thresholds["min_structural_redundancy"]
                else "fail",
            },
            {
                "name": "overall_score",
                "value": quality["overall_score"],
                "threshold": thresholds["min_overall_score"],
                "status": "pass"
                if quality["overall_score"] >= thresholds["min_overall_score"]
                else "fail",
            },
        ]

        all_passed = all(check["status"] == "pass" for check in checks)

        return {
            "thresholds": thresholds,
            "checks": checks,
            "all_passed": all_passed,
        }

    def _build_prometheus_payload(self, report: Dict[str, Any]) -> str:
        quality = report["quality"]
        gates = report["gates"]
        lines = [
            "# HELP rest_api_eval_resource_orientation Resource orientation score",
            "# TYPE rest_api_eval_resource_orientation gauge",
            f"rest_api_eval_resource_orientation {quality['resource_orientation']['score']}",
            "# HELP rest_api_eval_pagination Pagination score",
            "# TYPE rest_api_eval_pagination gauge",
            f"rest_api_eval_pagination {quality['pagination']['score']}",
            "# HELP rest_api_eval_versioning Versioning score",
            "# TYPE rest_api_eval_versioning gauge",
            f"rest_api_eval_versioning {quality['versioning']['score']}",
            "# HELP rest_api_eval_error_codes Error codes score",
            "# TYPE rest_api_eval_error_codes gauge",
            f"rest_api_eval_error_codes {quality['error_codes']['score']}",
            "# HELP rest_api_eval_structural_redundancy Structural redundancy score",
            "# TYPE rest_api_eval_structural_redundancy gauge",
            f"rest_api_eval_structural_redundancy {quality['structural_redundancy']['score']}",
            "# HELP rest_api_eval_overall_score Overall REST API quality score",
            "# TYPE rest_api_eval_overall_score gauge",
            f"rest_api_eval_overall_score {quality['overall_score']}",
            "# HELP rest_api_eval_gate_status Overall gate status (1=pass,0=fail)",
            "# TYPE rest_api_eval_gate_status gauge",
            f"rest_api_eval_gate_status {1 if gates['all_passed'] else 0}",
        ]
        for check in gates["checks"]:
            lines.extend([
                f"# HELP rest_api_eval_check_{{name}} Gate check status (1=pass,0=fail)",
                f"# TYPE rest_api_eval_check_{{name}} gauge",
                f'rest_api_eval_check{{name="{check["name"]}"}} {1 if check["status"] == "pass" else 0}',
            ])
        return "\n".join(lines) + "\n"

    def _build_summary_text(self, report: Dict[str, Any]) -> str:
        quality = report["quality"]
        lines = [
            f"timestamp={report['timestamp']}",
            f"dataset={report['dataset_path']}",
            f"endpoints={quality['count']}",
            f"status={report['status']}",
            "",
            f"resource_orientation={quality['resource_orientation']['score']:.4f}",
            f"pagination={quality['pagination']['score']:.4f}",
            f"versioning={quality['versioning']['score']:.4f}",
            f"error_codes={quality['error_codes']['score']:.4f}",
            f"structural_redundancy={quality['structural_redundancy']['score']:.4f}",
            f"overall_score={quality['overall_score']:.4f}",
            "",
            "gate_checks:",
        ]
        for check in report["gates"]["checks"]:
            lines.append(
                f"- {check['name']} status={check['status']} value={check['value']:.4f} threshold={check['threshold']}"
            )
        return "\n".join(lines) + "\n"

    async def run(self) -> Dict[str, Any]:
        records = load_rest_api_records(self.dataset_path, limit=self.record_limit)
        quality = await self._evaluate(records)

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dataset_path": self.dataset_path,
            "status": "unknown",
            "quality": quality,
        }
        report["gates"] = self._apply_gates(report)
        report["status"] = "pass" if report["gates"]["all_passed"] else "fail"
        report["prometheus_snapshot"] = self._build_prometheus_payload(report)
        report["summary_text"] = self._build_summary_text(report)
        return report

    async def run_and_export(self, output_dir: str) -> Dict[str, Any]:
        report = await self.run()
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        json_path = output_path / "rest_api_eval_report.json"
        prom_path = output_path / "rest_api_eval.prom"
        text_path = output_path / "rest_api_eval_summary.txt"

        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        prom_path.write_text(report["prometheus_snapshot"], encoding="utf-8")
        text_path.write_text(report["summary_text"], encoding="utf-8")

        report["artifacts"] = {
            "json": str(json_path),
            "prometheus": str(prom_path),
            "summary": str(text_path),
        }
        return report
