"""Structural smoke for MCP server packages under src/mcp_servers/.

Does not call live backends. Validates that each server package ships a
parseable manifest and a compilable server.py — enough to catch empty
scaffolds and broken packaging before integration tests.
"""

from __future__ import annotations

import json
import py_compile
import re
from pathlib import Path

import pytest

SERVERS_ROOT = Path(__file__).resolve().parents[1] / "src" / "mcp_servers"
REQUIRED_MANIFEST_KEYS = ("description", "version", "transport", "tools")
_DISPATCH_BLOCK_RE = re.compile(r"TOOL_DISPATCH\s*=\s*\{(.*?)\n\}", re.S)
_DISPATCH_KEY_RE = re.compile(r'"([a-zA-Z_][a-zA-Z0-9_]*)"\s*:')


def _server_dirs() -> list[Path]:
    return sorted(p for p in SERVERS_ROOT.iterdir() if p.is_dir() and (p / "server.py").exists())


def _dispatch_tool_names(server_path: Path) -> set[str]:
    text = server_path.read_text(encoding="utf-8")
    match = _DISPATCH_BLOCK_RE.search(text)
    if not match:
        return set()
    return set(_DISPATCH_KEY_RE.findall(match.group(1)))


@pytest.fixture(scope="module")
def server_dirs() -> list[Path]:
    dirs = _server_dirs()
    assert dirs, f"no MCP servers found under {SERVERS_ROOT}"
    return dirs


def test_mcp_server_count_matches_packages(server_dirs: list[Path]) -> None:
    assert len(server_dirs) >= 20


@pytest.mark.parametrize("server_dir", _server_dirs(), ids=lambda p: p.name)
def test_manifest_schema_and_server_compiles(server_dir: Path) -> None:
    manifest_path = server_dir / "manifest.json"
    server_path = server_dir / "server.py"

    assert manifest_path.is_file(), f"missing manifest: {manifest_path}"
    assert server_path.is_file(), f"missing server: {server_path}"

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in REQUIRED_MANIFEST_KEYS:
        assert key in data, f"{server_dir.name}: manifest missing '{key}'"

    assert data["transport"] in {"stdio", "sse", "http"}, data["transport"]
    tools = data["tools"]
    assert isinstance(tools, list) and tools, f"{server_dir.name}: empty tools"

    py_compile.compile(str(server_path), doraise=True)

    declared = {t if isinstance(t, str) else t.get("name") for t in tools}
    declared.discard(None)
    implemented = _dispatch_tool_names(server_path)
    if implemented:
        missing = declared - implemented
        assert not missing, (
            f"{server_dir.name}: manifest tools missing in TOOL_DISPATCH: {sorted(missing)}"
        )
