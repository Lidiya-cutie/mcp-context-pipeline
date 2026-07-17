import asyncio
import sys
sys.path.insert(0, 'src')

from mcp import ClientSession, stdio_client
from mcp.client.stdio import StdioServerParameters


async def test():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["src/context7_mcp_server.py"]
    )

    ctx = stdio_client(server_params)
    read_stream, write_stream = await ctx.__aenter__()
    session = ClientSession(read_stream, write_stream)
    await session.__aenter__()
    await session.initialize()

    print('Testing query_docs...')
    result = await session.call_tool(
        'query_docs',
        arguments={'library': '/pytorch/pytorch', 'query': 'tensor creation'}
    )
    print(f'Result type: {type(result)}')
    print(f'Content type: {type(result.content)}')
    print(f'Content: {result.content}')

    if result.content:
        content = result.content[0]
        print(f'Content item type: {type(content)}')
        print(f'Content item: {content}')
        if hasattr(content, 'text'):
            print(f'Text: {content.text}')

    await session.__aexit__(None, None, None)
    await ctx.__aexit__(None, None, None)

asyncio.run(test())
