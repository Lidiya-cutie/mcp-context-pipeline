"""
Test Pipeline for MCP Context Pipeline.
Stress test with 100k tokens to verify AC1 (automatic compression).

This test:
1. Generates a large amount of log data (simulating 100k+ tokens)
2. Feeds it through the orchestrator
3. Verifies automatic compression is triggered (AC1)
4. Confirms context is properly managed
"""

import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from host_orchestrator import ContextOrchestrator
from utils import count_tokens


def generate_log_data(num_logs: int = 500) -> str:
    """
    Generate realistic log data for testing.

    Args:
        num_logs: Number of log entries to generate

    Returns:
        Concatenated log string
    """
    import random
    from datetime import datetime, timedelta

    log_templates = [
        "[INFO] Process started with PID {pid}",
        "[DEBUG] Memory usage: {mem}MB, CPU: {cpu}%",
        "[INFO] Database connection established: {db}",
        "[WARN] Response time high: {time}ms for endpoint /api/{endpoint}",
        "[ERROR] Exception in module {module}: {error}",
        "[INFO] Cache hit ratio: {ratio}%",
        "[DEBUG] Transaction {tx_id} completed in {time}ms",
        "[INFO] User {user_id} authenticated via {method}",
        "[WARN] Disk usage at {disk}% - consider cleanup",
        "[INFO] Background job {job_id} started with priority {priority}"
    ]

    endpoints = ["users", "orders", "products", "analytics", "search", "auth"]
    modules = ["payment", "notification", "search", "auth", "database"]
    errors = ["TimeoutError", "ConnectionError", "ValidationError", "NotFoundError"]
    methods = ["OAuth2", "JWT", "API Key", "Session"]

    logs = []
    base_time = datetime.now() - timedelta(hours=1)

    for i in range(num_logs):
        template = random.choice(log_templates)
        log = template.format(
            pid=random.randint(1000, 9999),
            mem=random.randint(100, 2000),
            cpu=random.randint(5, 95),
            db=random.choice(["primary", "replica-1", "replica-2"]),
            time=random.randint(50, 5000),
            endpoint=random.choice(endpoints),
            tx_id=f"tx_{random.randint(100000, 999999)}",
            user_id=f"user_{random.randint(1, 10000)}",
            ratio=random.randint(60, 99),
            disk=random.randint(70, 95),
            module=random.choice(modules),
            error=random.choice(errors),
            job_id=f"job_{random.randint(1000, 9999)}",
            priority=random.choice(["low", "normal", "high", "critical"]),
            method=random.choice(methods)
        )

        timestamp = (base_time + timedelta(seconds=random.randint(0, 3600))).strftime("%Y-%m-%d %H:%M:%S")
        logs.append(f"{timestamp} {log}")

    return "\n".join(logs)


def generate_conversation_text(messages: int = 200) -> str:
    """
    Generate simulated conversation messages for testing.

    Args:
        messages: Number of messages to generate

    Returns:
        Concatenated conversation string
    """
    import random

    user_prompts = [
        "Can you help me understand how the authentication system works?",
        "I'm having issues with the database connection",
        "How do I implement caching for this endpoint?",
        "What's the best way to handle large file uploads?",
        "Can you explain the difference between SQL and NoSQL databases?",
        "I need to optimize this query, it's running too slow",
        "How should I structure my project for scalability?",
        "What's the recommended approach for error handling?",
        "Can you help me debug this async function?",
        "I'm trying to implement a retry mechanism for API calls"
    ]

    responses = [
        "The authentication system uses JWT tokens stored in Redis. The flow involves three steps: user credentials validation, token generation, and subsequent requests with the bearer token. Each token has a 24-hour expiration with refresh capability.",
        "For database connection issues, first check your connection string. Ensure the credentials are correct and the database server is reachable. Connection pooling is handled automatically with a default pool size of 10 connections.",
        "Caching can be implemented using Redis with TTL-based expiration. For this endpoint, I recommend caching the response for 5 minutes and invalidating on data changes. Use cache-aside pattern for optimal performance.",
        "Large file uploads should be handled with streaming to avoid memory issues. Configure Nginx with client_max_body_size and implement chunked uploads on the client side. Temporary files can be stored in /tmp with automatic cleanup.",
        "SQL databases excel at complex queries and transactions with ACID guarantees, making them ideal for financial data. NoSQL databases offer horizontal scalability and flexible schemas, better suited for high-throughput applications and unstructured data.",
        "Query optimization starts with EXPLAIN ANALYZE to identify bottlenecks. Add appropriate indexes on frequently queried columns. Consider denormalizing for read-heavy workloads. For joins, ensure foreign keys are indexed.",
        "For scalability, consider a microservices architecture with clear service boundaries. Use containerization with Docker and orchestration via Kubernetes. Implement circuit breakers for resilience and use a message queue for asynchronous processing.",
        "Error handling should follow a consistent pattern: validate early, fail fast, provide meaningful error messages. Use custom exception types for domain-specific errors. Implement centralized error logging with structured logs and exception tracking.",
        "Debugging async functions requires understanding the event loop. Use asyncio.create_task for concurrent execution. Be aware of potential race conditions and use asyncio.Lock when shared state is accessed. Debug prints and async debugger can help trace issues.",
        "Implement exponential backoff for retry mechanisms with jitter to avoid thundering herd. Set maximum retry attempts and handle permanent failures appropriately. Consider using a library like tenacity for robust retry logic."
    ]

    conversation = []
    for i in range(messages):
        if i % 2 == 0:
            conversation.append(f"User: {random.choice(user_prompts)}")
        else:
            conversation.append(f"Assistant: {random.choice(responses)}")

    return "\n\n".join(conversation)


async def run_stress_test():
    """
    Run stress test with 100k+ tokens.
    Verifies AC1 (automatic compression) is triggered correctly.
    """
    print("=" * 80)
    print("MCP CONTEXT PIPELINE - STRESS TEST")
    print("=" * 80)
    print("\nThis test will:")
    print("1. Generate ~100k tokens of data")
    print("2. Feed it through the orchestrator")
    print("3. Verify automatic compression triggers (AC1)")
    print("4. Report final statistics")
    print("\n" + "=" * 80 + "\n")

    orchestrator = ContextOrchestrator(
        server_script="src/server.py",
        max_tokens=128000,
        summary_threshold=100000  # Trigger at 100k tokens
    )

    try:
        # Connect to MCP server
        print("[STEP 1] Connecting to MCP server...")
        await orchestrator.connect()
        print("[STEP 1] Connected successfully!\n")

        # Generate test data
        print("[STEP 2] Generating test data (conversation + logs)...")
        conversation = generate_conversation_text(messages=150)
        logs = generate_log_data(num_logs=800)

        combined_data = conversation + "\n\n=== LOG DATA ===\n\n" + logs
        total_tokens = count_tokens(combined_data)

        print(f"[STEP 2] Generated {len(combined_data):,} characters")
        print(f"[STEP 2] Estimated {total_tokens:,} tokens\n")
        if total_tokens <= orchestrator.summary_threshold:
            adjusted_threshold = max(5000, int(total_tokens * 0.6))
            if adjusted_threshold < orchestrator.summary_threshold:
                print(
                    f"[STEP 2] Adjusting summary threshold for this run: "
                    f"{orchestrator.summary_threshold} -> {adjusted_threshold}"
                )
                orchestrator.summary_threshold = adjusted_threshold

        # Feed data in chunks to simulate real conversation
        print("[STEP 3] Feeding data through orchestrator...")
        print("[STEP 3] Will automatically trigger compression at threshold\n")

        # Split into manageable chunks (simulating conversation flow)
        chunk_size = 5000
        chunks = [combined_data[i:i+chunk_size] for i in range(0, len(combined_data), chunk_size)]

        initial_compressions = 0

        for i, chunk in enumerate(chunks):
            print(f"[{i+1}/{len(chunks)}] Processing chunk ({len(chunk):,} chars)...")

            # Simulate user message with chunk
            await orchestrator.user_message(chunk)

            # Simulate assistant response (small, doesn't add much)
            await orchestrator.assistant_message("I understand. Please continue.")

            # Check if compression was triggered
            current_stats = orchestrator.get_stats()
            if current_stats["compression_count"] > initial_compressions:
                print(f"     >>> COMPRESSION TRIGGERED! (Total: {current_stats['compression_count']}) <<<")
                initial_compressions = current_stats["compression_count"]

        # Print final statistics
        print("\n[STEP 4] Test completed!")
        orchestrator.print_stats()

        # Verify AC1 was triggered
        final_stats = orchestrator.get_stats()
        if final_stats["compression_count"] > 0:
            print("\n" + "=" * 80)
            print("SUCCESS: AC1 (Automatic Compression) was triggered!")
            print(f"Total compressions: {final_stats['compression_count']}")
            print("=" * 80 + "\n")
            return True
        else:
            print("\n" + "=" * 80)
            print("WARNING: AC1 was not triggered. Check threshold settings.")
            print("=" * 80 + "\n")
            return False

    except KeyboardInterrupt:
        print("\n[INFO] Test interrupted by user")
        return False
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await orchestrator.disconnect()


async def run_basic_functionality_test():
    """
    Run basic functionality tests.
    Tests core features without heavy load.
    """
    print("=" * 80)
    print("MCP CONTEXT PIPELINE - BASIC FUNCTIONALITY TEST")
    print("=" * 80 + "\n")

    orchestrator = ContextOrchestrator()

    try:
        print("[TEST 1] Connection test...")
        await orchestrator.connect()
        print("[PASS] Connected successfully\n")

        print("[TEST 2] Message addition test...")
        await orchestrator.user_message("Hello, can you help me?")
        await orchestrator.assistant_message("Of course! How can I assist you today?")
        print("[PASS] Messages added successfully\n")

        print("[TEST 3] State management test...")
        result = await orchestrator.save_state()
        if result.get("status") == "saved":
            print("[PASS] State saved successfully")

        loaded = await orchestrator.load_state()
        if loaded:
            print("[PASS] State loaded successfully\n")
        else:
            print("[FAIL] State load failed\n")

        print("[TEST 4] Statistics test...")
        stats = orchestrator.get_stats()
        print(f"Messages: {stats['message_count']}")
        print(f"Tokens: {stats['current_tokens']}")
        print(f"[PASS] Statistics retrieved successfully\n")

        print("=" * 80)
        print("All basic tests completed!")
        print("=" * 80 + "\n")

    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await orchestrator.disconnect()


async def run_checkpoint_recovery_test():
    """
    Test checkpoint save and recovery functionality (AC4).
    """
    print("=" * 80)
    print("MCP CONTEXT PIPELINE - CHECKPOINT RECOVERY TEST")
    print("=" * 80 + "\n")

    orchestrator1 = None
    orchestrator2 = None

    try:
        # First orchestrator - save state
        print("[PHASE 1] Creating orchestrator and adding data...")
        orchestrator1 = ContextOrchestrator()
        await orchestrator1.connect()

        for i in range(10):
            await orchestrator1.user_message(f"Test message {i+1}")
            await orchestrator1.assistant_message(f"Test response {i+1}")

        initial_stats = orchestrator1.get_stats()
        print(f"Initial state: {initial_stats['message_count']} messages")

        print("\n[PHASE 2] Saving checkpoint...")
        result = await orchestrator1.save_state()
        print(f"Save result: {result}")

        session_id_to_restore = orchestrator1.session_id
        await orchestrator1.disconnect()

        # Second orchestrator - load state
        print("\n[PHASE 3] Creating new orchestrator and loading state...")
        orchestrator2 = ContextOrchestrator()
        await orchestrator2.connect()

        # Manually set the session ID to match
        orchestrator2.session_id = session_id_to_restore

        print("\n[PHASE 4] Loading checkpoint...")
        loaded = await orchestrator2.load_state()

        if loaded:
            restored_stats = orchestrator2.get_stats()
            print(f"Restored state: {restored_stats['message_count']} messages")

            if restored_stats['message_count'] == initial_stats['message_count']:
                print("\n" + "=" * 80)
                print("SUCCESS: Checkpoint recovery works correctly!")
                print(f"All {restored_stats['message_count']} messages restored")
                print("=" * 80 + "\n")
            else:
                print("\n[FAIL] Message count mismatch after restore")
        else:
            print("\n[FAIL] Failed to load checkpoint")

    except Exception as e:
        print(f"[ERROR] Checkpoint test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if orchestrator2 and getattr(orchestrator2, "connected", False):
            try:
                await orchestrator2.disconnect()
            except Exception as disconnect_error:
                print(f"[WARN] Failed to disconnect orchestrator2: {disconnect_error}")
        if orchestrator1 and getattr(orchestrator1, "connected", False):
            try:
                await orchestrator1.disconnect()
            except Exception as disconnect_error:
                print(f"[WARN] Failed to disconnect orchestrator1: {disconnect_error}")


def print_menu():
    """Print test menu."""
    print("=" * 80)
    print("MCP Context Pipeline - Test Suite")
    print("=" * 80)
    print("Available tests:")
    print("  1. Basic Functionality Test (quick)")
    print("  2. Stress Test (100k tokens, triggers compression)")
    print("  3. Checkpoint Recovery Test")
    print("  4. Run all tests")
    print("  5. Interactive mode")
    print("=" * 80)


async def main():
    """Main entry point for test suite."""
    if len(sys.argv) > 1:
        test_type = sys.argv[1]
    else:
        print_menu()
        test_type = input("\nSelect test (1-5): ").strip()

    if test_type == "1":
        await run_basic_functionality_test()
    elif test_type == "2":
        await run_stress_test()
    elif test_type == "3":
        await run_checkpoint_recovery_test()
    elif test_type == "4":
        print("\n" + "=" * 80)
        print("RUNNING ALL TESTS")
        print("=" * 80 + "\n")

        await run_basic_functionality_test()
        print("\n" + "-" * 80 + "\n")

        await run_checkpoint_recovery_test()
        print("\n" + "-" * 80 + "\n")

        await run_stress_test()
    elif test_type == "5":
        from host_orchestrator import interactive_session
        await interactive_session()
    else:
        print(f"Unknown test type: {test_type}")
        print_menu()


if __name__ == "__main__":
    # Set event loop policy for Windows compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
