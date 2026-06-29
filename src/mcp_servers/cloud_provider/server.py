#!/usr/bin/env python3
"""MCP server: cloud_provider — AWS/GCP CLI wrapper (stdio, JSON-RPC)."""

import asyncio
import json
import os
import subprocess
import sys
from typing import Any

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "cloud_provider"
SERVER_VERSION = "1.0.0"

CLOUD_PROVIDER = os.environ.get("CLOUD_PROVIDER", "aws").lower()


def make_response(request_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": err}


def _run_cli(cmd: list[str], timeout: int = 30) -> dict:
    """Run a CLI command, return parsed JSON or error structure."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            return {"error": proc.stderr.strip() or f"exit code {proc.returncode}"}
        text = proc.stdout.strip()
        if not text:
            return {"result": []}
        return {"result": json.loads(text)}
    except FileNotFoundError:
        return {"error": f"command not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"error": f"timeout after {timeout}s"}
    except json.JSONDecodeError as exc:
        return {"error": f"JSON parse error: {exc}", "raw": text[:500]}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _aws_region(params: dict) -> list[str]:
    region = params.get("region")
    return ["--region", region] if region else []


def _gcp_project(params: dict) -> list[str]:
    project = params.get("project")
    return ["--project", project] if project else []


def tool_list_instances(params: dict) -> dict:
    if CLOUD_PROVIDER == "gcp":
        project_flag = _gcp_project(params)
        cmd = ["gcloud", "compute", "instances", "list", "--format=json"] + project_flag
    else:
        region_flag = _aws_region(params)
        cmd = ["aws", "ec2", "describe-instances", "--output", "json"] + region_flag
    out = _run_cli(cmd)
    if "error" in out:
        return out
    raw = out.get("result", [])
    if CLOUD_PROVIDER == "gcp":
        items = []
        for inst in raw:
            items.append({
                "id": inst.get("id"),
                "name": inst.get("name"),
                "status": inst.get("status"),
                "zone": inst.get("zone", "").rsplit("/", 1)[-1],
                "machineType": inst.get("machineType", "").rsplit("/", 1)[-1],
                "networkInterfaces": [ni.get("networkIP") for ni in inst.get("networkInterfaces", [])],
            })
        return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}
    else:
        items = []
        for reserv in raw.get("Reservations", []):
            for inst in reserv.get("Instances", []):
                name = ""
                for t in inst.get("Tags", []):
                    if t.get("Key") == "Name":
                        name = t.get("Value", "")
                items.append({
                    "instanceId": inst.get("InstanceId"),
                    "name": name,
                    "state": inst.get("State", {}).get("Name"),
                    "instanceType": inst.get("InstanceType"),
                    "availabilityZone": inst.get("Placement", {}).get("AvailabilityZone"),
                    "privateIp": inst.get("PrivateIpAddress"),
                    "publicIp": inst.get("PublicIpAddress"),
                })
        return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}


def tool_get_instance(params: dict) -> dict:
    instance_id = params.get("instance_id") or params.get("instanceId") or params.get("name")
    if not instance_id:
        return {"error": "instance_id (or name) is required"}

    if CLOUD_PROVIDER == "gcp":
        project_flag = _gcp_project(params)
        zone = params.get("zone", "")
        zone_flag = ["--zone", zone] if zone else []
        cmd = ["gcloud", "compute", "instances", "describe", instance_id, "--format=json"] + zone_flag + project_flag
    else:
        region_flag = _aws_region(params)
        cmd = ["aws", "ec2", "describe-instances", "--instance-ids", instance_id, "--output", "json"] + region_flag

    out = _run_cli(cmd)
    if "error" in out:
        return out
    raw = out.get("result")
    if CLOUD_PROVIDER == "gcp":
        disks = [d.get("source", "").rsplit("/", 1)[-1] for d in raw.get("disks", [])]
        tags = raw.get("labels", {})
        items = {
            "id": raw.get("id"),
            "name": raw.get("name"),
            "status": raw.get("status"),
            "zone": raw.get("zone", "").rsplit("/", 1)[-1],
            "machineType": raw.get("machineType", "").rsplit("/", 1)[-1],
            "cpuPlatform": raw.get("cpuPlatform"),
            "disks": disks,
            "networkInterfaces": raw.get("networkInterfaces", []),
            "tags": tags,
            "metadata": {i["key"]: i["value"] for i in raw.get("metadata", {}).get("items", [])},
        }
        return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}
    else:
        instances = []
        for reserv in raw.get("Reservations", []):
            instances.extend(reserv.get("Instances", []))
        if not instances:
            return {"content": [{"type": "text", "text": "[]"}]}
        inst = instances[0]
        tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
        items = {
            "instanceId": inst.get("InstanceId"),
            "instanceType": inst.get("InstanceType"),
            "state": inst.get("State", {}).get("Name"),
            "availabilityZone": inst.get("Placement", {}).get("AvailabilityZone"),
            "privateIp": inst.get("PrivateIpAddress"),
            "publicIp": inst.get("PublicIpAddress"),
            "subnetId": inst.get("SubnetId"),
            "vpcId": inst.get("VpcId"),
            "tags": tags,
            "securityGroups": [sg.get("GroupId") for sg in inst.get("SecurityGroups", [])],
            "blockDeviceMappings": inst.get("BlockDeviceMappings", []),
        }
        return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}


def tool_list_buckets(params: dict) -> dict:
    if CLOUD_PROVIDER == "gcp":
        project_flag = _gcp_project(params)
        cmd = ["gsutil", "ls", "-p"] + (project_flag[1:] if project_flag else []) if project_flag else ["gsutil", "ls"]
        # fallback to gcloud
        cmd = ["gcloud", "storage", "buckets", "list", "--format=json"] + project_flag
    else:
        cmd = ["aws", "s3api", "list-buckets", "--output", "json"]
    out = _run_cli(cmd)
    if "error" in out:
        return out
    raw = out.get("result", [])
    if CLOUD_PROVIDER == "gcp":
        items = []
        for b in raw if isinstance(raw, list) else [raw]:
            if isinstance(b, dict):
                items.append({"name": b.get("name"), "location": b.get("location"), "storageClass": b.get("storageClass")})
            else:
                items.append({"name": str(b)})
        return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}
    else:
        items = []
        for b in raw.get("Buckets", []):
            items.append({"name": b.get("Name"), "creationDate": b.get("CreationDate")})
        return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}


def tool_list_dns_records(params: dict) -> dict:
    zone_id = params.get("zone_id") or params.get("zoneId") or params.get("zone_name")
    if not zone_id:
        return {"error": "zone_id (or zone_name) is required"}

    if CLOUD_PROVIDER == "gcp":
        project_flag = _gcp_project(params)
        cmd = [
            "gcloud", "dns", "record-sets", "list",
            "--zone", zone_id, "--format=json",
        ] + project_flag
    else:
        cmd = [
            "aws", "route53", "list-resource-record-sets",
            "--hosted-zone-id", zone_id, "--output", "json",
        ]

    out = _run_cli(cmd, timeout=60)
    if "error" in out:
        return out
    raw = out.get("result", [])
    if CLOUD_PROVIDER == "gcp":
        items = []
        for r in raw:
            items.append({
                "name": r.get("name"),
                "type": r.get("type"),
                "ttl": r.get("ttl"),
                "rrdatas": r.get("rrdatas", []),
            })
        return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}
    else:
        items = []
        for r in raw.get("ResourceRecordSets", []):
            items.append({
                "name": r.get("Name"),
                "type": r.get("Type"),
                "ttl": r.get("TTL"),
                "records": [rr.get("Value") for rr in r.get("ResourceRecords", [])],
            })
        return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}


def tool_get_costs(params: dict) -> dict:
    start = params.get("start_date") or params.get("start")
    end = params.get("end_date") or params.get("end")
    if not start or not end:
        return {"error": "start_date and end_date are required (YYYY-MM-DD)"}

    if CLOUD_PROVIDER == "gcp":
        project_flag = _gcp_project(params)
        cmd = [
            "gcloud", "billing", "accounts", "list", "--format=json",
        ]
        # Note: detailed cost query requires BigQuery export or billing API
        # Using a simplified approach
        cmd = [
            "gcloud", "alpha", "billing", "projects", "list",
            "--format=json",
        ] + project_flag
        out = _run_cli(cmd)
        if "error" in out:
            return {"content": [{"type": "text", "text": json.dumps({"note": "GCP cost details require Billing API / BigQuery export", "period": f"{start} to {end}", "error": out["error"]})}]}
        return {"content": [{"type": "text", "text": json.dumps(out.get("result", {}), indent=2)}]}
    else:
        cmd = [
            "aws", "ce", "get-cost-and-usage",
            "--time-period", f"Start={start},End={end}",
            "--granularity", "MONTHLY",
            "--metrics", "BlendedCost",
            "--output", "json",
        ]
        out = _run_cli(cmd)
        if "error" in out:
            return out
        raw = out.get("result", {})
        items = []
        for item in raw.get("ResultsByTime", []):
            items.append({
                "period": item.get("TimePeriod", {}).get("Start"),
                "cost": item.get("Total", {}).get("BlendedCost", {}).get("Amount"),
                "unit": item.get("Total", {}).get("BlendedCost", {}).get("Unit"),
            })
        return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}


def tool_list_security_groups(params: dict) -> dict:
    if CLOUD_PROVIDER == "gcp":
        project_flag = _gcp_project(params)
        cmd = ["gcloud", "compute", "firewall-rules", "list", "--format=json"] + project_flag
    else:
        region_flag = _aws_region(params)
        cmd = ["aws", "ec2", "describe-security-groups", "--output", "json"] + region_flag

    out = _run_cli(cmd)
    if "error" in out:
        return out
    raw = out.get("result", [])
    if CLOUD_PROVIDER == "gcp":
        items = []
        for r in raw:
            items.append({
                "name": r.get("name"),
                "network": r.get("network", "").rsplit("/", 1)[-1],
                "direction": r.get("direction"),
                "priority": r.get("priority"),
                "allowed": r.get("allowed", []),
                "denied": r.get("denied", []),
                "targetTags": r.get("targetTags", []),
            })
        return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}
    else:
        items = []
        for sg in raw.get("SecurityGroups", []):
            items.append({
                "groupId": sg.get("GroupId"),
                "groupName": sg.get("GroupName"),
                "description": sg.get("Description"),
                "vpcId": sg.get("VpcId"),
                "inboundRules": sg.get("IpPermissions", []),
                "outboundRules": sg.get("IpPermissionsEgress", []),
            })
        return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}


def tool_get_load_balancers(params: dict) -> dict:
    if CLOUD_PROVIDER == "gcp":
        project_flag = _gcp_project(params)
        cmd = ["gcloud", "compute", "load-balancers", "list", "--format=json"] + project_flag
        out = _run_cli(cmd)
        if "error" in out:
            # Try backend-services instead
            cmd = ["gcloud", "compute", "backend-services", "list", "--format=json"] + project_flag
            out = _run_cli(cmd)
        if "error" in out:
            return out
        raw = out.get("result", [])
        items = []
        for lb in raw if isinstance(raw, list) else [raw]:
            if isinstance(lb, dict):
                items.append({
                    "name": lb.get("name"),
                    "protocol": lb.get("protocol"),
                    "loadBalancingScheme": lb.get("loadBalancingScheme"),
                    "healthChecks": lb.get("healthChecks", []),
                    "backends": [b.get("group", "").rsplit("/", 1)[-1] for b in lb.get("backends", [])],
                })
        return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}
    else:
        cmd = ["aws", "elbv2", "describe-load-balancers", "--output", "json"]
        out = _run_cli(cmd)
        if "error" in out:
            return out
        raw = out.get("result", {})
        items = []
        for lb in raw.get("LoadBalancers", []):
            items.append({
                "name": lb.get("LoadBalancerName"),
                "arn": lb.get("LoadBalancerArn"),
                "dnsName": lb.get("DNSName"),
                "type": lb.get("Type"),
                "scheme": lb.get("Scheme"),
                "state": lb.get("State", {}).get("Code"),
                "vpcId": lb.get("VpcId"),
                "availabilityZones": [az.get("ZoneName") for az in lb.get("AvailabilityZones", [])],
            })
        return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}


def tool_list_functions(params: dict) -> dict:
    if CLOUD_PROVIDER == "gcp":
        project_flag = _gcp_project(params)
        region = params.get("region")
        region_flag = ["--regions", region] if region else []
        cmd = ["gcloud", "functions", "list", "--format=json"] + region_flag + project_flag
    else:
        region_flag = _aws_region(params)
        cmd = ["aws", "lambda", "list-functions", "--output", "json"] + region_flag

    out = _run_cli(cmd)
    if "error" in out:
        return out
    raw = out.get("result", [])
    if CLOUD_PROVIDER == "gcp":
        items = []
        for fn in raw:
            items.append({
                "name": fn.get("name"),
                "status": fn.get("status"),
                "runtime": fn.get("runtime"),
                "availableMemoryMb": fn.get("availableMemoryMb"),
                "trigger": fn.get("eventTrigger", {}).get("eventType") if fn.get("eventTrigger") else "https",
                "region": fn.get("region"),
                "entryPoint": fn.get("entryPoint"),
            })
        return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}
    else:
        items = []
        for fn in raw.get("Functions", []):
            items.append({
                "name": fn.get("FunctionName"),
                "runtime": fn.get("Runtime"),
                "handler": fn.get("Handler"),
                "memorySize": fn.get("MemorySize"),
                "timeout": fn.get("Timeout"),
                "lastModified": fn.get("LastModified"),
                "description": fn.get("Description", ""),
            })
        return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}


def tool_check_health(_params: dict) -> dict:
    info: dict = {"provider": CLOUD_PROVIDER}

    if CLOUD_PROVIDER == "gcp":
        # Check gcloud CLI
        ver_out = _run_cli(["gcloud", "version", "--format=json"])
        if "error" in ver_out:
            info["cliInstalled"] = False
            info["error"] = ver_out["error"]
            return {"content": [{"type": "text", "text": json.dumps(info, indent=2)}]}

        info["cliInstalled"] = True
        ver_raw = ver_out.get("result", {})
        if isinstance(ver_raw, dict):
            info["version"] = ver_raw.get("Google Cloud SDK", "unknown")

        # Check auth
        auth_out = _run_cli(["gcloud", "auth", "list", "--format=json"])
        if "error" not in auth_out:
            accounts = auth_out.get("result", [])
            if isinstance(accounts, list):
                info["account"] = accounts[0].get("account") if accounts else None
                info["active"] = any(a.get("status", "") == "ACTIVE" for a in accounts)

        # Check config
        cfg_out = _run_cli(["gcloud", "config", "get-value", "project"])
        if "error" not in cfg_out:
            proj = cfg_out.get("result", "")
            info["project"] = str(proj).strip() if proj else None
    else:
        # Check aws CLI
        ver_out = _run_cli(["aws", "--version"])
        if "error" in ver_out:
            info["cliInstalled"] = False
            info["error"] = ver_out["error"]
            return {"content": [{"type": "text", "text": json.dumps(info, indent=2)}]}

        info["cliInstalled"] = True
        # aws --version outputs to stderr
        info["version"] = ver_out.get("error", "").split("/")[1].split(" ")[0] if ver_out.get("error") else "unknown"

        # Check identity
        id_out = _run_cli(["aws", "sts", "get-caller-identity", "--output", "json"])
        if "error" not in id_out:
            ident = id_out.get("result", {})
            info["account"] = ident.get("Account")
            info["userId"] = ident.get("UserId")
            info["arn"] = ident.get("Arn")
            info["configured"] = True
        else:
            info["configured"] = False
            info["configError"] = id_out["error"]

    info["status"] = "ok" if info.get("cliInstalled") else "error"
    return {"content": [{"type": "text", "text": json.dumps(info, indent=2)}]}


# ---------------------------------------------------------------------------
# Tool definitions (schema)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "list_instances",
        "description": "List compute instances (EC2/GCE) with status, type, region/zone.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "description": "Region filter (AWS)"},
                "project": {"type": "string", "description": "Project ID (GCP)"},
            },
        },
    },
    {
        "name": "get_instance",
        "description": "Detailed instance info: CPU, memory, network, disks, tags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string", "description": "Instance ID (AWS) or name (GCP)"},
                "region": {"type": "string", "description": "Region (AWS)"},
                "zone": {"type": "string", "description": "Zone (GCP)"},
                "project": {"type": "string", "description": "Project ID (GCP)"},
            },
            "required": ["instance_id"],
        },
    },
    {
        "name": "list_buckets",
        "description": "List storage buckets (S3/GCS).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project ID (GCP)"},
            },
        },
    },
    {
        "name": "list_dns_records",
        "description": "List DNS records for a zone (Route53/Cloud DNS).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "zone_id": {"type": "string", "description": "Hosted zone ID (AWS) or zone name (GCP)"},
                "project": {"type": "string", "description": "Project ID (GCP)"},
            },
            "required": ["zone_id"],
        },
    },
    {
        "name": "get_costs",
        "description": "Cost summary for a period (Cost Explorer / Billing API).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                "project": {"type": "string", "description": "Project ID (GCP)"},
            },
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "list_security_groups",
        "description": "List security groups (AWS) / firewall rules (GCP).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "description": "Region (AWS)"},
                "project": {"type": "string", "description": "Project ID (GCP)"},
            },
        },
    },
    {
        "name": "get_load_balancers",
        "description": "List load balancers with targets, health, listeners.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "description": "Region (AWS)"},
                "project": {"type": "string", "description": "Project ID (GCP)"},
            },
        },
    },
    {
        "name": "list_functions",
        "description": "List serverless functions (Lambda/Cloud Functions) with runtime, memory, trigger.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "description": "Region (AWS)"},
                "project": {"type": "string", "description": "Project ID (GCP)"},
            },
        },
    },
    {
        "name": "check_health",
        "description": "Verify CLI installed, configured, identity/account info.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

TOOL_DISPATCH = {
    "list_instances": tool_list_instances,
    "get_instance": tool_get_instance,
    "list_buckets": tool_list_buckets,
    "list_dns_records": tool_list_dns_records,
    "get_costs": tool_get_costs,
    "list_security_groups": tool_list_security_groups,
    "get_load_balancers": tool_get_load_balancers,
    "list_functions": tool_list_functions,
    "check_health": tool_check_health,
}


# ---------------------------------------------------------------------------
# JSON-RPC dispatcher
# ---------------------------------------------------------------------------

def handle_request(msg: dict) -> dict | None:
    method = msg.get("method")
    request_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return make_response(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "notifications/initialized":
        return None  # no response for notifications

    if method == "tools/list":
        return make_response(request_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if tool_name not in TOOL_DISPATCH:
            return make_error(request_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = TOOL_DISPATCH[tool_name](arguments)
            return make_response(request_id, result)
        except Exception as exc:
            return make_error(request_id, -32603, f"Tool execution error: {exc}")

    if method == "ping":
        return make_response(request_id, {})

    return make_error(request_id, -32601, f"Method not found: {method}")


# ---------------------------------------------------------------------------
# Main async loop (stdio)
# ---------------------------------------------------------------------------

async def read_lines(loop: asyncio.AbstractEventLoop):
    """Async generator yielding lines from stdin."""
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    while True:
        line = await reader.readline()
        if not line:
            break
        yield line.decode("utf-8", errors="replace").strip()


async def main():
    loop = asyncio.get_event_loop()
    writer = asyncio.StreamWriter(
        *(await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout)),
        None, loop
    )

    async for line in read_lines(loop):
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            writer.write(json.dumps(make_error(None, -32700, "Parse error")).encode() + b"\n")
            await writer.drain()
            continue

        resp = handle_request(msg)
        if resp is not None:
            writer.write(json.dumps(resp).encode() + b"\n")
            await writer.drain()


if __name__ == "__main__":
    asyncio.run(main())
