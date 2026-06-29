#!/usr/bin/env python3
"""MCP server for Redis — stdio JSON-RPC, no external deps."""

import asyncio
import json
import os
import shlex
import subprocess
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REDIS_CLI = os.environ.get("REDIS_CLI_PATH", "redis-cli")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")


def _cli_args() -> list[str]:
    """Build redis-cli base arguments from REDIS_URL."""
    url = REDIS_URL
    args: list[str] = []
    if "://" in url:
        _, rest = url.split("://", 1)
        host_port = rest.split("/", 1)[0]
        if "@" in host_port:
            password_part, host_port = host_port.split("@", 1)
            if password_part:
                args += ["-a", password_part]
        if ":" in host_port:
            host, port = host_port.rsplit(":", 1)
            if host:
                args += ["-h", host]
            if port:
                args += ["-p", port]
        else:
            if host_port:
                args += ["-h", host_port]
    return args


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

def _redis(*cmd_parts: str) -> tuple[bool, str]:
    """Run redis-cli, return (ok, output_or_error)."""
    base = _cli_args()
    try:
        result = subprocess.run(
            [REDIS_CLI, *base, *cmd_parts],
            capture_output=True, text=True, timeout=10,
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        if result.returncode != 0:
            return False, err or out or f"redis-cli exited {result.returncode}"
        return True, out
    except FileNotFoundError:
        return False, f"redis-cli not found at {REDIS_CLI}"
    except subprocess.TimeoutExpired:
        return False, "redis-cli timed out"
    except Exception as e:
        return False, str(e)


def _redis_pipe(commands: list[list[str]]) -> list[tuple[bool, str]]:
    """Run multiple redis-cli commands via pipe mode."""
    base = _cli_args()
    try:
        payload = "\n".join(
            shlex.join(part for part in cmd) for cmd in commands
        ) + "\n"
        result = subprocess.run(
            [REDIS_CLI, *base, "--pipe-mode"],
            input=payload, capture_output=True, text=True, timeout=10,
        )
        # pipe-mode is tricky; fall back to sequential
        raise NotImplementedError
    except Exception:
        # fallback: sequential
        return [_redis(*cmd) for cmd in commands]


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def make_response(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _parse_simple(raw: str) -> Any:
    """Try to parse redis-cli output as int, float, json, or return raw."""
    if raw.startswith("(nil)") or raw == "":
        return None
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    # integer
    try:
        return int(raw)
    except ValueError:
        pass
    # float
    try:
        return float(raw)
    except ValueError:
        pass
    # json
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass
    return raw


def tool_get(params: dict) -> dict:
    key = params.get("key", "")
    if not key:
        return {"content": [{"type": "text", "text": "Error: 'key' is required"}], "isError": True}

    ok, raw = _redis("GET", key)
    if not ok:
        return {"content": [{"type": "text", "text": f"Error: {raw}"}], "isError": True}

    # Also get type
    ok_t, type_raw = _redis("TYPE", key)
    key_type = type_raw if ok_t else "unknown"
    # TTL
    ok_ttl, ttl_raw = _redis("TTL", key)
    ttl = _parse_simple(ttl_raw) if ok_ttl else None

    value = None if raw == "(nil)" or raw == "" else raw
    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "key": key,
                "value": value,
                "type": key_type,
                "ttl": ttl,
                "exists": value is not None,
            }, ensure_ascii=False)
        }]
    }


def tool_set(params: dict) -> dict:
    key = params.get("key", "")
    value = params.get("value", "")
    if not key:
        return {"content": [{"type": "text", "text": "Error: 'key' is required"}], "isError": True}

    cmd = ["SET", key, value]
    ex = params.get("ex")
    px = params.get("px")
    if ex is not None:
        cmd += ["EX", str(int(ex))]
    elif px is not None:
        cmd += ["PX", str(int(px))]

    ok, raw = _redis(*cmd)
    if not ok:
        return {"content": [{"type": "text", "text": f"Error: {raw}"}], "isError": True}
    return {
        "content": [{
            "type": "text",
            "text": json.dumps({"key": key, "status": "OK", "set": True}, ensure_ascii=False)
        }]
    }


def tool_delete(params: dict) -> dict:
    keys = params.get("keys", [])
    if isinstance(keys, str):
        keys = [keys]
    if not keys:
        return {"content": [{"type": "text", "text": "Error: 'keys' is required"}], "isError": True}

    cmd = ["DEL"] + keys
    ok, raw = _redis(*cmd)
    if not ok:
        return {"content": [{"type": "text", "text": f"Error: {raw}"}], "isError": True}
    count = _parse_simple(raw)
    return {
        "content": [{
            "type": "text",
            "text": json.dumps({"keys": keys, "deleted": count}, ensure_ascii=False)
        }]
    }


def tool_list_keys(params: dict) -> dict:
    pattern = params.get("pattern", "*")
    count = params.get("count", 100)
    cursor = params.get("cursor", 0)

    ok, raw = _redis("SCAN", str(cursor), "MATCH", pattern, "COUNT", str(count))
    if not ok:
        return {"content": [{"type": "text", "text": f"Error: {raw}"}], "isError": True}

    # Parse SCAN output: cursor\n key1\n key2\n ...
    lines = raw.split("\n")
    if not lines:
        return {"content": [{"type": "text", "text": "Error: unexpected SCAN output"}], "isError": True}

    new_cursor = lines[0].strip().strip('"')
    keys_list = [l.strip().strip('"') for l in lines[1:] if l.strip() and l.strip() != "(empty array)"]

    # Get types and TTLs for each key (batch, limit to 50 to avoid slowness)
    keys_info = []
    batch = keys_list[:50]
    for k in batch:
        ok_t, t_raw = _redis("TYPE", k)
        ktype = t_raw if ok_t else "unknown"
        ok_ttl, ttl_raw = _redis("TTL", k)
        ttl = _parse_simple(ttl_raw) if ok_ttl else None
        keys_info.append({"key": k, "type": ktype, "ttl": ttl})

    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "cursor": new_cursor,
                "count": len(keys_info),
                "total_available": len(keys_list),
                "keys": keys_info,
            }, ensure_ascii=False)
        }]
    }


def tool_get_hash(params: dict) -> dict:
    key = params.get("key", "")
    if not key:
        return {"content": [{"type": "text", "text": "Error: 'key' is required"}], "isError": True}

    ok, raw = _redis("HGETALL", key)
    if not ok:
        return {"content": [{"type": "text", "text": f"Error: {raw}"}], "isError": True}

    if raw == "(empty array)" or not raw.strip():
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({"key": key, "type": "hash", "fields": {}, "count": 0}, ensure_ascii=False)
            }]
        }

    lines = [l.strip().strip('"') for l in raw.split("\n") if l.strip()]
    fields = {}
    for i in range(0, len(lines) - 1, 2):
        fields[lines[i]] = lines[i + 1]

    return {
        "content": [{
            "type": "text",
            "text": json.dumps({"key": key, "type": "hash", "fields": fields, "count": len(fields)}, ensure_ascii=False)
        }]
    }


def tool_get_list(params: dict) -> dict:
    key = params.get("key", "")
    start = params.get("start", 0)
    stop = params.get("stop", -1)
    if not key:
        return {"content": [{"type": "text", "text": "Error: 'key' is required"}], "isError": True}

    ok, raw = _redis("LRANGE", key, str(start), str(stop))
    if not ok:
        return {"content": [{"type": "text", "text": f"Error: {raw}"}], "isError": True}

    if raw == "(empty array)" or not raw.strip():
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({"key": key, "type": "list", "elements": [], "count": 0}, ensure_ascii=False)
            }]
        }

    elements = [l.strip().strip('"') for l in raw.split("\n") if l.strip()]
    return {
        "content": [{
            "type": "text",
            "text": json.dumps({"key": key, "type": "list", "elements": elements, "count": len(elements)}, ensure_ascii=False)
        }]
    }


def tool_get_set(params: dict) -> dict:
    key = params.get("key", "")
    if not key:
        return {"content": [{"type": "text", "text": "Error: 'key' is required"}], "isError": True}

    ok, raw = _redis("SMEMBERS", key)
    if not ok:
        return {"content": [{"type": "text", "text": f"Error: {raw}"}], "isError": True}

    if raw == "(empty array)" or not raw.strip():
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({"key": key, "type": "set", "members": [], "count": 0}, ensure_ascii=False)
            }]
        }

    members = [l.strip().strip('"') for l in raw.split("\n") if l.strip()]
    return {
        "content": [{
            "type": "text",
            "text": json.dumps({"key": key, "type": "set", "members": members, "count": len(members)}, ensure_ascii=False)
        }]
    }


def _parse_info_section(raw: str) -> dict:
    """Parse redis INFO output into structured dict."""
    result: dict = {}
    current_section = ""
    for line in raw.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            if line.startswith("# "):
                current_section = line[2:].strip().lower().replace(" ", "_")
                result[current_section] = {}
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip()
            # try parse numeric
            try:
                v_out: Any = int(v)
            except ValueError:
                try:
                    v_out = float(v)
                except ValueError:
                    v_out = v
            if current_section:
                result[current_section][k] = v_out
            else:
                result[k] = v_out
    return result


def tool_get_info(params: dict) -> dict:
    sections = params.get("sections", ["memory", "clients", "keyspace", "server", "stats"])
    if isinstance(sections, str):
        sections = [s.strip() for s in sections.split(",")]

    results: dict = {}
    for sec in sections:
        ok, raw = _redis("INFO", sec)
        if ok:
            results[sec] = _parse_info_section(raw)
        else:
            results[sec] = {"error": raw}

    return {
        "content": [{
            "type": "text",
            "text": json.dumps(results, ensure_ascii=False, indent=2)
        }]
    }


def tool_check_health(params: dict) -> dict:
    health: dict = {"status": "unknown"}

    # PING
    ok, raw = _redis("PING")
    health["ping"] = {"ok": ok, "response": raw}
    if not ok:
        health["status"] = "unreachable"
        return {
            "content": [{
                "type": "text",
                "text": json.dumps(health, ensure_ascii=False)
            }],
            "isError": True
        }

    # Latency (simple: time PING round-trip via INFO command_time)
    import time as _time
    t0 = _time.monotonic()
    _redis("PING")
    latency_ms = round((_time.monotonic() - t0) * 1000, 2)
    health["latency_ms"] = latency_ms

    # Version
    ok_v, ver_raw = _redis("INFO", "server")
    version = "unknown"
    if ok_v:
        for line in ver_raw.split("\n"):
            if line.startswith("redis_version:"):
                version = line.split(":", 1)[1].strip()
                break
    health["version"] = version

    # Memory
    ok_m, mem_raw = _redis("INFO", "memory")
    if ok_m:
        mem_info = _parse_info_section(mem_raw)
        used_memory = mem_info.get("memory", {}).get("used_memory", "unknown")
        used_human = mem_info.get("memory", {}).get("used_memory_human", "unknown")
        peak_human = mem_info.get("memory", {}).get("used_memory_peak_human", "unknown")
        health["memory"] = {
            "used_bytes": used_memory,
            "used_human": used_human,
            "peak_human": peak_human,
        }

    # Connected clients
    ok_c, cli_raw = _redis("INFO", "clients")
    if ok_c:
        cli_info = _parse_info_section(cli_raw)
        connected = cli_info.get("clients", {}).get("connected_clients", "unknown")
        health["connected_clients"] = connected

    # Keyspace
    ok_k, ks_raw = _redis("INFO", "keyspace")
    if ok_k:
        ks_info = _parse_info_section(ks_raw)
        health["keyspace"] = ks_info.get("keyspace", {})

    health["status"] = "ok"
    return {
        "content": [{
            "type": "text",
            "text": json.dumps(health, ensure_ascii=False, indent=2)
        }]
    }


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOLS: dict[str, dict] = {
    "get": {
        "description": "GET a Redis key, returning value with type and TTL info",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Redis key to get"},
            },
            "required": ["key"],
        },
        "handler": tool_get,
    },
    "set": {
        "description": "SET a Redis key with optional TTL (EX seconds or PX milliseconds)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Redis key to set"},
                "value": {"type": "string", "description": "Value to set"},
                "ex": {"type": "integer", "description": "Expire in seconds (optional)"},
                "px": {"type": "integer", "description": "Expire in milliseconds (optional)"},
            },
            "required": ["key", "value"],
        },
        "handler": tool_set,
    },
    "delete": {
        "description": "DEL one or more Redis keys, returning count deleted",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key(s) to delete",
                },
            },
            "required": ["keys"],
        },
        "handler": tool_delete,
    },
    "list_keys": {
        "description": "SCAN Redis keys matching a pattern, returning keys with types and TTLs",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Key pattern (default *)", "default": "*"},
                "count": {"type": "integer", "description": "SCAN COUNT hint (default 100)", "default": 100},
                "cursor": {"type": "integer", "description": "SCAN cursor (default 0)", "default": 0},
            },
        },
        "handler": tool_list_keys,
    },
    "get_hash": {
        "description": "HGETALL for a Redis hash key",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Hash key"},
            },
            "required": ["key"],
        },
        "handler": tool_get_hash,
    },
    "get_list": {
        "description": "LRANGE for a Redis list key",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "List key"},
                "start": {"type": "integer", "description": "Start index (default 0)", "default": 0},
                "stop": {"type": "integer", "description": "Stop index (default -1 = all)", "default": -1},
            },
            "required": ["key"],
        },
        "handler": tool_get_list,
    },
    "get_set": {
        "description": "SMEMBERS for a Redis set key",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Set key"},
            },
            "required": ["key"],
        },
        "handler": tool_get_set,
    },
    "get_info": {
        "description": "Redis INFO: memory, clients, keyspace, uptime, version",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "INFO sections (default: memory,clients,keyspace,server,stats)",
                    "default": ["memory", "clients", "keyspace", "server", "stats"],
                },
            },
        },
        "handler": tool_get_info,
    },
    "check_health": {
        "description": "Redis health check: PING, latency, version, memory usage",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "handler": tool_check_health,
    },
}


# ---------------------------------------------------------------------------
# Request dispatcher
# ---------------------------------------------------------------------------

def handle_request(msg: dict) -> dict | None:
    """Dispatch a single JSON-RPC request. Return response dict or None (for notifications)."""
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params", {})

    # --- initialize ---
    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "redis", "version": "1.0.0"},
        })

    # --- notifications (no response) ---
    if method == "notifications/initialized":
        return None

    # --- tools/list ---
    if method == "tools/list":
        tool_list = []
        for name, t in TOOLS.items():
            tool_list.append({
                "name": name,
                "description": t["description"],
                "inputSchema": t["inputSchema"],
            })
        return make_response(req_id, {"tools": tool_list})

    # --- tools/call ---
    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_params = params.get("arguments", {})
        if tool_name not in TOOLS:
            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = TOOLS[tool_name]["handler"](tool_params)
            return make_response(req_id, result)
        except Exception as e:
            return make_response(req_id, {
                "content": [{"type": "text", "text": f"Tool error: {e}"}],
                "isError": True,
            })

    # --- ping ---
    if method == "ping":
        return make_response(req_id, {})

    return make_error(req_id, -32601, f"Method not found: {method}")


# ---------------------------------------------------------------------------
# Main async loop
# ---------------------------------------------------------------------------

async def main():
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_event_loop()
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    writer_transport, writer_protocol = await loop.connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, loop)

    while True:
        try:
            line = await reader.readline()
            if not line:
                break
            line = line.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                resp = make_error(None, -32700, "Parse error")
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()
                continue

            resp = handle_request(msg)
            if resp is not None:
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()

        except Exception:
            break

    writer.close()


if __name__ == "__main__":
    asyncio.run(main())
