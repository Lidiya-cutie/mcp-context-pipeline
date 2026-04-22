"""
Context7 MCP Server Integration.

Позволяет получать актуальную документацию и примеры кода
из внешнего Context7 MCP сервера для любых библиотек.

Инструменты:
- resolve_library_id: Разрешить имя библиотеки в Context7 ID
- query_docs: Получить документацию для библиотеки
- get_library_examples: Получить примеры кода для библиотеки
"""

from mcp.server.fastmcp import FastMCP
from typing import List, Dict, Optional, Any
import subprocess
import json
import os
import re
from dataclasses import dataclass

mcp = FastMCP("Context7-MCP-Integration")


@dataclass
class LibraryInfo:
    """Информация о библиотеке."""
    library_id: str
    library_name: str
    description: Optional[str] = None
    version: Optional[str] = None


@dataclass
class DocumentationResult:
    """Результат запроса документации."""
    library: LibraryInfo
    docs: str
    examples: List[str]
    metadata: Dict[str, Any]


CONTEXT7_MCP_CONFIG = {
    "command": "npx",
    "args": ["-y", "@upstash/context7-mcp"]
}

LIBRARY_MAPPINGS = {
    "torch": {"id": "/pytorch/pytorch", "name": "PyTorch"},
    "transformers": {"id": "/huggingface/transformers", "name": "Hugging Face Transformers"},
    "diffusers": {"id": "/huggingface/diffusers", "name": "Diffusers"},
    "fastapi": {"id": "/tiangolo/fastapi", "name": "FastAPI"},
    "anthropic": {"id": "/anthropics/anthropic-sdk-python", "name": "Anthropic Python SDK"},
    "openai": {"id": "/openai/openai-python", "name": "OpenAI Python"},
    "redis": {"id": "/redis/redis-py", "name": "Redis Python"},
    "postgresql": {"id": "/psycopg/psycopg", "name": "Psycopg"},
    "pillow": {"id": "/python-pillow/Pillow", "name": "Pillow"},
    "requests": {"id": "/psf/requests", "name": "Requests"},
    "pytest": {"id": "/pytest-dev/pytest", "name": "Pytest"},
    "celery": {"id": "/celery/celery", "name": "Celery"},
    "numpy": {"id": "/numpy/numpy", "name": "NumPy"},
    "pandas": {"id": "/pandas-dev/pandas", "name": "Pandas"},
    "scipy": {"id": "/scipy/scipy", "name": "SciPy"},
    "asyncio": {"id": "/python/cpython", "name": "Python AsyncIO"},
}


def _extract_library_id_from_text(text: str) -> Optional[str]:
    """Извлечь library ID из текстового ответа Context7."""
    if not text:
        return None

    for line in text.splitlines():
        if "Context7-compatible library ID:" in line:
            value = line.split("Context7-compatible library ID:", 1)[-1].strip()
            if value:
                return value

    match = re.search(r"(/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?)", text)
    if match:
        return match.group(1)
    return None


def _call_context7_cli(tool: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Вызвать Context7 MCP через CLI.

    Args:
        tool: Имя инструмента (resolve-library-id, query-docs)
        args: Аргументы для инструмента

    Returns:
        Результат в виде словаря или None
    """
    try:
        api_key = os.environ.get("CONTEXT7_API_KEY", "")

        if tool == "resolve-library-id":
            cmd = [
                "npx", "-y", "@upstash/context7-mcp",
                "--tool", "resolve-library-id",
                "--query", args.get("query", ""),
                "--libraryName", args.get("libraryName", "")
            ]
        elif tool == "query-docs":
            cmd = [
                "npx", "-y", "@upstash/context7-mcp",
                "--tool", "query-docs",
                "--query", args.get("query", ""),
                "--library-id", args.get("libraryId", "")
            ]
        else:
            return None

        if api_key:
            cmd.extend(["--api-key", api_key])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"raw": result.stdout.strip()}
        else:
            stderr = result.stderr.strip() if result.stderr else ""
            stdout = result.stdout.strip() if result.stdout else ""
            return {
                "error": f"Context7 CLI exited with code {result.returncode}",
                "stderr": stderr,
                "raw": stdout
            }

    except subprocess.TimeoutExpired:
        print(f"[ERROR] Context7 CLI timeout")
    except Exception as e:
        print(f"[ERROR] Context7 CLI error: {e}")

    return None


@mcp.tool()
def resolve_library_id(library: str, query: str = "") -> Optional[str]:
    """
    Разрешить общее имя библиотеки в Context7 ID.

    Args:
        library: Имя библиотеки (например, 'torch', 'fastapi')
        query: Контекстный запрос для ранжирования по релевантности

    Returns:
        Context7 library ID (например, '/pytorch/pytorch') или None
    """
    library_lower = library.lower()

    if library_lower in LIBRARY_MAPPINGS:
        lib_info = LIBRARY_MAPPINGS[library_lower]
        print(f"[Context7] Resolved '{library}' to '{lib_info['id']}'")
        return lib_info["id"]

    result = _call_context7_cli(
        "resolve-library-id",
        {"library": library, "query": query}
    )

    if result and "libraryId" in result:
        library_id = result["libraryId"]
        print(f"[Context7] Resolved '{library}' to '{library_id}' via CLI")
        return library_id

    print(f"[Context7] Could not resolve library: {library}")
    return None


@mcp.tool()
def query_docs(library: str, query: str) -> Optional[Dict[str, Any]]:
    """
    Получить документацию для библиотеки.

    Args:
        library: Context7 library ID (например, '/pytorch/pytorch')
        query: Вопрос или задача для получения документации

    Returns:
        DocumentationResult с документацией и примерами кода
    """
    result = _call_context7_cli(
        "query-docs",
        {"libraryId": library, "query": query}
    )

    if not result:
        return None

    if result.get("error"):
        return {
            "status": "error",
            "library_id": library,
            "error": result.get("error"),
            "stderr": result.get("stderr", ""),
            "docs": result.get("raw", "")
        }

    if result.get("raw") and not result.get("docs"):
        docs_text = result.get("raw", "")
        return {
            "status": "ok",
            "library_id": library,
            "library_name": library,
            "docs": docs_text,
            "examples": [],
            "metadata": {"source": "Context7", "format": "raw"}
        }

    library_info = LibraryInfo(
        library_id=library,
        library_name=result.get("libraryName", library),
        description=result.get("description"),
        version=result.get("version")
    )

    docs = result.get("docs", "")
    examples = result.get("examples", [])
    metadata = {
        "version": result.get("version"),
        "last_updated": result.get("lastUpdated"),
        "source": result.get("source", "Context7")
    }

    print(f"[Context7] Retrieved docs for '{library_info.library_name}'")
    print(f"[Context7] Query: {query}")
    print(f"[Context7] Examples found: {len(examples)}")

    payload = DocumentationResult(
        library=library_info,
        docs=docs,
        examples=examples,
        metadata=metadata
    )
    return {
        "status": "ok",
        "library_id": payload.library.library_id,
        "library_name": payload.library.library_name,
        "description": payload.library.description,
        "version": payload.library.version,
        "docs": payload.docs,
        "examples": payload.examples,
        "metadata": payload.metadata
    }


@mcp.tool()
def get_library_examples(library: str, topic: str) -> List[str]:
    """
    Получить примеры кода для библиотеки.

    Args:
        library: Имя библиотеки (например, 'torch', 'fastapi')
        topic: Тема для примеров (например, 'authentication', 'tensor operations')

    Returns:
        Список примеров кода
    """
    library_id = resolve_library_id(library, topic)

    if not library_id:
        return []

    result = query_docs(library_id, f"examples code {topic}")

    if result and isinstance(result, dict) and result.get("examples"):
        return result["examples"]

    return []


@mcp.tool()
def list_supported_libraries() -> Dict[str, Dict[str, str]]:
    """
    Получить список поддерживаемых библиотек.

    Returns:
        Словарь с информацией о библиотеках
    """
    return LIBRARY_MAPPINGS


@mcp.resource("ctx7://libraries")
def get_libraries_resource() -> str:
    """
    Ресурс с информацией о поддерживаемых библиотеках.

    Returns:
        JSON строка с информацией о библиотеках
    """
    output = {
        "libraries": LIBRARY_MAPPINGS,
        "total": len(LIBRARY_MAPPINGS),
        "description": "Context7 поддерживает тысячи библиотек. Это список часто используемых."
    }
    return json.dumps(output, indent=2)


@mcp.tool()
def quick_query(library: str, topic: str) -> str:
    """
    Быстрый запрос документации.

    Args:
        library: Имя библиотеки
        topic: Тема для запроса

    Returns:
        Документация или сообщение об ошибке
    """
    library_id = resolve_library_id(library, "")

    if not library_id:
        return f"Библиотека '{library}' не найдена"

    result = query_docs(library_id, topic)

    if not result or result.get("status") != "ok":
        return f"Не удалось получить документацию для '{library}' по теме '{topic}'"

    output = f"# {result.get('library_name', library)}\n\n"
    output += f"{result.get('docs', '')}\n\n"

    examples = result.get("examples", [])
    if examples:
        output += "## Примеры кода\n\n"
        for i, ex in enumerate(examples[:5], 1):
            output += f"### Пример {i}\n```python\n{ex}\n```\n\n"

    return output


@mcp.tool()
def get_best_practices(library: str) -> str:
    """
    Получить лучшие практики для библиотеки.

    Args:
        library: Имя библиотеки

    Returns:
        Текст с лучшими практиками
    """
    library_id = resolve_library_id(library, "best practices")

    if not library_id:
        return f"Библиотека '{library}' не найдена"

    result = query_docs(library_id, "best practices patterns recommended")

    if not result or result.get("status") != "ok":
        return f"Не удалось получить лучшие практики для '{library}'"

    return result.get("docs", "")


@mcp.tool()
def check_version_compatibility(library: str, version: str) -> Dict[str, Any]:
    """
    Проверить совместимость версии библиотеки.

    Args:
        library: Имя библиотеки
        version: Версия для проверки

    Returns:
        Информация о совместимости
    """
    library_id = resolve_library_id(library, f"version {version}")

    if not library_id:
        return {"status": "error", "message": f"Библиотека '{library}' не найдена"}

    result = query_docs(library_id, f"version {version} compatibility migration")

    if not result or result.get("status") != "ok":
        return {"status": "unknown", "message": "Не удалось проверить версию"}

    return {
        "status": "checked",
        "library": result.get("library_name", library),
        "current_version": result.get("version"),
        "requested_version": version,
        "docs": (
            result.get("docs", "")[:500] + "..."
            if len(result.get("docs", "")) > 500
            else result.get("docs", "")
        )
    }


if __name__ == "__main__":
    mcp.run()
