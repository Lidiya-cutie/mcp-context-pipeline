"""
Quick test for Context7 integration.
Запуск быстрого теста для проверки Context7 MCP.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from utils import count_tokens, generate_session_id
from mcp import ClientSession, stdio_client


class ContextOrchestrator:
    """Упрощенный orchestrator для быстрого теста."""

    def __init__(self, enable_context7: bool = False):
        self.enable_context7 = enable_context7
        self.context7_session: Optional[ClientSession] = None
        self._context7_stdcio_ctx = None

    async def connect(self):
        """Connect to Context7."""
        if self.enable_context7:
            try:
                from mcp.client.stdio import StdioServerParameters

                api_key = os.environ.get("CONTEXT7_API_KEY", "")

                server_params = StdioServerParameters(
                    command="npx",
                    args=["-y", "@upstash/context7-mcp"] + (["--api-key", api_key] if api_key else [])
                )

                self._context7_stdcio_ctx = stdio_client(server_params)
                read_stream, write_stream = await self._context7_stdcio_ctx.__aenter__()

                self.context7_session = ClientSession(read_stream, write_stream)
                await self.context7_session.__aenter__()
                await self.context7_session.initialize()

                print("[INFO] Connected to Context7")
            except Exception as e:
                print(f"[ERROR] Failed to connect: {e}")
                self.context7_session = None

    async def list_supported_libraries(self):
        """Get supported libraries."""
        if not self.context7_session:
            return {}
        try:
            result = await self.context7_session.call_tool(
                "list_supported_libraries", arguments={}
            )
            if result.content:
                import json
                content = result.content[0]
                if hasattr(content, 'text'):
                    return json.loads(content.text)
                elif isinstance(content, dict):
                    return content
        except Exception as e:
            print(f"[ERROR] {e}")
        return {}

    async def resolve_library_id(self, library_name: str, query: str = ""):
        """Resolve library ID."""
        if not self.context7_session:
            return None
        try:
            result = await self.context7_session.call_tool(
                "resolve-library-id",
                arguments={"libraryName": library_name, "query": query}
            )
            if result.content:
                content = result.content[0]
                if hasattr(content, 'text'):
                    return content.text
                elif isinstance(content, dict):
                    return content.get("libraryId")
        except Exception as e:
            print(f"[ERROR] {e}")
        return None

    async def query_library_docs(self, library: str, query: str):
        """Query library docs."""
        if not self.context7_session:
            return None
        try:
            result = await self.context7_session.call_tool(
                "query-docs",
                arguments={"libraryId": library, "query": query}
            )
            if result.content:
                content = result.content[0]
                if hasattr(content, 'text'):
                    return content.text
                elif isinstance(content, dict):
                    docs = content.get("docs", "")
                    examples = content.get("examples", [])
                    output = f"# Documentation\n\n{docs}\n\n"
                    if examples:
                        output += "## Examples\n\n"
                        for ex in examples[:3]:
                            output += f"```python\n{ex}\n```\n\n"
                    return output
        except Exception as e:
            print(f"[ERROR] {e}")
        return None

    async def get_library_examples(self, library: str, topic: str):
        """Get library examples."""
        if not self.context7_session:
            return []
        try:
            result = await self.context7_session.call_tool(
                "get_library_examples",
                arguments={"library": library, "topic": topic}
            )
            if result.content:
                content = result.content[0]
                if hasattr(content, 'text'):
                    import json
                    return json.loads(content.text)
                elif isinstance(content, list):
                    return content
                elif isinstance(content, dict):
                    return content.get("examples", [])
        except Exception as e:
            print(f"[ERROR] {e}")
        return []

    async def disconnect(self):
        """Disconnect."""
        if self.context7_session:
            try:
                await self.context7_session.__aexit__(None, None, None)
            except:
                pass
        if self._context7_stdcio_ctx:
            try:
                await self._context7_stdcio_ctx.__aexit__(None, None, None)
            except:
                pass


async def quick_test():
    """Быстрый тест Context7."""
    print("\n" + "=" * 60)
    print("CONTEXT7 QUICK TEST")
    print("=" * 60 + "\n")

    orchestrator = ContextOrchestrator(enable_context7=True)

    try:
        print("1. Connecting to Context7...")
        await orchestrator.connect()
        print("   [OK] Connected\n")

        print("2. Getting supported libraries...")
        libs = await orchestrator.list_supported_libraries()
        print(f"   [OK] {len(libs)} libraries found")
        print(f"   {', '.join(list(libs.keys())[:10])}...\n")

        print("3. Resolving library ID for 'torch'...")
        torch_id = await orchestrator.resolve_library_id("torch", "tensor operations")
        print(f"   [OK] {torch_id}\n")

        print("4. Querying FastAPI documentation...")
        docs = await orchestrator.query_library_docs("fastapi", "JWT authentication")
        if docs:
            print(f"   [OK] Got {len(docs)} chars of documentation")
            print(f"   Preview: {docs[:200]}...\n")
        else:
            print("   [INFO] No documentation retrieved\n")

        print("5. Getting PyTorch examples...")
        examples = await orchestrator.get_library_examples("torch", "tensor creation")
        if examples:
            print(f"   [OK] {len(examples)} examples found")
            print(f"   Example 1: {examples[0][:150]}...\n")
        else:
            print("   [INFO] No examples found\n")

        print("=" * 60)
        print("TEST COMPLETE - Context7 working!")
        print("=" * 60)

        return True

    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        await orchestrator.disconnect()


if __name__ == "__main__":
    success = asyncio.run(quick_test())
    sys.exit(0 if success else 1)
