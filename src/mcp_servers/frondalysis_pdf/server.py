#!/usr/bin/env python3
"""MCP server for Frondalysis PDF generation. Transit: MD -> Pandoc -> XeLaTeX -> PDF"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

PREAMBULA_PATH = os.environ.get(
    "FRONDALYSIS_PREAMBULA_PATH", "/mldata/rnd29-frondalysis/templates/preambula.tex"
)
OUTPUT_DIR = os.environ.get(
    "FRONDALYSIS_OUTPUT_DIR", "/mldata/rnd29-frondalysis/output"
)
MAINFONT = os.environ.get("FRONDALYSIS_MAINFONT", "Liberation Serif")
MONOFONT = os.environ.get("FRONDALYSIS_MONOFONT", "DejaVu Sans Mono")
LANG = os.environ.get("FRONDALYSIS_LANG", "russian")


def make_response(req_id, result):
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n"


def make_error(req_id, code, message):
    return (
        json.dumps(
            {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
        )
        + "\n"
    )


def _find_bin(name):
    import shutil

    for c in [
        os.path.expanduser(f"~/bin/{name}"),
        os.path.expanduser(f"~/texlive/2026/bin/x86_64-linux/{name}"),
        "/usr/local/texlive/2026/bin/x86_64-linux/" + name,
        f"/usr/bin/{name}",
        f"/usr/local/bin/{name}",
    ]:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    p = shutil.which(name)
    if p:
        return p
    raise FileNotFoundError(f"{name} not found")


def _run_pandoc(md_content, output_path, preambula_path=None):
    pandoc = _find_bin("pandoc")
    xelatex = _find_bin("xelatex")
    preambula = preambula_path or PREAMBULA_PATH
    if not os.path.isfile(preambula):
        return {"success": False, "error": f"Preambula not found: {preambula}"}
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(md_content)
        md_path = f.name
    env_path = os.path.dirname(xelatex) + ":" + os.environ.get("PATH", "")
    try:
        cmd = [
            pandoc,
            md_path,
            "-o",
            output_path,
            "--pdf-engine=xelatex",
            "-H",
            preambula,
            "-V",
            f"mainfont={MAINFONT}",
            "-V",
            f"monofont={MONOFONT}",
            "-V",
            f"lang={LANG}",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "PATH": env_path},
        )
        if result.returncode == 0:
            return {
                "success": True,
                "pdf_path": output_path,
                "size_bytes": os.path.getsize(output_path),
            }
        return {
            "success": False,
            "error": result.stderr[-2000:] if result.stderr else "Unknown error",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Timeout (120s)"}
    finally:
        os.unlink(md_path)


def _validate_markdown(md_content):
    forbidden = [
        ("\\begin{", "LaTeX environment"),
        ("\\end{", "LaTeX environment"),
        ("\\textbf{", "use **bold**"),
        ("\\textit{", "use *italic*"),
        ("\\ref{", "LaTeX ref"),
        ("\\pagebreak", "page break"),
        ("\\newpage", "page break"),
        ("\\tikz", "TikZ"),
    ]
    issues = []
    lines = md_content.split("\n")
    in_math = False
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("$$"):
            in_math = not in_math
            continue
        if in_math:
            continue
        for pattern, desc in forbidden:
            if pattern in line:
                issues.append({"line": i, "pattern": pattern, "description": desc})
    return {"valid": len(issues) == 0, "issues": issues, "total_lines": len(lines)}


TOOLS = {
    "generate_pdf": {
        "description": "Convert Markdown to PDF via Pandoc+XeLaTeX",
        "inputSchema": {
            "type": "object",
            "properties": {
                "markdown": {"type": "string"},
                "output_filename": {"type": "string"},
                "preambula_path": {"type": "string"},
            },
            "required": ["markdown"],
        },
    },
    "validate_markdown": {
        "description": "Validate Markdown for LaTeX-incompatible constructs",
        "inputSchema": {
            "type": "object",
            "properties": {"markdown": {"type": "string"}},
            "required": ["markdown"],
        },
    },
    "list_templates": {
        "description": "List available preambula.tex templates",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "get_preamble": {
        "description": "Get current preambula.tex content",
        "inputSchema": {"type": "object", "properties": {}},
    },
}


def handle_request(msg):
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params", {})
    if method == "initialize":
        return make_response(
            req_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "frondalysis_pdf", "version": "1.0.0"},
            },
        )
    if method == "tools/list":
        return make_response(
            req_id,
            {"tools": [{"name": k, **v} for k, v in TOOLS.items()]},
        )
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        if name == "generate_pdf":
            fn = args.get(
                "output_filename",
                f"frondalysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            )
            r = _run_pandoc(
                args.get("markdown", ""),
                os.path.join(OUTPUT_DIR, fn),
                args.get("preambula_path"),
            )
            return make_response(
                req_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"PDF: {r['pdf_path']} ({r['size_bytes']}b)"
                                if r["success"]
                                else f"Error: {r['error']}"
                            ),
                        }
                    ],
                    "isError": not r["success"],
                },
            )
        if name == "validate_markdown":
            r = _validate_markdown(args.get("markdown", ""))
            t = (
                f"Valid ({r['total_lines']} lines)"
                if r["valid"]
                else f"{len(r['issues'])} issues:\n"
                + "\n".join(
                    f"L{i['line']}: {i['pattern']} - {i['description']}"
                    for i in r["issues"]
                )
            )
            return make_response(req_id, {"content": [{"type": "text", "text": t}]})
        if name == "list_templates":
            td = os.path.dirname(PREAMBULA_PATH)
            ts = (
                [
                    {"name": f, "path": os.path.join(td, f)}
                    for f in sorted(os.listdir(td))
                    if f.endswith(".tex")
                ]
                if os.path.isdir(td)
                else []
            )
            return make_response(
                req_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(ts, indent=2) if ts else "No templates",
                        }
                    ]
                },
            )
        if name == "get_preamble":
            t = (
                open(PREAMBULA_PATH, encoding="utf-8").read()
                if os.path.isfile(PREAMBULA_PATH)
                else f"Not found: {PREAMBULA_PATH}"
            )
            return make_response(req_id, {"content": [{"type": "text", "text": t}]})
        return make_error(req_id, -32601, f"Unknown tool: {name}")
    if method == "notifications/initialized":
        return ""
    return make_error(req_id, -32601, f"Unknown method: {method}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        r = handle_request(msg)
        if r:
            sys.stdout.write(r)
            sys.stdout.flush()


if __name__ == "__main__":
    main()
