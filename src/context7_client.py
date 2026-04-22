"""
Context7 MCP клиент для интеграции документации.

Обеспечивает доступ к документации через Context7 MCP сервер.
"""

import os
import asyncio
import re
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

from mcp import ClientSession, stdio_client
from mcp.client.stdio import StdioServerParameters

from translator import translate_en_to_ru


class Context7Client:
    """Клиент для Context7 MCP сервера."""

    def __init__(self):
        """Инициализация клиента."""
        self.api_key = os.getenv("CONTEXT7_API_KEY", "")
        self.session: Optional[ClientSession] = None
        self.ctx: Optional[stdio_client] = None
        self._connected = False

    async def connect(self) -> bool:
        """Подключение к Context7 MCP серверу."""
        if self._connected:
            return True

        try:
            server_params = StdioServerParameters(
                command='npx',
                args=['-y', '@upstash/context7-mcp'] + (['--api-key', self.api_key] if self.api_key else [])
            )
            self.ctx = stdio_client(server_params)
            read_stream, write_stream = await self.ctx.__aenter__()
            self.session = ClientSession(read_stream, write_stream)
            await self.session.__aenter__()
            await self.session.initialize()
            self._connected = True
            return True
        except Exception as e:
            print(f"[ERROR] Context7 connection failed: {e}")
            return False

    async def disconnect(self):
        """Отключение от Context7 MCP сервера."""
        if self._connected and self.session:
            try:
                await self.session.__aexit__(None, None, None)
            except:
                pass
            self.session = None
        if self.ctx:
            try:
                await self.ctx.__aexit__(None, None, None)
            except:
                pass
            self.ctx = None
        self._connected = False

    async def resolve_library_id(self, library_name: str, query: Optional[str] = None) -> Optional[str]:
        """Разрешить идентификатор библиотеки."""
        if not self.session:
            await self.connect()

        try:
            arguments = {
                "libraryName": library_name,
                "query": query or f"Find documentation for {library_name}"
            }
            result = await self.session.call_tool('resolve-library-id', arguments=arguments)
            if result.content:
                content = result.content[0]
                if hasattr(content, "text"):
                    text = content.text or ""
                    marker = "Context7-compatible library ID:"
                    for line in text.splitlines():
                        if marker in line:
                            value = line.split(marker, 1)[-1].strip()
                            if value:
                                return value
                    match = re.search(r"(/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?)", text)
                    if match:
                        return match.group(1)
                elif isinstance(content, dict):
                    return content.get("libraryId") or content.get("id")
        except Exception as e:
            print(f"[ERROR] Library resolution failed: {e}")
        return None

    async def query_docs(
        self,
        library_id: str,
        query: str,
        translate: bool = True,
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Запрос документации с переводом.

        Args:
            library_id: Идентификатор библиотеки
            query: Поисковый запрос
            translate: Перевести результат на русский
            context: Контекст для перевода

        Returns:
            Словарь с результатом и статусом перевода
        """
        if not self.session:
            await self.connect()

        try:
            result = await self.session.call_tool(
                'query-docs',
                arguments={'libraryId': library_id, 'query': query}
            )

            if not result.content:
                return {"status": "no_content", "content": None}

            content_item = result.content[0]
            if hasattr(content_item, "text"):
                content = content_item.text or ""
            elif isinstance(content_item, dict):
                content = content_item.get("docs", "") or str(content_item)
            else:
                content = str(content_item)

            if "not found" in content.lower() and "library" in content.lower():
                return {"status": "error", "error": content}

            if translate and content:
                translated = translate_en_to_ru(content, context=context)
                return {
                    "status": "success",
                    "content": content,
                    "translated": translated,
                    "translated_to_ru": True
                }

            return {
                "status": "success",
                "content": content,
                "translated": None,
                "translated_to_ru": False
            }

        except Exception as e:
            print(f"[ERROR] Documentation query failed: {e}")
            return {"status": "error", "error": str(e)}


# Глобальный экземпляр клиента
_context7_client: Optional[Context7Client] = None


async def get_context7_client() -> Context7Client:
    """Получить или создать клиент Context7."""
    global _context7_client
    if _context7_client is None:
        _context7_client = Context7Client()
        await _context7_client.connect()
    return _context7_client
