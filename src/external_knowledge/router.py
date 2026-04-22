from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import time
from typing import Any, Dict, List, Optional, Sequence

from .base import BaseExternalKnowledgeProvider, KnowledgeChunk


FALLBACK_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
FALLBACK_PHONE_RE = re.compile(r"(?:\+7|7|8)[\s\-()]*\d[\d\s\-()]{8,}")


class ExternalKnowledgeRouter:
    def __init__(
        self,
        providers: Sequence[BaseExternalKnowledgeProvider],
        cache_ttl_seconds: int = 3600
    ):
        self.providers = list(providers)
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.source_weights = self._load_source_weights()
        self._metrics: Dict[str, Any] = {
            "requests_total": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "provider_calls": 0,
            "provider_errors": 0,
            "latencies_ms": [],
            "source_counts": {},
        }
        self._provider_health: Dict[str, Dict[str, Any]] = {}
        self._redis_client = None
        self._redis_enabled = os.getenv("EXTERNAL_KNOWLEDGE_USE_REDIS", "true").lower() == "true"
        self._redis_prefix = os.getenv("EXTERNAL_KNOWLEDGE_REDIS_PREFIX", "extk")
        self._redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        self._metrics_history_maxlen = int(os.getenv("EXTERNAL_METRICS_HISTORY_MAXLEN", "5000"))
        self._metrics_history_ttl_seconds = int(os.getenv("EXTERNAL_METRICS_HISTORY_TTL_SECONDS", "604800"))
        self._metrics_history_local: List[Dict[str, Any]] = []
        self._alert_hit_rate_min = float(os.getenv("EXTERNAL_ALERT_HIT_RATE_MIN", "0.30"))
        self._alert_p95_max_ms = float(os.getenv("EXTERNAL_ALERT_P95_MAX_MS", "5000"))
        self._alert_min_requests = int(os.getenv("EXTERNAL_ALERT_MIN_REQUESTS", "20"))
        self._provider_health_ttl_seconds = int(os.getenv("EXTERNAL_PROVIDER_HEALTH_TTL_SECONDS", "604800"))
        self._mask_pii_queries = os.getenv("EXTERNAL_MASK_PII_QUERIES", "true").lower() == "true"
        self._pii_guard = None
        self._pii_guard_ready = None
        self._sensitive_external_sources = {
            "context7",
            "github",
            "tavily",
            "exa",
            "firecrawl",
            "shiva",
            "docfusion",
        }
        if self._redis_enabled:
            self._init_redis()

    def _cache_key(self, query: str, context: Optional[Dict[str, Any]], limit: int) -> str:
        payload = {
            "query": query,
            "context": context or {},
            "limit": limit,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _init_redis(self) -> None:
        try:
            import redis
            self._redis_client = redis.Redis.from_url(self._redis_url, decode_responses=True)
        except Exception:
            self._redis_client = None
            self._redis_enabled = False

    def _redis_query_key(self, key: str) -> str:
        return f"{self._redis_prefix}:query:{key}"

    def _redis_chunk_key(self, chunk_hash: str) -> str:
        return f"{self._redis_prefix}:chunk:{chunk_hash}"

    def _redis_provider_health_key(self, provider_name: str) -> str:
        return f"{self._redis_prefix}:provider:health:{provider_name}"

    def _ensure_pii_guard(self) -> bool:
        if self._pii_guard_ready is not None:
            return self._pii_guard_ready
        if not self._mask_pii_queries:
            self._pii_guard_ready = False
            return False
        try:
            from pii_guard import get_pii_guard  # type: ignore
            self._pii_guard = get_pii_guard(language="ru")
            self._pii_guard_ready = True
        except Exception:
            self._pii_guard_ready = False
        return bool(self._pii_guard_ready)

    def _mask_query_for_provider(self, provider_name: str, query: str) -> str:
        if provider_name not in self._sensitive_external_sources:
            return query
        if not self._ensure_pii_guard() or self._pii_guard is None:
            masked = FALLBACK_EMAIL_RE.sub("[MASKED_EMAIL]", query)
            masked = FALLBACK_PHONE_RE.sub("[MASKED_PHONE]", masked)
            return masked
        try:
            masked = self._pii_guard.mask(query, language="ru")
            return masked if masked else query
        except Exception:
            masked = FALLBACK_EMAIL_RE.sub("[MASKED_EMAIL]", query)
            masked = FALLBACK_PHONE_RE.sub("[MASKED_PHONE]", masked)
            return masked

    async def _get_cache(self, key: str) -> Optional[Dict[str, Any]]:
        if self._redis_enabled and self._redis_client is not None:
            redis_key = self._redis_query_key(key)
            try:
                raw = await asyncio.to_thread(self._redis_client.get, redis_key)
                if raw:
                    payload = json.loads(raw)
                    payload["cached"] = True
                    return payload
            except Exception:
                self._redis_enabled = False

        item = self._cache.get(key)
        if not item:
            return None
        if time.time() - item["created_at"] > self.cache_ttl_seconds:
            self._cache.pop(key, None)
            return None
        cached_value = dict(item["value"])
        cached_value["cached"] = True
        return cached_value

    async def _set_cache(self, key: str, value: Dict[str, Any]) -> None:
        if self._redis_enabled and self._redis_client is not None:
            redis_key = self._redis_query_key(key)
            try:
                await asyncio.to_thread(
                    self._redis_client.setex,
                    redis_key,
                    self.cache_ttl_seconds,
                    json.dumps(value, ensure_ascii=False),
                )
                chunks = value.get("chunks", [])
                for chunk in chunks:
                    chunk_hash = hashlib.sha256(
                        json.dumps(
                            {
                                "title": chunk.get("title"),
                                "content": chunk.get("content"),
                                "source": chunk.get("source"),
                                "url": chunk.get("url"),
                            },
                            sort_keys=True,
                            ensure_ascii=False,
                        ).encode("utf-8")
                    ).hexdigest()
                    await asyncio.to_thread(
                        self._redis_client.setex,
                        self._redis_chunk_key(chunk_hash),
                        self.cache_ttl_seconds,
                        json.dumps(chunk, ensure_ascii=False),
                    )
            except Exception:
                self._redis_enabled = False

        self._cache[key] = {"created_at": time.time(), "value": value}

    @staticmethod
    def _load_source_weights() -> Dict[str, float]:
        default_weights = {
            "github": 1.00,
            "context7": 0.98,
            "local_index": 0.95,
            "knowledge_bridge": 0.90,
            "shiva": 0.93,
            "docfusion": 0.94,
            "tavily": 0.78,
            "exa": 0.76,
            "firecrawl": 0.74,
        }
        raw = os.getenv("EXTERNAL_KNOWLEDGE_SOURCE_WEIGHTS", "").strip()
        if not raw:
            return default_weights
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    try:
                        default_weights[str(key)] = float(value)
                    except (TypeError, ValueError):
                        continue
        except json.JSONDecodeError:
            pass
        return default_weights

    @staticmethod
    def _dedup(chunks: List[KnowledgeChunk]) -> List[KnowledgeChunk]:
        seen = set()
        result = []
        for chunk in chunks:
            fingerprint = (chunk.source, chunk.url or "", chunk.title.strip(), chunk.content.strip()[:400])
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            result.append(chunk)
        return result

    @staticmethod
    def _keyword_match_ratio(query: str, text: str) -> float:
        tokens = [token.strip().lower() for token in query.split() if token.strip()]
        if not tokens:
            return 0.0
        hay = text.lower()
        matched = sum(1 for token in tokens if token in hay)
        return matched / len(tokens)

    @staticmethod
    def _normalize_scores_by_source(chunks: List[KnowledgeChunk]) -> Dict[int, float]:
        by_source: Dict[str, List[float]] = {}
        for chunk in chunks:
            by_source.setdefault(chunk.source, []).append(float(chunk.score))

        source_ranges: Dict[str, Dict[str, float]] = {}
        for source, values in by_source.items():
            source_ranges[source] = {"min": min(values), "max": max(values)}

        normalized: Dict[int, float] = {}
        for idx, chunk in enumerate(chunks):
            bounds = source_ranges[chunk.source]
            min_score = bounds["min"]
            max_score = bounds["max"]
            if max_score == min_score:
                normalized[idx] = 1.0 if max_score > 0 else 0.0
            else:
                normalized[idx] = (float(chunk.score) - min_score) / (max_score - min_score)
        return normalized

    def _rerank(self, query: str, chunks: List[KnowledgeChunk]) -> List[KnowledgeChunk]:
        if not chunks:
            return []

        normalized = self._normalize_scores_by_source(chunks)
        for idx, chunk in enumerate(chunks):
            source_weight = self.source_weights.get(chunk.source, 0.60)
            keyword_ratio = self._keyword_match_ratio(query, f"{chunk.title}\n{chunk.content}")
            rerank_score = (
                normalized[idx] * 0.55
                + source_weight * 0.35
                + keyword_ratio * 0.10
            )
            if chunk.metadata is None:
                chunk.metadata = {}
            chunk.metadata["base_score"] = float(chunk.score)
            chunk.metadata["normalized_score"] = normalized[idx]
            chunk.metadata["source_weight"] = source_weight
            chunk.metadata["keyword_ratio"] = keyword_ratio
            chunk.metadata["rerank_score"] = rerank_score
            chunk.score = rerank_score

        chunks.sort(key=lambda c: c.score, reverse=True)
        return chunks

    @staticmethod
    def _is_knowledge_bridge_fallback(chunk: KnowledgeChunk) -> bool:
        if chunk.source != "knowledge_bridge":
            return False
        text = (chunk.content or "").lower()
        return "no specific standard found" in text

    @staticmethod
    def _is_docfusion_spa_shell(chunk: KnowledgeChunk) -> bool:
        if chunk.source != "docfusion":
            return False
        text = (chunk.content or "").lower()
        return "<!doctype html" in text and "<div id=\"app\"" in text

    def _is_noise_chunk(self, chunk: KnowledgeChunk) -> bool:
        return self._is_knowledge_bridge_fallback(chunk) or self._is_docfusion_spa_shell(chunk)

    @staticmethod
    def _is_error_chunk(chunk: KnowledgeChunk) -> bool:
        text = (chunk.content or "").strip().lower()
        return text.startswith("error:")

    def _filter_noise_chunks(self, chunks: List[KnowledgeChunk]) -> List[KnowledgeChunk]:
        filtered = [chunk for chunk in chunks if not self._is_noise_chunk(chunk)]
        return filtered

    @staticmethod
    def _is_project_query_with_project_id(context: Optional[Dict[str, Any]]) -> bool:
        ctx = context or {}
        domain = str(ctx.get("domain", "")).strip().lower()
        project_id = ctx.get("project_id") or ctx.get("shiva_project_id")
        return domain == "project" and project_id not in (None, "", "null")

    def _prioritize_project_shiva(
        self,
        chunks: List[KnowledgeChunk],
        context: Optional[Dict[str, Any]],
        limit: int,
    ) -> List[KnowledgeChunk]:
        if not self._is_project_query_with_project_id(context):
            return chunks
        shiva_chunks = [chunk for chunk in chunks if chunk.source == "shiva"]
        if shiva_chunks:
            shiva_chunks = self._rerank(str((context or {}).get("query", "")), shiva_chunks)
            return shiva_chunks[:limit]
        return chunks[:limit]

    def _record_latency(self, latency_ms: float) -> None:
        latencies = self._metrics["latencies_ms"]
        latencies.append(latency_ms)
        if len(latencies) > 5000:
            del latencies[: len(latencies) - 5000]

    def _update_source_counts(self, chunks: List[KnowledgeChunk]) -> None:
        source_counts = self._metrics["source_counts"]
        for chunk in chunks:
            source_counts[chunk.source] = int(source_counts.get(chunk.source, 0)) + 1

    @staticmethod
    def _percentile(values: List[float], p: float) -> float:
        if not values:
            return 0.0
        sorted_values = sorted(values)
        idx = max(0, min(len(sorted_values) - 1, math.ceil(len(sorted_values) * p) - 1))
        return float(sorted_values[idx])

    def get_metrics(self) -> Dict[str, Any]:
        requests_total = int(self._metrics["requests_total"])
        cache_hits = int(self._metrics["cache_hits"])
        cache_misses = int(self._metrics["cache_misses"])
        provider_calls = int(self._metrics["provider_calls"])
        provider_errors = int(self._metrics["provider_errors"])
        latencies = list(self._metrics["latencies_ms"])
        source_counts = dict(self._metrics["source_counts"])

        total_cache_events = cache_hits + cache_misses
        hit_rate = (cache_hits / total_cache_events) if total_cache_events > 0 else 0.0

        total_sources = sum(source_counts.values())
        source_distribution = {}
        if total_sources > 0:
            for source, count in source_counts.items():
                source_distribution[source] = count / total_sources

        return {
            "requests_total": requests_total,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "hit_rate": hit_rate,
            "provider_calls": provider_calls,
            "provider_errors": provider_errors,
            "latency_ms_p50": self._percentile(latencies, 0.50),
            "latency_ms_p95": self._percentile(latencies, 0.95),
            "latency_ms_avg": (sum(latencies) / len(latencies)) if latencies else 0.0,
            "source_distribution": source_distribution,
            "redis_cache_enabled": bool(self._redis_enabled and self._redis_client is not None),
        }

    async def _update_provider_health(self, provider_name: str, ok: bool, error: Optional[str] = None) -> None:
        now_ts = time.time()
        current = self._provider_health.get(provider_name, {
            "provider": provider_name,
            "status": "unknown",
            "last_ok": None,
            "last_error": None,
            "ok_count": 0,
            "error_count": 0,
            "updated_at": now_ts,
        })

        if ok:
            current["status"] = "ok"
            current["last_ok"] = now_ts
            current["ok_count"] = int(current.get("ok_count", 0)) + 1
        else:
            current["status"] = "error"
            current["last_error"] = error or "unknown error"
            current["error_count"] = int(current.get("error_count", 0)) + 1
        current["updated_at"] = now_ts
        self._provider_health[provider_name] = current

        if self._redis_enabled and self._redis_client is not None:
            try:
                await asyncio.to_thread(
                    self._redis_client.setex,
                    self._redis_provider_health_key(provider_name),
                    self._provider_health_ttl_seconds,
                    json.dumps(current, ensure_ascii=False),
                )
            except Exception:
                self._redis_enabled = False

    async def get_provider_health(self) -> Dict[str, Dict[str, Any]]:
        health = dict(self._provider_health)
        if self._redis_enabled and self._redis_client is not None:
            for provider in self.providers:
                key = self._redis_provider_health_key(provider.name)
                try:
                    raw = await asyncio.to_thread(self._redis_client.get, key)
                    if raw:
                        parsed = json.loads(raw)
                        health[provider.name] = parsed
                except Exception:
                    self._redis_enabled = False
                    break
        return health

    async def _append_metrics_history(self, entry: Dict[str, Any]) -> None:
        self._metrics_history_local.append(entry)
        if len(self._metrics_history_local) > self._metrics_history_maxlen:
            del self._metrics_history_local[: len(self._metrics_history_local) - self._metrics_history_maxlen]

        if self._redis_enabled and self._redis_client is not None:
            history_key = f"{self._redis_prefix}:metrics:history"
            try:
                await asyncio.to_thread(self._redis_client.lpush, history_key, json.dumps(entry, ensure_ascii=False))
                await asyncio.to_thread(self._redis_client.ltrim, history_key, 0, self._metrics_history_maxlen - 1)
                await asyncio.to_thread(self._redis_client.expire, history_key, self._metrics_history_ttl_seconds)
            except Exception:
                self._redis_enabled = False

    async def get_metrics_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        normalized_limit = max(1, min(limit, self._metrics_history_maxlen))
        if self._redis_enabled and self._redis_client is not None:
            history_key = f"{self._redis_prefix}:metrics:history"
            try:
                raw_items = await asyncio.to_thread(self._redis_client.lrange, history_key, 0, normalized_limit - 1)
                history = []
                for item in raw_items:
                    try:
                        history.append(json.loads(item))
                    except json.JSONDecodeError:
                        continue
                return history
            except Exception:
                self._redis_enabled = False

        return list(reversed(self._metrics_history_local[-normalized_limit:]))

    async def export_metrics_json(self, history_limit: int = 100) -> Dict[str, Any]:
        current = self.get_metrics()
        history = await self.get_metrics_history(limit=history_limit)
        alerts = self.get_alerts(current_metrics=current)
        provider_health = await self.get_provider_health()
        return {
            "current": current,
            "history": history,
            "alerts": alerts,
            "provider_health": provider_health,
            "history_limit": history_limit,
        }

    def export_metrics_prometheus(self) -> str:
        metrics = self.get_metrics()
        alerts = self.get_alerts(current_metrics=metrics)

        lines = [
            "# HELP external_knowledge_requests_total Total external knowledge requests",
            "# TYPE external_knowledge_requests_total counter",
            f"external_knowledge_requests_total {metrics['requests_total']}",
            "# HELP external_knowledge_cache_hits_total Total cache hits",
            "# TYPE external_knowledge_cache_hits_total counter",
            f"external_knowledge_cache_hits_total {metrics['cache_hits']}",
            "# HELP external_knowledge_cache_misses_total Total cache misses",
            "# TYPE external_knowledge_cache_misses_total counter",
            f"external_knowledge_cache_misses_total {metrics['cache_misses']}",
            "# HELP external_knowledge_hit_rate Cache hit rate",
            "# TYPE external_knowledge_hit_rate gauge",
            f"external_knowledge_hit_rate {metrics['hit_rate']}",
            "# HELP external_knowledge_latency_ms_p95 P95 latency in milliseconds",
            "# TYPE external_knowledge_latency_ms_p95 gauge",
            f"external_knowledge_latency_ms_p95 {metrics['latency_ms_p95']}",
            "# HELP external_knowledge_latency_ms_p50 P50 latency in milliseconds",
            "# TYPE external_knowledge_latency_ms_p50 gauge",
            f"external_knowledge_latency_ms_p50 {metrics['latency_ms_p50']}",
            "# HELP external_knowledge_provider_errors_total Total provider errors",
            "# TYPE external_knowledge_provider_errors_total counter",
            f"external_knowledge_provider_errors_total {metrics['provider_errors']}",
        ]

        for source, share in metrics["source_distribution"].items():
            lines.extend([
                "# HELP external_knowledge_source_share Share of chunks by source",
                "# TYPE external_knowledge_source_share gauge",
                f'external_knowledge_source_share{{source="{source}"}} {share}',
            ])

        for alert in alerts:
            status = 1 if alert["status"] == "firing" else 0
            lines.extend([
                "# HELP external_knowledge_alert_status Alert status (1=firing,0=ok)",
                "# TYPE external_knowledge_alert_status gauge",
                f'external_knowledge_alert_status{{name="{alert["name"]}"}} {status}',
            ])

        return "\n".join(lines) + "\n"

    def get_alerts(self, current_metrics: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        metrics = current_metrics or self.get_metrics()
        requests_total = int(metrics.get("requests_total", 0))
        if requests_total < self._alert_min_requests:
            return [
                {
                    "name": "insufficient_data",
                    "status": "ok",
                    "message": (
                        f"Недостаточно данных для алертов: requests_total={requests_total}, "
                        f"min_required={self._alert_min_requests}"
                    ),
                }
            ]

        alerts = []
        hit_rate = float(metrics.get("hit_rate", 0.0))
        p95 = float(metrics.get("latency_ms_p95", 0.0))

        alerts.append(
            {
                "name": "hit_rate_degradation",
                "status": "firing" if hit_rate < self._alert_hit_rate_min else "ok",
                "value": hit_rate,
                "threshold": self._alert_hit_rate_min,
                "message": f"hit_rate={hit_rate:.4f}, threshold_min={self._alert_hit_rate_min:.4f}",
            }
        )
        alerts.append(
            {
                "name": "p95_latency_degradation",
                "status": "firing" if p95 > self._alert_p95_max_ms else "ok",
                "value": p95,
                "threshold": self._alert_p95_max_ms,
                "message": f"latency_ms_p95={p95:.2f}, threshold_max={self._alert_p95_max_ms:.2f}",
            }
        )
        return alerts

    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> Dict[str, Any]:
        started = time.perf_counter()
        self._metrics["requests_total"] += 1

        key = self._cache_key(query, context, limit)
        cached = await self._get_cache(key)
        if cached is not None:
            self._metrics["cache_hits"] += 1
            cached_chunks = cached.get("chunks", [])
            for chunk in cached_chunks:
                source = chunk.get("source")
                if source:
                    counts = self._metrics["source_counts"]
                    counts[source] = int(counts.get(source, 0)) + 1
            latency_ms = (time.perf_counter() - started) * 1000.0
            self._record_latency(latency_ms)
            await self._append_metrics_history(
                {
                    "timestamp": time.time(),
                    "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest()[:16],
                    "cached": True,
                    "result_count": int(cached.get("count", 0)),
                    "providers_used": cached.get("providers_used", []),
                    "provider_errors_count": len(cached.get("provider_errors", {})),
                    "latency_ms": latency_ms,
                    "metrics_snapshot": self.get_metrics(),
                }
            )
            return cached
        self._metrics["cache_misses"] += 1

        all_chunks: List[KnowledgeChunk] = []
        provider_errors: Dict[str, str] = {}
        providers_used: List[str] = []

        for provider in self.providers:
            self._metrics["provider_calls"] += 1
            try:
                provider_query = self._mask_query_for_provider(provider.name, query)
                chunks = await provider.search(query=provider_query, context=context, limit=limit)
                error_chunks = [chunk for chunk in chunks if self._is_error_chunk(chunk)]
                valid_chunks = [chunk for chunk in chunks if not self._is_error_chunk(chunk)]

                if error_chunks and not valid_chunks:
                    error_text = (error_chunks[0].content or "provider returned error chunk").strip()
                    self._metrics["provider_errors"] += 1
                    provider_errors[provider.name] = error_text[:500]
                    await self._update_provider_health(provider.name, ok=False, error=error_text[:500])
                    continue

                if valid_chunks:
                    providers_used.append(provider.name)
                    all_chunks.extend(valid_chunks)
                await self._update_provider_health(provider.name, ok=True)
            except Exception as exc:
                self._metrics["provider_errors"] += 1
                provider_errors[provider.name] = str(exc)
                await self._update_provider_health(provider.name, ok=False, error=str(exc))

        deduped = self._dedup(all_chunks)
        deduped = self._filter_noise_chunks(deduped)
        deduped = self._rerank(query, deduped)
        enriched_context = dict(context or {})
        enriched_context["query"] = query
        deduped = self._prioritize_project_shiva(deduped, enriched_context, limit=limit)
        deduped = deduped[:limit]
        self._update_source_counts(deduped)

        payload = {
            "query": query,
            "providers_used": providers_used,
            "provider_errors": provider_errors,
            "chunks": [chunk.to_dict() for chunk in deduped],
            "count": len(deduped),
            "cached": False,
        }
        await self._set_cache(key, payload)
        latency_ms = (time.perf_counter() - started) * 1000.0
        self._record_latency(latency_ms)
        await self._append_metrics_history(
            {
                "timestamp": time.time(),
                "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest()[:16],
                "cached": False,
                "result_count": len(deduped),
                "providers_used": providers_used,
                "provider_errors_count": len(provider_errors),
                "latency_ms": latency_ms,
                "metrics_snapshot": self.get_metrics(),
            }
        )
        return payload
