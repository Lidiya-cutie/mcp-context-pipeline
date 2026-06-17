"""Iterative correction pipeline with feedback loop.

Modules:
    orchestrator — main correction loop (LLM generate -> validate -> hint -> regenerate)
    test_cases   — 5 diverse test cases for pilot evaluation
    run_pilot    — pilot runner over test cases
    logger       — JSONL iteration logging
"""

__version__ = "1.0.0"
