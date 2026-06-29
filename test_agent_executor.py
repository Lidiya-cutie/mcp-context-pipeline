#!/usr/bin/env python3
"""
Тест Agent Executor — запуск эксперта по навыку.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from agent_executor import AgentExecutor


async def main():
    project_dir = os.path.dirname(os.path.abspath(__file__))
    executor = AgentExecutor(project_dir=project_dir)

    print("=" * 60)
    print("Agent Executor Tests")
    print("=" * 60)

    # 1. List skills
    print("\n1. Listing skills...")
    skills = executor.list_skills()
    print(f"   Loaded: {len(skills)} skills")
    assert len(skills) == 60, f"Expected 60, got {len(skills)}"
    print("   [PASS] 60 skills loaded")

    # 2. Find skill
    print("\n2. Finding skill for 'PII masking'...")
    matches = executor.find_skill("PII masking")
    assert len(matches) > 0, "No matches found"
    print(f"   Top match: {matches[0]['name']} (score={matches[0]['score']:.2f})")
    print("   [PASS] Skill found")

    # 3. Execute skill with MCP context (no LLM call - just MCP + context)
    print("\n3. Testing execute with pii_context_masking (MCP only)...")
    skill_name = "pii_context_masking"
    plan = executor.dispatcher.activate_skill(skill_name, "Scan this text for PII: Иван Иванов, телефон +7-999-123-45-67")
    print(f"   System prompt: {plan['system_prompt'][:80]}...")
    print(f"   MCP servers: {plan['mcp_servers']}")

    # Start MCP and test tool call
    mcp_context = await executor._gather_context("test", plan["mcp_servers"])
    print(f"   MCP context gathered: {len(mcp_context)} chars")
    assert len(mcp_context) > 0, "No MCP context"
    print("   [PASS] MCP context gathered")

    # 4. Test MCP tool call (pii_scanner)
    print("\n4. Testing MCP tool call (pii_scanner)...")
    client = await executor._start_mcp("pii_scanner")
    assert client is not None, "pii_scanner not started"
    tools = await client.list_tools()
    print(f"   Tools: {[t['name'] for t in tools]}")
    assert len(tools) > 0, "No tools"
    print("   [PASS] MCP server started with tools")

    # Call scan_string
    scan_result = await client.call_tool("scan_string", {"text": "Email: test@mail.ru, Phone: +7-999-123-45-67"})
    print(f"   Scan result: {scan_result[:200] if scan_result else 'None'}...")
    assert scan_result is not None, "scan_string returned None"
    print("   [PASS] MCP tool call works")

    await executor._stop_all_mcp()

    # 5. Full execute (with LLM if available)
    print("\n5. Full execute (LLM + MCP)...")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        result = await executor.execute(
            skill_name,
            "Просканируй текст на PII: Мой паспорт 4510 123456, ИНН 7712345678, email test@company.com",
        )
        print(f"   Status: {result['status']}")
        print(f"   Response: {result['response'][:200]}...")
        if result.get('error'):
            print(f"   Error: {result['error'][:100]}")
        if result['status'] == 'success':
            print("   [PASS] Full execute with LLM")
        else:
            print("   [WARN] LLM call failed (check API key/proxy)")
    else:
        print("   [SKIP] No ANTHROPIC_API_KEY set")

    # 6. Quick execute
    print("\n6. Quick execute (auto-find skill)...")
    if api_key:
        result = await executor.quick_execute(
            "GPU monitoring",
            "Проверь утилизацию GPU на сервере",
        )
        print(f"   Skill: {result['skill']}")
        print(f"   Status: {result['status']}")
        print(f"   Response: {result['response'][:150]}...")
        if result['status'] == 'success':
            print("   [PASS] Quick execute")
        else:
            print(f"   [WARN] Error: {result.get('error', '')[:100]}")
    else:
        print("   [SKIP] No ANTHROPIC_API_KEY set")

    print("\n" + "=" * 60)
    print("Tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
