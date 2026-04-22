"""Модуль для создания HTTP клиентов с поддержкой прокси.

Позволяет обходить региональные ограничения для LLM API.
"""

import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


def get_http_client(proxy_url: Optional[str] = None):
    """Создать HTTP клиент с поддержкой прокси."""
    try:
        import httpx

        if proxy_url:
            proxies = {
                "http://": proxy_url,
                "https://": proxy_url
            }
            return httpx.AsyncClient(proxies=proxies, timeout=60.0)
        else:
            return httpx.AsyncClient(timeout=60.0)
    except ImportError:
        return None


def get_anthropic_client(api_key: str, model: Optional[str] = None, proxy_url: Optional[str] = None):
    """Создать клиент Anthropic с поддержкой прокси."""
    try:
        from anthropic import Anthropic, AsyncAnthropic

        http_client = get_http_client(proxy_url)
        kwargs = {"api_key": api_key}
        if http_client:
            kwargs["http_client"] = http_client

        return {
            "sync": Anthropic(**kwargs),
            "async": AsyncAnthropic(**kwargs),
            "model": model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        }
    except ImportError:
        raise ImportError("anthropic package not installed. Install with: pip install anthropic")


def get_openai_client(api_key: str, model: Optional[str] = None, proxy_url: Optional[str] = None):
    """Создать клиент OpenAI с поддержкой прокси."""
    try:
        from openai import OpenAI, AsyncOpenAI

        http_client = get_http_client(proxy_url)
        kwargs = {"api_key": api_key}
        if http_client:
            kwargs["http_client"] = http_client

        return {
            "sync": OpenAI(**kwargs),
            "async": AsyncOpenAI(**kwargs),
            "model": model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        }
    except ImportError:
        raise ImportError("openai package not installed. Install with: pip install openai")


def get_proxy_url() -> Optional[str]:
    """Получить URL прокси из переменных окружения."""
    return os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("ALL_PROXY")


def get_urllib_proxy_handlers(proxy_url: Optional[str] = None):
    """Получить обработчики прокси для urllib."""
    if not proxy_url:
        proxy_url = get_proxy_url()

    if not proxy_url:
        return []

    try:
        import urllib.request
        return [urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})]
    except ImportError:
        return []
