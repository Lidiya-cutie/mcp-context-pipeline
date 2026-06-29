---
name: "AI-Assisted Visual Regression Testing"
role: "QA"
trigger: "Сравнение скриншотов UI, детект визуальных багов, пороговая настройка tolerance"
priority: high
allowed_tools: ["bash", "python", "mcp:playwright"]
context_rules:
 include: ["tests/visual/", "baselines/"]
 exclude: ["screenshots_raw/", ".cache/"]
memory_integration: true
worktree_isolation: true
---
## Цель
AI-анализ пиксельных diff'ов с игнорированием динамических элементов (loader, ads, timestamps).

## Алгоритм
1. Запустить `playwright` в headless-режиме, снять эталон и текущий скриншот.
2. Применить `pixelmatch` + LLM-фильтр динамических зон.
3. Рассчитать `diff_score`. Если > `threshold` → пометить баг.
4. Сохранить отчёт в `агент-память/visual/`.

## Интеграции
- MCP: `playwright` для автоматизации браузера.
- `.claudeignore`: исключить `*.png`, оставить `visual_report.json`.

## Ограничения
- Тестирование только на утверждённых viewport'ах.
- Запрет на игнорирование accessibility-элементов.

## Формат вывода
`{"page": "...", "diff_score": 0.02, "ignored_zones": [...], "status": "PASS/FAIL"}`

## Фоллбэк
При false positive → обновить `mask_zones.yaml`, переснять baseline.
