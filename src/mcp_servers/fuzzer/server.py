#!/usr/bin/env python3
"""MCP server: fuzzer — HTTP fuzzing via ffuf/zzuf CLI wrappers."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DB_PATH = os.environ.get("FUZZER_DB_PATH", "/tmp/fuzzer_results.db")

WORDLIST_DIRS = [
    "/usr/share/wordlists",
    "/usr/share/seclists",
    "/usr/share/wordlists/dirb",
    "/usr/share/wordlists/dirbuster",
    "/usr/share/wordlists/wfuzz",
    "/usr/share/seclists/Discovery/Web-Content",
    "/usr/share/seclists/Fuzzing",
]


# ── helpers ──────────────────────────────────────────────────────────

def make_response(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _init_db() -> None:
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool TEXT NOT NULL,
            target TEXT,
            args TEXT,
            output TEXT,
            created_at REAL NOT NULL
        )"""
    )
    con.commit()
    con.close()


def _store(tool: str, target: str, args: str, output: str) -> int:
    con = sqlite3.connect(DB_PATH)
    cur = con.execute(
        "INSERT INTO results (tool, target, args, output, created_at) VALUES (?,?,?,?,?)",
        (tool, target, args, output, time.time()),
    )
    rowid = cur.lastrowid
    con.commit()
    con.close()
    return rowid  # type: ignore[return-value]


def _ffuf_available() -> tuple[bool, str]:
    p = shutil.which("ffuf")
    if not p:
        return False, "ffuf not found. Install: https://github.com/ffuf/ffuf#installation"
    try:
        v = subprocess.run(["ffuf", "-V"], capture_output=True, text=True, timeout=5)
        return True, v.stdout.strip() or v.stderr.strip() or "ffuf available"
    except Exception as exc:
        return False, str(exc)


def _zzuf_available() -> tuple[bool, str]:
    p = shutil.which("zzuf")
    if not p:
        return False, "zzuf not found. Install: apt install zzuf / https://github.com/samhocevar/zzuf"
    try:
        v = subprocess.run(["zzuf", "--version"], capture_output=True, text=True, timeout=5)
        return True, v.stdout.strip() or v.stderr.strip() or "zzuf available"
    except Exception as exc:
        return False, str(exc)


def _run(cmd: list[str], timeout: int = 120) -> dict:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    except FileNotFoundError:
        return {"returncode": -1, "stdout": "", "stderr": f"Command not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"returncode": -2, "stdout": "", "stderr": f"Timeout after {timeout}s"}
    except Exception as exc:
        return {"returncode": -3, "stdout": "", "stderr": str(exc)}


def _parse_ffuf_json(stdout: str) -> list[dict]:
    try:
        data = json.loads(stdout)
        results = data.get("results", [])
        return [
            {
                "url": r.get("url", ""),
                "status": r.get("status", 0),
                "length": r.get("length", 0),
                "words": r.get("words", 0),
                "lines": r.get("lines", 0),
                "input": r.get("input", {}).get("FUZZ", ""),
                "duration_ms": r.get("duration", 0),
            }
            for r in results
        ]
    except (json.JSONDecodeError, AttributeError):
        return []


# ── tool implementations ────────────────────────────────────────────

def tool_fuzz_endpoints(params: dict) -> dict:
    """ffuf against URL with wordlist. Returns status codes, sizes, response times."""
    url = params.get("url")
    wordlist = params.get("wordlist", "/usr/share/seclists/Discovery/Web-Content/common.txt")
    method = params.get("method", "GET")
    filter_codes = params.get("filter_codes", [])
    match_codes = params.get("match_codes", [])
    threads = params.get("threads", 40)
    timeout = params.get("timeout", 120)
    extra_headers = params.get("headers", {})

    if not url:
        return {"isError": True, "content": [{"type": "text", "text": "Parameter 'url' is required"}]}

    ok, msg = _ffuf_available()
    if not ok:
        return {"isError": True, "content": [{"type": "text", "text": msg}]}

    cmd = [
        "ffuf",
        "-u", url,
        "-w", wordlist,
        "-X", method,
        "-t", str(threads),
        "-json",
        "-noninteractive",
    ]
    for code in filter_codes:
        cmd += ["-fc", str(code)]
    for code in match_codes:
        cmd += ["-mc", str(code)]
    for k, v in extra_headers.items():
        cmd += ["-H", f"{k}: {v}"]

    res = _run(cmd, timeout=timeout)
    parsed = _parse_ffuf_json(res["stdout"])

    output_lines = []
    if parsed:
        for entry in parsed:
            output_lines.append(
                f"{entry['status']} {entry['length']:>8}B {entry['duration_ms']:>6}ms  {entry['input']}  {entry['url']}"
            )
    else:
        output_lines.append("No results from ffuf.")
        if res["stderr"]:
            output_lines.append(f"stderr: {res['stderr'][:500]}")

    text = "\n".join(output_lines)
    rid = _store("fuzz_endpoints", url, json.dumps(params), text)

    return {
        "content": [
            {"type": "text", "text": f"Result id: {rid}\nTotal hits: {len(parsed)}\n\n{text}"}
        ]
    }


def tool_fuzz_parameters(params: dict) -> dict:
    """Fuzz query parameters / form data on an endpoint."""
    url = params.get("url")
    wordlist = params.get("wordlist", "/usr/share/seclists/Discovery/Web-Content/burp-parameter-names.txt")
    method = params.get("method", "GET")
    param_name = params.get("param_name", "FUZZ")
    threads = params.get("threads", 40)
    timeout = params.get("timeout", 120)

    if not url:
        return {"isError": True, "content": [{"type": "text", "text": "Parameter 'url' is required"}]}

    ok, msg = _ffuf_available()
    if not ok:
        return {"isError": True, "content": [{"type": "text", "text": msg}]}

    sep = "?" if "?" not in url else "&"
    fuzz_url = f"{url}{sep}{param_name}=FUZZ"

    cmd = [
        "ffuf",
        "-u", fuzz_url,
        "-w", wordlist,
        "-X", method,
        "-t", str(threads),
        "-json",
        "-noninteractive",
    ]

    res = _run(cmd, timeout=timeout)
    parsed = _parse_ffuf_json(res["stdout"])

    output_lines = []
    for entry in parsed:
        output_lines.append(
            f"{entry['status']} {entry['length']:>8}B  param={entry['input']}  {entry['url']}"
        )
    if not parsed:
        output_lines.append("No parameter variations found.")
        if res["stderr"]:
            output_lines.append(f"stderr: {res['stderr'][:500]}")

    text = "\n".join(output_lines)
    rid = _store("fuzz_parameters", url, json.dumps(params), text)

    return {
        "content": [
            {"type": "text", "text": f"Result id: {rid}\nTotal hits: {len(parsed)}\n\n{text}"}
        ]
    }


def tool_fuzz_headers(params: dict) -> dict:
    """Fuzz HTTP headers with custom values."""
    url = params.get("url")
    header_name = params.get("header_name")
    wordlist = params.get("wordlist", "/usr/share/seclists/Fuzzing/HTTPi/Databases/traversal.txt")
    threads = params.get("threads", 20)
    timeout = params.get("timeout", 120)

    if not url:
        return {"isError": True, "content": [{"type": "text", "text": "Parameter 'url' is required"}]}
    if not header_name:
        return {"isError": True, "content": [{"type": "text", "text": "Parameter 'header_name' is required"}]}

    ok, msg = _ffuf_available()
    if not ok:
        return {"isError": True, "content": [{"type": "text", "text": msg}]}

    cmd = [
        "ffuf",
        "-u", url,
        "-w", wordlist,
        "-H", f"{header_name}: FUZZ",
        "-t", str(threads),
        "-json",
        "-noninteractive",
    ]

    res = _run(cmd, timeout=timeout)
    parsed = _parse_ffuf_json(res["stdout"])

    output_lines = []
    for entry in parsed:
        output_lines.append(
            f"{entry['status']} {entry['length']:>8}B  {header_name}={entry['input']}"
        )
    if not parsed:
        output_lines.append("No header variations produced distinct responses.")
        if res["stderr"]:
            output_lines.append(f"stderr: {res['stderr'][:500]}")

    text = "\n".join(output_lines)
    rid = _store("fuzz_headers", url, json.dumps(params), text)

    return {
        "content": [
            {"type": "text", "text": f"Result id: {rid}\nTotal hits: {len(parsed)}\n\n{text}"}
        ]
    }


def tool_fuzz_auth(params: dict) -> dict:
    """Test authentication bypass scenarios."""
    url = params.get("url")
    method = params.get("method", "GET")
    token_header = params.get("token_header", "Authorization")
    valid_token = params.get("valid_token", "")
    timeout = params.get("timeout", 30)

    if not url:
        return {"isError": True, "content": [{"type": "text", "text": "Parameter 'url' is required"}]}

    tests: list[dict] = [
        {"name": "no_auth", "headers": {}},
        {"name": "empty_bearer", "headers": {token_header: "Bearer "}},
        {"name": "null_token", "headers": {token_header: "Bearer null"}},
        {"name": "undefined_token", "headers": {token_header: "Bearer undefined"}},
        {"name": "expired_jwt_like", "headers": {token_header: "Bearer eyJhbGciOiJub25lIn0.eyJleHAiOjF9."}},
        {"name": "admin_role_claim", "headers": {token_header: "Bearer eyJhbGciOiJub25lIn0.eyJyb2xlIjoiYWRtaW4ifQ."}},
        {"name": "basic_admin", "headers": {token_header: "Basic YWRtaW46YWRtaW4="}},
    ]

    if valid_token:
        tests.append({"name": "valid_token", "headers": {token_header: f"Bearer {valid_token}"}})

    results_list: list[dict] = []
    output_lines: list[str] = []

    for test in tests:
        cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{size_download} %{time_total}",
               "-X", method]
        for k, v in test["headers"].items():
            cmd += ["-H", f"{k}: {v}"]
        cmd.append(url)

        res = _run(cmd, timeout=timeout)
        parts = res["stdout"].strip().split()
        status = int(parts[0]) if parts and parts[0].isdigit() else 0
        size = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        elapsed = float(parts[2]) if len(parts) > 2 and parts[2].replace(".", "", 1).isdigit() else 0.0

        entry = {"test": test["name"], "status": status, "size": size, "time_s": elapsed}
        results_list.append(entry)
        flag = " ⚠ POSSIBLE BYPASS" if status not in (401, 403) and test["name"] != "valid_token" else ""
        output_lines.append(f"  {test['name']:20s} → {status}  {size:>8}B  {elapsed:.3f}s{flag}")

    bypass_count = sum(1 for r in results_list if r["status"] not in (401, 403)
                       and r["test"] != "valid_token")
    summary = f"Auth bypass tests: {len(tests)} sent, {bypass_count} potential bypass(es)\n"
    summary += "\n".join(output_lines)

    rid = _store("fuzz_auth", url, json.dumps(params), summary)

    return {
        "content": [
            {"type": "text", "text": f"Result id: {rid}\n{summary}"}
        ]
    }


def tool_scan_dir(params: dict) -> dict:
    """Directory/file discovery with common wordlists."""
    url = params.get("url")
    wordlist = params.get("wordlist", "/usr/share/seclists/Discovery/Web-Content/raft-medium-directories.txt")
    extensions = params.get("extensions", "php,html,txt,bak,old,json,xml,sql")
    threads = params.get("threads", 50)
    timeout = params.get("timeout", 180)
    recursion = params.get("recursion", 0)

    if not url:
        return {"isError": True, "content": [{"type": "text", "text": "Parameter 'url' is required"}]}

    ok, msg = _ffuf_available()
    if not ok:
        return {"isError": True, "content": [{"type": "text", "text": msg}]}

    cmd = [
        "ffuf",
        "-u", f"{url}/FUZZ",
        "-w", wordlist,
        "-e", extensions,
        "-t", str(threads),
        "-json",
        "-noninteractive",
        "-fc", "404",
    ]
    if recursion > 0:
        cmd += ["-recursion", str(recursion)]

    res = _run(cmd, timeout=timeout)
    parsed = _parse_ffuf_json(res["stdout"])

    output_lines: list[str] = []
    for entry in parsed:
        output_lines.append(
            f"  {entry['status']} {entry['length']:>8}B {entry['duration_ms']:>6}ms  {entry['url']}"
        )
    if not parsed:
        output_lines.append("No directories/files discovered.")
        if res["stderr"]:
            output_lines.append(f"stderr: {res['stderr'][:500]}")

    text = f"Wordlist: {wordlist}\nExtensions: {extensions}\n\n" + "\n".join(output_lines)
    rid = _store("scan_dir", url, json.dumps(params), text)

    return {
        "content": [
            {"type": "text", "text": f"Result id: {rid}\nDiscovered: {len(parsed)} items\n\n{text}"}
        ]
    }


def tool_get_wordlists(params: dict) -> dict:
    """List available wordlists from common paths."""
    found: list[dict] = []
    for base in WORDLIST_DIRS:
        p = Path(base)
        if not p.exists():
            continue
        for f in sorted(p.rglob("*")):
            if f.is_file() and f.stat().st_size > 0:
                found.append({
                    "path": str(f),
                    "size_kb": round(f.stat().st_size / 1024, 1),
                })

    if not found:
        text = "No wordlists found in standard paths. Install SecLists:\n"
        text += "  git clone https://github.com/danielmiessler/SecLists /usr/share/seclists"
        return {"content": [{"type": "text", "text": text}]}

    lines = [f"  {w['path']}  ({w['size_kb']} KB)" for w in found[:200]]
    text = f"Found {len(found)} wordlist(s) (showing up to 200):\n" + "\n".join(lines)
    return {"content": [{"type": "text", "text": text}]}


def tool_get_results(params: dict) -> dict:
    """Retrieve stored fuzzing results from SQLite."""
    limit = min(params.get("limit", 20), 100)
    tool_filter = params.get("tool")
    target_filter = params.get("target")

    if not Path(DB_PATH).exists():
        return {"content": [{"type": "text", "text": "No results database found."}]}

    con = sqlite3.connect(DB_PATH)
    query = "SELECT id, tool, target, args, output, created_at FROM results"
    conditions: list[str] = []
    qparams: list[Any] = []
    if tool_filter:
        conditions.append("tool = ?")
        qparams.append(tool_filter)
    if target_filter:
        conditions.append("target LIKE ?")
        qparams.append(f"%{target_filter}%")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC LIMIT ?"
    qparams.append(limit)

    rows = con.execute(query, qparams).fetchall()
    con.close()

    if not rows:
        return {"content": [{"type": "text", "text": "No results found."}]}

    lines: list[str] = []
    for rid, tool, target, args, output, ts in rows:
        import datetime
        tstr = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()
        lines.append(f"[{rid}] {tool} | {target} | {tstr}")
        lines.append(f"    args: {args[:200]}")
        lines.append(f"    {output[:300]}")
        lines.append("")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_check_health(params: dict) -> dict:
    """Check ffuf/zzuf availability, versions, wordlists."""
    sections: list[str] = []

    ffuf_ok, ffuf_msg = _ffuf_available()
    sections.append(f"ffuf: {'OK' if ffuf_ok else 'MISSING'} — {ffuf_msg}")

    zzuf_ok, zzuf_msg = _zzuf_available()
    sections.append(f"zzuf: {'OK' if zzuf_ok else 'MISSING'} — {zzuf_msg}")

    wl_count = 0
    for base in WORDLIST_DIRS:
        p = Path(base)
        if p.exists():
            wl_count += sum(1 for f in p.rglob("*") if f.is_file())
    sections.append(f"Wordlists: {wl_count} file(s) in standard paths")

    db_exists = Path(DB_PATH).exists()
    sections.append(f"Results DB: {'exists' if db_exists else 'not yet created'} ({DB_PATH})")

    status = "ready" if ffuf_ok else "degraded"
    if not ffuf_ok and not zzuf_ok:
        status = "unavailable"

    sections.append(f"\nOverall status: {status}")

    return {"content": [{"type": "text", "text": "\n".join(sections)}]}


# ── tool registry ────────────────────────────────────────────────────

TOOLS: dict[str, dict] = {
    "fuzz_endpoints": {
        "description": "Run ffuf against URL with wordlist — returns status codes, sizes, response times.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL (use FUZZ keyword position)"},
                "wordlist": {"type": "string", "description": "Path to wordlist file"},
                "method": {"type": "string", "description": "HTTP method", "default": "GET"},
                "filter_codes": {"type": "array", "items": {"type": "integer"}, "description": "Status codes to filter out"},
                "match_codes": {"type": "array", "items": {"type": "integer"}, "description": "Status codes to match"},
                "threads": {"type": "integer", "description": "Number of concurrent threads", "default": 40},
                "timeout": {"type": "integer", "description": "Overall timeout in seconds", "default": 120},
                "headers": {"type": "object", "description": "Extra HTTP headers"},
            },
            "required": ["url"],
        },
        "handler": tool_fuzz_endpoints,
    },
    "fuzz_parameters": {
        "description": "Fuzz query parameters / form data on an endpoint.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL"},
                "wordlist": {"type": "string", "description": "Path to wordlist file"},
                "method": {"type": "string", "description": "HTTP method", "default": "GET"},
                "param_name": {"type": "string", "description": "Query parameter name to fuzz", "default": "FUZZ"},
                "threads": {"type": "integer", "default": 40},
                "timeout": {"type": "integer", "default": 120},
            },
            "required": ["url"],
        },
        "handler": tool_fuzz_parameters,
    },
    "fuzz_headers": {
        "description": "Fuzz HTTP headers with custom values from a wordlist.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL"},
                "header_name": {"type": "string", "description": "Header name to fuzz (e.g. X-Custom-Header)"},
                "wordlist": {"type": "string", "description": "Path to wordlist file"},
                "threads": {"type": "integer", "default": 20},
                "timeout": {"type": "integer", "default": 120},
            },
            "required": ["url", "header_name"],
        },
        "handler": tool_fuzz_headers,
    },
    "fuzz_auth": {
        "description": "Test authentication bypass — missing token, expired JWT, wrong role, etc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL"},
                "method": {"type": "string", "default": "GET"},
                "token_header": {"type": "string", "description": "Header name for auth token", "default": "Authorization"},
                "valid_token": {"type": "string", "description": "A valid token for baseline comparison"},
                "timeout": {"type": "integer", "default": 30},
            },
            "required": ["url"],
        },
        "handler": tool_fuzz_auth,
    },
    "scan_dir": {
        "description": "Directory and file discovery using ffuf with common wordlists.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Base URL to scan"},
                "wordlist": {"type": "string", "description": "Path to directory wordlist"},
                "extensions": {"type": "string", "description": "Comma-separated extensions", "default": "php,html,txt,bak,old,json,xml,sql"},
                "threads": {"type": "integer", "default": 50},
                "timeout": {"type": "integer", "default": 180},
                "recursion": {"type": "integer", "description": "Recursion depth (0=none)", "default": 0},
            },
            "required": ["url"],
        },
        "handler": tool_scan_dir,
    },
    "get_wordlists": {
        "description": "List available wordlists from common paths (/usr/share/wordlists/, /usr/share/seclists/).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "handler": tool_get_wordlists,
    },
    "get_results": {
        "description": "Retrieve stored fuzzing results from SQLite database.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "description": "Filter by tool name"},
                "target": {"type": "string", "description": "Filter by target (substring match)"},
                "limit": {"type": "integer", "description": "Max results to return", "default": 20},
            },
        },
        "handler": tool_get_results,
    },
    "check_health": {
        "description": "Check if ffuf/zzuf are available, their versions, and wordlist accessibility.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "handler": tool_check_health,
    },
}


# ── JSON-RPC dispatcher ──────────────────────────────────────────────

async def handle_request(msg: dict) -> dict | None:
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params", {})

    # ── lifecycle ────────────────────────────────────────
    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "fuzzer", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None  # client notification, no response

    # ── tools ────────────────────────────────────────────
    if method == "tools/list":
        tools = []
        for name, t in TOOLS.items():
            tools.append({
                "name": name,
                "description": t["description"],
                "inputSchema": t["inputSchema"],
            })
        return make_response(req_id, {"tools": tools})

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_params = params.get("arguments", {})
        if tool_name not in TOOLS:
            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = TOOLS[tool_name]["handler"](tool_params)
            return make_response(req_id, result)
        except Exception as exc:
            return make_error(req_id, -32603, f"Tool execution error: {exc}")

    return make_error(req_id, -32601, f"Method not found: {method}")


async def main() -> None:
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
            resp = make_error(None, -32700, "Parse error")
            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()
            continue

        resp = await handle_request(msg)
        if resp is not None:
            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()


if __name__ == "__main__":
    asyncio.run(main())
