"""Pilot runner: executes the orchestrator on all 5 test cases.

Usage:
    cd /mldata/mcp_context_pipeline
    python -m pipeline.run_pilot

Results saved to pipeline/results/pilot_results.json.
Summary printed to stdout.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Ensure project root is on sys.path when running as module
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.logger import clear_log
from pipeline.orchestrator import DRIFT_THRESHOLD, F1_THRESHOLD, run_orchestration
from pipeline.test_cases import TEST_CASES


RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

MAX_ITERATIONS = 5


async def run_pilot() -> dict:
    """Run orchestrator on all test cases.

    Returns aggregated results dict.
    """
    # Clear previous logs for clean run
    clear_log()

    # Shared httpx client for connection pooling
    async with httpx.AsyncClient() as client:
        results = []
        for tc in TEST_CASES:
            print(f"\n{'='*60}")
            print(f"Test case: {tc['id']}")
            print(f"{'='*60}")

            orch_result = await run_orchestration(
                test_case_id=tc["id"],
                source_text=tc["source_text"],
                base_prompt=tc["prompt"],
                max_iterations=MAX_ITERATIONS,
                client=client,
            )

            # Print per-iteration summary
            for it in orch_result.iterations:
                status = "CONVERGED" if it.converged else "NOT CONVERGED"
                print(
                    f"  iter {it.iteration}: F1={it.f1:.4f}  "
                    f"drift={it.context_drift:.4f}  "
                    f"sim={it.semantic_similarity:.4f}  "
                    f"ratio={it.compression_ratio:.4f}  "
                    f"latency={it.latency_ms:.0f}ms  "
                    f"-> {status}"
                )
                if it.hint:
                    preview = it.hint[:120].replace("\n", " ")
                    print(f"           hint: {preview}...")

            verdict = "CONVERGED" if orch_result.converged else "NOT CONVERGED"
            print(f"  Result: {verdict} in {orch_result.total_iterations} iterations")

            results.append(
                {
                    "test_case_id": orch_result.test_case_id,
                    "converged": orch_result.converged,
                    "total_iterations": orch_result.total_iterations,
                    "final_f1": orch_result.final_f1,
                    "final_drift": orch_result.final_drift,
                    "final_text": orch_result.final_text,
                    "iterations": [
                        {
                            "iteration": it.iteration,
                            "f1": it.f1,
                            "semantic_similarity": it.semantic_similarity,
                            "context_drift": it.context_drift,
                            "compression_ratio": it.compression_ratio,
                            "original_tokens": it.original_tokens,
                            "compressed_tokens": it.compressed_tokens,
                            "latency_ms": it.latency_ms,
                            "converged": it.converged,
                            "hint": it.hint,
                            "per_type": it.per_type,
                            "generated_text": it.generated_text,
                        }
                        for it in orch_result.iterations
                    ],
                }
            )

    # Aggregate stats
    total = len(results)
    converged_count = sum(1 for r in results if r["converged"])
    avg_iterations = sum(r["total_iterations"] for r in results) / total if total else 0
    avg_f1 = sum(r["final_f1"] for r in results) / total if total else 0
    avg_drift = sum(r["final_drift"] for r in results) / total if total else 0

    summary = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "model": os.environ.get("ANTHROPIC_MODEL", "glm-4.7"),
        "max_iterations": MAX_ITERATIONS,
        "f1_threshold": F1_THRESHOLD,
        "drift_threshold": DRIFT_THRESHOLD,
        "total_cases": total,
        "converged": converged_count,
        "not_converged": total - converged_count,
        "avg_iterations": round(avg_iterations, 2),
        "avg_final_f1": round(avg_f1, 4),
        "avg_final_drift": round(avg_drift, 4),
        "results": results,
    }

    # Save results
    out_path = RESULTS_DIR / "pilot_results.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    return summary


def _print_summary(summary: dict) -> None:
    """Print human-readable summary."""
    print(f"\n{'='*60}")
    print("PILOT SUMMARY")
    print(f"{'='*60}")
    print(f"  Model:           {summary['model']}")
    print(f"  Total cases:     {summary['total_cases']}")
    print(f"  Converged:       {summary['converged']}/{summary['total_cases']}")
    print(f"  Avg iterations:  {summary['avg_iterations']}")
    print(f"  Avg final F1:    {summary['avg_final_f1']:.4f}")
    print(f"  Avg final drift: {summary['avg_final_drift']:.4f}")
    print()

    for r in summary["results"]:
        status = "OK" if r["converged"] else "FAIL"
        print(
            f"  {r['test_case_id']:6s}  [{status:4s}]  "
            f"iters={r['total_iterations']}  "
            f"F1={r['final_f1']:.4f}  "
            f"drift={r['final_drift']:.4f}"
        )

    print(f"\nResults saved to: {RESULTS_DIR / 'pilot_results.json'}")
    print(f"Logs in:          {Path(__file__).resolve().parent / 'logs'}")


def main() -> None:
    """Entry point for `python -m pipeline.run_pilot`."""
    summary = asyncio.run(run_pilot())
    _print_summary(summary)


if __name__ == "__main__":
    main()
