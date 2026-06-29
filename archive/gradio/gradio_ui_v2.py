"""
MCP Context Pipeline — Gradio UI v2.0
Переработанный интерфейс: поиск знаний, документация, PII, эксперты, MCP-серверы, система
"""

import gradio as gr
import asyncio
import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

sessions: Dict[str, Dict] = {}
logs: List[Dict] = []
current_summary_threshold = 100000
_skill_list_cache: Optional[List[Dict]] = None
_mcp_servers_cache: Optional[List[str]] = None
_mcp_health_cache: Dict[str, bool] = {}
_execution_history: List[Dict] = []

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_dispatcher_instance = None
_executor_instance = None


def _get_dispatcher():
    global _dispatcher_instance
    if _dispatcher_instance is None:
        from skill_dispatcher import SkillDispatcher
        _dispatcher_instance = SkillDispatcher(
            skills_dir=os.path.join(PROJECT_DIR, "Навыки"),
            mcp_servers_dir=os.path.join(PROJECT_DIR, "src", "mcp_servers"),
        )
    return _dispatcher_instance


def _get_executor():
    global _executor_instance
    if _executor_instance is None:
        from agent_executor import AgentExecutor
        _executor_instance = AgentExecutor(project_dir=PROJECT_DIR)
    return _executor_instance

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

APP_CSS = """
:root { --bg-main:#0f1117;--bg-panel:#1a1d2e;--bg-elevated:#1e2235;--text-main:#e2e8f0;--text-muted:#9aa7c1;--accent:#6366f1;--accent-light:#818cf8;--border:#2d3148;--border-hover:#4b5563; }
.gradio-container { background:var(--bg-main)!important;color:var(--text-main)!important;font-family:'Inter',system-ui,sans-serif!important; }
.app-hero { border:1px solid var(--border);border-radius:16px;padding:18px 22px;margin-bottom:12px;background:linear-gradient(120deg,#1a1d2e 0%,#0f1117 55%,#1a1d2e 100%);box-shadow:0 0 0 1px rgba(99,102,241,.06),0 8px 24px rgba(0,0,0,.3); }
.hero-title { font-size:26px;font-weight:800;margin:0 0 4px;color:var(--text-main); }
.hero-subtitle { color:var(--text-muted);margin:0;font-size:14px; }
.badge-row { margin-top:10px;display:flex;gap:8px;flex-wrap:wrap; }
.badge { padding:4px 10px;border-radius:999px;font-size:12px;font-weight:700;border:1px solid transparent; }
.badge-accent { background:rgba(99,102,241,.18);color:#a5b4fc;border-color:rgba(99,102,241,.36); }
.badge-orange { background:rgba(255,122,24,.18);color:#ffd5b0;border-color:rgba(255,122,24,.38); }
.badge-cyan { background:rgba(31,217,255,.14);color:#b9f4ff;border-color:rgba(31,217,255,.36); }
.card { background:var(--bg-panel)!important;border:1px solid var(--border)!important;border-radius:12px!important;padding:16px!important; }
button.primary { background:linear-gradient(90deg,var(--accent),#818cf8)!important;border:none!important;color:#fff!important;font-weight:700!important;border-radius:8px!important; }
button.secondary { background:var(--bg-elevated)!important;border:1px solid var(--border-hover)!important;color:var(--text-main)!important;border-radius:8px!important; }
textarea,input,select { background:#0f1522!important;border-color:var(--border)!important;color:var(--text-main)!important; }
.ops-strip { margin-top:8px;border:1px solid var(--border);border-radius:12px;padding:10px 14px;background:linear-gradient(90deg,#0f1117,#1a1d2e); }
.ops-title { font-size:12px;color:var(--text-muted);margin-bottom:8px;font-weight:700;letter-spacing:.04em; }
.ops-row { display:flex;gap:8px;flex-wrap:wrap; }
.ops-pill { display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;border:1px solid var(--border);background:#0f1624;font-size:12px; }
.ops-online{color:#34d399}.ops-offline{color:#f87171}.ops-metric{color:#ffd7b5}
.status-dot { display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px; }
.status-dot.online{background:#34d399}.status-dot.offline{background:#f87171}
.provider-result { background:var(--bg-elevated);border-left:3px solid var(--accent);padding:12px;margin:8px 0;border-radius:0 8px 8px 0; }
.skill-card { background:linear-gradient(135deg,#1a1d2e,#1e2235);border:1px solid var(--accent);border-radius:12px;padding:14px; }
.skill-badge { display:inline-block;padding:2px 10px;border-radius:12px;font-size:.85em; }
.badge-critical{background:#7f1d1d;color:#fca5a5}.badge-high{background:#78350f;color:#fcd34d}.badge-medium{background:#1e3a5f;color:#93c5fd}
.mcp-card { background:var(--bg-panel);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center;cursor:pointer;transition:all .2s; }
.mcp-card:hover { border-color:var(--accent);transform:translateY(-2px); }
.output-scroll { max-height:400px;overflow-y:auto;font-family:'JetBrains Mono','Fira Code',monospace;font-size:.9em; }
.tab-nav button{color:var(--text-muted)!important}.tab-nav button.selected{color:var(--accent-light)!important;border-bottom:2px solid var(--accent)!important}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def add_log(level: str, message: str):
    logs.append({
        "level": level,
        "message": message,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def ensure_local_no_proxy():
    bypass = ["localhost", "127.0.0.1", "::1"]
    for key in ("NO_PROXY", "no_proxy"):
        existing = os.getenv(key, "")
        parts = [x.strip() for x in existing.split(",") if x.strip()]
        for v in bypass:
            if v not in parts:
                parts.append(v)
        os.environ[key] = ",".join(parts)


# ---------------------------------------------------------------------------
# Provider / status helpers
# ---------------------------------------------------------------------------


def _provider_statuses() -> Dict[str, bool]:
    statuses: Dict[str, bool] = {}
    try:
        import host_orchestrator  # noqa: F401
        statuses["Orchestrator"] = True
    except Exception:
        statuses["Orchestrator"] = False

    try:
        import pii_guard  # noqa: F401
        statuses["PII Guard"] = True
    except Exception:
        statuses["PII Guard"] = False

    statuses["Context7"] = bool(os.getenv("CONTEXT7_API_KEY"))
    statuses["Tavily"] = bool(os.getenv("TAVILY_API_KEY"))
    statuses["Exa"] = bool(os.getenv("EXA_SEARCH_API_KEY"))
    statuses["Firecrawl"] = bool(os.getenv("FIRECRAWL_API_KEY"))
    return statuses


def render_operational_status_bar() -> str:
    statuses = _provider_statuses()
    pills = []
    for name, online in statuses.items():
        cls = "ops-online" if online else "ops-offline"
        pills.append(f'<span class="ops-pill">{name}: <b class="{cls}">{"ONLINE" if online else "OFFLINE"}</b></span>')
    pills.append(f'<span class="ops-pill">summary_threshold: <b class="ops-metric">{current_summary_threshold}</b></span>')
    pills.append(f'<span class="ops-pill">active_sessions: <b class="ops-metric">{len(sessions)}</b></span>')
    return f'<div class="ops-strip"><div class="ops-title">ОПЕРАЦИОННЫЙ СТАТУС</div><div class="ops-row">{"".join(pills)}</div></div>'


def refresh_operational_status() -> str:
    return render_operational_status_bar()


# ---------------------------------------------------------------------------
# Skill / MCP helpers
# ---------------------------------------------------------------------------


def _get_skill_list() -> List[Dict]:
    global _skill_list_cache
    if _skill_list_cache is not None:
        return _skill_list_cache
    try:
        _skill_list_cache = _get_dispatcher().list_skills()
        return _skill_list_cache
    except Exception as e:
        add_log("ERROR", f"Skill list load failed: {e}")
        return []


def _get_mcp_servers() -> List[str]:
    global _mcp_servers_cache
    if _mcp_servers_cache is not None:
        return _mcp_servers_cache
    servers_dir = os.path.join(PROJECT_DIR, "src", "mcp_servers")
    if not os.path.isdir(servers_dir):
        return []
    _mcp_servers_cache = sorted(
        d for d in os.listdir(servers_dir)
        if os.path.isdir(os.path.join(servers_dir, d))
    )
    return _mcp_servers_cache


def _skill_dropdown_choices() -> List[Tuple[str, str]]:
    skills = _get_skill_list()
    groups: Dict[str, List[Dict]] = {}
    for s in skills:
        groups.setdefault(s.get("role", "Other") or "Other", []).append(s)
    choices = []
    for role in sorted(groups):
        for s in groups[role]:
            choices.append((f"[{role}] {s.get('name', s.get('stem', '?'))}", s.get("stem", "")))
    return choices


# ---------------------------------------------------------------------------
# Tab 1: Knowledge Search
# ---------------------------------------------------------------------------


async def _unified_search(
    query: str,
    use_context7: bool,
    use_tavily: bool,
    use_exa: bool,
    use_shiva: bool,
    use_docfusion: bool,
    use_firecrawl: bool,
    library: str,
    translate: bool,
) -> str:
    if not query.strip():
        return "Введите поисковый запрос."
    results_parts: List[str] = []
    try:
        from host_orchestrator import ContextOrchestrator

        orchestrator = ContextOrchestrator(
            enable_knowledge_bridge=True,
            enable_context7=use_context7,
            enable_external_knowledge=True,
        )
        await orchestrator.connect()
        try:
            result = await orchestrator.external_search(
                query=query,
                domain="python",
                library=library.strip() or None,
                limit=5,
            )
            chunks = result.get("chunks", [])
            source_map: Dict[str, List] = {}
            for chunk in chunks:
                src = chunk.get("source", "unknown")
                source_map.setdefault(src, []).append(chunk)

            provider_flags = {
                "context7": use_context7,
                "tavily": use_tavily,
                "exa": use_exa,
                "shiva": use_shiva,
                "docfusion": use_docfusion,
                "firecrawl": use_firecrawl,
            }
            for src, items in source_map.items():
                flag = provider_flags.get(src, True)
                if not flag:
                    continue
                results_parts.append(f'<div class="provider-result">')
                results_parts.append(f"<h4>{src.upper()}</h4>")
                for item in items[:3]:
                    content = str(item.get("content", ""))[:800]
                    score = item.get("score", "—")
                    results_parts.append(
                        f"<p><b>Score:</b> {score}</p>"
                        f"<pre class='output-scroll'>{content}</pre>"
                    )
                results_parts.append("</div>")
            if not results_parts:
                results_parts.append("<p>Нет результатов по выбранным провайдерам.</p>")
            add_log("INFO", f"Unified search: {query[:60]}")
        finally:
            await orchestrator.disconnect()
    except Exception as e:
        add_log("ERROR", f"Unified search error: {e}")
        results_parts.append(f"<p style='color:#f87171'>Error: {e}</p>")
    return "\n".join(results_parts)


# ---------------------------------------------------------------------------
# Tab 2: Context7 Documentation
# ---------------------------------------------------------------------------


async def _resolve_library(library_name: str) -> str:
    try:
        from context7_client import Context7Client
        client = Context7Client()
        await client.connect()
        try:
            lib_id = await client.resolve_library_id(library_name)
            if lib_id:
                add_log("INFO", f"Resolved {library_name} -> {lib_id}")
                return f"Resolved: <b>{lib_id}</b>"
            return f"Библиотека '{library_name}' не найдена."
        finally:
            await client.disconnect()
    except Exception as e:
        return f"Error: {e}"


async def _query_docs(library: str, query: str, translate: bool) -> str:
    if not query.strip():
        return "Введите запрос."
    try:
        from context7_client import Context7Client
        client = Context7Client()
        await client.connect()
        try:
            if not client._connected:
                return "Ошибка: Context7 не подключён."
            lib_id = await client.resolve_library_id(library, query)
            if not lib_id:
                return f"Библиотека '{library}' не найдена."
            result = await client.query_docs(lib_id, query, translate=translate)
            if result.get("status") == "success":
                content = result.get("content", "")
                add_log("INFO", f"Context7 query: {library}/{query[:50]}")
                return content
            return f"Error: {result.get('error', 'Unknown')}"
        finally:
            await client.disconnect()
    except Exception as e:
        add_log("ERROR", f"Context7 query error: {e}")
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Tab 3: PII & Security
# ---------------------------------------------------------------------------


def _scan_pii_presidio(text: str, language: str) -> Tuple[str, str, str]:
    if not text.strip(): return "", "", ""
    try:
        from pii_guard import get_pii_guard
        guard = get_pii_guard()
        entities = guard.analyze(text, language=language)
        if not entities:
            return "<p style='color:#34d399'>PII не обнаружен.</p>", text, ""
        rows = []
        for e in entities:
            sev = "badge-critical" if e.entity_type in ("PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "INN") else "badge-medium"
            rows.append(f"<tr><td>{e.entity_type}</td><td>{e.text}</td><td>{e.start}-{e.end}</td><td><span class='skill-badge {sev}'>{('HIGH' if 'critical' in sev else 'MEDIUM')}</span></td></tr>")
        table = "<table style='width:100%;border-collapse:collapse'><tr style='color:#818cf8'><th>Type</th><th>Value</th><th>Pos</th><th>Severity</th></tr>" + "".join(rows) + "</table>"
        add_log("INFO", f"PII scan (Presidio): {len(entities)} entities")
        return table, text, ""
    except Exception as e:
        return f"<p style='color:#f87171'>Error: {e}</p>", text, ""


def _scan_pii_mcp(text: str, language: str) -> Tuple[str, str, str]:
    if not text.strip(): return "", "", ""
    try:
        from agent_executor import MCPClient
        server_path = os.path.join(PROJECT_DIR, "src", "mcp_servers", "pii_scanner", "server.py")
        client = MCPClient(server_path, "pii_scanner")

        async def _do():
            ok = await client.start()
            if not ok:
                return "<p style='color:#f87171'>MCP pii_scanner не запустился.</p>", text, ""
            tools = await client.list_tools()
            tool_names = [t["name"] for t in tools]
            html = f"<p>MCP pii_scanner tools: {', '.join(tool_names)}</p>"
            if "scan_pii" in tool_names:
                res = await client.call_tool("scan_pii", {"text": text, "language": language})
                html += f"<pre class='output-scroll'>{res or 'no result'}</pre>"
            elif "check_health" in tool_names:
                res = await client.call_tool("check_health")
                html += f"<pre class='output-scroll'>{res or 'no result'}</pre>"
            client.stop()
            add_log("INFO", "PII scan (MCP pii_scanner)")
            return html, text, ""

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_do())
        finally:
            loop.close()
    except Exception as e:
        return f"<p style='color:#f87171'>Error: {e}</p>", text, ""


def _mask_pii(text: str, language: str) -> str:
    if not text.strip():
        return ""
    try:
        from pii_guard import get_pii_guard
        guard = get_pii_guard()
        masked = guard.mask(text, language=language)
        add_log("INFO", "PII masked")
        return masked
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Tab 4: AI Experts
# ---------------------------------------------------------------------------


def _find_skills(query: str) -> str:
    if not query.strip():
        return "Введите описание задачи."
    try:
        dispatcher = _get_dispatcher()
        matches = dispatcher.find_skill(query, top_k=3)
        if not matches:
            return "Подходящие навыки не найдены."
        parts = []
        for m in matches:
            score = m.get("score", 0)
            parts.append(
                f"**{m.get('name', '?')}** (stem: `{m.get('stem', '')}`)\n"
                f"- Роль: {m.get('role', '—')}\n"
                f"- Триггер: {m.get('trigger', '—')}\n"
                f"- Приоритет: {m.get('priority', '—')}\n"
                f"- Score: {score}\n"
            )
        return "\n---\n".join(parts)
    except Exception as e:
        return f"Error: {e}"


def _get_skill_card(stem: str) -> str:
    if not stem:
        return ""
    try:
        dispatcher = _get_dispatcher()
        skills = {s["stem"]: s for s in dispatcher.list_skills()}
        s = skills.get(stem)
        if not s:
            return f"Навык '{stem}' не найден."
        tools = dispatcher.get_required_tools(stem)
        priority = s.get("priority", "normal")
        badge_cls = {
            "critical": "badge-critical",
            "high": "badge-high",
        }.get(priority, "badge-medium")

        return (
            f'<div class="skill-card">'
            f"<h3>{s.get('name', stem)}</h3>"
            f"<p><b>Роль:</b> {s.get('role', '—')}</p>"
            f"<p><b>Триггер:</b> {s.get('trigger', '—')}</p>"
            f"<p><b>Приоритет:</b> "
            f'<span class="skill-badge {badge_cls}">{priority}</span></p>'
            f"<p><b>Bash tools:</b> {', '.join(tools.get('bash_tools', [])[:8]) or '—'}</p>"
            f"<p><b>MCP servers:</b> {', '.join(tools.get('mcp_servers', [])[:8]) or '—'}</p>"
            f"</div>"
        )
    except Exception as e:
        return f"Error: {e}"


async def _execute_skill(stem: str, task: str) -> Tuple[str, str]:
    """Execute skill, returns (response_markdown, details_markdown)."""
    if not stem or not task.strip():
        return "Выберите навык и введите задачу.", ""
    try:
        executor = _get_executor()
        result = await executor.execute(stem, task)

        response = result.get("response", "")
        if not response:
            response = result.get("error", "Пустой ответ от LLM.")

        details_parts = [
            f"**Навык:** {result.get('skill', stem)}",
            f"**Статус:** {result.get('status', '—')}",
        ]
        if result.get("system_prompt"):
            sp = result["system_prompt"][:500]
            details_parts.append(f"<details><summary>System prompt</summary>\n```\n{sp}\n```</details>")
        mcp_results = result.get("mcp_results", {})
        if mcp_results:
            details_parts.append(
                f"<details><summary>MCP results</summary>\n```json\n"
                f"{json.dumps(mcp_results, ensure_ascii=False, indent=2, default=str)[:1000]}\n```</details>"
            )
        mcp_ctx = result.get("mcp_context", "")
        if mcp_ctx:
            details_parts.append(
                f"<details><summary>MCP context</summary>\n```\n{mcp_ctx[:500]}\n```</details>"
            )

        # Save to history
        _execution_history.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "skill": stem,
            "task": task[:100],
            "status": result.get("status", "unknown"),
        })

        add_log("INFO", f"Skill executed: {stem}, status={result.get('status')}")
        return response, "\n\n".join(details_parts)
    except Exception as e:
        add_log("ERROR", f"Skill execution error: {e}")
        return f"Error: {e}", ""


# ---------------------------------------------------------------------------
# Tab 5: MCP Servers
# ---------------------------------------------------------------------------


async def _check_server_health(server_name: str) -> bool:
    try:
        from agent_executor import MCPClient
        server_path = os.path.join(
            PROJECT_DIR, "src", "mcp_servers", server_name, "server.py"
        )
        client = MCPClient(server_path, server_name)
        ok = await client.start()
        if ok:
            client.stop()
        return ok
    except Exception:
        return False


async def _check_all_servers() -> str:
    servers = _get_mcp_servers()
    results_parts = []
    online_count = 0
    for name in servers:
        healthy = await _check_server_health(name)
        _mcp_health_cache[name] = healthy
        if healthy:
            online_count += 1
        dot_cls = "online" if healthy else "offline"
        label = "ONLINE" if healthy else "OFFLINE"
        results_parts.append(
            f'<div class="mcp-card" style="display:inline-block;margin:4px;">'
            f'<span class="status-dot {dot_cls}"></span>'
            f"<b>{name}</b> <small>{label}</small>"
            f"</div>"
        )
    add_log("INFO", f"MCP health check: {online_count}/{len(servers)} online")
    header = f"<h3>{online_count}/{len(servers)} онлайн</h3>"
    return header + "\n".join(results_parts)


async def _get_server_tools(server_name: str) -> Tuple[str, str, str]:
    """Returns (server_info, tool_dropdown_choices_str, empty_result)."""
    if not server_name:
        return "", "", ""
    try:
        from agent_executor import MCPClient
        server_path = os.path.join(
            PROJECT_DIR, "src", "mcp_servers", server_name, "server.py"
        )
        client = MCPClient(server_path, server_name)
        ok = await client.start()
        if not ok:
            return f"Сервер {server_name} не запустился.", "", ""
        tools = await client.list_tools()
        client.stop()

        info_parts = [f"<h3>{server_name}</h3>", f"<p>Tools: {len(tools)}</p>"]
        tool_names = []
        for t in tools:
            tname = t.get("name", "?")
            tdesc = t.get("description", "—")[:120]
            tool_names.append(tname)
            info_parts.append(f"<p><b>{tname}</b>: {tdesc}</p>")

        choices_str = json.dumps(tool_names, ensure_ascii=False)
        return "\n".join(info_parts), choices_str, ""
    except Exception as e:
        return f"Error: {e}", "", ""


async def _call_mcp_tool(server_name: str, tool_name: str, args_json: str) -> str:
    if not server_name or not tool_name:
        return "Выберите сервер и инструмент."
    try:
        from agent_executor import MCPClient
        server_path = os.path.join(
            PROJECT_DIR, "src", "mcp_servers", server_name, "server.py"
        )
        client = MCPClient(server_path, server_name)
        ok = await client.start()
        if not ok:
            return f"Сервер {server_name} не запустился."
        arguments = {}
        if args_json.strip():
            arguments = json.loads(args_json)
        result = await client.call_tool(tool_name, arguments)
        client.stop()
        add_log("INFO", f"MCP call: {server_name}/{tool_name}")
        return str(result or "Пустой ответ")
    except json.JSONDecodeError:
        return "Ошибка: аргументы должны быть валидным JSON."
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Tab 6: System
# ---------------------------------------------------------------------------


def get_stats_text() -> str:
    skills = _get_skill_list()
    mcp_servers = _get_mcp_servers()
    return (
        f"Session ID: demo_session\n"
        f"Context History Length: 0 messages\n"
        f"Compression Count: 0\n"
        f"Max Tokens: 128000\n"
        f"Summary Threshold: {current_summary_threshold}\n"
        f"Connected: True\n"
        f"Active Sessions: {len(sessions)}\n"
        f"Total Logs: {len(logs)}\n"
        f"Loaded Skills: {len(skills)}\n"
        f"MCP Servers: {len(mcp_servers)}"
    )


def get_logs_text() -> str:
    if not logs:
        return "Нет логов."
    lines = []
    for log in logs[-30:]:
        lines.append(f"[{log['timestamp']}] {log['level']}: {log['message']}")
    return "\n".join(lines)


def create_session(name: str) -> str:
    session_id = f"sess_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    sessions[session_id] = {
        "name": name or f"Session {session_id}",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "messages": [],
        "tokens": 0,
    }
    add_log("INFO", f"Session created: {session_id}")
    return f"Сессия '{name}' создана: {session_id}"


def list_sessions() -> str:
    if not sessions:
        return "Нет активных сессий."
    parts = []
    for sid, data in sessions.items():
        parts.append(
            f"ID: {sid}\nName: {data['name']}\n"
            f"Created: {data['created_at']}\nMessages: {len(data['messages'])}"
        )
    return "\n\n".join(parts)


def delete_session(session_id: str) -> str:
    if session_id not in sessions:
        return f"Сессия {session_id} не найдена."
    name = sessions[session_id]["name"]
    del sessions[session_id]
    add_log("INFO", f"Session deleted: {session_id}")
    return f"Сессия '{name}' удалена."


def compress_context(threshold: int = 100000) -> str:
    global current_summary_threshold
    current_summary_threshold = int(threshold)
    add_log("INFO", f"Compression triggered, threshold={threshold}")
    return f"Контекст сжат. Порог: {threshold} токенов."


def create_checkpoint() -> str:
    ckpt = f"ckpt_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    add_log("INFO", f"Checkpoint: {ckpt}")
    return f"Чекпоинт создан: {ckpt}"


def get_config_view() -> str:
    env_keys = [
        "CONTEXT7_API_KEY", "TAVILY_API_KEY", "EXA_SEARCH_API_KEY",
        "FIRECRAWL_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
        "ANTHROPIC_BASE_URL",
    ]
    lines = ["=== Конфигурация (.env) ===\n"]
    for key in env_keys:
        val = os.getenv(key, "")
        masked = val[:4] + "..." + val[-4:] if len(val) > 12 else ("***" if val else "НЕ ЗАДАН")
        lines.append(f"{key}: {masked}")
    skills = _get_skill_list()
    mcp = _get_mcp_servers()
    lines.append(f"\nНавыков загружено: {len(skills)}")
    lines.append(f"MCP серверов: {len(mcp)}")
    return "\n".join(lines)


def init_orchestrator() -> str:
    try:
        from host_orchestrator import ContextOrchestrator
        _orch = ContextOrchestrator()
        add_log("INFO", "Orchestrator initialized")
        return "Orchestrator инициализирован."
    except Exception as e:
        add_log("ERROR", f"Orchestrator init failed: {e}")
        return f"Error: {e}"


def get_execution_history() -> str:
    if not _execution_history:
        return "История пуста."
    parts = []
    for h in _execution_history[-20:]:
        parts.append(
            f"[{h['timestamp']}] {h['skill']} — {h['status']}\n  {h['task']}"
        )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# MCP server grid for Tab 5
# ---------------------------------------------------------------------------


def _render_mcp_grid() -> str:
    servers = _get_mcp_servers()
    cards = []
    for name in servers:
        healthy = _mcp_health_cache.get(name)
        if healthy is None:
            dot = '<span style="color:#9aa7c1">●</span>'
        elif healthy:
            dot = '<span class="status-dot online"></span>'
        else:
            dot = '<span class="status-dot offline"></span>'
        cards.append(
            f'<div class="mcp-card" style="display:inline-block;width:180px;margin:4px;vertical-align:top;">'
            f"{dot}<b>{name}</b>"
            f"</div>"
        )
    return "\n".join(cards) if cards else "<p>MCP серверы не найдены.</p>"


# ===========================================================================
# Gradio UI
# ===========================================================================


def build_ui():
    with gr.Blocks(title="MCP Context Pipeline v2", css=APP_CSS) as demo:
        # --- Header ---
        gr.HTML(
            """
<div class="app-hero">
  <p class="hero-title">MCP Context Pipeline Console v2</p>
  <p class="hero-subtitle">
    Поиск знаний, документация, PII-защита, AI-эксперты, MCP-серверы, системная диагностика.
  </p>
  <div class="badge-row">
    <span class="badge badge-accent">Knowledge Search</span>
    <span class="badge badge-orange">PII Guard</span>
    <span class="badge badge-cyan">Context7</span>
    <span class="badge badge-accent">AI Experts</span>
    <span class="badge badge-orange">MCP (27 servers)</span>
  </div>
</div>
"""
        )

        # --- Status bar ---
        with gr.Row():
            status_bar = gr.HTML(value=render_operational_status_bar())
            refresh_status_btn = gr.Button(
                "Обновить статус", size="sm", variant="secondary"
            )

        # ===================================================================
        # Tabs
        # ===================================================================
        with gr.Tabs():
            # ---------------------------------------------------------------
            # Tab 1: Knowledge Search
            # ---------------------------------------------------------------
            with gr.Tab("🔍 Поиск знаний"):
                with gr.Row():
                    with gr.Column(scale=3):
                        ks_query = gr.Textbox(
                            label="Поисковый запрос",
                            lines=3,
                            placeholder="Например: REST API pagination best practices",
                        )
                    with gr.Column(scale=2):
                        gr.Markdown("### Провайдеры")
                        ks_ctx7 = gr.Checkbox(label="Context7", value=True)
                        ks_tavily = gr.Checkbox(label="Tavily", value=True)
                        ks_exa = gr.Checkbox(label="Exa", value=True)
                        ks_shiva = gr.Checkbox(label="Shiva", value=True)
                        ks_docfusion = gr.Checkbox(label="DocFusion", value=True)
                        ks_firecrawl = gr.Checkbox(label="Firecrawl", value=True)
                        ks_library = gr.Dropdown(
                            choices=[
                                "torch", "transformers", "fastapi",
                                "anthropic", "openai", "redis", "postgresql",
                            ],
                            value="fastapi",
                            label="Библиотека (Context7)",
                        )
                        ks_translate = gr.Checkbox(
                            label="Перевести на русский", value=False
                        )

                ks_btn = gr.Button("Искать", variant="primary")
                ks_results = gr.HTML(label="Результаты")

            # ---------------------------------------------------------------
            # Tab 2: Documentation
            # ---------------------------------------------------------------
            with gr.Tab("📚 Документация"):
                with gr.Row():
                    with gr.Column(scale=1):
                        doc_library = gr.Textbox(
                            label="Библиотека",
                            placeholder="Например: fastapi",
                            value="fastapi",
                        )
                        doc_resolve_btn = gr.Button(
                            "Resolve", size="sm", variant="secondary"
                        )
                        doc_resolved = gr.HTML()
                    with gr.Column(scale=2):
                        doc_query = gr.Textbox(
                            label="Запрос документации",
                            lines=2,
                            placeholder="Например: dependency injection",
                        )
                        doc_translate = gr.Checkbox(
                            label="Перевести", value=False
                        )
                        doc_btn = gr.Button("Запросить", variant="primary")

                doc_output = gr.Textbox(
                    label="Документация",
                    lines=20,
                    interactive=False,
                    elem_classes=["output-scroll"],
                )

            # ---------------------------------------------------------------
            # Tab 3: PII & Security
            # ---------------------------------------------------------------
            with gr.Tab("🛡 PII & Безопасность"):
                pii_input = gr.Textbox(
                    label="Текст для анализа",
                    lines=5,
                    placeholder="Введите текст с возможными персональными данными...",
                )
                pii_lang = gr.Radio(
                    choices=["ru", "en"], value="ru", label="Язык"
                )

                with gr.Row():
                    pii_presidio_btn = gr.Button(
                        "Сканировать (Presidio)", variant="primary"
                    )
                    pii_mcp_btn = gr.Button(
                        "Сканировать (MCP pii_scanner)", variant="secondary"
                    )

                pii_entities = gr.HTML(label="Обнаруженные сущности")

                with gr.Row():
                    with gr.Column():
                        gr.Markdown("**Оригинал**")
                        pii_original = gr.Textbox(
                            lines=6, interactive=False, show_label=False
                        )
                    with gr.Column():
                        gr.Markdown("**Маскированный**")
                        pii_masked = gr.Textbox(
                            lines=6, interactive=False, show_label=False
                        )

                pii_mask_btn = gr.Button("Маскировать", variant="primary")

            # ---------------------------------------------------------------
            # Tab 4: AI Experts
            # ---------------------------------------------------------------
            with gr.Tab("🤖 Эксперты"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### Выбрать навык")
                        skill_dropdown = gr.Dropdown(
                            choices=_skill_dropdown_choices(),
                            label="Навык",
                            filterable=True,
                        )
                    with gr.Column(scale=1):
                        gr.Markdown("### Автоподбор")
                        auto_query = gr.Textbox(
                            label="Описание задачи",
                            placeholder="Опишите что нужно сделать...",
                        )
                        auto_find_btn = gr.Button(
                            "Найти подходящий навык", variant="secondary"
                        )
                        auto_results = gr.Markdown()

                skill_card = gr.HTML(label="Карточка навыка")
                expert_task = gr.Textbox(
                    label="Задача",
                    lines=4,
                    placeholder="Опишите задачу для выполнения...",
                )
                expert_run_btn = gr.Button(
                    "Запустить эксперта", variant="primary", size="lg"
                )

                with gr.Row():
                    with gr.Column(scale=2):
                        expert_response = gr.Markdown(label="Ответ")
                    with gr.Column(scale=1):
                        expert_details = gr.HTML(label="Детали")

                expert_history_btn = gr.Button("История запусков", size="sm", variant="secondary")
                expert_history = gr.Textbox(
                    label="История", lines=8, interactive=False
                )

            # ---------------------------------------------------------------
            # Tab 5: MCP Servers
            # ---------------------------------------------------------------
            with gr.Tab("⚡ MCP Серверы"):
                mcp_grid = gr.HTML(value=_render_mcp_grid())
                mcp_check_all_btn = gr.Button(
                    "Проверить все", variant="primary"
                )
                mcp_health_summary = gr.HTML()

                gr.Markdown("### Тестирование сервера")
                with gr.Row():
                    mcp_server_input = gr.Textbox(
                        label="Имя сервера",
                        placeholder="Например: pii_scanner",
                    )
                    mcp_load_btn = gr.Button(
                        "Загрузить инструменты", variant="secondary"
                    )
                mcp_server_info = gr.HTML()

                with gr.Row():
                    mcp_tool_select = gr.Dropdown(
                        choices=[], label="Инструмент"
                    )
                    mcp_tool_args = gr.Textbox(
                        label="Аргументы (JSON)",
                        placeholder='{"key": "value"}',
                        lines=3,
                    )
                mcp_call_btn = gr.Button("Вызвать", variant="primary")
                mcp_tool_result = gr.Textbox(
                    label="Результат", lines=12, interactive=False
                )

                # Hidden state for selected server name
                mcp_selected_server = gr.State("")

            # ---------------------------------------------------------------
            # Tab 6: System
            # ---------------------------------------------------------------
            with gr.Tab("⚙️ Система"):
                gr.Markdown("### Инициализация")
                with gr.Row():
                    init_btn = gr.Button(
                        "Инициализировать Orchestrator", variant="primary"
                    )
                    init_output = gr.Textbox(
                        label="Статус", interactive=False
                    )

                with gr.Row():
                    with gr.Column(elem_classes=["card"]):
                        gr.Markdown("### Статистика")
                        stats_text = gr.Textbox(
                            label="Статистика",
                            value="Нажмите для обновления",
                            lines=10,
                            interactive=False,
                        )
                        refresh_stats_btn = gr.Button(
                            "Обновить статистику", size="sm"
                        )

                    with gr.Column(elem_classes=["card"]):
                        gr.Markdown("### Конфигурация")
                        config_view = gr.Textbox(
                            label="Config",
                            value="Нажмите для загрузки",
                            lines=10,
                            interactive=False,
                        )
                        refresh_config_btn = gr.Button(
                            "Показать конфигурацию", size="sm"
                        )

                with gr.Row():
                    with gr.Column(elem_classes=["card"]):
                        gr.Markdown("### Сессии")
                        session_name = gr.Textbox(label="Имя сессии")
                        create_session_btn = gr.Button(
                            "Создать сессию", variant="primary"
                        )
                        session_output = gr.Textbox(
                            label="Результат", lines=2, interactive=False
                        )
                        with gr.Row():
                            list_sessions_btn = gr.Button(
                                "Список", size="sm"
                            )
                            delete_session_input = gr.Textbox(
                                label="ID для удаления", placeholder="sess_..."
                            )
                            delete_session_btn = gr.Button(
                                "Удалить", variant="stop", size="sm"
                            )
                        sessions_output = gr.Textbox(
                            label="Активные сессии",
                            lines=6,
                            interactive=False,
                        )

                    with gr.Column(elem_classes=["card"]):
                        gr.Markdown("### Действия")
                        compress_threshold = gr.Slider(
                            50000, 128000, value=100000,
                            label="Порог сжатия (токены)",
                        )
                        with gr.Row():
                            compress_btn = gr.Button(
                                "Сжать контекст", variant="secondary"
                            )
                            checkpoint_btn = gr.Button(
                                "Создать чекпоинт", variant="secondary"
                            )
                        action_output = gr.Textbox(
                            label="Результат", lines=3, interactive=False
                        )

                with gr.Row():
                    with gr.Column(elem_classes=["card"]):
                        gr.Markdown("### Системные логи")
                        refresh_logs_btn = gr.Button(
                            "Обновить логи", size="sm"
                        )
                        logs_output = gr.Textbox(
                            label="",
                            value="Логи будут здесь...",
                            lines=14,
                            interactive=False,
                        )

        # ===================================================================
        # Event wiring
        # ===================================================================

        # --- Tab 1: Knowledge Search ---
        ks_btn.click(
            lambda q, c, t, e, sh, df, fc, lib, tr: run_async(
                _unified_search(q, c, t, e, sh, df, fc, lib, tr)
            ),
            inputs=[
                ks_query, ks_ctx7, ks_tavily, ks_exa,
                ks_shiva, ks_docfusion, ks_firecrawl,
                ks_library, ks_translate,
            ],
            outputs=[ks_results],
        )

        # --- Tab 2: Documentation ---
        doc_resolve_btn.click(
            lambda lib: run_async(_resolve_library(lib)),
            inputs=[doc_library],
            outputs=[doc_resolved],
        )
        doc_btn.click(
            lambda lib, q, tr: run_async(_query_docs(lib, q, tr)),
            inputs=[doc_library, doc_query, doc_translate],
            outputs=[doc_output],
        )

        # --- Tab 3: PII ---
        pii_presidio_btn.click(
            _scan_pii_presidio,
            inputs=[pii_input, pii_lang],
            outputs=[pii_entities, pii_original, pii_masked],
        )
        pii_mcp_btn.click(
            _scan_pii_mcp,
            inputs=[pii_input, pii_lang],
            outputs=[pii_entities, pii_original, pii_masked],
        )
        pii_mask_btn.click(
            _mask_pii,
            inputs=[pii_input, pii_lang],
            outputs=[pii_masked],
        )

        # --- Tab 4: Experts ---
        skill_dropdown.change(
            _get_skill_card,
            inputs=[skill_dropdown],
            outputs=[skill_card],
        )
        auto_find_btn.click(
            _find_skills,
            inputs=[auto_query],
            outputs=[auto_results],
        )
        expert_run_btn.click(
            lambda stem, task: run_async(_execute_skill(stem, task)),
            inputs=[skill_dropdown, expert_task],
            outputs=[expert_response, expert_details],
        )
        expert_history_btn.click(
            get_execution_history,
            outputs=[expert_history],
        )

        # --- Tab 5: MCP ---
        mcp_check_all_btn.click(
            lambda: run_async(_check_all_servers()),
            outputs=[mcp_health_summary],
        )
        mcp_load_btn.click(
            lambda name: run_async(_get_server_tools(name)),
            inputs=[mcp_server_input],
            outputs=[mcp_server_info, mcp_tool_select, mcp_tool_result],
        )
        mcp_call_btn.click(
            lambda srv, tool, args: run_async(_call_mcp_tool(srv, tool, args)),
            inputs=[mcp_server_input, mcp_tool_select, mcp_tool_args],
            outputs=[mcp_tool_result],
        )

        # --- Tab 6: System ---
        init_btn.click(init_orchestrator, outputs=[init_output])
        refresh_stats_btn.click(get_stats_text, outputs=[stats_text])
        refresh_config_btn.click(get_config_view, outputs=[config_view])
        compress_btn.click(
            compress_context,
            inputs=[compress_threshold],
            outputs=[action_output],
        )
        checkpoint_btn.click(create_checkpoint, outputs=[action_output])
        create_session_btn.click(
            create_session, inputs=[session_name], outputs=[session_output]
        )
        list_sessions_btn.click(list_sessions, outputs=[sessions_output])
        delete_session_btn.click(
            delete_session,
            inputs=[delete_session_input],
            outputs=[session_output],
        )
        refresh_logs_btn.click(get_logs_text, outputs=[logs_output])
        refresh_status_btn.click(
            refresh_operational_status, outputs=[status_bar]
        )
        compress_threshold.change(
            lambda v: render_operational_status_bar(),
            outputs=[status_bar],
        )
        create_session_btn.click(
            refresh_operational_status, outputs=[status_bar]
        )
        delete_session_btn.click(
            refresh_operational_status, outputs=[status_bar]
        )
        demo.load(refresh_operational_status, outputs=[status_bar])

    return demo


# ===========================================================================
# Entry point
# ===========================================================================

demo = build_ui()

if __name__ == "__main__":
    ensure_local_no_proxy()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
    )
