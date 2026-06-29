#!/usr/bin/env python3
"""Anthropic Messages API MCP server — stdio transport, stdlib only."""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import hmac

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_state = {
    "last_rate_limit": None,
    "last_usage": None,
    "last_request_time": 0.0,
}

MODELS = {
    "claude-sonnet-4-20250514": {"context": 200000, "input_price": 3.0, "output_price": 15.0},
    "claude-opus-4-20250514": {"context": 200000, "input_price": 15.0, "output_price": 75.0},
    "claude-3-5-sonnet-20241022": {"context": 200000, "input_price": 3.0, "output_price": 15.0},
    "claude-3-5-haiku-20241022": {"context": 200000, "input_price": 0.8, "output_price": 4.0},
    "claude-3-opus-20240229": {"context": 200000, "input_price": 15.0, "output_price": 75.0},
    "claude-3-haiku-20240307": {"context": 200000, "input_price": 0.25, "output_price": 1.25},
}

# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def make_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def send(obj):
    payload = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(payload + "\n")
    sys.stdout.flush()


def read_line():
    return sys.stdin.readline()


# ---------------------------------------------------------------------------
# Anthropic API helpers
# ---------------------------------------------------------------------------

def _api_key():
    return os.environ.get("ANTHROPIC_API_KEY", "")


def _model():
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")


def _max_tokens():
    return int(os.environ.get("ANTHROPIC_MAX_TOKENS", "4096"))


def _parse_rate_headers(headers):
    rl = {}
    for key in headers:
        lk = key.lower()
        if "x-ratelimit" in lk:
            rl[lk] = headers[key]
    return rl if rl else None


def _call_api(messages, model=None, max_tokens=None, stream=False):
    api_key = _api_key()
    if not api_key:
        return None, {"error": "ANTHROPIC_API_KEY not set"}

    url = "https://api.anthropic.com/v1/messages"
    body = {
        "model": model or _model(),
        "max_tokens": max_tokens or _max_tokens(),
        "messages": messages,
    }
    if stream:
        body["stream"] = True

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", api_key)
    req.add_header("anthropic-version", "2023-06-01")

    try:
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            rate = _parse_rate_headers(resp.headers)
            elapsed = time.time() - t0
            _state["last_rate_limit"] = rate
            _state["last_request_time"] = elapsed
            parsed = json.loads(raw)
            _state["last_usage"] = parsed.get("usage")
            return parsed, None
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            err_json = json.loads(err_body)
        except Exception:
            err_json = {"raw": err_body}
        rate = _parse_rate_headers(e.headers) if hasattr(e, "headers") else None
        if rate:
            _state["last_rate_limit"] = rate
        return None, {"status": e.code, "error": err_json}
    except Exception as exc:
        return None, {"error": str(exc)}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def tool_send_message(params):
    message = params.get("message", "")
    system = params.get("system", "")
    model = params.get("model")
    max_tokens = params.get("max_tokens")

    if not message:
        return make_error_tool("message is required")

    msgs = [{"role": "user", "content": message}]
    api_params = {}
    if system:
        api_params["system"] = system

    # We call with messages only; system is not in messages array for Anthropic
    result, err = _call_api(msgs, model=model, max_tokens=max_tokens)
    if err:
        return {"content": [{"type": "text", "text": json.dumps(err, indent=2)}], "isError": True}

    text_blocks = []
    for block in result.get("content", []):
        if block.get("type") == "text":
            text_blocks.append(block["text"])

    usage = result.get("usage", {})
    _state["last_usage"] = usage

    output = {
        "text": "\n".join(text_blocks),
        "model": result.get("model"),
        "stop_reason": result.get("stop_reason"),
        "usage": usage,
    }
    return {"content": [{"type": "text", "text": json.dumps(output, indent=2, ensure_ascii=False)}]}


def tool_send_conversation(params):
    messages = params.get("messages", [])
    system = params.get("system", "")
    model = params.get("model")
    max_tokens = params.get("max_tokens")

    if not messages:
        return {"content": [{"type": "text", "text": "messages array is required"}], "isError": True}

    result, err = _call_api(messages, model=model, max_tokens=max_tokens)
    if err:
        return {"content": [{"type": "text", "text": json.dumps(err, indent=2)}], "isError": True}

    text_blocks = []
    for block in result.get("content", []):
        if block.get("type") == "text":
            text_blocks.append(block["text"])

    usage = result.get("usage", {})
    _state["last_usage"] = usage

    output = {
        "text": "\n".join(text_blocks),
        "model": result.get("model"),
        "stop_reason": result.get("stop_reason"),
        "usage": usage,
    }
    return {"content": [{"type": "text", "text": json.dumps(output, indent=2, ensure_ascii=False)}]}


def tool_count_tokens(params):
    messages = params.get("messages", [])
    text = params.get("text", "")

    total = 0
    if text:
        for ch in text:
            if "\u0400" <= ch <= "\u04FF":
                total += 0.5  # cyrillic: ~2 chars/token
            else:
                total += 0.25  # latin: ~4 chars/token
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            for ch in content:
                if "\u0400" <= ch <= "\u04FF":
                    total += 0.5
                else:
                    total += 0.25
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    for ch in block.get("text", ""):
                        if "\u0400" <= ch <= "\u04FF":
                            total += 0.5
                        else:
                            total += 0.25

    estimated = int(total) if total > 0 else 0
    output = {
        "estimated_tokens": estimated,
        "method": "rough: 4 chars/token latin, 2 chars/token cyrillic",
        "messages_count": len(messages),
    }
    return {"content": [{"type": "text", "text": json.dumps(output, indent=2)}]}


def tool_get_rate_limit(params):
    rl = _state["last_rate_limit"]
    if rl is None:
        output = {"info": "no requests made yet, no rate limit data available"}
    else:
        output = rl
    return {"content": [{"type": "text", "text": json.dumps(output, indent=2)}]}


def tool_list_models(params):
    models = []
    for name, info in MODELS.items():
        models.append({
            "id": name,
            "context_window": info["context"],
            "pricing_per_million_tokens": {
                "input_usd": info["input_price"],
                "output_usd": info["output_price"],
            },
        })
    output = {"models": models, "default": _model()}
    return {"content": [{"type": "text", "text": json.dumps(output, indent=2)}]}


def tool_get_usage(params):
    usage = _state["last_usage"]
    if usage is None:
        output = {"info": "no requests made yet"}
    else:
        output = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        }
    return {"content": [{"type": "text", "text": json.dumps(output, indent=2)}]}


def tool_stream_message(params):
    # Non-streaming fallback: same as send_message but returns chunked metadata
    message = params.get("message", "")
    model = params.get("model")
    max_tokens = params.get("max_tokens")

    if not message:
        return {"content": [{"type": "text", "text": "message is required"}], "isError": True}

    msgs = [{"role": "user", "content": message}]
    result, err = _call_api(msgs, model=model, max_tokens=max_tokens)
    if err:
        return {"content": [{"type": "text", "text": json.dumps(err, indent=2)}], "isError": True}

    text_blocks = []
    for block in result.get("content", []):
        if block.get("type") == "text":
            text_blocks.append(block["text"])

    usage = result.get("usage", {})
    _state["last_usage"] = usage

    output = {
        "text": "\n".join(text_blocks),
        "model": result.get("model"),
        "stop_reason": result.get("stop_reason"),
        "usage": usage,
        "chunks_simulated": len(text_blocks),
        "elapsed_seconds": _state.get("last_request_time", 0),
        "note": "non-streaming fallback used",
    }
    return {"content": [{"type": "text", "text": json.dumps(output, indent=2, ensure_ascii=False)}]}


def tool_check_health(params):
    api_key = _api_key()
    if not api_key:
        output = {"status": "error", "message": "ANTHROPIC_API_KEY not set"}
        return {"content": [{"type": "text", "text": json.dumps(output, indent=2)}], "isError": True}

    # Minimal request to check connectivity and auth
    msgs = [{"role": "user", "content": "ping"}]
    result, err = _call_api(msgs, max_tokens=16)
    if err:
        output = {"status": "error", "details": err}
        return {"content": [{"type": "text", "text": json.dumps(output, indent=2)}], "isError": True}

    output = {
        "status": "ok",
        "api_key_set": True,
        "api_key_prefix": api_key[:8] + "...",
        "model": result.get("model", _model()),
        "response_received": True,
    }
    return {"content": [{"type": "text", "text": json.dumps(output, indent=2)}]}


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "send_message",
        "description": "Send a message to Claude and return response text with usage stats.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "User message text"},
                "system": {"type": "string", "description": "Optional system prompt"},
                "model": {"type": "string", "description": "Model override (default: ANTHROPIC_MODEL env)"},
                "max_tokens": {"type": "integer", "description": "Max tokens override"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "send_conversation",
        "description": "Send a multi-turn conversation (messages array) and return response.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string", "enum": ["user", "assistant"]},
                            "content": {"type": "string"},
                        },
                        "required": ["role", "content"],
                    },
                    "description": "Conversation messages array",
                },
                "system": {"type": "string", "description": "Optional system prompt"},
                "model": {"type": "string", "description": "Model override"},
                "max_tokens": {"type": "integer", "description": "Max tokens override"},
            },
            "required": ["messages"],
        },
    },
    {
        "name": "count_tokens",
        "description": "Estimate token count for messages (rough: 4 chars/token latin, 2 chars/token cyrillic).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Messages array to estimate",
                },
                "text": {"type": "string", "description": "Plain text to estimate"},
            },
        },
    },
    {
        "name": "get_rate_limit",
        "description": "Get current rate limit headers from last request (requests/min, tokens/min).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_models",
        "description": "List available models with context windows and pricing info.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_usage",
        "description": "Get token usage summary from last response (input/output/cache tokens).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "stream_message",
        "description": "Send message and return chunked response metadata (non-streaming fallback).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "User message text"},
                "model": {"type": "string", "description": "Model override"},
                "max_tokens": {"type": "integer", "description": "Max tokens override"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "check_health",
        "description": "Verify API key, account info, and connectivity.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

TOOL_MAP = {
    "send_message": tool_send_message,
    "send_conversation": tool_send_conversation,
    "count_tokens": tool_count_tokens,
    "get_rate_limit": tool_get_rate_limit,
    "list_models": tool_list_models,
    "get_usage": tool_get_usage,
    "stream_message": tool_stream_message,
    "check_health": tool_check_health,
}


# ---------------------------------------------------------------------------
# Request dispatcher
# ---------------------------------------------------------------------------

def handle_request(msg):
    req_id = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params", {})

    # Notifications (no id) — ignore
    if req_id is None and method:
        return None

    # --- initialize ---
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "anthropic_api", "version": "1.0.0"},
        }
        return make_response(req_id, result)

    # --- notifications/initialized ---
    if method == "notifications/initialized":
        return None

    # --- tools/list ---
    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    # --- tools/call ---
    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_params = params.get("arguments", {})
        if tool_name not in TOOL_MAP:
            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            tool_result = TOOL_MAP[tool_name](tool_params)
            return make_response(req_id, tool_result)
        except Exception as exc:
            return make_response(req_id, {
                "content": [{"type": "text", "text": f"Tool error: {exc}"}],
                "isError": True,
            })

    # --- ping ---
    if method == "ping":
        return make_response(req_id, {})

    return make_error(req_id, -32601, f"Method not found: {method}")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    while True:
        line = read_line()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            send(make_error(None, -32700, "Parse error"))
            continue
        response = handle_request(msg)
        if response is not None:
            send(response)


if __name__ == "__main__":
    main()
