---
name: "LLM-Assisted Feature Engineering"
role: "Data Scientist"
trigger: "Генерация новых признаков из текста/метаданных, парсинг неструктурированных данных"
priority: medium
allowed_tools: ["python", "bash", "mcp:anthropic_api"]
context_rules:
 include: ["src/features/", "prompts/feat_gen.md"]
 exclude: ["*.csv", "raw/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Использование Claude для создания фичей на основе доменных описаний, с валидацией корреляции.

## Алгоритм
1. Загрузить `prompts/feat_gen.md`.
2. Сформировать батч-запросы к API (chunking 500 строк).
3. Склеить результаты, проверить `abs(corr) > 0.15` с target.
4. Сохранить фичи и промпт-версию в память.

## Интеграции
- MCP: `anthropic_api` с rate-limit 10 req/s.
- `.claudeignore`: скрыть промпты и черновики.

## Ограничения
- Запрет на генерацию target-leaking фичей.
- Авто-фильтрация NaN > 40%.

## Вывод
`features_v{N}.parquet` + `validation_report.md`.

## Фоллбэк
При high NaN → применить imputation или отбросить фичу.
