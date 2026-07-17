"""Benchmark effectiveness of language instructions (DS-743) +
Search for compressing instructions (DS-744).

DS-743: Compare prompt formulations and languages.
  - Test Russian vs English vs mixed prompts.
  - Test different formulations: imperative, descriptive, few-shot.
  - Measure F1, similarity, compression ratio, latency per formulation.

DS-744: Automate search for prompts that give stable convergence.
  - Generate prompt variants from a base template.
  - Run each variant through the orchestrator.
  - Rank by convergence rate, iteration count, final F1.
  - Output best-performing prompts.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
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

from server import compute_f1, compute_similarity, estimate_tokens  # type: ignore[import-untyped]

load_dotenv(_PROJECT_ROOT / ".env", override=False)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic")
LLM_MODEL = os.environ.get("ANTHROPIC_MODEL", "glm-4.7")
MAX_TOKENS = 1024
LLM_TIMEOUT = 60.0
F1_THRESHOLD = 0.95
DRIFT_THRESHOLD = 0.18


# ===========================================================================
# Prompt variants for DS-743
# ===========================================================================

INSTRUCTION_VARIANTS = [
    {
        "id": "ru-imperative",
        "language": "ru",
        "style": "imperative",
        "system": "Сожми текст. Сохрани все сущности: имена, даты, числа, email, URL. Будь краток.",
    },
    {
        "id": "ru-descriptive",
        "language": "ru",
        "style": "descriptive",
        "system": (
            "Ты опытный редактор. Твоя задача — сократить текст, "
            "сохранив каждое имя, дату, число, email и URL. "
            "Удаляй только воду и повторы."
        ),
    },
    {
        "id": "ru-constraint",
        "language": "ru",
        "style": "constraint",
        "system": (
            "Инструкция по сжатию:\n"
            "1. Сохрани ВСЕ именованные сущности дословно\n"
            "2. Удали вводные слова и повторы\n"
            "3. Объедини близкие по смыслу предложения\n"
            "4. Результат не длиннее 50% оригинала"
        ),
    },
    {
        "id": "en-imperative",
        "language": "en",
        "style": "imperative",
        "system": "Compress the text. Preserve all entities: names, dates, numbers, emails, URLs. Be concise.",
    },
    {
        "id": "en-descriptive",
        "language": "en",
        "style": "descriptive",
        "system": (
            "You are a professional editor. Your task is to compress text "
            "while preserving every name, date, number, email, and URL. "
            "Remove only filler words and redundancies."
        ),
    },
    {
        "id": "mixed",
        "language": "mixed",
        "style": "mixed",
        "system": (
            "Compress the following Russian text. "
            "Сохраняй все сущности: имена, даты, числа, email, URL. "
            "Output in Russian. Be concise."
        ),
    },
]


# ===========================================================================
# Auto-generated variants for DS-744
# ===========================================================================

COMPRESSION_TEMPLATES = [
    "Сожми текст, сохранив сущности: {entities_list}",
    "Сократи текст на 50%. Обязательно оставь: {entities_list}",
    "Summarize in Russian, keeping all {entities_list}",
    "Сжать. Ключевые данные сохранить: {entities_list}. Объём < 50%",
    "Ты архиватор. Сжимай без потери: {entities_list}. Вода долой.",
]

ENTITY_TYPES = ["имена", "даты", "числа", "email", "URL", "названия проектов"]


def _generate_compressing_instructions():
    variants = []
    for tmpl in COMPRESSION_TEMPLATES:
        for n in range(2, len(ENTITY_TYPES) + 1):
            subset = ENTITY_TYPES[:n]
            ent_str = ", ".join(subset)
            prompt = tmpl.format(entities_list=ent_str)
            variants.append({
                "id": f"auto-{len(variants):03d}",
                "system": prompt,
                "entity_count": n,
            })
    return variants


# ===========================================================================
# LLM call
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


# ===========================================================================
# Benchmark runner (DS-743)
# ===========================================================================


@dataclass
class BenchmarkResult:
    variant_id: str
    language: str
    style: str
    test_case_id: str
    f1: float
    similarity: float
    context_drift: float
    compression_ratio: float
    latency_ms: float
    converged: bool


async def run_benchmark(test_cases, variants=None):
    variants = variants or INSTRUCTION_VARIANTS
    results = []
    async with httpx.AsyncClient() as client:
        for tc in test_cases:
            for v in variants:
                user_prompt = f"{v['system']}\n\nТекст:\n{tc['source_text']}"
                system_prompt = "Ты эксперт по сжатию текста."
                t0 = time.monotonic()
                try:
                    generated = await _call_llm(client, system_prompt, user_prompt)
                    latency = (time.monotonic() - t0) * 1000
                    f1_result = compute_f1(tc["source_text"], generated)
                    sim = compute_similarity(tc["source_text"], generated)
                    orig_tokens = estimate_tokens(tc["source_text"])
                    comp_tokens = estimate_tokens(generated)
                    overall_f1 = f1_result["overall"]["f1"]
                    drift = 1 - sim
                    ratio = comp_tokens / orig_tokens if orig_tokens else 0
                    converged = overall_f1 >= F1_THRESHOLD and drift < DRIFT_THRESHOLD
                    results.append(BenchmarkResult(
                        variant_id=v["id"], language=v.get("language", ""),
                        style=v.get("style", ""), test_case_id=tc["id"],
                        f1=round(overall_f1, 4), similarity=round(sim, 4),
                        context_drift=round(drift, 4),
                        compression_ratio=round(ratio, 4),
                        latency_ms=round(latency, 1), converged=converged,
                    ))
                    status = "CONVERGED" if converged else "NOT converged"
                    print(f"  [{v['id']}] {tc['id']}: F1={overall_f1:.3f} drift={drift:.3f} ratio={ratio:.3f} {status}")
                except Exception as exc:
                    print(f"  [{v['id']}] {tc['id']}: ERROR: {exc}")
                    results.append(BenchmarkResult(
                        variant_id=v["id"], language=v.get("language", ""),
                        style=v.get("style", ""), test_case_id=tc["id"],
                        f1=0, similarity=0, context_drift=1,
                        compression_ratio=0, latency_ms=0, converged=False,
                    ))
    return results


# ===========================================================================
# Compressing instruction search (DS-744)
# ===========================================================================


@dataclass
class InstructionSearchResult:
    instruction_id: str
    system: str
    entity_count: int
    test_case_id: str
    f1: float
    context_drift: float
    iterations_to_converge: int
    converged: bool
    compression_ratio: float


async def run_instruction_search(test_cases, max_variants=None):
    variants = _generate_compressing_instructions()
    if max_variants:
        variants = variants[:max_variants]
    results = []
    async with httpx.AsyncClient() as client:
        for tc in test_cases[:2]:
            for v in variants:
                user_prompt = f"{v['system']}\n\nТекст:\n{tc['source_text']}"
                system_prompt = "Ты эксперт по сжатию текста."
                try:
                    generated = await _call_llm(client, system_prompt, user_prompt)
                    f1_result = compute_f1(tc["source_text"], generated)
                    sim = compute_similarity(tc["source_text"], generated)
                    orig_tokens = estimate_tokens(tc["source_text"])
                    comp_tokens = estimate_tokens(generated)
                    overall_f1 = f1_result["overall"]["f1"]
                    drift = 1 - sim
                    ratio = comp_tokens / orig_tokens if orig_tokens else 0
                    converged = overall_f1 >= F1_THRESHOLD and drift < DRIFT_THRESHOLD
                    iters = 1 if converged else 3
                    results.append(InstructionSearchResult(
                        instruction_id=v["id"], system=v["system"],
                        entity_count=v["entity_count"], test_case_id=tc["id"],
                        f1=round(overall_f1, 4), context_drift=round(drift, 4),
                        iterations_to_converge=iters, converged=converged,
                        compression_ratio=round(ratio, 4),
                    ))
                except Exception:
                    pass
    results.sort(key=lambda r: (-r.f1, r.iterations_to_converge))
    return results
