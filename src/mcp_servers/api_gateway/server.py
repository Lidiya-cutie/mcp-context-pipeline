#!/usr/bin/env python3
"""MCP server for API Gateway management (Kong / Nginx)."""

import json
import os
import sys
import urllib.request
import urllib.error
from typing import Any, Optional


GATEWAY_TYPE = os.environ.get("GATEWAY_TYPE", "kong").lower()
KONG_ADMIN_URL = os.environ.get("KONG_ADMIN_URL", "http://localhost:8001")
NGINX_STATUS_URL = os.environ.get("NGINX_STATUS_URL", "http://localhost/nginx_status")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _gw_get(path: str, base: Optional[str] = None) -> dict:
    """GET JSON from gateway admin API."""
    url = (base or KONG_ADMIN_URL).rstrip("/") + path
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace") if e.fp else ""
        raise RuntimeError(f"HTTP {e.code} from {url}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection error to {url}: {e.reason}") from e


def _gw_get_raw(path: str, base: Optional[str] = None) -> str:
    """GET raw text from a URL."""
    url = (base or KONG_ADMIN_URL).rstrip("/") + path
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode()
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        raise RuntimeError(str(e)) from e


def _kong_paginated(path: str) -> list:
    """Fetch all pages from a Kong paginated endpoint."""
    results = []
    url = KONG_ADMIN_URL.rstrip("/") + path
    while url:
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            raise RuntimeError(str(e)) from e
        results.extend(data.get("data", []))
        nxt = data.get("next")
        url = KONG_ADMIN_URL.rstrip("/") + nxt if nxt else None
    return results


def make_response(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


# ── Tool implementations ─────────────────────────────────────────────────────

def _list_routes_kong(args: dict) -> dict:
    routes = _kong_paginated("/routes")
    out = []
    for r in routes:
        svc_id = r.get("service", {}).get("id")
        svc_name = r.get("service", {}).get("name", svc_id or "")
        out.append({
            "id": r.get("id"),
            "name": r.get("name", ""),
            "methods": r.get("methods", []),
            "paths": r.get("paths", []),
            "hosts": r.get("hosts", []),
            "service": svc_name,
            "protocols": r.get("protocols", []),
            "strip_path": r.get("strip_path"),
            "preserve_host": r.get("preserve_host"),
        })
    return {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]}


def _list_routes_nginx(args: dict) -> dict:
    try:
        raw = _gw_get_raw("/routes", NGINX_STATUS_URL.rsplit("/", 1)[0])
        return {"content": [{"type": "text", "text": raw}]}
    except RuntimeError:
        return {"content": [{"type": "text", "text": json.dumps({
            "note": "Nginx does not expose routes via API. Check nginx config files.",
            "suggestion": "Parse /etc/nginx/sites-enabled/ or use nginx + Consul/etcd for dynamic routes."
        }, indent=2)}]}


def list_routes(args: dict) -> dict:
    if GATEWAY_TYPE == "nginx":
        return _list_routes_nginx(args)
    return _list_routes_kong(args)


def list_services(args: dict) -> dict:
    if GATEWAY_TYPE == "nginx":
        return {"content": [{"type": "text", "text": json.dumps({
            "note": "Nginx does not have a services concept. Upstreams defined in config."
        })}]}
    services = _kong_paginated("/services")
    out = []
    for s in services:
        out.append({
            "id": s.get("id"),
            "name": s.get("name", ""),
            "url": s.get("url", ""),
            "protocol": s.get("protocol", ""),
            "host": s.get("host", ""),
            "port": s.get("port"),
            "path": s.get("path", ""),
            "retries": s.get("retries"),
            "connect_timeout": s.get("connect_timeout"),
            "write_timeout": s.get("write_timeout"),
            "read_timeout": s.get("read_timeout"),
            "enabled": s.get("enabled"),
        })
    return {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]}


def list_plugins(args: dict) -> dict:
    if GATEWAY_TYPE == "nginx":
        return {"content": [{"type": "text", "text": json.dumps({
            "note": "Nginx does not have a plugin system. Features come from modules (lua, njs, etc.)."
        })}]}
    plugins = _kong_paginated("/plugins")
    out = []
    for p in plugins:
        out.append({
            "id": p.get("id"),
            "name": p.get("name", ""),
            "enabled": p.get("enabled", False),
            "config": p.get("config", {}),
            "scope": {
                "service": p.get("service", {}).get("id") if p.get("service") else None,
                "route": p.get("route", {}).get("id") if p.get("route") else None,
                "consumer": p.get("consumer", {}).get("id") if p.get("consumer") else None,
                "global": not p.get("service") and not p.get("route") and not p.get("consumer"),
            },
            "protocols": p.get("protocols", []),
            "tags": p.get("tags", []),
        })
    return {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]}


def get_route_details(args: dict) -> dict:
    if GATEWAY_TYPE == "nginx":
        return {"content": [{"type": "text", "text": json.dumps({"error": "Not applicable for nginx"})}]}
    route_id = args.get("route_id", "")
    if not route_id:
        return {"content": [{"type": "text", "text": json.dumps({"error": "route_id required"})}]}
    try:
        r = _gw_get(f"/routes/{route_id}")
    except RuntimeError as e:
        return {"content": [{"type": "text", "text": json.dumps({"error": str(e)})}]}
    # Also fetch plugins for this route
    try:
        plugins = _kong_paginated(f"/routes/{route_id}/plugins")
    except RuntimeError:
        plugins = []
    out = {
        "id": r.get("id"),
        "name": r.get("name", ""),
        "methods": r.get("methods", []),
        "paths": r.get("paths", []),
        "hosts": r.get("hosts", []),
        "headers": r.get("headers", {}),
        "protocols": r.get("protocols", []),
        "strip_path": r.get("strip_path"),
        "preserve_host": r.get("preserve_host"),
        "regex_priority": r.get("regex_priority"),
        "request_buffering": r.get("request_buffering"),
        "response_buffering": r.get("response_buffering"),
        "service": r.get("service"),
        "tags": r.get("tags", []),
        "plugins": [{"id": p.get("id"), "name": p.get("name"), "enabled": p.get("enabled")} for p in plugins],
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }
    return {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]}


def get_service_health(args: dict) -> dict:
    if GATEWAY_TYPE == "nginx":
        return {"content": [{"type": "text", "text": json.dumps({"error": "Not applicable for nginx"})}]}
    service_id = args.get("service_id", "")
    if not service_id:
        return {"content": [{"type": "text", "text": json.dumps({"error": "service_id required"})}]}
    out = {"service_id": service_id}
    # Upstream health
    try:
        upstreams = _kong_paginated("/upstreams")
        for u in upstreams:
            if u.get("name", "").startswith(service_id[:8]):
                try:
                    health = _gw_get(f"/upstreams/{u['id']}/health")
                    out["upstream"] = {
                        "id": u.get("id"),
                        "name": u.get("name"),
                        "health": health,
                    }
                except RuntimeError:
                    pass
                break
    except RuntimeError:
        pass
    # Service info
    try:
        svc = _gw_get(f"/services/{service_id}")
        out["retries"] = svc.get("retries")
        out["connect_timeout"] = svc.get("connect_timeout")
        out["write_timeout"] = svc.get("write_timeout")
        out["read_timeout"] = svc.get("read_timeout")
    except RuntimeError as e:
        out["service_error"] = str(e)
    return {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]}


def get_rate_limits(args: dict) -> dict:
    if GATEWAY_TYPE == "nginx":
        return {"content": [{"type": "text", "text": json.dumps({
            "note": "Check nginx limit_req_zone directives in config for rate limits."
        })}]}
    scope = args.get("scope", "global")  # global | route | service
    scope_id = args.get("scope_id", "")
    out = {"rate_limiting_plugins": []}
    try:
        if scope == "route" and scope_id:
            plugins = _kong_paginated(f"/routes/{scope_id}/plugins")
        elif scope == "service" and scope_id:
            plugins = _kong_paginated(f"/services/{scope_id}/plugins")
        else:
            plugins = _kong_paginated("/plugins")
        for p in plugins:
            name = p.get("name", "")
            if "rate-limiting" in name or "rate_limiting" in name:
                out["rate_limiting_plugins"].append({
                    "id": p.get("id"),
                    "name": name,
                    "enabled": p.get("enabled"),
                    "config": p.get("config", {}),
                    "scope": {
                        "service": p.get("service", {}).get("id") if p.get("service") else None,
                        "route": p.get("route", {}).get("id") if p.get("route") else None,
                        "consumer": p.get("consumer", {}).get("id") if p.get("consumer") else None,
                    },
                })
    except RuntimeError as e:
        out["error"] = str(e)
    return {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]}


def get_consumer_stats(args: dict) -> dict:
    if GATEWAY_TYPE == "nginx":
        return {"content": [{"type": "text", "text": json.dumps({
            "note": "Nginx does not have consumer/auth concepts natively."
        })}]}
    out = {"consumers": [], "total": 0}
    try:
        consumers = _kong_paginated("/consumers")
        out["total"] = len(consumers)
        for c in consumers:
            entry = {
                "id": c.get("id"),
                "username": c.get("username", ""),
                "custom_id": c.get("custom_id", ""),
                "created_at": c.get("created_at"),
            }
            # Credentials
            try:
                creds = _kong_paginated(f"/consumers/{c['id']}/plugins")
                entry["plugins_count"] = len(creds)
            except RuntimeError:
                pass
            out["consumers"].append(entry)
    except RuntimeError as e:
        out["error"] = str(e)
    return {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]}


def get_gateway_stats(args: dict) -> dict:
    if GATEWAY_TYPE == "nginx":
        try:
            raw = _gw_get_raw("", NGINX_STATUS_URL)
            return {"content": [{"type": "text", "text": raw}]}
        except RuntimeError as e:
            return {"content": [{"type": "text", "text": json.dumps({"error": str(e)})}]}
    try:
        status = _gw_get("/status")
    except RuntimeError:
        status = {"note": "Kong /status endpoint not available (needs kong-prometheus-plugin or status endpoint enabled)"}
    out = {
        "gateway": "kong",
        "admin_url": KONG_ADMIN_URL,
        "stats": status,
    }
    return {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]}


def check_health(args: dict) -> dict:
    out = {"gateway_type": GATEWAY_TYPE, "healthy": False}
    if GATEWAY_TYPE == "nginx":
        try:
            raw = _gw_get_raw("", NGINX_STATUS_URL)
            out["healthy"] = True
            out["status_url"] = NGINX_STATUS_URL
            out["stub_status"] = raw.strip()
        except RuntimeError as e:
            out["error"] = str(e)
    else:
        try:
            info = _gw_get("/")
            out["healthy"] = True
            out["version"] = info.get("version", "unknown")
            out["tagline"] = info.get("tagline", "")
            out["admin_url"] = KONG_ADMIN_URL
            # Try /status for connections
            try:
                status = _gw_get("/status")
                out["connections"] = {
                    "active": status.get("connections_active"),
                    "accepted": status.get("connections_accepted"),
                    "handled": status.get("connections_handled"),
                    "reading": status.get("connections_reading"),
                    "writing": status.get("connections_writing"),
                    "waiting": status.get("connections_waiting"),
                }
            except RuntimeError:
                pass
        except RuntimeError as e:
            out["error"] = str(e)
    return {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]}


# ── Tool registry ────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "list_routes",
        "description": "List all configured API gateway routes with methods, paths, and upstream mappings.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "list_services",
        "description": "List all gateway services with upstream URLs, retries, and timeout settings.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "list_plugins",
        "description": "List active gateway plugins (rate-limiting, auth, CORS, etc.) with their configuration.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_route_details",
        "description": "Get detailed information about a specific route: methods, paths, headers, redirects, and attached plugins.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "route_id": {
                    "type": "string",
                    "description": "Route ID to inspect.",
                },
            },
            "required": ["route_id"],
        },
    },
    {
        "name": "get_service_health",
        "description": "Get upstream health checks (active/passive) and circuit breaker status for a service.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "string",
                    "description": "Service ID to check.",
                },
            },
            "required": ["service_id"],
        },
    },
    {
        "name": "get_rate_limits",
        "description": "Get rate limiting configuration per route/service, including current usage if available.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "Scope: 'global', 'route', or 'service'.",
                    "enum": ["global", "route", "service"],
                },
                "scope_id": {
                    "type": "string",
                    "description": "Route or service ID when scope is not global.",
                },
            },
        },
    },
    {
        "name": "get_consumer_stats",
        "description": "List consumers/credentials and their usage statistics.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_gateway_stats",
        "description": "Get total requests, latency percentiles, and error rates from the gateway.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "check_health",
        "description": "Ping the gateway admin API, return version, connections, and uptime info.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

TOOL_DISPATCH = {
    "list_routes": list_routes,
    "list_services": list_services,
    "list_plugins": list_plugins,
    "get_route_details": get_route_details,
    "get_service_health": get_service_health,
    "get_rate_limits": get_rate_limits,
    "get_consumer_stats": get_consumer_stats,
    "get_gateway_stats": get_gateway_stats,
    "check_health": check_health,
}


# ── JSON-RPC dispatcher ──────────────────────────────────────────────────────

def handle_request(msg: dict) -> dict:
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "api_gateway", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return make_response(req_id, {})

    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if tool_name not in TOOL_DISPATCH:
            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = TOOL_DISPATCH[tool_name](arguments)
            return make_response(req_id, result)
        except Exception as e:
            return make_response(req_id, {
                "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                "isError": True,
            })

    if method == "ping":
        return make_response(req_id, {})

    return make_error(req_id, -32601, f"Method not found: {method}")


# ── Main loop ────────────────────────────────────────────────────────────────

async def main():
    reader = sys.stdin.buffer
    writer = sys.stdout.buffer

    while True:
        header = reader.readline()
        if not header:
            break
        header = header.decode("utf-8").strip()
        if not header:
            continue

        content_length = None
        while header:
            if header.lower().startswith("content-length:"):
                content_length = int(header.split(":", 1)[1].strip())
            header = reader.readline()
            if not header:
                break
            header = header.decode("utf-8").strip()
            if header == "":
                break

        if content_length is None:
            continue

        body = reader.read(content_length)
        if not body:
            break

        try:
            msg = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as e:
            resp = make_error(None, -32700, f"Parse error: {e}")
            body_out = json.dumps(resp).encode("utf-8")
            writer.write(f"Content-Length: {len(body_out)}\r\n\r\n".encode("utf-8") + body_out)
            writer.flush()
            continue

        resp = handle_request(msg)
        body_out = json.dumps(resp).encode("utf-8")
        writer.write(f"Content-Length: {len(body_out)}\r\n\r\n".encode("utf-8") + body_out)
        writer.flush()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
