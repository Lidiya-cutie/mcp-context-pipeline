"""DS-747: Experiments with LLM and system prompts.

Compare models and system prompt variants for stability, quality, and consistency.

Metrics:
- response_stability: variance of responses across runs (lower = more stable)
- keyword_coverage: fraction of must_include keywords present
- f1: token overlap with reference answer
- latency_ms: time to first token + total
- error_rate: fraction of failed requests
- consistency: pairwise similarity between repeated runs (same prompt, same model)
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

_PROJECT_ROOT = Path(os.environ.get(
    "MCP_CONTEXT_PIPELINE_ROOT",
    Path(__file__).resolve().parents[1],
))
_CTX_MODULE_DIR = _PROJECT_ROOT / "src" / "mcp_servers" / "context_manager"
if str(_CTX_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_CTX_MODULE_DIR))

from server import compute_f1, compute_similarity, extract_entities  # type: ignore[import-untyped]

load_dotenv(_PROJECT_ROOT / ".env", override=False)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic")

# OpenRouter key: env var first, file fallback for local dev only
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
if not OPENROUTER_KEY:
    _or_key = os.environ.get("OPENROUTER_KEY_FILE", "")
    if _or_key and Path(_or_key).exists():
        for line in Path(_or_key).read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                OPENROUTER_KEY = line.split("=", 1)[1].strip().strip('"')
                break

MODELS = {
    "glm-4.7": {
        "provider": "zai",
        "base_url": ANTHROPIC_BASE_URL,
        "api_key": ANTHROPIC_API_KEY,
        "protocol": "anthropic",
    },
    "mimo-v2.5": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": OPENROUTER_KEY,
        "protocol": "openai",
        "model_id": "xiaomi/mimo-v2.5:free",
    },
}

SYSTEM_PROMPTS = {
    "neutral": "You are a helpful assistant. Answer accurately and concisely.",
    "expert": (
        "You are a senior software engineer with 15 years of experience. "
        "Provide precise, production-ready answers with error handling. "
        "Include code examples when relevant."
    ),
    "strict": (
        "You are a code generation system. Follow the specification exactly. "
        "Do not add unnecessary commentary. Output only the requested code "
        "and minimal explanation."
    ),
    "ru-expert": (
        "Ты — старший разработчик с 15-летним опытом. "
        "Отвечай точно, с обработкой ошибок. "
        "Приводи примеры кода когда уместно."
    ),
    "safety": (
        "You are a careful assistant. Before answering, verify all assumptions. "
        "If uncertain, state what you don't know. Prioritize correctness over completeness."
    ),
}

REPEATS = 2
TIMEOUT = 60.0
BATCH_SIZE = 3
BATCH_DELAY = 3.0


def _parse_anthropic_response(data: dict) -> dict:
    """Extract text and token count from Anthropic API response."""
    content = data.get("content")
    if not content or not isinstance(content, list):
        return {"text": "", "tokens": 0, "warning": "empty or missing content block"}
    text = ""
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text", "")
    tokens = data.get("usage", {}).get("output_tokens", 0)
    return {"text": text, "tokens": tokens}


def _parse_openai_response(data: dict) -> dict:
    """Extract text and token count from OpenAI-compatible API response."""
    choices = data.get("choices")
    if not choices or not isinstance(choices, list):
        return {"text": "", "tokens": 0, "warning": "empty or missing choices"}
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    text = message.get("content", "")
    tokens = data.get("usage", {}).get("completion_tokens", 0)
    return {"text": text, "tokens": tokens}


async def call_glm(client: httpx.AsyncClient, system: str, user_msg: str) -> dict:
    payload = {
        "model": "glm-4.7",
        "max_tokens": 1024,
        "system": system,
        "messages": [{"role": "user", "content": user_msg}],
    }
    r = await client.post(
        f"{ANTHROPIC_BASE_URL}/v1/messages",
        json=payload,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return _parse_anthropic_response(r.json())


async def call_mimo(client: httpx.AsyncClient, system: str, user_msg: str) -> dict:
    payload = {
        "model": "xiaomi/mimo-v2.5:free",
        "max_tokens": 1024,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
    }
    r = await client.post(
        "https://openrouter.ai/api/v1/chat/completions",
        json=payload,
        headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return _parse_openai_response(r.json())


@dataclass
class RunResult:
    model: str
    system_prompt: str
    run_index: int
    text: str = ""
    latency_ms: float = 0.0
    error: str | None = None
    tokens: int = 0
    keywords_hit: list[str] = field(default_factory=list)
    keywords_total: int = 0
    f1: float = 0.0


async def run_single(
    client: httpx.AsyncClient,
    model_key: str,
    system_key: str,
    user_msg: str,
    keywords: list[str],
    run_idx: int,
) -> RunResult:
    start = time.monotonic()
    try:
        if model_key == "glm-4.7":
            res = await call_glm(client, SYSTEM_PROMPTS[system_key], user_msg)
        else:
            res = await call_mimo(client, SYSTEM_PROMPTS[system_key], user_msg)
        latency = (time.monotonic() - start) * 1000
        text = res["text"]
        kw_hit = [k for k in keywords if k.lower() in text.lower()]
        f1_raw = compute_f1(text, " ".join(keywords))
        if isinstance(f1_raw, dict):
            f1 = f1_raw.get("overall", {}).get("f1", 0.0)
        else:
            f1 = float(f1_raw)
        return RunResult(
            model=model_key,
            system_prompt=system_key,
            run_index=run_idx,
            text=text,
            latency_ms=round(latency, 1),
            tokens=res["tokens"],
            keywords_hit=kw_hit,
            keywords_total=len(keywords),
            f1=round(f1, 4),
        )
    except Exception as exc:
        latency = (time.monotonic() - start) * 1000
        return RunResult(
            model=model_key,
            system_prompt=system_key,
            run_index=run_idx,
            latency_ms=round(latency, 1),
            error=str(exc)[:300],
            keywords_total=len(keywords),
        )


async def main() -> None:
    queries_file = _PROJECT_ROOT / "eval_queries_v3.jsonl"
    queries: list[dict] = []
    with open(queries_file) as f:
        for line in f:
            q = json.loads(line.strip())
            if q.get("lang") == "en":
                queries.append(q)
    queries = queries[:3]

    async with httpx.AsyncClient() as client:
        tasks: list = []
        for q in queries:
            keywords = q.get("must_include", [])
            for model_key in MODELS:
                for sp_key in SYSTEM_PROMPTS:
                    for rep in range(REPEATS):
                        tasks.append(
                            run_single(
                                client, model_key, sp_key,
                                q["query"], keywords, rep,
                            )
                        )
        total = len(tasks)
        print(f"Running {total} requests in batches of {BATCH_SIZE}")
        results: list[RunResult] = []
        for i in range(0, total, BATCH_SIZE):
            batch = tasks[i:i + BATCH_SIZE]
            batch_results = await asyncio.gather(*batch)
            results.extend(batch_results)
            done = min(i + BATCH_SIZE, total)
            print(f"  {done}/{total} done")
            if done < total:
                await asyncio.sleep(BATCH_DELAY)

    summary: dict[str, dict] = {}
    for r in results:
        key = f"{r.model}|{r.system_prompt}"
        if key not in summary:
            summary[key] = {
                "model": r.model,
                "system_prompt": r.system_prompt,
                "runs": 0,
                "errors": 0,
                "latencies": [],
                "f1s": [],
                "keyword_ratios": [],
            }
        s = summary[key]
        s["runs"] += 1
        if r.error:
            s["errors"] += 1
        else:
            s["latencies"].append(r.latency_ms)
            s["f1s"].append(r.f1)
            if r.keywords_total > 0:
                s["keyword_ratios"].append(len(r.keywords_hit) / r.keywords_total)

    final_summary = {}
    for key, s in summary.items():
        lats = s.pop("latencies")
        f1s = s.pop("f1s")
        kws = s.pop("keyword_ratios")
        s["error_rate"] = round(s["errors"] / s["runs"], 3) if s["runs"] else 1.0
        s["avg_latency_ms"] = round(statistics.mean(lats), 1) if lats else 0
        s["latency_stdev"] = round(statistics.stdev(lats), 1) if len(lats) > 1 else 0
        s["avg_f1"] = round(statistics.mean(f1s), 4) if f1s else 0
        s["f1_stdev"] = round(statistics.stdev(f1s), 4) if len(f1s) > 1 else 0
        s["avg_keyword_coverage"] = round(statistics.mean(kws), 4) if kws else 0
        s["stability"] = round(1 - (s["f1_stdev"] / max(s["avg_f1"], 0.001)), 4) if f1s else 0
        final_summary[key] = s

    output = {
        "experiment": "DS-747: LLM and system prompt stability benchmark",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "models_tested": list(MODELS.keys()),
        "system_prompts_tested": list(SYSTEM_PROMPTS.keys()),
        "repeats_per_config": REPEATS,
        "queries": len(queries),
        "total_runs": len(results),
        "summary": final_summary,
        "raw_results": [asdict(r) for r in results],
    }

    outdir = Path(os.environ.get("OUTPUT_DIR", str(_PROJECT_ROOT / "experiments")))
    outdir.mkdir(exist_ok=True)
    outfile = outdir / f"system_prompt_benchmark_{int(time.time())}.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\nResults saved to {outfile}")
    print(f"\nSummary ({len(final_summary)} configs):")
    for key, s in sorted(final_summary.items(), key=lambda x: -x[1].get("avg_f1", 0)):
        print(f"  {key}: f1={s['avg_f1']:.4f} stability={s['stability']:.4f} "
              f"latency={s['avg_latency_ms']:.0f}ms errors={s['error_rate']:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
