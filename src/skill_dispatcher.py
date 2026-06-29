"""
Skill Dispatcher — loads skill .md files, provides search, prompt extraction,
tool mapping, and sub-agent activation planning for the MCP Context Pipeline.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


MCP_ALIAS_MAP: dict[str, str] = {
    "vault": "secrets_manager",
    "prometheus": "monitoring",
    "gitlab_ci": "ci_platform",
    "clickhouse_schema": "clickhouse_read",
}

EXTERNAL_MCP_TOOLS: set[str] = {
    "jira_read",
    "k8s",
    "playwright",
}

EXTERNAL_MCP_LABELS: dict[str, str] = {
    "jira_read": "Shiva MCP",
    "k8s": "npm package",
    "playwright": "npm package",
}


def _parse_frontmatter(text: str) -> Tuple[dict, str]:
    """Parse YAML-like frontmatter between --- delimiters.

    Returns (metadata_dict, body_text).
    """
    pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
    m = pattern.match(text)
    if not m:
        return {}, text

    raw = m.group(1)
    body = text[m.end():]
    meta: dict[str, Any] = {}

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        colon = line.find(":")
        if colon == -1:
            continue
        key = line[:colon].strip()
        val = line[colon + 1:].strip()

        # Parse JSON array [...]
        if val.startswith("["):
            try:
                meta[key] = json.loads(val)
            except json.JSONDecodeError:
                # Fallback: strip brackets, split by comma
                inner = val.strip("[]")
                meta[key] = [
                    item.strip().strip('"').strip("'")
                    for item in inner.split(",")
                    if item.strip()
                ]
        elif val.startswith('"') and val.endswith('"'):
            meta[key] = val[1:-1]
        elif val.startswith("'") and val.endswith("'"):
            meta[key] = val[1:-1]
        elif val.lower() in ("true", "false"):
            meta[key] = val.lower() == "true"
        else:
            meta[key] = val

    return meta, body


def _resolve_tool(tool_name: str) -> dict:
    """Resolve a single tool entry to {tool, type, mcp_server?, note?}."""
    clean = tool_name.strip().strip('"').strip("'")

    if clean.startswith("mcp:"):
        mcp_name = clean[4:]
        resolved = MCP_ALIAS_MAP.get(mcp_name, mcp_name)

        if mcp_name in EXTERNAL_MCP_TOOLS:
            return {
                "tool": mcp_name,
                "type": "external_mcp",
                "note": EXTERNAL_MCP_LABELS.get(mcp_name, "external"),
            }
        return {"tool": resolved, "type": "mcp_server", "mcp_server": resolved}

    return {"tool": clean, "type": "bash_tool"}


def _score_match(query_words: list[str], text: str) -> float:
    """Simple word-overlap scoring."""
    if not text:
        return 0.0
    text_lower = text.lower()
    hits = sum(1 for w in query_words if w in text_lower)
    return hits / max(len(query_words), 1)


@dataclass
class SkillEntry:
    filename: str
    name: str
    role: str
    trigger: str
    priority: str
    allowed_tools: List[str] = field(default_factory=list)
    context_rules: dict = field(default_factory=dict)
    memory_integration: bool = False
    worktree_isolation: bool = False
    body: str = ""
    raw_meta: dict = field(default_factory=dict)

    @property
    def stem(self) -> str:
        return Path(self.filename).stem


class SkillDispatcher:
    def __init__(
        self,
        skills_dir: str = "Навыки",
        mcp_servers_dir: str = "src/mcp_servers",
    ):
        self.skills_dir = Path(skills_dir)
        self.mcp_servers_dir = Path(mcp_servers_dir)
        self._skills: dict[str, SkillEntry] = {}
        self._load_skills()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_skills(self) -> None:
        if not self.skills_dir.is_dir():
            return
        for fp in sorted(self.skills_dir.glob("*.md")):
            text = fp.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)

            entry = SkillEntry(
                filename=fp.name,
                name=meta.get("name", fp.stem),
                role=meta.get("role", ""),
                trigger=meta.get("trigger", ""),
                priority=meta.get("priority", "normal"),
                allowed_tools=meta.get("allowed_tools", []),
                context_rules=meta.get("context_rules", {}),
                memory_integration=meta.get("memory_integration", False),
                worktree_isolation=meta.get("worktree_isolation", False),
                body=body,
                raw_meta=meta,
            )
            self._skills[entry.stem] = entry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_skills(self) -> List[Dict]:
        """Return all skills with metadata."""
        return [
            {
                "name": s.name,
                "stem": s.stem,
                "role": s.role,
                "trigger": s.trigger,
                "priority": s.priority,
                "allowed_tools": s.allowed_tools,
                "filename": s.filename,
            }
            for s in self._skills.values()
        ]

    def find_skill(
        self,
        query: str,
        role: str | None = None,
        top_k: int = 3,
    ) -> List[Dict]:
        """Find skills matching query by keyword/overlap scoring."""
        query_lower = query.lower()
        query_words = query_lower.split()
        results: list[tuple[float, SkillEntry]] = []

        for s in self._skills.values():
            if role and s.role.lower() != role.lower():
                continue

            searchable = f"{s.name} {s.trigger} {s.role} {s.stem} {' '.join(s.allowed_tools)}"
            stem_name = f"{s.stem} {s.name}"
            score = _score_match(query_words, searchable)

            # Exact substring bonus
            if query_lower in searchable.lower():
                score += 0.3

            # Bonus for stem/name match (higher signal)
            stem_hits = sum(1 for w in query_words if w in stem_name.lower())
            score += stem_hits * 0.15

            if score > 0:
                results.append((score, s))

        results.sort(key=lambda x: (-x[0], x[1].name))
        return [
            {
                "stem": s.stem,
                "name": s.name,
                "role": s.role,
                "trigger": s.trigger,
                "priority": s.priority,
                "score": round(score, 3),
            }
            for score, s in results[:top_k]
        ]

    def get_skill_prompt(self, skill_name: str) -> str:
        """Return full skill body as system prompt for sub-agent."""
        entry = self._skills.get(skill_name)
        if not entry:
            # Try partial match
            for stem, s in self._skills.items():
                if skill_name.lower() in stem.lower() or skill_name.lower() in s.name.lower():
                    entry = s
                    break
        if not entry:
            return ""
        return entry.body.strip()

    def get_required_tools(self, skill_name: str) -> Dict:
        """Parse allowed_tools, map MCP aliases.

        Returns {"bash_tools": [...], "mcp_servers": [...], "external": [...]}.
        """
        entry = self._skills.get(skill_name)
        if not entry:
            return {"bash_tools": [], "mcp_servers": [], "external": []}

        bash_tools: list[str] = []
        mcp_servers: list[str] = []
        external: list[dict] = []

        for raw_tool in entry.allowed_tools:
            resolved = _resolve_tool(raw_tool)
            rtype = resolved["type"]
            if rtype == "bash_tool":
                bash_tools.append(resolved["tool"])
            elif rtype == "mcp_server":
                mcp_servers.append(resolved["mcp_server"])
            elif rtype == "external_mcp":
                external.append(
                    {"tool": resolved["tool"], "note": resolved.get("note", "")}
                )

        return {
            "bash_tools": bash_tools,
            "mcp_servers": mcp_servers,
            "external": external,
        }

    def activate_skill(
        self,
        skill_name: str,
        task: str,
        llm_provider: str = "anthropic",
    ) -> Dict:
        """Prepare sub-agent execution plan (does not execute).

        Returns:
            {
                "system_prompt": str,
                "mcp_servers": [...],
                "task": str,
                "context": str,
                "skill": str,
                "provider": str,
            }
        """
        prompt = self.get_skill_prompt(skill_name)
        tools = self.get_required_tools(skill_name)
        entry = self._skills.get(skill_name)

        context_parts: list[str] = []
        if entry:
            context_parts.append(f"Skill: {entry.name}")
            context_parts.append(f"Role: {entry.role}")
            context_parts.append(f"Priority: {entry.priority}")
            if entry.context_rules:
                inc = entry.context_rules.get("include", [])
                exc = entry.context_rules.get("exclude", [])
                if inc:
                    context_parts.append(f"Include paths: {', '.join(inc)}")
                if exc:
                    context_parts.append(f"Exclude paths: {', '.join(exc)}")

        return {
            "system_prompt": prompt,
            "mcp_servers": tools["mcp_servers"],
            "bash_tools": tools["bash_tools"],
            "external_tools": tools["external"],
            "task": task,
            "context": "\n".join(context_parts),
            "skill": skill_name,
            "provider": llm_provider,
        }
