---
name: "Contextual Data Synthesis"
role: "Data Scientist"
trigger: "Генерация синтетических данных, балансировка классов, аугментация под конкретный домен"
priority: high
allowed_tools: ["python", "bash", "mcp:clickhouse_read", "git"]
context_rules:
 include: ["src/data/", "config/synth_profiles.yaml"]
 exclude: ["*.parquet", "venv/", "logs/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Создание синтетических датасетов с сохранением статистических и семантических свойств оригинала, учёт доменного сленга/артефактов.

## Алгоритм
1. Загрузить профиль генерации из `config/synth_profiles.yaml`.
2. Через `mcp:clickhouse_read` получить распределения ключевых признаков.
3. Запустить `python scripts/synth_generate.py --profile $PROFILE --seed $RANDOM`.
4. Валидировать KS-тестом и записать метаданные в `агент-память/`.

## Интеграции
- MCP: `clickhouse_read` для эмпирических распределений.
- `.claudeignore`: исключить сырые дампы, оставить только `metadata.json`.
- Память: сохранить `synth_version`, `seed`, `ks_p_value`.

## Ограничения
- Запрещено генерировать PII-поля. При обнаружении паттернов email/phone — остановка.
- Лимит токенов: 12k на сессию генерации.

## Формат вывода
```json
{
 "dataset_path": "data/synth_v{N}.parquet",
 "rows": 0,
 "ks_p_values": {"feature_A": 0.0},
 "warnings": []
}
```
## Фоллбэк
При падении KS < 0.05 → увеличить `--temperature` и перезапустить до 3 итераций.
