#!/usr/bin/env python3
"""MCP monitoring server — Prometheus + health checks. Stdio JSON-RPC, stdlib only."""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")
ALERTMANAGER_URL = os.environ.get("ALERTMANAGER_URL", "http://localhost:9093").rstrip("/")

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


def write_json(obj):
    payload = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(payload + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def http_get(url, timeout=10):
    """GET *url*, return (status_code, parsed_json_or_None, error_or_None)."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body), None
            except json.JSONDecodeError:
                return resp.status, body, None
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return exc.code, body, str(exc)
    except Exception as exc:
        return None, None, str(exc)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _prom_json(path, params=None):
    """Query Prometheus API, return tool result dict."""
    qs = urllib.parse.urlencode(params or {})
    url = f"{PROMETHEUS_URL}{path}?{qs}" if qs else f"{PROMETHEUS_URL}{path}"
    status, data, err = http_get(url)
    if err:
        return {"content": [{"type": "text", "text": f"Error: {err}"}], "isError": True}
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)}]}


def _am_json(path, params=None):
    """Query Alertmanager API, return tool result dict."""
    qs = urllib.parse.urlencode(params or {})
    url = f"{ALERTMANAGER_URL}{path}?{qs}" if qs else f"{ALERTMANAGER_URL}{path}"
    status, data, err = http_get(url)
    if err:
        return {"content": [{"type": "text", "text": f"Error: {err}"}], "isError": True}
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)}]}


# 1. prometheus_query
def tool_prometheus_query(args):
    query = args.get("query", "")
    time_ = args.get("time")
    params = {"query": query}
    if time_ is not None:
        params["time"] = str(time_)
    return _prom_json("/api/v1/query", params)


# 2. prometheus_range
def tool_prometheus_range(args):
    params = {
        "query": args.get("query", ""),
        "start": args.get("start", ""),
        "end": args.get("end", ""),
        "step": args.get("step", ""),
    }
    return _prom_json("/api/v1/query_range", params)


# 3. prometheus_series
def tool_prometheus_series(args):
    match = args.get("match", [])
    start = args.get("start")
    end = args.get("end")
    params = []
    for m in match:
        params.append(("match[]", m))
    if start is not None:
        params.append(("start", str(start)))
    if end is not None:
        params.append(("end", str(end)))
    qs = urllib.parse.urlencode(params)
    url = f"{PROMETHEUS_URL}/api/v1/series?{qs}"
    status, data, err = http_get(url)
    if err:
        return {"content": [{"type": "text", "text": f"Error: {err}"}], "isError": True}
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)}]}


# 4. prometheus_labels
def tool_prometheus_labels(args):
    label_name = args.get("label_name")
    start = args.get("start")
    end = args.get("end")
    if label_name:
        path = f"/api/v1/label/{urllib.parse.quote(label_name)}/values"
    else:
        path = "/api/v1/labels"
    params = {}
    if start is not None:
        params["start"] = str(start)
    if end is not None:
        params["end"] = str(end)
    return _prom_json(path, params)


# 5. list_alerts
def tool_list_alerts(_args):
    return _prom_json("/api/v1/alerts")


# 6. list_alert_rules
def tool_list_alert_rules(_args):
    return _prom_json("/api/v1/rules")


# 7. alertmanager_alerts
def tool_alertmanager_alerts(args):
    filters = args.get("filter", [])
    params = []
    for f in filters:
        params.append(("filter", f))
    qs = urllib.parse.urlencode(params)
    url = f"{ALERTMANAGER_URL}/api/v2/alerts?{qs}" if qs else f"{ALERTMANAGER_URL}/api/v2/alerts"
    status, data, err = http_get(url)
    if err:
        return {"content": [{"type": "text", "text": f"Error: {err}"}], "isError": True}
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)}]}


# 8. health_check
def tool_health_check(args):
    endpoints = args.get("endpoints", [])
    if not endpoints:
        endpoints = [
            {"name": "prometheus", "url": f"{PROMETHEUS_URL}/-/healthy"},
            {"name": "alertmanager", "url": f"{ALERTMANAGER_URL}/-/healthy"},
        ]
    results = []
    for ep in endpoints:
        name = ep.get("name", ep.get("url", "unknown"))
        url = ep.get("url", ep.get("name", ""))
        t0 = time.monotonic()
        status, data, err = http_get(url, timeout=5)
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        results.append({
            "name": name,
            "url": url,
            "status": "ok" if err is None and (status is not None and status < 400) else "error",
            "http_code": status,
            "latency_ms": latency_ms,
            "error": err,
        })
    return {"content": [{"type": "text", "text": json.dumps(results, indent=2)}]}


# 9. get_metrics_summary
def tool_get_metrics_summary(args):
    mode = args.get("mode", "cardinality")
    limit = args.get("limit", 20)

    if mode == "cardinality":
        # Fetch label values for __name__ to list metric names, count them
        status, data, err = http_get(f"{PROMETHEUS_URL}/api/v1/label/__name__/values")
        if err:
            return {"content": [{"type": "text", "text": f"Error: {err}"}], "isError": True}
        if isinstance(data, dict) and "data" in data:
            names = data["data"]
        elif isinstance(data, list):
            names = data
        else:
            return {"content": [{"type": "text", "text": json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)}]}

        # Count series per metric
        summary = []
        for name in names[:200]:  # cap to avoid flooding
            st, d2, _ = http_get(
                f"{PROMETHEUS_URL}/api/v1/query?query=count({{'__name__'=\"{name}\"}})",
                timeout=5,
            )
            count = 0
            if isinstance(d2, dict) and "data" in d2 and d2["data"].get("result"):
                try:
                    count = int(float(d2["data"]["result"][0]["value"][1]))
                except (KeyError, IndexError, ValueError):
                    pass
            summary.append({"metric": name, "series": count})

        summary.sort(key=lambda x: x["series"], reverse=True)
        summary = summary[:limit]
        return {"content": [{"type": "text", "text": json.dumps(summary, indent=2)}]}

    # mode == "targets"
    status, data, err = http_get(f"{PROMETHEUS_URL}/api/v1/targets")
    if err:
        return {"content": [{"type": "text", "text": f"Error: {err}"}], "isError": True}
    targets_info = []
    raw = data
    if isinstance(data, dict) and "data" in data:
        raw = data["data"]
    active = raw.get("activeTargets", []) if isinstance(raw, dict) else []
    for t in active[:limit]:
        health = t.get("health", "unknown")
        targets_info.append({
            "instance": t.get("labels", {}).get("instance", t.get("scrapeUrl", "")),
            "job": t.get("labels", {}).get("job", ""),
            "health": health,
            "last_scrape": t.get("lastScrape", ""),
            "scrape_duration_ms": round(t.get("scrapeDurationSeconds", 0) * 1000, 1) if t.get("scrapeDurationSeconds") else None,
        })
    return {"content": [{"type": "text", "text": json.dumps(targets_info, indent=2)}]}


# 10. check_slo
def tool_check_slo(args):
    window = args.get("window", "1h")
    error_metric = args.get("error_metric", 'sum(rate(http_requests_total{status=~"5.."}[{window}])) / sum(rate(http_requests_total[{window}]))')
    latency_metric = args.get("latency_metric", 'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[{window}])) by (le))')
    error_threshold = args.get("error_threshold", 0.01)
    latency_threshold = args.get("latency_threshold", 1.0)

    error_query = error_metric.replace("{window}", window)
    latency_query = latency_metric.replace("{window}", window)

    error_val = None
    latency_val = None

    st, d, err = http_get(f"{PROMETHEUS_URL}/api/v1/query?query={urllib.parse.quote(error_query)}")
    if not err and isinstance(d, dict) and d.get("data", {}).get("result"):
        try:
            error_val = float(d["data"]["result"][0]["value"][1])
        except (KeyError, IndexError, ValueError):
            pass

    st, d, err = http_get(f"{PROMETHEUS_URL}/api/v1/query?query={urllib.parse.quote(latency_query)}")
    if not err and isinstance(d, dict) and d.get("data", {}).get("result"):
        try:
            latency_val = float(d["data"]["result"][0]["value"][1])
        except (KeyError, IndexError, ValueError):
            pass

    error_ok = error_val is not None and error_val <= error_threshold
    latency_ok = latency_val is not None and latency_val <= latency_threshold
    slo_met = error_ok and latency_ok

    result = {
        "window": window,
        "error_rate": error_val,
        "error_threshold": error_threshold,
        "error_slo_met": error_ok,
        "latency_p99": latency_val,
        "latency_threshold_seconds": latency_threshold,
        "latency_slo_met": latency_ok,
        "slo_met": slo_met,
    }
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "prometheus_query",
        "description": "Execute an instant PromQL query against Prometheus.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "PromQL expression"},
                "time": {"type": "string", "description": "Evaluation timestamp (RFC3339 or Unix)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "prometheus_range",
        "description": "Execute a range PromQL query against Prometheus.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "PromQL expression"},
                "start": {"type": "string", "description": "Start timestamp"},
                "end": {"type": "string", "description": "End timestamp"},
                "step": {"type": "string", "description": "Query resolution step (e.g. '15s')"},
            },
            "required": ["query", "start", "end", "step"],
        },
    },
    {
        "name": "prometheus_series",
        "description": "Find time series matching label matchers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "match": {"type": "array", "items": {"type": "string"}, "description": "Label matchers (e.g. ['{job=\"nginx\"}'])"},
                "start": {"type": "string", "description": "Start timestamp"},
                "end": {"type": "string", "description": "End timestamp"},
            },
            "required": ["match"],
        },
    },
    {
        "name": "prometheus_labels",
        "description": "List label names or values for a label.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "label_name": {"type": "string", "description": "Label name; omit to list all label names"},
                "start": {"type": "string"},
                "end": {"type": "string"},
            },
        },
    },
    {
        "name": "list_alerts",
        "description": "List current firing and pending alerts from Prometheus.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_alert_rules",
        "description": "List all alerting and recording rules from Prometheus.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "alertmanager_alerts",
        "description": "List alerts currently in Alertmanager.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filter": {"type": "array", "items": {"type": "string"}, "description": "Alertmanager filter expressions"},
            },
        },
    },
    {
        "name": "health_check",
        "description": "Check health of monitoring endpoints (Prometheus, Alertmanager, custom). Returns status + latency.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "endpoints": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                    "description": "Endpoints to check. Defaults to Prometheus and Alertmanager.",
                },
            },
        },
    },
    {
        "name": "get_metrics_summary",
        "description": "Top N metrics by cardinality or scrape target health overview.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["cardinality", "targets"], "description": "'cardinality' for top metrics, 'targets' for scrape health"},
                "limit": {"type": "integer", "description": "Max items to return (default 20)"},
            },
        },
    },
    {
        "name": "check_slo",
        "description": "Calculate SLO compliance: query error rate and latency metrics over a time window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "window": {"type": "string", "description": "Prometheus range window (default '1h')"},
                "error_metric": {"type": "string", "description": "PromQL for error rate (use {window} placeholder)"},
                "latency_metric": {"type": "string", "description": "PromQL for latency percentile (use {window} placeholder)"},
                "error_threshold": {"type": "number", "description": "Max acceptable error rate (default 0.01)"},
                "latency_threshold": {"type": "number", "description": "Max acceptable p99 latency in seconds (default 1.0)"},
            },
        },
    },
]

TOOL_DISPATCH = {
    "prometheus_query": tool_prometheus_query,
    "prometheus_range": tool_prometheus_range,
    "prometheus_series": tool_prometheus_series,
    "prometheus_labels": tool_prometheus_labels,
    "list_alerts": tool_list_alerts,
    "list_alert_rules": tool_list_alert_rules,
    "alertmanager_alerts": tool_alertmanager_alerts,
    "health_check": tool_health_check,
    "get_metrics_summary": tool_get_metrics_summary,
    "check_slo": tool_check_slo,
}

SERVER_INFO = {
    "protocolVersion": "2024-11-05",
    "capabilities": {"tools": {"listChanged": False}},
    "serverInfo": {"name": "monitoring", "version": "1.0.0"},
}


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

def handle_request(msg):
    req_id = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params", {})

    # --- notifications (no id → no response) ---
    if req_id is None:
        return None

    # --- initialize ---
    if method == "initialize":
        return make_response(req_id, SERVER_INFO)

    # --- initialized (notification, but we handle defensively) ---
    if method == "notifications/initialized":
        return None

    # --- tools/list ---
    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    # --- tools/call ---
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        handler = TOOL_DISPATCH.get(tool_name)
        if handler is None:
            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = handler(arguments)
            return make_response(req_id, result)
        except Exception as exc:
            return make_error(req_id, -32603, f"Tool execution error: {exc}")

    return make_error(req_id, -32601, f"Method not found: {method}")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def main():
    """Read JSON-RPC from stdin, dispatch, write to stdout."""
    loop = True
    while loop:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            write_json(make_error(None, -32700, "Parse error"))
            continue
        resp = handle_request(msg)
        if resp is not None:
            write_json(resp)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
