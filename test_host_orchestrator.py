import asyncio
import sys
sys.path.insert(0, 'src')
from host_orchestrator import ContextOrchestrator


async def test():
    orch = ContextOrchestrator(enable_context7=True)
    await orch.connect()

    print('\n=== Test 1: Resolve torch ===')
    torch_id = await orch.resolve_library_id('torch', 'tensor')
    print(f'Torch ID: {torch_id}')

    print('\n=== Test 2: Query FastAPI docs ===')
    docs = await orch.query_library_docs('fastapi', 'JWT authentication')
    if docs:
        print(f'Got {len(docs)} chars of docs')
        print(f'Preview: {docs[:300]}')
    else:
        print('No docs returned')

    print('\n=== Test 3: Get PyTorch examples ===')
    examples = await orch.get_library_examples('torch', 'tensor creation')
    if examples:
        print(f'Got {len(examples)} examples')
        for i, ex in enumerate(examples[:2], 1):
            print(f'\nExample {i}:')
            print(ex[:200])
    else:
        print('No examples returned')

    await orch.disconnect()

asyncio.run(test())
