---
name: "Test Data Synthesis & PII Masking"
role: "QA"
trigger: "Генерация реалистичных тестовых данных, маскирование PII, создание edge-case сценариев"
priority: critical
allowed_tools: ["python", "bash", "mcp:pii_scanner", "mcp:clickhouse_read"]
context_rules:
 include: ["tests/fixtures/", "config/data_gen_rules.yaml"]
 exclude: ["raw_dumps/", "*.csv"]
memory_integration: false
worktree_isolation: true
---
## Цель
Безопасная генерация тестовых наборов с сохранением статистических свойств и нулевым риском утечки.

## Алгоритм
1. Считать схему из ClickHouse через MCP.
2. Сгенерировать данные по `data_gen_rules.yaml` с faker-паттернами.
3. Прогнать через `mcp:pii_scanner`, замаскировать sensitive поля.
4. Сохранить в `fixtures/` с checksum.

## Интеграции
- MCP: `pii_scanner`, `clickhouse_read`.
- `.claudeignore`: исключить `*.parquet`, оставить `metadata.json`.

## Ограничения
- Zero raw PII в артефактах.
- Фиксация `seed` для воспроизводимости.

## Формат вывода
`{"dataset_path": "...", "rows": 0, "pii_masked": true, "checksum": "sha256:..."}`

## Фоллбэк
При detect PII → остановить генерацию, обновить regex-правила, перезапустить.
