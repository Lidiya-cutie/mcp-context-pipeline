#!/usr/bin/env python3
"""MCP server: git_blame — git blame/log/annotate wrapper."""

import json
import os
import subprocess
import sys
from collections import defaultdict

REPO_PATH = os.environ.get("GIT_REPO_PATH", ".")


def git(*args, repo=None):
    cwd = repo or REPO_PATH
    result = subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git exited with code {result.returncode}")
    return result.stdout


def git_raw(*args, repo=None):
    cwd = repo or REPO_PATH
    return subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------- helpers ----------

def make_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


# ---------- tool implementations ----------

def tool_blame_file(params):
    file_path = params.get("file_path")
    if not file_path:
        raise ValueError("file_path is required")
    revision = params.get("revision", "HEAD")
    out = git("blame", "--porcelain", revision, "--", file_path)
    lines = []
    commit_cache = {}
    current = None
    for raw_line in out.splitlines():
        if raw_line.startswith("author "):
            current = raw_line[7:]
        elif raw_line.startswith("author-mail "):
            pass
        elif raw_line.startswith("author-time "):
            pass
        elif raw_line.startswith("summary "):
            pass
        elif raw_line.startswith("\t"):
            lines.append({"content": raw_line[1:], "commit": current or ""})
            current = None
    return {"file": file_path, "revision": revision, "lines": lines}


def tool_blame_lines(params):
    file_path = params.get("file_path")
    start = params.get("start_line")
    end = params.get("end_line")
    if not file_path or start is None or end is None:
        raise ValueError("file_path, start_line and end_line are required")
    revision = params.get("revision", "HEAD")
    out = git("blame", "--porcelain", "-L", f"{start},{end}", revision, "--", file_path)
    lines = []
    current_commit = ""
    current_author = ""
    current_date = ""
    for raw_line in out.splitlines():
        if raw_line.startswith("author "):
            current_author = raw_line[7:]
        elif raw_line.startswith("committer-time "):
            current_date = raw_line[14:]
        elif raw_line.startswith("\t"):
            lines.append({
                "content": raw_line[1:],
                "commit": current_commit,
                "author": current_author,
                "date": current_date,
            })
        else:
            parts = raw_line.split()
            if parts and len(parts) >= 2:
                current_commit = parts[0]
    return {"file": file_path, "revision": revision, "range": [start, end], "lines": lines}


def tool_get_commit_history(params):
    path = params.get("path")
    max_count = params.get("max_count", 20)
    args = ["log", f"--max-count={max_count}", "--pretty=format:%H|%an|%ae|%aI|%s"]
    if path:
        args += ["--", path]
    out = git(*args)
    commits = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 4)
        if len(parts) == 5:
            commits.append({
                "hash": parts[0],
                "author": parts[1],
                "email": parts[2],
                "date": parts[3],
                "message": parts[4],
            })
    # add stats if requested
    if params.get("include_stats") and commits:
        for c in commits:
            stat_out = git("show", "--stat", "--format=", c["hash"])
            c["stats"] = stat_out.strip()
    return {"path": path, "commits": commits, "count": len(commits)}


def tool_get_commit_detail(params):
    commit_hash = params.get("commit_hash")
    if not commit_hash:
        raise ValueError("commit_hash is required")
    out = git("show", "--format=%H|%an|%ae|%aI|%s%n%n%b", commit_hash)
    header, _, body = out.partition("\n\n")
    parts = header.split("|", 4)
    if len(parts) < 5:
        raise RuntimeError(f"unexpected git show output for {commit_hash}")
    diff = git("diff-tree", "--no-commit-id", "-r", "-p", commit_hash)
    files_raw = git("diff-tree", "--no-commit-id", "--name-status", "-r", commit_hash)
    files = []
    for fline in files_raw.splitlines():
        if fline.strip():
            fp = fline.split("\t", 1)
            if len(fp) == 2:
                files.append({"status": fp[0], "file": fp[1]})
    return {
        "hash": parts[0],
        "author": parts[1],
        "email": parts[2],
        "date": parts[3],
        "message": parts[4],
        "body": body.strip(),
        "files_changed": files,
        "diff": diff.strip(),
    }


def tool_get_author_stats(params):
    revision = params.get("revision", "HEAD")
    since = params.get("since")
    args = ["log", "--format=%ae", revision]
    if since:
        args.insert(2, f"--since={since}")
    out = git(*args)
    author_commits = defaultdict(int)
    for line in out.splitlines():
        if line.strip():
            author_commits[line.strip()] += 1
    # lines added/removed per author
    shortstat_args = ["log", "--format=%ae", "--shortstat", revision]
    if since:
        shortstat_args.insert(2, f"--since={since}")
    ss_out = git(*shortstat_args)
    author_lines = defaultdict(lambda: {"added": 0, "removed": 0, "files": 0})
    current_author = None
    for line in ss_out.splitlines():
        line = line.strip()
        if not line:
            continue
        if " | " not in line and "@" in line:
            current_author = line
            continue
        if current_author and ("file" in line or "insertion" in line or "deletion" in line):
            added = 0
            removed = 0
            files = 0
            for token in line.split(","):
                token = token.strip()
                if "file" in token:
                    files = int(token.split()[0])
                elif "insertion" in token:
                    added = int(token.split()[0])
                elif "deletion" in token:
                    removed = int(token.split()[0])
            author_lines[current_author]["added"] += added
            author_lines[current_author]["removed"] += removed
            author_lines[current_author]["files"] += files
            current_author = None
    stats = []
    for email, commits in sorted(author_commits.items(), key=lambda x: -x[1]):
        entry = {"email": email, "commits": commits}
        if email in author_lines:
            entry.update(author_lines[email])
        else:
            entry.update({"added": 0, "removed": 0, "files": 0})
        stats.append(entry)
    return {"authors": stats, "total": len(stats)}


def tool_find_author(params):
    pattern = params.get("pattern")
    if not pattern:
        raise ValueError("pattern is required")
    max_count = params.get("max_count", 20)
    out = git("log", f"--max-count={max_count}", "--all-match", "--format=%H|%an|%ae|%aI|%s",
              f"--author={pattern}")
    commits = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 4)
        if len(parts) == 5:
            commits.append({
                "hash": parts[0],
                "author": parts[1],
                "email": parts[2],
                "date": parts[3],
                "message": parts[4],
            })
    return {"pattern": pattern, "commits": commits, "count": len(commits)}


def tool_get_hotspots(params):
    n = params.get("n", 50)
    revision = params.get("revision", "HEAD")
    out = git("log", f"--max-count={n}", "--format=", "--name-only", revision)
    freq = defaultdict(int)
    for line in out.splitlines():
        f = line.strip()
        if f:
            freq[f] += 1
    hotspots = sorted(freq.items(), key=lambda x: -x[1])
    return {"analyzed_commits": n, "hotspots": [{"file": f, "changes": c} for f, c in hotspots[:50]]}


def tool_check_health(params):
    r = git_raw("rev-parse", "--is-inside-work-tree")
    if r.returncode != 0:
        return {"healthy": False, "error": "not a git repository", "path": REPO_PATH}
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    last_commit = git("log", "-1", "--format=%H|%an|%aI|%s").strip()
    total = git("rev-list", "--count", "HEAD").strip()
    parts = last_commit.split("|", 3)
    return {
        "healthy": True,
        "path": os.path.abspath(REPO_PATH),
        "branch": branch,
        "total_commits": int(total),
        "last_commit": {
            "hash": parts[0] if len(parts) > 0 else "",
            "author": parts[1] if len(parts) > 1 else "",
            "date": parts[2] if len(parts) > 2 else "",
            "message": parts[3] if len(parts) > 3 else "",
        },
    }


# ---------- tool definitions ----------

TOOLS = [
    {
        "name": "blame_file",
        "description": "Git blame for entire file. Returns per-line: content, commit hash.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to file (relative to repo root)"},
                "revision": {"type": "string", "description": "Git revision (default HEAD)"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "blame_lines",
        "description": "Git blame for specific line range in a file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
                "revision": {"type": "string", "description": "Git revision (default HEAD)"},
            },
            "required": ["file_path", "start_line", "end_line"],
        },
    },
    {
        "name": "get_commit_history",
        "description": "Git log for file or directory with author, date, message.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory path (optional)"},
                "max_count": {"type": "integer", "description": "Max commits (default 20)"},
                "include_stats": {"type": "boolean", "description": "Include file change stats"},
            },
        },
    },
    {
        "name": "get_commit_detail",
        "description": "Full commit info: diff, files changed, author, message.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "commit_hash": {"type": "string", "description": "Commit hash (full or short)"},
            },
            "required": ["commit_hash"],
        },
    },
    {
        "name": "get_author_stats",
        "description": "Contribution stats by author: commits, lines added/removed, files touched.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "revision": {"type": "string", "description": "Git revision range (default HEAD)"},
                "since": {"type": "string", "description": "Date filter e.g. '2024-01-01'"},
            },
        },
    },
    {
        "name": "find_author",
        "description": "Search commits by author name/email pattern.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Author name/email regex pattern"},
                "max_count": {"type": "integer", "description": "Max results (default 20)"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "get_hotspots",
        "description": "Files with most changes in last N commits (change frequency analysis).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "description": "Number of recent commits to analyze (default 50)"},
                "revision": {"type": "string", "description": "Git revision (default HEAD)"},
            },
        },
    },
    {
        "name": "check_health",
        "description": "Verify git repo: current branch, last commit, total commits.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

TOOL_MAP = {
    "blame_file": tool_blame_file,
    "blame_lines": tool_blame_lines,
    "get_commit_history": tool_get_commit_history,
    "get_commit_detail": tool_get_commit_detail,
    "get_author_stats": tool_get_author_stats,
    "find_author": tool_find_author,
    "get_hotspots": tool_get_hotspots,
    "check_health": tool_check_health,
}


# ---------- JSON-RPC dispatcher ----------

def handle_request(msg):
    req_id = msg.get("id")
    method = msg.get("method")

    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "git_blame", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None  # no response for notifications

    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    if method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if tool_name not in TOOL_MAP:
            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = TOOL_MAP[tool_name](arguments)
            return make_response(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
            })
        except Exception as exc:
            return make_response(req_id, {
                "content": [{"type": "text", "text": json.dumps({"error": str(exc)})}],
                "isError": True,
            })

    return make_error(req_id, -32601, f"Method not found: {method}")


# ---------- main loop ----------

async def main():
    reader = sys.stdin.buffer
    writer = sys.stdout.buffer
    buf = b""

    while True:
        chunk = reader.read1(65536) if hasattr(reader, "read1") else None
        if chunk is None:
            # fallback: read line by line
            line = sys.stdin.readline()
            if not line:
                break
            buf += line.encode() if isinstance(line, str) else line
        else:
            if not chunk:
                break
            buf += chunk

        while b"\n" in buf:
            line_bytes, buf = buf.split(b"\n", 1)
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            resp = handle_request(msg)
            if resp is not None:
                payload = json.dumps(resp, ensure_ascii=False) + "\n"
                writer.write(payload.encode("utf-8"))
                writer.flush()


if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
