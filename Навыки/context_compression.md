---
name: "Context Compression & Token Optimization"
role: "ML Engineer"
trigger: "Работа с большими репозиториями, минимизация токенов, оптимизация .claudeignore"
priority: medium
allowed_tools: ["bash", "python"]
context_rules:
 include: [".claudeignore", "scripts/token_audit.py"]
 exclude: ["node_modules/", "*.ckpt", "logs/"]
memory_integration: false
worktree_isolation: false
---
## Цель
Динамическая оптимизация `.claudeignore` для снижения затрат токенов без потери контекста.

## Алгоритм
1. Проанализировать `git diff --stat`.
2. Запустить `token_audit.py` для оценки веса файлов.
3. Обновить `.claudeignore` с приоритетом: `logs/ > binaries/ > tests/`.
4. Записать `token_savings` в память.

## Интеграции
- `.claudeignore`: авто-генерация правил.
- `.claude/settings.json`: `"max_tokens_per_session": 8000`.

## Ограничения
- Запрет на исключение `src/`, `config/`, `Навыки/`.
- Валидация после каждого обновления.

## Вывод
`.claudeignore.updated` + `compression_report.json`.

## Фоллбэк
При потере критического контекста → восстановить из `git stash`.
