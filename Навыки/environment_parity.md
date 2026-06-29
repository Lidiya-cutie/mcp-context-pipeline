---
name: "Environment Parity & Dependency Locking"
role: "ML Engineer"
trigger: "Синхронизация окружений, фиксация Python/CUDA версий, разрешение конфликтов"
priority: high
allowed_tools: ["bash", "python", "mcp:registry"]
context_rules:
 include: ["requirements/", "Dockerfile", "config/env.yaml"]
 exclude: ["__pycache__/", ".venv/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Гарантия идентичности сред: Python 3.12, CUDA 12.4, точные хеши пакетов.

## Алгоритм
1. Сравнить `requirements.txt` с `env.yaml`.
2. Запустить `pip-compile --generate-hashes`.
3. Валидировать `torch`/`cuda` совместимость.
4. Зафиксировать хеш в памяти.

## Интеграции
- MCP: `registry` (PyPI/conda mirror).
- `.claude/settings.json`: `"allowed_commands": ["pip-compile", "docker build"]`.

## Ограничения
- Запрет на `pip install --upgrade` без фиксации.
- Проверка `wheel` совместимости с CPU/GPU.

## Вывод
`requirements.locked.txt` + `compatibility_report.json`.

## Фоллбэк
При конфликте → изолировать в venv и предложить `Docker`-сборку.
