---
name: "Domain-Specific NLP/CV Processing"
role: "Data Scientist"
trigger: "Обработка доменного текста/изображений, кастомные токенизаторы, препроцессинг"
priority: high
allowed_tools: ["python", "bash", "mcp:clickhouse_read"]
context_rules:
 include: ["src/proc/", "config/domain_rules.yaml"]
 exclude: ["*.bin", "cache/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Адаптация препроцессинга под специфику модерации: сленг, сокращения, артефакты изображений.

## Алгоритм
1. Загрузить `domain_rules.yaml`.
2. Применить кастомный токенизатор/аугментатор.
3. Валидировать на золотом сете.
4. Сохранить конфиг и метрики в память.

## Интеграции
- MCP: `clickhouse_read` для золотого сета.
- `.claudeignore`: скрыть временные артефакты.

## Ограничения
- Запрет на удаление стоп-слов, если они несут смысл.
- Фиксация версии препроцессора.

## Вывод
`processor_v{N}.pkl` + `validation_metrics.json`.

## Фоллбэк
При падении accuracy > 5% → откатиться к `v{N-1}`.
