#!/usr/bin/env python3
"""
Quick verification script to check if MCP Context Pipeline is set up correctly.
This script verifies:
1. Docker containers are running
2. Python dependencies are installed
3. Basic connectivity to services
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


def check_python_dependencies():
    """Check if all required Python packages are installed."""
    print("=" * 60)
    print("Checking Python Dependencies...")
    print("=" * 60)

    dependencies = [
        ('mcp', 'MCP'),
        ('tiktoken', 'Tiktoken'),
        ('openai', 'OpenAI'),
    ]

    all_ok = True
    for module, name in dependencies:
        try:
            __import__(module)
            print(f"  [OK] {name}")
        except ImportError:
            print(f"  [FAIL] {name} - NOT INSTALLED")
            all_ok = False

    # Check optional dependencies
    optional = [
        ('presidio_analyzer', 'Presidio Analyzer'),
        ('presidio_anonymizer', 'Presidio Anonymizer'),
        ('spacy', 'spaCy'),
    ]

    print("\nOptional Dependencies:")
    for module, name in optional:
        try:
            __import__(module)
            print(f"  [OK] {name}")
        except ImportError:
            print(f"  [WARN] {name} - NOT INSTALLED (PII masking will be limited)")

    return all_ok


def check_docker_containers():
    """Check if Docker containers are running."""
    import subprocess

    print("\n" + "=" * 60)
    print("Checking Docker Containers...")
    print("=" * 60)

    try:
        # Check docker compose ps
        result = subprocess.run(
            ['docker', 'compose', 'ps'],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(__file__)
        )

        if result.returncode == 0:
            print("  [OK] Docker compose is working")

            # Check for redis and postgres
            if 'redis' in result.stdout.lower():
                print("  [OK] Redis container found")
            else:
                print("  [FAIL] Redis container NOT found")

            if 'postgres' in result.stdout.lower():
                print("  [OK] PostgreSQL container found")
            else:
                print("  [FAIL] PostgreSQL container NOT found")

            return True
        else:
            print(f"  [FAIL] Docker compose failed: {result.stderr}")
            return False

    except Exception as e:
        print(f"  [FAIL] Error checking Docker: {e}")
        return False


def check_redis_connection():
    """Check Redis connectivity."""
    print("\n" + "=" * 60)
    print("Checking Redis Connection...")
    print("=" * 60)

    try:
        import redis

        r = redis.Redis(host='localhost', port=6379, decode_responses=True)
        r.ping()
        print("  [OK] Redis connection successful")
        return True
    except Exception as e:
        print(f"  [FAIL] Redis connection failed: {e}")
        return False


def check_postgres_connection():
    """Check PostgreSQL connectivity."""
    print("\n" + "=" * 60)
    print("Checking PostgreSQL Connection...")
    print("=" * 60)

    try:
        import psycopg2

        conn = psycopg2.connect(
            host='localhost',
            port=5433,
            user='mcp_user',
            password='mcp_password',
            dbname='mcp_memory'
        )
        conn.close()
        print("  [OK] PostgreSQL connection successful")
        return True
    except ImportError:
        print("  [WARN] psycopg2 not installed (optional)")
        return True  # Not critical
    except Exception as e:
        print(f"  [FAIL] PostgreSQL connection failed: {e}")
        return False


def check_utils():
    """Check utility functions."""
    print("\n" + "=" * 60)
    print("Checking Utility Functions...")
    print("=" * 60)

    try:
        from utils import count_tokens, generate_session_id

        # Test token counting
        test_text = "Hello, world!"
        tokens = count_tokens(test_text)
        print(f"  [OK] Token counting: '{test_text}' = {tokens} tokens")

        # Test session ID generation
        session_id = generate_session_id()
        print(f"  [OK] Session ID generation: {session_id}")

        return True
    except Exception as e:
        print(f"  [FAIL] Utils check failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all verification checks."""
    print("\n" + "=" * 60)
    print("MCP Context Pipeline - Setup Verification")
    print("=" * 60 + "\n")

    results = {
        'Python Dependencies': check_python_dependencies(),
        'Docker Containers': check_docker_containers(),
        'Redis Connection': check_redis_connection(),
        'PostgreSQL Connection': check_postgres_connection(),
        'Utility Functions': check_utils(),
    }

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    all_passed = True
    for check, result in results.items():
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status} {check}")
        if not result:
            all_passed = False

    print("=" * 60)

    if all_passed:
        print("\n✓ All checks passed! The pipeline is ready to use.")
        print("\nNext steps:")
        print("  1. Create .env file with your OPENAI_API_KEY")
        print("  2. Run: python src/test_pipeline.py 1  (basic test)")
        print("  3. Run: python src/test_pipeline.py 4  (all tests)")
        return 0
    else:
        print("\n✗ Some checks failed. Please fix the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
