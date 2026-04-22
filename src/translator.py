"""
Переводчик через LLM для Context7.

Автоматический перевод технической документации с английского на русский.
"""

import os
from typing import Optional
import anthropic
from dotenv import load_dotenv

load_dotenv()


class LLMLanguageTranslator:
    """Переводчик через Anthropic Claude API."""

    def __init__(self):
        """Инициализация переводчика."""
        self.enabled = os.environ.get("ENABLE_TRANSLATION", "false").lower() == "true"
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.proxy_url = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("ALL_PROXY")

        if not self.enabled:
            print("[INFO] Перевод отключен (ENABLE_TRANSLATION=false)")
            self.client = None
        elif not self.api_key:
            print("[WARN] ANTHROPIC_API_KEY не найден. Перевод недоступен.")
            self.client = None
        else:
            kwargs = {"api_key": self.api_key}
            if self.proxy_url:
                try:
                    import httpx
                    proxies = {"http://": self.proxy_url, "https://": self.proxy_url}
                    kwargs["http_client"] = httpx.Client(proxies=proxies, timeout=60.0)
                    print(f"[INFO] Перевод через Anthropic Claude с прокси: {self.proxy_url}")
                except ImportError:
                    print("[WARN] httpx не установлен, прокси не будет использован")

            self.client = anthropic.Anthropic(**kwargs)
            if not self.proxy_url:
                print("[INFO] Перевод включен через Anthropic Claude")

        self._cache = {}

    def translate(
        self,
        text: str,
        context: Optional[str] = None
    ) -> str:
        """
        Перевести текст на русский язык.

        Args:
            text: Текст для перевода
            context: Контекст (например, "PyTorch документация")

        Returns:
            Переведенный текст или оригинал при ошибке
        """
        if not self.enabled or not self.client:
            return text

        if not text or len(text) < 10:
            return text

        # Кэширование коротких запросов
        cache_key = text[:100]
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            if context:
                prompt = f"""
Переведи эту техническую документацию на русский язык.

Контекст: {context}

Технические термины:
- tensor → тензор
- library → библиотека
- API → интерфейс
- framework → фреймворк
- authentication → аутентификация
- authorization → авторизация
- middleware → посредник/мидлварь
- documentation → документация

Текст для перевода:
{text}

Требования:
1. Используй профессиональный технический стиль
2. Сохраняй точность технических терминов
3. Сохраняй структуру документации
4. Не добавляй лишний текст, которого нет в оригинале
5. Переведи на русский язык, сохраняя примеры кода на английском
"""
            else:
                prompt = f"""
Переведи этот текст на русский язык.

Технические термины:
- tensor → тензор
- library → библиотека
- API → интерфейс
- framework → фреймворк
- authentication → аутентификация
- authorization → авторизация
- middleware → посредник/мидлварь
- documentation → документация

Текст для перевода:
{text}

Требования:
1. Используй профессиональный технический стиль
2. Сохраняй точность технических терминов
3. Переведи на русский язык, сохраняя примеры кода на английском
"""

            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=8000,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            translated = message.content[0].text

            # Кэширование результата
            self._cache[cache_key] = translated

            return translated

        except Exception as e:
            print(f"[ERROR] Перевод не удался: {e}")
            return text


# Глобальный экземпляр переводчика
_translator: Optional[LLMLanguageTranslator] = None


def get_translator() -> LLMLanguageTranslator:
    """Получить или создать переводчик."""
    global _translator
    if _translator is None:
        _translator = LLMLanguageTranslator()
    return _translator


def translate_en_to_ru(
    text: str,
    context: Optional[str] = None
) -> str:
    """
    Перевести текст с английского на русский.

    Args:
        text: Текст для перевода
        context: Контекст перевода

    Returns:
        Переведенный текст или оригинал при ошибке
    """
    translator = get_translator()
    return translator.translate(text, context)
