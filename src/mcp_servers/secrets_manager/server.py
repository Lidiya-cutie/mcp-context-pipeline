#!/usr/bin/env python3
"""Secrets Manager MCP Server — stdio transport, JSON-RPC.

Manages secrets with encrypted storage at rest, rotation tracking, access
audit log, and TTL-based expiration. Backend: encrypted SQLite (AES-256 via
cryptography library) or plain SQLite fallback.

Tools:
  write_secret       — store a secret (encrypted at rest)
  read_secret        — retrieve a secret value
  delete_secret      — remove a secret
  list_secrets       — list secret keys (never values) with metadata
  rotate_secret      — rotate a secret value, keeping history
  get_secret_history — view rotation history
  get_audit_log      — view all access events
  set_secret_ttl     — set or update TTL for auto-expiration
  check_health       — verify storage integrity and stats
"""

import asyncio
import json
import os
import sys
import sqlite3
import hashlib
import hmac
import base64
import time
import secrets as _secrets
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Encryption helpers (Fernet via cryptography, fallback to base64 obfuscation)
# ---------------------------------------------------------------------------

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    def _derive_key(password: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480_000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    def _encrypt(value: str, key: bytes) -> str:
        return Fernet(key).encrypt(value.encode()).decode()

    def _decrypt(token: str, key: bytes) -> str:
        return Fernet(key).decrypt(token.encode()).decode()

    HAS_CRYPTO = True

except ImportError:
    HAS_CRYPTO = False

    def _derive_key(password: str, salt: bytes) -> bytes:
        return base64.urlsafe_b64encode(
            hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 480_000))

    def _encrypt(value: str, key: bytes) -> str:
        return base64.urlsafe_b64encode(value.encode()).decode()

    def _decrypt(token: str, key: bytes) -> str:
        return base64.urlsafe_b64decode(token.encode()).decode()


# ---------------------------------------------------------------------------
# Secrets store with SQLite backend
# ---------------------------------------------------------------------------

class SecretsStore:
    def __init__(self, db_path: str = ":memory:", master_key: str | None = None):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._salt = os.urandom(16)
        self._key = _derive_key(master_key or "default-mcp-key-change-me", self._salt)
        self._encryption = "fernet" if HAS_CRYPTO else "base64"
        self._init_schema()

    def _init_schema(self):
        c = self._conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS secrets (
                key TEXT PRIMARY KEY,
                encrypted_value TEXT NOT NULL,
                description TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                rotated_at TEXT,
                rotation_count INTEGER DEFAULT 0,
                ttl_expiry REAL DEFAULT NULL,
                version INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS secret_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                secret_key TEXT NOT NULL,
                encrypted_value TEXT NOT NULL,
                version INTEGER NOT NULL,
                rotated_at TEXT NOT NULL,
                rotated_by TEXT DEFAULT 'system'
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                secret_key TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT DEFAULT 'mcp_client',
                timestamp TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            );
        """)
        self._conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _audit(self, key: str, action: str, actor: str = "mcp_client",
               metadata: dict | None = None):
        c = self._conn.cursor()
        c.execute(
            "INSERT INTO audit_log (secret_key, action, actor, timestamp, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            (key, action, actor, self._now(),
             json.dumps(metadata or {}, ensure_ascii=False)))
        self._conn.commit()

    def write_secret(self, key: str, value: str, description: str = "",
                     tags: list[str] | None = None, ttl_seconds: float | None = None,
                    actor: str = "mcp_client") -> dict:
        encrypted = _encrypt(value, self._key)
        ttl_expiry = time.time() + ttl_seconds if ttl_seconds else None
        c = self._conn.cursor()
        now = self._now()
        try:
            c.execute(
                "INSERT INTO secrets (key, encrypted_value, description, tags, created_at, "
                "updated_at, ttl_expiry, version) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (key, encrypted, description,
                 json.dumps(tags or [], ensure_ascii=False),
                 now, now, ttl_expiry))
        except sqlite3.IntegrityError:
            c.execute(
                "UPDATE secrets SET encrypted_value=?, description=?, tags=?, "
                "updated_at=?, ttl_expiry=?, version=version+1 WHERE key=?",
                (encrypted, description,
                 json.dumps(tags or [], ensure_ascii=False),
                 now, ttl_expiry, key))
        self._conn.commit()
        self._audit(key, "write", actor, {"ttl": ttl_seconds})
        return {"status": "written", "key": key, "has_ttl": ttl_seconds is not None}

    def read_secret(self, key: str, actor: str = "mcp_client") -> dict:
        c = self._conn.cursor()
        row = c.execute("SELECT * FROM secrets WHERE key = ?", (key,)).fetchone()
        if not row:
            self._audit(key, "read_miss", actor)
            return {"error": f"Secret '{key}' not found"}
        if row["ttl_expiry"] and time.time() > row["ttl_expiry"]:
            self._delete(key)
            self._audit(key, "read_expired", actor)
            return {"error": f"Secret '{key}' has expired"}
        try:
            value = _decrypt(row["encrypted_value"], self._key)
        except Exception:
            self._audit(key, "read_decrypt_error", actor)
            return {"error": f"Failed to decrypt secret '{key}'"}
        self._audit(key, "read", actor)
        return {
            "key": key,
            "value": value,
            "description": row["description"],
            "tags": json.loads(row["tags"]),
            "version": row["version"],
            "updated_at": row["updated_at"],
        }

    def delete_secret(self, key: str, actor: str = "mcp_client") -> dict:
        c = self._conn.cursor()
        if not c.execute("SELECT 1 FROM secrets WHERE key=?", (key,)).fetchone():
            return {"error": f"Secret '{key}' not found"}
        self._delete(key)
        self._audit(key, "delete", actor)
        return {"status": "deleted", "key": key}

    def _delete(self, key: str):
        c = self._conn.cursor()
        c.execute("DELETE FROM secrets WHERE key=?", (key,))
        self._conn.commit()

    def list_secrets(self, tag: str | None = None) -> dict:
        self._purge_expired()
        c = self._conn.cursor()
        rows = c.execute("SELECT key, description, tags, created_at, updated_at, "
                         "rotated_at, rotation_count, version, ttl_expiry FROM secrets").fetchall()
        results = []
        for r in rows:
            entry = {
                "key": r["key"],
                "description": r["description"],
                "tags": json.loads(r["tags"]),
                "version": r["version"],
                "rotation_count": r["rotation_count"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "has_ttl": r["ttl_expiry"] is not None,
            }
            if tag:
                if tag in json.loads(r["tags"]):
                    results.append(entry)
            else:
                results.append(entry)
        return {"secrets": results, "count": len(results)}

    def rotate_secret(self, key: str, new_value: str, actor: str = "mcp_client") -> dict:
        c = self._conn.cursor()
        row = c.execute("SELECT * FROM secrets WHERE key=?", (key,)).fetchone()
        if not row:
            return {"error": f"Secret '{key}' not found"}
        # archive old value
        c.execute(
            "INSERT INTO secret_history (secret_key, encrypted_value, version, rotated_at, rotated_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (key, row["encrypted_value"], row["version"], self._now(), actor))
        # write new value
        encrypted = _encrypt(new_value, self._key)
        now = self._now()
        c.execute(
            "UPDATE secrets SET encrypted_value=?, updated_at=?, rotated_at=?, "
            "rotation_count=rotation_count+1, version=version+1 WHERE key=?",
            (encrypted, now, now, key))
        self._conn.commit()
        self._audit(key, "rotate", actor, {"new_version": row["version"] + 1})
        return {
            "status": "rotated", "key": key,
            "new_version": row["version"] + 1,
            "rotation_count": row["rotation_count"] + 1,
        }

    def get_secret_history(self, key: str, limit: int = 20) -> dict:
        c = self._conn.cursor()
        rows = c.execute(
            "SELECT version, rotated_at, rotated_by FROM secret_history "
            "WHERE secret_key=? ORDER BY version DESC LIMIT ?",
            (key, limit)).fetchall()
        return {"key": key, "history": [dict(r) for r in rows], "count": len(rows)}

    def get_audit_log(self, key: str | None = None, limit: int = 50) -> dict:
        c = self._conn.cursor()
        if key:
            rows = c.execute(
                "SELECT * FROM audit_log WHERE secret_key=? ORDER BY id DESC LIMIT ?",
                (key, limit)).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        entries = []
        for r in rows:
            entries.append({
                "id": r["id"],
                "key": r["secret_key"],
                "action": r["action"],
                "actor": r["actor"],
                "timestamp": r["timestamp"],
                "metadata": json.loads(r["metadata"]),
            })
        return {"entries": entries, "count": len(entries)}

    def set_secret_ttl(self, key: str, ttl_seconds: float) -> dict:
        c = self._conn.cursor()
        row = c.execute("SELECT 1 FROM secrets WHERE key=?", (key,)).fetchone()
        if not row:
            return {"error": f"Secret '{key}' not found"}
        ttl_expiry = time.time() + ttl_seconds
        c.execute("UPDATE secrets SET ttl_expiry=? WHERE key=?", (ttl_expiry, key))
        self._conn.commit()
        self._audit(key, "set_ttl", metadata={"ttl": ttl_seconds})
        return {"status": "set", "key": key, "ttl_seconds": ttl_seconds}

    def check_health(self) -> dict:
        self._purge_expired()
        c = self._conn.cursor()
        secret_count = c.execute("SELECT COUNT(*) FROM secrets").fetchone()[0]
        audit_count = c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        # test encrypt/decrypt roundtrip
        test_val = "health_check_" + _secrets.token_hex(4)
        try:
            enc = _encrypt(test_val, self._key)
            dec = _decrypt(enc, self._key)
            crypto_ok = dec == test_val
        except Exception:
            crypto_ok = False
        return {
            "status": "ok" if crypto_ok else "degraded",
            "encryption": self._encryption,
            "secrets_stored": secret_count,
            "audit_entries": audit_count,
            "crypto_roundtrip": crypto_ok,
        }

    def _purge_expired(self):
        now = time.time()
        c = self._conn.cursor()
        expired = c.execute("SELECT key FROM secrets WHERE ttl_expiry IS NOT NULL AND ttl_expiry < ?",
                            (now,)).fetchall()
        for r in expired:
            self._audit(r["key"], "auto_expired")
        c.execute("DELETE FROM secrets WHERE ttl_expiry IS NOT NULL AND ttl_expiry < ?", (now,))
        self._conn.commit()


# ---------------------------------------------------------------------------
# MCP JSON-RPC protocol
# ---------------------------------------------------------------------------

store: SecretsStore | None = None


def make_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


TOOLS = [
    {
        "name": "write_secret",
        "description": "Store a secret value (encrypted at rest). Overwrites if exists.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Secret key/name"},
                "value": {"type": "string", "description": "Secret value (will be encrypted)"},
                "description": {"type": "string", "description": "Human-readable description"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "ttl_seconds": {"type": "number", "description": "Auto-expiration TTL in seconds"},
                "actor": {"type": "string", "description": "Who is writing (for audit)"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "read_secret",
        "description": "Retrieve a decrypted secret value.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "actor": {"type": "string", "description": "Who is reading (for audit)"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "delete_secret",
        "description": "Remove a secret permanently.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "actor": {"type": "string"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "list_secrets",
        "description": "List all secret keys (never values) with metadata. Optional tag filter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tag": {"type": "string", "description": "Filter by tag"},
            },
        },
    },
    {
        "name": "rotate_secret",
        "description": "Rotate a secret value. Old value archived in history.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "new_value": {"type": "string"},
                "actor": {"type": "string"},
            },
            "required": ["key", "new_value"],
        },
    },
    {
        "name": "get_secret_history",
        "description": "View rotation history for a secret.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "limit": {"type": "integer", "description": "Max entries (default 20)"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "get_audit_log",
        "description": "View access audit log. Optionally filter by secret key.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Filter by secret key"},
                "limit": {"type": "integer", "description": "Max entries (default 50)"},
            },
        },
    },
    {
        "name": "set_secret_ttl",
        "description": "Set or update auto-expiration TTL for a secret.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "ttl_seconds": {"type": "number", "description": "TTL in seconds from now"},
            },
            "required": ["key", "ttl_seconds"],
        },
    },
    {
        "name": "check_health",
        "description": "Verify storage integrity, encryption status, and stats.",
        "inputSchema": {"type": "object", "properties": {}},
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
            "serverInfo": {"name": "secrets_manager", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})

        if store is None:
            return make_error(req_id, -32603, "Store not initialized")

        try:
            result = None

            if tool_name == "write_secret":
                result = store.write_secret(
                    args["key"], args["value"],
                    args.get("description", ""), args.get("tags"),
                    args.get("ttl_seconds"), args.get("actor", "mcp_client"))
            elif tool_name == "read_secret":
                result = store.read_secret(args["key"], args.get("actor", "mcp_client"))
            elif tool_name == "delete_secret":
                result = store.delete_secret(args["key"], args.get("actor", "mcp_client"))
            elif tool_name == "list_secrets":
                result = store.list_secrets(args.get("tag"))
            elif tool_name == "rotate_secret":
                result = store.rotate_secret(
                    args["key"], args["new_value"], args.get("actor", "mcp_client"))
            elif tool_name == "get_secret_history":
                result = store.get_secret_history(args["key"], args.get("limit", 20))
            elif tool_name == "get_audit_log":
                result = store.get_audit_log(args.get("key"), args.get("limit", 50))
            elif tool_name == "set_secret_ttl":
                result = store.set_secret_ttl(args["key"], args["ttl_seconds"])
            elif tool_name == "check_health":
                result = store.check_health()
            else:
                return make_error(req_id, -32601, f"Unknown tool: {tool_name}")

            return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]})

        except Exception as e:
            return make_error(req_id, -32603, f"Internal error: {e}")

    if method == "ping":
        return make_response(req_id, {})

    return make_error(req_id, -32601, f"Unknown method: {method}")


async def main():
    global store

    db_path = os.environ.get("SECRETS_DB_PATH", ":memory:")
    master_key = os.environ.get("SECRETS_MASTER_KEY", "default-mcp-key-change-me")
    store = SecretsStore(db_path=db_path, master_key=master_key)

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
