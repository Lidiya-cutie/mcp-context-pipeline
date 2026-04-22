"""Проверка доступных инструментов Context7."""

import asyncio
import sys
from mcp import ClientSession, stdio_client
from mcp.client.stdio import StdioServerParameters
import os

async def test():
    api_key = os.environ.get('CONTEXT7_API_KEY', '')
    server_params = StdioServerParameters(
        command='npx',
        args=['-y', '@upstash/context7-mcp'] + (['--api-key', api_key] if api_key else [])
    )
    ctx = stdio_client(server_params)
    read_stream, write_stream = await ctx.__aenter__()
    session = ClientSession(read_stream, write_stream)
    await session.__aenter__()
    await session.initialize()

    print('=== Доступные инструменты ===')
    tools = await session.list_tools()
    for tool in tools.tools:
        print(f'\n{tool.name}:')
        print(f'  Описание: {tool.description}')
        if hasattr(tool, 'inputSchema'):
            import json
            print(f'  Параметры: {json.dumps(tool.inputSchema, indent=2)}')

    await session.__aexit__(None, None, None)
    await ctx.__aexit__(None, None, None)

if __name__ == '__main__':
    asyncio.run(test())
