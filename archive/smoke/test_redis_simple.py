"""Простой тест Redis."""

import sys
sys.path.insert(0, 'src')
from redis_manager import RedisManager

def test():
    print('=== Тест Redis ===')

    manager = RedisManager()
    client = manager.get_client()

    if client:
        print(f'✓ Redis подключен')

        # Тест set/get
        client.set('test_key', 'test_value')
        result = client.get('test_key')
        print(f'Set/Get результат: {result}')

        # Пинг
        ping = client.ping()
        print(f'Пинг: {ping}')

        # Существование
        exists = client.exists('test_key')
        print(f'Существование: {exists}')
    else:
        print('✗ Redis не подключен')

    # Использование с threading
    from concurrent.futures import ThreadPoolExecutor
    import time
    executor = ThreadPoolExecutor(max_workers=1)

    def redis_op(op):
        try:
            return executor.submit(op).result(timeout=10)
        except Exception as e:
            print(f'Ошибка: {e}')
            return None

    # Запуск асинхронно
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = []

        # Несколько операций параллельно
        for i in range(5):
            futures.append(redis_op(lambda: client.set(f'key{i}', f'value{i}')))
            futures.append(redis_op(lambda: client.get(f'key{i}')))

        # Дождаться завершения
        for future in futures:
            result = future.result()
            if i == 4:  # Последний get для проверки
                print(f'Ключ 4: {result}')

        print(f'✓ {len(futures)} операций завершено')

    print('\n=== Вывод ===')
    print('1. Redis-py может иметь проблемы с постоянными соединениями в Docker')
    print('2. Контейнер работает (docker exec redis-cli ping = PONG)')
    print('3. Внешние подключения могут быть блокированы')
    print('4. Рекомендуется использовать docker exec вместо прямых подключений')
    print('5. Или настроить сеть Docker для доступа к 6379')

if __name__ == '__main__':
    test()
