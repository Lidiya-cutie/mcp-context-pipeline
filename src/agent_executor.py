"""
Agent Executor — запуск субагентов-экспертов по навыкам.

Связывает:
- SkillDispatcher (60 навыков) — выбор навыка и system prompt
- SecureLLMMiddleware — вызов LLM с PII masking
- MCP servers (27 штук) — инструменты через stdio JSON-RPC
"""

import asyncio
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from skill_dispatcher import SkillDispatcher


class MCPClient:
    """Stdio JSON-RPC клиент для MCP серверов."""

    def __init__(self, server_path: str, server_name: str):
        self.server_path = server_path
        self.server_name = server_name
        self.process = None
        self._request_id = 0
        self._initialized = False

    async def start(self) -> bool:
        try:
            self.process = subprocess.Popen(
                [sys.executable, self.server_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.path.dirname(self.server_path),
            )
            result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agent_executor", "version": "1.0.0"},
            })
            self._initialized = result is not None
            return self._initialized
        except Exception as e:
            print(f"[MCP] Failed to start {self.server_name}: {e}")
            return False

    async def _send_request(self, method: str, params: dict = None) -> Optional[dict]:
        if not self.process or self.process.poll() is not None:
            return None
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {},
        }
        try:
            self.process.stdin.write((json.dumps(request) + "\n").encode())
            self.process.stdin.flush()
            response_line = await asyncio.to_thread(
                self.process.stdout.readline
            )
            if not response_line:
                return None
            raw = response_line.decode().strip()
            if raw.startswith("Content-Length:"):
                header = raw
                response_line = await asyncio.to_thread(
                    self.process.stdout.readline
                )
                if not response_line:
                    return None
                response_line = await asyncio.to_thread(
                    self.process.stdout.readline
                )
                if not response_line:
                    return None
                raw = response_line.decode().strip()
            return json.loads(raw)
        except Exception as e:
            print(f"[MCP] Request error ({self.server_name}): {e}")
            return None

    async def list_tools(self) -> List[dict]:
        result = await self._send_request("tools/list")
        if result and "result" in result:
            return result["result"].get("tools", [])
        return []

    async def call_tool(self, tool_name: str, arguments: dict = None) -> Optional[str]:
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        })
        if result and "result" in result:
            content = result["result"].get("content", [])
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(item.get("text", str(item)))
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        if result and "error" in result:
            return f"ERROR: {result['error'].get('message', 'unknown')}"
        return None

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()


class AgentExecutor:
    """Запуск субагента-эксперта по навыку."""

    def __init__(
        self,
        project_dir: str = None,
    ):
        self.project_dir = project_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.dispatcher = SkillDispatcher(
            skills_dir=os.path.join(self.project_dir, "Навыки"),
            mcp_servers_dir=os.path.join(self.project_dir, "src", "mcp_servers"),
        )
        self._mcp_clients: Dict[str, MCPClient] = {}

    def list_skills(self) -> List[Dict]:
        return self.dispatcher.list_skills()

    def find_skill(self, query: str, role: str = None, top_k: int = 3) -> List[Dict]:
        return self.dispatcher.find_skill(query, role, top_k)

    async def _start_mcp(self, server_name: str) -> Optional[MCPClient]:
        if server_name in self._mcp_clients:
            return self._mcp_clients[server_name]
        server_path = os.path.join(
            self.project_dir, "src", "mcp_servers", server_name, "server.py"
        )
        if not os.path.exists(server_path):
            print(f"[MCP] Server not found: {server_path}")
            return None
        client = MCPClient(server_path, server_name)
        ok = await client.start()
        if ok:
            self._mcp_clients[server_name] = client
            return client
        return None

    async def _stop_all_mcp(self):
        for name, client in self._mcp_clients.items():
            client.stop()
        self._mcp_clients.clear()

    async def _gather_context(
        self, task: str, mcp_servers: List[str]
    ) -> str:
        """Собрать контекст из MCP серверов для задачи."""
        context_parts = []
        for server_name in mcp_servers:
            client = await self._start_mcp(server_name)
            if not client:
                continue
            tools = await client.list_tools()
            tool_names = [t["name"] for t in tools]
            context_parts.append(
                f"[{server_name}] Available tools: {', '.join(tool_names[:10])}"
            )
            # Try check_health for status info
            if "check_health" in tool_names:
                health = await client.call_tool("check_health")
                if health and not health.startswith("ERROR"):
                    context_parts.append(f"[{server_name}] Status: {health[:200]}")
        return "\n".join(context_parts) if context_parts else "No MCP context available"

    async def execute(
        self,
        skill_name: str,
        task: str,
        max_tokens: int = 4000,
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """
        Execute a skill as a sub-agent.

        Returns:
            {
                "skill": str,
                "task": str,
                "system_prompt": str,
                "mcp_context": str,
                "response": str,
                "mcp_results": dict,
                "status": "success" | "error",
            }
        """
        plan = self.dispatcher.activate_skill(skill_name, task)
        system_prompt = plan["system_prompt"]
        mcp_servers = plan["mcp_servers"]

        # Gather MCP context
        mcp_context = await self._gather_context(task, mcp_servers)

        # Execute MCP tools that match the task
        mcp_results = {}
        for server_name in mcp_servers:
            client = await self._start_mcp(server_name)
            if not client:
                mcp_results[server_name] = "server unavailable"
                continue
            tools = await client.list_tools()
            tool_names = [t["name"] for t in tools]
            # Call check_health for diagnostics when available,
            # иначе фиксируем факт подключения и список инструментов.
            if "check_health" in tool_names:
                result = await client.call_tool("check_health")
                mcp_results[server_name] = {
                    "health": result,
                    "tools": tool_names,
                }
            else:
                mcp_results[server_name] = {
                    "connected": True,
                    "tools": tool_names,
                }

        # Call LLM via SecureLLMMiddleware
        response_text = ""
        llm_error = None
        try:
            from secure_middleware import SecureLLMMiddleware
            middleware = SecureLLMMiddleware()
            messages = [
                {
                    "role": "user",
                    "content": (
                        f"Задача: {task}\n\n"
                        f"Доступные MCP-инструменты:\n{mcp_context}\n\n"
                        f"Результаты MCP:\n{json.dumps(mcp_results, ensure_ascii=False, indent=2, default=str)}"
                    ),
                }
            ]
            response_text = await middleware.chat(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                system_prompt=system_prompt,
            )
        except Exception as e:
            llm_error = str(e)
            # Fallback: try direct Anthropic API
            try:
                import anthropic
                api_key = os.getenv("ANTHROPIC_API_KEY")
                base_url = os.getenv("ANTHROPIC_BASE_URL")
                model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
                if api_key:
                    kwargs = {"api_key": api_key}
                    if base_url:
                        kwargs["base_url"] = base_url
                    direct_client = anthropic.Anthropic(**kwargs)
                    full_prompt = (
                        f"{system_prompt}\n\n"
                        f"MCP Context:\n{mcp_context}\n\n"
                        f"MCP Results:\n{json.dumps(mcp_results, ensure_ascii=False, indent=2, default=str)}\n\n"
                        f"Task: {task}"
                    )
                    msg = direct_client.messages.create(
                        model=model,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        messages=[{"role": "user", "content": full_prompt}],
                    )
                    response_text = "".join(
                        b.text for b in msg.content if hasattr(b, "text")
                    )
                    llm_error = None
            except Exception as e2:
                llm_error = f"Middleware: {e}; Direct: {e2}"

        await self._stop_all_mcp()

        return {
            "skill": skill_name,
            "task": task,
            "system_prompt": system_prompt,
            "mcp_context": mcp_context,
            "response": response_text or "",
            "mcp_results": mcp_results,
            "error": llm_error,
            "status": "success" if response_text and not llm_error else "error",
        }

    async def quick_execute(
        self,
        query: str,
        task: str,
        role: str = None,
    ) -> Dict[str, Any]:
        """Найти подходящий навык по запросу и выполнить."""
        matches = self.dispatcher.find_skill(query, role, top_k=1)
        if not matches:
            return {
                "skill": None,
                "task": task,
                "response": "",
                "error": f"No skill found for: {query}",
                "status": "error",
            }
        best = matches[0]
        skill_name = best.get("stem") or best.get("filename", "").replace(".md", "")
        return await self.execute(skill_name, task)
