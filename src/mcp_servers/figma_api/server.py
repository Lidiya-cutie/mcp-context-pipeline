#!/usr/bin/env python3
"""MCP server for Figma REST API proxy. stdio transport, JSON-RPC, MCP 2024-11-05."""

import json
import sys
import os
import urllib.request
import urllib.error
import urllib.parse

FIGMA_BASE = "https://api.figma.com/v1"


def _token():
    return os.environ.get("FIGMA_ACCESS_TOKEN", "")


def _headers():
    return {"X-Figma-Token": _token()}


def figma_get(path, params=None):
    url = FIGMA_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        return {"error": {"status": e.code, "message": body}}
    except Exception as e:
        return {"error": {"status": 0, "message": str(e)}}


def make_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


# ── Tool handlers ──────────────────────────────────────────────────────────

def tool_get_file(args):
    key = args.get("key")
    if not key:
        return {"error": {"status": 400, "message": "Missing required parameter: key"}}
    data = figma_get(f"/files/{key}")
    if "error" in data:
        return data
    doc = data.get("document", {})
    return {
        "name": data.get("name"),
        "lastModified": data.get("lastModified"),
        "thumbnailUrl": data.get("thumbnailUrl"),
        "pages": [
            {"id": p.get("id"), "name": p.get("name"), "type": p.get("type")}
            for p in doc.get("children", [])
        ],
        "components": data.get("components", {}),
    }


def tool_get_file_nodes(args):
    key = args.get("key")
    ids = args.get("ids")
    if not key or not ids:
        return {"error": {"status": 400, "message": "Missing required parameters: key, ids"}}
    if isinstance(ids, list):
        ids = ",".join(ids)
    data = figma_get(f"/files/{key}/nodes", {"ids": ids})
    if "error" in data:
        return data
    return {"nodes": data.get("nodes", {})}


def tool_get_components(args):
    team_id = args.get("team_id")
    if not team_id:
        return {"error": {"status": 400, "message": "Missing required parameter: team_id"}}
    data = figma_get(f"/teams/{team_id}/components")
    if "error" in data:
        return data
    return {"components": data.get("components", [])}


def tool_get_component(args):
    key = args.get("key")
    if not key:
        return {"error": {"status": 400, "message": "Missing required parameter: key"}}
    data = figma_get(f"/components/{key}")
    if "error" in data:
        return data
    meta = data.get("meta", {})
    return {
        "name": meta.get("name"),
        "description": meta.get("description"),
        "key": meta.get("key"),
        "componentSetId": meta.get("componentSetId"),
        "containing_frame": meta.get("containing_frame"),
    }


def tool_get_styles(args):
    team_id = args.get("team_id")
    if not team_id:
        return {"error": {"status": 400, "message": "Missing required parameter: team_id"}}
    data = figma_get(f"/teams/{team_id}/styles")
    if "error" in data:
        return data
    return {"styles": data.get("styles", [])}


def tool_get_style(args):
    key = args.get("key")
    if not key:
        return {"error": {"status": 400, "message": "Missing required parameter: key"}}
    data = figma_get(f"/styles/{key}")
    if "error" in data:
        return data
    meta = data.get("meta", {})
    return {
        "name": meta.get("name"),
        "description": meta.get("description"),
        "key": meta.get("key"),
        "styleType": meta.get("style_type"),
        "sortPosition": meta.get("sortPosition"),
    }


def tool_get_images(args):
    key = args.get("key")
    ids = args.get("ids")
    if not key or not ids:
        return {"error": {"status": 400, "message": "Missing required parameters: key, ids"}}
    if isinstance(ids, list):
        ids = ",".join(ids)
    params = {"ids": ids}
    if args.get("format"):
        params["format"] = args["format"]
    if args.get("scale"):
        params["scale"] = str(args["scale"])
    data = figma_get(f"/images/{key}", params)
    if "error" in data:
        return data
    return {"images": data.get("images", {})}


def tool_check_health(_args):
    data = figma_get("/me")
    if "error" in data:
        return data
    return {
        "id": data.get("id"),
        "email": data.get("email"),
        "handle": data.get("handle"),
        "img_url": data.get("img_url"),
    }


# ── Tool definitions ───────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_file",
        "description": "Get Figma file document tree. Returns name, pages, and components.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Figma file key (from URL)"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "get_file_nodes",
        "description": "Get specific nodes by ID with their properties from a Figma file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Figma file key"},
                "ids": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": "Node ID(s), comma-separated string or array",
                },
            },
            "required": ["key", "ids"],
        },
    },
    {
        "name": "get_components",
        "description": "List published components from a team library.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "string", "description": "Figma team ID"},
            },
            "required": ["team_id"],
        },
    },
    {
        "name": "get_component",
        "description": "Get component by key, return properties and variants.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Component key"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "get_styles",
        "description": "List published styles (colors, typography, effects, grids) from a team.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "string", "description": "Figma team ID"},
            },
            "required": ["team_id"],
        },
    },
    {
        "name": "get_style",
        "description": "Get style details by key.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Style key"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "get_images",
        "description": "Render nodes as images and return image URLs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Figma file key"},
                "ids": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": "Node ID(s) to render",
                },
                "format": {"type": "string", "enum": ["png", "jpg", "svg", "pdf"], "description": "Image format (default png)"},
                "scale": {"type": "number", "enum": [1, 2, 3, 4], "description": "Image scale factor"},
            },
            "required": ["key", "ids"],
        },
    },
    {
        "name": "check_health",
        "description": "Verify Figma token validity and return current user info.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

TOOL_DISPATCH = {
    "get_file": tool_get_file,
    "get_file_nodes": tool_get_file_nodes,
    "get_components": tool_get_components,
    "get_component": tool_get_component,
    "get_styles": tool_get_styles,
    "get_style": tool_get_style,
    "get_images": tool_get_images,
    "check_health": tool_check_health,
}


# ── JSON-RPC dispatch ──────────────────────────────────────────────────────

def handle_request(msg):
    req_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params", {})

    # --- initialize ---
    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "figma_api", "version": "1.0.0"},
        })

    # --- notifications (no response expected for initialized) ---
    if method == "notifications/initialized":
        return None

    # --- tools/list ---
    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    # --- tools/call ---
    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})
        if tool_name not in TOOL_DISPATCH:
            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")
        result = TOOL_DISPATCH[tool_name](tool_args)
        if "error" in result:
            return make_response(req_id, {
                "content": [{"type": "text", "text": json.dumps(result)}],
                "isError": True,
            })
        return make_response(req_id, {
            "content": [{"type": "text", "text": json.dumps(result)}],
        })

    return make_error(req_id, -32601, f"Method not found: {method}")


# ── Main loop (synchronous stdio) ─────────────────────────────────────────

def main():
    writer = sys.stdout.buffer
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = make_error(None, -32700, "Parse error")
            writer.write((json.dumps(resp) + "\n").encode())
            writer.flush()
            continue

        resp = handle_request(msg)
        if resp is not None:
            writer.write((json.dumps(resp) + "\n").encode())
            writer.flush()


if __name__ == "__main__":
    main()
