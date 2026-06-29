#!/usr/bin/env python3
"""MCP server for Docker Registry API v2 — stdio transport."""

import json
import sys
import os
import base64
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "registry"
SERVER_VERSION = "1.0.0"

REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://localhost:5000").rstrip("/")
REGISTRY_USERNAME = os.environ.get("REGISTRY_USERNAME")
REGISTRY_PASSWORD = os.environ.get("REGISTRY_PASSWORD")


def _auth_header():
    if REGISTRY_USERNAME and REGISTRY_PASSWORD:
        token = base64.b64encode(
            f"{REGISTRY_USERNAME}:{REGISTRY_PASSWORD}".encode()
        ).decode()
        return f"Basic {token}"
    return None


def _registry_request(path, method="GET", headers=None, accept=None):
    url = f"{REGISTRY_URL}{path}"
    hdrs = headers or {}
    auth = _auth_header()
    if auth:
        hdrs["Authorization"] = auth
    if accept:
        hdrs["Accept"] = accept
    req = Request(url, method=method, headers=hdrs)
    try:
        with urlopen(req) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            ct = resp.headers.get("Content-Type", "")
            return {
                "status": resp.status,
                "body": json.loads(body) if "json" in ct else body,
                "headers": dict(resp.headers),
            }
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"status": e.code, "error": body, "headers": dict(e.headers)}
    except URLError as e:
        return {"status": 0, "error": str(e.reason)}


# ---------- helpers ----------

def make_response(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": err}


# ---------- tool implementations ----------

def tool_list_repositories(params):
    n = params.get("n")
    last = params.get("last")
    qs = ""
    parts = []
    if n is not None:
        parts.append(f"n={n}")
    if last:
        parts.append(f"last={last}")
    if parts:
        qs = "?" + "&".join(parts)
    r = _registry_request(f"/v2/_catalog{qs}")
    if "error" in r:
        return {"error": r["error"], "status": r.get("status")}
    return r.get("body", {})


def tool_list_tags(params):
    name = params.get("name")
    if not name:
        return {"error": "parameter 'name' is required"}
    n = params.get("n")
    last = params.get("last")
    qs = ""
    parts = []
    if n is not None:
        parts.append(f"n={n}")
    if last:
        parts.append(f"last={last}")
    if parts:
        qs = "?" + "&".join(parts)
    r = _registry_request(f"/v2/{name}/tags/list{qs}")
    if "error" in r:
        return {"error": r["error"], "status": r.get("status")}
    return r.get("body", {})


def tool_get_manifest(params):
    name = params.get("name")
    reference = params.get("reference")
    if not name or not reference:
        return {"error": "parameters 'name' and 'reference' are required"}
    accept = (
        "application/vnd.docker.distribution.manifest.v2+json, "
        "application/vnd.docker.distribution.manifest.list.v2+json, "
        "application/vnd.oci.image.manifest.v1+json, "
        "application/vnd.oci.image.index.v1+json"
    )
    r = _registry_request(
        f"/v2/{name}/manifests/{reference}", accept=accept
    )
    if "error" in r:
        return {"error": r["error"], "status": r.get("status")}
    manifest = r.get("body") if isinstance(r.get("body"), dict) else {}
    result = {
        "schemaVersion": manifest.get("schemaVersion"),
        "mediaType": manifest.get("mediaType"),
        "config": manifest.get("config"),
        "layers": manifest.get("layers", manifest.get("manifests", [])),
        "size": _manifest_total_size(manifest),
    }
    return result


def _manifest_total_size(manifest):
    total = 0
    if isinstance(manifest, dict):
        config = manifest.get("config")
        if isinstance(config, dict):
            total += config.get("size", 0)
        for layer in manifest.get("layers", []):
            if isinstance(layer, dict):
                total += layer.get("size", 0)
        for m in manifest.get("manifests", []):
            if isinstance(m, dict):
                total += m.get("size", 0)
    return total


def tool_get_blob(params):
    name = params.get("name")
    digest = params.get("digest")
    if not name or not digest:
        return {"error": "parameters 'name' and 'digest' are required"}
    url = f"{REGISTRY_URL}/v2/{name}/blobs/{digest}"
    hdrs = {}
    auth = _auth_header()
    if auth:
        hdrs["Authorization"] = auth
    req = Request(url, method="HEAD", headers=hdrs)
    try:
        with urlopen(req) as resp:
            return {
                "digest": digest,
                "size": int(resp.headers.get("Content-Length", 0)),
                "content_type": resp.headers.get("Content-Type", ""),
                "status": resp.status,
            }
    except HTTPError as e:
        return {"error": e.read().decode("utf-8", errors="replace"), "status": e.code}
    except URLError as e:
        return {"error": str(e.reason), "status": 0}


def tool_delete_tag(params):
    name = params.get("name")
    reference = params.get("reference")
    if not name or not reference:
        return {"error": "parameters 'name' and 'reference' are required"}
    # First get the digest
    accept = (
        "application/vnd.docker.distribution.manifest.v2+json, "
        "application/vnd.docker.distribution.manifest.list.v2+json, "
        "application/vnd.oci.image.manifest.v1+json"
    )
    url = f"{REGISTRY_URL}/v2/{name}/manifests/{reference}"
    hdrs = {"Accept": accept}
    auth = _auth_header()
    if auth:
        hdrs["Authorization"] = auth
    req = Request(url, method="GET", headers=hdrs)
    try:
        with urlopen(req) as resp:
            digest = resp.headers.get("Docker-Content-Digest", "")
            body = resp.read()
    except HTTPError as e:
        return {"error": f"fetch manifest: {e.read().decode()}", "status": e.code}
    except URLError as e:
        return {"error": str(e.reason), "status": 0}

    if not digest:
        return {"error": "could not resolve digest for reference"}

    # Delete by digest
    del_url = f"{REGISTRY_URL}/v2/{name}/manifests/{digest}"
    del_hdrs = {}
    if auth:
        del_hdrs["Authorization"] = auth
    del_req = Request(del_url, method="DELETE", headers=del_hdrs)
    try:
        with urlopen(del_req) as resp:
            return {"status": resp.status, "deleted": digest}
    except HTTPError as e:
        return {"error": e.read().decode("utf-8", errors="replace"), "status": e.code}
    except URLError as e:
        return {"error": str(e.reason), "status": 0}


def tool_get_image_size(params):
    name = params.get("name")
    reference = params.get("reference", "latest")
    if not name:
        return {"error": "parameter 'name' is required"}
    accept = (
        "application/vnd.docker.distribution.manifest.v2+json, "
        "application/vnd.docker.distribution.manifest.list.v2+json, "
        "application/vnd.oci.image.manifest.v1+json"
    )
    r = _registry_request(f"/v2/{name}/manifests/{reference}", accept=accept)
    if "error" in r:
        return {"error": r["error"], "status": r.get("status")}
    manifest = r.get("body") if isinstance(r.get("body"), dict) else {}
    total = _manifest_total_size(manifest)
    layer_count = len(manifest.get("layers", []))
    return {
        "name": name,
        "reference": reference,
        "total_size": total,
        "layer_count": layer_count,
    }


def tool_get_tag_history(params):
    name = params.get("name")
    if not name:
        return {"error": "parameter 'name' is required"}
    r = _registry_request(f"/v2/{name}/tags/list")
    if "error" in r:
        return {"error": r["error"], "status": r.get("status")}
    body = r.get("body", {})
    tags = body.get("tags", [])
    if not tags:
        return {"tags": []}

    accept = (
        "application/vnd.docker.distribution.manifest.v2+json, "
        "application/vnd.oci.image.manifest.v1+json"
    )
    results = []
    for tag in tags:
        mr = _registry_request(f"/v2/{name}/manifests/{tag}", accept=accept)
        if "error" in mr:
            results.append({"tag": tag, "error": mr["error"]})
            continue
        manifest = mr.get("body") if isinstance(mr.get("body"), dict) else {}
        # Try to get created timestamp from config blob
        config_digest = ""
        config_obj = manifest.get("config", {})
        if isinstance(config_obj, dict):
            config_digest = config_obj.get("digest", "")
        created = None
        if config_digest:
            cr = _registry_request(f"/v2/{name}/blobs/{config_digest}")
            if "error" not in cr and isinstance(cr.get("body"), dict):
                cfg = cr["body"]
                created = cfg.get("created")
        results.append({"tag": tag, "created": created})

    results.sort(key=lambda x: x.get("created") or "", reverse=True)
    return {"tags": results}


def tool_gc_candidates(params):
    name = params.get("name")
    if not name:
        return {"error": "parameter 'name' is required"}
    older_than_days = params.get("older_than_days", 30)
    keep_latest = params.get("keep_latest", 1)

    r = _registry_request(f"/v2/{name}/tags/list")
    if "error" in r:
        return {"error": r["error"], "status": r.get("status")}
    body = r.get("body", {})
    tags = body.get("tags", [])
    if not tags:
        return {"candidates": []}

    accept = (
        "application/vnd.docker.distribution.manifest.v2+json, "
        "application/vnd.oci.image.manifest.v1+json"
    )
    now = time.time()
    cutoff = now - older_than_days * 86400
    tag_info = []
    for tag in tags:
        mr = _registry_request(f"/v2/{name}/manifests/{tag}", accept=accept)
        if "error" in mr:
            tag_info.append({"tag": tag, "created": None, "error": mr["error"]})
            continue
        manifest = mr.get("body") if isinstance(mr.get("body"), dict) else {}
        config_digest = ""
        config_obj = manifest.get("config", {})
        if isinstance(config_obj, dict):
            config_digest = config_obj.get("digest", "")
        created = None
        created_ts = None
        if config_digest:
            cr = _registry_request(f"/v2/{name}/blobs/{config_digest}")
            if "error" not in cr and isinstance(cr.get("body"), dict):
                created = cr["body"].get("created")
        if created:
            try:
                from email.utils import parsedate_to_datetime
                # ISO format
                created_ts = _parse_iso_timestamp(created)
            except Exception:
                pass
        tag_info.append({"tag": tag, "created": created, "created_ts": created_ts})

    # Sort by created descending
    tag_info.sort(key=lambda x: x.get("created_ts") or 0, reverse=True)

    # Keep latest K, exclude from candidates
    protected = set()
    for entry in tag_info[:keep_latest]:
        protected.add(entry["tag"])

    candidates = []
    for entry in tag_info:
        if entry["tag"] in protected:
            continue
        ts = entry.get("created_ts")
        if ts is not None and ts < cutoff:
            candidates.append(entry)
        elif ts is None:
            candidates.append(entry)  # unknown age -> candidate

    # Clean internal field
    for c in candidates:
        c.pop("created_ts", None)

    return {"candidates": candidates, "total_tags": len(tags), "kept_latest": keep_latest}


def _parse_iso_timestamp(s):
    """Parse ISO 8601 timestamp to epoch seconds."""
    import re
    s = s.strip()
    # Handle Z suffix
    s = s.replace("Z", "+00:00")
    # Remove fractional seconds beyond microseconds
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(s)
        return dt.timestamp()
    except Exception:
        return None


def tool_check_health(params):
    r = _registry_request("/v2/")
    if "error" in r:
        return {
            "healthy": False,
            "error": r["error"],
            "status": r.get("status"),
        }
    headers = r.get("headers", {})
    version = ""
    for h_name, h_val in headers.items():
        if h_name.lower() == "docker-distribution-api-version":
            version = h_val
            break
    return {
        "healthy": r.get("status") == 200,
        "status": r.get("status"),
        "api_version": version,
        "registry_url": REGISTRY_URL,
    }


# ---------- tool definitions ----------

TOOLS = [
    {
        "name": "list_repositories",
        "description": "List all repositories in the registry (GET /v2/_catalog)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "description": "Limit number of results"},
                "last": {"type": "string", "description": "Start from this repository for pagination"},
            },
        },
    },
    {
        "name": "list_tags",
        "description": "List tags for a repository (GET /v2/{name}/tags/list)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Repository name"},
                "n": {"type": "integer", "description": "Limit number of results"},
                "last": {"type": "string", "description": "Start from this tag for pagination"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_manifest",
        "description": "Get image manifest for a repository tag or digest",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Repository name"},
                "reference": {"type": "string", "description": "Tag or digest"},
            },
            "required": ["name", "reference"],
        },
    },
    {
        "name": "get_blob",
        "description": "Fetch blob metadata (HEAD /v2/{name}/blobs/{digest})",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Repository name"},
                "digest": {"type": "string", "description": "Blob digest (sha256:...)"},
            },
            "required": ["name", "digest"],
        },
    },
    {
        "name": "delete_tag",
        "description": "Delete a tag or manifest by reference (resolves digest first)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Repository name"},
                "reference": {"type": "string", "description": "Tag or digest to delete"},
            },
            "required": ["name", "reference"],
        },
    },
    {
        "name": "get_image_size",
        "description": "Calculate total image size (config + all layers)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Repository name"},
                "reference": {"type": "string", "description": "Tag or digest (default: latest)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_tag_history",
        "description": "List tags sorted by creation date (from manifest config)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Repository name"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "gc_candidates",
        "description": "Find tags eligible for garbage collection (older than N days, exclude latest K)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Repository name"},
                "older_than_days": {"type": "integer", "description": "Minimum age in days (default: 30)"},
                "keep_latest": {"type": "integer", "description": "Keep this many newest tags (default: 1)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "check_health",
        "description": "Check registry health (ping /v2/ endpoint)",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

TOOL_DISPATCH = {
    "list_repositories": tool_list_repositories,
    "list_tags": tool_list_tags,
    "get_manifest": tool_get_manifest,
    "get_blob": tool_get_blob,
    "delete_tag": tool_delete_tag,
    "get_image_size": tool_get_image_size,
    "get_tag_history": tool_get_tag_history,
    "gc_candidates": tool_gc_candidates,
    "check_health": tool_check_health,
}


# ---------- JSON-RPC dispatch ----------

def handle_request(msg):
    method = msg.get("method", "")
    params = msg.get("params", {})
    req_id = msg.get("id")

    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "notifications/initialized":
        return None  # no response for notifications

    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if tool_name not in TOOL_DISPATCH:
            return make_error(req_id, -32601, f"unknown tool: {tool_name}")
        try:
            result = TOOL_DISPATCH[tool_name](arguments)
            return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
        except Exception as e:
            return make_error(req_id, -32603, str(e))

    if method == "ping":
        return make_response(req_id, {})

    return make_error(req_id, -32601, f"method not found: {method}")


# ---------- main loop ----------

def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = make_error(None, -32700, "parse error")
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_request(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
