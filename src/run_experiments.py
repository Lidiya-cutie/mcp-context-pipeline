"""Runner for cross-validation and instruction-benchmark experiments.

Usage:
    python -m src.run_experiments
    # or: python src/run_experiments.py
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(
    os.environ.get("MCP_CONTEXT_PIPELINE_ROOT", Path(__file__).resolve().parents[1])
)
sys.path.insert(0, str(_PROJECT_ROOT / "pipeline"))
sys.path.insert(0, str(_PROJECT_ROOT / "src" / "mcp_servers" / "context_manager"))
sys.path.insert(0, str(Path(__file__).parent))

from test_cases import TEST_CASES
from cross_validation import run_cross_validation
from instruction_benchmark import run_benchmark, run_instruction_search, INSTRUCTION_VARIANTS

OUTPUT_DIR = _PROJECT_ROOT / "experiments"
OUTPUT_DIR.mkdir(exist_ok=True)


async def main():
    ts = int(time.time())

    # --- DS-742: Cross-validation ---
    print("=" * 70)
    print("DS-742: Cross-validation with multiple LLMs")
    print("=" * 70)
    cv_results = []
    for tc in TEST_CASES:
        print(f"\nTest case: {tc['id']}")
        report = await run_cross_validation(
            test_case_id=tc["id"],
            source_text=tc["source_text"],
            base_prompt=tc["prompt"],
        )
        d = {
            "test_case_id": report.test_case_id,
            "responses": [
                {"model": r.model, "text": r.text[:200], "latency_ms": r.latency_ms,
                 "error": r.error, "tokens": r.tokens}
                for r in report.responses
            ],
            "pairwise_similarity": report.pairwise_similarity,
            "avg_similarity": report.avg_similarity,
            "consensus_fragments_count": len(report.consensus_fragments),
            "divergent_fragments_count": len(report.divergent_fragments),
            "entity_coverage": report.entity_coverage,
            "hallucination_risk": report.hallucination_risk,
            "confidence": report.confidence,
        }
        cv_results.append(d)
        print(f"  Avg similarity: {report.avg_similarity}")
        print(f"  Hallucination risk: {report.hallucination_risk}")
        print(f"  Confidence: {report.confidence}")
        for pair, sim in report.pairwise_similarity.items():
            print(f"    {pair}: {sim}")

    cv_output = {
        "experiment": "DS-742-cross-validation",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_cases": len(cv_results),
        "results": cv_results,
    }
    cv_path = OUTPUT_DIR / f"ds742_cross_validation_{ts}.json"
    cv_path.write_text(json.dumps(cv_output, ensure_ascii=False, indent=2))
    print(f"\nSaved: {cv_path}")

    # --- DS-743: Instruction benchmark ---
    print("\n" + "=" * 70)
    print("DS-743: Benchmark effectiveness of language instructions")
    print("=" * 70)
    bench_results = await run_benchmark(TEST_CASES, INSTRUCTION_VARIANTS)
    bench_data = [r.__dict__ for r in bench_results]

    # Aggregate by variant
    by_variant = {}
    for r in bench_results:
        v = r.variant_id
        if v not in by_variant:
            by_variant[v] = {"count": 0, "converged": 0, "f1_sum": 0, "drift_sum": 0, "ratio_sum": 0}
        by_variant[v]["count"] += 1
        by_variant[v]["converged"] += int(r.converged)
        by_variant[v]["f1_sum"] += r.f1
        by_variant[v]["drift_sum"] += r.context_drift
        by_variant[v]["ratio_sum"] += r.compression_ratio

    summary = {}
    for v, agg in by_variant.items():
        n = agg["count"]
        summary[v] = {
            "convergence_rate": round(agg["converged"] / n, 4),
            "avg_f1": round(agg["f1_sum"] / n, 4),
            "avg_drift": round(agg["drift_sum"] / n, 4),
            "avg_compression_ratio": round(agg["ratio_sum"] / n, 4),
        }

    bench_output = {
        "experiment": "DS-743-instruction-benchmark",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "variants_tested": len(INSTRUCTION_VARIANTS),
        "total_runs": len(bench_data),
        "summary_by_variant": summary,
        "results": bench_data,
    }
    bench_path = OUTPUT_DIR / f"ds743_instruction_benchmark_{ts}.json"
    bench_path.write_text(json.dumps(bench_output, ensure_ascii=False, indent=2))
    print(f"\nSaved: {bench_path}")
    print("\nSummary by variant:")
    for v, s in sorted(summary.items(), key=lambda x: -x[1]["avg_f1"]):
        print(f"  {v}: F1={s['avg_f1']:.3f} drift={s['avg_drift']:.3f} conv={s['convergence_rate']:.0%}")

    # --- DS-744: Compressing instruction search ---
    print("\n" + "=" * 70)
    print("DS-744: Search for compressing instructions")
    print("=" * 70)
    search_results = await run_instruction_search(TEST_CASES, max_variants=10)
    search_data = [r.__dict__ for r in search_results]

    search_output = {
        "experiment": "DS-744-compressing-instructions",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_variants": len(search_data),
        "top_5": search_data[:5],
        "results": search_data,
    }
    search_path = OUTPUT_DIR / f"ds744_compressing_instructions_{ts}.json"
    search_path.write_text(json.dumps(search_output, ensure_ascii=False, indent=2))
    print(f"\nSaved: {search_path}")
    print("\nTop 5 compressing instructions:")
    for r in search_results[:5]:
        print(f"  {r.instruction_id} (entities={r.entity_count}): F1={r.f1:.3f} drift={r.context_drift:.3f} conv={r.converged}")

    print("\n" + "=" * 70)
    print("ALL EXPERIMENTS COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
