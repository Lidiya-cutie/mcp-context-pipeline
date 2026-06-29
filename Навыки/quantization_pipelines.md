---
name: "Model Quantization & Optimization"
role: "ML Engineer"
trigger: "Квантование модели, INT8/FP8, ускорение инференса, валидация деградации"
priority: high
allowed_tools: ["python", "bash", "mcp:gpu_monitor"]
context_rules:
 include: ["scripts/quantize/", "config/quant_profiles.yaml"]
 exclude: ["*.bin", "cache/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Автоматизация квантования с контролем accuracy drop < 1.5%.

## Алгоритм
1. Загрузить профиль из `quant_profiles.yaml`.
2. Запустить `quantize.py --model $PATH --bits 8`.
3. Оценить на holdout, сравнить с baseline.
4. Сохранить `quantized_model/` и метрики в память.

## Интеграции
- MCP: `gpu_monitor` для проверки latency.
- `.claudeignore`: исключить `.onnx`, оставить `metrics.json`.

## Ограничения
- Запрет на деплои без валидации.
- Фиксация `quantization_config`.

## Вывод
`quantized_model/` + `accuracy_report.json` с `delta`, `latency_ms`, `size_mb`.

## Фоллбэк
При drop > 1.5% → откатиться к FP16, обновить профиль.
