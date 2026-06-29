---
name: "CI/CD Pipeline Synthesis for ML"
role: "MLOps"
trigger: "Генерация GitHub Actions/GitLab CI под GPU-тесты, валидацию фотометрии, деплой"
priority: high
allowed_tools: ["bash", "python", "mcp:ci_templates"]
context_rules:
 include: [".github/", "config/ci_rules.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Автоматическая генерация pipeline: lint → test → quantize → build → deploy → monitor.

## Алгоритм
1. Считать `ci_rules.yaml`.
2. Сгенерировать `.github/workflows/ml.yml`.
3. Валидировать синтаксис, запустить dry-run.
4. Записать `pipeline_version` в память.

## Интеграции
- MCP: `ci_templates` для базовых шаблонов.
- `.claude/settings.json`: `"ci_generation": true`.

## Ограничения
- Только approved runners.
- Фиксация `pipeline_hash`.

## Вывод
`pipeline_report.json` с `workflow_file`, `stages`, `validation_status`.

## Фоллбэк
При syntax error → rollback to `v{N-1}`, alert DevOps.
