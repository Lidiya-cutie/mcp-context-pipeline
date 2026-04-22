#!/usr/bin/env python3
"""Тест проверки работы прокси для LLM клиентов."""

import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def test_anthropic_client():
    """Тест подключения к Anthropic с прокси."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    proxy_url = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("ALL_PROXY")

    if not api_key:
        print("[SKIP] ANTHROPIC_API_KEY не установлен")
        return

    print(f"[INFO] Тест Anthropic клиент")
    if proxy_url:
        print(f"[INFO] Используется прокси: {proxy_url}")

    try:
        from anthropic import AsyncAnthropic
        import httpx

        kwargs = {"api_key": api_key}
        if proxy_url:
            proxies = {"http://": proxy_url, "https://": proxy_url}
            kwargs["http_client"] = httpx.AsyncClient(proxies=proxies, timeout=60.0)

        client = AsyncAnthropic(**kwargs)

        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[{"role": "user", "content": "Say 'Hello' in Russian"}]
        )

        print(f"[SUCCESS] Anthropic ответ: {response.content[0].text}")

    except Exception as e:
        print(f"[ERROR] Ошибка подключения к Anthropic: {e}")


async def test_openai_client():
    """Тест подключения к OpenAI с прокси."""
    api_key = os.getenv("OPENAI_API_KEY")
    proxy_url = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("ALL_PROXY")

    if not api_key:
        print("[SKIP] OPENAI_API_KEY не установлен")
        return

    print(f"[INFO] Тест OpenAI клиент")
    if proxy_url:
        print(f"[INFO] Используется прокси: {proxy_url}")

    try:
        from openai import AsyncOpenAI
        import httpx

        kwargs = {"api_key": api_key}
        if proxy_url:
            proxies = {"http://": proxy_url, "https://": proxy_url}
            kwargs["http_client"] = httpx.AsyncClient(proxies=proxies, timeout=60.0)

        client = AsyncOpenAI(**kwargs)

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say 'Hello' in Russian"}],
            max_tokens=100
        )

        print(f"[SUCCESS] OpenAI ответ: {response.choices[0].message.content}")

    except Exception as e:
        print(f"[ERROR] Ошибка подключения к OpenAI: {e}")


async def test_translator():
    """Тест переводчика с прокси."""
    print(f"[INFO] Тест переводчика")

    try:
        from src.translator import get_translator

        translator = get_translator()
        if not translator.enabled:
            print("[SKIP] Перевод отключен")
            return

        result = translator.translate("Hello, world!", context="test")
        print(f"[SUCCESS] Результат перевода: {result}")

    except Exception as e:
        print(f"[ERROR] Ошибка переводчика: {e}")


def test_urllib_proxy():
    """Тест urllib с прокси."""
    print(f"[INFO] Тест urllib с прокси")

    proxy_url = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("ALL_PROXY")
    if proxy_url:
        print(f"[INFO] Используется прокси: {proxy_url}")

    try:
        from src.external_knowledge.providers import _get_opener

        opener = _get_opener()
        request = urllib.request.Request("https://httpbin.org/ip", method="GET")
        with opener.open(request, timeout=10) as response:
            data = response.read().decode("utf-8")
            print(f"[SUCCESS] Ответ httpbin: {data}")
    except Exception as e:
        print(f"[ERROR] Ошибка urllib: {e}")


if __name__ == "__main__":
    import urllib.request

    print("=" * 60)
    print("Тестирование прокси для LLM клиентов")
    print("=" * 60)

    proxy_url = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("ALL_PROXY")
    if proxy_url:
        print(f"[INFO] Настроен прокси: {proxy_url}")
    else:
        print("[WARN] Прокси не настроен. Установите HTTP_PROXY или HTTPS_PROXY в .env")

    print()

    asyncio.run(test_anthropic_client())
    print()
    asyncio.run(test_openai_client())
    print()
    test_translator()
    print()
    test_urllib_proxy()

    print("=" * 60)
    print("Тестирование завершено")
    print("=" * 60)
