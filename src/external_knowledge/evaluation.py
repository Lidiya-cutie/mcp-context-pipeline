from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .base import BaseExternalKnowledgeProvider, KnowledgeChunk
from .router import ExternalKnowledgeRouter


EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_REGEX = re.compile(r"(?:\+7|7|8)[\s\-()]*\d[\d\s\-()]{8,}")


@dataclass
class EvalRecord:
    record_id: str
    query: str
    context: Dict[str, Any]
    gold_sources: List[Dict[str, Any]]


def _percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    idx = max(0, min(len(sorted_values) - 1, math.ceil(len(sorted_values) * p) - 1))
    return float(sorted_values[idx])


def _normalize_url(url: str) -> str:
    return url.rstrip("/").strip().lower()


def _chunk_has_provenance(chunk: Dict[str, Any]) -> bool:
    url = (chunk.get("url") or "").strip()
    if url:
        return True
    metadata = chunk.get("metadata") or {}
    if not isinstance(metadata, dict):
        return False
    has_repo = bool(metadata.get("repo"))
    has_path = bool(metadata.get("path"))
    has_commit = bool(metadata.get("commit"))
    return (has_repo and has_path) or (has_repo and has_commit)


def _gold_matches_chunk(gold: Dict[str, Any], chunk: Dict[str, Any]) -> bool:
    gold_url = (gold.get("url") or "").strip()
    chunk_url = (chunk.get("url") or "").strip()
    if gold_url and chunk_url and _normalize_url(gold_url) == _normalize_url(chunk_url):
        return True

    metadata = chunk.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    gold_repo = (gold.get("repo") or "").strip()
    gold_path = (gold.get("path") or "").strip()
    gold_commit = (gold.get("commit") or "").strip()

    if gold_repo:
        meta_repo = str(metadata.get("repo") or "").strip()
        if meta_repo and meta_repo == gold_repo:
            if gold_path:
                meta_path = str(metadata.get("path") or "").strip()
                if meta_path and meta_path == gold_path:
                    return True
            if gold_commit:
                meta_commit = str(metadata.get("commit") or "").strip()
                if meta_commit and meta_commit == gold_commit:
                    return True
            if chunk_url and gold_repo in chunk_url:
                if not gold_path or gold_path in chunk_url:
                    return True

    gold_title = (gold.get("title") or "").strip().lower()
    chunk_title = (chunk.get("title") or "").strip().lower()
    if gold_title and chunk_title and gold_title in chunk_title:
        return True

    return False


def load_eval_records(path: str, limit: Optional[int] = None) -> List[EvalRecord]:
    rows = Path(path).read_text(encoding="utf-8").splitlines()
    records: List[EvalRecord] = []
    for row in rows:
        data = json.loads(row)
        records.append(
            EvalRecord(
                record_id=str(data.get("id")),
                query=str(data.get("query", "")).strip(),
                context=dict(data.get("context") or {}),
                gold_sources=list(data.get("gold_sources") or []),
            )
        )
        if limit and len(records) >= limit:
            break
    return records


class ReplayGoldProvider(BaseExternalKnowledgeProvider):
    def __init__(
        self,
        records: Sequence[EvalRecord],
        name: str = "offline_gold",
        mode: str = "normal",
        timeout_ms: int = 20,
    ):
        super().__init__(name)
        self.mode = mode
        self.timeout_ms = timeout_ms
        self._index = {record.query: record.gold_sources for record in records}

    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5,
    ) -> List[KnowledgeChunk]:
        if self.mode == "empty":
            return []
        if self.mode == "timeout":
            await asyncio.sleep(self.timeout_ms / 1000.0)
            raise TimeoutError("simulated provider timeout")
        if self.mode == "error":
            raise RuntimeError("simulated provider error")

        gold_sources = self._index.get(query, [])
        chunks: List[KnowledgeChunk] = []
        for i, gold in enumerate(gold_sources[: max(1, min(limit, 8))], 1):
            metadata = {}
            for key in ("repo", "path", "commit", "library_id"):
                if gold.get(key):
                    metadata[key] = gold.get(key)
            chunks.append(
                KnowledgeChunk(
                    title=gold.get("title") or f"Gold source {i}",
                    content=f"Offline gold evidence for query: {query}",
                    source=self.name,
                    score=max(0.1, 1.0 - (i * 0.05)),
                    url=gold.get("url"),
                    metadata=metadata or {"source_type": gold.get("source_type", "unknown")},
                )
            )
        return chunks


class FallbackProvider(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("local_index")

    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5,
    ) -> List[KnowledgeChunk]:
        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]
        return [
            KnowledgeChunk(
                title="Fallback local chunk",
                content=f"Fallback answer for: {query}",
                source=self.name,
                score=0.61,
                url=f"https://local.example/offline/{digest}",
                metadata={"repo": "local/offline", "path": f"chunks/{digest}.txt"},
            )
        ][:limit]


class CapturingExternalProvider(BaseExternalKnowledgeProvider):
    def __init__(self, name: str = "tavily"):
        super().__init__(name)
        self.received_queries: List[str] = []

    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5,
    ) -> List[KnowledgeChunk]:
        self.received_queries.append(query)
        return [
            KnowledgeChunk(
                title="Captured query result",
                content="security validation",
                source=self.name,
                score=0.5,
                url="https://example.com/security/capture",
                metadata={"provider": self.name},
            )
        ][:limit]


class OfflineExternalKnowledgeEvaluator:
    def __init__(
        self,
        dataset_path: str,
        top_k: int = 5,
        record_limit: Optional[int] = None,
        cache_warm_repeat: int = 1,
    ):
        self.dataset_path = dataset_path
        self.top_k = top_k
        self.record_limit = record_limit
        self.cache_warm_repeat = cache_warm_repeat

    def _thresholds(self) -> Dict[str, float]:
        return {
            "min_recall_at_k": float(os.getenv("EVAL_MIN_RECALL_AT_K", "0.60")),
            "min_mrr": float(os.getenv("EVAL_MIN_MRR", "0.45")),
            "min_source_coverage": float(os.getenv("EVAL_MIN_SOURCE_COVERAGE", "0.95")),
            "max_not_found_rate": float(os.getenv("EVAL_MAX_NOT_FOUND_RATE", "0.20")),
            "max_p95_latency_ms": float(os.getenv("EVAL_MAX_P95_MS", "8000")),
            "min_cache_hit_rate": float(os.getenv("EVAL_MIN_CACHE_HIT_RATE", "0.20")),
            "min_provenance_coverage": float(os.getenv("EVAL_MIN_PROVENANCE_COVERAGE", "0.95")),
            "min_fallback_success_rate": float(os.getenv("EVAL_MIN_FALLBACK_SUCCESS_RATE", "0.95")),
        }

    async def _evaluate_quality(
        self,
        router: ExternalKnowledgeRouter,
        records: Sequence[EvalRecord],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        total = len(records)
        if total == 0:
            return {
                "count": 0,
                "recall_at_k": 0.0,
                "mrr": 0.0,
                "source_coverage": 0.0,
                "provenance_coverage": 0.0,
                "not_found_rate": 1.0,
                "latency_ms_p50": 0.0,
                "latency_ms_p95": 0.0,
                "latency_ms_avg": 0.0,
                "cache_hit_rate": 0.0,
            }, []

        recall_hits = 0
        mrr_sum = 0.0
        responses_with_sources = 0
        not_found = 0
        chunks_total = 0
        chunks_with_provenance = 0
        latencies: List[float] = []
        per_query: List[Dict[str, Any]] = []

        for record in records:
            started = time.perf_counter()
            result = await router.search(query=record.query, context=record.context, limit=self.top_k)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            latencies.append(elapsed_ms)

            chunks = list(result.get("chunks", []))
            count = int(result.get("count", len(chunks)))
            if count == 0:
                not_found += 1
            else:
                if any(_chunk_has_provenance(chunk) for chunk in chunks):
                    responses_with_sources += 1

            chunks_total += len(chunks)
            chunks_with_provenance += sum(1 for chunk in chunks if _chunk_has_provenance(chunk))

            first_relevant_rank = 0
            for idx, chunk in enumerate(chunks, 1):
                if any(_gold_matches_chunk(gold, chunk) for gold in record.gold_sources):
                    first_relevant_rank = idx
                    break

            if first_relevant_rank > 0:
                recall_hits += 1
                mrr_sum += 1.0 / first_relevant_rank

            per_query.append(
                {
                    "id": record.record_id,
                    "cached": bool(result.get("cached", False)),
                    "count": count,
                    "first_relevant_rank": first_relevant_rank,
                    "providers_used": result.get("providers_used", []),
                    "provider_errors": result.get("provider_errors", {}),
                    "latency_ms": elapsed_ms,
                }
            )

        for _ in range(max(0, self.cache_warm_repeat)):
            for record in records:
                await router.search(query=record.query, context=record.context, limit=self.top_k)

        router_metrics = router.get_metrics()
        quality = {
            "count": total,
            "recall_at_k": recall_hits / total,
            "mrr": mrr_sum / total,
            "source_coverage": responses_with_sources / total,
            "provenance_coverage": (
                (chunks_with_provenance / chunks_total) if chunks_total > 0 else 0.0
            ),
            "not_found_rate": not_found / total,
            "latency_ms_p50": _percentile(latencies, 0.50),
            "latency_ms_p95": _percentile(latencies, 0.95),
            "latency_ms_avg": (sum(latencies) / len(latencies)) if latencies else 0.0,
            "cache_hit_rate": float(router_metrics.get("hit_rate", 0.0)),
            "router_metrics": router_metrics,
        }
        return quality, per_query

    async def _run_degradation_scenario(
        self,
        records: Sequence[EvalRecord],
        mode: str,
    ) -> Dict[str, Any]:
        providers: List[BaseExternalKnowledgeProvider] = [
            ReplayGoldProvider(records=records, mode=mode),
            FallbackProvider(),
        ]
        router = ExternalKnowledgeRouter(providers=providers, cache_ttl_seconds=60)

        total = len(records)
        non_empty = 0
        exceptions = 0
        for record in records:
            try:
                result = await router.search(query=record.query, context=record.context, limit=self.top_k)
                if int(result.get("count", 0)) > 0:
                    non_empty += 1
            except Exception:
                exceptions += 1

        success_rate = (total - exceptions) / total if total else 0.0
        fallback_success_rate = non_empty / total if total else 0.0
        return {
            "scenario": mode,
            "total": total,
            "exceptions": exceptions,
            "success_rate": success_rate,
            "fallback_success_rate": fallback_success_rate,
            "provider_errors": int(router.get_metrics().get("provider_errors", 0)),
        }

    async def _evaluate_degradation(self, records: Sequence[EvalRecord]) -> Dict[str, Any]:
        sample_size = int(os.getenv("EVAL_DEGRADATION_SAMPLE_SIZE", "50"))
        subset = list(records[: max(1, min(sample_size, len(records)))])
        scenarios = []
        for mode in ("empty", "timeout", "error"):
            scenarios.append(await self._run_degradation_scenario(subset, mode=mode))
        return {
            "sample_size": len(subset),
            "scenarios": scenarios,
        }

    async def _evaluate_security(self, records: Sequence[EvalRecord]) -> Dict[str, Any]:
        capture_provider = CapturingExternalProvider(name="tavily")
        router = ExternalKnowledgeRouter(providers=[capture_provider], cache_ttl_seconds=30)
        pii_query = "Контакт клиента ivan.petrov@example.com, телефон +7 (999) 123-45-67"
        await router.search(query=pii_query, context={"domain": "security"}, limit=3)

        captured = capture_provider.received_queries[0] if capture_provider.received_queries else ""
        pii_leak = bool(EMAIL_REGEX.search(captured) or PHONE_REGEX.search(captured))

        # Provenance coverage is separately measured in quality pass and checked by gate.
        return {
            "pii_masking": {
                "status": "ok" if not pii_leak else "failing",
                "captured_query": captured,
            }
        }

    def _apply_gates(self, report: Dict[str, Any]) -> Dict[str, Any]:
        thresholds = self._thresholds()
        quality = report["quality"]
        degradation = report["degradation"]["scenarios"]
        pii_status = report["security"]["pii_masking"]["status"]

        scenario_fallback_min = min(
            (float(item["fallback_success_rate"]) for item in degradation),
            default=0.0,
        )
        scenario_success_min = min(
            (float(item["success_rate"]) for item in degradation),
            default=0.0,
        )

        checks = [
            {
                "name": "recall_at_k",
                "value": quality["recall_at_k"],
                "threshold": thresholds["min_recall_at_k"],
                "status": "pass" if quality["recall_at_k"] >= thresholds["min_recall_at_k"] else "fail",
            },
            {
                "name": "mrr",
                "value": quality["mrr"],
                "threshold": thresholds["min_mrr"],
                "status": "pass" if quality["mrr"] >= thresholds["min_mrr"] else "fail",
            },
            {
                "name": "source_coverage",
                "value": quality["source_coverage"],
                "threshold": thresholds["min_source_coverage"],
                "status": "pass"
                if quality["source_coverage"] >= thresholds["min_source_coverage"]
                else "fail",
            },
            {
                "name": "provenance_coverage",
                "value": quality["provenance_coverage"],
                "threshold": thresholds["min_provenance_coverage"],
                "status": "pass"
                if quality["provenance_coverage"] >= thresholds["min_provenance_coverage"]
                else "fail",
            },
            {
                "name": "not_found_rate",
                "value": quality["not_found_rate"],
                "threshold": thresholds["max_not_found_rate"],
                "status": "pass"
                if quality["not_found_rate"] <= thresholds["max_not_found_rate"]
                else "fail",
            },
            {
                "name": "latency_ms_p95",
                "value": quality["latency_ms_p95"],
                "threshold": thresholds["max_p95_latency_ms"],
                "status": "pass"
                if quality["latency_ms_p95"] <= thresholds["max_p95_latency_ms"]
                else "fail",
            },
            {
                "name": "cache_hit_rate",
                "value": quality["cache_hit_rate"],
                "threshold": thresholds["min_cache_hit_rate"],
                "status": "pass"
                if quality["cache_hit_rate"] >= thresholds["min_cache_hit_rate"]
                else "fail",
            },
            {
                "name": "degradation_fallback_success_min",
                "value": scenario_fallback_min,
                "threshold": thresholds["min_fallback_success_rate"],
                "status": "pass"
                if scenario_fallback_min >= thresholds["min_fallback_success_rate"]
                else "fail",
            },
            {
                "name": "degradation_success_min",
                "value": scenario_success_min,
                "threshold": 1.0,
                "status": "pass" if scenario_success_min >= 1.0 else "fail",
            },
            {
                "name": "pii_masking",
                "value": pii_status,
                "threshold": "ok",
                "status": "pass" if pii_status == "ok" else "fail",
            },
        ]
        all_passed = all(check["status"] == "pass" for check in checks)
        return {
            "thresholds": thresholds,
            "checks": checks,
            "all_passed": all_passed,
        }

    @staticmethod
    def _build_prometheus_payload(report: Dict[str, Any], router_prometheus: str) -> str:
        quality = report["quality"]
        gates = report["gates"]
        lines = [router_prometheus.strip(), ""]
        lines.extend(
            [
                "# HELP external_knowledge_eval_recall_at_k Offline eval recall@k",
                "# TYPE external_knowledge_eval_recall_at_k gauge",
                f"external_knowledge_eval_recall_at_k {quality['recall_at_k']}",
                "# HELP external_knowledge_eval_mrr Offline eval MRR",
                "# TYPE external_knowledge_eval_mrr gauge",
                f"external_knowledge_eval_mrr {quality['mrr']}",
                "# HELP external_knowledge_eval_source_coverage Answers with sources ratio",
                "# TYPE external_knowledge_eval_source_coverage gauge",
                f"external_knowledge_eval_source_coverage {quality['source_coverage']}",
                "# HELP external_knowledge_eval_not_found_rate Not found answers ratio",
                "# TYPE external_knowledge_eval_not_found_rate gauge",
                f"external_knowledge_eval_not_found_rate {quality['not_found_rate']}",
                "# HELP external_knowledge_eval_provenance_coverage Chunks with provenance ratio",
                "# TYPE external_knowledge_eval_provenance_coverage gauge",
                f"external_knowledge_eval_provenance_coverage {quality['provenance_coverage']}",
                "# HELP external_knowledge_eval_gate_status Overall gate status (1=pass,0=fail)",
                "# TYPE external_knowledge_eval_gate_status gauge",
                f"external_knowledge_eval_gate_status {1 if gates['all_passed'] else 0}",
            ]
        )
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _build_summary_text(report: Dict[str, Any]) -> str:
        quality = report["quality"]
        lines = [
            f"timestamp={report['timestamp']}",
            f"dataset={report['dataset_path']}",
            f"records={quality['count']}",
            f"status={report['status']}",
            "",
            f"recall_at_k={quality['recall_at_k']:.4f}",
            f"mrr={quality['mrr']:.4f}",
            f"source_coverage={quality['source_coverage']:.4f}",
            f"provenance_coverage={quality['provenance_coverage']:.4f}",
            f"not_found_rate={quality['not_found_rate']:.4f}",
            f"latency_ms_p50={quality['latency_ms_p50']:.2f}",
            f"latency_ms_p95={quality['latency_ms_p95']:.2f}",
            f"cache_hit_rate={quality['cache_hit_rate']:.4f}",
            "",
            "gate_checks:",
        ]
        for check in report["gates"]["checks"]:
            lines.append(
                f"- {check['name']} status={check['status']} value={check['value']} threshold={check['threshold']}"
            )
        return "\n".join(lines) + "\n"

    async def run(self) -> Dict[str, Any]:
        records = load_eval_records(self.dataset_path, limit=self.record_limit)
        providers: List[BaseExternalKnowledgeProvider] = [
            ReplayGoldProvider(records=records, mode="normal"),
            FallbackProvider(),
        ]
        router = ExternalKnowledgeRouter(providers=providers, cache_ttl_seconds=3600)
        quality, per_query = await self._evaluate_quality(router=router, records=records)
        degradation = await self._evaluate_degradation(records=records)
        security = await self._evaluate_security(records=records)

        router_metrics_export = await router.export_metrics_json(history_limit=50)
        router_prometheus = router.export_metrics_prometheus()
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dataset_path": self.dataset_path,
            "status": "unknown",
            "quality": quality,
            "degradation": degradation,
            "security": security,
            "router_export": router_metrics_export,
            "sample_results": per_query[: min(25, len(per_query))],
        }
        report["gates"] = self._apply_gates(report)
        report["status"] = "pass" if report["gates"]["all_passed"] else "fail"
        report["prometheus_snapshot"] = self._build_prometheus_payload(report, router_prometheus)
        report["summary_text"] = self._build_summary_text(report)
        return report

    async def run_and_export(self, output_dir: str) -> Dict[str, Any]:
        report = await self.run()
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        json_path = output_path / "external_knowledge_eval_report.json"
        prom_path = output_path / "external_knowledge_eval.prom"
        text_path = output_path / "external_knowledge_eval_summary.txt"

        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        prom_path.write_text(report["prometheus_snapshot"], encoding="utf-8")
        text_path.write_text(report["summary_text"], encoding="utf-8")
        report["artifacts"] = {
            "json": str(json_path),
            "prometheus": str(prom_path),
            "summary": str(text_path),
        }
        return report
