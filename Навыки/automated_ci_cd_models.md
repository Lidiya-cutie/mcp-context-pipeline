---
name: "Automated CI/CD for Model Artifacts"
role: "ML Engineer"
trigger: "Сборка контейнера, пуш в registry, деплой staging после тестов"
priority: high
allowed_tools: ["bash", "docker", "mcp:gitlab_ci"]
context_rules:
 include: [".github/workflows/", "Dockerfile", "config/deploy.yaml"]
 exclude: ["*.tar", "build/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Автоматизация pipeline: build → test → push → deploy (staging).

## Алгоритм
1. Проверить статус тестов в worktree.
2. Запустить `docker build -t model:{hash} .`.
3. Push в registry, обновить `deploy.yaml`.
4. Запустить `staging_health_check.sh`.

## Интеграции
- MCP: `gitlab_ci` для триггеров.
- `.claudeignore`: скрыть `*.tar`, оставить `manifest.json`.

## Ограничения
- Запрет на деплой без passing tests.
- Фиксация `image_digest`.

## Вывод
`ci_report.json` с `build_time`, `tests_passed`, `image_tag`, `staging_status`.

## Фоллбэк
При fail test → создать `hotfix` worktree, уведомить разработчика.
