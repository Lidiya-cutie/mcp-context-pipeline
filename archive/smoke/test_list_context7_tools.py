import asyncio
import sys
from mcp import ClientSession, stdio_client
from mcp.client.stdio import StdioServerParameters
import os


async def main():
    api_key = os.environ.get("CONTEXT7_API_KEY", "")

    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@upstash/context7-mcp"] + (["--api-key", api_key] if api_key else [])
    )

    ctx = stdio_client(server_params)
    read_stream, write_stream = await ctx.__aenter__()
    session = ClientSession(read_stream, write_stream)
    await session.__aenter__()
    await session.initialize()

    print("Available tools:")
    tools_result = await session.list_tools()
    print(f"  Tools result type: {type(tools_result)}")
    print(f"  Tools result: {tools_result}")

    print("\nAvailable resources:")
    resources = await session.list_resources()
    for resource in resources:
        print(f"  - {resource.uri}: {resource.name}")

    await session.__aexit__(None, None, None)
    await ctx.__aexit__(None, None, None)

asyncio.run(main())
