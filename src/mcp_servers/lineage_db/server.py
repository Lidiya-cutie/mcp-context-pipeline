#!/usr/bin/env python3
"""Lineage DB MCP Server — stdio transport, JSON-RPC.

Tracks data-to-model-to-deploy lineage as a directed acyclic graph.
SQLite backend for persistence, pure-Python graph traversal.

Nodes: datasets, features, models, metrics, deploys, experiments.
Edges: typed relationships (derived_from, trained_on, evaluated_with, deployed_as).

Tools:
  add_node           — create a lineage node
  get_node           — retrieve node by ID
  update_node        — update node metadata
  delete_node        — remove node and its edges
  list_nodes         — list nodes with type/tag filters
  add_edge           — create a directed edge between nodes
  get_edges          — get edges for a node (incoming/outgoing)
  delete_edge        — remove an edge
  get_lineage        — trace full lineage (upstream or downstream)
  get_path           — shortest path between two nodes
  get_subgraph       — extract subgraph around a node (N hops)
  get_roots          — find root nodes (no incoming edges)
  get_leaves         — find leaf nodes (no outgoing edges)
  stats              — graph statistics
  export_graph       — export full graph as JSON
  import_graph       — import graph from JSON (merge or replace)
"""

import asyncio
import json
import os
import sys
import sqlite3
import hashlib
from datetime import datetime, timezone
from typing import Any
from collections import deque


# ---------------------------------------------------------------------------
# SQLite-backed lineage graph
# ---------------------------------------------------------------------------

class LineageDB:
    def __init__(self, db_path: str = ":memory:"):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        c = self._conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                name TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS edges (
                edge_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES nodes(node_id),
                FOREIGN KEY (target_id) REFERENCES nodes(node_id),
                UNIQUE(source_id, target_id, edge_type)
            );
            CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
            CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
        """)
        self._conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _edge_id(source: str, target: str, edge_type: str) -> str:
        raw = f"{source}:{target}:{edge_type}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # --- nodes ---

    def add_node(self, node_id: str, node_type: str, name: str,
                 metadata: dict | None = None, tags: list[str] | None = None) -> dict:
        c = self._conn.cursor()
        now = self._now()
        try:
            c.execute(
                "INSERT INTO nodes (node_id, node_type, name, metadata, tags, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (node_id, node_type, name,
                 json.dumps(metadata or {}, ensure_ascii=False),
                 json.dumps(tags or [], ensure_ascii=False), now, now))
            self._conn.commit()
        except sqlite3.IntegrityError:
            return {"error": f"Node '{node_id}' already exists"}
        return {"status": "created", "node_id": node_id, "type": node_type, "name": name}

    def get_node(self, node_id: str) -> dict:
        c = self._conn.cursor()
        row = c.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
        if not row:
            return {"error": f"Node '{node_id}' not found"}
        return self._row_to_node(row)

    def update_node(self, node_id: str, name: str | None = None,
                    metadata: dict | None = None, tags: list[str] | None = None) -> dict:
        existing = self.get_node(node_id)
        if "error" in existing:
            return existing
        new_name = name if name is not None else existing["name"]
        new_meta = metadata if metadata is not None else existing["metadata"]
        new_tags = tags if tags is not None else existing["tags"]
        c = self._conn.cursor()
        c.execute(
            "UPDATE nodes SET name=?, metadata=?, tags=?, updated_at=? WHERE node_id=?",
            (new_name, json.dumps(new_meta, ensure_ascii=False),
             json.dumps(new_tags, ensure_ascii=False), self._now(), node_id))
        self._conn.commit()
        return {"status": "updated", "node_id": node_id}

    def delete_node(self, node_id: str) -> dict:
        c = self._conn.cursor()
        if not c.execute("SELECT 1 FROM nodes WHERE node_id=?", (node_id,)).fetchone():
            return {"error": f"Node '{node_id}' not found"}
        c.execute("DELETE FROM edges WHERE source_id=? OR target_id=?", (node_id, node_id))
        c.execute("DELETE FROM nodes WHERE node_id=?", (node_id,))
        self._conn.commit()
        return {"status": "deleted", "node_id": node_id}

    def list_nodes(self, node_type: str | None = None,
                   tag: str | None = None, limit: int = 100) -> dict:
        c = self._conn.cursor()
        if node_type:
            rows = c.execute("SELECT * FROM nodes WHERE node_type = ? ORDER BY created_at DESC LIMIT ?",
                             (node_type, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM nodes ORDER BY created_at DESC LIMIT ?",
                             (limit,)).fetchall()
        nodes = [self._row_to_node(r) for r in rows]
        if tag:
            nodes = [n for n in nodes if tag in n.get("tags", [])]
        return {"nodes": nodes, "count": len(nodes)}

    def _row_to_node(self, row) -> dict:
        return {
            "node_id": row["node_id"],
            "type": row["node_type"],
            "name": row["name"],
            "metadata": json.loads(row["metadata"]),
            "tags": json.loads(row["tags"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # --- edges ---

    def add_edge(self, source_id: str, target_id: str, edge_type: str,
                 metadata: dict | None = None) -> dict:
        for nid in (source_id, target_id):
            if not self.get_node(nid).get("node_id"):
                return {"error": f"Node '{nid}' not found"}
        eid = self._edge_id(source_id, target_id, edge_type)
        c = self._conn.cursor()
        try:
            c.execute(
                "INSERT INTO edges (edge_id, source_id, target_id, edge_type, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, source_id, target_id, edge_type,
                 json.dumps(metadata or {}, ensure_ascii=False), self._now()))
            self._conn.commit()
        except sqlite3.IntegrityError:
            return {"error": f"Edge '{source_id}'--'{edge_type}'->'{target_id}' already exists"}
        return {"status": "created", "edge_id": eid, "source": source_id,
                "target": target_id, "type": edge_type}

    def get_edges(self, node_id: str, direction: str = "both") -> dict:
        c = self._conn.cursor()
        edges = []
        if direction in ("outgoing", "both"):
            for r in c.execute("SELECT * FROM edges WHERE source_id=?", (node_id,)):
                edges.append({"edge_id": r["edge_id"], "source": r["source_id"],
                              "target": r["target_id"], "type": r["edge_type"],
                              "metadata": json.loads(r["metadata"]), "direction": "outgoing"})
        if direction in ("incoming", "both"):
            for r in c.execute("SELECT * FROM edges WHERE target_id=?", (node_id,)):
                edges.append({"edge_id": r["edge_id"], "source": r["source_id"],
                              "target": r["target_id"], "type": r["edge_type"],
                              "metadata": json.loads(r["metadata"]), "direction": "incoming"})
        return {"node_id": node_id, "edges": edges, "count": len(edges)}

    def delete_edge(self, edge_id: str) -> dict:
        c = self._conn.cursor()
        if not c.execute("SELECT 1 FROM edges WHERE edge_id=?", (edge_id,)).fetchone():
            return {"error": f"Edge '{edge_id}' not found"}
        c.execute("DELETE FROM edges WHERE edge_id=?", (edge_id,))
        self._conn.commit()
        return {"status": "deleted", "edge_id": edge_id}

    # --- graph traversal ---

    def get_lineage(self, node_id: str, direction: str = "upstream",
                    max_depth: int = 10) -> dict:
        if not self.get_node(node_id).get("node_id"):
            return {"error": f"Node '{node_id}' not found"}
        visited_nodes = set()
        visited_edges = set()
        result_nodes = []
        result_edges = []
        queue = deque([(node_id, 0)])
        while queue:
            current, depth = queue.popleft()
            if current in visited_nodes or depth > max_depth:
                continue
            visited_nodes.add(current)
            node = self.get_node(current)
            result_nodes.append(node)
            if direction in ("upstream", "both"):
                for r in self._conn.execute("SELECT * FROM edges WHERE target_id=?", (current,)):
                    if r["edge_id"] not in visited_edges:
                        visited_edges.add(r["edge_id"])
                        result_edges.append({
                            "source": r["source_id"], "target": r["target_id"],
                            "type": r["edge_type"]})
                        queue.append((r["source_id"], depth + 1))
            if direction in ("downstream", "both"):
                for r in self._conn.execute("SELECT * FROM edges WHERE source_id=?", (current,)):
                    if r["edge_id"] not in visited_edges:
                        visited_edges.add(r["edge_id"])
                        result_edges.append({
                            "source": r["source_id"], "target": r["target_id"],
                            "type": r["edge_type"]})
                        queue.append((r["target_id"], depth + 1))
        return {"root": node_id, "direction": direction, "nodes": result_nodes,
                "edges": result_edges, "depth": max_depth}

    def get_path(self, from_id: str, to_id: str) -> dict:
        for nid in (from_id, to_id):
            if not self.get_node(nid).get("node_id"):
                return {"error": f"Node '{nid}' not found"}
        # BFS
        visited = {from_id}
        queue = deque([(from_id, [])])
        while queue:
            current, path = queue.popleft()
            if current == to_id:
                return {"from": from_id, "to": to_id, "path": path, "found": True, "length": len(path)}
            for r in self._conn.execute("SELECT target_id, edge_type FROM edges WHERE source_id=?",
                                         (current,)):
                nid = r["target_id"]
                if nid not in visited:
                    visited.add(nid)
                    queue.append((nid, path + [{"source": current, "target": nid, "type": r["edge_type"]}]))
        return {"from": from_id, "to": to_id, "path": [], "found": False, "length": 0}

    def get_subgraph(self, node_id: str, hops: int = 2) -> dict:
        return self.get_lineage(node_id, direction="both", max_depth=hops)

    def get_roots(self) -> dict:
        c = self._conn.cursor()
        rows = c.execute(
            "SELECT n.* FROM nodes n WHERE n.node_id NOT IN "
            "(SELECT DISTINCT target_id FROM edges)").fetchall()
        return {"roots": [self._row_to_node(r) for r in rows], "count": len(rows)}

    def get_leaves(self) -> dict:
        c = self._conn.cursor()
        rows = c.execute(
            "SELECT n.* FROM nodes n WHERE n.node_id NOT IN "
            "(SELECT DISTINCT source_id FROM edges)").fetchall()
        return {"leaves": [self._row_to_node(r) for r in rows], "count": len(rows)}

    # --- stats / export ---

    def stats(self) -> dict:
        c = self._conn.cursor()
        node_count = c.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edge_count = c.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        type_counts = {}
        for r in c.execute("SELECT node_type, COUNT(*) as cnt FROM nodes GROUP BY node_type"):
            type_counts[r[0]] = r[1]
        edge_type_counts = {}
        for r in c.execute("SELECT edge_type, COUNT(*) as cnt FROM edges GROUP BY edge_type"):
            edge_type_counts[r[0]] = r[1]
        return {
            "nodes": node_count, "edges": edge_count,
            "node_types": type_counts, "edge_types": edge_type_counts,
        }

    def export_graph(self) -> dict:
        nodes = [self._row_to_node(r) for r in
                 self._conn.execute("SELECT * FROM nodes").fetchall()]
        edges = []
        for r in self._conn.execute("SELECT * FROM edges").fetchall():
            edges.append({"edge_id": r["edge_id"], "source": r["source_id"],
                          "target": r["target_id"], "type": r["edge_type"],
                          "metadata": json.loads(r["metadata"])})
        return {"nodes": nodes, "edges": edges}

    def import_graph(self, data: dict, mode: str = "merge") -> dict:
        if mode == "replace":
            self._conn.execute("DELETE FROM edges")
            self._conn.execute("DELETE FROM nodes")
            self._conn.commit()
        nodes_added = 0
        edges_added = 0
        for n in data.get("nodes", []):
            res = self.add_node(
                n["node_id"], n["type"], n["name"],
                n.get("metadata"), n.get("tags"))
            if "created" in res.get("status", ""):
                nodes_added += 1
        for e in data.get("edges", []):
            res = self.add_edge(e["source"], e["target"], e["type"], e.get("metadata"))
            if "created" in res.get("status", ""):
                edges_added += 1
        return {"status": "imported", "nodes_added": nodes_added,
                "edges_added": edges_added, "mode": mode}


# ---------------------------------------------------------------------------
# MCP JSON-RPC protocol
# ---------------------------------------------------------------------------

db: LineageDB | None = None


def make_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


TOOLS = [
    {
        "name": "add_node",
        "description": "Create a lineage node (dataset, feature, model, metric, deploy, experiment).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "Unique node identifier"},
                "node_type": {"type": "string", "description": "Type: dataset, features, model, metrics, deploy, experiment"},
                "name": {"type": "string", "description": "Human-readable name"},
                "metadata": {"type": "object", "description": "Arbitrary metadata"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for filtering"},
            },
            "required": ["node_id", "node_type", "name"],
        },
    },
    {
        "name": "get_node",
        "description": "Retrieve a node by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {"node_id": {"type": "string"}},
            "required": ["node_id"],
        },
    },
    {
        "name": "update_node",
        "description": "Update node name, metadata, or tags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "name": {"type": "string"},
                "metadata": {"type": "object"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "delete_node",
        "description": "Remove a node and all connected edges.",
        "inputSchema": {
            "type": "object",
            "properties": {"node_id": {"type": "string"}},
            "required": ["node_id"],
        },
    },
    {
        "name": "list_nodes",
        "description": "List nodes with optional type and tag filters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_type": {"type": "string", "description": "Filter by type"},
                "tag": {"type": "string", "description": "Filter by tag"},
                "limit": {"type": "integer", "description": "Max results (default 100)"},
            },
        },
    },
    {
        "name": "add_edge",
        "description": "Create a directed edge: source --type--> target.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "target_id": {"type": "string"},
                "edge_type": {"type": "string", "description": "e.g. derived_from, trained_on, evaluated_with, deployed_as"},
                "metadata": {"type": "object"},
            },
            "required": ["source_id", "target_id", "edge_type"],
        },
    },
    {
        "name": "get_edges",
        "description": "Get edges for a node (incoming, outgoing, or both).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "direction": {"type": "string", "enum": ["incoming", "outgoing", "both"], "description": "Default: both"},
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "delete_edge",
        "description": "Remove an edge by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {"edge_id": {"type": "string"}},
            "required": ["edge_id"],
        },
    },
    {
        "name": "get_lineage",
        "description": "Trace full lineage upstream or downstream from a node.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "direction": {"type": "string", "enum": ["upstream", "downstream", "both"]},
                "max_depth": {"type": "integer", "description": "Max traversal depth (default 10)"},
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "get_path",
        "description": "Find shortest path between two nodes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_id": {"type": "string"},
                "to_id": {"type": "string"},
            },
            "required": ["from_id", "to_id"],
        },
    },
    {
        "name": "get_subgraph",
        "description": "Extract subgraph around a node (N hops in all directions).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "hops": {"type": "integer", "description": "Number of hops (default 2)"},
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "get_roots",
        "description": "Find root nodes (no upstream dependencies).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_leaves",
        "description": "Find leaf nodes (no downstream dependents).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "stats",
        "description": "Graph statistics: node/edge counts, type distributions.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "export_graph",
        "description": "Export full graph as JSON (nodes + edges).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "import_graph",
        "description": "Import graph from JSON. Mode: merge (add) or replace (clear + load).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "data": {"type": "object", "description": "Graph data {nodes: [...], edges: [...]}"},
                "mode": {"type": "string", "enum": ["merge", "replace"]},
            },
            "required": ["data"],
        },
    },
]


def handle_request(msg: dict) -> dict | None:
    method = msg.get("method", "")
    params = msg.get("params", {})
    req_id = msg.get("id")

    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "lineage_db", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})

        if db is None:
            return make_error(req_id, -32603, "DB not initialized")

        try:
            result = None

            if tool_name == "add_node":
                result = db.add_node(args["node_id"], args["node_type"],
                                     args["name"], args.get("metadata"), args.get("tags"))
            elif tool_name == "get_node":
                result = db.get_node(args["node_id"])
            elif tool_name == "update_node":
                result = db.update_node(args["node_id"], args.get("name"),
                                        args.get("metadata"), args.get("tags"))
            elif tool_name == "delete_node":
                result = db.delete_node(args["node_id"])
            elif tool_name == "list_nodes":
                result = db.list_nodes(args.get("node_type"), args.get("tag"),
                                       args.get("limit", 100))
            elif tool_name == "add_edge":
                result = db.add_edge(args["source_id"], args["target_id"],
                                     args["edge_type"], args.get("metadata"))
            elif tool_name == "get_edges":
                result = db.get_edges(args["node_id"], args.get("direction", "both"))
            elif tool_name == "delete_edge":
                result = db.delete_edge(args["edge_id"])
            elif tool_name == "get_lineage":
                result = db.get_lineage(args["node_id"], args.get("direction", "upstream"),
                                        args.get("max_depth", 10))
            elif tool_name == "get_path":
                result = db.get_path(args["from_id"], args["to_id"])
            elif tool_name == "get_subgraph":
                result = db.get_subgraph(args["node_id"], args.get("hops", 2))
            elif tool_name == "get_roots":
                result = db.get_roots()
            elif tool_name == "get_leaves":
                result = db.get_leaves()
            elif tool_name == "stats":
                result = db.stats()
            elif tool_name == "export_graph":
                result = db.export_graph()
            elif tool_name == "import_graph":
                result = db.import_graph(args["data"], args.get("mode", "merge"))
            else:
                return make_error(req_id, -32601, f"Unknown tool: {tool_name}")

            return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]})

        except Exception as e:
            return make_error(req_id, -32603, f"Internal error: {e}")

    if method == "ping":
        return make_response(req_id, {})

    return make_error(req_id, -32601, f"Unknown method: {method}")


async def main():
    global db

    db_path = os.environ.get("LINEAGE_DB_PATH", ":memory:")
    db = LineageDB(db_path)

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
