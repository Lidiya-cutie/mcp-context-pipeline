#!/usr/bin/env python3
"""MCP server for NVIDIA GPU monitoring via nvidia-smi."""

import asyncio
import json
import sys
import subprocess
import re
from typing import Any

SERVER_NAME = "gpu_monitor"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"

NVIDIA_SMI = "nvidia-smi"


def make_response(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def run_nvidia_smi(*args: str, fallback_simulated: bool = True) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [NVIDIA_SMI, *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, result.stdout
        if fallback_simulated:
            return False, ""
        return False, result.stderr
    except FileNotFoundError:
        if fallback_simulated:
            return False, ""
        return False, "nvidia-smi not found"
    except subprocess.TimeoutExpired:
        return False, "nvidia-smi timed out"
    except Exception as e:
        return False, str(e)


def parse_csv_lines(output: str) -> list[dict]:
    lines = output.strip().splitlines()
    if len(lines) < 2:
        return []
    headers = [h.strip() for h in lines[0].split(",")]
    rows = []
    for line in lines[1:]:
        vals = [v.strip() for v in line.split(",")]
        row = {}
        for i, h in enumerate(headers):
            row[h] = vals[i] if i < len(vals) else ""
        rows.append(row)
    return rows


def simulated_gpu(count: int = 1) -> list[dict]:
    gpus = []
    for i in range(count):
        gpus.append({
            "index": i,
            "name": "SIMULATED GPU",
            "utilization_gpu": 0,
            "utilization_memory": 0,
            "memory_used_mb": 0,
            "memory_free_mb": 8192,
            "memory_total_mb": 8192,
            "temperature_c": 35,
            "power_draw_w": 0,
            "power_cap_w": 250,
            "fan_speed_pct": 30,
        })
    return gpus


def get_gpu_query(fields: str, format_args: str = "--format=csv,noheader,nounits") -> tuple[bool, str]:
    return run_nvidia_smi(f"--query-gpu={fields}", format_args)


def get_process_query(fields: str, format_args: str = "--format=csv,noheader,nounits") -> tuple[bool, str]:
    return run_nvidia_smi(f"--query-compute-apps={fields}", format_args)


# --- Tool implementations ---

def tool_gpu_status(_args: dict) -> dict:
    ok, driver_out = run_nvidia_smi("--query-gpu=driver_version", "--format=csv,noheader", fallback_simulated=False)
    driver_version = driver_out.strip().splitlines()[0] if ok and driver_out.strip() else "N/A"

    ok2, cuda_out = run_nvidia_smi("--query-gpu=cuda_version", "--format=csv,noheader", fallback_simulated=False)
    cuda_version = cuda_out.strip().splitlines()[0] if ok2 and cuda_out.strip() else "N/A"

    ok3, count_out = run_nvidia_smi("--query-gpu=count", "--format=csv,noheader", fallback_simulated=False)
    gpu_count = 0
    if ok3 and count_out.strip():
        try:
            gpu_count = int(count_out.strip().splitlines()[0])
        except ValueError:
            gpu_count = 0

    available = ok and ok3

    return {
        "nvidia_smi_available": available,
        "driver_version": driver_version if available else "N/A",
        "cuda_version": cuda_version if available else "N/A",
        "gpu_count": gpu_count if available else 0,
        "simulated": not available,
        "warning": None if available else "nvidia-smi not available, data is simulated",
    }


def tool_gpu_utilization(_args: dict) -> dict:
    fields = "index,name,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw,fan.speed"
    ok, output = get_gpu_query(fields)
    if not ok:
        return {
            "gpus": simulated_gpu(),
            "simulated": True,
            "warning": "nvidia-smi not available, data is simulated",
        }

    gpus = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 9:
            continue
        try:
            gpus.append({
                "index": int(parts[0]),
                "name": parts[1],
                "utilization_gpu_pct": int(parts[2]) if parts[2] != "[N/A]" else None,
                "utilization_memory_pct": int(parts[3]) if parts[3] != "[N/A]" else None,
                "memory_used_mb": int(parts[4]) if parts[4] != "[N/A]" else None,
                "memory_total_mb": int(parts[5]) if parts[5] != "[N/A]" else None,
                "temperature_c": int(parts[6]) if parts[6] != "[N/A]" else None,
                "power_draw_w": float(parts[7]) if parts[7] not in ("[N/A]", "") else None,
                "fan_speed_pct": int(parts[8]) if parts[8] != "[N/A]" else None,
            })
        except (ValueError, IndexError):
            continue

    return {"gpus": gpus, "simulated": False}


def tool_gpu_processes(_args: dict) -> dict:
    fields = "gpu_uuid,gpu_bus_id,pid,process_name,used_memory"
    ok, output = get_process_query(fields, "--format=csv,noheader")
    if not ok:
        return {
            "processes": [],
            "simulated": True,
            "warning": "nvidia-smi not available",
        }

    processes = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            processes.append({
                "gpu_bus_id": parts[1],
                "pid": int(parts[2]) if parts[2] not in ("[N/A]", "") else None,
                "process_name": parts[3],
                "used_memory_mb": int(parts[4]) if parts[4] not in ("[N/A]", "") else None,
            })
        except (ValueError, IndexError):
            continue

    return {"processes": processes, "simulated": False}


def tool_gpu_memory(_args: dict) -> dict:
    fields = "index,name,memory.used,memory.free,memory.total,utilization.memory"
    ok, output = get_gpu_query(fields)
    if not ok:
        mems = []
        for g in simulated_gpu():
            mems.append({
                "index": g["index"],
                "name": g["name"],
                "used_mb": g["memory_used_mb"],
                "free_mb": g["memory_free_mb"],
                "total_mb": g["memory_total_mb"],
                "utilization_pct": 0,
            })
        return {"gpus": mems, "simulated": True, "warning": "nvidia-smi not available"}

    gpus = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            gpus.append({
                "index": int(parts[0]),
                "name": parts[1],
                "used_mb": int(parts[2]) if parts[2] != "[N/A]" else None,
                "free_mb": int(parts[3]) if parts[3] != "[N/A]" else None,
                "total_mb": int(parts[4]) if parts[4] != "[N/A]" else None,
                "utilization_pct": int(parts[5]) if parts[5] != "[N/A]" else None,
            })
        except (ValueError, IndexError):
            continue

    return {"gpus": gpus, "simulated": False}


def tool_gpu_top(args: dict) -> dict:
    top_n = args.get("top_n", 10)
    fields = "pid,process_name,used_memory,gpu_uuid"
    ok, output = get_process_query(fields, "--format=csv,noheader")
    if not ok:
        return {"processes": [], "simulated": True, "warning": "nvidia-smi not available"}

    procs = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            mem = int(parts[2]) if parts[2] not in ("[N/A]", "") else 0
            procs.append({
                "pid": int(parts[0]) if parts[0] not in ("[N/A]", "") else None,
                "process_name": parts[1],
                "used_memory_mb": mem,
            })
        except (ValueError, IndexError):
            continue

    procs.sort(key=lambda p: p.get("used_memory_mb", 0) or 0, reverse=True)
    return {"processes": procs[:top_n], "simulated": False}


def tool_gpu_clocks(_args: dict) -> dict:
    fields = "index,name,clocks.sm,clocks.mem,clocks.gr,clocks.max.sm,clocks.max.mem,clocks.max.gr,power.limit"
    ok, output = get_gpu_query(fields)
    if not ok:
        return {"gpus": [], "simulated": True, "warning": "nvidia-smi not available"}

    gpus = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 9:
            continue
        try:
            def safe_int(v):
                return int(v) if v not in ("[N/A]", "") else None
            gpus.append({
                "index": int(parts[0]),
                "name": parts[1],
                "clock_sm_mhz": safe_int(parts[2]),
                "clock_mem_mhz": safe_int(parts[3]),
                "clock_graphics_mhz": safe_int(parts[4]),
                "max_clock_sm_mhz": safe_int(parts[5]),
                "max_clock_mem_mhz": safe_int(parts[6]),
                "max_clock_graphics_mhz": safe_int(parts[7]),
                "power_cap_w": safe_int(parts[8]),
            })
        except (ValueError, IndexError):
            continue

    return {"gpus": gpus, "simulated": False}


def tool_gpu_pcie(_args: dict) -> dict:
    fields = "index,name,pcie.link.gen.current,pcie.link.width.current,pcie.rx_throughput,pcie.tx_throughput"
    ok, output = get_gpu_query(fields)
    if not ok:
        return {"gpus": [], "simulated": True, "warning": "nvidia-smi not available"}

    gpus = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            def safe_int(v):
                return int(v) if v not in ("[N/A]", "") else None
            gpus.append({
                "index": int(parts[0]),
                "name": parts[1],
                "pcie_generation": safe_int(parts[2]),
                "pcie_width": safe_int(parts[3]),
                "rx_throughput_kbps": safe_int(parts[4]),
                "tx_throughput_kbps": safe_int(parts[5]),
            })
        except (ValueError, IndexError):
            continue

    return {"gpus": gpus, "simulated": False}


def tool_gpu_set_power_limit(args: dict) -> dict:
    gpu_id = args.get("gpu_id", 0)
    power_limit = args.get("power_limit_w")
    if power_limit is None:
        return {"success": False, "error": "power_limit_w is required"}

    ok, output = run_nvidia_smi(f"-i {gpu_id}", f"-pl {power_limit}", fallback_simulated=False)
    if not ok:
        return {
            "success": False,
            "error": output if output else "nvidia-smi not available or permission denied",
            "hint": "Setting power limit requires root privileges or GPU persistence mode",
        }

    return {"success": True, "gpu_id": gpu_id, "power_limit_w": power_limit, "output": output.strip()}


def tool_check_health(args: dict) -> dict:
    temp_threshold = args.get("temp_threshold_c", 85)
    mem_threshold_pct = args.get("memory_threshold_pct", 95)

    ok, output = run_nvidia_smi("--query-gpu=index,temperature.gpu,memory.used,memory.total",
                                 "--format=csv,noheader,nounits", fallback_simulated=False)

    if not ok:
        return {
            "healthy": False,
            "nvidia_smi_available": False,
            "warning": "nvidia-smi not available",
            "issues": ["nvidia-smi is not available on this system"],
        }

    issues = []
    gpu_status = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            idx = int(parts[0])
            temp = int(parts[1]) if parts[1] != "[N/A]" else None
            mem_used = int(parts[2]) if parts[2] != "[N/A]" else None
            mem_total = int(parts[3]) if parts[3] != "[N/A]" else None

            gpu_issues = []
            if temp is not None and temp >= temp_threshold:
                gpu_issues.append(f"GPU {idx}: temperature {temp}C >= threshold {temp_threshold}C")
            mem_pct = None
            if mem_used is not None and mem_total is not None and mem_total > 0:
                mem_pct = round(mem_used / mem_total * 100, 1)
                if mem_pct >= mem_threshold_pct:
                    gpu_issues.append(f"GPU {idx}: memory usage {mem_pct}% >= threshold {mem_threshold_pct}%")

            gpu_status.append({
                "index": idx,
                "temperature_c": temp,
                "memory_used_mb": mem_used,
                "memory_total_mb": mem_total,
                "memory_utilization_pct": mem_pct,
                "issues": gpu_issues,
            })
            issues.extend(gpu_issues)
        except (ValueError, IndexError):
            continue

    return {
        "healthy": len(issues) == 0,
        "nvidia_smi_available": True,
        "issues": issues,
        "gpus": gpu_status,
    }


TOOLS = {
    "gpu_status": {
        "description": "Overall GPU status: driver version, CUDA version, GPU count, nvidia-smi availability",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "handler": tool_gpu_status,
    },
    "gpu_utilization": {
        "description": "Per-GPU utilization: GPU/memory utilization %, memory used/total, temperature, power draw, fan speed",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "handler": tool_gpu_utilization,
    },
    "gpu_processes": {
        "description": "Running compute processes on each GPU (PID, name, used memory)",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "handler": tool_gpu_processes,
    },
    "gpu_memory": {
        "description": "Detailed memory info per GPU: used, free, total, utilization %",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "handler": tool_gpu_memory,
    },
    "gpu_top": {
        "description": "Top N processes by GPU memory usage",
        "inputSchema": {
            "type": "object",
            "properties": {"top_n": {"type": "integer", "description": "Number of top processes to return", "default": 10}},
            "required": [],
        },
        "handler": tool_gpu_top,
    },
    "gpu_clocks": {
        "description": "Current clock speeds (SM, memory, graphics), max clocks, power cap",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "handler": tool_gpu_clocks,
    },
    "gpu_pcie": {
        "description": "PCIe link info: generation, width, RX/TX throughput",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "handler": tool_gpu_pcie,
    },
    "gpu_set_power_limit": {
        "description": "Set power cap for a GPU (requires nvidia-smi -pl, needs root privileges)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "gpu_id": {"type": "integer", "description": "GPU index", "default": 0},
                "power_limit_w": {"type": "integer", "description": "Power limit in watts"},
            },
            "required": ["power_limit_w"],
        },
        "handler": tool_gpu_set_power_limit,
    },
    "check_health": {
        "description": "Check if nvidia-smi works, GPU temperatures within thresholds, memory not full",
        "inputSchema": {
            "type": "object",
            "properties": {
                "temp_threshold_c": {"type": "integer", "description": "Temperature alarm threshold (C)", "default": 85},
                "memory_threshold_pct": {"type": "integer", "description": "Memory usage alarm threshold (%)", "default": 95},
            },
            "required": [],
        },
        "handler": tool_check_health,
    },
}


async def handle_request(msg: dict) -> dict | None:
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        tool_list = []
        for name, info in TOOLS.items():
            tool_list.append({
                "name": name,
                "description": info["description"],
                "inputSchema": info["inputSchema"],
            })
        return make_response(req_id, {"tools": tool_list})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if tool_name not in TOOLS:
            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = TOOLS[tool_name]["handler"](arguments)
            return make_response(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
            })
        except Exception as e:
            return make_error(req_id, -32603, f"Tool execution error: {e}")

    if method == "ping":
        return make_response(req_id, {})

    return make_error(req_id, -32601, f"Method not found: {method}")


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

        response = await handle_request(msg)
        if response is not None:
            payload = json.dumps(response) + "\n"
            writer.write(payload.encode())
            await writer.drain()


if __name__ == "__main__":
    asyncio.run(main())
