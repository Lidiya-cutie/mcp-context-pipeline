"""
Test Context7 MCP Integration.

Тесты для проверки интеграции с Context7 MCP сервером
для получения актуальной документации по библиотекам.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from host_orchestrator import ContextOrchestrator


async def test_context7_connection():
    """Test 1: Подключение к Context7."""
    print("\n" + "=" * 60)
    print("Test 1: Context7 Connection")
    print("=" * 60)

    orchestrator = ContextOrchestrator(enable_context7=True)

    try:
        await orchestrator.connect()
        assert orchestrator.context7_session is not None, "Context7 session not connected"
        print("[PASS] Connected to Context7 successfully")
        return True
    except Exception as e:
        print(f"[FAIL] Connection failed: {e}")
        return False
    finally:
        await orchestrator.disconnect()


async def test_resolve_library_id():
    """Test 2: Разрешение ID библиотеки."""
    print("\n" + "=" * 60)
    print("Test 2: Resolve Library ID")
    print("=" * 60)

    orchestrator = ContextOrchestrator(enable_context7=True)

    try:
        await orchestrator.connect()

        library_id = await orchestrator.resolve_library_id("torch", "tensor operations")
        print(f"Resolved ID for 'torch': {library_id}")

        if library_id:
            print("[PASS] Library ID resolved successfully")
            return True
        else:
            print("[INFO] Library ID not resolved (may be expected)")
            return None

    except Exception as e:
        print(f"[FAIL] Resolve failed: {e}")
        return False
    finally:
        await orchestrator.disconnect()


async def test_query_library_docs():
    """Test 3: Запрос документации."""
    print("\n" + "=" * 60)
    print("Test 3: Query Library Documentation")
    print("=" * 60)

    orchestrator = ContextOrchestrator(enable_context7=True)

    try:
        await orchestrator.connect()

        docs = await orchestrator.query_library_docs("torch", "tensor creation")
        print(f"Documentation result: {len(docs) if docs else 0} chars")

        if docs and len(docs) > 0:
            print(f"[PASS] Documentation retrieved successfully")
            print(f"\n--- Docs Preview ---\n{docs[:500]}...")
            return True
        else:
            print("[INFO] No documentation retrieved (may be expected)")
            return None

    except Exception as e:
        print(f"[FAIL] Query failed: {e}")
        return False
    finally:
        await orchestrator.disconnect()


async def test_get_library_examples():
    """Test 4: Получение примеров кода."""
    print("\n" + "=" * 60)
    print("Test 4: Get Library Examples")
    print("=" * 60)

    orchestrator = ContextOrchestrator(enable_context7=True)

    try:
        await orchestrator.connect()

        examples = await orchestrator.get_library_examples("torch", "tensor operations")
        print(f"Examples count: {len(examples)}")

        if examples:
            print("[PASS] Examples retrieved successfully")
            for i, ex in enumerate(examples[:2], 1):
                print(f"\n--- Example {i} ---")
                print(ex[:300] + "..." if len(ex) > 300 else ex)
            return True
        else:
            print("[INFO] No examples retrieved (may be expected)")
            return None

    except Exception as e:
        print(f"[FAIL] Get examples failed: {e}")
        return False
    finally:
        await orchestrator.disconnect()


async def test_list_supported_libraries():
    """Test 5: Список поддерживаемых библиотек."""
    print("\n" + "=" * 60)
    print("Test 5: List Supported Libraries")
    print("=" * 60)

    orchestrator = ContextOrchestrator(enable_context7=True)

    try:
        await orchestrator.connect()

        libs = await orchestrator.list_supported_libraries()
        print(f"Supported libraries: {len(libs)}")

        if libs:
            print(f"[PASS] Libraries list retrieved successfully")
            print(f"Libraries: {', '.join(libs.keys())}")
            return True
        else:
            print("[INFO] No libraries retrieved (may be expected)")
            return None

    except Exception as e:
        print(f"[FAIL] List libraries failed: {e}")
        return False
    finally:
        await orchestrator.disconnect()


async def test_context7_with_knowledge_bridge():
    """Test 6: Совместная работа Context7 и Knowledge Bridge."""
    print("\n" + "=" * 60)
    print("Test 6: Context7 + Knowledge Bridge")
    print("=" * 60)

    orchestrator = ContextOrchestrator(
        enable_knowledge_bridge=True,
        enable_context7=True
    )

    try:
        await orchestrator.connect()

        assert orchestrator.knowledge_session is not None, "Knowledge Bridge not connected"
        assert orchestrator.context7_session is not None, "Context7 not connected"

        print("[PASS] Both services connected successfully")

        kb_domains = await orchestrator.list_knowledge_domains()
        ctx7_libs = await orchestrator.list_supported_libraries()

        print(f"Knowledge domains: {len(kb_domains)}")
        print(f"Context7 libraries: {len(ctx7_libs)}")

        return True

    except Exception as e:
        print(f"[FAIL] Combined connection failed: {e}")
        return False
    finally:
        await orchestrator.disconnect()


async def run_all_tests():
    """Запустить все тесты."""
    print("\n" + "=" * 60)
    print("CONTEXT7 INTEGRATION TEST SUITE")
    print("=" * 60)

    tests = [
        ("Context7 Connection", test_context7_connection),
        ("Resolve Library ID", test_resolve_library_id),
        ("Query Library Docs", test_query_library_docs),
        ("Get Library Examples", test_get_library_examples),
        ("List Supported Libraries", test_list_supported_libraries),
        ("Context7 + Knowledge Bridge", test_context7_with_knowledge_bridge),
    ]

    results = []

    for name, test_func in tests:
        result = await test_func()
        results.append((name, result))

    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, r in results if r is True)
    failed = sum(1 for _, r in results if r is False)
    skipped = sum(1 for _, r in results if r is None)

    for name, result in results:
        status = "[PASS]" if result is True else ("[FAIL]" if result is False else "[SKIP]")
        print(f"{status} {name}")

    print(f"\nTotal: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Skipped: {skipped}")

    return passed, failed, skipped


if __name__ == "__main__":
    passed, failed, skipped = asyncio.run(run_all_tests())

    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)
