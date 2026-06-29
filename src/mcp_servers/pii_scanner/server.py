#!/usr/bin/env python3
"""PII Scanner MCP Server — stdio transport, JSON-RPC.

Scans files and strings for PII patterns (email, phone, passport, SNILS,
INN, credit card, IP, address fragments, names) with configurable rules.

Tools:
  scan_file       — scan a file, return matches with line numbers
  scan_string     — scan a string/buffer
  scan_directory  — recursively scan all files in a directory
  get_rules       — list active detection rules
  add_rule        — add custom regex rule
  mask_string     — return masked copy of input string
  mask_file       — create masked copy of file
"""

import asyncio
import json
import re
import sys
import os
import hashlib
import copy
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# PII detection rules
# ---------------------------------------------------------------------------

DEFAULT_RULES = [
    {
        "id": "email",
        "name": "Email",
        "pattern": r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        "severity": "high",
        "replacement": "[EMAIL_REDACTED]",
    },
    {
        "id": "phone_ru",
        "name": "Russian phone",
        "pattern": r"(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",
        "severity": "high",
        "replacement": "[PHONE_REDACTED]",
    },
    {
        "id": "phone_international",
        "name": "International phone",
        "pattern": r"\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{1,4}[\s\-]?\d{1,4}[\s\-]?\d{1,9}",
        "severity": "medium",
        "replacement": "[PHONE_REDACTED]",
    },
    {
        "id": "passport_ru",
        "name": "Russian passport",
        "pattern": r"\b\d{2}\s?\d{2}\s?\d{6}\b",
        "severity": "critical",
        "replacement": "[PASSPORT_REDACTED]",
    },
    {
        "id": "snils",
        "name": "SNILS",
        "pattern": r"\b\d{3}[\s\-]?\d{3}[\s\-]?\d{3}\s?\d{2}\b",
        "severity": "critical",
        "replacement": "[SNILS_REDACTED]",
    },
    {
        "id": "inn",
        "name": "INN",
        "pattern": r"\b\d{10}(?:\d{2})?\b",
        "severity": "high",
        "replacement": "[INN_REDACTED]",
    },
    {
        "id": "credit_card",
        "name": "Credit card number",
        "pattern": r"\b(?:\d{4}[\s\-]?){3}\d{4}\b",
        "severity": "critical",
        "replacement": "[CARD_REDACTED]",
    },
    {
        "id": "ip_address",
        "name": "IPv4 address",
        "pattern": r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
        "severity": "low",
        "replacement": "[IP_REDACTED]",
    },
    {
        "id": "ipv6",
        "name": "IPv6 address",
        "pattern": r"(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}",
        "severity": "low",
        "replacement": "[IP_REDACTED]",
    },
    {
        "id": "ru_address",
        "name": "Russian address fragment",
        "pattern": r"(?:ул\.|улица|пр\.|проспект|пер\.|переулок|д\.|дом|кв\.|квартира)\s*[a-zA-Zа-яА-ЯёЁ0-9\s\-]+",
        "severity": "medium",
        "replacement": "[ADDRESS_REDACTED]",
    },
    {
        "id": "full_name_ru",
        "name": "Russian full name pattern",
        "pattern": r"\b[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:вич|вна|евич|евна|ович|овна|ич|на)?(?:\s+[А-ЯЁ][а-яё]+(?:вич|вна|евич|евна|ович|овна|ич|на)?)?\b",
        "severity": "medium",
        "replacement": "[NAME_REDACTED]",
    },
    {
        "id": "date_of_birth",
        "name": "Date of birth",
        "pattern": r"\b(?:дата\s*рождения|born|DOB)[:\s]*\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}",
        "severity": "high",
        "replacement": "[DOB_REDACTED]",
    },
    {
        "id": "jwt_token",
        "name": "JWT token",
        "pattern": r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}",
        "severity": "critical",
        "replacement": "[JWT_REDACTED]",
    },
    {
        "id": "api_key_generic",
        "name": "Generic API key",
        "pattern": r"(?:api[_\-]?key|secret|token|password|passwd|pwd)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{16,}['\"]?",
        "severity": "high",
        "replacement": "[API_KEY_REDACTED]",
    },
    {
        "id": "aws_key",
        "name": "AWS access key",
        "pattern": r"(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}",
        "severity": "critical",
        "replacement": "[AWS_KEY_REDACTED]",
    },
]

# ---------------------------------------------------------------------------
# Scanner engine
# ---------------------------------------------------------------------------

class PIIScanner:
    def __init__(self, rules_path: str | None = None):
        self.rules = copy.deepcopy(DEFAULT_RULES)
        self._compiled = {}
        self._compile_rules()
        if rules_path and os.path.isfile(rules_path):
            self._load_custom_rules(rules_path)

    def _compile_rules(self):
        self._compiled.clear()
        for rule in self.rules:
            try:
                self._compiled[rule["id"]] = re.compile(
                    rule["pattern"], re.IGNORECASE | re.MULTILINE
                )
            except re.error:
                pass

    def _load_custom_rules(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            custom = json.load(f)
        if isinstance(custom, list):
            for r in custom:
                if "id" in r and "pattern" in r:
                    self.rules.append(r)
            self._compile_rules()

    def scan_text(self, text: str, rule_ids: list[str] | None = None) -> list[dict]:
        matches = []
        rules = self.rules if rule_ids is None else [r for r in self.rules if r["id"] in rule_ids]
        for rule in rules:
            compiled = self._compiled.get(rule["id"])
            if not compiled:
                continue
            for m in compiled.finditer(text):
                matches.append({
                    "rule_id": rule["id"],
                    "rule_name": rule["name"],
                    "severity": rule.get("severity", "medium"),
                    "value": m.group(0),
                    "start": m.start(),
                    "end": m.end(),
                })
        return matches

    def scan_string(self, text: str, rule_ids: list[str] | None = None) -> dict:
        matches = self.scan_text(text, rule_ids)
        return {
            "pii_found": len(matches),
            "has_pii": len(matches) > 0,
            "matches": matches,
            "severity_max": max((m["severity"] for m in matches), default="none"),
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }

    def scan_file(self, file_path: str, rule_ids: list[str] | None = None) -> dict:
        path = Path(file_path)
        if not path.is_file():
            return {"error": f"File not found: {file_path}"}
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"error": f"Cannot read file: {e}"}

        raw_matches = self.scan_text(text, rule_ids)
        # Add line numbers
        lines = text.split("\n")
        line_offsets = []
        offset = 0
        for line in lines:
            line_offsets.append(offset)
            offset += len(line) + 1

        matches_with_lines = []
        for m in raw_matches:
            line_num = 1
            for i, lo in enumerate(line_offsets):
                if lo > m["start"]:
                    line_num = i
                    break
            else:
                line_num = len(lines)
            matches_with_lines.append({
                **m,
                "line": line_num,
            })

        file_hash = hashlib.sha256(text.encode()).hexdigest()
        return {
            "file": str(path),
            "file_hash": f"sha256:{file_hash}",
            "pii_found": len(matches_with_lines),
            "has_pii": len(matches_with_lines) > 0,
            "matches": matches_with_lines,
            "severity_max": max((m["severity"] for m in matches_with_lines), default="none"),
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }

    def scan_directory(self, dir_path: str, rule_ids: list[str] | None = None,
                       extensions: list[str] | None = None,
                       max_file_size_mb: float = 10.0) -> dict:
        root = Path(dir_path)
        if not root.is_dir():
            return {"error": f"Directory not found: {dir_path}"}

        default_exts = {".txt", ".md", ".json", ".yaml", ".yml", ".csv", ".tsv",
                        ".py", ".js", ".ts", ".sql", ".xml", ".html", ".env", ".cfg", ".ini", ".log"}
        allowed_ext = set(extensions) if extensions else default_exts
        max_bytes = int(max_file_size_mb * 1024 * 1024)

        results = []
        total_matches = 0
        scanned = 0
        skipped = 0
        errors = 0

        for fpath in root.rglob("*"):
            if not fpath.is_file():
                continue
            if fpath.suffix.lower() not in allowed_ext:
                continue
            if fpath.stat().st_size > max_bytes:
                skipped += 1
                continue
            try:
                res = self.scan_file(str(fpath), rule_ids)
                if "error" in res:
                    errors += 1
                    continue
                scanned += 1
                total_matches += res["pii_found"]
                if res["pii_found"] > 0:
                    results.append(res)
            except Exception:
                errors += 1

        return {
            "directory": str(root),
            "files_scanned": scanned,
            "files_skipped_size": skipped,
            "files_error": errors,
            "total_pii_found": total_matches,
            "has_pii": total_matches > 0,
            "files_with_pii": len(results),
            "results": results,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }

    def mask_string(self, text: str, rule_ids: list[str] | None = None) -> dict:
        matches = self.scan_text(text, rule_ids)
        masked = text
        # Replace from end to preserve positions
        for m in sorted(matches, key=lambda x: x["start"], reverse=True):
            rule = next((r for r in self.rules if r["id"] == m["rule_id"]), None)
            replacement = rule["replacement"] if rule else "[REDACTED]"
            masked = masked[:m["start"]] + replacement + masked[m["end"]:]
        return {
            "original_length": len(text),
            "masked_length": len(masked),
            "replacements_made": len(matches),
            "masked_text": masked,
        }

    def mask_file(self, file_path: str, output_path: str | None = None,
                  rule_ids: list[str] | None = None) -> dict:
        path = Path(file_path)
        if not path.is_file():
            return {"error": f"File not found: {file_path}"}
        text = path.read_text(encoding="utf-8", errors="replace")
        result = self.mask_string(text, rule_ids)

        out = Path(output_path) if output_path else path.with_suffix(path.suffix + ".masked")
        out.write_text(result["masked_text"], encoding="utf-8")
        result["input_file"] = str(path)
        result["output_file"] = str(out)
        return result

    def get_rules(self) -> list[dict]:
        return [{"id": r["id"], "name": r["name"], "severity": r.get("severity", "medium")}
                for r in self.rules]

    def add_rule(self, rule_id: str, name: str, pattern: str,
                 severity: str = "medium", replacement: str = "[REDACTED]") -> dict:
        # Validate regex
        try:
            re.compile(pattern)
        except re.error as e:
            return {"error": f"Invalid regex: {e}"}
        # Check duplicate
        if any(r["id"] == rule_id for r in self.rules):
            return {"error": f"Rule '{rule_id}' already exists"}
        rule = {
            "id": rule_id,
            "name": name,
            "pattern": pattern,
            "severity": severity,
            "replacement": replacement,
        }
        self.rules.append(rule)
        self._compile_rules()
        return {"status": "added", "rule": {"id": rule_id, "name": name, "severity": severity}}


# ---------------------------------------------------------------------------
# MCP JSON-RPC protocol (stdio)
# ---------------------------------------------------------------------------

scanner: PIIScanner | None = None


def make_response(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_request(msg: dict) -> dict | None:
    method = msg.get("method", "")
    params = msg.get("params", {})
    req_id = msg.get("id")

    # --- lifecycle ---
    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "pii_scanner", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None  # notification, no response

    # --- tools ---
    if method == "tools/list":
        tools = [
            {
                "name": "scan_file",
                "description": "Scan a file for PII patterns. Returns matches with line numbers, severity, and file hash.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to file to scan"},
                        "rule_ids": {"type": "array", "items": {"type": "string"},
                                     "description": "Optional list of rule IDs to apply. All rules if omitted."},
                    },
                    "required": ["file_path"],
                },
            },
            {
                "name": "scan_string",
                "description": "Scan a string for PII patterns. Returns matches with positions and severity.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to scan"},
                        "rule_ids": {"type": "array", "items": {"type": "string"},
                                     "description": "Optional list of rule IDs to apply."},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "scan_directory",
                "description": "Recursively scan all files in a directory for PII. Skips binary/large files.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dir_path": {"type": "string", "description": "Directory to scan"},
                        "rule_ids": {"type": "array", "items": {"type": "string"},
                                     "description": "Optional rule IDs filter."},
                        "extensions": {"type": "array", "items": {"type": "string"},
                                       "description": "File extensions to scan (e.g. ['.py', '.json'])"},
                        "max_file_size_mb": {"type": "number", "description": "Max file size in MB (default 10)"},
                    },
                    "required": ["dir_path"],
                },
            },
            {
                "name": "mask_string",
                "description": "Return a masked copy of input text with PII replaced by placeholders.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to mask"},
                        "rule_ids": {"type": "array", "items": {"type": "string"},
                                     "description": "Optional rule IDs to apply."},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "mask_file",
                "description": "Create a masked copy of a file with PII replaced. Writes to <filename>.masked by default.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Input file path"},
                        "output_path": {"type": "string", "description": "Output file path (optional)"},
                        "rule_ids": {"type": "array", "items": {"type": "string"},
                                     "description": "Optional rule IDs to apply."},
                    },
                    "required": ["file_path"],
                },
            },
            {
                "name": "get_rules",
                "description": "List all active PII detection rules with IDs, names, and severity levels.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "add_rule",
                "description": "Add a custom PII detection rule (regex pattern).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "rule_id": {"type": "string", "description": "Unique rule identifier"},
                        "name": {"type": "string", "description": "Human-readable rule name"},
                        "pattern": {"type": "string", "description": "Regex pattern"},
                        "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"],
                                     "description": "Severity level (default: medium)"},
                        "replacement": {"type": "string", "description": "Replacement text (default: [REDACTED])"},
                    },
                    "required": ["rule_id", "name", "pattern"],
                },
            },
        ]
        return make_response(req_id, {"tools": tools})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if scanner is None:
            return make_error(req_id, -32603, "Scanner not initialized")

        try:
            if tool_name == "scan_file":
                res = scanner.scan_file(
                    arguments["file_path"],
                    arguments.get("rule_ids"),
                )
                return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}]})

            if tool_name == "scan_string":
                res = scanner.scan_string(
                    arguments["text"],
                    arguments.get("rule_ids"),
                )
                return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}]})

            if tool_name == "scan_directory":
                res = scanner.scan_directory(
                    arguments["dir_path"],
                    arguments.get("rule_ids"),
                    arguments.get("extensions"),
                    arguments.get("max_file_size_mb", 10.0),
                )
                return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}]})

            if tool_name == "mask_string":
                res = scanner.mask_string(
                    arguments["text"],
                    arguments.get("rule_ids"),
                )
                return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}]})

            if tool_name == "mask_file":
                res = scanner.mask_file(
                    arguments["file_path"],
                    arguments.get("output_path"),
                    arguments.get("rule_ids"),
                )
                return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}]})

            if tool_name == "get_rules":
                res = scanner.get_rules()
                return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}]})

            if tool_name == "add_rule":
                res = scanner.add_rule(
                    arguments["rule_id"],
                    arguments["name"],
                    arguments["pattern"],
                    arguments.get("severity", "medium"),
                    arguments.get("replacement", "[REDACTED]"),
                )
                return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}]})

            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")

        except Exception as e:
            return make_error(req_id, -32603, f"Internal error: {e}")

    if method == "ping":
        return make_response(req_id, {})

    return make_error(req_id, -32601, f"Unknown method: {method}")


async def main():
    global scanner
    scanner = PIIScanner()

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
