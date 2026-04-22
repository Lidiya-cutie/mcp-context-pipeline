import asyncio
import sys
from mcp import ClientSession, stdio_client
from mcp.client.stdio import StdioServerParameters
import os


async def test():
    api_key = os.environ.get('CONTEXT7_API_KEY', '')
    server_params = StdioServerParameters(
        command='npx',
        args=['-y', '@upstash/context7-mcp'] + (['--api-key', api_key] if api_key else [])
    )
    ctx = stdio_client(server_params)
    read_stream, write_stream = await ctx.__aenter__()
    session = ClientSession(read_stream, write_stream)
    await session.__aenter__()
    await session.initialize()

    print('=== Testing resolve-library-id ===')
    result1 = await session.call_tool(
        'resolve-library-id',
        arguments={'libraryName': 'torch', 'query': 'tensor'}
    )
    print(f'Result 1 content: {len(result1.content)} items')

    if result1.content:
        for i, item in enumerate(result1.content):
            print(f'Item {i}: type={type(item)}')
            if hasattr(item, 'text'):
                print(f'  Text length: {len(item.text)}')
                print(f'  Preview: {item.text[:150]}')

    print('\n=== Testing query-docs ===')
    result2 = await session.call_tool(
        'query-docs',
        arguments={'libraryId': '/pytorch/pytorch', 'query': 'tensor creation'}
    )
    print(f'Result 2 content: {len(result2.content)} items')

    if result2.content:
        for i, item in enumerate(result2.content):
            print(f'Item {i}: type={type(item)}')
            if hasattr(item, 'text'):
                print(f'  Text length: {len(item.text)}')
                print(f'  Preview: {item.text[:200]}')

    await session.__aexit__(None, None, None)
    await ctx.__aexit__(None, None, None)

asyncio.run(test())
