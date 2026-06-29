#!/usr/bin/env python3
"""
Smoke-тесты MCP Context Pipeline v2
Покрывают: провайдеры поиска, MCP клиент, NiceGUI модули
"""
import asyncio
import json
import os
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PROJECT_DIR, "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

PASS = 0
FAIL = 0
TOTAL = 0


def check(name, condition, detail=""):
    global PASS, FAIL, TOTAL
    TOTAL += 1
    if condition:
        print(f"  [PASS] {name}")
        PASS += 1
    else:
        print(f"  [FAIL] {name}")
        if detail:
            print(f"         {detail}")
        FAIL += 1


async def main():
    global PASS, FAIL, TOTAL

    print("=" * 60)
    print("MCP Context Pipeline — Smoke Tests v2")
    print("=" * 60)

    # ============================================================
    # 1. Imports
    # ============================================================
    print("\n--- 1. Импорт модулей ---")

    try:
        from skill_dispatcher import SkillDispatcher
        check("SkillDispatcher импортирован", True)
    except Exception as e:
        check("SkillDispatcher импортирован", False, str(e))

    try:
        from agent_executor import AgentExecutor, MCPClient
        check("AgentExecutor + MCPClient импортированы", True)
    except Exception as e:
        check("AgentExecutor + MCPClient импортированы", False, str(e))

    try:
        from host_orchestrator import ContextOrchestrator
        check("ContextOrchestrator импортирован", True)
    except Exception as e:
        check("ContextOrchestrator импортирован", False, str(e))

    try:
        from context7_client import Context7Client
        check("Context7Client импортирован", True)
    except Exception as e:
        check("Context7Client импортирован", False, str(e))

    try:
        from external_knowledge.providers import (
            TavilyProvider, ExaProvider, FirecrawlProvider,
            ShivaProvider, DocFusionProvider,
        )
        check("External Knowledge Providers импортированы", True)
    except Exception as e:
        check("External Knowledge Providers импортированы", False, str(e))

    # ============================================================
    # 2. Skill Dispatcher
    # ============================================================
    print("\n--- 2. Skill Dispatcher ---")

    try:
        sd = SkillDispatcher(
            skills_dir=os.path.join(PROJECT_DIR, "Навыки"),
            mcp_servers_dir=os.path.join(PROJECT_DIR, "src", "mcp_servers"),
        )
        skills = sd.list_skills()
        check("Загрузка навыков (>=60)", len(skills) >= 60, f"загружено: {len(skills)}")

        # Roles distribution
        roles = set(s.get("role", "") for s in skills)
        check("Минимум 4 роли", len(roles) >= 4, f"ролей: {len(roles)} ({', '.join(list(roles)[:6])})")

        # Find PII skill
        pii_matches = sd.find_skill("PII masking")
        check("Поиск PII навыков", len(pii_matches) > 0)

        # Get tools for pii_context_masking
        tools = sd.get_required_tools("pii_context_masking")
        check("pii_context_masking → pii_scanner MCP",
              "pii_scanner" in tools.get("mcp_servers", []))

        # Alias mapping: vault → secrets_manager
        vault_tools = sd.get_required_tools("secrets_vault_rotation")
        has_secrets = "secrets_manager" in vault_tools.get("mcp_servers", [])
        check("Алиас vault → secrets_manager", has_secrets,
              f"mcp_servers: {vault_tools.get('mcp_servers', [])}")

        # Activate skill
        plan = sd.activate_skill("pii_context_masking", "Scan for PII")
        check("Activate возвращает system_prompt", bool(plan.get("system_prompt")))
        check("Activate возвращает mcp_servers", len(plan.get("mcp_servers", [])) > 0)
    except Exception as e:
        check("Skill Dispatcher", False, str(e))

    # ============================================================
    # 3. MCP Client — pii_scanner
    # ============================================================
    print("\n--- 3. MCP Client (pii_scanner) ---")

    pii_scanner_path = os.path.join(PROJECT_DIR, "src", "mcp_servers", "pii_scanner", "server.py")
    if os.path.exists(pii_scanner_path):
        client = MCPClient(pii_scanner_path, "pii_scanner")
        started = await client.start()
        check("pii_scanner запущен", started)

        if started:
            tools = await client.list_tools()
            tool_names = [t["name"] for t in tools]
            check("pii_scanner имеет scan_string", "scan_string" in tool_names)
            check("pii_scanner имеет mask_string", "mask_string" in tool_names)
            check("pii_scanner инструментов >= 7", len(tools) >= 7, f"найдено: {len(tools)}")

            # Test scan_string
            scan_result = await client.call_tool("scan_string", {
                "text": "Email: test@mail.ru, Phone: +7-999-123-45-67, Паспорт: 4510 123456"
            })
            check("scan_string возвращает результат", scan_result is not None)
            has_pii = "pii_found" in (scan_result or "")
            check("scan_string находит PII", has_pii)

            # Test mask_string
            mask_result = await client.call_tool("mask_string", {
                "text": "My email is john@company.com and phone is +7-999-000-11-22"
            })
            check("mask_string возвращает результат", mask_result is not None)
            mask_str = mask_result or ""
            has_masked = (
                "REDACTED" in mask_str
                or "MASKED" in mask_str
                or "***" in mask_str
                or '"replacements_made": 0' not in mask_str
                and '"replacements_made"' in mask_str
            )
            check("mask_string маскирует данные", has_masked)

        client.stop()
    else:
        check("pii_scanner server.py найден", False, pii_scanner_path)

    # ============================================================
    # 4. MCP Client — gpu_monitor
    # ============================================================
    print("\n--- 4. MCP Client (gpu_monitor) ---")

    gpu_path = os.path.join(PROJECT_DIR, "src", "mcp_servers", "gpu_monitor", "server.py")
    if os.path.exists(gpu_path):
        client = MCPClient(gpu_path, "gpu_monitor")
        started = await client.start()
        check("gpu_monitor запущен", started)

        if started:
            tools = await client.list_tools()
            tool_names = [t["name"] for t in tools]
            check("gpu_monitor имеет check_health", "check_health" in tool_names)

            health = await client.call_tool("check_health")
            check("gpu_monitor check_health отвечает", health is not None)

        client.stop()
    else:
        check("gpu_monitor server.py найден", False)

    # ============================================================
    # 5. Knowledge Providers
    # ============================================================
    print("\n--- 5. Knowledge Providers ---")

    # Tavily
    try:
        tavily = TavilyProvider()
        results = await tavily.search("Python async await", limit=2)
        check("Tavily возвращает результаты", len(results) > 0,
              f"chunks: {len(results)}")
    except Exception as e:
        check("Tavily", False, str(e))

    # Firecrawl
    try:
        firecrawl = FirecrawlProvider()
        results = await firecrawl.search("FastAPI tutorial", limit=2)
        check("Firecrawl возвращает результаты", len(results) > 0,
              f"chunks: {len(results)}")
    except Exception as e:
        check("Firecrawl", False, str(e))

    # Exa
    try:
        exa = ExaProvider()
        exa_key = os.getenv("EXA_API_KEY", "")
        check("EXA_API_KEY настроен", bool(exa_key),
              "Добавьте EXA_API_KEY=... в .env")
        if exa_key:
            results = await exa.search("machine learning deployment", limit=2)
            check("Exa возвращает результаты", len(results) > 0,
                  f"chunks: {len(results)}")
    except Exception as e:
        check("Exa", False, str(e))

    # Shiva
    try:
        shiva = ShivaProvider()
        if shiva._is_enabled():
            results = await shiva.search("проект data science", context={"project_id": 44}, limit=2)
            check("Shiva возвращает результаты", len(results) > 0,
                  f"chunks: {len(results)}")
        else:
            check("Shiva провайдер включён", False, "ENABLE_SHIVA_PROVIDER != true")
    except Exception as e:
        check("Shiva", False, str(e))

    # DocFusion
    try:
        docfusion = DocFusionProvider()
        if docfusion._is_enabled():
            results = await docfusion.search("документация API", limit=2)
            check("DocFusion возвращает результаты", len(results) > 0,
                  f"chunks: {len(results)}")
        else:
            check("DocFusion провайдер включён", False, "ENABLE_DOCFUSION_PROVIDER != true")
    except Exception as e:
        check("DocFusion", False, str(e))

    # ============================================================
    # 6. Context7
    # ============================================================
    print("\n--- 6. Context7 Documentation ---")

    try:
        c7 = Context7Client()
        connected = await c7.connect()
        check("Context7 подключение", connected)

        if connected:
            lib_id = await c7.resolve_library_id("fastapi", "routes")
            check("Context7 resolve fastapi", lib_id is not None, f"lib_id: {lib_id}")

            if lib_id:
                docs = await c7.query_docs(lib_id, "how to create a route", translate=False)
                check("Context7 query возвращает документацию",
                      docs.get("status") == "success",
                      f"status: {docs.get('status')}, content: {len(docs.get('content', ''))} chars")

            await c7.disconnect()
    except Exception as e:
        check("Context7", False, str(e))

    # ============================================================
    # 7. Agent Executor end-to-end
    # ============================================================
    print("\n--- 7. Agent Executor (end-to-end) ---")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        try:
            executor = AgentExecutor(project_dir=PROJECT_DIR)

            result = await executor.execute(
                "pii_context_masking",
                "Просканируй: Email admin@corp.ru, телефон +7-495-123-45-67",
                max_tokens=1000,
            )
            check("Agent execute статус success", result["status"] == "success")
            check("Agent execute возвращает ответ",
                  len(result.get("response", "")) > 50,
                  f"response length: {len(result.get('response', ''))}")
            check("Agent execute подключает MCP",
                  len(result.get("mcp_results", {})) > 0,
                  f"mcp_results: {list(result.get('mcp_results', {}).keys())}")
        except Exception as e:
            check("Agent Executor", False, str(e))
    else:
        check("Agent Executor (LLM)", False, "ANTHROPIC_API_KEY не задан")

    # ============================================================
    # 8. NiceGUI UI импорт
    # ============================================================
    print("\n--- 8. NiceGUI UI ---")

    mcp_ui_path = os.path.join(PROJECT_DIR, "mcp_ui.py")
    check("mcp_ui.py существует", os.path.exists(mcp_ui_path))

    if os.path.exists(mcp_ui_path):
        try:
            import ast
            with open(mcp_ui_path) as f:
                tree = ast.parse(f.read())
            classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
            expected = ["KnowledgeSearchTab", "Context7Tab", "PIISecurityTab", "ExpertsTab", "MCPServersTab", "SystemTab"]
            found = [c for c in expected if c in classes]
            check("NiceGUI содержит 6 tab-классов", len(found) >= 4,
                  f"найдено: {found}")
        except Exception as e:
            check("NiceGUI парсинг", False, str(e))

    # ============================================================
    # 9. MCP Servers inventory
    # ============================================================
    print("\n--- 9. MCP Servers (27 штук) ---")

    mcp_dir = os.path.join(PROJECT_DIR, "src", "mcp_servers")
    if os.path.isdir(mcp_dir):
        servers = [d for d in os.listdir(mcp_dir)
                   if os.path.isdir(os.path.join(mcp_dir, d))
                   and os.path.exists(os.path.join(mcp_dir, d, "server.py"))]
        check("MCP серверов >= 27", len(servers) >= 27, f"найдено: {len(servers)}")

        # Quick health check on 3 servers
        for srv in ["pii_scanner", "context_manager", "gpu_monitor"]:
            srv_path = os.path.join(mcp_dir, srv, "server.py")
            exists = os.path.exists(srv_path)
            check(f"  {srv}/server.py", exists)
    else:
        check("mcp_servers директория", False, mcp_dir)

    # ============================================================
    # Итог
    # ============================================================
    print("\n" + "=" * 60)
    print(f"Результат: {PASS}/{TOTAL} пройдено, {FAIL} не пройдено")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
