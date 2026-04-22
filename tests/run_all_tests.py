"""
Master test runner for MCP Context Pipeline.

Runs all test suites:
- Epic 1: Context Management
- Epic 2: Security & PII
- Epic 3: Performance & Infrastructure
- Epic 4: Model Evaluation
"""

import asyncio
import inspect
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _normalize_suite_result(raw_result):
    """Normalize different suite return formats to POSIX-like exit codes."""
    if isinstance(raw_result, bool):
        return 0 if raw_result else 1
    if isinstance(raw_result, int):
        return raw_result
    if isinstance(raw_result, tuple) and len(raw_result) >= 2:
        # Context7 suite returns (passed, failed, skipped)
        try:
            failed = int(raw_result[1])
            return 0 if failed == 0 else 1
        except Exception:
            return 1
    return 1 if raw_result else 0


async def run_suite(suite_name: str, test_module: str):
    """Run a single test suite."""
    print("\n" + "=" * 80)
    print(f"RUNNING: {suite_name}")
    print("=" * 80)

    try:
        if test_module in {"context_management", "test_context_management"} or test_module.endswith("_management"):
            from test_context_management import run_all_tests as test_func
        elif test_module in {"security_pii", "test_security_pii"} or test_module.endswith("_security"):
            from test_security_pii import run_all_tests as test_func
        elif test_module in {"performance_infra", "test_performance_infra"} or test_module.endswith("_infra"):
            from test_performance_infra import run_all_tests as test_func
        elif test_module in {"model_evaluation", "test_model_evaluation"} or test_module.endswith("_evaluation"):
            from test_model_evaluation import run_all_tests as test_func
        elif test_module in {"knowledge_bridge", "test_knowledge_bridge"} or test_module.endswith("_bridge"):
            from test_knowledge_bridge import run_all_tests as test_func
        elif test_module in {"context7_integration", "test_context7_integration"} or test_module.endswith("_context7"):
            from test_context7_integration import run_all_tests as test_func
        else:
            print(f"  Unknown test module: {test_module}")
            return 1

        suite_result = test_func()
        if inspect.isawaitable(suite_result):
            suite_result = await suite_result
        return _normalize_suite_result(suite_result)
    except Exception as e:
        print(f"  ERROR in {suite_name}: {e}")
        import traceback
        traceback.print_exc()
        return 1


async def main():
    """Main test runner."""
    print("\n" + "=" * 80)
    print("MCP CONTEXT PIPELINE - COMPLETE TEST SUITE")
    print("=" * 80)
    print(f"\nStarted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    suites = [
        ("Epic 1: Context Management", "context_management"),
        ("Epic 2: Security & PII", "security_pii"),
        ("Epic 3: Performance & Infrastructure", "performance_infra"),
        ("Epic 4: Model Evaluation", "model_evaluation"),
        ("Epic 5: Knowledge Bridge", "knowledge_bridge"),
        ("Epic 6: Context7 Integration", "context7_integration")
    ]

    results = {}
    for suite_name, module in suites:
        result = await run_suite(suite_name, module)
        results[suite_name] = result

    print("\n" + "=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)

    for suite, result in results.items():
        status = "PASS" if result == 0 else "FAIL"
        print(f"  {status:6s} - {suite}")

    total_passed = sum(1 for r in results.values() if r == 0)
    total_suites = len(results)

    print(f"\nTotal: {total_passed}/{total_suites} suites passed")

    print(f"\nCompleted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return 0 if all(r == 0 for r in results.values()) else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
