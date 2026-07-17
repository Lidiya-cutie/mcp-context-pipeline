"""
Тест Context7 с переводом на русский язык.
"""

import asyncio
import sys
from mcp import ClientSession, stdio_client
from mcp.client.stdio import StdioServerParameters
import os

sys.path.insert(0, 'src')
from translator import translate_en_to_ru

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

    print('=== Context7 с переводом на русский ===\n')

    print('Тест 1: Запрос документации PyTorch (будет переведен)')
    result = await session.call_tool(
        'query-docs',
        arguments={'libraryId': '/pytorch/pytorch', 'query': 'tensor creation'}
    )
    if result.content:
        text = result.content[0].text
        print(f'Длина оригинала: {len(text)} символов')
        translated = translate_en_to_ru(text[:3000], context='PyTorch documentation')
        print(f'Длина перевода: {len(translated)} символов')
        print(f'Перевод:\n{translated}\n')

    print('Тест 2: Запрос документации FastAPI')
    result2 = await session.call_tool(
        'query-docs',
        arguments={'libraryId': '/fastapi/fastapi', 'query': 'JWT authentication'}
    )
    if result2.content:
        text2 = result2.content[0].text
        print(f'Длина оригинала: {len(text2)} символов')
        translated2 = translate_en_to_ru(text2, context='FastAPI documentation')
        print(f'Длина перевода: {len(translated2)} символов')
        print(f'Перевод:\n{translated2}\n')

    await session.__aexit__(None, None, None)
    await ctx.__aexit__(None, None, None)

asyncio.run(test())
