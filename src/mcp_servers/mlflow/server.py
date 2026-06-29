#!/usr/bin/env python3
"""MLflow REST API proxy MCP server.

Stdio transport, JSON-RPC over stdin/stdout, MCP protocol version 2024-11-05.
No external dependencies — stdlib only (urllib.request for HTTP).
"""

import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse
from typing import Any

MLFLOW_URL = os.environ.get("MLFLOW_URL", "http://localhost:5000").rstrip("/")

# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def make_response(request_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": err}


# ---------------------------------------------------------------------------
# MLflow HTTP helpers
# ---------------------------------------------------------------------------

def _mlflow_get(path: str, params: dict | None = None) -> Any:
    url = MLFLOW_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"MLflow HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"MLflow connection error: {exc.reason}") from exc


def _mlflow_paginated(path: str, key: str, params: dict | None = None) -> list:
    params = dict(params or {})
    items: list = []
    while True:
        data = _mlflow_get(path, params)
        batch = data.get(key, [])
        items.extend(batch)
        token = data.get("next_page_token")
        if not token:
            break
        params["page_token"] = token
    return items


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "list_experiments",
        "description": "List all MLflow experiments with artifact location and lifecycle stage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "Filter expression (e.g. 'attribute.lifecycle_stage = active')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of experiments to return (default 1000)",
                },
            },
        },
    },
    {
        "name": "get_experiment",
        "description": "Get detailed experiment info including tags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "experiment_id": {
                    "type": "string",
                    "description": "Experiment ID",
                },
            },
            "required": ["experiment_id"],
        },
    },
    {
        "name": "list_runs",
        "description": "List runs for an experiment, sorted by metric, filterable by status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "experiment_id": {
                    "type": "string",
                    "description": "Experiment ID",
                },
                "filter": {
                    "type": "string",
                    "description": "Run filter expression",
                },
                "run_view_type": {
                    "type": "string",
                    "enum": ["ACTIVE_ONLY", "DELETED_ONLY", "ALL"],
                    "description": "Run view type (default ACTIVE_ONLY)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum runs to return (default 1000)",
                },
                "order_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Sort order, e.g. ['metric.accuracy DESC']",
                },
            },
            "required": ["experiment_id"],
        },
    },
    {
        "name": "get_run",
        "description": "Get detailed run info: params, metrics, tags, artifact URIs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "Run UUID",
                },
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "get_metrics",
        "description": "Get metric history for a run (full time series).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "Run UUID",
                },
                "metric_key": {
                    "type": "string",
                    "description": "Metric key name",
                },
            },
            "required": ["run_id", "metric_key"],
        },
    },
    {
        "name": "get_params",
        "description": "Get all parameters for a run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "Run UUID",
                },
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "list_artifacts",
        "description": "List artifacts for a run (files and directories).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "Run UUID",
                },
                "path": {
                    "type": "string",
                    "description": "Artifact path prefix (default root)",
                },
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "list_models",
        "description": "List registered models with versions, stages, and description.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "Model filter expression",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum models to return (default 100)",
                },
            },
        },
    },
    {
        "name": "check_health",
        "description": "Verify MLflow API connectivity, version, and tracking URI.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _format_experiment(exp: dict) -> dict:
    return {
        "experiment_id": exp.get("experiment_id"),
        "name": exp.get("name"),
        "artifact_location": exp.get("artifact_location"),
        "lifecycle_stage": exp.get("lifecycle_stage"),
        "creation_time": exp.get("creation_time"),
        "last_update_time": exp.get("last_update_time"),
        "tags": {t["key"]: t["value"] for t in exp.get("tags", [])},
    }


def _format_run(run: dict) -> dict:
    info = run.get("info", {})
    data = run.get("data", {})
    return {
        "run_id": info.get("run_id"),
        "run_name": info.get("run_name", ""),
        "status": info.get("status"),
        "start_time": info.get("start_time"),
        "end_time": info.get("end_time"),
        "lifecycle_stage": info.get("lifecycle_stage"),
        "artifact_uri": info.get("artifact_uri"),
        "params": {p["key"]: p["value"] for p in data.get("params", [])},
        "metrics": {m["key"]: m["value"] for m in data.get("metrics", [])},
        "tags": {t["key"]: t["value"] for t in data.get("tags", [])},
    }


def _format_model_version(v: dict) -> dict:
    return {
        "version": v.get("version"),
        "current_stage": v.get("current_stage"),
        "creation_timestamp": v.get("creation_timestamp"),
        "last_updated_timestamp": v.get("last_updated_timestamp"),
        "source": v.get("source"),
        "run_id": v.get("run_id"),
        "status": v.get("status"),
        "description": v.get("description", ""),
    }


def _format_model(model: dict) -> dict:
    versions = model.get("latest_versions", [])
    return {
        "name": model.get("name"),
        "creation_timestamp": model.get("creation_timestamp"),
        "last_updated_timestamp": model.get("last_updated_timestamp"),
        "description": model.get("description", ""),
        "tags": {t["key"]: t["value"] for t in model.get("tags", [])},
        "latest_versions": [_format_model_version(v) for v in versions],
    }


def _format_artifact(art: dict) -> dict:
    return {
        "path": art.get("path"),
        "is_dir": art.get("is_dir", False),
        "file_size": art.get("file_size"),
    }


# ---- tool handlers ----

def tool_list_experiments(args: dict) -> Any:
    params: dict = {}
    if args.get("filter"):
        params["filter"] = args["filter"]
    max_r = args.get("max_results", 1000)
    params["max_results"] = str(max_r)
    experiments = _mlflow_paginated("/api/2.0/mlflow/experiments/search", "experiments", params)
    return [_format_experiment(e) for e in experiments]


def tool_get_experiment(args: dict) -> Any:
    data = _mlflow_get(
        "/api/2.0/mlflow/experiments/get",
        {"experiment_id": args["experiment_id"]},
    )
    exp = data.get("experiment", {})
    return _format_experiment(exp)


def tool_list_runs(args: dict) -> Any:
    params: dict = {
        "experiment_ids": json.dumps([args["experiment_id"]]),
    }
    if args.get("filter"):
        params["filter"] = args["filter"]
    if args.get("run_view_type"):
        params["run_view_type"] = args["run_view_type"]
    max_r = args.get("max_results", 1000)
    params["max_results"] = str(max_r)
    if args.get("order_by"):
        params["order_by"] = json.dumps(args["order_by"])
    runs = _mlflow_paginated("/api/2.0/mlflow/runs/search", "runs", params)
    return [_format_run(r) for r in runs]


def tool_get_run(args: dict) -> Any:
    data = _mlflow_get(
        "/api/2.0/mlflow/runs/get",
        {"run_id": args["run_id"]},
    )
    run = data.get("run", {})
    return _format_run(run)


def tool_get_metrics(args: dict) -> Any:
    data = _mlflow_get(
        "/api/2.0/mlflow/metrics/get-history",
        {"run_id": args["run_id"], "metric_key": args["metric_key"]},
    )
    metrics = data.get("metrics", [])
    return [
        {
            "key": m.get("key"),
            "value": m.get("value"),
            "timestamp": m.get("timestamp"),
            "step": m.get("step"),
        }
        for m in metrics
    ]


def tool_get_params(args: dict) -> Any:
    data = _mlflow_get(
        "/api/2.0/mlflow/runs/get",
        {"run_id": args["run_id"]},
    )
    run_data = data.get("run", {}).get("data", {})
    return {p["key"]: p["value"] for p in run_data.get("params", [])}


def tool_list_artifacts(args: dict) -> Any:
    params: dict = {"run_id": args["run_id"]}
    if args.get("path"):
        params["path"] = args["path"]
    data = _mlflow_get("/api/2.0/mlflow/artifacts/list", params)
    artifacts = data.get("files", [])
    return [_format_artifact(a) for a in artifacts]


def tool_list_models(args: dict) -> Any:
    params: dict = {}
    if args.get("filter"):
        params["filter"] = args["filter"]
    max_r = args.get("max_results", 100)
    params["max_results"] = str(max_r)
    models = _mlflow_paginated("/api/2.0/mlflow/registered-models/search", "registered_models", params)
    return [_format_model(m) for m in models]


def tool_check_health(args: dict) -> Any:
    try:
        data = _mlflow_get("/api/2.0/mlflow/experiments/search", {"max_results": "1"})
        return {
            "status": "ok",
            "tracking_uri": MLFLOW_URL,
            "protocol": "2.0",
            "message": "MLflow API is reachable",
        }
    except Exception as exc:
        return {
            "status": "error",
            "tracking_uri": MLFLOW_URL,
            "error": str(exc),
        }


TOOL_HANDLERS = {
    "list_experiments": tool_list_experiments,
    "get_experiment": tool_get_experiment,
    "list_runs": tool_list_runs,
    "get_run": tool_get_run,
    "get_metrics": tool_get_metrics,
    "get_params": tool_get_params,
    "list_artifacts": tool_list_artifacts,
    "list_models": tool_list_models,
    "check_health": tool_check_health,
}


# ---------------------------------------------------------------------------
# Request dispatcher
# ---------------------------------------------------------------------------

def handle_request(request: dict) -> dict:
    method = request.get("method", "")
    request_id = request.get("id")
    params = request.get("params", {})

    # --- notifications (no id → no response) ---
    if request_id is None and method == "notifications/cancelled":
        return None

    # --- initialize ---
    if method == "initialize":
        return make_response(request_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "mlflow", "version": "1.0.0"},
        })

    # --- tools/list ---
    if method == "tools/list":
        return make_response(request_id, {"tools": TOOLS})

    # --- tools/call ---
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        handler = TOOL_HANDLERS.get(tool_name)
        if handler is None:
            return make_error(request_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = handler(arguments)
            return make_response(request_id, {
                "content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}],
            })
        except Exception as exc:
            return make_response(request_id, {
                "content": [{"type": "text", "text": json.dumps({"error": str(exc)}, ensure_ascii=False)}],
                "isError": True,
            })

    return make_error(request_id, -32601, f"Method not found: {method}")


# ---------------------------------------------------------------------------
# Main loop (async-style via stdin reading)
# ---------------------------------------------------------------------------

async def main():
    """Read JSON-RPC messages from stdin, write responses to stdout."""
    reader = sys.stdin.buffer
    writer = sys.stdout.buffer

    while True:
        line_bytes = reader.readline()
        if not line_bytes:
            break
        line = line_bytes.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            writer.write(json.dumps(make_error(None, -32700, "Parse error")).encode() + b"\n")
            writer.flush()
            continue

        response = handle_request(request)
        if response is not None:
            writer.write(json.dumps(response).encode() + b"\n")
            writer.flush()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
