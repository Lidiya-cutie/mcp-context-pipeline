---
name: "Performance Profiling & Bottleneck Resolution"
role: "ML Engineer"
trigger: "Анализ latency, CPU/GPU утилизации, оптимизация bottlenecks"
priority: medium
allowed_tools: ["bash", "python", "mcp:gpu_monitor"]
context_rules:
 include: ["scripts/profile/", "config/bottleneck_rules.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Поиск узких мест: dataloader, memory allocation, kernel execution, I/O.

## Алгоритм
1. Запустить `py-spy` / `torch.profiler`.
2. Агрегировать `timeline.json`.
3. Сопоставить с `bottleneck_rules.yaml`.
4. Предложить оптимизации, сохранить в память.

## Интеграции
- MCP: `gpu_monitor` для real-time метрик.
- `.claudeignore`: скрыть `raw_traces/`, оставить `summary.json`.

## Ограничения
- Профилирование только в staging.
- Запрет на изменение prod-кода без review.

## Вывод
`profile_report.md` с `top_bottlenecks`, `optimization_plan`, `expected_gain`.

## Фоллбэк
При неоднозначных данных → увеличить sample size, перезапустить.
