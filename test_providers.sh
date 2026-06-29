#!/bin/bash
# ============================================
# test_providers.sh — Проверка всех knowledge-провайдеров
# Запуск: bash /mldata/mcp_context_pipeline/test_providers.sh
# ============================================

set -a
source /mldata/mcp_context_pipeline/.env 2>/dev/null
set +a

PYTHON="/mldata/mcp_context_pipeline/venv/bin/python3"
PROJECT="/mldata/mcp_context_pipeline"

echo "=== Проверка Knowledge Providers ==="
echo "Python: $PYTHON"
echo ""

# 1. Context7 (npm-based)
echo "--- 1. Context7 ---"
$PYTHON -c "
import asyncio, sys
sys.path.insert(0, '$PROJECT/src')
from context7_client import Context7Client

async def test():
    client = Context7Client()
    connected = await client.connect()
    print(f'  Connected: {connected}')
    if connected:
        lib_id = await client.resolve_library_id('fastapi', 'pagination')
        print(f'  fastapi → {lib_id}')
        if lib_id:
            result = await client.query_docs(lib_id, 'how to create a route', translate=False)
            status = result.get('status', 'unknown')
            content_len = len(result.get('content', '') or '')
            print(f'  query_docs: status={status}, content={content_len} chars')
        await client.disconnect()

asyncio.run(test())
" 2>&1 | head -10

# 2. Tavily
echo ""
echo "--- 2. Tavily ---"
$PYTHON -c "
import asyncio, sys, os
sys.path.insert(0, '$PROJECT/src')
from external_knowledge.providers import TavilyProvider

async def test():
    p = TavilyProvider()
    print(f'  Enabled: {bool(os.getenv(\"TAVILY_API_KEY\"))}')
    results = await p.search('Python async await best practices', limit=2)
    print(f'  Results: {len(results)} chunks')
    for r in results:
        print(f'    [{r.score:.2f}] {r.title[:60]}... ({len(r.content)} chars)')

asyncio.run(test())
" 2>&1 | head -10

# 3. Exa
echo ""
echo "--- 3. Exa ---"
$PYTHON -c "
import asyncio, sys, os
sys.path.insert(0, '$PROJECT/src')
from external_knowledge.providers import ExaProvider

async def test():
    p = ExaProvider()
    print(f'  Enabled: {bool(os.getenv(\"EXA_SEARCH_API_KEY\"))}')
    results = await p.search('machine learning model deployment guide', limit=2)
    print(f'  Results: {len(results)} chunks')
    for r in results:
        print(f'    [{r.score:.2f}] {r.title[:60]}... ({len(r.content)} chars)')

asyncio.run(test())
" 2>&1 | head -10

# 4. Shiva
echo ""
echo "--- 4. Shiva ---"
$PYTHON -c "
import asyncio, sys, os
sys.path.insert(0, '$PROJECT/src')
from external_knowledge.providers import ShivaProvider

async def test():
    p = ShivaProvider()
    print(f'  Enabled: {p._is_enabled()}')
    if p._is_enabled():
        results = await p.search('проект data science', context={'project_id': 44}, limit=2)
        print(f'  Results: {len(results)} chunks')
        for r in results:
            print(f'    [{r.score:.2f}] {r.title[:60]}... ({len(r.content)} chars)')

asyncio.run(test())
" 2>&1 | head -10

# 5. DocFusion
echo ""
echo "--- 5. DocFusion ---"
$PYTHON -c "
import asyncio, sys, os
sys.path.insert(0, '$PROJECT/src')
from external_knowledge.providers import DocFusionProvider

async def test():
    p = DocFusionProvider()
    print(f'  Enabled: {p._is_enabled()}')
    if p._is_enabled():
        results = await p.search('документация API', limit=2)
        print(f'  Results: {len(results)} chunks')
        for r in results:
            print(f'    [{r.score:.2f}] {r.title[:60]}... ({len(r.content)} chars)')

asyncio.run(test())
" 2>&1 | head -10

# 6. Firecrawl
echo ""
echo "--- 6. Firecrawl ---"
$PYTHON -c "
import asyncio, sys, os
sys.path.insert(0, '$PROJECT/src')
from external_knowledge.providers import FirecrawlProvider

async def test():
    p = FirecrawlProvider()
    print(f'  Enabled: {bool(os.getenv(\"FIRECRAWL_API_KEY\"))}')
    results = await p.search('gradio documentation tutorial', limit=2)
    print(f'  Results: {len(results)} chunks')
    for r in results:
        print(f'    [{r.score:.2f}] {r.title[:60]}... ({len(r.content)} chars)')

asyncio.run(test())
" 2>&1 | head -10

# 7. Full orchestrator test
echo ""
echo "--- 7. Full Orchestrator (all providers) ---"
$PYTHON -c "
import asyncio, sys
sys.path.insert(0, '$PROJECT/src')
from host_orchestrator import ContextOrchestrator

async def test():
    orch = ContextOrchestrator(
        enable_knowledge_bridge=True,
        enable_context7=True,
        enable_external_knowledge=True
    )
    await orch.connect()
    
    # External search through router
    result = await orch.external_search('how to use FastAPI dependency injection')
    if result:
        summary = result.get('summary', '')
        raw_len = len(result.get('raw_json', ''))
        print(f'  Summary: {summary[:100]}...' if summary else '  No summary')
        print(f'  Raw JSON: {raw_len} chars')
        print(f'  Providers used: {result.get(\"providers_used\", [])}')
    else:
        print('  No result')
    
    await orch.disconnect()

asyncio.run(test())
" 2>&1 | head -15

echo ""
echo "=== Проверка завершена ==="
