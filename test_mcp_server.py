"""Тест MCP Context Manager Server."""

import asyncio
import sys
from mcp import ClientSession, stdio_client
from mcp.client.stdio import StdioServerParameters

async def test():
    server_params = StdioServerParameters(
        command='python3',
        args=['src/server.py'],
        env={}
    )
    ctx = stdio_client(server_params)
    read_stream, write_stream = await ctx.__aenter__()
    session = ClientSession(read_stream, write_stream)
    await session.__aenter__()
    await session.initialize()

    print('=== Инструменты MCP сервера ===')
    tools = await session.list_tools()
    for tool in tools.tools:
        print(f'- {tool.name}: {tool.description[:60]}...')

    print('\n=== Ресурсы MCP сервера ===')
    resources = await session.list_resources()
    for resource in resources.resources:
        print(f'- {resource.name}')

    print('\n=== Тест запроса документации ===')
    result = await session.call_tool(
        'query_docs_with_translation',
        arguments={
            'library_id': '/pytorch/pytorch',
            'query': 'tensor operations',
            'translate': True
        }
    )
    print(f'Статус: {result.content[0].text[:100]}...' if result.content else 'Нет результата')

    await session.__aexit__(None, None, None)
    await ctx.__aexit__(None, None, None)

if __name__ == '__main__':
    asyncio.run(test())
