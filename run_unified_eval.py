"""
Unified evaluation runner for external knowledge and REST API quality.

Artifacts:
- unified_eval_report.json
- unified_eval_summary.txt
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.unified_evaluator import main


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
