#!/usr/bin/env python3
"""MCP server for OWASP ZAP API (zap_proxy)."""

import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "zap_proxy"
SERVER_VERSION = "1.0.0"

ZAP_URL = os.environ.get("ZAP_URL", "http://localhost:8080")
ZAP_API_KEY = os.environ.get("ZAP_API_KEY", "")


def log_err(msg):
    print(msg, file=sys.stderr, flush=True)


def zap_get(path, params=None):
    """GET request to ZAP API, return parsed JSON."""
    qs = {"apikey": ZAP_API_KEY}
    if params:
        qs.update(params)
    url = ZAP_URL + path + "?" + urllib.parse.urlencode(qs)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.URLError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


def make_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


# --- Tool definitions ---

TOOLS = [
    {
        "name": "start_spider",
        "description": "Start ZAP spider scan on a target URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL to spider"},
                "maxChildren": {"type": "integer", "description": "Max children to crawl (optional)"},
                "recurse": {"type": "boolean", "description": "Recurse into children (default true)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "start_active_scan",
        "description": "Start ZAP active scan on a target URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL to scan"},
                "recurse": {"type": "boolean", "description": "Recurse (default true)"},
                "inScopeOnly": {"type": "boolean", "description": "Scan only in-scope (optional)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "get_scan_status",
        "description": "Get scan progress percentage for spider or active scan.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scanType": {
                    "type": "string",
                    "enum": ["spider", "ascan"],
                    "description": "Type of scan: 'spider' or 'ascan'",
                },
                "scanId": {"type": "integer", "description": "Scan ID (optional, uses first active if omitted)"},
            },
            "required": ["scanType"],
        },
    },
    {
        "name": "get_alerts",
        "description": "Get ZAP alerts filtered by risk level.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "baseurl": {"type": "string", "description": "Base URL to filter alerts (optional)"},
                "riskId": {
                    "type": "string",
                    "enum": ["0", "1", "2", "3"],
                    "description": "Risk level: 0=info, 1=low, 2=medium, 3=high (optional, all if omitted)",
                },
                "start": {"type": "integer", "description": "Pagination start position (optional)"},
                "count": {"type": "integer", "description": "Max number of alerts to return (optional)"},
            },
        },
    },
    {
        "name": "get_scan_results",
        "description": "Get full scan results: URLs scanned, alerts found, statistics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "baseurl": {"type": "string", "description": "Base URL to filter results (optional)"},
            },
        },
    },
    {
        "name": "get_report",
        "description": "Generate a ZAP report in HTML, XML, or JSON format.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["html", "xml", "json"],
                    "description": "Report format (default json)",
                },
                "title": {"type": "string", "description": "Report title (optional)"},
                "description": {"type": "string", "description": "Report description (optional)"},
            },
        },
    },
    {
        "name": "scan_url",
        "description": "One-shot full scan: spider + active scan + wait + get results.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL to scan"},
                "maxChildren": {"type": "integer", "description": "Max children for spider (optional)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "check_health",
        "description": "Check ZAP API connectivity, version, and mode.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# --- Tool implementations ---

def _poll_until_done(scan_type, scan_id, interval=2, timeout=600):
    """Poll scan status until 100% or timeout. Returns final status dict."""
    import time
    elapsed = 0
    while elapsed < timeout:
        if scan_type == "spider":
            data = zap_get("/JSON/spider/view/status/", {"scanId": str(scan_id)})
        else:
            data = zap_get("/JSON/ascan/view/status/", {"scanId": str(scan_id)})
        status = data.get("status", "0")
        if status == "100" or data.get("error"):
            return data
        time.sleep(interval)
        elapsed += interval
    return {"error": "timeout", "status": status}


def tool_start_spider(args):
    url = args.get("url")
    params = {"url": url}
    if "maxChildren" in args:
        params["maxChildren"] = str(args["maxChildren"])
    if "recurse" in args:
        params["recurse"] = str(args["recurse"]).lower()
    data = zap_get("/JSON/spider/action/scan/", params)
    scan_id = data.get("scan", data.get("scanId", "-1"))
    return {"scanId": scan_id, "status": "started", "url": url, "raw": data}


def tool_start_active_scan(args):
    url = args.get("url")
    params = {"url": url}
    if "recurse" in args:
        params["recurse"] = str(args["recurse"]).lower()
    if "inScopeOnly" in args:
        params["inScopeOnly"] = str(args["inScopeOnly"]).lower()
    data = zap_get("/JSON/ascan/action/scan/", params)
    scan_id = data.get("scan", data.get("scanId", "-1"))
    return {"scanId": scan_id, "status": "started", "url": url, "raw": data}


def tool_get_scan_status(args):
    scan_type = args.get("scanType", "spider")
    params = {}
    if "scanId" in args:
        params["scanId"] = str(args["scanId"])
    if scan_type == "spider":
        data = zap_get("/JSON/spider/view/status/", params)
        # Also get spider results count
        results = zap_get("/JSON/spider/view/results/", params if params else None)
        return {"status": data.get("status", "0"), "resultsCount": len(results.get("results", [])), "raw": data}
    else:
        data = zap_get("/JSON/ascan/view/status/", params)
        scans = zap_get("/JSON/ascan/view/scans/", None)
        return {"status": data.get("status", "0"), "scans": scans.get("scans", []), "raw": data}


def tool_get_alerts(args):
    params = {}
    if "baseurl" in args:
        params["baseurl"] = args["baseurl"]
    if "riskId" in args:
        params["riskId"] = args["riskId"]
    if "start" in args:
        params["start"] = str(args["start"])
    if "count" in args:
        params["count"] = str(args["count"])
    data = zap_get("/JSON/core/view/alerts/", params)
    alerts = data.get("alerts", [])
    summary = {}
    for a in alerts:
        risk = a.get("risk", "unknown")
        summary[risk] = summary.get(risk, 0) + 1
    return {"totalAlerts": len(alerts), "summary": summary, "alerts": alerts}


def tool_get_scan_results(args):
    params = {}
    if "baseurl" in args:
        params["baseurl"] = args["baseurl"]
    urls_data = zap_get("/JSON/core/view/urls/", params)
    alerts_data = zap_get("/JSON/core/view/alerts/", params)
    stats = zap_get("/JSON/stats/view/allSitesStats/", None)
    urls = urls_data.get("urls", [])
    alerts = alerts_data.get("alerts", [])
    summary = {}
    for a in alerts:
        risk = a.get("risk", "unknown")
        summary[risk] = summary.get(risk, 0) + 1
    return {
        "urlsScanned": len(urls),
        "urls": urls,
        "totalAlerts": len(alerts),
        "alertsSummary": summary,
        "alerts": alerts,
        "statistics": stats,
    }


def tool_get_report(args):
    fmt = args.get("format", "json")
    title = args.get("title", "ZAP Scan Report")
    desc = args.get("description", "")
    if fmt == "html":
        path = "/OTHER/core/other/htmlreport/"
    elif fmt == "xml":
        path = "/OTHER/core/other/xmlreport/"
    else:
        path = "/OTHER/core/other/jsonreport/"

    qs = urllib.parse.urlencode({"apikey": ZAP_API_KEY})
    url = ZAP_URL + path + "?" + qs
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        if fmt == "json":
            body = json.loads(body)
        return {"format": fmt, "report": body}
    except Exception as e:
        return {"error": str(e), "format": fmt}


def tool_scan_url(args):
    import time
    url = args.get("url")
    max_children = args.get("maxChildren")

    # Start spider
    spider_params = {"url": url}
    if max_children:
        spider_params["maxChildren"] = str(max_children)
    spider_data = zap_get("/JSON/spider/action/scan/", spider_params)
    spider_id = spider_data.get("scan", spider_data.get("scanId", "-1"))
    if spider_data.get("error"):
        return {"phase": "spider", "error": spider_data["error"]}

    # Wait for spider
    poll_elapsed = 0
    while poll_elapsed < 300:
        status_data = zap_get("/JSON/spider/view/status/", {"scanId": str(spider_id)})
        if status_data.get("status") == "100" or status_data.get("error"):
            break
        time.sleep(2)
        poll_elapsed += 2

    spider_results = zap_get("/JSON/spider/view/results/", {"scanId": str(spider_id)})

    # Start active scan
    ascan_data = zap_get("/JSON/ascan/action/scan/", {"url": url})
    ascan_id = ascan_data.get("scan", ascan_data.get("scanId", "-1"))
    if ascan_data.get("error"):
        return {"phase": "ascan", "spiderId": spider_id, "error": ascan_data["error"]}

    # Wait for active scan
    poll_elapsed = 0
    while poll_elapsed < 600:
        status_data = zap_get("/JSON/ascan/view/status/", {"scanId": str(ascan_id)})
        if status_data.get("status") == "100" or status_data.get("error"):
            break
        time.sleep(3)
        poll_elapsed += 3

    # Gather results
    alerts_data = zap_get("/JSON/core/view/alerts/", {"baseurl": url})
    urls_data = zap_get("/JSON/core/view/urls/", {"baseurl": url})
    alerts = alerts_data.get("alerts", [])
    summary = {}
    for a in alerts:
        risk = a.get("risk", "unknown")
        summary[risk] = summary.get(risk, 0) + 1

    return {
        "url": url,
        "spiderScanId": spider_id,
        "ascanScanId": ascan_id,
        "urlsFound": len(spider_results.get("results", [])),
        "urlsScanned": len(urls_data.get("urls", [])),
        "totalAlerts": len(alerts),
        "alertsSummary": summary,
        "alerts": alerts,
    }


def tool_check_health(args):
    version = zap_get("/JSON/core/view/version/", None)
    mode = zap_get("/JSON/core/view/mode/", None)
    # Try a lightweight call to verify connectivity
    ok = "error" not in version or "error" not in mode
    # Some ZAP versions may return error for version endpoint
    connectivity = True
    if version.get("error") and mode.get("error"):
        connectivity = False
    return {
        "connected": connectivity,
        "zapUrl": ZAP_URL,
        "version": version.get("version", version.get("error", "unknown")),
        "mode": mode.get("mode", mode.get("error", "unknown")),
    }


TOOL_DISPATCH = {
    "start_spider": tool_start_spider,
    "start_active_scan": tool_start_active_scan,
    "get_scan_status": tool_get_scan_status,
    "get_alerts": tool_get_alerts,
    "get_scan_results": tool_get_scan_results,
    "get_report": tool_get_report,
    "scan_url": tool_scan_url,
    "check_health": tool_check_health,
}


# --- JSON-RPC dispatcher ---

def handle_request(req):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})

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
        fn = TOOL_DISPATCH.get(tool_name)
        if not fn:
            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = fn(arguments)
            return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
        except Exception as e:
            return make_error(req_id, -32000, str(e))

    return make_error(req_id, -32601, f"Method not found: {method}")


async def main():
    """Read JSON-RPC from stdin, write responses to stdout."""
    reader = sys.stdin.buffer
    writer = sys.stdout.buffer

    while True:
        line = reader.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            writer.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}).encode() + b"\n")
            writer.flush()
            continue

        resp = handle_request(req)
        if resp is not None:
            writer.write(json.dumps(resp).encode() + b"\n")
            writer.flush()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
