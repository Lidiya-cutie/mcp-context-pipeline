---
name: "AI Model Output Validation"
role: "QA"
trigger: "Проверка ответов ML-моделей, валидация схем, граничные кейсы, детект аномалий инференса"
priority: critical
allowed_tools: ["python", "pytest", "mcp:api_gateway"]
context_rules:
 include: ["tests/api/", "schemas/model_output.json"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Автоматическая валидация ответов ML-эндпоинтов на соответствие JSON Schema, бизнес-правилам и допустимым диапазонам.

## Алгоритм
1. Загрузить `model_output.json` и исторические эталоны из `агент-память/`.
2. Запустить `pytest tests/api/test_model_responses.py --schema`.
3. Проверить типы, диапазоны confidence score, наличие запрещённых меток.
4. Сохранить отчёт в память, линковать с JIRA-тикетом.

## Интеграции
- MCP: `api_gateway` для live-запросов к staging.
- `.claudeignore`: исключить `raw_responses/`, оставить `validation_report.json`.

## Ограничения
- Фолл при `confidence < 0.3` без fallback-метки.
- Запрет на тестирование prod-эндпоинтов.

## Формат вывода
`{"status": "PASS/FAIL", "schema_violations": [], "edge_cases_triggered": 0, "recommendations": []}`

## Фоллбэк
При schema mismatch → сгенерировать diff, создать PR с фиксом схемы, уведомить ML-инженера.
