"""DS-743: Full benchmark pipeline — >=100 tasks with gold standard, RU/EN/PL comparison.

Pipeline:
1. Load eval_queries_v3.jsonl (300 queries: 150 RU + 150 EN)
2. Generate PL translations for a subset
3. Run each query through 3 language-specific instruction variants
4. Measure: keyword coverage (must_include), latency, answer quality
5. Output structured report

DS-744 extension: auto-search compressing instructions on the same dataset.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

_PROJECT_ROOT = Path(
    os.environ.get("MCP_CONTEXT_PIPELINE_ROOT", Path(__file__).resolve().parents[1])
)
_CTX_MODULE_DIR = _PROJECT_ROOT / "src" / "mcp_servers" / "context_manager"
if str(_CTX_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_CTX_MODULE_DIR))

load_dotenv(_PROJECT_ROOT / ".env", override=False)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic")
LLM_MODEL = os.environ.get("ANTHROPIC_MODEL", "glm-4.7")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MAX_TOKENS = 1024
LLM_TIMEOUT = 90.0
F1_THRESHOLD = 0.95
DRIFT_THRESHOLD = 0.18

RESULTS_DIR = _PROJECT_ROOT / "experiments" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ===========================================================================
# Language-specific instruction variants
# ===========================================================================

LANG_VARIANTS = {
    "ru": {
        "id": "ru-descriptive",
        "system": (
            "Ты опытный редактор. Твоя задача — дать точный, краткий ответ на вопрос. "
            "Обязательно включи все ключевые слова из списка. "
            "Сохраняй факты, имена, числа, URL."
        ),
    },
    "en": {
        "id": "en-descriptive",
        "system": (
            "You are a professional editor. Your task is to provide a precise, "
            "concise answer to the question. You must include all keywords from the list. "
            "Preserve facts, names, numbers, URLs."
        ),
    },
    "pl": {
        "id": "pl-descriptive",
        "system": (
            "Jestes profesjonalnym redaktorem. Twoim zadaniem jest udzielenie precyzyjnej, "
            "zrozumialej odpowiedzi na pytanie. Musisz uwzglednic wszystkie slowa kluczowe z listy. "
            "Zachowaj fakty, imiona, liczby, adresy URL."
        ),
    },
}


# ===========================================================================
# Data structures
# ===========================================================================


@dataclass
class BenchmarkRow:
    query_id: str
    query_lang: str
    instruction_lang: str
    instruction_id: str
    difficulty: str
    keywords_total: int
    keywords_found: int
    keyword_coverage: float
    latency_ms: float
    answer_tokens: int
    converged: bool
    error: str | None = None


# ===========================================================================
# LLM
# ===========================================================================


async def _call_llm(client, system_prompt, user_prompt):
    url = f"{ANTHROPIC_BASE_URL}/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    resp = await client.post(url, json=payload, headers=headers, timeout=LLM_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    parts = []
    for block in data.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block["text"])
        elif isinstance(block, str):
            parts.append(block)
    result = "\n".join(parts).strip()
    if not result:
        raise ValueError("empty response")
    return result


async def _translate_to_pl(client, text):
    system = "Translate to Polish. Preserve all technical terms, names, numbers, URLs. Output only translation."
    url = f"{ANTHROPIC_BASE_URL}/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "max_tokens": 512,
        "system": system,
        "messages": [{"role": "user", "content": text}],
    }
    resp = await client.post(url, json=payload, headers=headers, timeout=LLM_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    parts = [b["text"] for b in data.get("content", []) if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(parts).strip()


# ===========================================================================
# Keyword coverage
# ===========================================================================


def _check_keywords(answer: str, must_include: list[str]) -> int:
    answer_lower = answer.lower()
    found = 0
    for kw in must_include:
        if kw.lower() in answer_lower:
            found += 1
    return found


# ===========================================================================
# Main benchmark pipeline
# ===========================================================================


async def run_pipeline(dataset_path: str, max_queries: int = 100):
    # Load dataset
    records = []
    with open(dataset_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    ru = [r for r in records if r.get("lang") == "ru"]
    en = [r for r in records if r.get("lang") == "en"]

    half = max_queries // 2
    selected = ru[:half] + en[:half]

    print(f"Loaded {len(records)} total, selected {len(selected)} ({len(ru[:half])} RU + {len(en[:half])} EN)", flush=True)

    # Generate PL translations for first 25 EN queries (to have PL subset)
    pl_queries = []
    async with httpx.AsyncClient() as client:
        print("Generating PL translations...", flush=True)
        for r in en[:25]:
            try:
                pl_text = await _translate_to_pl(client, r["query"])
                pl_r = dict(r)
                pl_r["query"] = pl_text
                pl_r["lang"] = "pl"
                pl_r["id"] = r["id"].replace("-EN-", "-PL-")
                pl_queries.append(pl_r)
            except Exception as e:
                print(f"  PL translation failed for {r['id']}: {e}", flush=True)

        all_queries = selected + pl_queries
        print(f"Total queries with PL: {len(all_queries)}", flush=True)

        # Run benchmark: each query × each language variant
        results: list[BenchmarkRow] = []
        total_runs = len(all_queries) * len(LANG_VARIANTS)
        done = 0

        for q in all_queries:
            q_lang = q.get("lang", "ru")
            must_include = q.get("must_include", [])
            difficulty = q.get("difficulty", "?")

            for instr_lang, variant in LANG_VARIANTS.items():
                done += 1
                system = variant["system"]
                user = f"Question: {q['query']}\n\nKeywords to include: {', '.join(must_include)}"

                t0 = time.monotonic()
                try:
                    answer = await _call_llm(client, system, user)
                    latency = (time.monotonic() - t0) * 1000
                    tokens = len(answer) // 4  # rough estimate
                    found = _check_keywords(answer, must_include)
                    coverage = found / len(must_include) if must_include else 1.0
                    converged = coverage >= F1_THRESHOLD

                    results.append(BenchmarkRow(
                        query_id=q["id"], query_lang=q_lang,
                        instruction_lang=instr_lang, instruction_id=variant["id"],
                        difficulty=difficulty, keywords_total=len(must_include),
                        keywords_found=found, keyword_coverage=round(coverage, 4),
                        latency_ms=round(latency, 1), answer_tokens=tokens,
                        converged=converged,
                    ))
                except Exception as exc:
                    results.append(BenchmarkRow(
                        query_id=q["id"], query_lang=q_lang,
                        instruction_lang=instr_lang, instruction_id=variant["id"],
                        difficulty=difficulty, keywords_total=len(must_include),
                        keywords_found=0, keyword_coverage=0,
                        latency_ms=round((time.monotonic() - t0) * 1000, 1),
                        answer_tokens=0, converged=False, error=str(exc),
                    ))

                if done % 30 == 0:
                    print(f"  Progress: {done}/{total_runs} ({done*100//total_runs}%)", flush=True)

    # Aggregate
    by_instr = defaultdict(lambda: {"count": 0, "coverage_sum": 0, "converged": 0, "latency_sum": 0})
    by_qinstr = defaultdict(lambda: {"count": 0, "coverage_sum": 0, "converged": 0})
    for r in results:
        k = r.instruction_lang
        by_instr[k]["count"] += 1
        by_instr[k]["coverage_sum"] += r.keyword_coverage
        by_instr[k]["converged"] += int(r.converged)
        by_instr[k]["latency_sum"] += r.latency_ms

        qk = f"{r.query_lang}->{r.instruction_lang}"
        by_qinstr[qk]["count"] += 1
        by_qinstr[qk]["coverage_sum"] += r.keyword_coverage
        by_qinstr[qk]["converged"] += int(r.converged)

    summary = {}
    for k, v in by_instr.items():
        n = v["count"]
        summary[k] = {
            "queries": n,
            "avg_keyword_coverage": round(v["coverage_sum"] / n, 4),
            "convergence_rate": round(v["converged"] / n, 4),
            "avg_latency_ms": round(v["latency_sum"] / n, 1),
        }

    cross_summary = {}
    for k, v in by_qinstr.items():
        n = v["count"]
        cross_summary[k] = {
            "queries": n,
            "avg_keyword_coverage": round(v["coverage_sum"] / n, 4),
            "convergence_rate": round(v["converged"] / n, 4),
        }

    report = {
        "experiment": "DS-743-full-benchmark",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset": dataset_path,
        "total_queries": len(all_queries),
        "total_runs": len(results),
        "languages_tested": list(LANG_VARIANTS.keys()),
        "variants": [v["id"] for v in LANG_VARIANTS.values()],
        "thresholds": {"keyword_coverage": F1_THRESHOLD, "drift": DRIFT_THRESHOLD},
        "summary_by_instruction_lang": summary,
        "summary_by_query_to_instruction": cross_summary,
        "results": [asdict(r) for r in results],
    }

    out_path = RESULTS_DIR / f"ds743_full_benchmark_{int(time.time())}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved: {out_path}", flush=True)

    print("\n=== SUMMARY BY INSTRUCTION LANGUAGE ===", flush=True)
    for k, s in sorted(summary.items(), key=lambda x: -x[1]["avg_keyword_coverage"]):
        print(f"  {k}: coverage={s['avg_keyword_coverage']:.3f} conv={s['convergence_rate']:.1%} latency={s['avg_latency_ms']:.0f}ms ({s['queries']} queries)", flush=True)

    print("\n=== CROSS (query_lang -> instruction_lang) ===", flush=True)
    for k, s in sorted(cross_summary.items()):
        print(f"  {k}: coverage={s['avg_keyword_coverage']:.3f} conv={s['convergence_rate']:.1%} ({s['queries']} queries)", flush=True)

    return report


if __name__ == "__main__":
    dataset = sys.argv[1] if len(sys.argv) > 1 else "/opt/mcp_context_pipeline/eval_queries_v3.jsonl"
    max_q = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    asyncio.run(run_pipeline(dataset, max_q))
