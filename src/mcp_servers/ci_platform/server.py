#!/usr/bin/env python3
"""MCP server for ci_platform — unified CI/CD (GitLab CI + Jenkins)."""

import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse
import base64
import time
from typing import Any, Optional

# ── helpers ──────────────────────────────────────────────────────────────────

def _read_line() -> Optional[dict]:
    """Read one JSON-RPC message from stdin (content-length header)."""
    length = None
    while True:
        line = sys.stdin.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            if length is not None:
                break
            continue
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip())
    if length is None:
        return None
    data = sys.stdin.read(length)
    return json.loads(data)


def _write(msg: dict) -> None:
    body = json.dumps(msg, ensure_ascii=False)
    blob = body.encode("utf-8")
    sys.stdout.write(f"Content-Length: {len(blob)}\r\n\r\n")
    sys.stdout.write(blob.decode("utf-8", errors="replace"))
    sys.stdout.flush()


def make_response(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _gitlab_headers() -> dict:
    token = os.environ.get("GITLAB_TOKEN", "")
    return {"PRIVATE-TOKEN": token, "Content-Type": "application/json"}


def _jenkins_auth() -> tuple:
    user = os.environ.get("JENKINS_USER", "")
    token = os.environ.get("JENKINS_TOKEN", "")
    return (user, token)


def _http_get(url: str, headers: dict = None, auth: tuple = None, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, method="GET")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if auth:
        cred = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {cred}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ct = resp.headers.get("Content-Type", "")
        raw = resp.read().decode("utf-8", errors="replace")
        if "json" in ct:
            return json.loads(raw)
        return raw


def _http_post(url: str, data: dict = None, headers: dict = None, auth: tuple = None, timeout: int = 30) -> Any:
    body = json.dumps(data).encode("utf-8") if data else b""
    req = urllib.request.Request(url, data=body, method="POST")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if auth:
        cred = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {cred}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        ct = resp.headers.get("Content-Type", "")
        if raw and "json" in ct:
            return json.loads(raw)
        return raw or None


def _http_post_form(url: str, params: dict = None, headers: dict = None, auth: tuple = None, timeout: int = 30) -> Any:
    body = urllib.parse.urlencode(params).encode() if params else b""
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if auth:
        cred = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {cred}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        ct = resp.headers.get("Content-Type", "")
        if raw and "json" in ct:
            return json.loads(raw)
        return raw or None


def _http_delete(url: str, headers: dict = None, auth: tuple = None, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, method="DELETE")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if auth:
        cred = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {cred}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw
        return None


# ── CI backends ──────────────────────────────────────────────────────────────

CI_TYPE = os.environ.get("CI_TYPE", "gitlab").lower()
GITLAB_URL = os.environ.get("GITLAB_URL", "https://gitlab.com").rstrip("/")
JENKINS_URL = os.environ.get("JENKINS_URL", "http://localhost:8080").rstrip("/")


# ── GitLab CI ────────────────────────────────────────────────────────────────

def _gl_project_id(project_id: str) -> str:
    return urllib.parse.quote(project_id, safe="")


def gl_list_pipelines(args: dict) -> list:
    pid = args.get("project_id")
    if not pid:
        raise ValueError("project_id is required")
    ep = pid
    per_page = min(args.get("limit", 20), 100)
    url = f"{GITLAB_URL}/api/v4/projects/{_gl_project_id(ep)}/pipelines?per_page={per_page}&order_by=updated_at&sort=desc"
    if args.get("branch"):
        url += f"&ref={urllib.parse.quote(args['branch'])}"
    if args.get("status"):
        url += f"&status={args['status']}"
    data = _http_get(url, _gitlab_headers())
    if isinstance(data, list):
        return [{
            "id": p.get("id"),
            "sha": p.get("sha"),
            "ref": p.get("ref"),
            "status": p.get("status"),
            "source": p.get("source"),
            "created_at": p.get("created_at"),
            "updated_at": p.get("updated_at"),
            "web_url": p.get("web_url"),
            "duration": p.get("duration"),
            "user": p.get("user", {}).get("username") if p.get("user") else None,
        } for p in data]
    return data


def gl_get_pipeline(args: dict) -> dict:
    pid = args.get("project_id")
    pipeline_id = args.get("pipeline_id")
    if not pid or not pipeline_id:
        raise ValueError("project_id and pipeline_id are required")
    base = f"{GITLAB_URL}/api/v4/projects/{_gl_project_id(pid)}"
    pipe = _http_get(f"{base}/pipelines/{pipeline_id}", _gitlab_headers())
    jobs = _http_get(f"{base}/pipelines/{pipeline_id}/jobs", _gitlab_headers())
    stages = []
    if isinstance(jobs, list):
        stage_map: dict = {}
        for j in jobs:
            sn = j.get("stage", "unknown")
            if sn not in stage_map:
                stage_map[sn] = {"name": sn, "jobs": []}
            stage_map[sn]["jobs"].append({
                "id": j.get("id"),
                "name": j.get("name"),
                "status": j.get("status"),
                "duration": j.get("duration"),
                "started_at": j.get("started_at"),
                "finished_at": j.get("finished_at"),
                "runner": j.get("runner", {}).get("description") if j.get("runner") else None,
                "web_url": j.get("web_url"),
            })
        stages = list(stage_map.values())
    return {
        "id": pipe.get("id"),
        "sha": pipe.get("sha"),
        "ref": pipe.get("ref"),
        "status": pipe.get("status"),
        "source": pipe.get("source"),
        "created_at": pipe.get("created_at"),
        "updated_at": pipe.get("updated_at"),
        "duration": pipe.get("duration"),
        "web_url": pipe.get("web_url"),
        "user": pipe.get("user", {}).get("username") if pipe.get("user") else None,
        "stages": stages,
    }


def gl_get_job_log(args: dict) -> dict:
    pid = args.get("project_id")
    job_id = args.get("job_id")
    if not pid or not job_id:
        raise ValueError("project_id and job_id are required")
    base = f"{GITLAB_URL}/api/v4/projects/{_gl_project_id(pid)}"
    job_info = _http_get(f"{base}/jobs/{job_id}", _gitlab_headers())
    try:
        log_url = f"{base}/jobs/{job_id}/trace"
        log = _http_get(log_url, _gitlab_headers())
    except Exception:
        log = "(log unavailable)"
    if isinstance(log, str):
        tail = args.get("tail")
        if tail and isinstance(tail, int) and tail > 0:
            lines = log.splitlines()
            log = "\n".join(lines[-tail:])
    return {
        "job_id": job_id,
        "name": job_info.get("name"),
        "status": job_info.get("status"),
        "stage": job_info.get("stage"),
        "log": log,
    }


def gl_trigger_pipeline(args: dict) -> dict:
    pid = args.get("project_id")
    if not pid:
        raise ValueError("project_id is required")
    base = f"{GITLAB_URL}/api/v4/projects/{_gl_project_id(pid)}"
    params = {"ref": args.get("branch", "main")}
    if args.get("variables"):
        params["variables"] = args["variables"]
    result = _http_post(f"{base}/pipeline", params, _gitlab_headers())
    if isinstance(result, dict):
        return {
            "id": result.get("id"),
            "sha": result.get("sha"),
            "ref": result.get("ref"),
            "status": result.get("status"),
            "web_url": result.get("web_url"),
        }
    return result


def gl_retry_pipeline(args: dict) -> dict:
    pid = args.get("project_id")
    pipeline_id = args.get("pipeline_id")
    if not pid or not pipeline_id:
        raise ValueError("project_id and pipeline_id are required")
    base = f"{GITLAB_URL}/api/v4/projects/{_gl_project_id(pid)}"
    result = _http_post(f"{base}/pipelines/{pipeline_id}/retry", headers=_gitlab_headers())
    if isinstance(result, dict):
        return {"id": result.get("id"), "status": result.get("status"), "web_url": result.get("web_url")}
    return result


def gl_cancel_pipeline(args: dict) -> dict:
    pid = args.get("project_id")
    pipeline_id = args.get("pipeline_id")
    if not pid or not pipeline_id:
        raise ValueError("project_id and pipeline_id are required")
    base = f"{GITLAB_URL}/api/v4/projects/{_gl_project_id(pid)}"
    result = _http_post(f"{base}/pipelines/{pipeline_id}/cancel", headers=_gitlab_headers())
    if isinstance(result, dict):
        return {"id": result.get("id"), "status": result.get("status")}
    return result


def gl_get_artifacts(args: dict) -> Any:
    pid = args.get("project_id")
    pipeline_id = args.get("pipeline_id")
    if not pid:
        raise ValueError("project_id is required")
    base = f"{GITLAB_URL}/api/v4/projects/{_gl_project_id(pid)}"
    if pipeline_id:
        jobs = _http_get(f"{base}/pipelines/{pipeline_id}/jobs", _gitlab_headers())
        if isinstance(jobs, list):
            artifacts = []
            for j in jobs:
                if j.get("artifacts"):
                    for a in j["artifacts"]:
                        artifacts.append({
                            "job_id": j.get("id"),
                            "job_name": j.get("name"),
                            "filename": a.get("filename"),
                            "size": a.get("size"),
                            "file_type": a.get("file_type"),
                        })
            return artifacts
    job_id = args.get("job_id")
    if job_id:
        url = f"{base}/jobs/{job_id}/artifacts"
        if args.get("download"):
            raw = _http_get(url, _gitlab_headers())
            return {"downloaded": True, "content_preview": str(raw)[:500] if raw else None}
        try:
            _http_get(url, _gitlab_headers())
            return {"available": True}
        except urllib.error.HTTPError:
            return {"available": False}
    return {"error": "specify pipeline_id or job_id"}


def gl_get_queue(args: dict) -> list:
    url = f"{GITLAB_URL}/api/v4/runners/all?status=online&per_page=20"
    try:
        runners = _http_get(url, _gitlab_headers())
    except Exception:
        runners = []
    return runners if isinstance(runners, list) else []


def gl_check_health() -> dict:
    try:
        user = _http_get(f"{GITLAB_URL}/api/v4/user", _gitlab_headers())
        if isinstance(user, dict):
            return {
                "status": "ok",
                "platform": "gitlab",
                "url": GITLAB_URL,
                "user": user.get("username"),
                "user_id": user.get("id"),
                "api_version": "v4",
            }
        return {"status": "ok", "platform": "gitlab", "url": GITLAB_URL}
    except Exception as e:
        return {"status": "error", "platform": "gitlab", "url": GITLAB_URL, "error": str(e)}


# ── Jenkins ──────────────────────────────────────────────────────────────────

def _jk_build_to_pipeline(b: dict) -> dict:
    dur = b.get("duration", 0)
    timestamp = b.get("timestamp", 0)
    return {
        "id": b.get("number"),
        "display_name": b.get("displayName"),
        "url": b.get("url"),
        "status": b.get("result") or "RUNNING",
        "building": b.get("building", False),
        "branch": (b.get("actions", [{}])
                    and next((a.get("lastBuiltRevision", {}).get("branch", [{}])[0].get("name", "")
                              for a in b.get("actions", [])
                              if "lastBuiltRevision" in a), "")),
        "duration_ms": dur,
        "timestamp": timestamp,
        "estimated_duration_ms": b.get("estimatedDuration", 0),
        "triggerer": next((a.get("causes", [{}])[0].get("shortDescription", "")
                          for a in b.get("actions", [])
                          if "causes" in a), ""),
    }


def jk_list_pipelines(args: dict) -> list:
    job_name = args.get("job_name", "")
    per_page = min(args.get("limit", 20), 100)
    encoded = urllib.parse.quote(job_name, safe="")
    url = f"{JENKINS_URL}/job/{encoded}/api/json?tree=builds[number,displayName,url,result,building,duration,timestamp,estimatedDuration,actions[lastBuiltRevision[branch[name]],causes[shortDescription]]]{{0,{per_page}}}"
    data = _http_get(url, auth=_jenkins_auth())
    if isinstance(data, dict) and "builds" in data:
        return [_jk_build_to_pipeline(b) for b in data["builds"]]
    return []


def jk_get_pipeline(args: dict) -> dict:
    job_name = args.get("job_name", "")
    build_id = args.get("build_id")
    if not job_name:
        raise ValueError("job_name is required")
    encoded = urllib.parse.quote(job_name, safe="")
    path = f"{build_id}" if build_id else "lastBuild"
    url = f"{JENKINS_URL}/job/{encoded}/{path}/api/json"
    b = _http_get(url, auth=_jenkins_auth())
    if not isinstance(b, dict):
        return {"error": "no data"}
    stages = []
    for a in b.get("actions", []):
        if "executionNodeUrl" in a or "stages" in a:
            stages.append(a)
    return {
        **_jk_build_to_pipeline(b),
        "description": b.get("description", ""),
        "stages": stages,
        "artifacts": [{"filename": f.get("fileName"), "relative_path": f.get("relativePath")}
                      for f in b.get("artifacts", [])],
    }


def jk_get_job_log(args: dict) -> dict:
    job_name = args.get("job_name", "")
    build_id = args.get("build_id")
    if not job_name:
        raise ValueError("job_name is required")
    encoded = urllib.parse.quote(job_name, safe="")
    path = f"{build_id}" if build_id else "lastBuild"
    url = f"{JENKINS_URL}/job/{encoded}/{path}/consoleText"
    log = _http_get(url, auth=_jenkins_auth())
    if isinstance(log, str):
        tail = args.get("tail")
        if tail and isinstance(tail, int) and tail > 0:
            lines = log.splitlines()
            log = "\n".join(lines[-tail:])
    else:
        log = str(log)
    return {"job_name": job_name, "build_id": build_id, "log": log}


def jk_trigger_pipeline(args: dict) -> dict:
    job_name = args.get("job_name", "")
    if not job_name:
        raise ValueError("job_name is required")
    encoded = urllib.parse.quote(job_name, safe="")
    params = args.get("parameters")
    if params:
        url = f"{JENKINS_URL}/job/{encoded}/buildWithParameters"
        _http_post_form(url, params, auth=_jenkins_auth())
    else:
        url = f"{JENKINS_URL}/job/{encoded}/build"
        _http_post(url, auth=_jenkins_auth())
    return {"status": "triggered", "job_name": job_name, "parameters": params}


def jk_retry_pipeline(args: dict) -> dict:
    job_name = args.get("job_name", "")
    build_id = args.get("build_id")
    if not job_name or not build_id:
        raise ValueError("job_name and build_id are required")
    encoded = urllib.parse.quote(job_name, safe="")
    url = f"{JENKINS_URL}/job/{encoded}/{build_id}/retry"
    _http_post(url, auth=_jenkins_auth())
    return {"status": "retried", "job_name": job_name, "build_id": build_id}


def jk_cancel_pipeline(args: dict) -> dict:
    job_name = args.get("job_name", "")
    build_id = args.get("build_id")
    if not job_name or not build_id:
        raise ValueError("job_name and build_id are required")
    encoded = urllib.parse.quote(job_name, safe="")
    url = f"{JENKINS_URL}/job/{encoded}/{build_id}/stop"
    _http_post(url, auth=_jenkins_auth())
    return {"status": "stopped", "job_name": job_name, "build_id": build_id}


def jk_get_artifacts(args: dict) -> list:
    job_name = args.get("job_name", "")
    build_id = args.get("build_id")
    if not job_name:
        raise ValueError("job_name is required")
    encoded = urllib.parse.quote(job_name, safe="")
    path = f"{build_id}" if build_id else "lastBuild"
    url = f"{JENKINS_URL}/job/{encoded}/{path}/api/json?tree=artifacts[*]"
    data = _http_get(url, auth=_jenkins_auth())
    if isinstance(data, dict) and "artifacts" in data:
        return [{"filename": a.get("fileName"), "relative_path": a.get("relativePath")}
                for a in data["artifacts"]]
    return []


def jk_get_queue(args: dict) -> list:
    url = f"{JENKINS_URL}/queue/api/json"
    data = _http_get(url, auth=_jenkins_auth())
    if isinstance(data, dict) and "items" in data:
        return [{
            "id": i.get("id"),
            "name": i.get("task", {}).get("name"),
            "url": i.get("task", {}).get("url"),
            "why": i.get("why"),
            "in_queue_since": i.get("inQueueSince"),
        } for i in data["items"]]
    return []


def jk_check_health() -> dict:
    try:
        data = _http_get(f"{JENKINS_URL}/api/json?tree=url,nodeDescription", auth=_jenkins_auth())
        if isinstance(data, dict):
            return {
                "status": "ok",
                "platform": "jenkins",
                "url": JENKINS_URL,
                "node_description": data.get("nodeDescription", ""),
            }
        return {"status": "ok", "platform": "jenkins", "url": JENKINS_URL}
    except Exception as e:
        return {"status": "error", "platform": "jenkins", "url": JENKINS_URL, "error": str(e)}


# ── tool definitions ─────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "list_pipelines",
        "description": "List recent CI/CD pipelines or builds with status, branch, duration, triggerer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "GitLab project ID or path (GitLab)"},
                "job_name": {"type": "string", "description": "Jenkins job name (Jenkins)"},
                "branch": {"type": "string", "description": "Filter by branch/ref"},
                "status": {"type": "string", "description": "Filter by status"},
                "limit": {"type": "integer", "description": "Max results (default 20, max 100)"},
            },
        },
    },
    {
        "name": "get_pipeline",
        "description": "Get detailed pipeline/build info: stages, jobs, durations, artifacts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "GitLab project ID or path"},
                "pipeline_id": {"type": "integer", "description": "Pipeline ID (GitLab)"},
                "job_name": {"type": "string", "description": "Jenkins job name"},
                "build_id": {"type": "integer", "description": "Build number (Jenkins)"},
            },
        },
    },
    {
        "name": "get_job_log",
        "description": "Get job/build log output (last N lines or full).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "GitLab project ID or path"},
                "job_id": {"type": "integer", "description": "Job ID (GitLab)"},
                "job_name": {"type": "string", "description": "Jenkins job name"},
                "build_id": {"type": "integer", "description": "Build number (Jenkins)"},
                "tail": {"type": "integer", "description": "Last N lines (omit for full log)"},
            },
        },
    },
    {
        "name": "trigger_pipeline",
        "description": "Trigger a new pipeline or build on a branch.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "GitLab project ID or path"},
                "branch": {"type": "string", "description": "Branch/ref to run (GitLab, default main)"},
                "variables": {"type": "object", "description": "Pipeline variables (GitLab)"},
                "job_name": {"type": "string", "description": "Jenkins job name"},
                "parameters": {"type": "object", "description": "Build parameters (Jenkins)"},
            },
        },
    },
    {
        "name": "retry_pipeline",
        "description": "Retry a failed pipeline/build.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "GitLab project ID or path"},
                "pipeline_id": {"type": "integer", "description": "Pipeline ID (GitLab)"},
                "job_name": {"type": "string", "description": "Jenkins job name"},
                "build_id": {"type": "integer", "description": "Build number (Jenkins)"},
            },
        },
    },
    {
        "name": "cancel_pipeline",
        "description": "Cancel a running pipeline/build.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "GitLab project ID or path"},
                "pipeline_id": {"type": "integer", "description": "Pipeline ID (GitLab)"},
                "job_name": {"type": "string", "description": "Jenkins job name"},
                "build_id": {"type": "integer", "description": "Build number (Jenkins)"},
            },
        },
    },
    {
        "name": "get_artifacts",
        "description": "List or download artifacts from a pipeline/build.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "GitLab project ID or path"},
                "pipeline_id": {"type": "integer", "description": "Pipeline ID (GitLab)"},
                "job_id": {"type": "integer", "description": "Job ID (GitLab)"},
                "download": {"type": "boolean", "description": "Download artifact content (GitLab)"},
                "job_name": {"type": "string", "description": "Jenkins job name"},
                "build_id": {"type": "integer", "description": "Build number (Jenkins)"},
            },
        },
    },
    {
        "name": "get_queue",
        "description": "Get current build queue / pending jobs.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "check_health",
        "description": "Verify CI platform connection, API version, user info.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


# ── dispatcher ───────────────────────────────────────────────────────────────

def _dispatch_gitlab(tool: str, args: dict) -> Any:
    mapping = {
        "list_pipelines": gl_list_pipelines,
        "get_pipeline": gl_get_pipeline,
        "get_job_log": gl_get_job_log,
        "trigger_pipeline": gl_trigger_pipeline,
        "retry_pipeline": gl_retry_pipeline,
        "cancel_pipeline": gl_cancel_pipeline,
        "get_artifacts": gl_get_artifacts,
        "get_queue": gl_get_queue,
    }
    fn = mapping.get(tool)
    if fn:
        return fn(args)
    raise ValueError(f"unknown tool: {tool}")


def _dispatch_jenkins(tool: str, args: dict) -> Any:
    mapping = {
        "list_pipelines": jk_list_pipelines,
        "get_pipeline": jk_get_pipeline,
        "get_job_log": jk_get_job_log,
        "trigger_pipeline": jk_trigger_pipeline,
        "retry_pipeline": jk_retry_pipeline,
        "cancel_pipeline": jk_cancel_pipeline,
        "get_artifacts": jk_get_artifacts,
        "get_queue": jk_get_queue,
    }
    fn = mapping.get(tool)
    if fn:
        return fn(args)
    raise ValueError(f"unknown tool: {tool}")


def handle_request(msg: dict) -> dict:
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "ci_platform", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return make_response(req_id, {})

    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        if tool_name == "check_health":
            if CI_TYPE == "jenkins":
                result = jk_check_health()
            else:
                result = gl_check_health()
            return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]})
        try:
            if CI_TYPE == "jenkins":
                result = _dispatch_jenkins(tool_name, args)
            else:
                result = _dispatch_gitlab(tool_name, args)
            return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]})
        except ValueError as e:
            return make_error(req_id, -32602, str(e))
        except urllib.error.HTTPError as e:
            body_text = ""
            try:
                body_text = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            return make_error(req_id, -32000, f"HTTP {e.code}: {e.reason}", body_text)
        except Exception as e:
            return make_error(req_id, -32603, str(e))

    return make_error(req_id, -32601, f"Method not found: {method}")


# ── main loop ────────────────────────────────────────────────────────────────

async def main():
    while True:
        try:
            msg = _read_line()
        except Exception:
            break
        if msg is None:
            break
        resp = handle_request(msg)
        _write(resp)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
