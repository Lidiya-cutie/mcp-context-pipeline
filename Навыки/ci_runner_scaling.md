---
name: "CI/CD Runner Scaling & Cache Optimization"
role: "DevOps"
trigger: "Масштабирование GitHub Actions/GitLab runners, кэш стратегия, parallel job tuning"
priority: high
allowed_tools: ["bash", "docker", "mcp:ci_platform"]
context_rules:
 include: ["ci/", "config/runner_policies.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Ускорение пайплайнов: ephemeral runners, dependency caching, job parallelism.

## Алгоритм
1. Анализировать queue depth через MCP.
2. Настроить `actions-runner-controller` / `gitlab-runner`.
3. Применить `cache-key` стратегии, включить parallel matrix.
4. Сохранить `ci_metrics` в память.

## Интеграции
- MCP: `ci_platform`, `storage` (S3 cache).
- `.claudeignore`: скрыть `runner_logs/`, оставить `ci_perf.json`.

## Ограничения
- Max concurrent <= license limit.
- Cache TTL <= 7 days.

## Формат вывода
`{"avg_pipeline_time": "4m", "queue_wait": "10s", "cache_hit_rate": "82%"}`

## Фоллбэк
При cache miss > 50% → invalidate, rebuild, alert DevOps.
