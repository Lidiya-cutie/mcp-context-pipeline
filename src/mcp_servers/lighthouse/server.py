#!/usr/bin/env python3
"""MCP server for Google Lighthouse web performance audits.

Protocol: MCP 2024-11-05, JSON-RPC over stdio, stdlib only.
"""

import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DB_PATH = os.environ.get("LIGHTHOUSE_DB_PATH", "/tmp/lighthouse_audit.db")


def make_response(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """CREATE TABLE IF NOT EXISTS audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            category TEXT,
            scores TEXT,
            metrics TEXT,
            raw_json TEXT,
            created_at REAL NOT NULL
        )"""
    )
    con.commit()
    con.close()


def _store_audit(url: str, category: str, scores: str, metrics: str, raw_json: str):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO audits (url, category, scores, metrics, raw_json, created_at) VALUES (?,?,?,?,?,?)",
        (url, category, scores, metrics, raw_json, time.time()),
    )
    con.commit()
    con.close()


def _find_lighthouse() -> str | None:
    for name in ("lighthouse", "lighthouse.exe"):
        path = shutil.which(name)
        if path:
            return path
    return None


async def _run_lighthouse(url: str, categories: list[str], extra_args: list[str] | None = None) -> dict:
    lh = _find_lighthouse()
    if not lh:
        return {
            "error": True,
            "message": "lighthouse CLI not found. Install: npm install -g lighthouse",
        }
    cmd = [lh, url, "--output=json", "--chrome-flags=--headless", "--no-enable-error-reporting"]
    for cat in categories:
        cmd.append(f"--only-categories={cat}")
    if extra_args:
        cmd.extend(extra_args)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        return {"error": True, "message": "Lighthouse audit timed out (120s)"}
    except Exception as exc:
        return {"error": True, "message": f"Failed to run lighthouse: {exc}"}
    if proc.returncode != 0:
        err_text = stderr.decode(errors="replace")[:500]
        return {"error": True, "message": f"Lighthouse exited with code {proc.returncode}: {err_text}"}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"error": True, "message": "Failed to parse lighthouse JSON output"}


def _extract_scores(data: dict) -> dict:
    cats = data.get("categories", {})
    result = {}
    for name, cat in cats.items():
        score = cat.get("score")
        result[name] = round(score * 100, 1) if score is not None else None
    return result


def _extract_metrics(data: dict) -> dict:
    audits = data.get("audits", {})
    keys = {
        "first-contentful-paint": "FCP",
        "largest-contentful-paint": "LCP",
        "total-blocking-time": "TBT",
        "cumulative-layout-shift": "CLS",
        "speed-index": "SI",
        "interactive": "TTI",
    }
    metrics = {}
    for audit_key, label in keys.items():
        a = audits.get(audit_key, {})
        dv = a.get("displayValue", "")
        nv = a.get("numericValue")
        metrics[label] = {"displayValue": dv, "numericValue": nv}
    return metrics


def _extract_accessibility(data: dict) -> dict:
    audits = data.get("audits", {})
    violations = []
    for key, audit in audits.items():
        if audit.get("score") is not None and audit["score"] < 1:
            details = audit.get("details", {})
            if details.get("type") == "table":
                items = details.get("items", [])
                violations.append(
                    {"id": key, "title": audit.get("title", key), "impact": audit.get("score", 0), "items": len(items)}
                )
    return {"violationCount": len(violations), "violations": violations[:30]}


def _extract_seo(data: dict) -> dict:
    audits = data.get("audits", {})
    issues = []
    suggestions = []
    for key, audit in audits.items():
        if audit.get("score") is not None and audit["score"] < 1:
            issues.append({"id": key, "title": audit.get("title", key), "score": audit["score"]})
        elif audit.get("score") == 1 and audit.get("details"):
            suggestions.append({"id": key, "title": audit.get("title", key)})
    return {"issueCount": len(issues), "issues": issues[:30], "suggestions": suggestions[:10]}


def _extract_performance(data: dict) -> dict:
    audits = data.get("audits", {})
    timings = {}
    for key in (
        "first-contentful-paint",
        "largest-contentful-paint",
        "total-blocking-time",
        "cumulative-layout-shift",
        "speed-index",
        "interactive",
        "max-potential-fid",
        "render-blocking-resources",
        "uses-rel-preconnect",
        "uses-rel-preload",
        "uses-text-compression",
        "uses-optimized-images",
        "uses-responsive-images",
        "offscreen-images",
        "unminified-css",
        "unminified-javascript",
        "unused-css-rules",
        "unused-javascript",
        "modern-image-formats",
        "uses-optimized-images",
        "efficient-animated",
    ):
        a = audits.get(key, {})
        if a:
            timings[key] = {
                "title": a.get("title", key),
                "score": a.get("score"),
                "displayValue": a.get("displayValue", ""),
                "numericValue": a.get("numericValue"),
            }
    return timings


# --- Tool implementations ---


async def tool_run_audit(params: dict) -> dict:
    url = params.get("url")
    if not url:
        return {"content": [{"type": "text", "text": "Parameter 'url' is required"}], "isError": True}
    categories = ["performance", "accessibility", "best-practices", "seo", "pwa"]
    data = await _run_lighthouse(url, categories)
    if data.get("error"):
        return {"content": [{"type": "text", "text": data["message"]}], "isError": True}
    scores = _extract_scores(data)
    metrics = _extract_metrics(data)
    _store_audit(url, "full", json.dumps(scores), json.dumps(metrics), json.dumps(data)[:50000])
    text = f"URL: {url}\n\nScores:\n"
    for cat, sc in scores.items():
        text += f"  {cat}: {sc}\n"
    text += "\nMetrics:\n"
    for m, v in metrics.items():
        text += f"  {m}: {v.get('displayValue', 'N/A')}\n"
    return {"content": [{"type": "text", "text": text}]}


async def tool_run_performance(params: dict) -> dict:
    url = params.get("url")
    if not url:
        return {"content": [{"type": "text", "text": "Parameter 'url' is required"}], "isError": True}
    data = await _run_lighthouse(url, ["performance"])
    if data.get("error"):
        return {"content": [{"type": "text", "text": data["message"]}], "isError": True}
    scores = _extract_scores(data)
    timings = _extract_performance(data)
    metrics = _extract_metrics(data)
    _store_audit(url, "performance", json.dumps(scores), json.dumps(metrics), json.dumps(data)[:50000])
    text = f"URL: {url}\nPerformance score: {scores.get('performance', 'N/A')}\n\nDetailed timings:\n"
    for key, val in timings.items():
        sc = val.get("score")
        dv = val.get("displayValue", "")
        title = val.get("title", key)
        sc_str = f"{sc}" if sc is not None else "N/A"
        text += f"  {title}: {dv} (score: {sc_str})\n"
    return {"content": [{"type": "text", "text": text}]}


async def tool_run_accessibility(params: dict) -> dict:
    url = params.get("url")
    if not url:
        return {"content": [{"type": "text", "text": "Parameter 'url' is required"}], "isError": True}
    data = await _run_lighthouse(url, ["accessibility"])
    if data.get("error"):
        return {"content": [{"type": "text", "text": data["message"]}], "isError": True}
    scores = _extract_scores(data)
    a11y = _extract_accessibility(data)
    _store_audit(url, "accessibility", json.dumps(scores), "{}", json.dumps(data)[:50000])
    text = f"URL: {url}\nAccessibility score: {scores.get('accessibility', 'N/A')}\n"
    text += f"Violations: {a11y['violationCount']}\n"
    for v in a11y["violations"]:
        text += f"  - {v['title']} (items: {v['items']})\n"
    return {"content": [{"type": "text", "text": text}]}


async def tool_run_seo(params: dict) -> dict:
    url = params.get("url")
    if not url:
        return {"content": [{"type": "text", "text": "Parameter 'url' is required"}], "isError": True}
    data = await _run_lighthouse(url, ["seo"])
    if data.get("error"):
        return {"content": [{"type": "text", "text": data["message"]}], "isError": True}
    scores = _extract_scores(data)
    seo = _extract_seo(data)
    _store_audit(url, "seo", json.dumps(scores), "{}", json.dumps(data)[:50000])
    text = f"URL: {url}\nSEO score: {scores.get('seo', 'N/A')}\n"
    text += f"Issues: {seo['issueCount']}\n"
    for iss in seo["issues"]:
        text += f"  - {iss['title']} (score: {iss['score']})\n"
    if seo["suggestions"]:
        text += "\nPassed audits (sample):\n"
        for s in seo["suggestions"][:5]:
            text += f"  + {s['title']}\n"
    return {"content": [{"type": "text", "text": text}]}


async def tool_compare_urls(params: dict) -> dict:
    url_a = params.get("url_a")
    url_b = params.get("url_b")
    if not url_a or not url_b:
        return {"content": [{"type": "text", "text": "Parameters 'url_a' and 'url_b' are required"}], "isError": True}
    categories = ["performance", "accessibility", "best-practices", "seo"]
    data_a, data_b = await asyncio.gather(
        _run_lighthouse(url_a, categories),
        _run_lighthouse(url_b, categories),
    )
    errors = []
    if data_a.get("error"):
        errors.append(f"URL A ({url_a}): {data_a['message']}")
    if data_b.get("error"):
        errors.append(f"URL B ({url_b}): {data_b['message']}")
    if errors:
        return {"content": [{"type": "text", "text": "; ".join(errors)}], "isError": True}
    scores_a = _extract_scores(data_a)
    scores_b = _extract_scores(data_b)
    metrics_a = _extract_metrics(data_a)
    metrics_b = _extract_metrics(data_b)
    text = f"Comparison: {url_a} vs {url_b}\n\nScore delta (B - A):\n"
    for cat in sorted(set(scores_a) | set(scores_b)):
        sa = scores_a.get(cat, 0) or 0
        sb = scores_b.get(cat, 0) or 0
        delta = round(sb - sa, 1)
        sign = "+" if delta > 0 else ""
        text += f"  {cat}: {sa} -> {sb} ({sign}{delta})\n"
    text += "\nMetric delta (B - A):\n"
    for m in sorted(set(metrics_a) | set(metrics_b)):
        ma = metrics_a.get(m, {}).get("numericValue", 0) or 0
        mb = metrics_b.get(m, {}).get("numericValue", 0) or 0
        delta = round(mb - ma, 1)
        sign = "+" if delta > 0 else ""
        text += f"  {m}: {ma:.0f} -> {mb:.0f} ({sign}{delta:.0f})\n"
    return {"content": [{"type": "text", "text": text}]}


async def tool_get_audit_history(params: dict) -> dict:
    limit = min(params.get("limit", 20), 100)
    url_filter = params.get("url")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    if url_filter:
        rows = con.execute(
            "SELECT id, url, category, scores, metrics, created_at FROM audits WHERE url LIKE ? ORDER BY created_at DESC LIMIT ?",
            (f"%{url_filter}%", limit),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT id, url, category, scores, metrics, created_at FROM audits ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    con.close()
    if not rows:
        return {"content": [{"type": "text", "text": "No audit history found"}]}
    text = f"Audit history (last {len(rows)}):\n"
    for r in rows:
        scores = r["scores"] or "{}"
        text += f"  #{r['id']} [{r['category']}] {r['url']} — {scores} ({r['created_at']:.0f})\n"
    return {"content": [{"type": "text", "text": text}]}


async def tool_get_budget_report(params: dict) -> dict:
    url = params.get("url")
    budget = params.get("budget", {})
    if not url:
        return {"content": [{"type": "text", "text": "Parameter 'url' is required"}], "isError": True}
    default_budget = {"performance": 90, "accessibility": 90, "seo": 80, "best-practices": 90, "pwa": 50}
    budget = {**default_budget, **budget}
    data = await _run_lighthouse(url, [k for k in budget if k != "pwa"])
    if data.get("error"):
        return {"content": [{"type": "text", "text": data["message"]}], "isError": True}
    scores = _extract_scores(data)
    text = f"Budget report for {url}:\n"
    all_pass = True
    for cat, threshold in sorted(budget.items()):
        actual = scores.get(cat)
        if actual is None:
            text += f"  {cat}: N/A (budget: {threshold}) — SKIP\n"
            continue
        passed = actual >= threshold
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        text += f"  {cat}: {actual} (budget: {threshold}) — {status}\n"
    text += f"\nOverall: {'ALL PASS' if all_pass else 'SOME FAILURES'}\n"
    return {"content": [{"type": "text", "text": text}]}


async def tool_check_health(_params: dict) -> dict:
    lh_path = _find_lighthouse()
    result = {"lighthouse": {"available": lh_path is not None, "path": lh_path}}
    if lh_path:
        try:
            ver_out = subprocess.run([lh_path, "--version"], capture_output=True, text=True, timeout=10)
            result["lighthouse"]["version"] = ver_out.stdout.strip()
        except Exception as exc:
            result["lighthouse"]["version_error"] = str(exc)
    chrome_names = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
    chrome_path = None
    for cn in chrome_names:
        p = shutil.which(cn)
        if p:
            chrome_path = p
            break
    result["chrome"] = {"available": chrome_path is not None, "path": chrome_path}
    result["db_path"] = DB_PATH
    db_exists = Path(DB_PATH).exists()
    result["db_exists"] = db_exists
    if not lh_path:
        result["install_instructions"] = "npm install -g lighthouse"
    text_parts = []
    for section, info in result.items():
        if isinstance(info, dict):
            text_parts.append(f"{section}: {info}")
        else:
            text_parts.append(f"{section}: {info}")
    text = "Health check:\n" + "\n".join(f"  {p}" for p in text_parts)
    return {"content": [{"type": "text", "text": text}]}


# --- Tool registry ---

TOOLS = {
    "run_audit": {
        "description": "Run full lighthouse audit on URL. Returns performance/accessibility/seo/pwa scores + metrics (FCP, LCP, TBT, CLS, SI).",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL to audit"}},
            "required": ["url"],
        },
        "handler": tool_run_audit,
    },
    "run_performance": {
        "description": "Performance-only audit with detailed timings and optimization hints.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL to audit"}},
            "required": ["url"],
        },
        "handler": tool_run_performance,
    },
    "run_accessibility": {
        "description": "Accessibility audit with violations list.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL to audit"}},
            "required": ["url"],
        },
        "handler": tool_run_accessibility,
    },
    "run_seo": {
        "description": "SEO audit with issues and suggestions.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL to audit"}},
            "required": ["url"],
        },
        "handler": tool_run_seo,
    },
    "compare_urls": {
        "description": "Run audit on 2 URLs and return delta comparison.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url_a": {"type": "string", "description": "First URL"},
                "url_b": {"type": "string", "description": "Second URL"},
            },
            "required": ["url_a", "url_b"],
        },
        "handler": tool_compare_urls,
    },
    "get_audit_history": {
        "description": "List past audit results stored in SQLite.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max results (default 20, max 100)", "default": 20},
                "url": {"type": "string", "description": "Filter by URL substring"},
            },
        },
        "handler": tool_get_audit_history,
    },
    "get_budget_report": {
        "description": "Compare scores against performance budget thresholds.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to audit"},
                "budget": {
                    "type": "object",
                    "description": "Score thresholds, e.g. {\"performance\": 90, \"accessibility\": 85}",
                    "properties": {
                        "performance": {"type": "number"},
                        "accessibility": {"type": "number"},
                        "seo": {"type": "number"},
                        "best-practices": {"type": "number"},
                        "pwa": {"type": "number"},
                    },
                },
            },
            "required": ["url"],
        },
        "handler": tool_get_budget_report,
    },
    "check_health": {
        "description": "Check if lighthouse CLI is available, Chrome/Chromium accessible, version info.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_check_health,
    },
}


async def handle_request(msg: dict) -> dict | None:
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return make_response(
            req_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "lighthouse", "version": "1.0.0"},
            },
        )

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        tool_list = []
        for name, info in TOOLS.items():
            tool_list.append({"name": name, "description": info["description"], "inputSchema": info["inputSchema"]})
        return make_response(req_id, {"tools": tool_list})

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if tool_name not in TOOLS:
            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = await TOOLS[tool_name]["handler"](arguments)
            return make_response(req_id, result)
        except Exception as exc:
            return make_response(
                req_id,
                {"content": [{"type": "text", "text": f"Tool error: {exc}"}], "isError": True},
            )

    if method == "ping":
        return make_response(req_id, {})

    return make_error(req_id, -32601, f"Method not found: {method}")


async def main():
    _init_db()
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
            continue
        response = await handle_request(msg)
        if response is not None:
            payload = json.dumps(response) + "\n"
            writer.write(payload.encode())
            await writer.drain()


if __name__ == "__main__":
    asyncio.run(main())
