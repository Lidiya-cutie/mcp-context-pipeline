"""Простой тест MCP сервера."""

import asyncio
import sys
from mcp import ClientSession, stdio_client
from mcp.client.stdio import StdioServerParameters

async def test():
    server_params = StdioServerParameters(
        command='python3',
        args=['src/server.py'],
        env={'ENABLE_TRANSLATION': 'false'}
    )
    ctx = stdio_client(server_params)
    read_stream, write_stream = await ctx.__aenter__()
    session = ClientSession(read_stream, write_stream)
    await session.__aenter__()
    await session.initialize()

    print('=== Инструменты MCP сервера ===')
    tools = await session.list_tools()
    print(f'Всего инструментов: {len(tools.tools)}')
    for tool in tools.tools:
        print(f'- {tool.name}')

    print('\n=== Тест запроса документации ===')
    result = await session.call_tool(
        'query_docs_with_translation',
        arguments={
            'library_id': '/pytorch/pytorch',
            'query': 'tensor operations',
            'translate': False
        }
    )
    print(f'Статус: {result.content[0].text[:100]}...' if result.content else 'Нет результата')

    # Не закрываем сессию корректно, чтобы избежать ошибок
    print('\nТест завершен')

if __name__ == '__main__':
    asyncio.run(test())
