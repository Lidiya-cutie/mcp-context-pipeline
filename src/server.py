"""
MCP Server for Context Management.
Implements Tools and Resources for context compression, memory management,
and session state handling.

Supports both OpenAI and Anthropic Claude APIs for summarization.
SECURITY: Includes automatic PII masking using Microsoft Presidio.
"""

import asyncio
import json
import hashlib
import os
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv

try:
    from .utils import count_tokens
except ImportError:
    from utils import count_tokens

# Load environment variables
load_dotenv()

# Redis import for Redis manager
try:
    from .redis_manager import RedisManager
except ImportError:
    from redis_manager import RedisManager
from concurrent.futures import ThreadPoolExecutor

# MCP imports
from mcp.server.fastmcp import FastMCP

# Initialize MCP server
mcp = FastMCP("Context-Manager-Server")

# Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()  # Default: anthropic
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ENABLE_PII_MASKING = os.getenv("ENABLE_PII_MASKING", "true").lower() == "true"

# Initialize connections (lazy connect in real production)
# Redis for sessions and cache (Memory Service)
redis_client = None
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

# LLM clients (lazy initialization)
llm_client = None
secure_middleware = None
anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY")

# Redis import (moved to top level)
import redis

# Translator import
try:
    from .translator import translate_en_to_ru, get_translator
except ImportError:
    from translator import translate_en_to_ru, get_translator

# Lazy initialization helpers
def get_redis_client():
    """Get or initialize Redis connection."""
    global redis_client
    if redis_client is None:
        try:
            # Используем redis-py вместо redis.asyncio для совместимости с Docker
            redis_client = redis.Redis(
                host='localhost',
                port=6379,
                db=0,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5
            )
            redis_client.ping()
            print(f"[INFO] Connected to Redis at localhost:6379")
        except Exception as e:
            print(f"[ERROR] Failed to connect to Redis: {e}")
            redis_client = None
    return redis_client

# Helper для синхронных вызовов Redis в async контексте
async def redis_set(key: str, value: str, ttl: int = 86400):
    """Синхронная установка значения в Redis."""
    if redis_client is None:
        raise Exception("Redis client not available")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, redis_client.set, key, value)
    if ttl > 0:
        await loop.run_in_executor(None, redis_client.expire, key, ttl)

async def redis_get(key: str):
    """Синхронное получение значения из Redis."""
    if redis_client is None:
        raise Exception("Redis client not available")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: redis_client.get(key))

async def redis_hset(key: str, mapping: dict, ttl: int = 86400):
    """Синхронная установка хэша в Redis."""
    if redis_client is None:
        raise Exception("Redis client not available")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: redis_client.hset(key, mapping=mapping))
    if ttl > 0:
        await loop.run_in_executor(None, lambda: redis_client.expire(key, ttl))

async def redis_hgetall(key: str):
    """Синхронное получение хэша из Redis."""
    if redis_client is None:
        raise Exception("Redis client not available")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: redis_client.hgetall(key))

async def redis_exists(key: str):
    """Синхронная проверка существования ключа в Redis."""
    if redis_client is None:
        return False
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: redis_client.exists(key))

async def redis_hlen(key: str):
    """Синхронное получение длины хэша из Redis."""
    if redis_client is None:
        return 0
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: redis_client.hlen(key))

async def redis_ping():
    """Синхронный пинг Redis."""
    if redis_client is None:
        return False
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: redis_client.ping())


def get_llm_client():
    """
    Get or initialize LLM client based on provider.
    Supports both Anthropic Claude and OpenAI APIs.
    """
    global llm_client

    if llm_client is not None:
        return llm_client

    try:
        proxy_url = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("ALL_PROXY")

        if LLM_PROVIDER == "anthropic":
            if not anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY not set in environment")

            try:
                from anthropic import AsyncAnthropic

                kwargs = {"api_key": anthropic_api_key}
                if proxy_url:
                    try:
                        import httpx
                        proxies = {"http://": proxy_url, "https://": proxy_url}
                        kwargs["http_client"] = httpx.AsyncClient(proxies=proxies, timeout=60.0)
                        print(f"[INFO] Anthropic Claude client with proxy: {proxy_url}")
                    except ImportError:
                        print("[WARN] httpx not installed, proxy will not be used")

                llm_client = AsyncAnthropic(**kwargs)
                if not proxy_url:
                    print(f"[INFO] Anthropic Claude client initialized (model: {ANTHROPIC_MODEL})")
            except ImportError:
                print("[ERROR] anthropic package not installed. Install with: pip install anthropic")
                raise

        elif LLM_PROVIDER == "openai":
            if not openai_api_key:
                raise ValueError("OPENAI_API_KEY not set in environment")

            try:
                from openai import AsyncOpenAI

                kwargs = {"api_key": openai_api_key}
                if proxy_url:
                    try:
                        import httpx
                        proxies = {"http://": proxy_url, "https://": proxy_url}
                        kwargs["http_client"] = httpx.AsyncClient(proxies=proxies, timeout=60.0)
                        print(f"[INFO] OpenAI client with proxy: {proxy_url}")
                    except ImportError:
                        print("[WARN] httpx not installed, proxy will not be used")

                llm_client = AsyncOpenAI(**kwargs)
                if not proxy_url:
                    print(f"[INFO] OpenAI client initialized (model: {OPENAI_MODEL})")
            except ImportError:
                print("[ERROR] openai package not installed. Install with: pip install openai")
                raise

        else:
            raise ValueError(f"Unsupported LLM_PROVIDER: {LLM_PROVIDER}. Use 'anthropic' or 'openai'")

    except Exception as e:
        print(f"[ERROR] Failed to initialize LLM client: {e}")
        raise

    return llm_client


def get_secure_middleware():
    """
    Get or initialize Secure LLM Middleware with PII protection.
    """
    global secure_middleware

    if secure_middleware is not None:
        return secure_middleware

    try:
        from secure_middleware import SecureLLMMiddleware

        api_key = anthropic_api_key if LLM_PROVIDER == "anthropic" else openai_api_key
        model = ANTHROPIC_MODEL if LLM_PROVIDER == "anthropic" else OPENAI_MODEL

        secure_middleware = SecureLLMMiddleware(
            provider=LLM_PROVIDER,
            api_key=api_key,
            model=model,
            enable_logging=True
        )

        print(f"[INFO] Secure LLM Middleware initialized (Provider: {LLM_PROVIDER})")

    except Exception as e:
        print(f"[ERROR] Failed to initialize Secure Middleware: {e}")
        print("[WARN] Falling back to direct LLM client (PII masking disabled)")

    return secure_middleware


async def call_llm_for_summary(text: str, system_message: str, language: str = "ru") -> str:
    """
    Call LLM for text summarization using the configured provider.
    Automatically masks PII if ENABLE_PII_MASKING is true.

    Args:
        text: Text to summarize
        system_message: System prompt for summarization
        language: Language for PII detection

    Returns:
        Generated summary
    """
    # Check for fallback mode (for testing without valid API key)
    fallback_mode = os.getenv("FALLBACK_SUMMARY", "false").lower() == "true"

    # Check API key availability
    if LLM_PROVIDER == "anthropic" and not anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in environment")
    elif LLM_PROVIDER == "openai" and not openai_api_key:
        raise ValueError("OPENAI_API_KEY not set in environment")

    if fallback_mode:
        return _create_fallback_summary(text)

    # Use secure middleware if PII masking is enabled
    if ENABLE_PII_MASKING:
        try:
            middleware = get_secure_middleware()
            if middleware:
                print("[SECURITY] Using Secure Middleware with PII masking")
                return await middleware.summarize(text, language=language)
        except Exception as e:
            print(f"[WARN] Secure Middleware failed, falling back to direct LLM: {e}")

    # Fallback to direct LLM client
    print("[WARN] Using direct LLM client (PII masking disabled)")
    llm = get_llm_client()

    try:
        if LLM_PROVIDER == "anthropic":
            response = await llm.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=2000,
                temperature=0.3,
                system=system_message,
                messages=[
                    {"role": "user", "content": text}
                ]
            )
            return response.content[0].text

        elif LLM_PROVIDER == "openai":
            response = await llm.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": text}
                ],
                max_tokens=2000,
                temperature=0.3
            )
            return response.choices[0].message.content

        else:
            raise ValueError(f"Unsupported provider: {LLM_PROVIDER}")
    except Exception as e:
        print(f"[ERROR] LLM call failed: {e}")
        return _create_fallback_summary(text)


def _create_fallback_summary(text: str) -> str:
    """Create a simple fallback summary when LLM is not available."""
    words = text.split()
    preview = " ".join(words[:30])
    return f"[FALLBACK SUMMARY] {preview}..."


# ==================== RESOURCES (AC3) ====================

@mcp.resource("time://current")
def get_current_time_resource() -> str:
    """
    Resource for injecting current timestamp into System Prompt.
    Provides temporal context for the agent.
    """
    return f"Current timestamp: {datetime.now(timezone.utc).isoformat()}"


@mcp.resource("context://limits")
def get_limits() -> str:
    """
    Resource providing context limits configuration.
    Used by host to understand compression thresholds.
    """
    limits = {
        "max_tokens": int(os.getenv("MAX_TOKENS", "128000")),
        "summary_threshold": int(os.getenv("SUMMARY_THRESHOLD", "100000")),
        "chunk_size": int(os.getenv("CHUNK_SIZE", "500")),
        "llm_provider": LLM_PROVIDER,
        "model": ANTHROPIC_MODEL if LLM_PROVIDER == "anthropic" else OPENAI_MODEL
    }
    return json.dumps(limits, indent=2)


@mcp.resource("system://prompt")
def get_system_prompt() -> str:
    """
    Base system prompt resource.
    Can be extended with dynamic content.
    """
    base_prompt = """You are a helpful assistant with context management capabilities.
When conversation becomes long, you will receive summaries of previous context.
Use these summaries to maintain continuity while focusing on current tasks."""
    return base_prompt


# ==================== TOOLS (AC2, AC4) ====================

@mcp.tool()
async def compress_context(messages: List[str], session_id: str, model: Optional[str] = None) -> Dict[str, Any]:
    """
    Tool for proactive context compression by the agent (AC2).
    Compresses messages and saves to Memory (AC4).

    Supports both Anthropic Claude and OpenAI APIs.

    Args:
        messages: List of message texts to compress
        session_id: Session identifier
        model: Optional override model (uses default if not specified)

    Returns:
        Dictionary with compression status, memory_id, and summary preview
    """
    try:
        redis = get_redis_client()

        if redis is None:
            raise Exception("Redis client not available. Redis connection required for context compression.")

        text_block = "\n\n".join(messages)

        print(f"[INFO] Compressing {len(messages)} messages for session {session_id}")

        language = "ru"
        print(f"[INFO] PII masking enabled: {ENABLE_PII_MASKING}, Language: {language}")

        system_message = """Summarize the following text concisely while preserving:
- Key technical details and decisions
- Action items and next steps
- Important context that should be remembered

Focus on information that would be useful for continuing the conversation later."""

        summary = await call_llm_for_summary(text_block, system_message, language=language)
        summary_tokens = count_tokens(summary)

        memory_id = hashlib.sha256(f"{session_id}_{summary}".encode()).hexdigest()[:16]

        memory_data = {
            "summary": summary,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "original_tokens": str(count_tokens(text_block)),
            "summary_tokens": str(summary_tokens),
            "compression_ratio": f"{summary_tokens / max(count_tokens(text_block), 1):.2f}",
            "provider": LLM_PROVIDER,
            "model": model if model else (ANTHROPIC_MODEL if LLM_PROVIDER == "anthropic" else OPENAI_MODEL),
            "pii_masking_enabled": ENABLE_PII_MASKING
        }

        await redis_hset(f"session:{session_id}:memory", mapping={memory_id: json.dumps(memory_data)}, ttl=86400)

        print(f"[SUCCESS] Context compressed. Memory ID: {memory_id}, Compression: {memory_data['compression_ratio']}")

        return {
            "status": "compressed",
            "memory_id": memory_id,
            "summary_preview": summary[:200],
            "original_tokens": count_tokens(text_block),
            "summary_tokens": summary_tokens,
            "compression_ratio": memory_data["compression_ratio"],
            "provider": LLM_PROVIDER,
            "model": memory_data["model"],
            "pii_masking_enabled": ENABLE_PII_MASKING
        }

    except Exception as e:
        print(f"[ERROR] Context compression failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "error": str(e),
            "memory_id": None
        }


@mcp.tool()
async def save_checkpoint(session_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save session state checkpoint (AC4).
    Enables resuming conversations from saved states.

    Args:
        session_id: Session identifier
        state: Dictionary containing session state

    Returns:
        Confirmation of checkpoint save
    """
    try:
        redis = get_redis_client()

        if redis is None:
            return {
                "status": "error",
                "error": "Redis client not available"
            }

        key = f"checkpoint:{session_id}"
        checkpoint_data = {
            "state": state,
            "saved_at": datetime.now(timezone.utc).isoformat()
        }

        await redis_set(key, json.dumps(checkpoint_data), ttl=604800)  # TTL 7 days

        print(f"[INFO] Checkpoint saved for session {session_id}")

        return {
            "status": "saved",
            "session_id": session_id,
            "saved_at": checkpoint_data["saved_at"]
        }

    except Exception as e:
        print(f"[ERROR] Checkpoint save failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@mcp.tool()
async def load_checkpoint(session_id: str) -> Dict[str, Any]:
    """
    Restore session state from checkpoint (AC4).

    Args:
        session_id: Session identifier

    Returns:
        Saved session state or empty dict if not found
    """
    try:
        redis = get_redis_client()

        if redis is None:
            return {
                "status": "error",
                "error": "Redis client not available",
                "state": {}
            }

        key = f"checkpoint:{session_id}"
        data = await redis_get(key)

        if data:
            checkpoint = json.loads(data)
            print(f"[INFO] Checkpoint loaded for session {session_id}")
            return {
                "status": "loaded",
                "session_id": session_id,
                "state": checkpoint.get("state", {}),
                "saved_at": checkpoint.get("saved_at")
            }
        else:
            print(f"[WARN] No checkpoint found for session {session_id}")
            return {
                "status": "not_found",
                "session_id": session_id,
                "state": {}
            }

    except Exception as e:
        print(f"[ERROR] Checkpoint load failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "state": {}
        }


@mcp.tool()
async def search_memory(query: str, session_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Semantic search through memory (simplified via Redis pattern matching).
    In production, this would use VectorDB (Qdrant/Pinecone).

    Args:
        query: Search query string
        session_id: Session identifier
        limit: Maximum number of results to return

    Returns:
        List of matching memory entries
    """
    try:
        redis = get_redis_client()

        if redis is None:
            return []

        pattern = f"session:{session_id}:memory"
        results = []

        # Scan for memory keys
        async for key in redis.scan_iter(match=pattern):
            memory_entries = await redis_hgetall(key)

            for memory_id, memory_json in memory_entries.items():
                try:
                    memory_data = json.loads(memory_json)

                    # Simple text matching (in production: use vector similarity)
                    summary = memory_data.get("summary", "")
                    if query.lower() in summary.lower():
                        results.append({
                            "memory_id": memory_id,
                            "summary": summary,
                            "timestamp": memory_data.get("timestamp"),
                            "compression_ratio": memory_data.get("compression_ratio"),
                            "provider": memory_data.get("provider")
                        })

                        if len(results) >= limit:
                            break

                except json.JSONDecodeError:
                    continue

            if len(results) >= limit:
                break

        print(f"[INFO] Found {len(results)} memory entries matching query")

        return results

    except Exception as e:
        print(f"[ERROR] Memory search failed: {e}")
        return []


@mcp.tool()
async def get_session_info(session_id: str) -> Dict[str, Any]:
    """
    Get information about a session including memory entries and checkpoints.

    Args:
        session_id: Session identifier

    Returns:
        Session information
    """
    try:
        redis = get_redis_client()

        # Check for memory
        memory_key = f"session:{session_id}:memory"
        memory_exists = await redis_exists(memory_key)
        memory_count = await redis_hlen(memory_key) if memory_exists else 0

        # Check for checkpoint
        checkpoint_key = f"checkpoint:{session_id}"
        checkpoint_exists = await redis_exists(checkpoint_key)

        return {
            "session_id": session_id,
            "has_memory": bool(memory_exists),
            "memory_entries": memory_count,
            "has_checkpoint": bool(checkpoint_exists)
        }

    except Exception as e:
        print(f"[ERROR] Failed to get session info: {e}")
        return {
            "session_id": session_id,
            "error": str(e)
        }


@mcp.tool()
async def query_docs_with_translation(
    library_id: str,
    query: str,
    translate: bool = True
) -> Dict[str, Any]:
    """
    Query documentation from libraries with optional translation to Russian.

    Args:
        library_id: Library identifier (e.g., '/fastapi/fastapi', '/pytorch/pytorch')
        query: Search query for documentation
        translate: Whether to translate results to Russian (default: True)

    Returns:
        Dictionary with documentation content and translation status
    """
    try:
        translator = get_translator()

        if not translator.enabled or not translate:
            return {
                "status": "not_translated",
                "content": None,
                "message": "Translation disabled or not available"
            }

        result = {
            "status": "success",
            "translation_enabled": translator.enabled,
            "library_id": library_id,
            "query": query,
            "message": "Context7 integration available via separate client"
        }

        return result

    except Exception as e:
        print(f"[ERROR] Documentation query failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


# ==================== MAIN ENTRY POINT ====================

async def check_connections():
    """Check if all required services are available."""
    try:
        redis = get_redis_client()
        result = await redis_ping()
        print("[INFO] Redis connection verified")

        # Check LLM client based on provider
        if LLM_PROVIDER == "anthropic":
            if anthropic_api_key:
                print(f"[INFO] ANTHROPIC_API_KEY set - compression features available")
            else:
                print("[WARN] ANTHROPIC_API_KEY not set - compression features will fail")
        elif LLM_PROVIDER == "openai":
            if openai_api_key:
                print(f"[INFO] OPENAI_API_KEY set - compression features available")
            else:
                print("[WARN] OPENAI_API_KEY not set - compression features will fail")

        return True
    except Exception as e:
        print(f"[ERROR] Connection check failed: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("MCP Context Manager Server Starting...")
    print("=" * 60)
    print(f"[INFO] LLM Provider: {LLM_PROVIDER}")
    print(f"[INFO] Model: {ANTHROPIC_MODEL if LLM_PROVIDER == 'anthropic' else OPENAI_MODEL}")

    # Run connection checks
    try:
        asyncio.run(check_connections())
    except Exception as e:
        print(f"[WARN] Initial connection check failed: {e}")
        print("[INFO] Server will start anyway, but features may be limited")

    print("[INFO] Starting MCP server on stdio...")
    print("[INFO] Press Ctrl+C to stop")

    # Start MCP server
    mcp.run()
