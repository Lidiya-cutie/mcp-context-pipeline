---
name: "Automated Model Evaluation"
role: "Data Scientist"
trigger: "Валидация новой модели, сравнение с baseline/SOTA, оценка на holdout"
priority: high
allowed_tools: ["python", "bash", "mcp:clickhouse_read"]
context_rules:
 include: ["src/eval/", "models/baseline/"]
 exclude: ["*.ckpt", "wandb/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Стандартизированная оценка моделей: ROC-AUC, F1, latency, throughput, calibration.

## Алгоритм
1. Загрузить `holdout` из ClickHouse.
2. Запустить `python scripts/eval_model.py --model_path $PATH`.
3. Сравнить с baseline из `агент-память/baselines/`.
4. Сгенерировать `evaluation_card.md`.

## Интеграции
- MCP: `clickhouse_read` для holdout.
- Память: сохранить `best_metrics`, `model_hash`.

## Ограничения
- Запрет на тестирование на данных из train/val.
- Фиксация random seed.

## Вывод
JSON + markdown-карточка с графиками, `delta_vs_baseline`, `recommendation`.

## Фоллбэк
При деградации > 3% → автоматически пометить `STAGING` и создать JIRA-тикет.
