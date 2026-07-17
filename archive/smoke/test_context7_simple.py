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

    print('\n=== Test 1: Resolve library ID for torch ===')
    result1 = await session.call_tool(
        'resolve-library-id',
        arguments={'libraryName': 'torch', 'query': 'tensor operations'}
    )
    if result1.content:
        text = result1.content[0].text
        print(f'Result length: {len(text)}')
        lines = text.split('\n')
        for i, line in enumerate(lines[:5], 1):
            print(f'  Line {i}: {line[:80]}...')

    print('\n=== Test 2: Query docs for PyTorch ===')
    result2 = await session.call_tool(
        'query-docs',
        arguments={'libraryId': '/pytorch/pytorch', 'query': 'tensor creation examples'}
    )
    if result2.content:
        text = result2.content[0].text
        print(f'Result length: {len(text)}')
        print(f'Preview: {text[:400]}...')

    print('\n=== Test 3: Query docs for FastAPI ===')
    result3 = await session.call_tool(
        'query-docs',
        arguments={'libraryId': '/tiangolo/fastapi', 'query': 'JWT authentication'}
    )
    if result3.content:
        text = result3.content[0].text
        print(f'Result length: {len(text)}')
        print(f'Preview: {text[:400]}...')

    await session.__aexit__(None, None, None)
    await ctx.__aexit__(None, None, None)

asyncio.run(test())
