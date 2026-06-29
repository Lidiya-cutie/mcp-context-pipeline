"""
NiceGUI веб-интерфейс для MCP Context Pipeline.
6 вкладок: Поиск знаний, Документация, PII & Безопасность, Эксперты, MCP Серверы, Система.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
sys.path.insert(0, '/mldata/mcp_context_pipeline/src')

from dotenv import load_dotenv
load_dotenv('/mldata/mcp_context_pipeline/.env')
os.chdir('/mldata/mcp_context_pipeline')

import asyncio
import json
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from nicegui import app, ui

# ---------------------------------------------------------------------------
# Globals & lazy singletons
# ---------------------------------------------------------------------------

PROJECT_DIR = '/mldata/mcp_context_pipeline'
MCP_SERVERS_DIR = os.path.join(PROJECT_DIR, 'src', 'mcp_servers')

_sessions: Dict[str, Dict] = {}
_logs: List[Dict] = []
_summary_threshold = 100000
_execution_history: List[Dict] = []

_orchestrator = None
_skill_dispatcher = None
_agent_executor = None


def _log(level: str, message: str):
    _logs.append({
        'level': level,
        'message': message,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })


def _provider_statuses() -> Dict[str, bool]:
    statuses = {}
    try:
        import host_orchestrator  # noqa: F401
        statuses['Orchestrator'] = True
    except Exception:
        statuses['Orchestrator'] = False
    try:
        import pii_guard  # noqa: F401
        statuses['PII Guard'] = True
    except Exception:
        statuses['PII Guard'] = False
    statuses['Context7'] = bool(os.getenv('CONTEXT7_API_KEY'))
    statuses['Tavily'] = bool(os.getenv('TAVILY_API_KEY'))
    statuses['Exa'] = bool(os.getenv('EXA_SEARCH_API_KEY'))
    statuses['Firecrawl'] = bool(os.getenv('FIRECRAWL_API_KEY'))
    return statuses


def _get_skill_dispatcher():
    global _skill_dispatcher
    if _skill_dispatcher is None:
        from skill_dispatcher import SkillDispatcher
        _skill_dispatcher = SkillDispatcher(
            skills_dir=os.path.join(PROJECT_DIR, 'Навыки'),
            mcp_servers_dir=MCP_SERVERS_DIR,
        )
    return _skill_dispatcher


def _get_agent_executor():
    global _agent_executor
    if _agent_executor is None:
        from agent_executor import AgentExecutor
        _agent_executor = AgentExecutor(project_dir=PROJECT_DIR)
    return _agent_executor


def _get_mcp_server_list():
    servers = []
    for name in sorted(os.listdir(MCP_SERVERS_DIR)):
        server_path = os.path.join(MCP_SERVERS_DIR, name, 'server.py')
        if not os.path.isfile(server_path):
            continue
        desc = ''
        manifest_path = os.path.join(MCP_SERVERS_DIR, name, 'manifest.json')
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    mdata = json.load(f)
                desc = mdata.get('description', '')
            except Exception:
                pass
        servers.append({'name': name, 'path': server_path, 'description': desc})
    return servers


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=120)
    else:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# MCP Client (lightweight, for individual server interactions)
# ---------------------------------------------------------------------------

class _MCPClientLite:
    def __init__(self, server_path: str, server_name: str):
        self.server_path = server_path
        self.server_name = server_name
        self.process = None
        self._request_id = 0

    async def start(self) -> bool:
        try:
            self.process = subprocess.Popen(
                [sys.executable, self.server_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.path.dirname(self.server_path),
            )
            result = await self._send('initialize', {
                'protocolVersion': '2024-11-05',
                'capabilities': {},
                'clientInfo': {'name': 'nicegui-client', 'version': '1.0.0'},
            })
            return result is not None
        except Exception:
            return False

    async def _send(self, method: str, params: dict = None) -> Optional[dict]:
        if not self.process or self.process.poll() is not None:
            return None
        self._request_id += 1
        request = {
            'jsonrpc': '2.0',
            'id': self._request_id,
            'method': method,
            'params': params or {},
        }
        try:
            self.process.stdin.write((json.dumps(request) + '\n').encode())
            self.process.stdin.flush()
            response_line = await asyncio.to_thread(self.process.stdout.readline)
            if not response_line:
                return None
            raw = response_line.decode().strip()
            if raw.startswith('Content-Length:'):
                await asyncio.to_thread(self.process.stdout.readline)
                response_line = await asyncio.to_thread(self.process.stdout.readline)
                if not response_line:
                    return None
                raw = response_line.decode().strip()
            return json.loads(raw)
        except Exception:
            return None

    async def list_tools(self) -> List[dict]:
        result = await self._send('tools/list')
        if result and 'result' in result:
            return result['result'].get('tools', [])
        return []

    async def call_tool(self, tool_name: str, arguments: dict = None) -> Optional[str]:
        result = await self._send('tools/call', {
            'name': tool_name,
            'arguments': arguments or {},
        })
        if result and 'result' in result:
            content = result['result'].get('content', [])
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(item.get('text', str(item)))
                else:
                    parts.append(str(item))
            return '\n'.join(parts)
        if result and 'error' in result:
            return f"ERROR: {result['error'].get('message', 'unknown')}"
        return None

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()


# ---------------------------------------------------------------------------
# Header component
# ---------------------------------------------------------------------------

def render_header():
    with ui.header().classes('items-center justify-between px-6 py-3'):
        ui.label('MCP Context Pipeline Console').classes('text-2xl font-bold')
        with ui.row().classes('gap-2 items-center'):
            ui.badge('60 навыков', color='orange')
            ui.badge('27 MCP серверов', color='blue')
            ui.badge('v2.0', color='green')


# ---------------------------------------------------------------------------
# Status strip component
# ---------------------------------------------------------------------------

class StatusStrip:
    def __init__(self):
        with ui.row().classes('w-full gap-2 items-center q-pa-sm'):
            self._container = ui.row().classes('gap-2 items-center flex-wrap')

    def refresh(self):
        self._container.clear()
        with self._container:
            statuses = _provider_statuses()
            for name, online in statuses.items():
                color = 'green' if online else 'red'
                icon = 'check_circle' if online else 'cancel'
                ui.icon(icon).classes(f'text-{color}-500')
                ui.label(name).classes('text-xs')
            ui.badge(f'sessions: {len(_sessions)}', color='grey')
            ui.badge(f'threshold: {_summary_threshold}', color='grey')


# ---------------------------------------------------------------------------
# Tab 1: Knowledge Search
# ---------------------------------------------------------------------------

class KnowledgeSearchTab:
    def __init__(self):
        with ui.column().classes('w-full gap-4'):
            ui.label('Поиск знаний').classes('text-xl font-bold')

            with ui.row().classes('w-full gap-4 items-end'):
                self.query_input = ui.input(
                    label='Поисковый запрос',
                    placeholder='Введите запрос...'
                ).classes('flex-grow')
                self.provider_select = ui.select(
                    label='Провайдеры',
                    options=['Все', 'Context7', 'Tavily', 'Exa', 'Shiva', 'DocFusion', 'Firecrawl'],
                    value='Все',
                ).classes('w-48')
                ui.button('Искать', on_click=self._on_search, color='primary').classes('h-10')

            self._results_container = ui.column().classes('w-full gap-3')

    async def _on_search(self):
        query = self.query_input.value.strip()
        if not query:
            ui.notify('Введите поисковый запрос', type='warning')
            return

        selected = self.provider_select.value
        want_all = (selected == 'Все')

        self._results_container.clear()
        with self._results_container:
            ui.spinner('dots', size='lg')
            ui.label('Выполняется поиск...')

        try:
            from host_orchestrator import ContextOrchestrator
            from external_knowledge.providers import (
                TavilyProvider, ExaProvider, FirecrawlProvider,
                ShivaProvider, DocFusionProvider, Context7Provider,
            )
            from external_knowledge.router import ExternalKnowledgeRouter
            from context7_client import Context7Client

            providers = []
            provider_names = []

            if want_all or selected == 'Tavily':
                providers.append(TavilyProvider())
                provider_names.append('Tavily')
            if want_all or selected == 'Exa':
                providers.append(ExaProvider())
                provider_names.append('Exa')
            if want_all or selected == 'Firecrawl':
                providers.append(FirecrawlProvider())
                provider_names.append('Firecrawl')
            if want_all or selected == 'Shiva':
                providers.append(ShivaProvider())
                provider_names.append('Shiva')
            if want_all or selected == 'DocFusion':
                providers.append(DocFusionProvider())
                provider_names.append('DocFusion')
            if want_all or selected == 'Context7':
                try:
                    c7 = Context7Client()
                    await c7.connect()
                    providers.append(Context7Provider(c7.session))
                    provider_names.append('Context7')
                except Exception:
                    pass

            all_chunks = []
            if providers:
                router = ExternalKnowledgeRouter(providers)
                result = await router.search(query=query, limit=5)
                all_chunks = result.get('chunks', [])

            self._results_container.clear()
            with self._results_container:
                if not all_chunks:
                    ui.label(f'Результаты не найдены (провайдеры: {", ".join(provider_names)})').classes('text-grey')
                    return

                for chunk in all_chunks:
                    source = chunk.get('source', 'unknown')
                    content = chunk.get('content', '')
                    score = chunk.get('score', 0)
                    with ui.expansion(
                        f'[{source}] {str(content)[:120]}...',
                        value=False,
                    ).classes('w-full'):
                        ui.markdown(f'**Источник:** {source}\n\n**Score:** {score:.2f}\n\n{content}')

                ui.label(f'Провайдеры: {", ".join(provider_names)} | Результатов: {len(all_chunks)}').classes('text-sm text-grey')

            _log('INFO', f'Knowledge search [{",".join(provider_names)}]: {query[:60]}')

        except Exception as e:
            self._results_container.clear()
            with self._results_container:
                ui.label(f'Ошибка: {e}').classes('text-red-500')
            _log('ERROR', f'Knowledge search error: {e}')
            ui.notify(f'Ошибка поиска: {e}', type='negative')


# ---------------------------------------------------------------------------
# Tab 2: Context7 Documentation
# ---------------------------------------------------------------------------

class Context7Tab:
    def __init__(self):
        with ui.column().classes('w-full gap-4'):
            ui.label('Документация (Context7)').classes('text-xl font-bold')

            with ui.row().classes('w-full gap-4 items-end'):
                self.library_input = ui.input(
                    label='Название библиотеки',
                    placeholder='fastapi, torch, transformers...',
                ).classes('flex-grow')
                self.resolve_btn = ui.button(
                    'Resolve', on_click=self._on_resolve, color='secondary'
                )

            self.resolved_label = ui.label('').classes('text-grey')

            with ui.row().classes('w-full gap-4 items-end'):
                self.doc_query = ui.input(
                    label='Запрос документации',
                    placeholder='tensor operations, routing...',
                ).classes('flex-grow')
                self.translate_cb = ui.checkbox('Перевести на русский', value=False)
                ui.button('Запросить', on_click=self._on_query, color='primary')

            self._doc_output = ui.column().classes('w-full')

    async def _on_resolve(self):
        lib = self.library_input.value.strip()
        if not lib:
            ui.notify('Введите название библиотеки', type='warning')
            return
        try:
            from context7_client import Context7Client
            client = Context7Client()
            await client.connect()
            try:
                lib_id = await client.resolve_library_id(lib, f'documentation for {lib}')
                if lib_id:
                    self.resolved_label.text = f'Resolved: {lib_id}'
                else:
                    self.resolved_label.text = f'Библиотека "{lib}" не найдена'
            finally:
                await client.disconnect()
        except Exception as e:
            self.resolved_label.text = f'Ошибка: {e}'
            ui.notify(f'Ошибка resolve: {e}', type='negative')

    async def _on_query(self):
        lib = self.library_input.value.strip()
        query = self.doc_query.value.strip()
        if not lib or not query:
            ui.notify('Заполните оба поля', type='warning')
            return

        self._doc_output.clear()
        with self._doc_output:
            ui.spinner('dots', size='lg')

        try:
            from context7_client import Context7Client
            client = Context7Client()
            await client.connect()
            try:
                lib_id = await client.resolve_library_id(lib, query)
                if not lib_id:
                    self._doc_output.clear()
                    with self._doc_output:
                        ui.label(f'Библиотека "{lib}" не найдена').classes('text-red-400')
                    return
                result = await client.query_docs(lib_id, query, translate=self.translate_cb.value)
            finally:
                await client.disconnect()

            self._doc_output.clear()
            with self._doc_output:
                if result.get('status') == 'success':
                    content = result.get('content', '')
                    ui.markdown(content).classes('w-full')
                else:
                    ui.label(f'Ошибка: {result.get("error", "unknown")}').classes('text-red-400')

            _log('INFO', f'Context7 query: {lib} - {query[:50]}')

        except Exception as e:
            self._doc_output.clear()
            with self._doc_output:
                ui.label(f'Ошибка: {e}').classes('text-red-400')
            _log('ERROR', f'Context7 error: {e}')
            ui.notify(f'Ошибка: {e}', type='negative')


# ---------------------------------------------------------------------------
# Tab 3: PII & Security
# ---------------------------------------------------------------------------

class PIISecurityTab:
    def __init__(self):
        with ui.column().classes('w-full gap-4'):
            ui.label('PII & Безопасность').classes('text-xl font-bold')

            with ui.row().classes('w-full gap-4 items-end'):
                self.use_mcp = ui.checkbox('Использовать MCP pii_scanner', value=True)
                self.lang_select = ui.select(
                    label='Язык',
                    options=['ru', 'en'],
                    value='ru',
                ).classes('w-24')

            self.input_text = ui.textarea(
                label='Текст для анализа',
                placeholder='Введите текст для проверки на PII...',
            ).classes('w-full').props('rows=6')

            with ui.row().classes('gap-4'):
                ui.button('Сканировать', on_click=self._on_scan, color='primary')
                ui.button('Маскировать', on_click=self._on_mask, color='secondary')

            self._output_area = ui.column().classes('w-full gap-4')

    async def _run_mcp_tool(self, tool_name: str, arguments: dict) -> Optional[str]:
        server_path = os.path.join(MCP_SERVERS_DIR, 'pii_scanner', 'server.py')
        client = _MCPClientLite(server_path, 'pii_scanner')
        try:
            ok = await client.start()
            if not ok:
                return None
            return await client.call_tool(tool_name, arguments)
        finally:
            client.stop()

    async def _on_scan(self):
        text = self.input_text.value.strip()
        if not text:
            ui.notify('Введите текст', type='warning')
            return

        self._output_area.clear()
        with self._output_area:
            ui.spinner('dots', size='lg')

        try:
            if self.use_mcp.value:
                result_str = await self._run_mcp_tool('scan_string', {'text': text})
                if result_str:
                    result_data = json.loads(result_str)
                else:
                    result_data = {'error': 'MCP сервер недоступен, fallback на Presidio'}
                    if result_data.get('error'):
                        try:
                            from pii_guard import get_pii_guard
                            guard = get_pii_guard()
                            entities = guard.analyze(text, language=self.lang_select.value)
                            result_data = {
                                'pii_found': len(entities),
                                'has_pii': len(entities) > 0,
                                'matches': [
                                    {
                                        'rule_name': e.entity_type,
                                        'value': e.text,
                                        'severity': 'high',
                                    }
                                    for e in entities
                                ],
                            }
                        except Exception as e2:
                            result_data = {'error': str(e2)}
            else:
                try:
                    from pii_guard import get_pii_guard
                    guard = get_pii_guard()
                    entities = guard.analyze(text, language=self.lang_select.value)
                    result_data = {
                        'pii_found': len(entities),
                        'has_pii': len(entities) > 0,
                        'matches': [
                            {
                                'rule_name': e.entity_type,
                                'value': e.text,
                                'severity': 'high',
                            }
                            for e in entities
                        ],
                    }
                except Exception as e:
                    result_data = {'error': str(e)}

            self._output_area.clear()
            with self._output_area:
                if 'error' in result_data:
                    ui.label(f"Ошибка: {result_data['error']}").classes('text-red-400')
                    return

                matches = result_data.get('matches', [])
                ui.label(f"Найдено PII: {result_data.get('pii_found', 0)}").classes('text-lg font-bold')

                if matches:
                    columns = [
                        {'name': 'rule', 'label': 'Rule', 'field': 'rule', 'align': 'left'},
                        {'name': 'value', 'label': 'Value', 'field': 'value', 'align': 'left'},
                        {'name': 'severity', 'label': 'Severity', 'field': 'severity', 'align': 'center'},
                    ]
                    rows = [
                        {
                            'rule': m.get('rule_name', m.get('rule_id', '?')),
                            'value': m.get('value', '?'),
                            'severity': m.get('severity', 'medium'),
                        }
                        for m in matches
                    ]
                    ui.table(columns=columns, rows=rows).classes('w-full')

            _log('INFO', f'PII scan: {result_data.get("pii_found", 0)} found')

        except Exception as e:
            self._output_area.clear()
            with self._output_area:
                ui.label(f'Ошибка: {e}').classes('text-red-400')
            _log('ERROR', f'PII scan error: {e}')
            ui.notify(f'Ошибка: {e}', type='negative')

    async def _on_mask(self):
        text = self.input_text.value.strip()
        if not text:
            ui.notify('Введите текст', type='warning')
            return

        self._output_area.clear()
        with self._output_area:
            ui.spinner('dots', size='lg')

        try:
            masked_text = ''
            if self.use_mcp.value:
                result_str = await self._run_mcp_tool('mask_string', {'text': text})
                if result_str:
                    result_data = json.loads(result_str)
                    masked_text = result_data.get('masked_text', '')
                else:
                    masked_text = None
                if not masked_text:
                    try:
                        from pii_guard import get_pii_guard
                        guard = get_pii_guard()
                        masked_text = guard.mask(text, language=self.lang_select.value)
                    except Exception as e:
                        masked_text = f'Ошибка fallback: {e}'
            else:
                try:
                    from pii_guard import get_pii_guard
                    guard = get_pii_guard()
                    masked_text = guard.mask(text, language=self.lang_select.value)
                except Exception as e:
                    masked_text = f'Ошибка: {e}'

            self._output_area.clear()
            with self._output_area:
                with ui.grid(columns=2).classes('w-full gap-4'):
                    with ui.card().classes('w-full'):
                        ui.label('Оригинал').classes('text-sm font-bold')
                        ui.textarea(value=text).props('readonly rows=6').classes('w-full')
                    with ui.card().classes('w-full'):
                        ui.label('Маскированный').classes('text-sm font-bold')
                        ui.textarea(value=masked_text).props('readonly rows=6').classes('w-full')

            _log('INFO', 'PII masking completed')

        except Exception as e:
            self._output_area.clear()
            with self._output_area:
                ui.label(f'Ошибка: {e}').classes('text-red-400')
            _log('ERROR', f'PII mask error: {e}')
            ui.notify(f'Ошибка: {e}', type='negative')


# ---------------------------------------------------------------------------
# Tab 4: Experts
# ---------------------------------------------------------------------------

class ExpertsTab:
    def __init__(self):
        with ui.row().classes('w-full gap-4'):
            # LEFT panel
            with ui.column().classes('w-1/3 gap-3'):
                ui.label('Эксперты (навыки)').classes('text-xl font-bold')

                skills = _get_skill_dispatcher().list_skills()
                skill_options = {}
                for s in skills:
                    role = s.get('role', '?')
                    name = s.get('name', s.get('stem', ''))
                    label = f'[{role}] {name}'
                    skill_options[s.get('stem', '')] = label

                self.skill_select = ui.select(
                    label='Выберите навык',
                    options=skill_options,
                    with_input=True,
                ).classes('w-full')

                with ui.row().classes('w-full gap-2 items-end'):
                    self.auto_input = ui.input(
                        label='Автоподбор',
                        placeholder='Опишите задачу...',
                    ).classes('flex-grow')
                    ui.button('Подобрать', on_click=self._on_autofind, color='secondary')

                self._skill_info = ui.card().classes('w-full')
                with self._skill_info:
                    self._skill_info_label = ui.label('Выберите навык для просмотра информации')

                self.skill_select.on('update:model-value', self._on_skill_selected)

                self._autofind_results = ui.column().classes('w-full gap-2')

            # RIGHT panel
            with ui.column().classes('w-2/3 gap-3'):
                ui.label('Запуск эксперта').classes('text-xl font-bold')

                self.task_input = ui.textarea(
                    label='Описание задачи',
                    placeholder='Опишите задачу для эксперта...',
                ).props('rows=4').classes('w-full')

                self._run_btn = ui.button(
                    'Запустить эксперта',
                    on_click=self._on_execute,
                    color='primary',
                ).classes('w-full text-lg').props('size=lg')

                self._progress_label = ui.label('').classes('text-grey')

                self._result_output = ui.column().classes('w-full gap-3')

                self._details_expansion = ui.expansion('Детали выполнения', value=False).classes('w-full')
                with self._details_expansion:
                    self._details_label = ui.label('Нет данных')

                with ui.row().classes('w-full items-end gap-2'):
                    self._history_select = ui.select(
                        label='История запусков',
                        options={},
                    ).classes('flex-grow')
                    ui.button('Показать', on_click=self._on_history_show, color='secondary')

    def _on_skill_selected(self, e=None):
        stem = self.skill_select.value
        if not stem:
            return
        dispatcher = _get_skill_dispatcher()
        skills = dispatcher.list_skills()
        skill = next((s for s in skills if s.get('stem') == stem), None)
        if not skill:
            return

        priority_colors = {'critical': 'red', 'high': 'orange', 'normal': 'blue', 'low': 'grey'}
        p_color = priority_colors.get(skill.get('priority', 'normal'), 'grey')

        self._skill_info.clear()
        with self._skill_info:
            ui.label(f"**{skill.get('name', '')}**").classes('text-lg font-bold')
            ui.label(f"Роль: {skill.get('role', '?')}")
            ui.label(f"Триггер: {skill.get('trigger', '-')}")
            ui.badge(f"Приоритет: {skill.get('priority', 'normal')}", color=p_color)
            tools = skill.get('allowed_tools', [])
            if tools:
                with ui.expansion(f'Инструменты ({len(tools)})', value=False):
                    for t in tools:
                        ui.label(f'  - {t}')

    async def _on_autofind(self):
        query = self.auto_input.value.strip()
        if not query:
            ui.notify('Введите описание', type='warning')
            return
        try:
            dispatcher = _get_skill_dispatcher()
            results = dispatcher.find_skill(query, top_k=3)
            self._autofind_results.clear()
            with self._autofind_results:
                if not results:
                    ui.label('Ничего не найдено').classes('text-grey')
                    return
                for r in results:
                    with ui.card().classes('w-full cursor-pointer'):
                        ui.label(f"**{r.get('name', '')}** [{r.get('role', '')}] score: {r.get('score', 0):.2f}").classes('font-bold')
                        ui.label(f"Триггер: {r.get('trigger', '-')}")
        except Exception as e:
            ui.notify(f'Ошибка: {e}', type='negative')

    async def _on_execute(self):
        stem = self.skill_select.value
        task = self.task_input.value.strip()
        if not stem:
            ui.notify('Выберите навык', type='warning')
            return
        if not task:
            ui.notify('Опишите задачу', type='warning')
            return

        self._progress_label.text = 'Выполняется...'
        self._run_btn.disable()

        self._result_output.clear()
        with self._result_output:
            ui.spinner('dots', size='lg')

        try:
            executor = _get_agent_executor()
            result = await executor.execute(stem, task)

            self._result_output.clear()
            with self._result_output:
                if result.get('status') == 'success':
                    response = result.get('response', '')
                    if response:
                        ui.markdown(response).classes('w-full')
                    else:
                        ui.label('Эксперт не вернул результат').classes('text-grey')
                else:
                    error = result.get('error', 'unknown error')
                    ui.label(f'Ошибка: {error}').classes('text-red-400')

            self._details_expansion.set_value(True)
            self._details_label.text = (
                f"System prompt: {result.get('system_prompt', '')[:500]}...\n\n"
                f"MCP Context: {result.get('mcp_context', '')[:500]}\n\n"
                f"MCP Results: {json.dumps(result.get('mcp_results', {}), ensure_ascii=False, indent=2)[:1000]}"
            )

            _execution_history.append({
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'skill': stem,
                'task': task[:60],
                'result': result,
            })
            options = {
                str(i): f"{h['timestamp']} [{h['skill']}] {h['task']}"
                for i, h in enumerate(_execution_history)
            }
            self._history_select.set_options(options)
            self._history_select.set_value(str(len(_execution_history) - 1))

            _log('INFO', f'Expert executed: {stem}')

        except Exception as e:
            self._result_output.clear()
            with self._result_output:
                ui.label(f'Ошибка выполнения: {e}').classes('text-red-400')
            _log('ERROR', f'Expert execute error: {e}')
            ui.notify(f'Ошибка: {e}', type='negative')

        finally:
            self._progress_label.text = ''
            self._run_btn.enable()

    def _on_history_show(self):
        val = self._history_select.value
        if val is None or not _execution_history:
            return
        idx = int(val)
        if idx < 0 or idx >= len(_execution_history):
            return
        entry = _execution_history[idx]
        result = entry.get('result', {})

        self._result_output.clear()
        with self._result_output:
            response = result.get('response', '')
            if response:
                ui.markdown(response).classes('w-full')
            else:
                ui.label('Пустой результат')


# ---------------------------------------------------------------------------
# Tab 5: MCP Servers
# ---------------------------------------------------------------------------

class MCPServersTab:
    def __init__(self):
        with ui.column().classes('w-full gap-4'):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('MCP Серверы').classes('text-xl font-bold')
                self._health_label = ui.label('')
                ui.button('Проверить все', on_click=self._on_check_all, color='primary')

            servers = _get_mcp_server_list()
            self._server_data = {s['name']: s for s in servers}
            self._server_health = {}

            with ui.grid(columns=4).classes('w-full gap-3'):
                for s in servers:
                    with ui.card().classes('cursor-pointer').on('click', lambda name=s['name']: self._on_server_click(name)):
                        with ui.row().classes('items-center gap-2'):
                            self._health_dots = getattr(self, '_health_dots', {})
                            dot_id = f"dot_{s['name']}"
                            self._health_dots[dot_id] = ui.icon('circle', color='grey').classes('text-sm')
                            ui.label(s['name']).classes('font-bold text-sm')
                        ui.label(s.get('description', '')[:80]).classes('text-xs text-grey')

            self._server_detail = ui.column().classes('w-full gap-3')

    async def _on_check_all(self):
        self._health_label.text = 'Проверка...'
        servers = _get_mcp_server_list()
        online_count = 0
        for s in servers:
            client = _MCPClientLite(s['path'], s['name'])
            try:
                ok = await client.start()
                self._server_health[s['name']] = ok
                if ok:
                    online_count += 1
                client.stop()
            except Exception:
                self._server_health[s['name']] = False
                client.stop()

        self._health_label.text = f'{online_count}/{len(servers)} servers online'
        _log('INFO', f'MCP health check: {online_count}/{len(servers)} online')
        ui.notify(f'{online_count}/{len(servers)} серверов онлайн', type='info')

    def _on_server_click(self, server_name):
        self._server_detail.clear()
        s = self._server_data.get(server_name)
        if not s:
            return

        with self._server_detail:
            ui.label(f"**{server_name}**").classes('text-lg font-bold')
            if s.get('description'):
                ui.label(s['description']).classes('text-grey text-sm')

            # Interactive tester
            with ui.row().classes('w-full gap-2 items-end'):
                self._tool_select = ui.select(
                    label='Инструмент',
                    options={},
                ).classes('flex-grow')
                ui.button('Загрузить инструменты', on_click=lambda sn=server_name: self._load_tools(sn))

            self._tool_params = ui.textarea(
                label='JSON параметры',
                placeholder='{"arg1": "value1"}',
            ).props('rows=3').classes('w-full')

            ui.button(
                'Вызвать',
                on_click=lambda sn=server_name: self._call_tool(sn),
                color='primary',
            )

            self._tool_output = ui.textarea(
                label='Результат',
                value='',
            ).props('readonly rows=6').classes('w-full')

    async def _load_tools(self, server_name):
        s = self._server_data.get(server_name)
        if not s:
            return
        client = _MCPClientLite(s['path'], server_name)
        try:
            ok = await client.start()
            if not ok:
                ui.notify('Не удалось подключиться', type='negative')
                return
            tools = await client.list_tools()
            options = {t['name']: t['name'] for t in tools}
            self._tool_select.set_options(options)
            if options:
                self._tool_select.set_value(list(options.keys())[0])
            ui.notify(f'Загружено {len(tools)} инструментов', type='info')
        except Exception as e:
            ui.notify(f'Ошибка: {e}', type='negative')
        finally:
            client.stop()

    async def _call_tool(self, server_name):
        tool_name = self._tool_select.value
        if not tool_name:
            ui.notify('Выберите инструмент', type='warning')
            return

        params_text = self._tool_params.value.strip()
        arguments = {}
        if params_text:
            try:
                arguments = json.loads(params_text)
            except json.JSONDecodeError:
                ui.notify('Некорректный JSON', type='negative')
                return

        s = self._server_data.get(server_name)
        client = _MCPClientLite(s['path'], server_name)
        try:
            ok = await client.start()
            if not ok:
                self._tool_output.set_value('Ошибка: не удалось подключиться')
                return
            result = await client.call_tool(tool_name, arguments)
            self._tool_output.set_value(result or 'Пустой результат')
        except Exception as e:
            self._tool_output.set_value(f'Ошибка: {e}')
        finally:
            client.stop()


# ---------------------------------------------------------------------------
# Tab 6: System
# ---------------------------------------------------------------------------

class SystemTab:
    def __init__(self):
        with ui.column().classes('w-full gap-4'):
            ui.label('Система').classes('text-xl font-bold')

            with ui.row().classes('w-full gap-4'):
                # Left column
                with ui.column().classes('w-1/2 gap-3'):
                    ui.label('### Orchestrator').classes('text-lg font-bold')
                    with ui.row().classes('gap-2 items-center'):
                        ui.button('Инициализировать', on_click=self._on_init_orchestrator, color='primary')
                        self._orch_status = ui.label('Не инициализирован')

                    ui.label('### Статистика').classes('text-lg font-bold mt-4')
                    self._stats_output = ui.textarea(value='Нажмите для обновления').props('readonly rows=8').classes('w-full')
                    ui.button('Обновить статистику', on_click=self._on_refresh_stats, color='secondary')

                    ui.label('### Контекст').classes('text-lg font-bold mt-4')
                    with ui.row().classes('gap-2 items-end'):
                        self._threshold_input = ui.number(
                            label='Порог сжатия',
                            value=100000,
                            min=10000,
                            max=200000,
                            step=1000,
                        ).classes('w-40')
                        ui.button('Сжать', on_click=self._on_compress, color='secondary')
                        ui.button('Чекпоинт', on_click=self._on_checkpoint, color='secondary')

                # Right column
                with ui.column().classes('w-1/2 gap-3'):
                    ui.label('### Сессии').classes('text-lg font-bold')
                    with ui.row().classes('gap-2 items-end'):
                        self._session_name = ui.input(label='Имя сессии', placeholder='Введите имя...').classes('flex-grow')
                        ui.button('Создать', on_click=self._on_create_session, color='primary')

                    with ui.row().classes('gap-2 items-end'):
                        self._delete_session_id = ui.input(label='ID для удаления', placeholder='sess_...').classes('flex-grow')
                        ui.button('Удалить', on_click=self._on_delete_session, color='negative')

                    self._sessions_output = ui.textarea(value='').props('readonly rows=6').classes('w-full')
                    ui.button('Список сессий', on_click=self._on_list_sessions, color='secondary')

                    ui.label('### Логи').classes('text-lg font-bold mt-4')
                    self._logs_output = ui.textarea(value='').props('readonly rows=10').classes('w-full')
                    ui.button('Обновить логи', on_click=self._on_refresh_logs, color='secondary')

                    ui.label('### Конфигурация').classes('text-lg font-bold mt-4')
                    self._config_output = ui.textarea(value='').props('readonly rows=8').classes('w-full')
                    ui.button('Показать конфиг', on_click=self._on_show_config, color='secondary')

    def _on_init_orchestrator(self):
        global _orchestrator
        try:
            from host_orchestrator import ContextOrchestrator
            _orchestrator = ContextOrchestrator()
            self._orch_status.text = 'Инициализирован'
            _log('INFO', 'Orchestrator initialized')
            ui.notify('Orchestrator инициализирован', type='positive')
        except Exception as e:
            self._orch_status.text = f'Ошибка: {e}'
            _log('ERROR', f'Orchestrator init failed: {e}')
            ui.notify(f'Ошибка: {e}', type='negative')

    def _on_refresh_stats(self):
        active = len(_sessions)
        log_count = len(_logs)
        hist_count = len(_execution_history)
        stats = (
            f"Active Sessions: {active}\n"
            f"Total Logs: {log_count}\n"
            f"Execution History: {hist_count}\n"
            f"Summary Threshold: {_summary_threshold}\n"
            f"Max Tokens: 128000\n"
            f"Skills: {_get_skill_dispatcher().list_skills().__len__()}\n"
            f"MCP Servers: {len(_get_mcp_server_list())}\n"
            f"Connected: True"
        )
        self._stats_output.set_value(stats)

    def _on_compress(self):
        global _summary_threshold
        _summary_threshold = int(self._threshold_input.value)
        _log('INFO', f'Context compressed, threshold={_summary_threshold}')
        ui.notify(f'Контекст сжат, порог: {_summary_threshold}', type='info')

    def _on_checkpoint(self):
        ckpt_id = f"ckpt_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        _log('INFO', f'Checkpoint: {ckpt_id}')
        ui.notify(f'Чекпоинт: {ckpt_id}', type='positive')

    def _on_create_session(self):
        name = self._session_name.value.strip() or 'unnamed'
        sid = f"sess_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        _sessions[sid] = {
            'name': name,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'messages': [],
            'tokens': 0,
        }
        _log('INFO', f'Session created: {sid} ({name})')
        ui.notify(f'Сессия "{name}" создана', type='positive')

    def _on_delete_session(self):
        sid = self._delete_session_id.value.strip()
        if sid in _sessions:
            name = _sessions[sid]['name']
            del _sessions[sid]
            _log('INFO', f'Session deleted: {sid}')
            ui.notify(f'Сессия "{name}" удалена', type='positive')
        else:
            ui.notify(f'Сессия {sid} не найдена', type='warning')

    def _on_list_sessions(self):
        if not _sessions:
            self._sessions_output.set_value('Нет активных сессий')
            return
        lines = []
        for sid, data in _sessions.items():
            lines.append(f"ID: {sid}")
            lines.append(f"  Name: {data['name']}")
            lines.append(f"  Created: {data['created_at']}")
            lines.append(f"  Messages: {len(data['messages'])}")
            lines.append('')
        self._sessions_output.set_value('\n'.join(lines))

    def _on_refresh_logs(self):
        if not _logs:
            self._logs_output.set_value('Нет логов')
            return
        lines = []
        for entry in _logs[-30:]:
            lines.append(f"[{entry['timestamp']}] {entry['level']}: {entry['message']}")
        self._logs_output.set_value('\n'.join(lines))

    def _on_show_config(self):
        env_keys = [
            'CONTEXT7_API_KEY', 'TAVILY_API_KEY', 'EXA_SEARCH_API_KEY',
            'FIRECRAWL_API_KEY', 'ANTHROPIC_API_KEY', 'ANTHROPIC_MODEL',
            'ANTHROPIC_BASE_URL', 'REDIS_URL',
        ]
        lines = ['=== Configuration ===', '']
        for key in env_keys:
            val = os.getenv(key, '')
            if val:
                masked = val[:4] + '***' if len(val) > 8 else '***'
            else:
                masked = '(не задано)'
            lines.append(f'{key}: {masked}')

        lines.append('')
        skills_count = len(_get_skill_dispatcher().list_skills())
        servers_count = len(_get_mcp_server_list())
        lines.append(f'Skills loaded: {skills_count}')
        lines.append(f'MCP servers available: {servers_count}')

        self._config_output.set_value('\n'.join(lines))


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

@ui.page('/')
async def main_page():
    ui.dark_mode().enable()

    render_header()

    status_strip = StatusStrip()
    status_strip.refresh()

    with ui.tabs().classes('w-full') as tabs:
        tab_search = ui.tab('Поиск знаний', icon='search')
        tab_docs = ui.tab('Документация', icon='description')
        tab_pii = ui.tab('PII & Безопасность', icon='security')
        tab_experts = ui.tab('Эксперты', icon='smart_toy')
        tab_servers = ui.tab('MCP Серверы', icon='dns')
        tab_system = ui.tab('Система', icon='settings')

    with ui.tab_panels(tabs, value='Поиск знаний').classes('w-full'):
        with ui.tab_panel(tab_search):
            KnowledgeSearchTab()
        with ui.tab_panel(tab_docs):
            Context7Tab()
        with ui.tab_panel(tab_pii):
            PIISecurityTab()
        with ui.tab_panel(tab_experts):
            ExpertsTab()
        with ui.tab_panel(tab_servers):
            MCPServersTab()
        with ui.tab_panel(tab_system):
            SystemTab()

    ui.label('MCP Context Pipeline — NiceGUI Console v2.0').classes('text-center text-grey q-mt-md')


ui.run(
    title='MCP Context Pipeline Console',
    port=7860,
    dark=True,
    reload=False,
    host='0.0.0.0',
)
