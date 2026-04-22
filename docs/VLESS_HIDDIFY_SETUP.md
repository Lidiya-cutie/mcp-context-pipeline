# Настройка VLESS (Hiddify) для обхода региональных ограничений

## Обзор

Интеграция VLESS протокола через Xray клиент для надежного обхода региональных ограничений при доступе к LLM API.

## Преимущества использования VLESS

1. **Высокая производительность** - VLESS легче V2Ray/Trojan, меньше задержки
2. **Надежность** - работает через WebSocket + TLS, сложно детектировать
3. **Hiddify интеграция** - автоматическая настройка через подписку
4. **Кроссплатформенность** - работает на Linux/Windows/Mac через Docker

## Быстрый старт

### Требования

- Docker и Docker Compose
- Подписка Hiddify или VLESS ссылка
- Python 3.10+ с PyYAML (`pip install pyyaml requests`)

### Установка зависимостей

```bash
pip install pyyaml requests
```

### Шаг 1: Настройка подписки Hiddify

#### Вариант A: Использование подписки Hiddify

1. Получите подписку в Hiddify (обычно ссылка вида `https://hiddify.com/s/...`)

2. Добавьте в `.env`:
```env
VLESS_SUBSCRIPTION=https://hiddify.com/s/your_subscription_code
VLESS_SERVER_INDEX=0
```

#### Вариант B: Использование прямой VLESS ссылки

1. Получите VLESS ссылку от провайдера

2. Добавьте в `.env`:
```env
VLESS_URL=vless://uuid@host:port?type=ws&security=tls&host=domain.com&path=/ws#MyServer
```

### Шаг 2: Запуск Xray клиента

```bash
chmod +x run_vless.sh
./run_vless.sh start
```

После успешного запуска увидите:
```
[SUCCESS] Xray запущен
[INFO] SOCKS5 прокси: socks5://127.0.0.1:10809
[INFO] HTTP прокси:  http://127.0.0.1:10808
```

### Шаг 3: Настройка пайплайна на использование прокси

Добавьте в `.env`:
```env
ALL_PROXY=socks5://127.0.0.1:10809
```

Или используйте HTTP прокси:
```env
HTTP_PROXY=http://127.0.0.1:10808
```

### Шаг 4: Проверка работы

```bash
# Тест прокси
./run_vless.sh test

# Проверка подключения к Anthropic
python3 test_proxy.py
```

## Управление Xray клиентом

### Команды

```bash
./run_vless.sh start    # Запустить клиент
./run_vless.sh stop     # Остановить клиент
./run_vless.sh restart  # Перезапустить клиент
./run_vless.sh status   # Показать статус
./run_vless.sh logs     # Показать логи
./run_vless.sh test     # Протестировать подключение
./run_vless.sh config   # Пересоздать конфигурацию
```

### Просмотр логов

```bash
#实时 логи
./run_vless.sh logs

# Последние 100 строк
docker logs mcp-xray-vless --tail 100
```

## Программное использование

### Python API

```python
from src.vless_client import VLESSClient

# Создание клиента из подписки
client = VLESSClient(listen_port=10809)
client.generate_xray_config(
    subscription_url="https://hiddify.com/s/...",
    server_index=0
)

# Запуск через Docker
if client.start_docker():
    proxy_url = client.get_proxy_url(protocol="socks5")
    print(f"Прокси URL: {proxy_url}")

    # Проверка статуса
    status = client.status()
    print(f"Статус: {status}")
```

### Автоматическая настройка из переменных окружения

```python
from src.vless_client import setup_vless_from_env

# Автоматическое чтение из .env
client = setup_vless_from_env()
if client:
    client.start_docker()
    proxy_url = client.get_proxy_url()
    # Используйте proxy_url в приложении
```

## Продвинутая настройка

### Выбор сервера из подписки

Если подписка содержит несколько серверов, выберите нужный:

```env
VLESS_SERVER_INDEX=0  # Первый сервер
VLESS_SERVER_INDEX=1  # Второй сервер
VLESS_SERVER_INDEX=2  # Третий сервер
```

Перезапустите клиента после изменения:
```bash
VLESS_SERVER_INDEX=1 ./run_vless.sh restart
```

### Изменение портов

По умолчанию:
- SOCKS5: 10809
- HTTP: 10808

Измените в `.env`:
```env
XRAY_SOCKS_PORT=10810
XRAY_HTTP_PORT=10811
```

### Кастомная конфигурация

Создайте файл `xray-config/config.json` с вашей конфигурацией Xray:

```json
{
  "log": {
    "loglevel": "warning"
  },
  "inbounds": [
    {
      "port": 10809,
      "protocol": "socks",
      "settings": {
        "auth": "noauth",
        "udp": true
      }
    }
  ],
  "outbounds": [
    {
      "protocol": "vless",
      "settings": {
        "vnext": [{
          "address": "your-server.com",
          "port": 443,
          "users": [{"id": "your-uuid", "encryption": "none"}]
        }]
      },
      "streamSettings": {
        "network": "ws",
        "security": "tls",
        "tlsSettings": {
          "serverName": "your-server.com",
          "allowInsecure": false
        },
        "wsSettings": {
          "path": "/ws",
          "headers": {"Host": "your-server.com"}
        }
      }
    }
  ]
}
```

## Интеграция с пайплайном

### Автоматический запуск при старте

Добавьте в `run_host.sh` перед запуском пайплайна:

```bash
# Запуск VLESS клиента если настроен
if [ -n "$VLESS_SUBSCRIPTION" ] || [ -n "$VLESS_URL" ]; then
    echo "[INFO] Запуск Xray VLESS клиента..."
    ./run_vless.sh start

    # Настройка переменных прокси для текущей сессии
    export ALL_PROXY="socks5://127.0.0.1:${XRAY_SOCKS_PORT:-10809}"
    export HTTP_PROXY="http://127.0.0.1:${XRAY_HTTP_PORT:-10808}"
fi
```

### Очистка при остановке

Добавьте в скрипт остановки:

```bash
# Остановка VLESS клиента
./run_vless.sh stop
```

## Устранение неполадок

### Проблема: Контейнер не запускается

```bash
# Проверьте логи
docker logs mcp-xray-vless

# Проверьте конфигурацию
cat xray-config/config.json

# Попробуйте пересоздать конфигурацию
./run_vless.sh config
./run_vless.sh restart
```

### Проблема: Прокси не отвечает

1. Проверьте, что порт не занят:
```bash
netstat -tuln | grep 10809
```

2. Проверьте статус контейнера:
```bash
docker ps | grep xray
```

3. Протестируйте напрямую:
```bash
curl -x socks5://127.0.0.1:10809 https://httpbin.org/ip
```

### Проблема: 403 Forbidden все еще появляется

1. Убедитесь, что прокси настроен в `.env`:
```bash
grep HTTP_PROXY .env
```

2. Перезапустите приложение после изменения настроек:
```bash
./run_vless.sh restart
# Перезапустите пайплайн
```

3. Проверьте, что httpx использует прокси (должна быть строка в логах):
```
[INFO] Anthropic client with proxy: socks5://127.0.0.1:10809
```

### Проблема: Подписка не загружается

```bash
# Проверьте подписку напрямую
curl -L "https://your-subscription-url" | base64 -d

# Проверьте, что установлен requests
python3 -c "import requests; print(requests.__version__)"
```

## Безопасность

- **Не коммитьте** `.env` с реальными подписками и VLESS ссылками
- Используйте **TLS** всегда (`security=tls` в параметрах)
- Не используйте `allowInsecure: true` в production
- Ограничьте доступ к локальным портам прокси (firewall)
- Регулярно обновляйте Docker образ Xray

## Альтернативные методы

### Использование Hiddify Next Desktop

1. Установите Hiddify Next
2. Импортируйте подписку
3. Включите системный прокси
4. Используйте `ALL_PROXY=http://127.0.0.1:1080` в `.env`

### Использование V2RayNG / Clash

Настройте клиент и используйте его локальный прокси-порт:
```env
ALL_PROXY=socks5://127.0.0.1:7890
```

## Производительность

### Сравнение протоколов

| Протокол | Задержка | Стабильность | Обнаружение |
|----------|----------|--------------|-------------|
| VLESS+WS+TLS | Низкая | Высокая | Сложно |
| Trojan+WS+TLS | Средняя | Высокая | Сложно |
| VMess+WS+TLS | Средняя | Высокая | Средне |
| Shadowsocks | Очень низкая | Средняя | Легко |

### Оптимизация

Для минимальной задержки:
1. Выберите сервер ближе к целевому API
2. Используйте VLESS вместо VMess/Trojan
3. Отключите Mux если не нужно
4. Используйте TCP вместо QUIC если соединение стабильное

## Дополнительные ресурсы

- [Xray Project](https://xtls.github.io/)
- [Hiddify](https://github.com/hiddify/hiddify-config)
- [VLESS Protocol](https://github.com/XTLS/VLESS)
- [Docker Xray Image](https://github.com/XTLS/Xray-core)
