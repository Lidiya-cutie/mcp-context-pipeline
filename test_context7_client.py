"""Тест Context7 клиента."""

import asyncio
import sys
import os
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, 'src')
from context7_client import get_context7_client

async def test():
    client = await get_context7_client()

    print('=== Тест 1: Разрешение идентификатора библиотеки ===')
    library_id = await client.resolve_library_id('pytorch')
    print(f'PyTorch library ID: {library_id}')

    print('\n=== Тест 2: Запрос документации с переводом ===')
    result = await client.query_docs(
        library_id='/pytorch/pytorch',
        query='tensor operations',
        translate=True
    )

    if result.get('status') == 'success':
        content = result.get('content', '')
        translated = result.get('translated', '')
        print(f'Оригинал: {len(content)} символов')
        print(f'Перевод: {len(translated)} символов')
        print(f'Переведено: {result.get("translated_to_ru")}')
    else:
        print(f'Статус: {result.get("status")}')
        print(f'Ошибка: {result.get("error")}')

    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(test())
