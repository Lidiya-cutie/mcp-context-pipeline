---
name: "Automated Unit & Integration Testing for ML"
role: "ML Engineer"
trigger: "Запуск тестов пайплайнов, валидация схем данных, проверка совместимости API"
priority: high
allowed_tools: ["bash", "python", "pytest"]
context_rules:
 include: ["tests/", "config/test_profiles.yaml"]
 exclude: ["__pycache__/", ".pytest_cache/"]
memory_integration: false
worktree_isolation: true
---
## Цель
Полное покрытие: unit (функции), integration (end-to-end пайплайн), schema validation.

## Алгоритм
1. Запустить `pytest tests/ --cov=src`.
2. Валидировать схемы через `pydantic`.
3. Проверить совместимость с `api/v2/`.
4. Сгенерировать `test_report.xml`.

## Интеграции
- `.claude/settings.json`: `"allowed_commands": ["pytest", "coverage run"]`.
- Worktree: изоляция от prod-ветки.

## Ограничения
- Fail на coverage < 80%.
- Запрет на пропуск integration-тестов.

## Вывод
`test_report.json` с `passed`, `failed`, `coverage`, `blocking_issues`.

## Фоллбэк
При flaky тест → изолировать в `quarantine/`, уведомить разработчика.
