---
name: "Automated Environment Sandbox Creation"
role: "MLOps"
trigger: "Создание изолированных Docker-контейнеров для субагентов, избегание dependency hell"
priority: high
allowed_tools: ["bash", "docker", "mcp:registry"]
context_rules:
 include: ["sandbox/", "config/sandbox_profiles.yaml"]
 exclude: ["*.tar", "tmp/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Быстрое развёртывание чистых сред для каждого агента с фиксированными зависимостями.

## Алгоритм
1. Выбрать профиль из `sandbox_profiles.yaml`.
2. Запустить `docker build -t sandbox:{id} .`.
3. Mount worktree, установить `.claudeignore`.
4. Записать `container_id` в память.

## Интеграции
- MCP: `registry` для базовых образов.
- `.claude/settings.json`: `"sandbox_mode": true`.

## Ограничения
- Авто-удаление после idle 2h.
- Запрет на host-network.

## Вывод
`sandbox_report.json` с `container_id`, `profile`, `status`, `idle_timeout`.

## Фоллбэк
При pull fail → fallback на cached image, retry.
