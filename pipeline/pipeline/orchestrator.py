"""Iterative correction orchestrator with feedback loop.

Closes the cycle: LLM generation -> metric validation -> hint -> regeneration.

Uses direct imports from context_manager (compute_f1, compute_similarity,
estimate_tokens) — not via MCP protocol.

LLM calls go through httpx to the z.ai anthropic-compatible endpoint
(model glm-4.7) using ANTHROPIC_API_KEY from .env.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# --- Direct imports from context_manager ---
# Allow override via env var for non-standard install locations
_PROJECT_ROOT = Path(
    os.environ.get(
        "MCP_CONTEXT_PIPELINE_ROOT",
        str(Path(__file__).resolve().parent.parent),
    )
)
_CTX_MODULE_DIR = _PROJECT_ROOT / "src" / "mcp_servers" / "context_manager"
if str(_CTX_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_CTX_MODULE_DIR))

from server import compute_f1, compute_similarity, estimate_tokens  # type: ignore[import-untyped]

from pipeline.logger import log_iteration


# ===========================================================================
# Configuration
# ===========================================================================

load_dotenv(_PROJECT_ROOT / ".env", override=False)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic")
LLM_MODEL = os.environ.get("ANTHROPIC_MODEL", "glm-4.7")

F1_THRESHOLD = 0.95
DRIFT_THRESHOLD = 0.15  # context_drift = 1 - similarity; must be < 0.15
MAX_TOKENS = 1024
LLM_TIMEOUT = 60.0  # seconds


# ===========================================================================
# Data structures
# ===========================================================================


@dataclass
class IterationResult:
    """Metrics for a single iteration."""

    iteration: int
    generated_text: str
    f1: float
    semantic_similarity: float
    context_drift: float
    compression_ratio: float
    original_tokens: int
    compressed_tokens: int
    latency_ms: float
    hint: str | None
    converged: bool
    per_type: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestrationResult:
    """Full result across all iterations for one test case."""

    test_case_id: str
    iterations: list[IterationResult]
    converged: bool
    total_iterations: int
    final_text: str | None
    final_f1: float
    final_drift: float


# ===========================================================================
# LLM client
# ===========================================================================


async def _call_llm(
    client: httpx.AsyncClient,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """Call z.ai anthropic-compatible endpoint.

    Returns generated text. Raises on error.
    """
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
        "messages": [
            {"role": "user", "content": user_prompt},
        ],
    }

    resp = await client.post(url, json=payload, headers=headers, timeout=LLM_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    # Anthropic response format
    content_blocks = data.get("content", [])
    text_parts = []
    for block in content_blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(block["text"])
        elif isinstance(block, str):
            text_parts.append(block)

    result = "\n".join(text_parts).strip()
    if not result:
        raise ValueError("LLM returned empty content")
    return result


# ===========================================================================
# Hint generation
# ===========================================================================


def _build_hint(
    f1_result: dict[str, Any],
    similarity: float,
    original_text: str,
    compressed_text: str,
) -> str:
    """Build a corrective hint based on validation errors."""
    from server import extract_entities  # noqa: F811 -- re-import inside function is fine

    problems: list[str] = []
    per_type = f1_result.get("per_type", {})

    # Identify lost entity types
    lost_entities: list[str] = []
    for etype, metrics in per_type.items():
        recall = metrics.get("recall", 1.0)
        if recall < 1.0:
            orig_entities = extract_entities(original_text).get(etype, set())
            comp_entities = extract_entities(compressed_text).get(etype, set())
            missing = orig_entities - comp_entities
            if missing:
                lost_entities.append(f"{etype}={', '.join(sorted(missing))}")

    if lost_entities:
        problems.append(f"Потеряны сущности: {'; '.join(lost_entities)}")

    drift = 1 - similarity
    if drift > DRIFT_THRESHOLD:
        problems.append(
            f"Семантический дрейф слишком велик: {drift:.2f} "
            f"(допустимо < {DRIFT_THRESHOLD:.2f})"
        )

    overall_f1 = f1_result.get("overall", {}).get("f1", 0)
    if overall_f1 < F1_THRESHOLD:
        low_types = [
            f"{etype} (F1={m['f1']:.2f})"
            for etype, m in per_type.items()
            if m.get("f1", 1.0) < F1_THRESHOLD
        ]
        if low_types:
            problems.append(f"Низкий F1 по типам: {', '.join(low_types)}")

    if not problems:
        return ""

    hint = (
        "При сжатии текста были допущены следующие ошибки:\n"
        + "\n".join(f"- {p}" for p in problems)
        + "\n\nПерегенерируй сжатую версию, устранив эти проблемы. "
        "Обязательно сохрани все перечисленные сущности дословно."
    )
    return hint


# ===========================================================================
# Main orchestration loop
# ===========================================================================


async def run_orchestration(
    test_case_id: str,
    source_text: str,
    base_prompt: str,
    max_iterations: int = 3,
    client: httpx.AsyncClient | None = None,
) -> OrchestrationResult:
    """Run the iterative correction loop for one test case.

    Args:
        test_case_id: Identifier for logging.
        source_text: Original text to compress.
        base_prompt: Instruction for the coder agent.
        max_iterations: Maximum number of generate-validate cycles.
        client: Optional pre-configured httpx client (for connection reuse).

    Returns:
        OrchestrationResult with all iteration details.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    iterations: list[IterationResult] = []
    converged = False
    final_text = None
    current_hint: str | None = None

    original_tokens = estimate_tokens(source_text)

    try:
        for i in range(1, max_iterations + 1):
            # --- Step 1: Generate compressed text ---
            system_parts = [
                "Ты — эксперт по сжатию текста.",
                "Сохраняй смысл и ВСЕ сущности: имена, даты, email, числа, URL, названия проектов.",
                "Результат должен быть кратким, но без потери фактов.",
            ]
            if current_hint:
                system_parts.append(f"\n\nКОРРЕКТИРУЮЩАЯ ПОДСКАЗКА:\n{current_hint}")

            system_prompt = "\n".join(system_parts)
            user_prompt = f"{base_prompt}\n\nТекст:\n{source_text}"

            t_start = time.monotonic()
            generated_text = await _call_llm(client, system_prompt, user_prompt)
            gen_latency_ms = (time.monotonic() - t_start) * 1000

            # --- Step 2: Validate metrics ---
            f1_result = compute_f1(source_text, generated_text)
            similarity = compute_similarity(source_text, generated_text)
            context_drift = 1 - similarity
            compressed_tokens = estimate_tokens(generated_text)
            compression_ratio = (
                compressed_tokens / original_tokens if original_tokens > 0 else 0
            )
            overall_f1 = f1_result["overall"]["f1"]

            # --- Step 3: Check convergence ---
            is_converged = (
                overall_f1 >= F1_THRESHOLD and context_drift < DRIFT_THRESHOLD
            )

            # --- Step 4: Build hint if not converged ---
            if is_converged:
                hint = None
            else:
                hint = _build_hint(f1_result, similarity, source_text, generated_text)

            # --- Log ---
            iter_result = IterationResult(
                iteration=i,
                generated_text=generated_text,
                f1=overall_f1,
                semantic_similarity=similarity,
                context_drift=context_drift,
                compression_ratio=round(compression_ratio, 4),
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens,
                latency_ms=round(gen_latency_ms, 1),
                hint=hint,
                converged=is_converged,
                per_type=f1_result.get("per_type", {}),
            )
            iterations.append(iter_result)

            log_iteration(
                test_case=test_case_id,
                iteration=i,
                f1=overall_f1,
                semantic_sim=similarity,
                context_drift=context_drift,
                hint=hint,
                converged=is_converged,
                extra={
                    "compression_ratio": round(compression_ratio, 4),
                    "latency_ms": round(gen_latency_ms, 1),
                    "per_type": f1_result.get("per_type", {}),
                },
            )

            current_hint = hint
            final_text = generated_text

            if is_converged:
                converged = True
                break

    finally:
        if own_client:
            await client.aclose()

    return OrchestrationResult(
        test_case_id=test_case_id,
        iterations=iterations,
        converged=converged,
        total_iterations=len(iterations),
        final_text=final_text,
        final_f1=iterations[-1].f1 if iterations else 0.0,
        final_drift=iterations[-1].context_drift if iterations else 1.0,
    )
