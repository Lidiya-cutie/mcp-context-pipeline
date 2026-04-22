# Best Practices для работы с внешними знаниями в MCP Context Pipeline

## Архитектурные паттерны

### 1. Unified Router Pattern

Единый роутер `ExternalKnowledgeRouter` управляет всеми провайдерами внешних знаний.

**Когда использовать:**
- Несколько источников знаний с единым интерфейсом
- Необходимость в агрегации результатов из разных источников
- Требование к единой метрике и мониторингу

**Преимущества:**
- Единая точка входа для всех запросов
- Общая логика кэширования и reranking
- Централизованные метрики и алерты
- Упрощенное добавление новых провайдеров

**Пример:**
```python
from src.external_knowledge import ExternalKnowledgeRouter, Context7Provider, LocalIndexProvider

router = ExternalKnowledgeRouter(
    providers=[Context7Provider(session), LocalIndexProvider()],
    cache_ttl_seconds=3600
)

result = await router.search(
    query="FastAPI JWT authentication",
    context={"library": "fastapi"},
    limit=5
)
```

**Реализация:** `src/external_knowledge/router.py:19-643`

### 2. Provider Pattern

Все провайдеры наследуются от `BaseExternalKnowledgeProvider` для обеспечения унифицированного интерфейса.

**Когда использовать:**
- Добавление нового источника знаний
- Модульное тестирование провайдеров
- Гибкая конфигурация набора провайдеров

**Интерфейс:**
```python
from src.external_knowledge.base import BaseExternalKnowledgeProvider, KnowledgeChunk

class CustomProvider(BaseExternalKnowledgeProvider):
    def __init__(self, name: str):
        super().__init__(name)

    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[KnowledgeChunk]:
        pass
```

**Реализация:** `src/external_knowledge/base.py:23-34`

### 3. Caching Pattern

Кэширование результатов через Redis с TTL для снижения нагрузки на внешние API.

**Когда использовать:**
- Повторяющиеся запросы
- Высокая стоимость внешних API вызовов
- Требование к низкой latency

**Конфигурация:**
```env
EXTERNAL_KNOWLEDGE_CACHE_TTL=3600
EXTERNAL_KNOWLEDGE_USE_REDIS=true
EXTERNAL_KNOWLEDGE_REDIS_PREFIX=extk
```

**Практики:**
- Устанавливайте TTL в зависимости от частоты обновления данных
- Используйте разные префиксы для разных окружений
- Мониторьте cache hit rate (>20%)

**Реализация:** `src/external_knowledge/router.py:119-174`

### 4. Reranking Pattern

Комбинированный reranking с весами источников для улучшения релевантности.

**Когда использовать:**
- Множественные источники с разным качеством
- Требование к персонализации результатов
- Необходимость в адаптации под домен

**Формула:**
```
rerank_score = normalized_score * 0.55
              + source_weight * 0.35
              + keyword_ratio * 0.10
```

**Практики:**
- Регулируйте веса источников на основе A/B тестов
- Мониторите распределение источников по результатам
- Используйте keyword ratio для бустинга точных совпадений

**Реализация:** `src/external_knowledge/router.py:246-269`

### 5. Fallback Pattern

Graceful degradation при ошибках провайдеров для обеспечения доступности.

**Когда использовать:**
- Критичные системы с требованиями к availability
- Нестабильные внешние API
- Необходимость в непрерывной работе

**Сценарии:**
- Empty result: возврат кэша или другого провайдера
- Timeout: использование следующего провайдера
- Error: логирование и продолжение работы

**Конфигурация degradation тестов:**
```env
EVAL_DEGRADATION_SAMPLE_SIZE=50
EVAL_MIN_FALLBACK_SUCCESS_RATE=0.95
```

**Реализация:** `src/external_knowledge/router.py:587-610`

## Мини-чеклист перед push (безопасность секретов)

Перед отправкой изменений в удаленный репозиторий выполнить:

```bash
git status
git check-ignore -v .env
git ls-files .env
git diff --cached --name-only
```

Обязательные условия:
- `.env` находится в ignore.
- `git ls-files .env` возвращает пустой вывод.
- В staged-списке отсутствуют `.env` и другие файлы с ключами/токенами.

Безопасная последовательность:

```bash
git add .
git restore --staged .env
git commit -m "your message"
git push origin master
```

## Сценарии использования

### Сценарий 1: Документация библиотек с Context7

**Проблема:** Требуется актуальная документация для Python библиотек.

**Решение:**
```python
from src.host_orchestrator import ContextOrchestrator

orchestrator = ContextOrchestrator(enable_context7=True)
await orchestrator.connect()

docs = await orchestrator.query_library_docs(
    library="fastapi",
    query="OAuth2 password flow"
)
```

**Best practices:**
- Используйте конкретные запросы для лучших результатов
- Кэшируйте популярные запросы
- Комбинируйте с Knowledge Bridge для внутренних стандартов

### Сценарий 2: Локальная база знаний с SQLite FTS5

**Проблема:** Требуется поиск по внутренним документам без выхода в интернет.

**Решение:**
```python
from src.external_knowledge import ExternalKnowledgeRouter, LocalIndexProvider

provider = LocalIndexProvider()
await provider.ingest_documents([
    {
        "title": "Python Coding Standards",
        "content": "doc_content...",
        "url": "internal://standards/python",
        "source": "internal",
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
])

router = ExternalKnowledgeRouter(providers=[provider])
result = await router.search("PEP 8 style guide")
```

**Best practices:**
- Bootstrap директорию при запуске
- Обновляйте индекс периодически
- Используйте BM25 ranking для FTS5

### Сценарий 3: Комбинация нескольких источников

**Проблема:** Требуется поиск по документации, вебу и внутренней базе знаний.

**Решение:**
```python
from src.external_knowledge import (
    ExternalKnowledgeRouter,
    Context7Provider,
    ExaProvider,
    LocalIndexProvider
)

providers = [
    Context7Provider(session),
    ExaProvider(),
    LocalIndexProvider()
]

router = ExternalKnowledgeRouter(providers=providers)
result = await router.search(
    "React Server Components best practices",
    context={"domain": "frontend"}
)
```

**Best practices:**
- Настраивайте веса источников по домену
- Используйте reranking для улучшения качества
- Мониторите source distribution

### Сценарий 4: Проектные данные через Shiva

**Проблема:** Требуется информация о проекте, командах, спринтах.

**Решение:**
```python
from src.external_knowledge import ExternalKnowledgeRouter, ShivaProvider

provider = ShivaProvider()
router = ExternalKnowledgeRouter(providers=[provider])

result = await router.search(
    "project status",
    context={"project_id": 123}
)
```

**Best practices:**
- Используйте project_id для точных результатов
- Кэшируйте результаты с долгим TTL
- Обновляйте провайдер при изменениях в Shiva

### Сценарий 5: Поиск по коду с GitHub

**Проблема:** Требуется найти примеры использования в репозитории.

**Решение:**
```python
from src.external_knowledge import ExternalKnowledgeRouter, GitHubProvider

provider = GitHubProvider()
router = ExternalKnowledgeRouter(providers=[provider])

result = await router.search(
    "authentication middleware",
    context={"repo": "tiangolo/fastapi"}
)
```

**Best practices:**
- Убедитесь, что gh CLI аутентифицирован
- Используйте конкретные имена файлов в запросах
- Ограничивайте результаты для скорости

## Выбор провайдера

### По типу запроса

| Тип запроса | Рекомендуемый провайдер | Причина |
|-------------|------------------------|---------|
| Документация библиотеки | Context7 | Актуальная документация из исходников |
| Внутренние стандарты | Knowledge Bridge | Компания-специфичные стандарты |
| Локальные документы | LocalIndexProvider | Приватность и скорость |
| Веб-поиск | Exa / Tavily | Нейросетевой поиск с фокусом на технический контент |
| Проектные данные | Shiva | Специализированный MCP сервер |
| Поиск по коду | GitHub | Прямой доступ к репозиториям |

### По критериям

| Критерий | Провайдер |
|----------|-----------|
| Приватность | LocalIndexProvider, DocFusion |
| Скорость | LocalIndexProvider, Knowledge Bridge |
| Актуальность | Context7, Exa, Tavily |
| Покрытие | Exa, Tavily, Firecrawl |
| Стоимость | LocalIndexProvider, Knowledge Bridge |

## Метрики и мониторинг

### Ключевые метрики

| Метрика | Описание | Целевое значение |
|---------|----------|------------------|
| Cache Hit Rate | Доля запросов из кэша | >20% |
| Recall@K | Доля релевантных результатов в top-K | >60% |
| MRR | Mean Reciprocal Rank | >0.45 |
| Latency P95 | 95-й перцентиль задержки | <8000 ms |
| Provider Errors | Ошибки провайдеров | <5% |

### Алерты

```env
EXTERNAL_ALERT_HIT_RATE_MIN=0.30
EXTERNAL_ALERT_P95_MAX_MS=5000
EXTERNAL_ALERT_MIN_REQUESTS=20
```

### Prometheus метрики

```python
# Получить метрики в формате Prometheus
prometheus = router.export_metrics_prometheus()

# Получить полные метрики в JSON
full_metrics = await router.export_metrics_json()
```

## Безопасность

### PII маскирование

Все запросы к внешним провайдерам автоматически маскируются:

```env
EXTERNAL_MASK_PII_QUERIES=true
```

**Маскируемые сущности:**
- Email адреса
- Телефонные номера
- Имена и адреса
- Российские документы (паспорт, ИНН, СНИЛС)

**Реализация:** `src/external_knowledge/router.py:90-117`

### Конфигурация прокси

Для обхода региональных ограничений:

```env
HTTP_PROXY=http://localhost:7890
HTTPS_PROXY=http://localhost:7890
ALL_PROXY=socks5://127.0.0.1:1080
```

## Тестирование

### Unit тесты провайдера

```python
import pytest
from src.external_knowledge.providers import LocalIndexProvider

@pytest.mark.asyncio
async def test_local_index_provider():
    provider = LocalIndexProvider()
    results = await provider.search(
        query="test query",
        limit=3
    )
    assert len(results) <= 3
    for result in results:
        assert result.source == "local_index"
```

### Интеграционные тесты

```bash
# Тесты интеграции Context7
python tests/test_context7_integration.py

# Тесты внешних знаний
python tests/test_external_knowledge_live.py

# Оффлайн оценка
python run_external_knowledge_eval.py
```

### Degradation тесты

```bash
# Автоматический запуск degradation сценариев
python tests/test_external_knowledge_eval_stage4.py
```

## Производительность

### Оптимизация кэша

1. **Настройка TTL по типу данных:**
   - Документация библиотек: 24 часа
   - Веб-поиск: 1 час
   - Локальные документы: 7 дней

2. **Warm-up кэша:**
   ```python
   # Предварительное прогревание кэша
   warm_queries = ["FastAPI auth", "React hooks", "Python async"]
   for query in warm_queries:
       await router.search(query)
   ```

### Оптимизация запросов

1. **Используйте конкретные запросы:**
   - Плохо: "authentication"
   - Хорошо: "FastAPI OAuth2 password flow"

2. **Укажите контекст:**
   ```python
   result = await router.search(
       "authentication",
       context={"library": "fastapi", "domain": "security"}
   )
   ```

3. **Ограничьте результаты:**
   ```python
   # 3 результата для скорости
   result = await router.search(query, limit=3)
   ```

## Troubleshooting

### Провайдер возвращает пустые результаты

**Причины:**
- Неверный запрос
- Неверная конфигурация API ключа
- Проблемы с сетью

**Решения:**
```python
# Проверьте здоровье провайдера
health = await router.get_provider_health()
print(health)

# Проверьте метрики
metrics = router.get_metrics()
print(metrics)
```

### Низкий cache hit rate

**Причины:**
- Слишком короткий TTL
- Большое разнообразие запросов
- Проблемы с Redis

**Решения:**
```bash
# Проверьте Redis
redis-cli ping

# Увеличьте TTL
EXTERNAL_KNOWLEDGE_CACHE_TTL=7200
```

### Высокая latency

**Причины:**
- Медленные внешние API
- Нехватка кэша
- Проблемы с сетью

**Решения:**
```python
# Проверьте P95 latency
metrics = router.get_metrics()
print(f"P95: {metrics['latency_ms_p95']} ms")

# Увеличьте cache hit rate
# или используйте локальный провайдер
```

## Заключение

Следуя этим best practices, вы сможете:
- Эффективно использовать внешние знания в MCP Context Pipeline
- Обеспечить высокую доступность и производительность
- Интегрировать новые источники знаний быстро и надежно
- Мониторить и оптимизировать систему

Для вопросов и предложений обратитесь к документации в `docs/` и примерам в `tests/`.
