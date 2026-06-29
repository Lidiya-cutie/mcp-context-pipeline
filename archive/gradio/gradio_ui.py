"""
Веб-интерфейс для MCP Context Pipeline на базе Gradio
"""

import gradio as gr
import asyncio
import json
import os
import re
from datetime import datetime
from typing import List, Dict, Optional
import sys
sys.path.insert(0, '/mldata/mcp_context_pipeline/src')

sessions: Dict[str, Dict] = {}
logs: List[Dict] = []

STATUS_LINE_RE = re.compile(r"-\s*([А-Яа-яA-Za-zЁё][^—\n]+?)\s*—\s*tasks:\s*(\d+)")
TOTAL_TASKS_RE = re.compile(r"Total tasks:\s*(\d+)", re.IGNORECASE)
PROJECT_RE = re.compile(r"\*\*Project\*\*:\s*(.+)")
TEAM_RE = re.compile(r"\*\*Team\*\*:\s*(.+)")
LEADER_RE = re.compile(r"\*\*Leader\*\*:\s*(.+)")
OBJECTIVE_RE = re.compile(r"### Objective\s*(.*?)\s*(?:###|$)", re.DOTALL)
DESCRIPTION_RE = re.compile(r"### Description\s*(.*?)\s*(?:###|$)", re.DOTALL)
PARTICIPANT_RE = re.compile(r"-\s*([^—\n]+)\s*—\s*roles:\s*[^,]+,\s*tasks:\s*(\d+)")
PROJECT_ID_RE = re.compile(r"\*\*projectId\*\*:\s*(\d+)", re.IGNORECASE)

APP_CSS = """
:root {
  --bg-main: #0d1016;
  --bg-panel: #141925;
  --bg-elevated: #1b2232;
  --text-main: #eef3ff;
  --text-muted: #9aa7c1;
  --accent-orange: #ff7a18;
  --accent-amber: #ffb347;
  --accent-cyan: #1fd9ff;
  --border-soft: #2a344b;
}

.gradio-container {
  background: radial-gradient(circle at 15% 0%, #1b2232 0%, var(--bg-main) 42%, #0a0d13 100%);
  color: var(--text-main);
}

.app-hero {
  border: 1px solid var(--border-soft);
  border-radius: 16px;
  padding: 16px 18px;
  margin-bottom: 10px;
  background: linear-gradient(120deg, #161d2c 0%, #121823 55%, #181f2f 100%);
  box-shadow: 0 0 0 1px rgba(255, 122, 24, 0.08), 0 8px 26px rgba(0, 0, 0, 0.35);
}

.hero-title {
  font-size: 28px;
  font-weight: 800;
  margin: 0 0 6px 0;
}

.hero-subtitle {
  color: var(--text-muted);
  margin: 0;
}

.badge-row {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.badge {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  border: 1px solid transparent;
}

.badge-orange {
  background: rgba(255, 122, 24, 0.18);
  color: #ffd5b0;
  border-color: rgba(255, 122, 24, 0.38);
}

.badge-cyan {
  background: rgba(31, 217, 255, 0.14);
  color: #b9f4ff;
  border-color: rgba(31, 217, 255, 0.36);
}

.card {
  border: 1px solid var(--border-soft);
  border-radius: 14px;
  padding: 12px;
  background: linear-gradient(180deg, var(--bg-panel), #111725);
}

.card h2, .card h3 {
  margin-top: 0;
}

.param-note {
  font-size: 12px;
  color: var(--text-muted);
}

button.primary {
  background: linear-gradient(90deg, var(--accent-orange), var(--accent-amber)) !important;
  border: none !important;
  color: #151515 !important;
  font-weight: 800 !important;
}

button.secondary {
  background: linear-gradient(90deg, #27314a, #303c5b) !important;
  border: 1px solid #3e4d72 !important;
  color: #dce6ff !important;
}

textarea, input, .wrap {
  background: #0f1522 !important;
  border-color: #2d3851 !important;
}

.ops-strip {
  margin-top: 12px;
  border: 1px solid var(--border-soft);
  border-radius: 12px;
  padding: 10px;
  background: linear-gradient(90deg, #131a28, #171f2e);
}

.ops-title {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 8px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.ops-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.ops-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid var(--border-soft);
  background: #0f1624;
  font-size: 12px;
}

.ops-online {
  color: #7dffb2;
}

.ops-offline {
  color: #ff9b9b;
}

.ops-metric {
  color: #ffd7b5;
}
"""


def add_log(level: str, message: str):
    logs.append({
        "level": level,
        "message": message,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


current_summary_threshold = 100000


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
    pills: List[str] = []
    for name, online in statuses.items():
        state = "ONLINE" if online else "OFFLINE"
        cls = "ops-online" if online else "ops-offline"
        pills.append(f'<span class="ops-pill">{name}: <b class="{cls}">{state}</b></span>')

    pills.append(
        f'<span class="ops-pill">summary_threshold: <b class="ops-metric">{current_summary_threshold}</b></span>'
    )
    pills.append(
        f'<span class="ops-pill">active_sessions: <b class="ops-metric">{len(sessions)}</b></span>'
    )
    return (
        '<div class="ops-strip">'
        '<div class="ops-title">ОПЕРАЦИОННЫЙ СТАТУС</div>'
        f'<div class="ops-row">{"".join(pills)}</div>'
        "</div>"
    )


def refresh_operational_status() -> str:
    return render_operational_status_bar()


def update_summary_threshold(value: int) -> str:
    global current_summary_threshold
    current_summary_threshold = int(value)
    return render_operational_status_bar()


def ensure_local_no_proxy() -> None:
    bypass_values = ["localhost", "127.0.0.1", "::1"]
    for key in ("NO_PROXY", "no_proxy"):
        existing = os.getenv(key, "")
        parts = [x.strip() for x in existing.split(",") if x.strip()]
        for value in bypass_values:
            if value not in parts:
                parts.append(value)
        os.environ[key] = ",".join(parts)


def init_orchestrator() -> str:
    try:
        from host_orchestrator import ContextOrchestrator
        global orchestrator
        orchestrator = ContextOrchestrator()
        add_log("INFO", "Orchestrator initialized")
        return "Orchestrator initialized successfully"
    except Exception as e:
        add_log("ERROR", f"Orchestrator init failed: {str(e)}")
        return f"Error: {str(e)}"


def mask_pii_text(text: str, language: str = "ru") -> str:
    try:
        from pii_guard import get_pii_guard
        pii_guard = get_pii_guard()
        masked = pii_guard.mask(text, language=language)
        entities = pii_guard.analyze(text, language=language)

        result_text = f"Original: {text}\n\nMasked: {masked}\n\nFound {len(entities)} entities:\n"
        for e in entities:
            result_text += f"- {e.entity_type}: '{e.text}'\n"

        add_log("INFO", f"PII masked, found {len(entities)} entities")
        return result_text
    except Exception as e:
        add_log("ERROR", f"PII masking error: {str(e)}")
        return f"Error: {str(e)}"


def compress_context(threshold: int = 100000) -> str:
    add_log("INFO", f"Compression triggered with threshold {threshold}")
    return f"Context compressed with threshold: {threshold} tokens"


def create_checkpoint() -> str:
    checkpoint_id = f"ckpt_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    add_log("INFO", f"Checkpoint created: {checkpoint_id}")
    return f"Checkpoint created: {checkpoint_id}"


async def search_knowledge_async(domain: str, topic: str = "") -> str:
    try:
        from host_orchestrator import ContextOrchestrator

        orchestrator = ContextOrchestrator(
            enable_knowledge_bridge=True,
            enable_context7=False,
            enable_external_knowledge=False
        )
        await orchestrator.connect()
        try:
            if topic:
                result = await orchestrator.search_standard(domain, topic)
            else:
                domains = await orchestrator.list_knowledge_domains()
                result = f"Доступные домены: {', '.join(domains)}"
        finally:
            await orchestrator.disconnect()

        add_log("INFO", f"Knowledge search: {domain} - {topic}")
        return result
    except Exception as e:
        add_log("ERROR", f"Knowledge search error: {str(e)}")
        return f"Error: {str(e)}"


async def query_context7_async(library: str, query: str) -> str:
    client = None
    try:
        from context7_client import Context7Client

        client = Context7Client()
        await client.connect()
        if not client._connected:
            return "Error: Context7 connection failed"

        library_id = await client.resolve_library_id(library, query)

        if not library_id:
            return f"Library '{library}' not found in Context7"

        result = await client.query_docs(library_id, query, translate=False)

        if result["status"] == "success":
            content = result["content"]
            return f"=== Результат для {library} ===\n\n{content}"
        else:
            return f"Error: {result.get('error', 'Unknown error')}"

    except Exception as e:
        add_log("ERROR", f"Context7 query error: {str(e)}")
        return f"Error: {str(e)}\n\nNote: Ensure npx is installed and CONTEXT7_API_KEY is set in .env file."
    finally:
        if client:
            await client.disconnect()


def _to_optional_int(value: str) -> Optional[int]:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


async def external_search_async(
    query: str,
    domain: str = "python",
    library: str = "",
    repo: str = "",
    project_id: str = "",
    summary_mode: bool = True,
    summary_format: str = "Расширенная",
) -> tuple[str, str]:
    def _extract_summary_fields(result: Dict) -> Dict:
        chunks = result.get("chunks", [])
        shiva_chunks = [chunk for chunk in chunks if chunk.get("source") == "shiva"]
        if not shiva_chunks:
            return {"available": False}

        combined_text = "\n\n".join(str(chunk.get("content", "")) for chunk in shiva_chunks)

        total_tasks_values = [int(x) for x in TOTAL_TASKS_RE.findall(combined_text)]
        total_tasks = max(total_tasks_values) if total_tasks_values else None

        status_totals: Dict[str, int] = {}
        for status_name, tasks_count in STATUS_LINE_RE.findall(combined_text):
            normalized = status_name.strip()
            status_totals[normalized] = status_totals.get(normalized, 0) + int(tasks_count)

        project_id_match = PROJECT_ID_RE.search(combined_text)
        project = PROJECT_RE.search(combined_text)
        team = TEAM_RE.search(combined_text)
        leader = LEADER_RE.search(combined_text)
        objective = OBJECTIVE_RE.search(combined_text)
        description = DESCRIPTION_RE.search(combined_text)

        participants = []
        for participant_name, count in PARTICIPANT_RE.findall(combined_text):
            parsed_count = int(count)
            if parsed_count > 0:
                participants.append((participant_name.strip(), parsed_count))
        participants.sort(key=lambda x: x[1], reverse=True)
        return {
            "available": True,
            "total_tasks": total_tasks,
            "status_totals": status_totals,
            "project_id": int(project_id_match.group(1)) if project_id_match else _to_optional_int(project_id),
            "project": project.group(1).strip() if project else None,
            "team": team.group(1).strip() if team else None,
            "leader": leader.group(1).strip() if leader else None,
            "objective": " ".join(objective.group(1).strip().split()) if objective else None,
            "description": " ".join(description.group(1).strip().split()) if description else None,
            "participants": participants[:3],
        }

    def _extract_brief_summary(result: Dict) -> str:
        fields = _extract_summary_fields(result)
        if not fields.get("available"):
            return "Краткая сводка недоступна: в ответе нет данных SHIVA."

        total_tasks = fields.get("total_tasks")
        status_totals = fields.get("status_totals", {})
        lines = ["Краткая сводка (SHIVA):"]
        if total_tasks is not None:
            lines.append(f"- Всего задач: {total_tasks}")
        else:
            lines.append("- Всего задач: нет данных")

        if status_totals:
            preferred_order = ["Разработка", "Бэклог", "Тестирование", "Завершено"]
            ordered = []
            for key in preferred_order:
                if key in status_totals:
                    ordered.append((key, status_totals[key]))
            for key, value in status_totals.items():
                if key not in preferred_order:
                    ordered.append((key, value))
            statuses_text = "; ".join([f"{name} — {count}" for name, count in ordered])
            lines.append(f"- Статусы: {statuses_text}")
        else:
            lines.append("- Статусы: нет данных")

        key_points: List[str] = []
        if fields.get("project") and fields.get("team") and fields.get("leader"):
            key_points.append(
                f"Проект: {fields['project']}, команда: {fields['team']}, лидер: {fields['leader']}."
            )
        if fields.get("objective"):
            key_points.append(f"Цель: {fields['objective']}")
        if fields.get("description"):
            key_points.append(f"Описание: {fields['description']}")
        if fields.get("participants"):
            participants_text = ", ".join([f"{name} ({count})" for name, count in fields["participants"]])
            key_points.append(f"Топ-участники по задачам: {participants_text}.")
        key_points.append("Источник: SHIVA project summary + project overview.")

        lines.append("- Ключевые пункты:")
        for i, point in enumerate(key_points[:5], 1):
            lines.append(f"  {i}. {point}")
        return "\n".join(lines)

    def _extract_strict_shiva_summary(result: Dict) -> str:
        fields = _extract_summary_fields(result)
        if not fields.get("available"):
            return "Краткая сводка недоступна: в ответе нет данных SHIVA."

        project_name = fields.get("project") or "Data Science"
        project_id_value = fields.get("project_id")
        total_tasks = fields.get("total_tasks")
        status_totals = fields.get("status_totals", {})

        lines: List[str] = []
        if project_id_value is not None:
            lines.append(f"Кратко по {project_name} (project {project_id_value}):")
        else:
            lines.append(f"Кратко по {project_name}:")

        if total_tasks is not None:
            lines.append(f"Всего задач: {total_tasks}")
        else:
            lines.append("Всего задач: нет данных")

        preferred_order = ["Разработка", "Бэклог", "Тестирование", "Завершено"]
        status_lines = []
        for key in preferred_order:
            if key in status_totals:
                status_lines.append(f"{key} — {status_totals[key]}")

        if not status_lines:
            status_lines.append("Статусы: нет данных")

        for item in status_lines[:4]:
            lines.append(item)

        # Строгий формат: 4-6 строк
        return "\n".join(lines[:6])

    try:
        from host_orchestrator import ContextOrchestrator

        orchestrator = ContextOrchestrator(
            enable_knowledge_bridge=True,
            enable_context7=True,
            enable_external_knowledge=True
        )
        await orchestrator.connect()
        try:
            result = await orchestrator.external_search(
                query=query,
                domain=domain or "python",
                library=library.strip() or None,
                repo=repo.strip() or None,
                project_id=_to_optional_int(project_id),
                limit=5,
            )
            add_log(
                "INFO",
                f"External search: domain={domain}, query={query[:80]}, project_id={project_id or 'none'}"
            )
            raw_json = json.dumps(result, ensure_ascii=False, indent=2)
            if summary_mode:
                if summary_format == "Строго как @shiva":
                    summary_text = _extract_strict_shiva_summary(result)
                else:
                    summary_text = _extract_brief_summary(result)
            else:
                summary_text = "Краткая сводка отключена."
            return summary_text, raw_json
        finally:
            await orchestrator.disconnect()
    except Exception as e:
        add_log("ERROR", f"External search error: {str(e)}")
        error_text = f"Error: {str(e)}"
        return error_text, error_text


def get_stats_text() -> str:
    active_count = len(sessions)
    log_count = len(logs)
    return f"""Session ID: demo_session
Context History Length: 0 messages
Compression Count: 0
Max Tokens: 128000
Summary Threshold: 100000
Connected: True
Active Sessions: {active_count}
Total Logs: {log_count}"""


def get_logs_text() -> str:
    if not logs:
        return "No logs available"

    result = "=== Recent Logs ===\n\n"
    for log in logs[-20:]:
        result += f"[{log['timestamp']}] {log['level']}: {log['message']}\n"
    return result


def create_session(name: str = "") -> str:
    session_id = f"sess_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    sessions[session_id] = {
        "name": name or f"Session {session_id}",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "messages": [],
        "tokens": 0
    }
    add_log("INFO", f"Session created: {session_id}")
    return f"Session '{name}' created with ID: {session_id}"


def list_sessions() -> str:
    if not sessions:
        return "No active sessions"

    result = "=== Active Sessions ===\n\n"
    for sid, data in sessions.items():
        result += f"ID: {sid}\nName: {data['name']}\nCreated: {data['created_at']}\nMessages: {len(data['messages'])}\n\n"
    return result


def delete_session(session_id: str) -> str:
    if session_id not in sessions:
        return f"Session {session_id} not found"

    name = sessions[session_id]["name"]
    del sessions[session_id]
    add_log("INFO", f"Session deleted: {session_id}")
    return f"Session '{name}' deleted successfully"


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


with gr.Blocks(title="MCP Context Pipeline Console") as demo:
    gr.Markdown(
        """
<div class="app-hero">
  <p class="hero-title">MCP Context Pipeline Console</p>
  <p class="hero-subtitle">Тёмная операционная панель для управления контекстом, PII-защитой и внешними источниками знаний.</p>
  <div class="badge-row">
    <span class="badge badge-orange">Context Compression</span>
    <span class="badge badge-cyan">PII Guard</span>
    <span class="badge badge-orange">Knowledge Bridge</span>
    <span class="badge badge-cyan">Context7 + External Router</span>
  </div>
</div>
"""
    )
    with gr.Row():
        status_bar = gr.HTML(value=render_operational_status_bar())
        refresh_status_btn = gr.Button("Обновить операционный статус", size="sm", variant="secondary")

    with gr.Tabs():
        with gr.Tab("Операции"):
            with gr.Row():
                with gr.Column(scale=2, elem_classes="card"):
                    gr.Markdown("### Инициализация и состояние")
                    init_btn = gr.Button("Инициализировать Orchestrator", variant="primary")
                    init_output = gr.Textbox(label="Статус", interactive=False)
                    stats_text = gr.Textbox(
                        label="Статистика",
                        value="Нажмите кнопку для получения статистики",
                        lines=8,
                        interactive=False
                    )
                    refresh_stats_btn = gr.Button("Обновить статистику", size="sm")

                with gr.Column(scale=1, elem_classes="card"):
                    gr.Markdown("### Быстрые действия")
                    gr.Markdown(
                        '<div class="param-note">Порог сжатия влияет на момент активации компрессии контекста.</div>'
                    )
                    compress_threshold = gr.Slider(50000, 128000, value=100000, label="Порог сжатия (токены)")
                    with gr.Row():
                        compress_btn = gr.Button("Сжать контекст", variant="secondary")
                        checkpoint_btn = gr.Button("Создать чекпоинт", variant="secondary")
                    quick_action_output = gr.Textbox(label="Результат действия", lines=3, interactive=False)

            with gr.Row():
                with gr.Column(scale=1, elem_classes="card"):
                    gr.Markdown("## PII Маскирование")
                    gr.Markdown("Автоматическое маскирование персональных данных с помощью Microsoft Presidio.")
                    pii_input = gr.Textbox(label="Текст для маскирования", lines=4, placeholder="Введите текст с персональными данными...")
                    pii_language = gr.Radio(["ru", "en"], value="ru", label="Язык")
                    pii_btn = gr.Button("Маскировать PII", variant="primary")
                    pii_output = gr.Textbox(label="Результат маскирования", lines=8, interactive=False)

                with gr.Column(scale=1, elem_classes="card"):
                    gr.Markdown("## Knowledge Bridge")
                    gr.Markdown("Поиск по доменным знаниям и документации библиотек.")
                    kb_domain = gr.Dropdown(
                        ["api", "security", "db", "python", "deployment"],
                        value="api",
                        label="Домен"
                    )
                    kb_topic = gr.Textbox(label="Тема (опционально)", placeholder="Например: pagination")
                    kb_btn = gr.Button("Поиск в Knowledge Bridge", variant="secondary")
                    kb_output = gr.Textbox(label="Результаты поиска", lines=6, interactive=False)

                    gr.Markdown("### Context7 Документация")
                    ctx7_library = gr.Dropdown(
                        ["torch", "transformers", "fastapi", "anthropic", "openai", "redis", "postgresql"],
                        value="torch",
                        label="Библиотека"
                    )
                    ctx7_query = gr.Textbox(label="Запрос документации", placeholder="Например: tensor operations")
                    ctx7_btn = gr.Button("Запросить документацию", variant="secondary")
                    ctx7_output = gr.Textbox(label="Результаты запроса", lines=6, interactive=False)

            with gr.Row():
                with gr.Column(elem_classes="card"):
                    gr.Markdown("## External Knowledge Router (SHIVA/DocFusion)")
                    gr.Markdown(
                        '<div class="param-note">Сценарий похож на этапы Text2Image: сначала задаются параметры качества/формата, затем выполняется запрос и анализ результата.</div>'
                    )
                    ext_query = gr.Textbox(
                        label="Запрос",
                        placeholder="Например: Покажи сводку по проекту Data Science и статус спринта",
                    )
                    with gr.Row():
                        ext_domain = gr.Dropdown(
                            ["python", "api", "security", "db", "deployment", "project", "docs"],
                            value="python",
                            label="Домен"
                        )
                        ext_library = gr.Textbox(label="Library (опционально)", placeholder="Например: fastapi")
                    with gr.Row():
                        ext_repo = gr.Textbox(label="GitHub repo (опционально)", placeholder="owner/repo")
                        ext_project_id = gr.Textbox(label="SHIVA project_id (опционально)", placeholder="Например: 44")
                    ext_summary_mode = gr.Checkbox(
                        value=True,
                        label="Режим: краткая сводка поверх JSON"
                    )
                    ext_summary_format = gr.Radio(
                        ["Расширенная", "Строго как @shiva"],
                        value="Строго как @shiva",
                        label="Формат сводки"
                    )
                    ext_btn = gr.Button("Выполнить внешний поиск", variant="primary")
                    ext_summary_output = gr.Textbox(label="Краткая сводка", lines=10, interactive=False)
                    ext_output = gr.Textbox(label="Сырой JSON external_search", lines=10, interactive=False)

        with gr.Tab("Сессии и Логи"):
            with gr.Row():
                with gr.Column(elem_classes="card"):
                    gr.Markdown("## Управление сессиями")
                    session_name = gr.Textbox(label="Имя сессии", placeholder="Введите имя...")
                    create_session_btn = gr.Button("Создать сессию", variant="primary")
                    session_output = gr.Textbox(label="Результат", lines=2, interactive=False)

                    with gr.Row():
                        list_sessions_btn = gr.Button("Список сессий", size="sm")
                        delete_session_input = gr.Textbox(label="ID сессии для удаления", placeholder="sess_...")
                        delete_session_btn = gr.Button("Удалить сессию", variant="stop", size="sm")

                    sessions_output = gr.Textbox(label="Активные сессии", lines=8, interactive=False)

                with gr.Column(elem_classes="card"):
                    gr.Markdown("## Системные логи")
                    refresh_logs_btn = gr.Button("Обновить логи", size="sm")
                    logs_output = gr.Textbox(label="", value="Логи будут отображаться здесь...", lines=12, interactive=False)

    gr.Markdown("**MCP Context Pipeline** — визуальная консоль управления контекстом, PII и внешним знанием.")

    init_btn.click(init_orchestrator, outputs=init_output)

    refresh_stats_btn.click(get_stats_text, outputs=stats_text)

    compress_btn.click(compress_context, inputs=[compress_threshold], outputs=quick_action_output)
    checkpoint_btn.click(create_checkpoint, outputs=quick_action_output)

    pii_btn.click(mask_pii_text, inputs=[pii_input, pii_language], outputs=pii_output)

    kb_btn.click(lambda d, t: run_async(search_knowledge_async(d, t)), inputs=[kb_domain, kb_topic], outputs=kb_output)
    ctx7_btn.click(lambda lib, q: run_async(query_context7_async(lib, q)), inputs=[ctx7_library, ctx7_query], outputs=ctx7_output)
    ext_btn.click(
        lambda q, d, l, r, p, s, f: run_async(external_search_async(q, d, l, r, p, s, f)),
        inputs=[ext_query, ext_domain, ext_library, ext_repo, ext_project_id, ext_summary_mode, ext_summary_format],
        outputs=[ext_summary_output, ext_output]
    )

    create_session_btn.click(create_session, inputs=[session_name], outputs=session_output)
    list_sessions_btn.click(list_sessions, outputs=sessions_output)
    delete_session_btn.click(delete_session, inputs=[delete_session_input], outputs=session_output)

    refresh_logs_btn.click(get_logs_text, outputs=logs_output)
    refresh_status_btn.click(refresh_operational_status, outputs=status_bar)
    compress_threshold.change(update_summary_threshold, inputs=[compress_threshold], outputs=status_bar)
    create_session_btn.click(refresh_operational_status, outputs=status_bar)
    delete_session_btn.click(refresh_operational_status, outputs=status_bar)
    demo.load(refresh_operational_status, outputs=status_bar)


if __name__ == "__main__":
    ensure_local_no_proxy()
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False, css=APP_CSS)
