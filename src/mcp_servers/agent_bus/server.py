#!/usr/bin/env python3
"""Agent Bus MCP Server — stdio transport, JSON-RPC.

Pub/sub message bus for coordinating sub-agents. Supports channels,
subscriptions, message publishing, shared state, locks, and presence.

Backend: in-memory by default, optional Redis for persistence.

Tools:
  create_channel     — create a named communication channel
  list_channels      — list all channels with subscriber counts
  delete_channel     — remove a channel
  subscribe          — subscribe an agent to a channel
  unsubscribe        — remove agent from channel
  publish            — send a message to all channel subscribers
  poll_messages      — retrieve pending messages for an agent
  get_state          — read shared state key
  set_state          — write shared state key (with optional TTL)
  delete_state       — remove a state key
  list_state         — list all state keys/values
  acquire_lock       — acquire a named mutex (with timeout)
  release_lock       — release a mutex
  list_locks         — show all active locks
  register_agent     — register agent with role and metadata
  deregister_agent   — remove agent from bus
  list_agents        — list all registered agents and status
  heartbeat          — update agent heartbeat timestamp
"""

import asyncio
import json
import os
import sys
import time
import uuid
import threading
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# In-memory message bus
# ---------------------------------------------------------------------------

class AgentBus:
    def __init__(self):
        self.channels: dict[str, dict] = {}
        self.subscriptions: dict[str, dict[str, dict]] = {}  # channel -> {agent_id: meta}
        self.mailboxes: dict[str, list[dict]] = {}  # agent_id -> [messages]
        self.state: dict[str, dict] = {}  # key -> {value, updated_at, updated_by, ttl_expiry}
        self.locks: dict[str, dict] = {}  # lock_name -> {holder, acquired_at, timeout}
        self.agents: dict[str, dict] = {}  # agent_id -> {role, metadata, registered_at, last_heartbeat}

    # --- channels ---

    def create_channel(self, name: str, metadata: dict | None = None) -> dict:
        if name in self.channels:
            return {"error": f"Channel '{name}' already exists"}
        self.channels[name] = {
            "name": name,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "message_count": 0,
        }
        self.subscriptions[name] = {}
        return {"status": "created", "channel": name}

    def list_channels(self) -> list[dict]:
        result = []
        for name, ch in self.channels.items():
            result.append({
                "name": name,
                "subscribers": len(self.subscriptions.get(name, {})),
                "message_count": ch.get("message_count", 0),
                "created_at": ch.get("created_at"),
            })
        return result

    def delete_channel(self, name: str) -> dict:
        if name not in self.channels:
            return {"error": f"Channel '{name}' not found"}
        del self.channels[name]
        self.subscriptions.pop(name, None)
        return {"status": "deleted", "channel": name}

    # --- subscriptions ---

    def subscribe(self, channel: str, agent_id: str) -> dict:
        if channel not in self.channels:
            return {"error": f"Channel '{channel}' not found"}
        self.subscriptions[channel][agent_id] = {
            "subscribed_at": datetime.now(timezone.utc).isoformat()
        }
        return {"status": "subscribed", "channel": channel, "agent": agent_id}

    def unsubscribe(self, channel: str, agent_id: str) -> dict:
        if channel not in self.subscriptions:
            return {"error": f"Channel '{channel}' not found"}
        if agent_id not in self.subscriptions[channel]:
            return {"error": f"Agent '{agent_id}' not subscribed to '{channel}'"}
        del self.subscriptions[channel][agent_id]
        return {"status": "unsubscribed", "channel": channel, "agent": agent_id}

    # --- messaging ---

    def publish(self, channel: str, sender: str, message: Any,
                message_type: str = "info") -> dict:
        if channel not in self.channels:
            return {"error": f"Channel '{channel}' not found"}
        msg = {
            "id": str(uuid.uuid4())[:8],
            "channel": channel,
            "sender": sender,
            "type": message_type,
            "payload": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        subscribers = self.subscriptions.get(channel, {})
        delivered = 0
        for agent_id in subscribers:
            if agent_id == sender:
                continue  # skip self
            if agent_id not in self.mailboxes:
                self.mailboxes[agent_id] = []
            self.mailboxes[agent_id].append(msg)
            delivered += 1
        self.channels[channel]["message_count"] = self.channels[channel].get("message_count", 0) + 1
        return {"status": "published", "message_id": msg["id"], "delivered_to": delivered}

    def poll_messages(self, agent_id: str, limit: int = 50) -> dict:
        if agent_id not in self.mailboxes:
            return {"messages": [], "count": 0}
        msgs = self.mailboxes[agent_id][-limit:]
        self.mailboxes[agent_id] = self.mailboxes[agent_id][len(msgs):]
        return {"messages": msgs, "count": len(msgs)}

    # --- shared state ---

    def get_state(self, key: str) -> dict:
        if key not in self.state:
            return {"key": key, "exists": False}
        entry = self.state[key]
        if entry.get("ttl_expiry") and time.time() > entry["ttl_expiry"]:
            del self.state[key]
            return {"key": key, "exists": False}
        return {"key": key, "exists": True, "value": entry["value"],
                "updated_at": entry["updated_at"], "updated_by": entry["updated_by"]}

    def set_state(self, key: str, value: Any, updated_by: str,
                  ttl_seconds: float | None = None) -> dict:
        entry = {
            "value": value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": updated_by,
        }
        if ttl_seconds:
            entry["ttl_expiry"] = time.time() + ttl_seconds
        self.state[key] = entry
        return {"status": "set", "key": key, "ttl": ttl_seconds}

    def delete_state(self, key: str) -> dict:
        if key not in self.state:
            return {"error": f"Key '{key}' not found"}
        del self.state[key]
        return {"status": "deleted", "key": key}

    def list_state(self) -> dict:
        now = time.time()
        expired = [k for k, v in self.state.items() if v.get("ttl_expiry") and now > v["ttl_expiry"]]
        for k in expired:
            del self.state[k]
        return {"keys": list(self.state.keys()), "count": len(self.state)}

    # --- locks ---

    def acquire_lock(self, lock_name: str, holder: str,
                     timeout_seconds: float = 300.0) -> dict:
        now = time.time()
        if lock_name in self.locks:
            lock = self.locks[lock_name]
            if lock["timeout"] and now > lock["timeout"]:
                del self.locks[lock_name]  # expired
            else:
                return {"status": "locked", "holder": lock["holder"],
                        "retry_after": round(lock["timeout"] - now, 1)}
        self.locks[lock_name] = {
            "holder": holder,
            "acquired_at": datetime.now(timezone.utc).isoformat(),
            "timeout": now + timeout_seconds,
        }
        return {"status": "acquired", "lock": lock_name, "holder": holder,
                "expires_in": timeout_seconds}

    def release_lock(self, lock_name: str, holder: str) -> dict:
        if lock_name not in self.locks:
            return {"error": f"Lock '{lock_name}' not found"}
        lock = self.locks[lock_name]
        if lock["holder"] != holder:
            return {"error": f"Lock '{lock_name}' held by '{lock['holder']}', not '{holder}'"}
        del self.locks[lock_name]
        return {"status": "released", "lock": lock_name}

    def list_locks(self) -> dict:
        now = time.time()
        active = {}
        expired = []
        for name, lock in self.locks.items():
            if lock["timeout"] and now > lock["timeout"]:
                expired.append(name)
            else:
                active[name] = {"holder": lock["holder"],
                                "expires_in": round(lock["timeout"] - now, 1)}
        for name in expired:
            del self.locks[name]
        return {"locks": active, "count": len(active)}

    # --- agents ---

    def register_agent(self, agent_id: str, role: str,
                       metadata: dict | None = None) -> dict:
        self.agents[agent_id] = {
            "role": role,
            "metadata": metadata or {},
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        }
        if agent_id not in self.mailboxes:
            self.mailboxes[agent_id] = []
        return {"status": "registered", "agent": agent_id, "role": role}

    def deregister_agent(self, agent_id: str) -> dict:
        if agent_id not in self.agents:
            return {"error": f"Agent '{agent_id}' not found"}
        # unsubscribe from all channels
        for ch in list(self.subscriptions.keys()):
            self.subscriptions[ch].pop(agent_id, None)
        del self.agents[agent_id]
        self.mailboxes.pop(agent_id, None)
        # release all locks
        for lock_name in list(self.locks.keys()):
            if self.locks[lock_name]["holder"] == agent_id:
                del self.locks[lock_name]
        return {"status": "deregistered", "agent": agent_id}

    def list_agents(self) -> dict:
        result = []
        for aid, info in self.agents.items():
            result.append({
                "id": aid,
                "role": info["role"],
                "metadata": info.get("metadata", {}),
                "last_heartbeat": info.get("last_heartbeat"),
                "pending_messages": len(self.mailboxes.get(aid, [])),
            })
        return {"agents": result, "count": len(result)}

    def heartbeat(self, agent_id: str) -> dict:
        if agent_id not in self.agents:
            return {"error": f"Agent '{agent_id}' not found"}
        self.agents[agent_id]["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        pending = len(self.mailboxes.get(agent_id, []))
        return {"status": "ok", "pending_messages": pending}


# ---------------------------------------------------------------------------
# MCP JSON-RPC protocol
# ---------------------------------------------------------------------------

bus: AgentBus | None = None


def make_response(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


TOOLS = [
    {
        "name": "create_channel",
        "description": "Create a named communication channel for agent messaging.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Channel name"},
                "metadata": {"type": "object", "description": "Optional channel metadata"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_channels",
        "description": "List all channels with subscriber counts and message counts.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "delete_channel",
        "description": "Remove a channel and all subscriptions.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "subscribe",
        "description": "Subscribe an agent to a channel to receive messages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string"},
                "agent_id": {"type": "string", "description": "Agent identifier"},
            },
            "required": ["channel", "agent_id"],
        },
    },
    {
        "name": "unsubscribe",
        "description": "Remove agent subscription from a channel.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string"},
                "agent_id": {"type": "string"},
            },
            "required": ["channel", "agent_id"],
        },
    },
    {
        "name": "publish",
        "description": "Send a message to all subscribers of a channel (except sender).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string"},
                "sender": {"type": "string", "description": "Sender agent ID"},
                "message": {"description": "Message payload (any type)"},
                "message_type": {"type": "string", "description": "Message type tag (default: info)"},
            },
            "required": ["channel", "sender", "message"],
        },
    },
    {
        "name": "poll_messages",
        "description": "Retrieve and clear pending messages for an agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "limit": {"type": "integer", "description": "Max messages to return (default 50)"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "get_state",
        "description": "Read a shared state key.",
        "inputSchema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "set_state",
        "description": "Write a shared state key with optional TTL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {"description": "Value (any type)"},
                "updated_by": {"type": "string", "description": "Agent ID writing the state"},
                "ttl_seconds": {"type": "number", "description": "Optional TTL in seconds"},
            },
            "required": ["key", "value", "updated_by"],
        },
    },
    {
        "name": "delete_state",
        "description": "Remove a shared state key.",
        "inputSchema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "list_state",
        "description": "List all shared state keys.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "acquire_lock",
        "description": "Acquire a named mutex lock. Auto-expires after timeout.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lock_name": {"type": "string"},
                "holder": {"type": "string", "description": "Agent ID acquiring the lock"},
                "timeout_seconds": {"type": "number", "description": "Lock timeout (default 300s)"},
            },
            "required": ["lock_name", "holder"],
        },
    },
    {
        "name": "release_lock",
        "description": "Release a mutex lock.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lock_name": {"type": "string"},
                "holder": {"type": "string", "description": "Agent ID releasing the lock"},
            },
            "required": ["lock_name", "holder"],
        },
    },
    {
        "name": "list_locks",
        "description": "List all active locks.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "register_agent",
        "description": "Register an agent with role and metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "role": {"type": "string", "description": "Agent role (coder, tester, reviewer, etc.)"},
                "metadata": {"type": "object"},
            },
            "required": ["agent_id", "role"],
        },
    },
    {
        "name": "deregister_agent",
        "description": "Remove agent from bus, unsubscribe from channels, release locks.",
        "inputSchema": {
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
            "required": ["agent_id"],
        },
    },
    {
        "name": "list_agents",
        "description": "List all registered agents with status.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "heartbeat",
        "description": "Update agent heartbeat and get pending message count.",
        "inputSchema": {
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
            "required": ["agent_id"],
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
            "serverInfo": {"name": "agent_bus", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})

        if bus is None:
            return make_error(req_id, -32603, "Bus not initialized")

        try:
            result = None

            if tool_name == "create_channel":
                result = bus.create_channel(args["name"], args.get("metadata"))
            elif tool_name == "list_channels":
                result = {"channels": bus.list_channels()}
            elif tool_name == "delete_channel":
                result = bus.delete_channel(args["name"])
            elif tool_name == "subscribe":
                result = bus.subscribe(args["channel"], args["agent_id"])
            elif tool_name == "unsubscribe":
                result = bus.unsubscribe(args["channel"], args["agent_id"])
            elif tool_name == "publish":
                result = bus.publish(args["channel"], args["sender"],
                                     args["message"], args.get("message_type", "info"))
            elif tool_name == "poll_messages":
                result = bus.poll_messages(args["agent_id"], args.get("limit", 50))
            elif tool_name == "get_state":
                result = bus.get_state(args["key"])
            elif tool_name == "set_state":
                result = bus.set_state(args["key"], args["value"],
                                       args["updated_by"], args.get("ttl_seconds"))
            elif tool_name == "delete_state":
                result = bus.delete_state(args["key"])
            elif tool_name == "list_state":
                result = bus.list_state()
            elif tool_name == "acquire_lock":
                result = bus.acquire_lock(args["lock_name"], args["holder"],
                                          args.get("timeout_seconds", 300.0))
            elif tool_name == "release_lock":
                result = bus.release_lock(args["lock_name"], args["holder"])
            elif tool_name == "list_locks":
                result = bus.list_locks()
            elif tool_name == "register_agent":
                result = bus.register_agent(args["agent_id"], args["role"], args.get("metadata"))
            elif tool_name == "deregister_agent":
                result = bus.deregister_agent(args["agent_id"])
            elif tool_name == "list_agents":
                result = bus.list_agents()
            elif tool_name == "heartbeat":
                result = bus.heartbeat(args["agent_id"])
            else:
                return make_error(req_id, -32601, f"Unknown tool: {tool_name}")

            return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]})

        except Exception as e:
            return make_error(req_id, -32603, f"Internal error: {e}")

    if method == "ping":
        return make_response(req_id, {})

    return make_error(req_id, -32601, f"Unknown method: {method}")


async def main():
    global bus
    bus = AgentBus()

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
