---
name: "Distributed Training & Checkpoint Management"
role: "ML Engineer"
trigger: "DDP/FSDP обучение, управление чекпоинтами, восстановление после прерывания"
priority: high
allowed_tools: ["bash", "python", "mcp:storage"]
context_rules:
 include: ["scripts/ddp/", "config/train_distributed.yaml"]
 exclude: ["*.ckpt", "tmp/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Настройка распределённого обучения, авто-сохранение чекпоинтов, graceful recovery.

## Алгоритм
1. Инициализировать `torchrun` с `--nnodes`, `--nproc_per_node`.
2. Настроить `CheckpointCallback` в `checkpoints/`.
3. При прерывании → автоматически восстановить из `latest.pt`.
4. Записать `epoch`, `loss`, `node_status` в память.

## Интеграции
- MCP: `storage` для сетевых чекпоинтов.
- `.claudeignore`: скрыть `*.ckpt`, оставить `state.json`.

## Ограничения
- Запрет на ручное удаление чекпоинтов.
- Валидация синхронизации градиентов.

## Вывод
`train_log.json` с `epochs_completed`, `checkpoints_saved`, `recovery_status`.

## Фоллбэк
При sync error → уменьшить `gradient_accumulation`, рестарт.
