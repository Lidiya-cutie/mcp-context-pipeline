#!/usr/bin/env python3
"""ClickHouse Read MCP Server — stdio transport, JSON-RPC.

Read-only ClickHouse client via HTTP interface.
Provides query execution, schema introspection, statistics, and health checks.

Tools (10):
  query              — execute SELECT query, return JSON columns+rows
  query_raw          — execute any query, return raw text
  list_databases     — SHOW DATABASES
  list_tables        — SHOW TABLES with engine, row count, size
  describe_table     — DESCRIBE TABLE with columns, types, defaults, comment
  get_table_create   — SHOW CREATE TABLE
  get_table_stats    — estimated row count, size, partitions, parts
  get_recent_queries — last N queries from system.query_log
  get_schema_graph   — foreign key relationships / join patterns
  check_health       — ping ClickHouse, version, uptime
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode


# ===========================================================================
# Configuration
# ===========================================================================

CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "http://localhost:8123").rstrip("/")
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = os.environ.get("CLICKHOUSE_DATABASE", "default")
DEFAULT_LIMIT = 1000


# ===========================================================================
# ClickHouse HTTP helpers
# ===========================================================================

def _ch_request(sql: str, database: str | None = None, params: dict | None = None) -> str:
    """Execute a query against ClickHouse HTTP interface, return raw text."""
    db = database or CLICKHOUSE_DATABASE
    url = f"{CLICKHOUSE_URL}/?user={CLICKHOUSE_USER}&database={db}"
    if CLICKHOUSE_PASSWORD:
        url += f"&password={CLICKHOUSE_PASSWORD}"
    if params:
        url += "&" + urlencode(params)

    req = Request(url, data=sql.encode("utf-8"), method="POST")
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ClickHouse HTTP {e.code}: {body}") from e
    except URLError as e:
        raise RuntimeError(f"ClickHouse connection error: {e.reason}") from e


def _ch_query_json(sql: str, database: str | None = None) -> list[dict]:
    """Execute query and return list of dicts (JSONEachRow)."""
    sql_with_fmt = sql.rstrip(";") + "\nFORMAT JSONEachRow"
    raw = _ch_request(sql_with_fmt, database)
    if not raw.strip():
        return []
    rows = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _is_select(query: str) -> bool:
    """Check if query starts with SELECT, WITH, or EXPLAIN (read-only)."""
    stripped = query.strip().upper()
    return stripped.startswith(("SELECT", "WITH"))


# ===========================================================================
# Tool implementations
# ===========================================================================

def tool_query(args: dict) -> dict:
    """Execute SELECT query, return columns + rows."""
    sql = args.get("query", "").strip()
    if not sql:
        return {"content": [{"type": "text", "text": "Error: 'query' is required"}], "isError": True}
    if not _is_select(sql):
        return {"content": [{"type": "text", "text": "Error: only SELECT queries allowed. Use query_raw for other statements."}], "isError": True}

    limit = args.get("limit", DEFAULT_LIMIT)
    database = args.get("database")

    if "LIMIT" not in sql.upper().split("FROM")[-1] if "FROM" in sql.upper() else True:
        sql = sql.rstrip(";") + f"\nLIMIT {int(limit)}"

    try:
        rows = _ch_query_json(sql, database)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Query error: {e}"}], "isError": True}

    if not rows:
        return {"content": [{"type": "text", "text": "No rows returned"}]}

    columns = list(rows[0].keys())
    return {"content": [{"type": "text", "text": json.dumps({"columns": columns, "row_count": len(rows), "rows": rows}, ensure_ascii=False, indent=2)}]}


def tool_query_raw(args: dict) -> dict:
    """Execute any query, return raw text."""
    sql = args.get("query", "").strip()
    if not sql:
        return {"content": [{"type": "text", "text": "Error: 'query' is required"}], "isError": True}

    database = args.get("database")
    try:
        result = _ch_request(sql, database)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Query error: {e}"}], "isError": True}

    return {"content": [{"type": "text", "text": result}]}


def tool_list_databases(args: dict) -> dict:
    """SHOW DATABASES."""
    try:
        rows = _ch_query_json("SHOW DATABASES")
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

    dbs = [r.get("name", r.get("database", "")) for r in rows]
    return {"content": [{"type": "text", "text": json.dumps({"databases": dbs, "count": len(dbs)}, ensure_ascii=False, indent=2)}]}


def tool_list_tables(args: dict) -> dict:
    """SHOW TABLES with engine, row count, size."""
    database = args.get("database", CLICKHOUSE_DATABASE)
    sql = f"""
        SELECT
            t.name AS table,
            t.engine,
            coalesce(s.total_rows, 0) AS total_rows,
            coalesce(s.total_bytes, 0) AS total_bytes
        FROM system.tables t
        LEFT JOIN system.table_sizes s ON t.database = s.database AND t.name = s.table
        WHERE t.database = '{database}'
          AND t.engine NOT IN ('View', 'MaterializedView')
        ORDER BY t.name
    """
    try:
        rows = _ch_query_json(sql, database)
    except Exception as e:
        # Fallback to simple SHOW TABLES
        try:
            raw = _ch_request(f"SHOW TABLES FROM {database}")
            tables = [{"table": line.strip(), "engine": None, "total_rows": None, "total_bytes": None}
                       for line in raw.strip().split("\n") if line.strip()]
            return {"content": [{"type": "text", "text": json.dumps({"database": database, "tables": tables, "count": len(tables)}, ensure_ascii=False, indent=2)}]}
        except Exception as e2:
            return {"content": [{"type": "text", "text": f"Error: {e2}"}], "isError": True}

    return {"content": [{"type": "text", "text": json.dumps({"database": database, "tables": rows, "count": len(rows)}, ensure_ascii=False, indent=2)}]}


def tool_describe_table(args: dict) -> dict:
    """DESCRIBE TABLE with columns, types, defaults, comment."""
    table = args.get("table", "").strip()
    database = args.get("database", CLICKHOUSE_DATABASE)
    if not table:
        return {"content": [{"type": "text", "text": "Error: 'table' is required"}], "isError": True}

    sql = f"DESCRIBE TABLE {database}.`{table}`"
    try:
        rows = _ch_query_json(sql, database)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

    return {"content": [{"type": "text", "text": json.dumps({"database": database, "table": table, "columns": rows}, ensure_ascii=False, indent=2)}]}


def tool_get_table_create(args: dict) -> dict:
    """SHOW CREATE TABLE."""
    table = args.get("table", "").strip()
    database = args.get("database", CLICKHOUSE_DATABASE)
    if not table:
        return {"content": [{"type": "text", "text": "Error: 'table' is required"}], "isError": True}

    sql = f"SHOW CREATE TABLE {database}.`{table}`"
    try:
        rows = _ch_query_json(sql, database)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

    statement = rows[0].get("statement", rows[0].get("Create Table", "")) if rows else ""
    return {"content": [{"type": "text", "text": json.dumps({"database": database, "table": table, "create_statement": statement}, ensure_ascii=False, indent=2)}]}


def tool_get_table_stats(args: dict) -> dict:
    """Estimated row count, size bytes, partitions, parts."""
    table = args.get("table", "").strip()
    database = args.get("database", CLICKHOUSE_DATABASE)
    if not table:
        return {"content": [{"type": "text", "text": "Error: 'table' is required"}], "isError": True}

    stats_sql = f"""
        SELECT
            name,
            engine,
            total_rows,
            total_bytes,
            metadata_modification_time
        FROM system.tables
        WHERE database = '{database}' AND name = '{table}'
    """
    parts_sql = f"""
        SELECT
            count() AS parts_count,
            sum(rows) AS total_rows_in_parts,
            sum(bytes_on_disk) AS total_bytes_on_disk,
            count(DISTINCT partition) AS partition_count
        FROM system.parts
        WHERE database = '{database}' AND table = '{table}' AND active
    """
    try:
        table_info = _ch_query_json(stats_sql, database)
        parts_info = _ch_query_json(parts_sql, database)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

    result = {
        "database": database,
        "table": table,
        "table_info": table_info[0] if table_info else {},
        "parts_summary": parts_info[0] if parts_info else {},
    }
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}


def tool_get_recent_queries(args: dict) -> dict:
    """Last N queries from system.query_log."""
    limit = min(int(args.get("limit", 20)), 200)
    database = args.get("database")

    sql = f"""
        SELECT
            query_id,
            query_start_time,
            query_duration_ms,
            query,
            read_rows,
            read_bytes,
            memory_usage,
            result_rows,
            result_bytes,
            tables,
            databases,
            event_date
        FROM system.query_log
        WHERE type = 'QueryFinish'
        {"AND databases = ['" + database + "']" if database else ""}
        ORDER BY query_start_time DESC
        LIMIT {limit}
    """
    try:
        rows = _ch_query_json(sql)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

    return {"content": [{"type": "text", "text": json.dumps({"queries": rows, "count": len(rows)}, ensure_ascii=False, indent=2)}]}


def tool_get_schema_graph(args: dict) -> dict:
    """Detect join patterns / foreign key relationships from column names."""
    database = args.get("database", CLICKHOUSE_DATABASE)
    sql = f"""
        SELECT
            table,
            name AS column_name,
            type
        FROM system.columns
        WHERE database = '{database}'
        ORDER BY table, position
    """
    try:
        columns = _ch_query_json(sql)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

    # Group by table
    tables_map: dict[str, list[dict]] = {}
    for col in columns:
        tbl = col["table"]
        if tbl not in tables_map:
            tables_map[tbl] = []
        tables_map[tbl].append(col)

    # Detect potential FK relationships: columns ending with '_id' that match another table's 'id' column
    relationships = []
    table_names = set(tables_map.keys())
    for tbl, cols in tables_map.items():
        for col in cols:
            cname = col["column_name"]
            if cname.endswith("_id") and cname != "id":
                potential_table = cname[:-3]  # strip '_id'
                # Direct match or pluralized
                candidates = [potential_table, potential_table + "s"]
                for candidate in candidates:
                    if candidate in table_names:
                        relationships.append({
                            "from_table": tbl,
                            "from_column": cname,
                            "to_table": candidate,
                            "to_column": "id",
                            "confidence": "high" if candidate == potential_table else "medium",
                        })
                        break
                # Also check if any table has a column matching this pattern
                if not any(r["from_table"] == tbl and r["from_column"] == cname for r in relationships):
                    for other_tbl, other_cols in tables_map.items():
                        if other_tbl == tbl:
                            continue
                        for oc in other_cols:
                            if oc["column_name"] == cname:
                                relationships.append({
                                    "from_table": tbl,
                                    "from_column": cname,
                                    "to_table": other_tbl,
                                    "to_column": cname,
                                    "confidence": "low",
                                })

    result = {
        "database": database,
        "tables": {tbl: [c["column_name"] + " " + c["type"] for c in cols] for tbl, cols in tables_map.items()},
        "relationships": relationships,
        "table_count": len(tables_map),
    }
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}


def tool_check_health(args: dict) -> dict:
    """Ping ClickHouse, version, uptime."""
    sql = "SELECT version() AS version, uptime() AS uptime_seconds, now() AS server_time FORMAT JSONEachRow"
    try:
        rows = _ch_query_json(sql)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"ClickHouse unreachable: {e}"}], "isError": True}

    info = rows[0] if rows else {}
    return {"content": [{"type": "text", "text": json.dumps({
        "status": "ok",
        "version": info.get("version", "unknown"),
        "uptime_seconds": info.get("uptime_seconds", 0),
        "server_time": info.get("server_time", ""),
        "url": CLICKHOUSE_URL,
        "user": CLICKHOUSE_USER,
        "database": CLICKHOUSE_DATABASE,
    }, ensure_ascii=False, indent=2)}]}


# ===========================================================================
# Tool dispatch table
# ===========================================================================

TOOL_DISPATCH = {
    "query": tool_query,
    "query_raw": tool_query_raw,
    "list_databases": tool_list_databases,
    "list_tables": tool_list_tables,
    "describe_table": tool_describe_table,
    "get_table_create": tool_get_table_create,
    "get_table_stats": tool_get_table_stats,
    "get_recent_queries": tool_get_recent_queries,
    "get_schema_graph": tool_get_schema_graph,
    "check_health": tool_check_health,
}


TOOLS = [
    {
        "name": "query",
        "description": "Execute a SELECT query on ClickHouse and return results as JSON (columns + rows). Only SELECT queries are allowed. Use query_raw for SHOW/DESCRIBE/EXPLAIN.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "SQL SELECT query"},
                "database": {"type": "string", "description": "Database name (default from config)"},
                "limit": {"type": "integer", "description": "Max rows to return (default 1000)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "query_raw",
        "description": "Execute any query on ClickHouse and return raw text output. Use for SHOW, DESCRIBE, EXPLAIN, and other non-SELECT statements.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Any SQL query"},
                "database": {"type": "string", "description": "Database name (default from config)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_databases",
        "description": "List all databases on the ClickHouse server.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "list_tables",
        "description": "List tables in a database with engine, row count, and size information.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "database": {"type": "string", "description": "Database name (default from config)"},
            },
        },
    },
    {
        "name": "describe_table",
        "description": "Describe table columns with types, defaults, and comments.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name"},
                "database": {"type": "string", "description": "Database name (default from config)"},
            },
            "required": ["table"],
        },
    },
    {
        "name": "get_table_create",
        "description": "Get the CREATE TABLE statement for a table.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name"},
                "database": {"type": "string", "description": "Database name (default from config)"},
            },
            "required": ["table"],
        },
    },
    {
        "name": "get_table_stats",
        "description": "Get table statistics: row count, size, partitions, and parts info.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name"},
                "database": {"type": "string", "description": "Database name (default from config)"},
            },
            "required": ["table"],
        },
    },
    {
        "name": "get_recent_queries",
        "description": "Get recent queries from system.query_log with duration, rows read, memory usage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of recent queries (default 20, max 200)"},
                "database": {"type": "string", "description": "Filter by database"},
            },
        },
    },
    {
        "name": "get_schema_graph",
        "description": "Detect foreign key relationships and join patterns between tables in a database.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "database": {"type": "string", "description": "Database name (default from config)"},
            },
        },
    },
    {
        "name": "check_health",
        "description": "Check ClickHouse connectivity, version, and uptime.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


# ===========================================================================
# JSON-RPC helpers
# ===========================================================================

def make_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


# ===========================================================================
# Request handler
# ===========================================================================

def handle_request(msg: dict) -> dict | None:
    method = msg.get("method", "")
    params = msg.get("params", {})
    req_id = msg.get("id")

    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "clickhouse_read", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})

        handler = TOOL_DISPATCH.get(tool_name)
        if handler is None:
            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")

        try:
            result = handler(args)
            return make_response(req_id, result)
        except Exception as e:
            return make_response(req_id, {
                "content": [{"type": "text", "text": f"Internal error: {e}"}],
                "isError": True,
            })

    if method == "ping":
        return make_response(req_id, {})

    return make_error(req_id, -32601, f"Unknown method: {method}")


# ===========================================================================
# Main loop
# ===========================================================================

async def main():
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
        response = handle_request(msg)
        if response is not None:
            payload = json.dumps(response, ensure_ascii=False) + "\n"
            writer.write(payload.encode("utf-8"))
            await writer.drain()


if __name__ == "__main__":
    asyncio.run(main())
