#!/usr/bin/env python3
"""db_read MCP server — read-only database access via stdio JSON-RPC."""

import json
import sys
import os
import sqlite3
import subprocess
import re

MAX_ROWS = 500
PROTOCOL_VERSION = "2024-11-05"

SELECT_RE = re.compile(r"^\s*SELECT\s", re.IGNORECASE)

db_type = os.environ.get("DB_TYPE", "sqlite").lower()
db_path = os.environ.get("DB_PATH", ":memory:")
pg_url = os.environ.get("PG_URL", "")
mysql_url = os.environ.get("MYSQL_URL", "")


def make_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def get_sqlite_conn():
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def sqlite_query(sql, params=None):
    conn = get_sqlite_conn()
    try:
        cur = conn.execute(sql, params or [])
        if cur.description:
            columns = [d[0] for d in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchmany(MAX_ROWS + 1)]
            truncated = len(rows) > MAX_ROWS
            if truncated:
                rows = rows[:MAX_ROWS]
            return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated}
        conn.commit()
        return {"affected": cur.rowcount}
    finally:
        conn.close()


def psql_exec(sql):
    cmd = ["psql", pg_url, "-t", "-A", "-F", "\t", "-c", sql]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "psql error")
    return r.stdout.strip()


def mysql_exec(sql):
    cmd = ["mysql", mysql_url, "-N", "-B", "-e", sql]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "mysql error")
    return r.stdout.strip()


def pg_query(sql):
    raw = psql_exec(sql)
    if not raw:
        return {"columns": [], "rows": [], "row_count": 0, "truncated": False}
    lines = raw.split("\n")
    rows = []
    for line in lines:
        if line:
            vals = line.split("\t")
            rows.append(vals)
    col_count = len(rows[0]) if rows else 0
    columns = [f"col{i}" for i in range(col_count)]
    truncated = len(rows) > MAX_ROWS
    if truncated:
        rows = rows[:MAX_ROWS]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated}


def pg_query_with_columns(sql):
    sql_wrapped = f"SELECT * FROM ({sql}) AS _q LIMIT {MAX_ROWS + 1}"
    header_sql = f"SELECT column_name FROM information_schema.columns WHERE 1=0"
    cmd = ["psql", pg_url, "-A", "-F", "\t", "-c", sql_wrapped]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "psql error")
    output = r.stdout.strip()
    if not output:
        return {"columns": [], "rows": [], "row_count": 0, "truncated": False}
    lines = output.split("\n")
    if len(lines) < 2:
        return {"columns": [], "rows": [], "row_count": 0, "truncated": False}
    columns = lines[0].split("\t")
    data_lines = lines[2:]
    rows = []
    for line in data_lines:
        if line:
            rows.append(line.split("\t"))
    truncated = len(rows) > MAX_ROWS
    if truncated:
        rows = rows[:MAX_ROWS]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated}


def mysql_query(sql):
    raw = mysql_exec(sql)
    if not raw:
        return {"columns": [], "rows": [], "row_count": 0, "truncated": False}
    lines = raw.split("\n")
    rows = []
    for line in lines:
        if line:
            rows.append(line.split("\t"))
    col_count = len(rows[0]) if rows else 0
    columns = [f"col{i}" for i in range(col_count)]
    truncated = len(rows) > MAX_ROWS
    if truncated:
        rows = rows[:MAX_ROWS]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated}


def mysql_query_with_columns(sql):
    limit_sql = f"SELECT * FROM ({sql}) AS _q LIMIT {MAX_ROWS + 1}"
    cmd = ["mysql", mysql_url, "-B", "-e", limit_sql]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "mysql error")
    output = r.stdout.strip()
    if not output:
        return {"columns": [], "rows": [], "row_count": 0, "truncated": False}
    lines = output.split("\n")
    columns = lines[0].split("\t") if lines else []
    data_lines = lines[1:]
    rows = []
    for line in data_lines:
        if line:
            rows.append(line.split("\t"))
    truncated = len(rows) > MAX_ROWS
    if truncated:
        rows = rows[:MAX_ROWS]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated}


def run_query(sql):
    if db_type == "sqlite":
        return sqlite_query(sql)
    elif db_type == "postgresql":
        return pg_query_with_columns(sql)
    elif db_type == "mysql":
        return mysql_query_with_columns(sql)
    else:
        raise RuntimeError(f"Unsupported DB_TYPE: {db_type}")


def run_scalar(sql):
    if db_type == "sqlite":
        conn = get_sqlite_conn()
        try:
            cur = conn.execute(sql)
            row = cur.fetchone()
            return row[0] if row else None
        finally:
            conn.close()
    elif db_type == "postgresql":
        result = psql_exec(sql)
        return result.split("\n")[0] if result else None
    elif db_type == "mysql":
        result = mysql_exec(sql)
        return result.split("\n")[0] if result else None


def run_raw(sql):
    if db_type == "sqlite":
        conn = get_sqlite_conn()
        try:
            conn.execute(sql)
            conn.commit()
        finally:
            conn.close()
    elif db_type == "postgresql":
        psql_exec(sql)
    elif db_type == "mysql":
        mysql_exec(sql)


def validate_select(sql):
    stripped = sql.strip().rstrip(";").strip()
    if not SELECT_RE.match(stripped):
        raise ValueError("Only SELECT queries are allowed")
    if re.search(r";\s*\S", sql):
        raise ValueError("Multiple statements are not allowed")
    return stripped


def ensure_not_select(sql):
    if SELECT_RE.match(sql.strip()):
        raise ValueError("SELECT queries not allowed here")


TOOLS = [
    {
        "name": "execute_query",
        "description": "Execute a SELECT query and return results as JSON columns+rows. Only SELECT is allowed. Results capped at 500 rows.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SELECT query to execute"}
            },
            "required": ["sql"]
        }
    },
    {
        "name": "list_tables",
        "description": "List all tables with row counts and sizes.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "describe_table",
        "description": "Describe table columns with types, nullable, defaults, constraints.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name"}
            },
            "required": ["table"]
        }
    },
    {
        "name": "get_table_create",
        "description": "Get CREATE TABLE statement for a table.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name"}
            },
            "required": ["table"]
        }
    },
    {
        "name": "get_indexes",
        "description": "List indexes for a table with columns, unique flag, type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name"}
            },
            "required": ["table"]
        }
    },
    {
        "name": "get_foreign_keys",
        "description": "List foreign key relationships with referenced table/column and on delete/update actions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name"}
            },
            "required": ["table"]
        }
    },
    {
        "name": "get_row_count",
        "description": "Get exact or estimated row count for a table, optionally with a WHERE clause.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name"},
                "where": {"type": "string", "description": "Optional WHERE clause (without the WHERE keyword)"}
            },
            "required": ["table"]
        }
    },
    {
        "name": "search_data",
        "description": "LIKE search across all text columns of a table. Returns matching rows.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name"},
                "search": {"type": "string", "description": "Search term"},
                "limit": {"type": "integer", "description": "Max rows to return (default 100)"}
            },
            "required": ["table", "search"]
        }
    },
    {
        "name": "check_health",
        "description": "Verify database connection, type, version, size.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
]


def tool_execute_query(args):
    sql = args["sql"]
    validate_select(sql)
    return run_query(sql)


def tool_list_tables(_args):
    if db_type == "sqlite":
        return sqlite_query(
            "SELECT name as table_name, (SELECT COUNT(*) FROM pragma_table_info(name)) as column_count "
            "FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    elif db_type == "postgresql":
        return pg_query_with_columns(
            "SELECT schemaname || '.' || tablename AS table_name, "
            "pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) AS total_size, "
            "pg_stat_get_tuples_returned(c.oid) AS row_estimate "
            "FROM pg_tables t JOIN pg_class c ON c.relname = t.tablename "
            "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
            "ORDER BY table_name"
        )
    elif db_type == "mysql":
        return mysql_query_with_columns(
            "SELECT TABLE_NAME AS table_name, TABLE_ROWS AS row_estimate, "
            "DATA_LENGTH + INDEX_LENGTH AS total_bytes, "
            "ROUND((DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 2) AS size_mb "
            "FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() "
            "ORDER BY table_name"
        )


def tool_describe_table(args):
    table = args["table"]
    if db_type == "sqlite":
        return sqlite_query(
            "SELECT name AS column_name, type, CASE WHEN \"notnull\" = 1 THEN 'NO' ELSE 'YES' END AS nullable, "
            "dflt_value AS default_value, pk AS is_primary_key "
            f"FROM pragma_table_xinfo('{table}') ORDER BY cid"
        )
    elif db_type == "postgresql":
        safe = table.replace("'", "''")
        return pg_query_with_columns(
            f"SELECT column_name, data_type, is_nullable, column_default, "
            f"character_maximum_length, numeric_precision "
            f"FROM information_schema.columns WHERE table_name = '{safe}' "
            f"ORDER BY ordinal_position"
        )
    elif db_type == "mysql":
        safe = table.replace("'", "''")
        return mysql_query_with_columns(
            f"SELECT COLUMN_NAME AS column_name, COLUMN_TYPE AS data_type, "
            f"IS_NULLABLE AS nullable, COLUMN_DEFAULT AS default_value, "
            f"COLUMN_KEY AS key_type, EXTRA "
            f"FROM information_schema.COLUMNS WHERE TABLE_NAME = '{safe}' "
            f"AND TABLE_SCHEMA = DATABASE() ORDER BY ORDINAL_POSITION"
        )


def tool_get_table_create(args):
    table = args["table"]
    if db_type == "sqlite":
        result = sqlite_query(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table.replace(chr(39), chr(39)+chr(39))}'"
        )
        if result["rows"]:
            return {"create_statement": result["rows"][0].get("sql", result["rows"][0].get("col0", ""))}
        return {"create_statement": None, "error": "Table not found"}
    elif db_type == "postgresql":
        safe = table.replace("'", "''")
        try:
            raw = psql_exec(f"SHOW CREATE TABLE {safe}")
        except Exception:
            schema = run_scalar(
                f"SELECT table_schema FROM information_schema.tables "
                f"WHERE table_name = '{safe}' LIMIT 1"
            ) or "public"
            raw = psql_exec(
                f"SELECT pg_get_tabledef('{schema}.{safe}'::regclass)"
            )
        return {"create_statement": raw}
    elif db_type == "mysql":
        raw = mysql_exec(f"SHOW CREATE TABLE {table}")
        lines = raw.split("\n")
        if len(lines) >= 2:
            parts = lines[0].split("\t")
            if len(parts) >= 2:
                return {"create_statement": parts[1]}
        return {"create_statement": raw}


def tool_get_indexes(args):
    table = args["table"]
    if db_type == "sqlite":
        return sqlite_query(
            f"SELECT name AS index_name, tbl_name AS table_name, "
            f"CASE WHEN \"unique\" = 1 THEN 'YES' ELSE 'NO' END AS is_unique, "
            f"sql AS index_def "
            f"FROM sqlite_master WHERE type='index' AND tbl_name='{table.replace(chr(39), chr(39)+chr(39))}'"
        )
    elif db_type == "postgresql":
        safe = table.replace("'", "''")
        return pg_query_with_columns(
            f"SELECT i.relname AS index_name, "
            f"array_to_string(array_agg(a.attname), ', ') AS columns, "
            f"CASE WHEN idx.indisunique THEN 'YES' ELSE 'NO' END AS is_unique, "
            f"am.amname AS index_type "
            f"FROM pg_index idx "
            f"JOIN pg_class t ON t.oid = idx.indrelid "
            f"JOIN pg_class i ON i.oid = idx.indexrelid "
            f"JOIN pg_am am ON am.oid = i.relam "
            f"JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(idx.indkey) "
            f"WHERE t.relname = '{safe}' "
            f"GROUP BY i.relname, idx.indisunique, am.amname "
            f"ORDER BY i.relname"
        )
    elif db_type == "mysql":
        return mysql_query_with_columns(f"SHOW INDEX FROM {table}")


def tool_get_foreign_keys(args):
    table = args["table"]
    if db_type == "sqlite":
        return sqlite_query(
            f"SELECT id AS fk_id, \"table\" AS referenced_table, \"from\" AS column_name, "
            f"\"to\" AS referenced_column, on_update, on_delete "
            f"FROM pragma_foreign_key_list('{table}')"
        )
    elif db_type == "postgresql":
        safe = table.replace("'", "''")
        return pg_query_with_columns(
            f"SELECT tc.constraint_name, kcu.column_name, "
            f"ccu.table_name AS referenced_table, ccu.column_name AS referenced_column, "
            f"rc.update_rule AS on_update, rc.delete_rule AS on_delete "
            f"FROM information_schema.table_constraints tc "
            f"JOIN information_schema.key_column_usage kcu "
            f"ON tc.constraint_name = kcu.constraint_name "
            f"JOIN information_schema.constraint_column_usage ccu "
            f"ON tc.constraint_name = ccu.constraint_name "
            f"JOIN information_schema.referential_constraints rc "
            f"ON tc.constraint_name = rc.constraint_name "
            f"WHERE tc.table_name = '{safe}' AND tc.constraint_type = 'FOREIGN KEY'"
        )
    elif db_type == "mysql":
        safe = table.replace("'", "''")
        return mysql_query_with_columns(
            f"SELECT kcu.COLUMN_NAME AS column_name, "
            f"kcu.REFERENCED_TABLE_NAME AS referenced_table, "
            f"kcu.REFERENCED_COLUMN_NAME AS referenced_column, "
            f"rc.UPDATE_RULE AS on_update, rc.DELETE_RULE AS on_delete "
            f"FROM information_schema.KEY_COLUMN_USAGE kcu "
            f"JOIN information_schema.REFERENTIAL_CONSTRAINTS rc "
            f"ON kcu.CONSTRAINT_NAME = rc.CONSTRAINT_NAME "
            f"WHERE kcu.TABLE_NAME = '{safe}' AND kcu.TABLE_SCHEMA = DATABASE() "
            f"AND kcu.REFERENCED_TABLE_NAME IS NOT NULL"
        )


def tool_get_row_count(args):
    table = args["table"]
    where = args.get("where", "")
    safe_table = table.replace("'", "''")
    where_clause = f" WHERE {where}" if where else ""
    if db_type == "sqlite":
        return sqlite_query(f"SELECT COUNT(*) AS count FROM {safe_table}{where_clause}")
    elif db_type == "postgresql":
        return pg_query_with_columns(f"SELECT COUNT(*) AS count FROM {safe_table}{where_clause}")
    elif db_type == "mysql":
        return mysql_query_with_columns(f"SELECT COUNT(*) AS count FROM {safe_table}{where_clause}")


def tool_search_data(args):
    table = args["table"]
    search = args["search"]
    limit = min(args.get("limit", 100), MAX_ROWS)
    safe_table = table.replace("'", "''")
    safe_search = search.replace("'", "''")
    if db_type == "sqlite":
        conn = get_sqlite_conn()
        try:
            cur = conn.execute(f"PRAGMA table_info('{safe_table}')")
            text_cols = [row[1] for row in cur.fetchall()
                         if row[2].upper() in ("TEXT", "VARCHAR", "CHAR", "CLOB")]
        finally:
            conn.close()
        if not text_cols:
            return {"columns": [], "rows": [], "row_count": 0, "truncated": False, "message": "No text columns found"}
        conditions = " OR ".join(f"{c} LIKE '%{safe_search}%'" for c in text_cols)
        return sqlite_query(f"SELECT * FROM {safe_table} WHERE {conditions} LIMIT {limit}")
    elif db_type == "postgresql":
        safe = table.replace("'", "''")
        cols_sql = (
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{safe}' AND data_type IN ('text','character varying','character') "
            f"ORDER BY ordinal_position"
        )
        raw = psql_exec(cols_sql)
        text_cols = [l.strip() for l in raw.split("\n") if l.strip()] if raw else []
        if not text_cols:
            return {"columns": [], "rows": [], "row_count": 0, "truncated": False, "message": "No text columns found"}
        conditions = " OR ".join(f"{c}::text ILIKE '%{safe_search}%'" for c in text_cols)
        return pg_query_with_columns(f"SELECT * FROM {safe_table} WHERE {conditions} LIMIT {limit}")
    elif db_type == "mysql":
        safe = table.replace("'", "''")
        cols_sql = (
            f"SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            f"WHERE TABLE_NAME = '{safe}' AND TABLE_SCHEMA = DATABASE() "
            f"AND DATA_TYPE IN ('text','varchar','char') ORDER BY ORDINAL_POSITION"
        )
        raw = mysql_exec(cols_sql)
        text_cols = [l.strip() for l in raw.split("\n") if l.strip()] if raw else []
        if not text_cols:
            return {"columns": [], "rows": [], "row_count": 0, "truncated": False, "message": "No text columns found"}
        conditions = " OR ".join(f"`{c}` LIKE '%{safe_search}%'" for c in text_cols)
        return mysql_query_with_columns(f"SELECT * FROM `{table}` WHERE {conditions} LIMIT {limit}")


def tool_check_health(_args):
    info = {"db_type": db_type, "status": "ok"}
    try:
        if db_type == "sqlite":
            conn = get_sqlite_conn()
            try:
                ver = conn.execute("SELECT sqlite_version()").fetchone()[0]
                info["version"] = ver
                if db_path != ":memory:":
                    size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
                    info["database_size_bytes"] = size
                else:
                    info["database_size_bytes"] = 0
                    info["database"] = ":memory:"
            finally:
                conn.close()
        elif db_type == "postgresql":
            info["version"] = psql_exec("SELECT version()")
            info["database_size"] = psql_exec("SELECT pg_size_pretty(pg_database_size(current_database()))")
        elif db_type == "mysql":
            info["version"] = mysql_exec("SELECT version()")
            size_raw = mysql_exec(
                "SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) "
                "FROM information_schema.tables WHERE table_schema = DATABASE()"
            )
            info["database_size_mb"] = size_raw
    except Exception as e:
        info["status"] = "error"
        info["error"] = str(e)
    return info


TOOL_DISPATCH = {
    "execute_query": tool_execute_query,
    "list_tables": tool_list_tables,
    "describe_table": tool_describe_table,
    "get_table_create": tool_get_table_create,
    "get_indexes": tool_get_indexes,
    "get_foreign_keys": tool_get_foreign_keys,
    "get_row_count": tool_get_row_count,
    "search_data": tool_search_data,
    "check_health": tool_check_health,
}


def handle_request(msg):
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "db_read", "version": "1.0.0"}
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        handler = TOOL_DISPATCH.get(tool_name)
        if not handler:
            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = handler(arguments)
            return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}]})
        except ValueError as e:
            return make_error(req_id, -32600, str(e))
        except Exception as e:
            return make_error(req_id, -32603, f"Internal error: {e}")

    if method == "ping":
        return make_response(req_id, {})

    return make_error(req_id, -32601, f"Method not found: {method}")


async def main():
    reader = sys.stdin.buffer
    writer = sys.stdout.buffer

    while True:
        line_bytes = await _readline(reader)
        if not line_bytes:
            break
        line = line_bytes.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = make_error(None, -32700, "Parse error")
            writer.write((json.dumps(resp) + "\n").encode())
            writer.flush()
            continue

        resp = handle_request(msg)
        if resp is None:
            continue

        writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode())
        writer.flush()


async def _readline(reader):
    loop = __import__("asyncio").get_event_loop()
    return await loop.run_in_executor(None, reader.readline)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
