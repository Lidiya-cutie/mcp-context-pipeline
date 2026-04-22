"""
Quick test to verify compression is working with lower threshold.
"""

import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from host_orchestrator import ContextOrchestrator
from utils import count_tokens


def generate_large_text(target_tokens: int = 50000) -> str:
    """
    Generate text to reach target token count.

    Args:
        target_tokens: Target number of tokens

    Returns:
        Generated text
    """
    paragraphs = []

    # Technical content templates
    templates = [
        """The system architecture consists of multiple microservices communicating via REST APIs and message queues.
The authentication service handles JWT token generation and validation with Redis-based session management.
The user service stores profile data in PostgreSQL with connection pooling for optimal performance.""",
        """Database optimization strategies include proper indexing, query planning, and denormalization where appropriate.
Redis caching reduces database load by 80% for frequently accessed data.
Connection pooling with a maximum of 20 connections prevents connection exhaustion.""",
        """Error handling follows a consistent pattern: validate input, catch specific exceptions, log structured data,
and return appropriate HTTP status codes. Custom exceptions domain-specific error types.
Circuit breaker pattern prevents cascading failures in distributed systems.""",
        """Container orchestration via Kubernetes ensures scalability and fault tolerance.
Horizontal pod autoscaling adjusts replica count based on CPU/memory metrics.
Rolling updates enable zero-downtime deployments of new versions.""",
        """Monitoring stack includes Prometheus for metrics collection, Grafana for visualization,
and AlertManager for notifications. Logs are centralized using ELK stack.
Distributed tracing with Jaeger helps identify performance bottlenecks."""
    ]

    current_tokens = 0
    while current_tokens < target_tokens:
        paragraph = templates[len(paragraphs) % len(templates)]
        paragraphs.append(paragraph)
        current_tokens += count_tokens(paragraph)

    return "\n\n".join(paragraphs)


async def run_compression_test():
    """
    Test compression with lower threshold.
    """
    print("=" * 80)
    print("MCP CONTEXT PIPELINE - COMPRESSION TEST")
    print("=" * 80)
    print("\nThis test will:")
    print("1. Generate ~30k tokens of data")
    print("2. Set compression threshold to 15k tokens")
    print("3. Verify automatic compression triggers")
    print("4. Test Anthropic API summarization")
    print("\n" + "=" * 80 + "\n")

    orchestrator = ContextOrchestrator(
        server_script="src/server.py",
        max_tokens=128000,
        summary_threshold=15000  # Lower threshold for testing
    )

    try:
        # Connect to MCP server
        print("[STEP 1] Connecting to MCP server...")
        await orchestrator.connect()
        print("[STEP 1] Connected successfully!\n")

        # Generate test data
        print("[STEP 2] Generating test data (30k tokens)...")
        test_data = generate_large_text(target_tokens=30000)
        total_tokens = count_tokens(test_data)

        print(f"[STEP 2] Generated {len(test_data):,} characters")
        print(f"[STEP 2] Estimated {total_tokens:,} tokens\n")

        # Feed data in chunks
        print("[STEP 3] Feeding data through orchestrator (threshold: 15k tokens)...")
        print("[STEP 3] Compression should trigger at 15k tokens\n")

        chunk_size = 3000
        chunks = [test_data[i:i+chunk_size] for i in range(0, len(test_data), chunk_size)]

        initial_compressions = 0

        for i, chunk in enumerate(chunks):
            print(f"[{i+1}/{len(chunks)}] Processing chunk ({len(chunk):,} chars)...")

            # Simulate user message with chunk
            await orchestrator.user_message(chunk)

            # Simulate assistant response
            await orchestrator.assistant_message("I understand. Please continue.")

            # Check if compression was triggered
            current_stats = orchestrator.get_stats()
            if current_stats["compression_count"] > initial_compressions:
                print(f"     >>> COMPRESSION TRIGGERED! (Total: {current_stats['compression_count']}) <<<")
                initial_compressions = current_stats["compression_count"]
                break  # Stop after first compression

        # Print final statistics
        print("\n[STEP 4] Test completed!")
        orchestrator.print_stats()

        # Verify compression was triggered
        final_stats = orchestrator.get_stats()
        if final_stats["compression_count"] > 0:
            print("\n" + "=" * 80)
            print("SUCCESS: AC1 (Automatic Compression) was triggered!")
            print(f"Total compressions: {final_stats['compression_count']}")
            print(f"Used Anthropic Claude API: claude-sonnet-4-20250514")
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


if __name__ == "__main__":
    # Set event loop policy for Windows compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(run_compression_test())
