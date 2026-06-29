#!/usr/bin/env python3
"""MCP server: static_analysis — code linting and security scanning."""

import ast
import json
import shutil
import subprocess
import sys
import os
from pathlib import Path

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "static_analysis"
SERVER_VERSION = "1.0.0"

ANALYZERS = ["ruff", "pylint", "bandit", "mypy"]


def make_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _run_tool(cmd, cwd=None, timeout=120):
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return None, None, f"Tool not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout expired"


def _ensure_path(path_str):
    p = Path(path_str)
    if not p.exists():
        return None, f"Path not found: {path_str}"
    return p, None


# --- Tool implementations ---

def tool_lint_python(args):
    target = args.get("path", ".")
    tool = args.get("tool", "ruff")

    p, err = _ensure_path(target)
    if err:
        return {"error": err}

    if tool == "ruff":
        rc, out, serr = _run_tool(["ruff", "check", "--output-format=json", str(p)])
        if rc is None:
            return {"error": serr}
        try:
            issues = json.loads(out) if out.strip() else []
        except json.JSONDecodeError:
            issues = []
        result = []
        for item in issues:
            result.append({
                "file": item.get("filename", ""),
                "line": item.get("location", {}).get("row", 0),
                "col": item.get("location", {}).get("column", 0),
                "message": item.get("message", ""),
                "code": item.get("code", ""),
                "severity": "error" if item.get("fix") is None else "warning",
            })
        return {"tool": "ruff", "issues": result, "count": len(result)}

    elif tool == "pylint":
        rc, out, serr = _run_tool(
            ["pylint", "--output-format=json", str(p)]
        )
        if rc is None:
            return {"error": serr}
        try:
            issues = json.loads(out) if out.strip() else []
        except json.JSONDecodeError:
            issues = []
        result = []
        for item in issues:
            result.append({
                "file": item.get("path", ""),
                "line": item.get("line", 0),
                "col": item.get("column", 0),
                "message": item.get("message", ""),
                "code": item.get("message-id", ""),
                "severity": item.get("type", "convention"),
            })
        return {"tool": "pylint", "issues": result, "count": len(result)}

    else:
        return {"error": f"Unsupported lint tool: {tool}. Use 'ruff' or 'pylint'."}


def tool_security_scan(args):
    target = args.get("path", ".")
    severity_threshold = args.get("severity", "all")

    p, err = _ensure_path(target)
    if err:
        return {"error": err}

    cmd = ["bandit", "-r", "-f", "json", str(p)]
    if severity_threshold != "all":
        cmd.extend(["-l" if severity_threshold == "low" else "-ll" if severity_threshold == "medium" else "-lll"])

    rc, out, serr = _run_tool(cmd)
    if rc is None:
        return {"error": serr}

    try:
        data = json.loads(out) if out.strip() else {}
    except json.JSONDecodeError:
        return {"error": "Failed to parse bandit output", "raw": serr}

    results = []
    for item in data.get("results", []):
        results.append({
            "file": item.get("filename", ""),
            "line": item.get("line_number", 0),
            "test_id": item.get("test_id", ""),
            "test_name": item.get("test_name", ""),
            "severity": item.get("issue_severity", ""),
            "confidence": item.get("issue_confidence", ""),
            "message": item.get("issue_text", ""),
        })

    return {
        "issues": results,
        "count": len(results),
        "metrics": data.get("metrics", {}),
    }


def tool_type_check(args):
    target = args.get("path", ".")
    strict = args.get("strict", False)

    p, err = _ensure_path(target)
    if err:
        return {"error": err}

    cmd = ["mypy", "--output=json", str(p)]
    if strict:
        cmd.append("--strict")

    rc, out, serr = _run_tool(cmd, timeout=180)
    if rc is None:
        return {"error": serr}

    errors = []
    for line in out.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            # mypy sometimes outputs non-JSON lines
            if ":" in line:
                parts = line.split(":", 3)
                if len(parts) >= 4:
                    errors.append({
                        "file": parts[0].strip(),
                        "line": int(parts[1].strip()) if parts[1].strip().isdigit() else 0,
                        "severity": "error",
                        "message": parts[3].strip(),
                    })
            continue
        errors.append({
            "file": item.get("file", ""),
            "line": item.get("line", 0),
            "col": item.get("column", 0),
            "severity": item.get("severity", "error"),
            "message": item.get("message", ""),
            "code": item.get("code", ""),
        })

    return {"errors": errors, "count": len(errors)}


def tool_analyze_file(args):
    target = args.get("path")
    if not target:
        return {"error": "path is required"}

    p, err = _ensure_path(target)
    if err:
        return {"error": err}
    if p.is_dir():
        return {"error": f"{target} is a directory, expected a file"}

    result = {"file": str(p)}

    # Complexity metrics
    try:
        source = p.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
        lines_total = source.count("\n") + 1
        functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        result["metrics"] = {
            "total_lines": lines_total,
            "functions": len(functions),
            "classes": len(classes),
            "code_lines": sum(1 for ln in source.splitlines() if ln.strip() and not ln.strip().startswith("#")),
        }
    except Exception as e:
        result["metrics"] = {"error": str(e)}

    # Lint
    lint = tool_lint_python({"path": str(p), "tool": "ruff"})
    if "error" not in lint:
        result["lint"] = lint
    else:
        lint2 = tool_lint_python({"path": str(p), "tool": "pylint"})
        result["lint"] = lint2 if "error" not in lint2 else lint

    # Security
    sec = tool_security_scan({"path": str(p)})
    result["security"] = sec

    # Type check
    tc = tool_type_check({"path": str(p)})
    result["type_check"] = tc

    return result


def tool_analyze_directory(args):
    target = args.get("path", ".")
    p, err = _ensure_path(target)
    if err:
        return {"error": err}
    if not p.is_dir():
        return {"error": f"{target} is not a directory"}

    py_files = sorted(p.rglob("*.py"))
    if not py_files:
        return {"files": [], "total_issues": 0, "summary": {}}

    file_results = {}
    total_by_severity = {"error": 0, "warning": 0, "info": 0}

    # Run ruff on the whole directory at once
    lint = tool_lint_python({"path": str(p), "tool": "ruff"})
    if "error" not in lint:
        for issue in lint.get("issues", []):
            f = issue["file"]
            file_results.setdefault(f, {"lint": []})
            file_results[f]["lint"].append(issue)
            sev = issue.get("severity", "warning")
            total_by_severity[sev] = total_by_severity.get(sev, 0) + 1

    # Run bandit on directory
    sec = tool_security_scan({"path": str(p)})
    if "error" not in sec:
        for issue in sec.get("issues", []):
            f = issue["file"]
            file_results.setdefault(f, {"security": []})
            file_results[f].setdefault("security", []).append(issue)
            sev = issue.get("severity", "LOW")
            key = "error" if sev == "HIGH" else "warning" if sev == "MEDIUM" else "info"
            total_by_severity[key] = total_by_severity.get(key, 0) + 1

    summary = {
        "files_scanned": len(py_files),
        "files_with_issues": len(file_results),
        "total_by_severity": total_by_severity,
    }

    return {
        "files": file_results,
        "summary": summary,
    }


def tool_get_complexity(args):
    target = args.get("path")
    if not target:
        return {"error": "path is required"}

    p, err = _ensure_path(target)
    if err:
        return {"error": err}

    try:
        source = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": str(e)}

    # Cyclomatic complexity estimation: count decision points
    decision_keywords = 0
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
            decision_keywords += 1
        elif isinstance(node, ast.BoolOp):
            decision_keywords += len(node.values) - 1

    # Also count via simple text scan as fallback
    text_count = 0
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for kw in ("if ", "elif ", "for ", "while ", "try:", "except ", " and ", " or "):
            text_count += stripped.count(kw)

    lines_total = source.count("\n") + 1
    functions = [n for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    return {
        "file": str(p),
        "total_lines": lines_total,
        "estimated_complexity_ast": decision_keywords,
        "estimated_complexity_text": text_count,
        "functions": len(functions),
        "avg_complexity_per_function": round(decision_keywords / max(len(functions), 1), 2),
    }


def tool_get_dependencies(args):
    target = args.get("path")
    if not target:
        return {"error": "path is required"}

    p, err = _ensure_path(target)
    if err:
        return {"error": err}

    try:
        source = p.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except Exception as e:
        return {"error": str(e)}

    stdlib_modules = {
        "os", "sys", "json", "re", "math", "datetime", "collections", "itertools",
        "functools", "pathlib", "subprocess", "threading", "multiprocessing", "logging",
        "unittest", "argparse", "typing", "abc", "io", "hashlib", "shutil", "copy",
        "time", "random", "string", "textwrap", "enum", "dataclasses", "contextlib",
        "ast", "importlib", "pickle", "csv", "xml", "html", "http", "urllib",
        "socket", "ssl", "struct", "ctypes", "platform", "traceback", "inspect",
        "signal", "tempfile", "glob", "fnmatch", "operator", "warnings",
    }

    stdlib_imports = []
    third_party = []
    local_imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.split(".")[0]
                if name in stdlib_modules:
                    stdlib_imports.append(alias.name)
                elif name.startswith("."):
                    local_imports.append(alias.name)
                else:
                    third_party.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                name = node.module.split(".")[0]
                if name in stdlib_modules:
                    stdlib_imports.append(node.module)
                elif name.startswith("."):
                    local_imports.append(node.module)
                else:
                    third_party.append(node.module)

    return {
        "file": str(p),
        "stdlib": sorted(set(stdlib_imports)),
        "third_party": sorted(set(third_party)),
        "local": sorted(set(local_imports)),
        "total": len(set(stdlib_imports)) + len(set(third_party)) + len(set(local_imports)),
    }


def tool_list_available_tools(args):
    available = {}
    for tool_name in ANALYZERS:
        path = shutil.which(tool_name)
        if path:
            rc, out, serr = _run_tool([tool_name, "--version"])
            version = (out or serr).strip().split("\n")[0] if rc is not None else "unknown"
            available[tool_name] = {"installed": True, "path": path, "version": version}
        else:
            available[tool_name] = {"installed": False, "path": None, "version": None}
    return available


def tool_check_health(args):
    tools_info = tool_list_available_tools(args)
    available_count = sum(1 for v in tools_info.values() if v["installed"])
    return {
        "healthy": available_count > 0,
        "available_analyzers": available_count,
        "details": tools_info,
    }


# --- Tool definitions ---

TOOLS = [
    {
        "name": "lint_python",
        "description": "Run ruff or pylint on a file/directory. Returns issues with line/col/message/severity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory path to lint"},
                "tool": {"type": "string", "enum": ["ruff", "pylint"], "default": "ruff", "description": "Which linter to use"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "security_scan",
        "description": "Run bandit on file/directory. Returns vulnerabilities with severity/confidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory path to scan"},
                "severity": {"type": "string", "enum": ["all", "low", "medium", "high"], "default": "all"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "type_check",
        "description": "Run mypy on file/directory. Returns type errors.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory path"},
                "strict": {"type": "boolean", "default": False},
            },
            "required": ["path"],
        },
    },
    {
        "name": "analyze_file",
        "description": "Comprehensive analysis of a single Python file: lint + security + type + complexity metrics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to Python file"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "analyze_directory",
        "description": "Scan directory, aggregate results by severity and file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "get_complexity",
        "description": "Cyclomatic complexity estimation (count decision points in Python file).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to Python file"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "get_dependencies",
        "description": "Parse import statements from Python file, categorize as stdlib/third-party/local.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to Python file"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_available_tools",
        "description": "Check which analyzers are installed (ruff, pylint, bandit, mypy) with versions.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_health",
        "description": "Verify at least one analyzer is available.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

TOOL_DISPATCH = {
    "lint_python": tool_lint_python,
    "security_scan": tool_security_scan,
    "type_check": tool_type_check,
    "analyze_file": tool_analyze_file,
    "analyze_directory": tool_analyze_directory,
    "get_complexity": tool_get_complexity,
    "get_dependencies": tool_get_dependencies,
    "list_available_tools": tool_list_available_tools,
    "check_health": tool_check_health,
}


# --- Protocol handlers ---

def handle_initialize(params, req_id):
    result = {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    }
    return make_response(req_id, result)


def handle_tools_list(params, req_id):
    return make_response(req_id, {"tools": TOOLS})


def handle_tools_call(params, req_id):
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if tool_name not in TOOL_DISPATCH:
        return make_error(req_id, -32601, f"Unknown tool: {tool_name}")

    try:
        result = TOOL_DISPATCH[tool_name](arguments)
        return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}]})
    except Exception as e:
        return make_response(req_id, {
            "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
            "isError": True,
        })


METHOD_DISPATCH = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
}


def handle_request(msg):
    req_id = msg.get("id")
    method = msg.get("method", "")

    # notifications — no response
    if req_id is None and method == "notifications/initialized":
        return None

    handler = METHOD_DISPATCH.get(method)
    if handler is None:
        return make_error(req_id, -32601, f"Method not found: {method}")

    return handler(msg.get("params", {}), req_id)


async def main():
    reader = sys.stdin.buffer
    writer = sys.stdout.buffer

    while True:
        header_line = await _read_line(reader)
        if header_line is None:
            break

        header_str = header_line.decode("utf-8", errors="replace").strip()
        if not header_str:
            continue

        content_length = None
        while header_str:
            if header_str.lower().startswith("content-length:"):
                content_length = int(header_str.split(":", 1)[1].strip())
            header_line = await _read_line(reader)
            if header_line is None:
                break
            header_str = header_line.decode("utf-8", errors="replace").strip()
            if not header_str:
                break

        if content_length is None:
            continue

        body = reader.read(content_length)
        if not body:
            break

        try:
            msg = json.loads(body)
        except json.JSONDecodeError:
            continue

        response = handle_request(msg)
        if response is not None:
            body_bytes = json.dumps(response, ensure_ascii=False).encode("utf-8")
            header = f"Content-Length: {len(body_bytes)}\r\n\r\n"
            writer.write(header.encode("utf-8") + body_bytes)
            writer.flush()


async def _read_line(reader):
    """Read a single line (\\n terminated) from a buffered reader."""
    line = b""
    while True:
        ch = reader.read(1)
        if not ch:
            return None if not line else line
        line += ch
        if ch == b"\n":
            return line


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
