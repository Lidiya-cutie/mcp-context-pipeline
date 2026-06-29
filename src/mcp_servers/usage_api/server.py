#!/usr/bin/env python3
"""MCP server for token usage and billing tracking."""

import json
import sqlite3
import os
import sys
import uuid
from datetime import datetime, timedelta

DB_PATH = os.environ.get("USAGE_DB_PATH", ":memory:")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS usage (
            id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cost REAL NOT NULL,
            request_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_usage_created ON usage(created_at);
        CREATE INDEX IF NOT EXISTS idx_usage_provider ON usage(provider);
        CREATE INDEX IF NOT EXISTS idx_usage_model ON usage(model);

        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL UNIQUE,
            budget REAL NOT NULL,
            alert_threshold REAL NOT NULL DEFAULT 0.8,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rate_limits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            remaining_requests INTEGER,
            total_requests INTEGER,
            reset_time TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()


def make_response(id_, result):
    return json.dumps({"jsonrpc": "2.0", "id": id_, "result": result}) + "\n"


def make_error(id_, code, message):
    return json.dumps({
        "jsonrpc": "2.0",
        "id": id_,
        "error": {"code": code, "message": message}
    }) + "\n"


def _row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def _rows_to_dicts(rows):
    return [dict(r) for r in rows]


# ── Tool implementations ──────────────────────────────────────────────

def tool_track_usage(conn, params):
    p = params
    record_id = str(uuid.uuid4())
    created_at = p.get("created_at") or datetime.utcnow().isoformat() + "Z"
    conn.execute(
        "INSERT INTO usage (id, provider, model, input_tokens, output_tokens, cost, request_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (record_id, p["provider"], p["model"], p["input_tokens"],
         p["output_tokens"], p["cost"], p.get("request_id"), created_at)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM usage WHERE id = ?", (record_id,)).fetchone()
    return {"record": _row_to_dict(row)}


def tool_get_daily_usage(conn, params):
    date_from = params.get("date_from")
    date_to = params.get("date_to")
    query = """
        SELECT DATE(created_at) AS date,
               SUM(input_tokens) AS total_input_tokens,
               SUM(output_tokens) AS total_output_tokens,
               SUM(input_tokens + output_tokens) AS total_tokens,
               SUM(cost) AS total_cost,
               COUNT(*) AS request_count
        FROM usage WHERE 1=1
    """
    args = []
    if date_from:
        query += " AND DATE(created_at) >= ?"
        args.append(date_from)
    if date_to:
        query += " AND DATE(created_at) <= ?"
        args.append(date_to)
    query += " GROUP BY DATE(created_at) ORDER BY date"
    rows = conn.execute(query, args).fetchall()
    return {"daily_usage": _rows_to_dicts(rows)}


def tool_get_model_breakdown(conn, params):
    date_from = params.get("date_from")
    date_to = params.get("date_to")
    query = """
        SELECT provider, model,
               SUM(input_tokens) AS total_input_tokens,
               SUM(output_tokens) AS total_output_tokens,
               SUM(input_tokens + output_tokens) AS total_tokens,
               SUM(cost) AS total_cost,
               COUNT(*) AS request_count
        FROM usage WHERE 1=1
    """
    args = []
    if date_from:
        query += " AND DATE(created_at) >= ?"
        args.append(date_from)
    if date_to:
        query += " AND DATE(created_at) <= ?"
        args.append(date_to)
    query += " GROUP BY provider, model ORDER BY total_cost DESC"
    rows = conn.execute(query, args).fetchall()
    return {"model_breakdown": _rows_to_dicts(rows)}


def tool_get_provider_breakdown(conn, params):
    date_from = params.get("date_from")
    date_to = params.get("date_to")
    query = """
        SELECT provider,
               SUM(input_tokens) AS total_input_tokens,
               SUM(output_tokens) AS total_output_tokens,
               SUM(input_tokens + output_tokens) AS total_tokens,
               SUM(cost) AS total_cost,
               COUNT(*) AS request_count
        FROM usage WHERE 1=1
    """
    args = []
    if date_from:
        query += " AND DATE(created_at) >= ?"
        args.append(date_from)
    if date_to:
        query += " AND DATE(created_at) <= ?"
        args.append(date_to)
    query += " GROUP BY provider ORDER BY total_cost DESC"
    rows = conn.execute(query, args).fetchall()
    return {"provider_breakdown": _rows_to_dicts(rows)}


def tool_get_cost_summary(conn, params):
    period = params.get("period", "day")
    if period == "day":
        group_expr = "DATE(created_at)"
    elif period == "week":
        group_expr = "STRFTIME('%Y-W%W', created_at)"
    elif period == "month":
        group_expr = "STRFTIME('%Y-%m', created_at)"
    else:
        return {"error": f"Unknown period: {period}. Use day/week/month."}

    query = f"""
        SELECT {group_expr} AS period_label,
               SUM(cost) AS total_cost,
               COUNT(*) AS request_count
        FROM usage
        GROUP BY period_label
        ORDER BY period_label
    """
    rows = conn.execute(query).fetchall()

    budget_info = None
    if period == "month":
        now = datetime.utcnow()
        month_key = now.strftime("%Y-%m")
        brow = conn.execute(
            "SELECT * FROM budgets WHERE month = ?", (month_key,)
        ).fetchone()
        if brow:
            budget_info = _row_to_dict(brow)

    result = {"period": period, "cost_summary": _rows_to_dicts(rows)}
    if budget_info:
        result["budget"] = budget_info
    return result


def tool_set_budget(conn, params):
    month = params["month"]
    budget = params["budget"]
    threshold = params.get("alert_threshold", 0.8)
    conn.execute(
        "INSERT INTO budgets (month, budget, alert_threshold) VALUES (?, ?, ?) "
        "ON CONFLICT(month) DO UPDATE SET budget=excluded.budget, alert_threshold=excluded.alert_threshold",
        (month, budget, threshold)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM budgets WHERE month = ?", (month,)).fetchone()
    return {"budget": _row_to_dict(row)}


def tool_check_budget(conn, params):
    month = params.get("month") or datetime.utcnow().strftime("%Y-%m")
    brow = conn.execute("SELECT * FROM budgets WHERE month = ?", (month,)).fetchone()
    if not brow:
        return {"error": f"No budget set for {month}"}

    budget_val = brow["budget"]
    threshold = brow["alert_threshold"]

    row = conn.execute(
        "SELECT COALESCE(SUM(cost), 0) AS total_cost, COUNT(*) AS request_count "
        "FROM usage WHERE STRFTIME('%Y-%m', created_at) = ?",
        (month,)
    ).fetchone()

    used = row["total_cost"]
    remaining = budget_val - used
    pct = (used / budget_val * 100) if budget_val > 0 else 0

    days_in_month = 30
    day_of_month = datetime.utcnow().day
    if day_of_month > 0:
        daily_avg = used / day_of_month
        burn_rate = daily_avg * days_in_month
    else:
        burn_rate = 0

    projected_remaining = budget_val - burn_rate

    return {
        "month": month,
        "budget": budget_val,
        "used": round(used, 6),
        "remaining": round(remaining, 6),
        "usage_pct": round(pct, 2),
        "alert_threshold": threshold,
        "threshold_exceeded": pct >= threshold * 100,
        "daily_avg_cost": round(daily_avg, 6) if day_of_month > 0 else 0,
        "projected_monthly_burn": round(burn_rate, 6),
        "projected_remaining": round(projected_remaining, 6),
        "request_count": row["request_count"]
    }


def tool_get_rate_limits(conn, params):
    provider = params.get("provider")
    query = "SELECT * FROM rate_limits WHERE 1=1"
    args = []
    if provider:
        query += " AND provider = ?"
        args.append(provider)
    query += " ORDER BY updated_at DESC"

    rows = conn.execute(query, args).fetchall()

    if params.get("update"):
        p = params["update"]
        provider = p.get("provider") or provider
        if not provider:
            return {"error": "provider is required"}
        conn.execute(
            "INSERT INTO rate_limits (provider, remaining_requests, total_requests, reset_time) "
            "VALUES (?, ?, ?, ?)",
            (provider, p.get("remaining_requests"), p.get("total_requests"), p.get("reset_time"))
        )
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM rate_limits WHERE provider = ? ORDER BY updated_at DESC",
            (provider,)
        ).fetchall()

    return {"rate_limits": _rows_to_dicts(rows)}


def tool_get_efficiency_metrics(conn, params):
    date_from = params.get("date_from")
    date_to = params.get("date_to")
    query = """
        SELECT provider, model,
               SUM(input_tokens) AS total_input_tokens,
               SUM(output_tokens) AS total_output_tokens,
               SUM(input_tokens + output_tokens) AS total_tokens,
               SUM(cost) AS total_cost,
               COUNT(*) AS request_count,
               ROUND(SUM(cost) / (SUM(input_tokens + output_tokens) / 1000.0), 6) AS cost_per_1k_tokens,
               ROUND(AVG(input_tokens + output_tokens), 2) AS avg_tokens_per_request,
               ROUND(SUM(input_tokens) * 1.0 / NULLIF(SUM(output_tokens), 0), 4) AS input_output_ratio
        FROM usage WHERE 1=1
    """
    args = []
    if date_from:
        query += " AND DATE(created_at) >= ?"
        args.append(date_from)
    if date_to:
        query += " AND DATE(created_at) <= ?"
        args.append(date_to)
    query += " GROUP BY provider, model ORDER BY cost_per_1k_tokens DESC"
    rows = conn.execute(query, args).fetchall()
    return {"efficiency_metrics": _rows_to_dicts(rows)}


def tool_check_health(conn, params):
    row = conn.execute(
        "SELECT COUNT(*) AS total_requests, "
        "MIN(created_at) AS earliest, MAX(created_at) AS latest "
        "FROM usage"
    ).fetchone()

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [r["name"] for r in tables]

    counts = {}
    for t in table_names:
        c = conn.execute(f"SELECT COUNT(*) AS cnt FROM {t}").fetchone()
        counts[t] = c["cnt"]

    return {
        "status": "ok",
        "database": DB_PATH,
        "tables": table_names,
        "table_counts": counts,
        "total_tracked_requests": row["total_requests"],
        "earliest_record": row["earliest"],
        "latest_record": row["latest"]
    }


# ── Tool definitions for tools/list ────────────────────────────────────

TOOLS = [
    {
        "name": "track_usage",
        "description": "Record token usage event",
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {"type": "string", "description": "Provider name (openai, anthropic, etc.)"},
                "model": {"type": "string", "description": "Model identifier"},
                "input_tokens": {"type": "integer", "description": "Number of input tokens"},
                "output_tokens": {"type": "integer", "description": "Number of output tokens"},
                "cost": {"type": "number", "description": "Cost in USD"},
                "request_id": {"type": "string", "description": "Optional external request ID"},
                "created_at": {"type": "string", "description": "ISO timestamp (defaults to now)"}
            },
            "required": ["provider", "model", "input_tokens", "output_tokens", "cost"]
        }
    },
    {
        "name": "get_daily_usage",
        "description": "Aggregate daily token counts and cost with optional date range filter",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "date_to": {"type": "string", "description": "End date (YYYY-MM-DD)"}
            }
        }
    },
    {
        "name": "get_model_breakdown",
        "description": "Usage breakdown by model: total tokens, cost, request count",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "date_to": {"type": "string", "description": "End date (YYYY-MM-DD)"}
            }
        }
    },
    {
        "name": "get_provider_breakdown",
        "description": "Usage breakdown by provider",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "date_to": {"type": "string", "description": "End date (YYYY-MM-DD)"}
            }
        }
    },
    {
        "name": "get_cost_summary",
        "description": "Total cost by period (day/week/month) with budget comparison",
        "inputSchema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "enum": ["day", "week", "month"], "description": "Aggregation period"}
            }
        }
    },
    {
        "name": "set_budget",
        "description": "Set monthly budget limit with alert threshold",
        "inputSchema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "Month in YYYY-MM format"},
                "budget": {"type": "number", "description": "Budget amount in USD"},
                "alert_threshold": {"type": "number", "description": "Alert threshold as fraction (default 0.8)"}
            },
            "required": ["month", "budget"]
        }
    },
    {
        "name": "check_budget",
        "description": "Current month usage vs budget, remaining amount, burn rate",
        "inputSchema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "Month in YYYY-MM (defaults to current)"}
            }
        }
    },
    {
        "name": "get_rate_limits",
        "description": "Track rate limit headers, remaining requests, reset time",
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {"type": "string", "description": "Provider name filter"},
                "update": {
                    "type": "object",
                    "description": "Optional update data",
                    "properties": {
                        "provider": {"type": "string"},
                        "remaining_requests": {"type": "integer"},
                        "total_requests": {"type": "integer"},
                        "reset_time": {"type": "string"}
                    }
                }
            }
        }
    },
    {
        "name": "get_efficiency_metrics",
        "description": "Cost per 1k tokens, avg tokens per request, input/output ratio",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "date_to": {"type": "string", "description": "End date (YYYY-MM-DD)"}
            }
        }
    },
    {
        "name": "check_health",
        "description": "Database status, total tracked requests, earliest/latest record",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]

TOOL_DISPATCH = {
    "track_usage": tool_track_usage,
    "get_daily_usage": tool_get_daily_usage,
    "get_model_breakdown": tool_get_model_breakdown,
    "get_provider_breakdown": tool_get_provider_breakdown,
    "get_cost_summary": tool_get_cost_summary,
    "set_budget": tool_set_budget,
    "check_budget": tool_check_budget,
    "get_rate_limits": tool_get_rate_limits,
    "get_efficiency_metrics": tool_get_efficiency_metrics,
    "check_health": tool_check_health,
}


def handle_request(conn, msg):
    method = msg.get("method")
    id_ = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return make_response(id_, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "usage_api", "version": "1.0.0"}
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return make_response(id_, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if tool_name not in TOOL_DISPATCH:
            return make_error(id_, -32601, f"Unknown tool: {tool_name}")
        try:
            result = TOOL_DISPATCH[tool_name](conn, arguments)
            return make_response(id_, {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
            })
        except Exception as e:
            return make_response(id_, {
                "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                "isError": True
            })

    return make_error(id_, -32601, f"Unknown method: {method}")


async def main():
    conn = get_db()
    init_db(conn)

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
            continue

        if msg.get("method") == "shutdown":
            resp = handle_request(conn, msg)
            if resp:
                sys.stdout.write(resp)
                sys.stdout.flush()
            break

        resp = handle_request(conn, msg)
        if resp is not None:
            sys.stdout.write(resp)
            sys.stdout.flush()

    conn.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
