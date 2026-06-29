#!/usr/bin/env python3
"""PagerDuty MCP Server — incidents, on-call, services, teams.

Env:
  PAGERDUTY_API_KEY          — REST API token (required)
  PAGERDUTY_ACCOUNT_SUBDOMAIN — account subdomain (optional, used for links)
"""

import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone

BASE_URL = "https://api.pagerduty.com"
API_KEY = os.environ.get("PAGERDUTY_API_KEY", "")
SUBDOMAIN = os.environ.get("PAGERDUTY_ACCOUNT_SUBDOMAIN", "")


# ── helpers ──────────────────────────────────────────────────────────────────

def _headers():
    return {
        "Accept": "application/vnd.pagerduty+json;version=2",
        "Authorization": f"Token token={API_KEY}",
        "Content-Type": "application/json",
    }


def _pd_get(path, params=None):
    """GET from PagerDuty REST API. Returns parsed JSON or raises."""
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            detail = json.loads(body)
        except Exception:
            detail = body
        raise RuntimeError(f"PagerDuty HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"PagerDuty connection error: {e.reason}") from e


def make_response(req_id, result):
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n"


def make_error(req_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "error": err}) + "\n"


# ── tool definitions ─────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "list_incidents",
        "description": "List PagerDuty incidents. Filter by status, urgency, or assignee.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["triggered", "acknowledged", "resolved"],
                    "description": "Incident status filter",
                },
                "urgency": {
                    "type": "string",
                    "enum": ["high", "low"],
                    "description": "Urgency filter",
                },
                "user_id": {
                    "type": "string",
                    "description": "Filter by assigned user ID",
                },
                "service_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by service IDs",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max incidents to return (default 25, max 100)",
                    "default": 25,
                },
            },
        },
    },
    {
        "name": "get_incident",
        "description": "Get detailed incident info: summary, status, severity, timeline, assignments.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "incident_id": {
                    "type": "string",
                    "description": "PagerDuty incident ID (e.g. PXXXXXX or UUID)",
                },
            },
            "required": ["incident_id"],
        },
    },
    {
        "name": "list_services",
        "description": "List services with status, escalation policy, and team.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "team_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by team IDs",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max services to return (default 25)",
                    "default": 25,
                },
            },
        },
    },
    {
        "name": "list_on_call",
        "description": "List current on-call entries, optionally filtered by schedule or escalation policy.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "escalation_policy_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by escalation policy IDs",
                },
                "schedule_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by schedule IDs",
                },
                "user_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by user IDs",
                },
            },
        },
    },
    {
        "name": "list_escalation_policies",
        "description": "List escalation policies with rules and targets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max policies to return (default 25)",
                    "default": 25,
                },
            },
        },
    },
    {
        "name": "list_teams",
        "description": "List teams with member counts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max teams to return (default 25)",
                    "default": 25,
                },
            },
        },
    },
    {
        "name": "get_recent_alerts",
        "description": "Get recent alert history for a service with timestamps and severity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "string",
                    "description": "Service ID to fetch alerts for",
                },
                "since": {
                    "type": "string",
                    "description": "Start time ISO 8601 (default: 24h ago)",
                },
                "until": {
                    "type": "string",
                    "description": "End time ISO 8601 (default: now)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max alerts to return (default 25)",
                    "default": 25,
                },
            },
            "required": ["service_id"],
        },
    },
    {
        "name": "check_health",
        "description": "Verify API key, account info, and connection to PagerDuty.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ── tool implementations ────────────────────────────────────────────────────

def _fmt_user(u):
    return {"id": u.get("id"), "name": u.get("name"), "email": u.get("email"), "html_url": u.get("html_url")}


def _fmt_assignment(a):
    u = a.get("assignee", {})
    return {"user": _fmt_user(u), "at": a.get("at")}


def tool_list_incidents(args):
    params = {"limit": min(args.get("limit", 25), 100)}
    if args.get("status"):
        params["statuses[]"] = args["status"]
    if args.get("urgency"):
        params["urgencies[]"] = args["urgency"]
    if args.get("user_id"):
        params["user_ids[]"] = args["user_id"]
    if args.get("service_ids"):
        for sid in args["service_ids"]:
            params.setdefault("service_ids[]", [])
            if isinstance(params.get("service_ids[]"), list):
                params["service_ids[]"].append(sid)
            else:
                params["service_ids[]"] = [params["service_ids[]"], sid]
    data = _pd_get("/incidents", params)
    incidents = []
    for inc in data.get("incidents", []):
        obj = {
            "id": inc["id"],
            "incident_number": inc.get("incident_number"),
            "title": inc.get("title"),
            "status": inc.get("status"),
            "urgency": inc.get("urgency"),
            "severity": inc.get("severity"),
            "created_at": inc.get("created_at"),
            "html_url": inc.get("html_url"),
            "service": {"id": inc.get("service", {}).get("id"), "name": inc.get("service", {}).get("name")},
            "assignments": [_fmt_assignment(a) for a in inc.get("assignments", [])],
        }
        incidents.append(obj)
    return {"incidents": incidents, "total": data.get("total", len(incidents)), "more": data.get("more", False)}


def tool_get_incident(args):
    inc_id = args["incident_id"]
    data = _pd_get(f"/incidents/{inc_id}")
    inc = data.get("incident", data)

    # Fetch log entries for timeline
    timeline = []
    try:
        log_data = _pd_get(f"/incidents/{inc_id}/log_entries", {"limit": 20})
        for entry in log_data.get("log_entries", []):
            timeline.append({
                "type": entry.get("type"),
                "summary": entry.get("summary"),
                "created_at": entry.get("created_at"),
                "agent": entry.get("agent", {}).get("summary", ""),
            })
    except Exception:
        pass

    return {
        "id": inc["id"],
        "incident_number": inc.get("incident_number"),
        "title": inc.get("title"),
        "status": inc.get("status"),
        "urgency": inc.get("urgency"),
        "severity": inc.get("severity"),
        "summary": inc.get("summary"),
        "created_at": inc.get("created_at"),
        "updated_at": inc.get("updated_at"),
        "resolved_at": inc.get("resolved_at"),
        "html_url": inc.get("html_url"),
        "service": {"id": inc.get("service", {}).get("id"), "name": inc.get("service", {}).get("name")},
        "escalation_policy": {
            "id": inc.get("escalation_policy", {}).get("id"),
            "name": inc.get("escalation_policy", {}).get("name"),
        },
        "assignments": [_fmt_assignment(a) for a in inc.get("assignments", [])],
        "acknowledgements": [_fmt_user(a.get("acknowledger", {})) for a in inc.get("acknowledgements", [])],
        "timeline": timeline,
    }


def tool_list_services(args):
    params = {"limit": min(args.get("limit", 25), 100), "include[]": "teams"}
    if args.get("team_ids"):
        for tid in args["team_ids"]:
            params.setdefault("team_ids[]", [])
            if isinstance(params.get("team_ids[]"), list):
                params["team_ids[]"].append(tid)
            else:
                params["team_ids[]"] = [params["team_ids[]"], tid]
    data = _pd_get("/services", params)
    services = []
    for svc in data.get("services", []):
        obj = {
            "id": svc["id"],
            "name": svc.get("name"),
            "status": svc.get("status"),
            "html_url": svc.get("html_url"),
            "escalation_policy": {
                "id": svc.get("escalation_policy", {}).get("id"),
                "name": svc.get("escalation_policy", {}).get("name"),
            },
            "teams": [{"id": t["id"], "name": t.get("name")} for t in svc.get("teams", [])],
            "created_at": svc.get("created_at"),
            "last_incident_timestamp": svc.get("last_incident_timestamp"),
        }
        services.append(obj)
    return {"services": services, "total": data.get("total", len(services)), "more": data.get("more", False)}


def tool_list_on_call(args):
    params = {"include[]": "users"}
    if args.get("escalation_policy_ids"):
        for eid in args["escalation_policy_ids"]:
            params.setdefault("escalation_policy_ids[]", [])
            if isinstance(params.get("escalation_policy_ids[]"), list):
                params["escalation_policy_ids[]"].append(eid)
            else:
                params["escalation_policy_ids[]"] = [params["escalation_policy_ids[]"], eid]
    if args.get("schedule_ids"):
        for sid in args["schedule_ids"]:
            params.setdefault("schedule_ids[]", [])
            if isinstance(params.get("schedule_ids[]"), list):
                params["schedule_ids[]"].append(sid)
            else:
                params["schedule_ids[]"] = [params["schedule_ids[]"], sid]
    if args.get("user_ids"):
        for uid in args["user_ids"]:
            params.setdefault("user_ids[]", [])
            if isinstance(params.get("user_ids[]"), list):
                params["user_ids[]"].append(uid)
            else:
                params["user_ids[]"] = [params["user_ids[]"], uid]
    data = _pd_get("/oncalls", params)
    oncalls = []
    for oc in data.get("oncalls", []):
        oncalls.append({
            "user": _fmt_user(oc.get("user", {})),
            "escalation_policy": {
                "id": oc.get("escalation_policy", {}).get("id"),
                "name": oc.get("escalation_policy", {}).get("name"),
            },
            "schedule": {
                "id": oc.get("schedule", {}).get("id"),
                "name": oc.get("schedule", {}).get("name"),
            },
            "start": oc.get("start"),
            "end": oc.get("end"),
        })
    return {"oncalls": oncalls}


def tool_list_escalation_policies(args):
    params = {"limit": min(args.get("limit", 25), 100), "include[]": "teams"}
    data = _pd_get("/escalation_policies", params)
    policies = []
    for ep in data.get("escalation_policies", []):
        rules = []
        for r in ep.get("escalation_rules", []):
            targets = []
            for t in r.get("targets", []):
                targets.append({"id": t.get("id"), "type": t.get("type"), "summary": t.get("summary")})
            rules.append({
                "id": r.get("id"),
                "delay": r.get("escalation_delay_in_minutes"),
                "targets": targets,
            })
        policies.append({
            "id": ep["id"],
            "name": ep.get("name"),
            "summary": ep.get("summary"),
            "repeat_enabled": ep.get("repeat_enabled"),
            "teams": [{"id": t["id"], "name": t.get("name")} for t in ep.get("teams", [])],
            "rules": rules,
        })
    return {"escalation_policies": policies, "total": data.get("total", len(policies))}


def tool_list_teams(args):
    params = {"limit": min(args.get("limit", 25), 100)}
    data = _pd_get("/teams", params)
    teams = []
    for t in data.get("teams", []):
        teams.append({
            "id": t["id"],
            "name": t.get("name"),
            "summary": t.get("summary"),
            "html_url": t.get("html_url"),
            "default_role": t.get("default_role"),
        })
    return {"teams": teams, "total": data.get("total", len(teams)), "more": data.get("more", False)}


def tool_get_recent_alerts(args):
    service_id = args["service_id"]
    now = datetime.now(timezone.utc)
    since = args.get("since", (now - __import__("datetime").timedelta(hours=24)).isoformat())
    until = args.get("until", now.isoformat())
    params = {
        "service_ids[]": service_id,
        "since": since,
        "until": until,
        "limit": min(args.get("limit", 25), 100),
        "time_zone": "UTC",
    }
    data = _pd_get("/alerts", params)
    alerts = []
    for a in data.get("alerts", []):
        alerts.append({
            "id": a.get("id"),
            "type": a.get("type"),
            "severity": a.get("severity"),
            "summary": a.get("summary"),
            "status": a.get("status"),
            "created_at": a.get("created_at"),
            "updated_at": a.get("updated_at"),
            "html_url": a.get("html_url"),
            "incident": {"id": a.get("incident", {}).get("id"), "html_url": a.get("incident", {}).get("html_url")},
        })
    return {"alerts": alerts, "total": data.get("total", len(alerts)), "more": data.get("more", False)}


def tool_check_health(args):
    # Test with a lightweight call — abilities endpoint
    data = _pd_get("/abilities")
    abilities = data.get("abilities", [])
    # Also fetch current user info
    user_data = {}
    try:
        users = _pd_get("/users", {"limit": 1})
        if users.get("users"):
            u = users["users"][0]
            user_data = {"id": u.get("id"), "name": u.get("name"), "email": u.get("email")}
    except Exception:
        pass
    return {
        "status": "ok",
        "account_subdomain": SUBDOMAIN or "not configured",
        "abilities_count": len(abilities),
        "abilities_sample": abilities[:10],
        "current_user": user_data or "unable to fetch",
    }


TOOL_MAP = {
    "list_incidents": tool_list_incidents,
    "get_incident": tool_get_incident,
    "list_services": tool_list_services,
    "list_on_call": tool_list_on_call,
    "list_escalation_policies": tool_list_escalation_policies,
    "list_teams": tool_list_teams,
    "get_recent_alerts": tool_get_recent_alerts,
    "check_health": tool_check_health,
}


# ── JSON-RPC dispatcher ──────────────────────────────────────────────────────

def handle_request(msg):
    req_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params", {})

    # ── initialize ──
    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "pagerduty", "version": "1.0.0"},
        })

    # ── initialized (notification, no response) ──
    if method == "notifications/initialized":
        return None

    # ── tools/list ──
    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    # ── tools/call ──
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if tool_name not in TOOL_MAP:
            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = TOOL_MAP[tool_name](arguments)
            return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]})
        except Exception as e:
            return make_response(req_id, {
                "content": [{"type": "text", "text": json.dumps({"error": str(e)}, ensure_ascii=False)}],
                "isError": True,
            })

    # ── ping ──
    if method == "ping":
        return make_response(req_id, {})

    return make_error(req_id, -32601, f"Method not found: {method}")


# ── main loop ────────────────────────────────────────────────────────────────

async def main():
    loop = __import__("asyncio").get_event_loop()
    reader = __import__("asyncio").StreamReader()
    protocol = __import__("asyncio").StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    buf = b""
    while True:
        chunk = await reader.read(65536)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                sys.stderr.write(f"[pagerduty] invalid JSON: {line!r}\n")
                continue
            resp = handle_request(msg)
            if resp is not None:
                sys.stdout.write(resp)
                sys.stdout.flush()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
