from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import subprocess
import urllib.request
import urllib.error
from html import unescape
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .base import BaseExternalKnowledgeProvider, KnowledgeChunk


def _get_proxy_handler():
    """Получить обработчик прокси для urllib если настроен."""
    proxy_url = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("ALL_PROXY")
    if proxy_url:
        return urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    return urllib.request.ProxyHandler({})


def _get_opener():
    """Получить opener с поддержкой прокси."""
    return urllib.request.build_opener(_get_proxy_handler())


def _extract_mcp_text_chunks(content_items: List[Any]) -> List[str]:
    chunks: List[str] = []
    for item in content_items:
        if hasattr(item, "text"):
            chunks.append(item.text)
        elif isinstance(item, dict):
            chunks.append(json.dumps(item, ensure_ascii=False))
        else:
            chunks.append(str(item))
    return chunks


def _extract_context7_library_id(text: str) -> Optional[str]:
    marker = "Context7-compatible library ID:"
    for line in text.splitlines():
        if marker in line:
            value = line.split(marker, 1)[-1].strip()
            if value:
                return value
    return None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _keyword_match_ratio(query: str, text: str) -> float:
    tokens = [token.strip().lower() for token in query.split() if token.strip()]
    if not tokens:
        return 0.0
    hay = text.lower()
    matched = sum(1 for token in tokens if token in hay)
    return matched / len(tokens)


class JsonHttpProvider(BaseExternalKnowledgeProvider):
    def __init__(self, name: str, timeout_seconds: int = 20):
        super().__init__(name)
        self.timeout_seconds = timeout_seconds

    async def _post_json(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, Any]]:
        def _do_post() -> Optional[Dict[str, Any]]:
            req_headers = {"Content-Type": "application/json"}
            if headers:
                req_headers.update(headers)

            body = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                url=url,
                data=body,
                headers=req_headers,
                method="POST"
            )
            try:
                opener = _get_opener()
                with opener.open(request, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    if not raw.strip():
                        return None
                    return json.loads(raw)
            except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
                return None

        return await asyncio.to_thread(_do_post)


class Context7Provider(BaseExternalKnowledgeProvider):
    def __init__(self, session: ClientSession):
        super().__init__("context7")
        self.session = session

    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[KnowledgeChunk]:
        if not self.session:
            return []

        library_name = (context or {}).get("library")
        if not library_name:
            return []

        resolve_result = await self.session.call_tool(
            "resolve-library-id",
            arguments={"libraryName": library_name, "query": query}
        )
        resolve_text = "\n".join(_extract_mcp_text_chunks(resolve_result.content or []))
        library_id = _extract_context7_library_id(resolve_text)
        if not library_id:
            return []

        docs_result = await self.session.call_tool(
            "query-docs",
            arguments={"libraryId": library_id, "query": query}
        )
        docs_text = "\n".join(_extract_mcp_text_chunks(docs_result.content or []))
        if not docs_text.strip():
            return []

        return [
            KnowledgeChunk(
                title=f"Context7 docs: {library_name}",
                content=docs_text,
                source=self.name,
                score=0.92,
                metadata={"library": library_name, "library_id": library_id}
            )
        ][:limit]


class TavilyProvider(JsonHttpProvider):
    def __init__(self):
        super().__init__("tavily")
        self.enabled = os.getenv("ENABLE_TAVILY_PROVIDER", "true").lower() == "true"
        self.api_key = os.getenv("TAVILY_API_KEY", "")
        self.api_url = os.getenv("TAVILY_API_URL", "https://api.tavily.com/search")

    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[KnowledgeChunk]:
        if not self.enabled or not self.api_key:
            return []

        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max(1, min(limit, 10)),
            "include_answer": False,
            "include_raw_content": False,
        }
        data = await self._post_json(self.api_url, payload)
        if not data:
            return []

        results = data.get("results", [])
        chunks: List[KnowledgeChunk] = []
        for item in results[:limit]:
            content = item.get("content", "") or item.get("raw_content", "")
            if not content:
                continue
            chunks.append(
                KnowledgeChunk(
                    title=item.get("title", "Tavily result"),
                    content=content,
                    source=self.name,
                    score=_to_float(item.get("score"), 0.82),
                    url=item.get("url"),
                    metadata={"provider": "tavily"},
                )
            )
        return chunks


class ExaProvider(JsonHttpProvider):
    def __init__(self):
        super().__init__("exa")
        self.enabled = os.getenv("ENABLE_EXA_PROVIDER", "true").lower() == "true"
        self.api_key = os.getenv("EXA_API_KEY", "")
        self.api_url = os.getenv("EXA_API_URL", "https://api.exa.ai/search")

    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[KnowledgeChunk]:
        if not self.enabled or not self.api_key:
            return []

        payload = {
            "query": query,
            "numResults": max(1, min(limit, 10)),
            "useAutoprompt": True,
            "contents": {"text": {"maxCharacters": 4000}},
        }
        headers = {"x-api-key": self.api_key}
        data = await self._post_json(self.api_url, payload, headers=headers)
        if not data:
            return []

        results = data.get("results") or data.get("data") or []
        chunks: List[KnowledgeChunk] = []
        for item in results[:limit]:
            content = item.get("text") or item.get("snippet") or ""
            if not content:
                highlights = item.get("highlights") or []
                if highlights and isinstance(highlights, list):
                    content = "\n".join(str(h) for h in highlights[:5])
            if not content:
                continue
            chunks.append(
                KnowledgeChunk(
                    title=item.get("title", "Exa result"),
                    content=content,
                    source=self.name,
                    score=_to_float(item.get("score"), 0.80),
                    url=item.get("url"),
                    metadata={"provider": "exa"},
                )
            )
        return chunks


class FirecrawlProvider(JsonHttpProvider):
    def __init__(self):
        super().__init__("firecrawl")
        self.enabled = os.getenv("ENABLE_FIRECRAWL_PROVIDER", "true").lower() == "true"
        self.api_key = os.getenv("FIRECRAWL_API_KEY", "")
        self.api_url = os.getenv("FIRECRAWL_API_URL", "https://api.firecrawl.dev/v1/search")

    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[KnowledgeChunk]:
        if not self.enabled or not self.api_key:
            return []

        payload = {
            "query": query,
            "limit": max(1, min(limit, 10)),
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        data = await self._post_json(self.api_url, payload, headers=headers)
        if not data:
            return []

        results = data.get("data") or data.get("results") or []
        chunks: List[KnowledgeChunk] = []
        for item in results[:limit]:
            content = item.get("markdown") or item.get("content") or item.get("description") or ""
            if not content:
                continue
            chunks.append(
                KnowledgeChunk(
                    title=item.get("title", "Firecrawl result"),
                    content=content,
                    source=self.name,
                    score=_to_float(item.get("score"), 0.78),
                    url=item.get("url"),
                    metadata={"provider": "firecrawl"},
                )
            )
        return chunks


class ShivaProvider(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("shiva")
        self.enabled = os.getenv("ENABLE_SHIVA_PROVIDER", "false").lower() == "true"
        self.mcp_url = os.getenv("SHIVA_MCP_URL", "https://shiva.imbalanced.tech/shiva-mcp/v0").strip()
        self.api_token = os.getenv("SHIVA_MCP_TOKEN", "").strip()
        self.default_project_id = os.getenv("SHIVA_DEFAULT_PROJECT_ID", "").strip()

    def _is_enabled(self) -> bool:
        return bool(self.enabled and self.mcp_url and self.api_token)

    async def _call_tool_text(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        if not self._is_enabled():
            return ""
        headers = {
            "Authorization": f"Bearer {self.api_token}",
        }
        async with streamablehttp_client(self.mcp_url, headers=headers) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments or {})
        return "\n".join(_extract_mcp_text_chunks(result.content or []))

    def _resolve_project_id(self, context: Optional[Dict[str, Any]]) -> Optional[int]:
        value = (context or {}).get("project_id") or (context or {}).get("shiva_project_id") or self.default_project_id
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[KnowledgeChunk]:
        if not self._is_enabled():
            return []

        query_lower = query.lower()
        project_id = self._resolve_project_id(context)
        calls: List[Dict[str, Any]] = []

        if project_id is not None:
            calls.append({"tool": "shiva_get_prjct_summary", "args": {"id": project_id}})
            calls.append(
                {
                    "tool": "shiva_get_prjct_overview",
                    "args": {"projectId": project_id, "participantsTop": 10, "statusesTop": 10},
                }
            )
        elif any(token in query_lower for token in ("команд", "team")):
            calls.append({"tool": "shiva_list_teams", "args": {}})
        elif any(token in query_lower for token in ("профил", "profile", "мой", "my profile")):
            calls.append({"tool": "shiva_get_my_profile", "args": {}})
        elif any(token in query_lower for token in ("спринт", "sprint")) and project_id is not None:
            now = datetime.now(timezone.utc)
            date_to = now.isoformat().replace("+00:00", "Z")
            date_from = (now.replace(microsecond=0) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
            calls.append(
                {
                    "tool": "shiva_get_prjct_sprint_report",
                    "args": {"idProject": project_id, "dateFrom": date_from, "dateTo": date_to},
                }
            )
        else:
            calls.append({"tool": "shiva_list_prjcts", "args": {}})

        chunks: List[KnowledgeChunk] = []
        for idx, call in enumerate(calls[: max(1, min(limit, 3))], 1):
            try:
                text = await self._call_tool_text(call["tool"], call["args"])
            except Exception:
                continue
            if not text.strip():
                continue
            chunks.append(
                KnowledgeChunk(
                    title=f"SHIVA: {call['tool']}",
                    content=text,
                    source=self.name,
                    score=max(0.65, 0.92 - (idx * 0.03)),
                    url=self.mcp_url,
                    metadata={
                        "tool": call["tool"],
                        "project_id": project_id,
                    },
                )
            )
        return chunks[:limit]


class DocFusionProvider(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("docfusion")
        self.enabled = os.getenv("ENABLE_DOCFUSION_PROVIDER", "false").lower() == "true"
        self.api_token = os.getenv("DOCFUSION_TOKEN", "").strip() or os.getenv("SHIVA_MCP_TOKEN", "").strip()
        raw_urls = os.getenv("DOCFUSION_KB_URLS", "").strip()
        default_urls = [
            "https://docfusion.imbalanced.tech/kb/frontend/1250af63-bdf9-42b1-8d2a-40d0e2d94d35",
            "https://docfusion.imbalanced.tech/folder/18a9d63c-2305-4999-bf9a-9573565fc576/kb",
            "https://docops-prod.imbalanced.tech/#/guide/Regulations-and-agreements/594?documentName=Document+Catalog.md&path=Document+Catalog.md&branch=main&type=text/markdown&webUrl=https://git.imbalanced.tech/government/agreements-policies-regulations/-/blob/main/Document%2520Catalog.md?ref_type=heads",
        ]
        if raw_urls:
            self.urls = [item.strip() for item in raw_urls.split(",") if item.strip()]
        else:
            self.urls = default_urls
        self._doc_cache: Dict[str, str] = {}

    def _is_enabled(self) -> bool:
        return bool(self.enabled and self.urls)

    @staticmethod
    def _strip_html(content: str) -> str:
        no_script = re.sub(r"(?is)<script.*?>.*?</script>", " ", content)
        no_style = re.sub(r"(?is)<style.*?>.*?</style>", " ", no_script)
        no_tags = re.sub(r"(?is)<[^>]+>", " ", no_style)
        normalized = re.sub(r"\s+", " ", no_tags).strip()
        return unescape(normalized)

    async def _fetch_url_text(self, url: str) -> str:
        def _do_fetch() -> str:
            headers = {}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            request = urllib.request.Request(url=url, headers=headers, method="GET")
            opener = _get_opener()
            with opener.open(request, timeout=20) as response:
                body = response.read().decode("utf-8", errors="ignore")
                stripped = self._strip_html(body)
                if stripped:
                    return stripped
                # SPA fallback: return raw HTML shell if no textual body is available.
                return body[:4000]

        return await asyncio.to_thread(_do_fetch)

    async def _load_doc(self, url: str) -> str:
        if url in self._doc_cache:
            return self._doc_cache[url]
        try:
            text = await self._fetch_url_text(url)
            if text:
                self._doc_cache[url] = text
            return text
        except Exception:
            return ""

    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[KnowledgeChunk]:
        if not self._is_enabled():
            return []

        scored: List[KnowledgeChunk] = []
        loaded_docs: List[KnowledgeChunk] = []
        for url in self.urls:
            text = await self._load_doc(url)
            if not text:
                continue
            snippet = text[:4000]
            loaded_docs.append(
                KnowledgeChunk(
                    title=f"DocFusion: {url}",
                    content=snippet,
                    source=self.name,
                    score=0.40,
                    url=url,
                    metadata={"provider": "docfusion"},
                )
            )
            score = _keyword_match_ratio(query, text[:12000])
            if score <= 0.0:
                continue
            scored.append(
                KnowledgeChunk(
                    title=f"DocFusion: {url}",
                    content=snippet,
                    source=self.name,
                    score=min(0.95, 0.55 + score),
                    url=url,
                    metadata={"provider": "docfusion"},
                )
            )

        scored.sort(key=lambda chunk: chunk.score, reverse=True)
        if scored:
            return scored[: max(1, min(limit, len(scored)))]
        if loaded_docs:
            return loaded_docs[: max(1, min(limit, len(loaded_docs)))]
        return []


class LocalIndexProvider(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("local_index")
        self.enabled = os.getenv("ENABLE_LOCAL_INDEX_PROVIDER", "true").lower() == "true"
        self.db_path = os.getenv(
            "EXTERNAL_LOCAL_INDEX_DB_PATH",
            "/mldata/mcp_context_pipeline/data/external_knowledge_index.db"
        )
        self.bootstrap_dir = os.getenv("EXTERNAL_LOCAL_INDEX_BOOTSTRAP_DIR", "").strip()
        self._fts_available = False
        if self.enabled:
            self._ensure_db()
            if self.bootstrap_dir:
                self._bootstrap_from_directory(self.bootstrap_dir)

    def _ensure_db(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    url TEXT,
                    source TEXT DEFAULT 'local',
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
                USING fts5(title, content, content='documents', content_rowid='id')
                """
            )
            cur.execute(
                """
                CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
                  INSERT INTO documents_fts(rowid, title, content)
                  VALUES (new.id, new.title, new.content);
                END;
                """
            )
            cur.execute(
                """
                CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
                  INSERT INTO documents_fts(documents_fts, rowid, title, content)
                  VALUES('delete', old.id, old.title, old.content);
                END;
                """
            )
            cur.execute(
                """
                CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
                  INSERT INTO documents_fts(documents_fts, rowid, title, content)
                  VALUES('delete', old.id, old.title, old.content);
                  INSERT INTO documents_fts(rowid, title, content)
                  VALUES (new.id, new.title, new.content);
                END;
                """
            )
            conn.commit()
            conn.close()
            self._fts_available = True
        except Exception:
            self._fts_available = False
            self.enabled = False

    def _bootstrap_from_directory(self, directory: str) -> None:
        if not os.path.isdir(directory):
            return
        docs = []
        for root, _, files in os.walk(directory):
            for file_name in files:
                if not file_name.lower().endswith((".txt", ".rst", ".json", ".py")):
                    continue
                path = os.path.join(root, file_name)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    if not content:
                        continue
                    title = os.path.relpath(path, directory)
                    docs.append(
                        {
                            "title": title,
                            "content": content[:20000],
                            "url": None,
                            "source": "local_bootstrap",
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                except Exception:
                    continue
        if docs:
            self._upsert_documents_sync(docs)

    def _upsert_documents_sync(self, documents: List[Dict[str, Any]]) -> None:
        if not self._fts_available:
            return
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        for doc in documents:
            cur.execute(
                """
                INSERT INTO documents (title, content, url, source, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    doc.get("title", "Untitled"),
                    doc.get("content", ""),
                    doc.get("url"),
                    doc.get("source", "local"),
                    doc.get("updated_at") or datetime.now(timezone.utc).isoformat(),
                ),
            )
        conn.commit()
        conn.close()

    async def ingest_documents(self, documents: List[Dict[str, Any]]) -> int:
        if not self.enabled or not self._fts_available or not documents:
            return 0
        await asyncio.to_thread(self._upsert_documents_sync, documents)
        return len(documents)

    def _query_sync(self, query: str, limit: int) -> List[KnowledgeChunk]:
        if not self._fts_available:
            return []
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT d.title, d.content, d.url, d.source, d.updated_at, bm25(documents_fts) as rank
                FROM documents_fts
                JOIN documents d ON d.id = documents_fts.rowid
                WHERE documents_fts MATCH ?
                ORDER BY rank ASC
                LIMIT ?
                """,
                (query, max(1, min(limit, 20))),
            )
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            conn.close()

        chunks: List[KnowledgeChunk] = []
        for row in rows:
            title, content, url, source, updated_at, rank = row
            rank_value = abs(float(rank)) if rank is not None else 1.0
            score = 1.0 / (1.0 + rank_value)
            chunks.append(
                KnowledgeChunk(
                    title=title,
                    content=content,
                    source=self.name,
                    score=score,
                    url=url,
                    updated_at=updated_at,
                    metadata={"origin_source": source, "bm25_rank": rank},
                )
            )
        return chunks

    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[KnowledgeChunk]:
        if not self.enabled or not self._fts_available:
            return []
        return await asyncio.to_thread(self._query_sync, query, limit)


class KnowledgeBridgeProvider(BaseExternalKnowledgeProvider):
    def __init__(self, session: ClientSession):
        super().__init__("knowledge_bridge")
        self.session = session

    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[KnowledgeChunk]:
        if not self.session:
            return []

        domain = (context or {}).get("domain", "python")
        result = await self.session.call_tool(
            "search_standard",
            arguments={"domain": domain, "topic": query}
        )
        text = "\n".join(_extract_mcp_text_chunks(result.content or []))
        if not text.strip():
            return []

        return [
            KnowledgeChunk(
                title=f"Knowledge Bridge standard: {domain}",
                content=text,
                source=self.name,
                score=0.88,
                metadata={"domain": domain}
            )
        ][:limit]


class GitHubProvider(BaseExternalKnowledgeProvider):
    def __init__(self):
        super().__init__("github")
        self.enabled = os.getenv("ENABLE_GITHUB_PROVIDER", "false").lower() == "true"

    async def _run(self, command: List[str]) -> subprocess.CompletedProcess:
        return await asyncio.to_thread(
            subprocess.run,
            command,
            capture_output=True,
            text=True,
            timeout=20
        )

    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[KnowledgeChunk]:
        if not self.enabled:
            return []

        repo = (context or {}).get("repo")
        if not repo:
            return []

        command = [
            "gh", "api",
            "search/code",
            "-f", f"q={query} repo:{repo}",
            "-f", f"per_page={max(1, min(limit, 10))}",
        ]
        result = await self._run(command)
        if result.returncode != 0:
            return []

        try:
            payload = json.loads(result.stdout)
            items = payload.get("items", [])
        except json.JSONDecodeError:
            return []

        chunks: List[KnowledgeChunk] = []
        for item in items[:limit]:
            path = item.get("path", "")
            html_url = item.get("html_url")
            repository = item.get("repository", {}).get("full_name", repo)
            chunks.append(
                KnowledgeChunk(
                    title=f"{repository}:{path}",
                    content=f"Найдено совпадение в репозитории {repository}, файл {path}",
                    source=self.name,
                    score=0.8,
                    url=html_url,
                    metadata={"repo": repository, "path": path}
                )
            )
        return chunks
