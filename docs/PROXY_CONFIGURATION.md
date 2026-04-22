# Настройка прокси для обхода региональных ограничений

## Обзор

Модуль `proxy_client.py` предоставляет возможность обходить региональные ограничения для LLM API (Anthropic Claude, OpenAI) и внешних сервисов (Tavily, Exa, Firecrawl, DocFusion).

## Поддерживаемые клиенты

1. **Anthropic API** (синхронный и асинхронный)
2. **OpenAI API** (синхронный и асинхронный)
3. **urllib.request** (для HTTP запросов в providers.py)

## Настройка

### 1. Установите зависимости

```bash
pip install httpx>=0.24.0
```

### 2. Настройте переменные окружения в `.env`

Добавьте одну из следующих переменных:

```env
# HTTP прокси
HTTP_PROXY=http://username:password@proxy.example.com:8080

# HTTPS прокси
HTTPS_PROXY=http://username:password@proxy.example.com:8080

# Или универсальная переменная
ALL_PROXY=http://username:password@proxy.example.com:8080
```

### 3. Примеры настроек прокси

#### HTTP прокси с аутентификацией
```env
HTTP_PROXY=http://user:pass@proxy.company.com:8080
```

#### SOCKS5 прокси (требует установку httpx[socks])
```env
HTTP_PROXY=socks5://127.0.0.1:1080
```

#### Локальный прокси (например, Clash, V2Ray)
```env
HTTP_PROXY=http://localhost:7890
```

#### HTTPS прокси
```env
HTTPS_PROXY=https://proxy.example.com:8443
```

## Использование в коде

### Автоматическое использование через переменные окружения

Большинство компонентов автоматически используют прокси если настроены переменные окружения:

```python
# translator.py - автоматически использует прокси
from src.translator import get_translator
translator = get_translator()
result = translator.translate("Hello")

# server.py - автоматически использует прокси
from src.server import get_llm_client
client = get_llm_client()

# secure_middleware.py - автоматически использует прокси
from src.secure_middleware import create_secure_middleware
middleware = create_secure_middleware()
```

### Явное использование прокси

```python
from src.proxy_client import get_anthropic_client, get_proxy_url

proxy_url = get_proxy_url()
clients = get_anthropic_client(api_key="sk-...", proxy_url=proxy_url)
async_client = clients["async"]
```

## Проверка работы

Запустите тестовый скрипт:

```bash
python3 test_proxy.py
```

## Устранение неполадок

### Прокси не работает

1. Проверьте, что прокси доступен:
```bash
curl -x http://localhost:7890 https://httpbin.org/ip
```

2. Убедитесь, что `httpx` установлен:
```bash
python3 -c "import httpx; print(httpx.__version__)"
```

3. Проверьте логи - компоненты должны выводить сообщение о использовании прокси.

### Ошибка 403 Forbidden

Если вы все еще получаете 403, возможно:

1. Прокси заблокирован API провайдером
2. Нужен другой тип прокси (SOCKS5 вместо HTTP)
3. Прокси требует аутентификацию

### Timeout ошибки

Увеличьте таймаут в коде или используйте более быстрый прокси.

## Безопасность

- Не коммитьте `.env` файл с реальными данными прокси
- Используйте переменные окружения вместо жестко прописанных URL
- Для SOCKS5 прокси установите `httpx[socks]`

## Дополнительные ресурсы

- [httpx documentation](https://www.python-httpx.org/)
- [Anthropic SDK documentation](https://docs.anthropic.com/)
- [OpenAI SDK documentation](https://platform.openai.com/docs)
