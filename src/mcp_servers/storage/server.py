#!/usr/bin/env python3
"""MCP server for S3-compatible object storage. stdlib only."""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import formatdate, parsedate_to_datetime

# ── Environment ──────────────────────────────────────────────────────────────

ENDPOINT = os.environ.get("STORAGE_ENDPOINT", "http://localhost:9000").rstrip("/")
BUCKET = os.environ.get("STORAGE_BUCKET", "default")
ACCESS_KEY = os.environ.get("STORAGE_ACCESS_KEY", "")
SECRET_KEY = os.environ.get("STORAGE_SECRET_KEY", "")
REGION = os.environ.get("STORAGE_REGION", "us-east-1")

# ── JSON-RPC helpers ─────────────────────────────────────────────────────────

def make_response(req_id, result):
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n"


def make_error(req_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "error": err}) + "\n"


# ── S3 signing (AWS Signature Version 2) ─────────────────────────────────────

def _sign(string_to_sign):
    return base64.b64encode(
        hmac.new(SECRET_KEY.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()


def _amz_date():
    return formatdate(usegmt=True)


def s3_request(method, path, query=None, headers=None, body=None, bucket=None):
    """Execute signed S3 request. Returns (status, response_headers, body_bytes)."""
    bucket = bucket or BUCKET
    headers = dict(headers or {})
    query = query or {}
    date_str = _amz_date()
    headers["Date"] = date_str

    host = ENDPOINT.replace("http://", "").replace("https://", "")
    resource = f"/{bucket}{path}"

    canonical_qs = ""
    subresources = {"acl", "lifecycle", "location", "logging", "notification",
                    "partNumber", "policy", "requestPayment", "response-content-type",
                    "response-content-language", "response-expires",
                    "response-cache-control", "response-content-disposition",
                    "response-content-encoding", "uploadId", "uploads", "versionId",
                    "versioning", "versions", "delete"}
    if query:
        filtered = {k: v for k, v in query.items() if k in subresources}
        if filtered:
            parts = []
            for k in sorted(filtered):
                parts.append(k if filtered[k] is None else f"{k}={filtered[k]}")
            canonical_qs = "?" + "&".join(parts)

    string_to_sign = f"{method}\n\n\n{date_str}\n{resource}{canonical_qs}"
    headers["Authorization"] = f"AWS {ACCESS_KEY}:{_sign(string_to_sign)}"

    qs = urllib.parse.urlencode(query) if query else ""
    url = f"{ENDPOINT}{resource}"
    if qs:
        url += f"?{qs}"

    req = urllib.request.Request(url, data=body, method=method)
    for k, v in headers.items():
        req.add_header(k, v)

    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
    except Exception as e:
        return 0, {}, str(e).encode()


def _xml_text(root, tag, default=""):
    el = root.find(tag)
    return el.text if el is not None and el.text else default


# ── Tool implementations ─────────────────────────────────────────────────────

def tool_list_buckets(args):
    status, _, body = s3_request("GET", "/", bucket="")
    if status == 0:
        return {"error": f"Connection failed: {body.decode()}"}
    if status != 200:
        return {"error": f"HTTP {status}", "detail": body.decode(errors="replace")[:500]}
    root = ET.fromstring(body)
    ns = ""
    tag = root.tag
    if "}" in tag:
        ns = tag[:tag.index("}") + 1]
    buckets = []
    for b in root.findall(f".//{ns}Bucket") or root.findall(".//Bucket"):
        name = (b.find(f"{ns}Name") or b.find("Name"))
        created = (b.find(f"{ns}CreationDate") or b.find("CreationDate"))
        buckets.append({
            "name": name.text if name is not None else "",
            "created": created.text if created is not None else ""
        })
    return {"buckets": buckets}


def tool_list_objects(args):
    prefix = args.get("prefix", "")
    delimiter = args.get("delimiter", "/")
    limit = min(int(args.get("limit", 100)), 1000)
    marker = args.get("marker", "")
    bucket = args.get("bucket")

    query = {"max-keys": str(limit)}
    if prefix:
        query["prefix"] = prefix
    if delimiter:
        query["delimiter"] = delimiter
    if marker:
        query["marker"] = marker

    status, _, body = s3_request("GET", "/", query=query, bucket=bucket)
    if status != 200:
        return {"error": f"HTTP {status}", "detail": body.decode(errors="replace")[:500]}

    root = ET.fromstring(body)
    ns = ""
    tag = root.tag
    if "}" in tag:
        ns = tag[:tag.index("}") + 1]

    objects = []
    for c in root.findall(f".//{ns}Contents") or root.findall(".//Contents"):
        key_el = c.find(f"{ns}Key") or c.find("Key")
        size_el = c.find(f"{ns}Size") or c.find("Size")
        mod_el = c.find(f"{ns}LastModified") or c.find("LastModified")
        etag_el = c.find(f"{ns}ETag") or c.find("ETag")
        objects.append({
            "key": key_el.text if key_el is not None else "",
            "size": int(size_el.text) if size_el is not None else 0,
            "lastModified": mod_el.text if mod_el is not None else "",
            "etag": etag_el.text if etag_el is not None else ""
        })

    prefixes = []
    for p in root.findall(f".//{ns}CommonPrefixes/{ns}Prefix") or []:
        prefixes.append(p.text or "")
    for p in root.findall(".//CommonPrefixes/Prefix") or []:
        prefixes.append(p.text or "")

    is_truncated_el = root.find(f"{ns}IsTruncated") or root.find("IsTruncated")
    is_truncated = is_truncated_el.text == "true" if is_truncated_el is not None else False

    return {
        "objects": objects,
        "commonPrefixes": prefixes,
        "isTruncated": is_truncated,
        "prefix": prefix,
        "delimiter": delimiter
    }


def tool_get_object(args):
    key = args.get("key", "")
    bucket = args.get("bucket")
    if not key:
        return {"error": "key is required"}

    status, headers, body = s3_request("GET", f"/{urllib.parse.quote(key, safe='')}", bucket=bucket)
    if status != 200:
        return {"error": f"HTTP {status}", "detail": body.decode(errors="replace")[:500]}

    ct = headers.get("Content-Type", headers.get("content-type", ""))
    is_text = any(t in ct.lower() for t in ["text/", "json", "xml", "csv", "javascript", "yaml"])
    if not is_text and status == 200:
        try:
            text = body.decode("utf-8")
            is_text = True
        except UnicodeDecodeError:
            is_text = False

    if is_text:
        return {
            "key": key,
            "content": body.decode("utf-8", errors="replace"),
            "size": len(body),
            "contentType": ct
        }
    return {
        "key": key,
        "contentBase64": base64.b64encode(body).decode(),
        "size": len(body),
        "contentType": ct
    }


def tool_put_object(args):
    key = args.get("key", "")
    content = args.get("content", "")
    content_type = args.get("contentType", "application/octet-stream")
    bucket = args.get("bucket")
    if not key:
        return {"error": "key is required"}

    data = content.encode("utf-8")
    headers = {"Content-Type": content_type, "Content-Length": str(len(data))}

    status, _, body = s3_request("PUT", f"/{urllib.parse.quote(key, safe='')}",
                                 headers=headers, body=data, bucket=bucket)
    if status not in (200, 201, 204):
        return {"error": f"HTTP {status}", "detail": body.decode(errors="replace")[:500]}

    return {"key": key, "size": len(data), "status": "uploaded"}


def tool_delete_object(args):
    key = args.get("key", "")
    bucket = args.get("bucket")
    if not key:
        return {"error": "key is required"}

    status, _, body = s3_request("DELETE", f"/{urllib.parse.quote(key, safe='')}", bucket=bucket)
    if status not in (200, 202, 204):
        return {"error": f"HTTP {status}", "detail": body.decode(errors="replace")[:500]}

    return {"key": key, "status": "deleted"}


def tool_get_object_metadata(args):
    key = args.get("key", "")
    bucket = args.get("bucket")
    if not key:
        return {"error": "key is required"}

    status, headers, _ = s3_request("HEAD", f"/{urllib.parse.quote(key, safe='')}", bucket=bucket)
    if status != 200:
        return {"error": f"HTTP {status}"}

    meta = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk.startswith("x-amz-meta-"):
            meta[lk[len("x-amz-meta-"):]] = v

    return {
        "key": key,
        "size": int(headers.get("Content-Length", headers.get("content-length", 0))),
        "contentType": headers.get("Content-Type", headers.get("content-type", "")),
        "lastModified": headers.get("Last-Modified", headers.get("last-modified", "")),
        "etag": headers.get("ETag", headers.get("etag", "")),
        "metadata": meta
    }


def tool_get_presigned_url(args):
    key = args.get("key", "")
    expires = min(int(args.get("expires", 3600)), 604800)
    method = args.get("method", "GET").upper()
    bucket = args.get("bucket")
    if not key:
        return {"error": "key is required"}

    date_str = _amz_date()
    resource = f"/{bucket or BUCKET}/{urllib.parse.quote(key, safe='')}"

    string_to_sign = f"{method}\n\n\n{date_str}\n{resource}"
    sig = urllib.parse.quote(_sign(string_to_sign))

    url = f"{ENDPOINT}{resource}?AWSAccessKeyId={urllib.parse.quote(ACCESS_KEY)}&Expires={expires}&Signature={sig}"
    return {"url": url, "key": key, "expires": expires, "method": method}


def tool_copy_object(args):
    source_key = args.get("sourceKey", "")
    dest_key = args.get("destKey", "")
    source_bucket = args.get("sourceBucket")
    dest_bucket = args.get("destBucket")
    if not source_key or not dest_key:
        return {"error": "sourceKey and destKey are required"}

    src = f"/{source_bucket or BUCKET}/{source_key}"
    headers = {"x-amz-copy-source": urllib.parse.quote(src, safe="/:")}

    status, _, body = s3_request("PUT", f"/{urllib.parse.quote(dest_key, safe='')}",
                                 headers=headers, bucket=dest_bucket)
    if status not in (200, 201):
        return {"error": f"HTTP {status}", "detail": body.decode(errors="replace")[:500]}

    return {"sourceKey": source_key, "destKey": dest_key, "status": "copied"}


def tool_get_bucket_stats(args):
    bucket = args.get("bucket")
    all_objects = []
    marker = ""
    while True:
        query = {"max-keys": "1000"}
        if marker:
            query["marker"] = marker
        status, _, body = s3_request("GET", "/", query=query, bucket=bucket)
        if status != 200:
            return {"error": f"HTTP {status}"}

        root = ET.fromstring(body)
        ns = ""
        tag = root.tag
        if "}" in tag:
            ns = tag[:tag.index("}") + 1]

        batch = []
        for c in root.findall(f".//{ns}Contents") or root.findall(".//Contents"):
            key_el = c.find(f"{ns}Key") or c.find("Key")
            size_el = c.find(f"{ns}Size") or c.find("Size")
            k = key_el.text if key_el is not None else ""
            s = int(size_el.text) if size_el is not None else 0
            batch.append({"key": k, "size": s})

        all_objects.extend(batch)
        is_truncated_el = root.find(f"{ns}IsTruncated") or root.find("IsTruncated")
        is_truncated = is_truncated_el.text == "true" if is_truncated_el is not None else False
        if not is_truncated or not batch:
            break
        marker = batch[-1]["key"]

    total_size = sum(o["size"] for o in all_objects)
    largest = sorted(all_objects, key=lambda x: x["size"], reverse=True)[:10]

    return {
        "bucket": bucket or BUCKET,
        "objectCount": len(all_objects),
        "totalSize": total_size,
        "totalSizeHuman": _human_size(total_size),
        "largestObjects": largest
    }


def tool_check_health(args):
    result = {"endpoint": ENDPOINT}
    status, hdrs, body = s3_request("GET", "/", bucket="")
    result["reachable"] = status != 0
    if status == 0:
        result["error"] = body.decode(errors="replace")[:300]
        return result
    result["status"] = status
    if status == 200:
        root = ET.fromstring(body)
        ns = ""
        tag = root.tag
        if "}" in tag:
            ns = tag[:tag.index("}") + 1]
        owner = root.find(f".//{ns}DisplayName") or root.find(".//DisplayName")
        result["owner"] = owner.text if owner is not None else "unknown"
        buckets = root.findall(f".//{ns}Bucket") or root.findall(".//Bucket")
        result["bucketCount"] = len(buckets)
        result["auth"] = "ok"
    elif status == 403:
        result["auth"] = "failed (403 Forbidden)"
    else:
        result["auth"] = f"unexpected status {status}"
    return result


def _human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ── Tool registry ─────────────────────────────────────────────────────────────

TOOLS = {
    "list_buckets": {
        "description": "List all available S3 buckets",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": tool_list_buckets
    },
    "list_objects": {
        "description": "List objects in a bucket with optional prefix, delimiter, and limit",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prefix": {"type": "string", "description": "Object key prefix filter"},
                "delimiter": {"type": "string", "description": "Delimiter for grouping (default /)"},
                "limit": {"type": "integer", "description": "Max objects to return (default 100, max 1000)"},
                "marker": {"type": "string", "description": "Pagination marker"},
                "bucket": {"type": "string", "description": "Bucket name (default from env)"}
            },
            "required": []
        },
        "handler": tool_list_objects
    },
    "get_object": {
        "description": "Download object content. Text files returned as string, binary as base64.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Object key"},
                "bucket": {"type": "string", "description": "Bucket name (default from env)"}
            },
            "required": ["key"]
        },
        "handler": tool_get_object
    },
    "put_object": {
        "description": "Upload text content as an object",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Object key"},
                "content": {"type": "string", "description": "Text content to upload"},
                "contentType": {"type": "string", "description": "MIME type (default application/octet-stream)"},
                "bucket": {"type": "string", "description": "Bucket name (default from env)"}
            },
            "required": ["key", "content"]
        },
        "handler": tool_put_object
    },
    "delete_object": {
        "description": "Delete an object from a bucket",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Object key to delete"},
                "bucket": {"type": "string", "description": "Bucket name (default from env)"}
            },
            "required": ["key"]
        },
        "handler": tool_delete_object
    },
    "get_object_metadata": {
        "description": "Get object metadata via HEAD request (size, content-type, last-modified, etag, user metadata)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Object key"},
                "bucket": {"type": "string", "description": "Bucket name (default from env)"}
            },
            "required": ["key"]
        },
        "handler": tool_get_object_metadata
    },
    "get_presigned_url": {
        "description": "Generate a presigned URL for temporary access to an object",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Object key"},
                "method": {"type": "string", "description": "HTTP method (default GET)"},
                "expires": {"type": "integer", "description": "URL expiry in seconds (default 3600, max 604800)"},
                "bucket": {"type": "string", "description": "Bucket name (default from env)"}
            },
            "required": ["key"]
        },
        "handler": tool_get_presigned_url
    },
    "copy_object": {
        "description": "Copy an object to a new key and/or bucket",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sourceKey": {"type": "string", "description": "Source object key"},
                "destKey": {"type": "string", "description": "Destination object key"},
                "sourceBucket": {"type": "string", "description": "Source bucket (default from env)"},
                "destBucket": {"type": "string", "description": "Destination bucket (default from env)"}
            },
            "required": ["sourceKey", "destKey"]
        },
        "handler": tool_copy_object
    },
    "get_bucket_stats": {
        "description": "Get bucket statistics: object count, total size, largest objects",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bucket": {"type": "string", "description": "Bucket name (default from env)"}
            },
            "required": []
        },
        "handler": tool_get_bucket_stats
    },
    "check_health": {
        "description": "Verify storage endpoint is reachable, authentication works, and list buckets",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": tool_check_health
    },
}


# ── MCP protocol handlers ─────────────────────────────────────────────────────

def handle_initialize(params, req_id):
    return make_response(req_id, {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "storage", "version": "1.0.0"}
    })


def handle_tools_list(params, req_id):
    tools = []
    for name, t in TOOLS.items():
        tools.append({
            "name": name,
            "description": t["description"],
            "inputSchema": t["inputSchema"]
        })
    return make_response(req_id, {"tools": tools})


def handle_tools_call(params, req_id):
    name = params.get("name", "")
    args = params.get("arguments", {})
    if name not in TOOLS:
        return make_error(req_id, -32601, f"Unknown tool: {name}")
    try:
        result = TOOLS[name]["handler"](args)
        return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
    except Exception as e:
        return make_response(req_id, {
            "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
            "isError": True
        })


METHODS = {
    "initialize": handle_initialize,
    "notifications/initialized": lambda p, r: None,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
}


# ── Main loop ─────────────────────────────────────────────────────────────────

async def main():
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, asyncio.get_event_loop())

    while True:
        line = await reader.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            writer.write(make_error(None, -32700, "Parse error").encode())
            await writer.drain()
            continue

        req_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {})

        handler = METHODS.get(method)
        if handler is None:
            writer.write(make_error(req_id, -32601, f"Method not found: {method}").encode())
            await writer.drain()
            continue

        result = handler(params, req_id)
        if result is not None:
            writer.write(result.encode())
            await writer.drain()


if __name__ == "__main__":
    asyncio.run(main())
