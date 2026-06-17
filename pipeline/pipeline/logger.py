"""JSONL iteration logger for the correction pipeline.

Log format (one JSON object per line):
    {"timestamp": "...", "test_case": "tc1", "iteration": 1,
     "f1": 0.65, "semantic_sim": 0.78, "context_drift": 0.22,
     "hint": "...", "converged": false}

Lines are flushed immediately so logs survive crashes.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _log_file(test_case_id: str) -> Path:
    """Return per-test-case log path, creating parent dir if needed."""
    safe = test_case_id.replace("/", "_")
    return LOG_DIR / f"{safe}.jsonl"


def log_iteration(
    test_case: str,
    iteration: int,
    f1: float,
    semantic_sim: float,
    context_drift: float,
    hint: str | None = None,
    converged: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one JSONL record to the test-case log file.

    Returns the record dict for convenience.
    """
    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "test_case": test_case,
        "iteration": iteration,
        "f1": round(f1, 4),
        "semantic_sim": round(semantic_sim, 4),
        "context_drift": round(context_drift, 4),
        "hint": hint,
        "converged": converged,
    }
    if extra:
        record.update(extra)

    path = _log_file(test_case)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record


def read_log(test_case: str) -> list[dict[str, Any]]:
    """Read all log entries for a given test case."""
    path = _log_file(test_case)
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def clear_log(test_case: str | None = None) -> None:
    """Clear log for a specific test case, or all logs if None."""
    if test_case:
        path = _log_file(test_case)
        if path.exists():
            path.unlink()
    else:
        for f in LOG_DIR.glob("*.jsonl"):
            f.unlink()
