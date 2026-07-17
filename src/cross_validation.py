"""Cross-validation with multiple LLMs — consensus-based hallucination reduction.

DS-742: Research how querying multiple LLMs and computing consensus
reduces hallucinations in generated outputs.

Approach:
1. Send the same prompt to N different models (glm-4.7, gpt-4o-mini).
2. Compute pairwise similarity between responses.
3. Extract consensus fragments (present in >=threshold responses).
4. Flag divergent fragments as potential hallucinations.
5. Produce a final "consensus" answer with confidence scores.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
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

from server import compute_similarity, extract_entities, estimate_tokens  # type: ignore[import-untyped]

load_dotenv(_PROJECT_ROOT / ".env", override=False)

MODELS = {
    "glm-4.7": {
        "provider": "zai",
        "base_url": os.getenv("ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic"),
        "api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "protocol": "anthropic",
    },
    "mimo-v2.5": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": os.getenv("OPENROUTER_API_KEY", ""),
        "model_name": "xiaomi/mimo-v2.5",
        "protocol": "openai",
    },
    "gpt-4o-mini": {
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "protocol": "openai",
    },
}

CONSENSUS_THRESHOLD = 0.6
SIMILARITY_GATE = 0.75
MAX_TOKENS = 1024
LLM_TIMEOUT = 60.0


@dataclass
class ModelResponse:
    model: str
    text: str
    latency_ms: float
    error: str | None = None
    tokens: int = 0


@dataclass
class ConsensusReport:
    test_case_id: str
    responses: list[ModelResponse]
    pairwise_similarity: dict[str, float]
    avg_similarity: float
    consensus_text: str
    consensus_fragments: list[dict[str, Any]]
    divergent_fragments: list[dict[str, Any]]
    entity_coverage: dict[str, dict[str, float]]
    hallucination_risk: float
    confidence: float


async def _call_anthropic(client, base_url, api_key, model, system_prompt, user_prompt):
    url = f"{base_url}/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
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
        raise ValueError(f"{model}: empty response")
    return result


async def _call_openai(client, base_url, api_key, model, system_prompt, user_prompt):
    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "content-type": "application/json"}
    payload = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    resp = await client.post(url, json=payload, headers=headers, timeout=LLM_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    result = data["choices"][0]["message"]["content"].strip()
    if not result:
        raise ValueError(f"{model}: empty response")
    return result


async def _call_model(client, model_name, system_prompt, user_prompt):
    cfg = MODELS[model_name]
    api_model = cfg.get("model_name", model_name)
    t0 = time.monotonic()
    try:
        if cfg["protocol"] == "anthropic":
            text = await _call_anthropic(client, cfg["base_url"], cfg["api_key"], api_model, system_prompt, user_prompt)
        else:
            text = await _call_openai(client, cfg["base_url"], cfg["api_key"], api_model, system_prompt, user_prompt)
        latency = (time.monotonic() - t0) * 1000
        return ModelResponse(model=model_name, text=text, latency_ms=round(latency, 1), tokens=estimate_tokens(text))
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return ModelResponse(model=model_name, text="", latency_ms=round(latency, 1), error=str(exc))


def _split_sentences(text):
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if s.strip()]


def _pairwise_similarity(responses):
    valid = [r for r in responses if r.text]
    result = {}
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            sim = compute_similarity(valid[i].text, valid[j].text)
            result[f"{valid[i].model} <-> {valid[j].model}"] = round(sim, 4)
    return result


def _extract_consensus(responses, threshold=CONSENSUS_THRESHOLD):
    valid = [r for r in responses if r.text]
    if not valid:
        return [], [], ""
    n = len(valid)
    min_agree = max(2, int(n * threshold))
    all_sentences = []
    for resp in valid:
        for sent in _split_sentences(resp.text):
            all_sentences.append((resp.model, sent))
    consensus_frags = []
    divergent_frags = []
    used = set()
    for idx, (model, sent) in enumerate(all_sentences):
        if idx in used:
            continue
        agreeing_models = {model}
        for jdx in range(idx + 1, len(all_sentences)):
            if jdx in used:
                continue
            other_model, other_sent = all_sentences[jdx]
            if other_model in agreeing_models:
                continue
            sim = compute_similarity(sent, other_sent)
            if sim >= SIMILARITY_GATE:
                agreeing_models.add(other_model)
                used.add(jdx)
        used.add(idx)
        entry = {
            "fragment": sent,
            "models": sorted(agreeing_models),
            "agreement": round(len(agreeing_models) / n, 2),
        }
        if len(agreeing_models) >= min_agree:
            consensus_frags.append(entry)
        else:
            divergent_frags.append(entry)
    consensus_frags.sort(key=lambda x: -x["agreement"])
    divergent_frags.sort(key=lambda x: x["agreement"])
    consensus_text = " ".join(f["fragment"] for f in consensus_frags)
    return consensus_frags, divergent_frags, consensus_text


def _entity_coverage(source_text, responses):
    source_entities = extract_entities(source_text)
    valid = [r for r in responses if r.text]
    if not valid:
        return {}
    coverage = {}
    for etype, ents in source_entities.items():
        if not ents:
            continue
        per_model = {}
        for resp in valid:
            resp_entities = extract_entities(resp.text).get(etype, set())
            per_model[resp.model] = round(len(ents & resp_entities) / len(ents), 4) if ents else 0
        coverage[etype] = per_model
    return coverage


def _hallucination_risk(divergent_frags, entity_coverage):
    if not divergent_frags and not entity_coverage:
        return 0.0
    risk = len(divergent_frags) / max(len(divergent_frags) + 1, 1)
    recalls = [r for etype in entity_coverage for r in entity_coverage[etype].values()]
    avg_recall = sum(recalls) / max(1, len(recalls)) if recalls else 1.0
    risk = risk * (1 - avg_recall)
    return round(min(risk, 1.0), 4)


async def run_cross_validation(test_case_id, source_text, base_prompt, models=None):
    model_list = models or list(MODELS.keys())
    system_prompt = (
        "Ты эксперт по сжатию текста. "
        "Сохраняй смысл и ВСЕ сущности: имена, даты, email, числа, URL, названия. "
        "Результат краткий, но без потери фактов."
    )
    user_prompt = f"{base_prompt}\n\nТекст:\n{source_text}"
    async with httpx.AsyncClient() as client:
        tasks = [_call_model(client, m, system_prompt, user_prompt) for m in model_list]
        responses = await asyncio.gather(*tasks)
    pairwise = _pairwise_similarity(responses)
    avg_sim = round(sum(pairwise.values()) / max(1, len(pairwise)), 4)
    cons_frags, div_frags, cons_text = _extract_consensus(responses)
    ent_coverage = _entity_coverage(source_text, responses)
    risk = _hallucination_risk(div_frags, ent_coverage)
    return ConsensusReport(
        test_case_id=test_case_id, responses=responses,
        pairwise_similarity=pairwise, avg_similarity=avg_sim,
        consensus_text=cons_text, consensus_fragments=cons_frags,
        divergent_fragments=div_frags, entity_coverage=ent_coverage,
        hallucination_risk=risk, confidence=round(1 - risk, 4),
    )
