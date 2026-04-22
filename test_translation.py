"""Тест переводчика."""

import asyncio
import sys
sys.path.insert(0, 'src')
from translator import translate_en_to_ru


async def test():
    print('=== Тест 1: Короткий текст ===')
    short = "PyTorch tensor operations"
    result1 = translate_en_to_ru(short)
    print(f'Оригинал: {short}')
    print(f'Перевод: {result1}\n')

    print('=== Тест 2: Длинный текст ===')
    long = """
### Tensor Creation API

Methods for initializing tensors from data, specific distributions, or existing tensor properties.

## CALL torch.tensor

### Description
Constructs a tensor with data provided in an array-like structure.
"""
    result2 = translate_en_to_ru(long, "PyTorch")
    print(f'Длина оригинала: {len(long)} символов')
    print(f'Перевод:\n{result2}\n')

    print('=== Тест 3: Технические термины ===')
    tech = "The library provides authentication and authorization middleware for API endpoints."
    result3 = translate_en_to_ru(tech, "API безопасность")
    print(f'Оригинал: {tech}')
    print(f'Перевод: {result3}\n')

    print('=== Тест 4: С кэшированием ===')
    result4 = translate_en_to_ru(short, "PyTorch")
    result5 = translate_en_to_ru(short, "PyTorch")
    print(f'Перевод 1: {result4}')
    print(f'Перевод 2 (должен быть из кэша): {result5}')
    if result4 == result5:
        print('✓ Кэширование работает!')
    else:
        print('✗ Кэширование не работает')

if __name__ == "__main__":
    asyncio.run(test())
