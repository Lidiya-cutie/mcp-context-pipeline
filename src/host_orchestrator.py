"""
Host Orchestrator for MCP Context Pipeline.
This is the "brain" of the solution. It runs on the client side (Windows/Client app).
Implements AC1 (automatic compression) logic and manages communication with MCP server.

In production, this code would be part of your Backend service (Python/Go).

Updated for MCP 1.27.0+ with new async client API.
"""

import asyncio
import ast
import json
import os
import sys
from contextlib import AsyncExitStack
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# MCP Client imports
from mcp import ClientSession, stdio_client

# Local imports
try:
    from .utils import count_tokens, generate_session_id
    from .translator import translate_en_to_ru
    from .external_knowledge import (
        ExternalKnowledgeRouter,
        Context7Provider,
        KnowledgeBridgeProvider,
        GitHubProvider,
        TavilyProvider,
        ExaProvider,
        FirecrawlProvider,
        LocalIndexProvider,
        ShivaProvider,
        DocFusionProvider,
    )
except ImportError:
    from utils import count_tokens, generate_session_id
    from translator import translate_en_to_ru
    from external_knowledge import (
        ExternalKnowledgeRouter,
        Context7Provider,
        KnowledgeBridgeProvider,
        GitHubProvider,
        TavilyProvider,
        ExaProvider,
        FirecrawlProvider,
        LocalIndexProvider,
        ShivaProvider,
        DocFusionProvider,
    )


def _resolve_script_path(path: str) -> str:
    """
    Нормализует относительный путь к скрипту так, чтобы запуск работал
    как из корня проекта, так и из директории src.
    """
    if os.path.isabs(path):
        return path

    module_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(module_dir)
    cwd = os.getcwd()

    candidates = [
        os.path.abspath(os.path.join(cwd, path)),
        os.path.abspath(os.path.join(module_dir, path)),
        os.path.abspath(os.path.join(project_root, path)),
    ]

    if path.startswith("src/"):
        trimmed = path.split("src/", 1)[1]
        candidates.append(os.path.abspath(os.path.join(module_dir, trimmed)))

    checked = set()
    for candidate in candidates:
        if candidate in checked:
            continue
        checked.add(candidate)
        if os.path.exists(candidate):
            return candidate

    # fallback: первый вариант (из cwd), если файл еще не создан
    return candidates[0]


class ContextOrchestrator:
    """
    Orchestrator for managing conversation context with automatic compression.

    Features:
    - AC1: Automatic context compression when exceeding threshold
    - AC2: Tool-based compression via MCP
    - AC3: Timestamp injection for temporal context
    - AC4: Session state checkpointing
    - Knowledge Bridge: Integration with Context 7
    """

    def __init__(
        self,
        server_script: str = "src/server.py",
        max_tokens: int = 128000,
        summary_threshold: int = 100000,
        enable_knowledge_bridge: bool = False,
        knowledge_server_script: str = "src/knowledge_server.py",
        enable_context7: bool = False,
        context7_server_script: str = "src/context7_mcp_server.py",
        enable_external_knowledge: bool = True
    ):
        """
        Initialize the Context Orchestrator.

        Args:
            server_script: Path to MCP server script
            max_tokens: Maximum allowed tokens before compression
            summary_threshold: Token threshold that triggers auto-compression
            enable_knowledge_bridge: Enable Context 7 knowledge bridge
            knowledge_server_script: Path to knowledge bridge MCP server
            enable_context7: Enable Context7 MCP for library docs
            context7_server_script: Path to Context7 MCP server script
            enable_external_knowledge: Enable provider router for external knowledge
        """
        self.server_script = _resolve_script_path(server_script)
        self.session: Optional[ClientSession] = None
        self.context_history: List[Dict[str, str]] = []
        self.system_prompt = "You are a helpful assistant."
        self.max_tokens = max_tokens
        self.summary_threshold = summary_threshold
        self.session_id = generate_session_id()
        self.compression_count = 0
        self.connected = False
        self._exit_stack: Optional[AsyncExitStack] = None
        self._read_stream = None
        self._write_stream = None

        self.enable_knowledge_bridge = enable_knowledge_bridge
        self.knowledge_server_script = _resolve_script_path(knowledge_server_script)
        self.knowledge_session: Optional[ClientSession] = None
        self._knowledge_read_stream = None
        self._knowledge_write_stream = None

        self.enable_context7 = enable_context7
        self.context7_server_script = _resolve_script_path(context7_server_script)
        self.context7_session: Optional[ClientSession] = None
        self._context7_read_stream = None
        self._context7_write_stream = None
        self.enable_external_knowledge = enable_external_knowledge
        self.external_knowledge_router: Optional[ExternalKnowledgeRouter] = None

    async def connect(self):
        """
        Connect to MCP server via stdio (locally) or SSE (remotely).

        For local development on Windows: uses stdio
        For remote production: would use SSE connection
        """
        try:
            from mcp.client.stdio import StdioServerParameters

            if self._exit_stack is not None:
                await self.disconnect()

            self._exit_stack = AsyncExitStack()

            # Create stdio client parameters
            server_params = StdioServerParameters(
                command=sys.executable,
                args=[self.server_script]
            )

            # Enter stdio and client session via a single AsyncExitStack
            self._read_stream, self._write_stream = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            self.session = await self._exit_stack.enter_async_context(
                ClientSession(self._read_stream, self._write_stream)
            )
            await self.session.initialize()

            # Initialize resources (AC3: Timestamp)
            await self._inject_timestamp()

            self.connected = True
            print(f"[INFO] Connected to MCP server. Session ID: {self.session_id}")

            # Connect to Knowledge Bridge if enabled
            if self.enable_knowledge_bridge:
                await self._connect_knowledge_bridge()

            # Connect to Context7 if enabled
            if self.enable_context7:
                await self._connect_context7()

            if self.enable_external_knowledge:
                self._initialize_external_knowledge_router()

        except Exception as e:
            print(f"[ERROR] Failed to connect to MCP server: {e}")
            import traceback
            traceback.print_exc()
            self.connected = False
            if self._exit_stack is not None:
                try:
                    await self._exit_stack.aclose()
                except BaseException:
                    pass
                self._exit_stack = None
            raise

    async def _connect_knowledge_bridge(self):
        """Connect to Knowledge Bridge MCP server."""
        try:
            from mcp.client.stdio import StdioServerParameters

            server_params = StdioServerParameters(
                command=sys.executable,
                args=[self.knowledge_server_script]
            )

            if self._exit_stack is None:
                self._exit_stack = AsyncExitStack()

            self._knowledge_read_stream, self._knowledge_write_stream = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            self.knowledge_session = await self._exit_stack.enter_async_context(
                ClientSession(
                    self._knowledge_read_stream,
                    self._knowledge_write_stream
                )
            )
            await self.knowledge_session.initialize()

            print("[INFO] Connected to Knowledge Bridge (Context 7)")

            # Enhance system prompt with Context 7 knowledge
            await self._enhance_system_prompt_with_context7()

        except Exception as e:
            print(f"[WARN] Failed to connect to Knowledge Bridge: {e}")
            self.knowledge_session = None

    async def _connect_context7(self):
        """Connect to Context7 MCP server."""
        try:
            from mcp.client.stdio import StdioServerParameters

            api_key = os.environ.get("CONTEXT7_API_KEY", "")

            server_params = StdioServerParameters(
                command="npx",
                args=["-y", "@upstash/context7-mcp"] + (["--api-key", api_key] if api_key else [])
            )

            if self._exit_stack is None:
                self._exit_stack = AsyncExitStack()

            self._context7_read_stream, self._context7_write_stream = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            self.context7_session = await self._exit_stack.enter_async_context(
                ClientSession(
                    self._context7_read_stream,
                    self._context7_write_stream
                )
            )
            await self.context7_session.initialize()

            print("[INFO] Connected to Context7 MCP")

            # Enhance system prompt with Context7 instructions
            self.system_prompt += """

--- CONTEXT7 MCP ---
When you need documentation, examples, or best practices for libraries:
Use Context7 tools directly (resolve-library-id, query-docs).
Supported libraries: torch, transformers, diffusers, fastapi, anthropic, openai, redis, postgresql, pillow, requests, pytest, celery, numpy, pandas, scipy.

Example: "How do I implement JWT authentication in FastAPI?" → use Context7 for up-to-date FastAPI docs.
"""

        except Exception as e:
            print(f"[WARN] Failed to connect to Context7: {e}")
            self.context7_session = None

    def _initialize_external_knowledge_router(self):
        """Инициализировать единый роутер внешних знаний."""
        providers = []

        if self.context7_session is not None:
            providers.append(Context7Provider(self.context7_session))

        if self.knowledge_session is not None:
            providers.append(KnowledgeBridgeProvider(self.knowledge_session))

        providers.append(LocalIndexProvider())
        providers.append(ShivaProvider())
        providers.append(DocFusionProvider())
        providers.append(TavilyProvider())
        providers.append(ExaProvider())
        providers.append(FirecrawlProvider())
        providers.append(GitHubProvider())

        if not providers:
            print("[WARN] External knowledge providers are unavailable")
            self.external_knowledge_router = None
            return

        self.external_knowledge_router = ExternalKnowledgeRouter(
            providers=providers,
            cache_ttl_seconds=int(os.getenv("EXTERNAL_KNOWLEDGE_CACHE_TTL", "3600"))
        )
        print(f"[INFO] External knowledge router initialized with providers: {', '.join([p.name for p in providers])}")

    async def _enhance_system_prompt_with_context7(self):
        """Enhance system prompt with Context 7 knowledge."""
        try:
            if not self.knowledge_session:
                return

            tech_stack_res = await self.knowledge_session.read_resource("kb://tech_stack")
            arch_principles_res = await self.knowledge_session.read_resource("kb://architecture/principles")

            context7_knowledge = ""

            if tech_stack_res.contents:
                context7_knowledge += f"\n\n{tech_stack_res.contents[0].text}\n"

            if arch_principles_res.contents:
                context7_knowledge += f"\n\n{arch_principles_res.contents[0].text}\n"

            self.system_prompt += """
\n\n--- CONTEXT 7 KNOWLEDGE ---
When generating code or architecture:
1. Use 'search_standard' tool for specific implementation rules
2. Check Context 7 for company standards before making decisions
3. If Context 7 has no info, use industry best practices
4. Never hallucinate internal standards
"""
            self.system_prompt += context7_knowledge

            print("[INFO] System prompt enhanced with Context 7 knowledge")

        except Exception as e:
            print(f"[WARN] Failed to enhance system prompt: {e}")

    async def _inject_timestamp(self):
        """
        AC3: Get current time and inject into system prompt.
        Provides temporal context to the agent.
        """
        try:
            time_res = await self.session.read_resource("time://current")
            if time_res.contents:
                timestamp = time_res.contents[0].text
                self.system_prompt += f"\n\n{timestamp}"
                print(f"[DEBUG] Time injected: {timestamp}")
        except Exception as e:
            print(f"[ERROR] Failed to inject time: {e}")

    async def _get_context_limits(self) -> Dict[str, int]:
        """Get context limits from server resource."""
        try:
            limits_res = await self.session.read_resource("context://limits")
            if limits_res.contents:
                limits = json.loads(limits_res.contents[0].text)
                print(f"[DEBUG] Context limits: {limits}")
                return limits
        except Exception as e:
            print(f"[WARN] Failed to get context limits: {e}")
        return {
            "max_tokens": self.max_tokens,
            "summary_threshold": self.summary_threshold
        }

    async def _check_context_overflow(self):
        """
        AC1: Automatic summarization when exceeding threshold.
        Implements proactive context management.
        """
        # Estimate current context size
        current_text = "\n".join([m["content"] for m in self.context_history])
        tokens = count_tokens(current_text)

        print(f"[INFO] Current context tokens: {tokens} / {self.summary_threshold} (threshold)")

        # Use orchestrator's threshold first (for testing), fallback to server limits
        threshold = self.summary_threshold

        if tokens >= threshold:
            print(f"[WARN] Context overflow! Triggering auto-summarization...")
            await self._compress_oldest_messages()

    async def _compress_oldest_messages(self):
        """
        Compress the oldest messages in the conversation history.
        Replaces old messages with a summary from the MCP server.
        """
        try:
            # Take oldest messages (first 50% or configurable)
            split_idx = len(self.context_history) // 2
            old_messages = [m["content"] for m in self.context_history[:split_idx]]

            print(f"[INFO] Compressing {len(old_messages)} oldest messages...")

            # Call MCP tool for compression
            result = await self.session.call_tool(
                "compress_context",
                arguments={
                    "messages": old_messages,
                    "session_id": self.session_id
                }
            )

            if result.content:
                content = result.content[0]

                if hasattr(content, 'text'):
                    result_data = content.text
                elif isinstance(content, dict):
                    result_data = content
                else:
                    result_data = str(content)

                # Check if compression succeeded
                compression_succeeded = False
                summary_text = ""

                # Parse JSON if result_data is a string
                if isinstance(result_data, str) and result_data.strip().startswith("{"):
                    try:
                        result_data = json.loads(result_data)
                    except json.JSONDecodeError:
                        print(f"[WARN] Failed to parse JSON result: {result_data[:100]}")

                if isinstance(result_data, dict):
                    status = result_data.get("status", "")
                    if status == "compressed":
                        compression_succeeded = True
                        summary_text = result_data.get("summary_preview", "")
                        compression_ratio = result_data.get("compression_ratio", "N/A")
                        print(f"[INFO] Compression ratio: {compression_ratio}")
                    elif status == "error":
                        print(f"[ERROR] Compression tool returned error: {result_data.get('error', 'Unknown')}")
                        return

                if compression_succeeded and summary_text:
                    # Create summary message
                    summary_msg = {
                        "role": "system",
                        "content": f"[COMPRESSED] Summary of previous conversation: {summary_text}\n\n{len(old_messages)} messages were compressed."
                    }

                    # Replace old history with summary
                    self.context_history = [summary_msg] + self.context_history[split_idx:]
                    self.compression_count += 1

                    new_tokens = count_tokens(str(self.context_history))
                    print(f"[SUCCESS] Context compressed. New size estimate: {new_tokens} tokens")
                    print(f"[INFO] Total compressions performed: {self.compression_count}")
                else:
                    print(f"[WARN] Compression did not produce valid summary")

        except Exception as e:
            print(f"[ERROR] Context compression failed: {e}")
            import traceback
            traceback.print_exc()

    async def add_message(self, role: str, content: str):
        """
        Add a message to the conversation history.

        Args:
            role: Message role (system, user, assistant)
            content: Message content
        """
        self.context_history.append({"role": role, "content": content})
        await self._check_context_overflow()

    async def user_message(self, text: str):
        """
        Simulate an incoming user message.

        Args:
            text: User message text
        """
        await self.add_message("user", text)
        print(f"[USER]: {text[:100]}{'...' if len(text) > 100 else ''}")

    async def assistant_message(self, text: str):
        """
        Add an assistant response to the conversation.

        Args:
            text: Assistant response text
        """
        await self.add_message("assistant", text)
        print(f"[ASSISTANT]: {text[:100]}{'...' if len(text) > 100 else ''}")

    async def save_state(self) -> Dict[str, Any]:
        """
        Save current session state using checkpoint tool (AC4).

        Returns:
            Checkpoint save result
        """
        if not self.session:
            print("[WARN] Not connected to MCP server")
            return {"status": "error", "error": "Not connected"}

        state = {
            "context_history": self.context_history,
            "system_prompt": self.system_prompt,
            "compression_count": self.compression_count
        }

        try:
            result = await self.session.call_tool(
                "save_checkpoint",
                arguments={
                    "session_id": self.session_id,
                    "state": state
                }
            )

            if result.content:
                content = result.content[0]
                if hasattr(content, 'text'):
                    return json.loads(content.text)
                elif isinstance(content, dict):
                    return content
                else:
                    return json.loads(str(content))

        except Exception as e:
            print(f"[ERROR] Failed to save state: {e}")
            return {"status": "error", "error": str(e)}

    async def load_state(self) -> bool:
        """
        Load session state from checkpoint (AC4).

        Returns:
            True if state was loaded successfully
        """
        if not self.session:
            print("[WARN] Not connected to MCP server")
            return False

        try:
            result = await self.session.call_tool(
                "load_checkpoint",
                arguments={"session_id": self.session_id}
            )

            if result.content:
                content = result.content[0]
                if hasattr(content, 'text'):
                    data = json.loads(content.text)
                elif isinstance(content, dict):
                    data = content
                else:
                    data = json.loads(str(content))

                if data.get("status") == "loaded":
                    state = data.get("state", {})
                    self.context_history = state.get("context_history", [])
                    self.system_prompt = state.get("system_prompt", self.system_prompt)
                    self.compression_count = state.get("compression_count", 0)

                    print(f"[INFO] State loaded. Context has {len(self.context_history)} messages")
                    return True

        except Exception as e:
            print(f"[ERROR] Failed to load state: {e}")

        return False

    def get_stats(self) -> Dict[str, Any]:
        """
        Get current orchestrator statistics.

        Returns:
            Dictionary with current stats
        """
        current_text = "\n".join([m["content"] for m in self.context_history])
        current_tokens = count_tokens(current_text)

        return {
            "session_id": self.session_id,
            "message_count": len(self.context_history),
            "current_tokens": current_tokens,
            "compression_count": self.compression_count,
            "connected": self.connected,
            "threshold": self.summary_threshold
        }

    def print_stats(self):
        """Print current orchestrator statistics."""
        stats = self.get_stats()
        print("\n" + "=" * 60)
        print("ORCHESTRATOR STATS")
        print("=" * 60)
        print(f"Session ID: {stats['session_id']}")
        print(f"Messages: {stats['message_count']}")
        print(f"Current Tokens: {stats['current_tokens']}")
        print(f"Threshold: {stats['threshold']}")
        print(f"Compressions: {stats['compression_count']}")
        print(f"Connected: {stats['connected']}")
        print("=" * 60 + "\n")

    async def disconnect(self):
        """Disconnect from MCP server."""
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except BaseException as e:
                print(f"[WARN] Error during disconnect: {e}")
            finally:
                self._exit_stack = None

        self.connected = False
        self.session = None
        self.knowledge_session = None
        self.context7_session = None
        self._read_stream = None
        self._write_stream = None
        self._knowledge_read_stream = None
        self._knowledge_write_stream = None
        self._context7_read_stream = None
        self._context7_write_stream = None
        self.external_knowledge_router = None

    async def search_standard(self, domain: str, topic: str) -> str:
        """
        Search for standards in Context 7.

        Args:
            domain: Knowledge domain (api, security, db, python, deployment)
            topic: Specific topic to search for

        Returns:
            Matching standard or fallback message
        """
        if not self.knowledge_session:
            print("[WARN] Knowledge Bridge not connected")
            return "Knowledge Bridge not available"

        try:
            result = await self.knowledge_session.call_tool(
                "search_standard",
                arguments={"domain": domain, "topic": topic}
            )

            if result.content:
                content = result.content[0]
                if hasattr(content, 'text'):
                    return content.text
                elif isinstance(content, dict):
                    return content.get("text", str(content))
                else:
                    return str(content)

        except Exception as e:
            print(f"[ERROR] Failed to search standard: {e}")

        return "No standard found"

    async def list_knowledge_domains(self) -> List[str]:
        """
        List all available knowledge domains in Context 7.

        Returns:
            List of domain names
        """
        if not self.knowledge_session:
            print("[WARN] Knowledge Bridge not connected")
            return []

        try:
            result = await self.knowledge_session.call_tool("list_domains", arguments={})
            if result.content:
                collected: List[str] = []

                def _parse_text(raw_text: str) -> List[str]:
                    raw_text = (raw_text or "").strip()
                    if not raw_text:
                        return []
                    try:
                        parsed = json.loads(raw_text)
                        if isinstance(parsed, list):
                            return [str(item) for item in parsed]
                        if isinstance(parsed, dict):
                            domains = parsed.get("domains", [])
                            return [str(item) for item in domains] if isinstance(domains, list) else []
                        if isinstance(parsed, str):
                            raw_text = parsed.strip()
                    except Exception:
                        pass

                    try:
                        parsed = ast.literal_eval(raw_text)
                        if isinstance(parsed, list):
                            return [str(item) for item in parsed]
                        if isinstance(parsed, str):
                            raw_text = parsed.strip()
                    except Exception:
                        pass

                    normalized = raw_text.replace("[", "").replace("]", "").replace("'", "").replace('"', "")
                    tokens = [chunk.strip() for chunk in normalized.replace("\n", ",").split(",")]
                    return [token for token in tokens if token]

                for content in result.content:
                    if hasattr(content, "text"):
                        collected.extend(_parse_text(content.text))
                    elif isinstance(content, dict):
                        domains = content.get("domains")
                        if isinstance(domains, list):
                            collected.extend(str(item) for item in domains)
                        elif "text" in content:
                            collected.extend(_parse_text(str(content.get("text", ""))))
                    elif isinstance(content, list):
                        collected.extend(str(item) for item in content)

                seen = set()
                ordered_unique = []
                for item in collected:
                    if item and item not in seen:
                        seen.add(item)
                        ordered_unique.append(item)
                return ordered_unique

        except Exception as e:
            print(f"[ERROR] Failed to list domains: {e}")

        return []

    async def get_best_practices(self, domain: str) -> str:
        """
        Get best practices for a specific domain.

        Args:
            domain: Domain name (api, security, db, python, deployment)

        Returns:
            Best practices summary
        """
        if not self.knowledge_session:
            print("[WARN] Knowledge Bridge not connected")
            return "Knowledge Bridge not available"

        try:
            result = await self.knowledge_session.call_tool(
                "get_best_practices",
                arguments={"domain": domain}
            )

            if result.content:
                content = result.content[0]
                if hasattr(content, 'text'):
                    return content.text
                elif isinstance(content, dict):
                    return content.get("text", str(content))
                else:
                    return str(content)

        except Exception as e:
            print(f"[ERROR] Failed to get best practices: {e}")

        return "No best practices found"

    async def resolve_library_id(self, library_name: str, query: str = "") -> Optional[str]:
        """
        Resolve library name to Context7 ID.

        Args:
            library_name: Library name (e.g., 'torch', 'fastapi')
            query: Contextual query for relevance ranking

        Returns:
            Context7 library ID or None
        """
        if not self.context7_session:
            print("[WARN] Context7 not connected")
            return None

        try:
            result = await self.context7_session.call_tool(
                "resolve-library-id",
                arguments={"libraryName": library_name, "query": query}
            )

            if result.content:
                content = result.content[0]
                if hasattr(content, 'text'):
                    text = content.text
                    # Переводим результат
                    translated = translate_en_to_ru(text, f"Библиотека {library_name}")

                    # Parse the result to extract library ID
                    # Format: "Context7-compatible library ID: /org/repo"
                    if "Context7-compatible library ID:" in translated or "Context7-compatible library ID:" in text:
                        for line in translated.split('\n'):
                            if "Context7-compatible library ID:" in line:
                                lib_id = line.split("Context7-compatible library ID:")[-1].strip()
                                return lib_id
                elif isinstance(content, dict):
                    return content.get("libraryId")
                else:
                    return str(content)

        except Exception as e:
            print(f"[ERROR] Failed to resolve library ID: {e}")

        return None

    async def query_library_docs(self, library: str, query: str) -> Optional[str]:
        """
        Query documentation for a library.

        Args:
            library: Library name or Context7 ID
            query: Question or task

        Returns:
            Documentation with examples or None
        """
        # Backward-compatible alias: use unified external router when available.
        if self.external_knowledge_router:
            routed = await self.external_search(
                query=query,
                library=library,
                domain="python",
                limit=3
            )
            chunks = routed.get("chunks", [])
            if chunks:
                return "\n\n".join(chunk.get("content", "") for chunk in chunks if chunk.get("content"))

        if not self.context7_session:
            print("[WARN] Context7 not connected")
            return None

        try:
            library_id = await self.resolve_library_id(library, query)

            if not library_id:
                return None

            result = await self.context7_session.call_tool(
                "query-docs",
                arguments={"libraryId": library_id, "query": query}
            )

            if result.content:
                output = []
                for content in result.content:
                    if hasattr(content, 'text'):
                        text = content.text
                        # Переводим документацию
                        translated = translate_en_to_ru(text, f"Документация библиотеки {library}")
                        output.append(translated)
                    elif isinstance(content, dict):
                        output.append(str(content))
                return "\n\n".join(output) if output else None

        except Exception as e:
            print(f"[ERROR] Failed to query library docs: {e}")

        return None

    async def get_library_examples(self, library: str, topic: str) -> List[str]:
        """
        Get code examples for a library.

        Args:
            library: Library name
            topic: Topic for examples

        Returns:
            List of code examples
        """
        # Backward-compatible alias: route through external provider stack.
        if self.external_knowledge_router:
            routed = await self.external_search(
                query=f"examples code {topic}",
                library=library,
                domain="python",
                limit=3
            )
            return [
                chunk.get("content", "")
                for chunk in routed.get("chunks", [])
                if chunk.get("content")
            ]

        if not self.context7_session:
            print("[WARN] Context7 not connected")
            return []

        try:
            library_id = await self.resolve_library_id(library, topic)

            if not library_id:
                return []

            result = await self.context7_session.call_tool(
                "query-docs",
                arguments={"libraryId": library_id, "query": f"examples code {topic}"}
            )

            if result.content:
                output = []
                for content in result.content:
                    if hasattr(content, 'text'):
                        text = content.text
                        # Переводим результат
                        translated = translate_en_to_ru(text, f"Примеры кода для {library}")
                        output.append(translated)
                    elif isinstance(content, dict):
                        output.append(str(content))
                return output

        except Exception as e:
            print(f"[ERROR] Failed to get library examples: {e}")

        return []

    async def list_supported_libraries(self) -> Dict[str, str]:
        """
        Get list of supported libraries.

        Returns:
            Dictionary with library information
        """
        if not self.context7_session:
            print("[WARN] Context7 not connected")
            return {}

        try:
            result = await self.context7_session.call_tool(
                "resolve-library-id",
                arguments={"query": "", "libraryName": "python"}
            )

            if result.content:
                output = []
                for content in result.content:
                    if hasattr(content, 'text'):
                        text = content.text
                        # Переводим результат
                        translated = translate_en_to_ru(text, "Список поддерживаемых библиотек")
                        output.append(translated)
                    elif isinstance(content, dict):
                        output.append(str(content))
                return {"info": "\n\n".join(output)}

        except Exception as e:
            print(f"[ERROR] Failed to list libraries: {e}")

        return {"note": "Context7 provides access to thousands of libraries. Use resolve-library-id to find specific libraries."}

    async def external_search(
        self,
        query: str,
        domain: str = "python",
        library: Optional[str] = None,
        repo: Optional[str] = None,
        project_id: Optional[int] = None,
        limit: int = 5
    ) -> Dict[str, Any]:
        """
        Единый поиск по внешним источникам через роутер провайдеров.
        """
        if not self.external_knowledge_router:
            return {
                "status": "error",
                "error": "External knowledge router not initialized",
                "chunks": []
            }

        context = {
            "domain": domain,
            "library": library,
            "repo": repo,
            "project_id": project_id,
            "shiva_project_id": project_id,
        }

        result = await self.external_knowledge_router.search(
            query=query,
            context=context,
            limit=limit
        )

        return {
            "status": "ok",
            **result
        }

    async def external_code(
        self,
        library: str,
        topic: str,
        repo: Optional[str] = None,
        limit: int = 5
    ) -> Dict[str, Any]:
        """Code-oriented external search alias."""
        return await self.external_search(
            query=f"code examples {topic}",
            domain="python",
            library=library,
            repo=repo,
            limit=limit
        )

    def get_external_knowledge_metrics(self) -> Dict[str, Any]:
        """
        Получить метрики качества внешнего knowledge-роутера.
        """
        if not self.external_knowledge_router:
            return {
                "status": "error",
                "error": "External knowledge router not initialized"
            }
        return {
            "status": "ok",
            **self.external_knowledge_router.get_metrics()
        }

    async def get_external_knowledge_metrics_history(self, limit: int = 100) -> Dict[str, Any]:
        if not self.external_knowledge_router:
            return {
                "status": "error",
                "error": "External knowledge router not initialized"
            }
        history = await self.external_knowledge_router.get_metrics_history(limit=limit)
        return {
            "status": "ok",
            "history": history,
            "count": len(history),
        }

    async def export_external_knowledge_metrics(self, export_format: str = "json", history_limit: int = 100) -> Dict[str, Any]:
        if not self.external_knowledge_router:
            return {
                "status": "error",
                "error": "External knowledge router not initialized"
            }
        if export_format == "prometheus":
            return {
                "status": "ok",
                "format": "prometheus",
                "payload": self.external_knowledge_router.export_metrics_prometheus(),
            }
        payload = await self.external_knowledge_router.export_metrics_json(history_limit=history_limit)
        return {
            "status": "ok",
            "format": "json",
            "payload": payload,
        }

    def get_external_knowledge_alerts(self) -> Dict[str, Any]:
        if not self.external_knowledge_router:
            return {
                "status": "error",
                "error": "External knowledge router not initialized"
            }
        return {
            "status": "ok",
            "alerts": self.external_knowledge_router.get_alerts()
        }

    async def get_external_provider_health(self) -> Dict[str, Any]:
        if not self.external_knowledge_router:
            return {
                "status": "error",
                "error": "External knowledge router not initialized"
            }
        health = await self.external_knowledge_router.get_provider_health()
        return {
            "status": "ok",
            "providers": health,
        }


async def interactive_session():
    """
    Interactive session for testing the orchestrator.
    Allows manual input of messages to test compression triggers.
    """
    orchestrator = ContextOrchestrator(
        enable_knowledge_bridge=True,
        enable_context7=True
    )

    try:
        await orchestrator.connect()

        print("\n" + "=" * 60)
        print("INTERACTIVE SESSION")
        print("=" * 60)
        print("Commands:")
        print("  - Type your message to add it to the conversation")
        print("  - 'stats' - Show current statistics")
        print("  - 'save' - Save current state")
        print("  - 'load' - Load saved state")
        print("  - 'search <domain> <topic>' - Search Context 7 standard")
        print("  - 'domains' - List knowledge domains")
        print("  - 'best <domain>' - Get best practices")
        print("  - 'ctx7-libs' - List supported Context7 libraries")
        print("  - 'ctx7-docs <lib> <query>' - Query library docs")
        print("  - 'ctx7-ex <lib> <topic>' - Get library examples")
        print("  - 'ext-search <domain> <query>' - Search across external knowledge providers")
        print("  - 'ext-docs <lib> <query>' - External docs search with library context")
        print("  - 'ext-code <lib> <topic>' - Code-oriented external search (router alias)")
        print("  - 'ext-metrics' - External knowledge quality metrics")
        print("  - 'ext-metrics-history [limit]' - Metrics history from Redis/local store")
        print("  - 'ext-metrics-json [limit]' - JSON export (current + history + alerts)")
        print("  - 'ext-metrics-prom' - Prometheus export")
        print("  - 'ext-alerts' - Alert states for hit_rate and p95")
        print("  - 'ext-provider-health' - Provider health from Redis/in-memory")
        print("  - 'quit' - Exit")
        print("=" * 60 + "\n")

        while True:
            try:
                user_input = input("You: ")

                if user_input.lower() == "quit":
                    break
                elif user_input.lower() == "stats":
                    orchestrator.print_stats()
                elif user_input.lower() == "save":
                    result = await orchestrator.save_state()
                    print(f"Save result: {result}")
                elif user_input.lower() == "load":
                    success = await orchestrator.load_state()
                    print(f"Load {'succeeded' if success else 'failed'}")
                elif user_input.lower() == "domains":
                    domains = await orchestrator.list_knowledge_domains()
                    print(f"Knowledge domains: {', '.join(domains)}")
                elif user_input.lower() == "ctx7-libs":
                    libs = await orchestrator.list_supported_libraries()
                    print(f"Context7 supported libraries: {', '.join(libs.keys())}")
                elif user_input.lower().startswith("search "):
                    parts = user_input[7:].split(" ", 1)
                    if len(parts) == 2:
                        result = await orchestrator.search_standard(parts[0], parts[1])
                        print(f"[Context 7]: {result}")
                    else:
                        print("Usage: search <domain> <topic>")
                elif user_input.lower().startswith("best "):
                    domain = user_input[5:]
                    result = await orchestrator.get_best_practices(domain)
                    print(f"[Best Practices]: {result}")
                elif user_input.lower().startswith("ctx7-docs "):
                    parts = user_input[10:].split(" ", 1)
                    if len(parts) == 2:
                        result = await orchestrator.query_library_docs(parts[0], parts[1])
                        print(f"[Context7]:\n{result}")
                    else:
                        print("Usage: ctx7-docs <library> <query>")
                elif user_input.lower().startswith("ctx7-ex "):
                    parts = user_input[8:].split(" ", 1)
                    if len(parts) == 2:
                        examples = await orchestrator.get_library_examples(parts[0], parts[1])
                        print(f"[Context7 Examples]:")
                        for i, ex in enumerate(examples[:3], 1):
                            print(f"\nExample {i}:\n{ex}")
                    else:
                        print("Usage: ctx7-ex <library> <topic>")
                elif user_input.lower().startswith("ext-search "):
                    parts = user_input[11:].split(" ", 1)
                    if len(parts) == 2:
                        result = await orchestrator.external_search(
                            query=parts[1],
                            domain=parts[0],
                            limit=3
                        )
                        print(json.dumps(result, ensure_ascii=False, indent=2))
                    else:
                        print("Usage: ext-search <domain> <query>")
                elif user_input.lower().startswith("ext-docs "):
                    parts = user_input[9:].split(" ", 1)
                    if len(parts) == 2:
                        result = await orchestrator.external_search(
                            query=parts[1],
                            library=parts[0],
                            domain="python",
                            limit=3
                        )
                        print(json.dumps(result, ensure_ascii=False, indent=2))
                    else:
                        print("Usage: ext-docs <library> <query>")
                elif user_input.lower().startswith("ext-code "):
                    parts = user_input[9:].split(" ", 1)
                    if len(parts) == 2:
                        result = await orchestrator.external_code(
                            library=parts[0],
                            topic=parts[1],
                            limit=3
                        )
                        print(json.dumps(result, ensure_ascii=False, indent=2))
                    else:
                        print("Usage: ext-code <library> <topic>")
                elif user_input.lower() == "ext-metrics":
                    metrics = orchestrator.get_external_knowledge_metrics()
                    print(json.dumps(metrics, ensure_ascii=False, indent=2))
                elif user_input.lower().startswith("ext-metrics-history"):
                    parts = user_input.split()
                    limit = 20
                    if len(parts) == 2 and parts[1].isdigit():
                        limit = int(parts[1])
                    history = await orchestrator.get_external_knowledge_metrics_history(limit=limit)
                    print(json.dumps(history, ensure_ascii=False, indent=2))
                elif user_input.lower().startswith("ext-metrics-json"):
                    parts = user_input.split()
                    limit = 100
                    if len(parts) == 2 and parts[1].isdigit():
                        limit = int(parts[1])
                    export_payload = await orchestrator.export_external_knowledge_metrics(
                        export_format="json",
                        history_limit=limit
                    )
                    print(json.dumps(export_payload, ensure_ascii=False, indent=2))
                elif user_input.lower() == "ext-metrics-prom":
                    export_payload = await orchestrator.export_external_knowledge_metrics(
                        export_format="prometheus"
                    )
                    print(export_payload.get("payload", ""))
                elif user_input.lower() == "ext-alerts":
                    alerts = orchestrator.get_external_knowledge_alerts()
                    print(json.dumps(alerts, ensure_ascii=False, indent=2))
                elif user_input.lower() == "ext-provider-health":
                    health = await orchestrator.get_external_provider_health()
                    print(json.dumps(health, ensure_ascii=False, indent=2))
                else:
                    await orchestrator.user_message(user_input)

            except KeyboardInterrupt:
                break
            except EOFError:
                break

    finally:
        await orchestrator.disconnect()


if __name__ == "__main__":
    # Interactive mode for testing
    asyncio.run(interactive_session())
