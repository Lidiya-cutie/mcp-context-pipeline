#!/usr/bin/env python3
"""Vector DB MCP Server — stdio transport, JSON-RPC.

Lightweight vector database using NumPy (cosine similarity) or optional
ChromaDB backend. Supports CRUD on collections, upsert/search/delete
vectors, metadata filtering.

Tools:
  create_collection    — create a named collection with dimension config
  list_collections     — list all collections
  delete_collection    — drop a collection
  upsert               — insert or update vectors with metadata
  search               — cosine similarity search (top-k)
  get                  — retrieve vectors by ID
  delete               — remove vectors by ID
  count                — count vectors in collection
  info                 — collection stats (dim, count, backend)
"""

import asyncio
import json
import os
import sys
import time
import hashlib
import copy
import math
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# NumPy-based vector store (no external deps beyond numpy)
# ---------------------------------------------------------------------------

def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class InMemoryCollection:
    def __init__(self, name: str, dimension: int):
        self.name = name
        self.dimension = dimension
        self.vectors: dict[str, list[float]] = {}
        self.metadata: dict[str, dict] = {}
        self.created_at = datetime.now(timezone.utc).isoformat()

    def upsert(self, vec_id: str, vector: list[float], metadata: dict | None = None):
        if len(vector) != self.dimension:
            return {"error": f"Vector dimension mismatch: expected {self.dimension}, got {len(vector)}"}
        self.vectors[vec_id] = vector
        self.metadata[vec_id] = metadata or {}
        return {"status": "upserted", "id": vec_id}

    def search(self, query: list[float], top_k: int = 5,
               filter_metadata: dict | None = None,
               threshold: float = 0.0) -> list[dict]:
        if len(query) != self.dimension:
            return []
        results = []
        for vec_id, vec in self.vectors.items():
            # metadata filter
            if filter_metadata:
                meta = self.metadata.get(vec_id, {})
                match = all(meta.get(k) == v for k, v in filter_metadata.items())
                if not match:
                    continue
            score = _cosine_sim(query, vec)
            if score >= threshold:
                results.append({
                    "id": vec_id,
                    "score": round(score, 6),
                    "metadata": self.metadata.get(vec_id, {}),
                })
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def get(self, vec_ids: list[str]) -> list[dict]:
        results = []
        for vid in vec_ids:
            if vid in self.vectors:
                results.append({
                    "id": vid,
                    "vector": self.vectors[vid],
                    "metadata": self.metadata.get(vid, {}),
                })
        return results

    def delete(self, vec_ids: list[str]) -> int:
        deleted = 0
        for vid in vec_ids:
            if vid in self.vectors:
                del self.vectors[vid]
                self.metadata.pop(vid, None)
                deleted += 1
        return deleted

    def count(self) -> int:
        return len(self.vectors)

    def info(self) -> dict:
        return {
            "name": self.name,
            "dimension": self.dimension,
            "count": len(self.vectors),
            "backend": "numpy_in_memory",
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# ChromaDB backend (optional, auto-detected)
# ---------------------------------------------------------------------------

class ChromaCollection:
    def __init__(self, name: str, dimension: int, chroma_client):
        self.name = name
        self.dimension = dimension
        self._client = chroma_client
        self._col = self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine", "dimension": str(dimension)},
        )
        self.created_at = datetime.now(timezone.utc).isoformat()

    def upsert(self, vec_id: str, vector: list[float], metadata: dict | None = None):
        if len(vector) != self.dimension:
            return {"error": f"Vector dimension mismatch: expected {self.dimension}, got {len(vector)}"}
        self._col.upsert(ids=[vec_id], embeddings=[vector], metadatas=[metadata or {}])
        return {"status": "upserted", "id": vec_id}

    def search(self, query: list[float], top_k: int = 5,
               filter_metadata: dict | None = None,
               threshold: float = 0.0) -> list[dict]:
        where = filter_metadata if filter_metadata else None
        results_raw = self._col.query(query_embeddings=[query], n_results=top_k, where=where)
        results = []
        ids = results_raw["ids"][0] if results_raw["ids"] else []
        distances = results_raw["distances"][0] if results_raw["distances"] else []
        metas = results_raw["metadatas"][0] if results_raw["metadatas"] else []
        for i, vid in enumerate(ids):
            dist = distances[i] if i < len(distances) else 1.0
            score = round(1.0 - dist, 6)  # cosine distance → similarity
            if score >= threshold:
                results.append({
                    "id": vid,
                    "score": score,
                    "metadata": metas[i] if i < len(metas) else {},
                })
        return results

    def get(self, vec_ids: list[str]) -> list[dict]:
        results_raw = self._col.get(ids=vec_ids, include=["embeddings", "metadatas"])
        results = []
        ids = results_raw["ids"] if results_raw["ids"] else []
        embeddings = results_raw["embeddings"] if results_raw.get("embeddings") else []
        metas = results_raw["metadatas"] if results_raw.get("metadatas") else []
        for i, vid in enumerate(ids):
            results.append({
                "id": vid,
                "vector": embeddings[i] if i < len(embeddings) else [],
                "metadata": metas[i] if i < len(metas) else {},
            })
        return results

    def delete(self, vec_ids: list[str]) -> int:
        self._col.delete(ids=vec_ids)
        return len(vec_ids)

    def count(self) -> int:
        return self._col.count()

    def info(self) -> dict:
        return {
            "name": self.name,
            "dimension": self.dimension,
            "count": self._col.count(),
            "backend": "chromadb",
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# VectorDB manager
# ---------------------------------------------------------------------------

class VectorDB:
    def __init__(self, persist_dir: str | None = None, backend: str = "auto"):
        self.collections: dict[str, InMemoryCollection | ChromaCollection] = {}
        self._chroma_client = None
        self._backend = backend
        self._persist_dir = persist_dir

        if backend in ("chromadb", "auto"):
            try:
                import chromadb
                if persist_dir:
                    self._chroma_client = chromadb.PersistentClient(path=persist_dir)
                else:
                    self._chroma_client = chromadb.Client()
                self._backend = "chromadb"
            except ImportError:
                self._backend = "numpy"

    def create_collection(self, name: str, dimension: int = 768) -> dict:
        if name in self.collections:
            return {"error": f"Collection '{name}' already exists"}
        if self._backend == "chromadb" and self._chroma_client:
            col = ChromaCollection(name, dimension, self._chroma_client)
        else:
            col = InMemoryCollection(name, dimension)
        self.collections[name] = col
        return {"status": "created", "name": name, "dimension": dimension, "backend": self._backend}

    def list_collections(self) -> list[dict]:
        return [col.info() for col in self.collections.values()]

    def delete_collection(self, name: str) -> dict:
        if name not in self.collections:
            return {"error": f"Collection '{name}' not found"}
        del self.collections[name]
        if self._backend == "chromadb" and self._chroma_client:
            try:
                self._chroma_client.delete_collection(name)
            except Exception:
                pass
        return {"status": "deleted", "name": name}

    def _get_col(self, name: str):
        if name not in self.collections:
            return None, {"error": f"Collection '{name}' not found"}
        return self.collections[name], None

    def upsert(self, collection: str, vectors: list[dict]) -> dict:
        col, err = self._get_col(collection)
        if err:
            return err
        results = []
        for v in vectors:
            vec_id = v.get("id")
            vector = v.get("vector")
            metadata = v.get("metadata")
            if not vec_id or not vector:
                results.append({"error": "Missing 'id' or 'vector'"})
                continue
            results.append(col.upsert(vec_id, vector, metadata))
        return {"results": results, "upserted": len([r for r in results if r.get("status") == "upserted"])}

    def search(self, collection: str, query: list[float], top_k: int = 5,
               filter_metadata: dict | None = None, threshold: float = 0.0) -> dict:
        col, err = self._get_col(collection)
        if err:
            return err
        if len(query) != col.dimension:
            return {"error": f"Query dimension mismatch: expected {col.dimension}, got {len(query)}"}
        results = col.search(query, top_k, filter_metadata, threshold)
        return {"results": results, "total": len(results)}

    def get(self, collection: str, ids: list[str]) -> dict:
        col, err = self._get_col(collection)
        if err:
            return err
        results = col.get(ids)
        return {"results": results, "found": len(results)}

    def delete(self, collection: str, ids: list[str]) -> dict:
        col, err = self._get_col(collection)
        if err:
            return err
        deleted = col.delete(ids)
        return {"status": "deleted", "count": deleted}

    def count(self, collection: str) -> dict:
        col, err = self._get_col(collection)
        if err:
            return err
        return {"collection": collection, "count": col.count()}

    def info(self, collection: str) -> dict:
        col, err = self._get_col(collection)
        if err:
            return err
        return col.info()


# ---------------------------------------------------------------------------
# MCP JSON-RPC protocol
# ---------------------------------------------------------------------------

db: VectorDB | None = None


def make_response(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_request(msg: dict) -> dict | None:
    method = msg.get("method", "")
    params = msg.get("params", {})
    req_id = msg.get("id")

    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "vector_db", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        tools = [
            {
                "name": "create_collection",
                "description": "Create a named vector collection with specified embedding dimension.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Collection name"},
                        "dimension": {"type": "integer", "description": "Vector dimension (default 768)"},
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "list_collections",
                "description": "List all collections with stats.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "delete_collection",
                "description": "Drop a collection and all its vectors.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Collection name"},
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "upsert",
                "description": "Insert or update vectors with optional metadata. Batch supported.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "collection": {"type": "string", "description": "Collection name"},
                        "vectors": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "vector": {"type": "array", "items": {"type": "number"}},
                                    "metadata": {"type": "object"},
                                },
                                "required": ["id", "vector"],
                            },
                            "description": "Array of {id, vector, metadata?} objects",
                        },
                    },
                    "required": ["collection", "vectors"],
                },
            },
            {
                "name": "search",
                "description": "Cosine similarity search. Returns top-k results with scores and metadata.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "collection": {"type": "string", "description": "Collection name"},
                        "query": {"type": "array", "items": {"type": "number"}, "description": "Query vector"},
                        "top_k": {"type": "integer", "description": "Number of results (default 5)"},
                        "filter_metadata": {"type": "object", "description": "Metadata filter key=value pairs"},
                        "threshold": {"type": "number", "description": "Minimum similarity score (default 0.0)"},
                    },
                    "required": ["collection", "query"],
                },
            },
            {
                "name": "get",
                "description": "Retrieve vectors by ID.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "collection": {"type": "string", "description": "Collection name"},
                        "ids": {"type": "array", "items": {"type": "string"}, "description": "Vector IDs"},
                    },
                    "required": ["collection", "ids"],
                },
            },
            {
                "name": "delete",
                "description": "Remove vectors by ID.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "collection": {"type": "string", "description": "Collection name"},
                        "ids": {"type": "array", "items": {"type": "string"}, "description": "Vector IDs to delete"},
                    },
                    "required": ["collection", "ids"],
                },
            },
            {
                "name": "count",
                "description": "Count vectors in a collection.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "collection": {"type": "string", "description": "Collection name"},
                    },
                    "required": ["collection"],
                },
            },
            {
                "name": "info",
                "description": "Get collection stats: dimension, count, backend.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "collection": {"type": "string", "description": "Collection name"},
                    },
                    "required": ["collection"],
                },
            },
        ]
        return make_response(req_id, {"tools": tools})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if db is None:
            return make_error(req_id, -32603, "DB not initialized")

        try:
            result = None

            if tool_name == "create_collection":
                result = db.create_collection(
                    arguments["name"],
                    arguments.get("dimension", 768),
                )

            elif tool_name == "list_collections":
                result = {"collections": db.list_collections()}

            elif tool_name == "delete_collection":
                result = db.delete_collection(arguments["name"])

            elif tool_name == "upsert":
                result = db.upsert(arguments["collection"], arguments["vectors"])

            elif tool_name == "search":
                result = db.search(
                    arguments["collection"],
                    arguments["query"],
                    arguments.get("top_k", 5),
                    arguments.get("filter_metadata"),
                    arguments.get("threshold", 0.0),
                )

            elif tool_name == "get":
                result = db.get(arguments["collection"], arguments["ids"])

            elif tool_name == "delete":
                result = db.delete(arguments["collection"], arguments["ids"])

            elif tool_name == "count":
                result = db.count(arguments["collection"])

            elif tool_name == "info":
                result = db.info(arguments["collection"])

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

    persist_dir = os.environ.get("VECTOR_DB_PATH")
    backend = os.environ.get("VECTOR_DB_BACKEND", "auto")
    db = VectorDB(persist_dir=persist_dir, backend=backend)

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
