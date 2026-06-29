---
name: "Semantic Similarity Search Optimization"
role: "Data Scientist"
trigger: "Поиск похожих изображений/текстов, тюнинг векторного ретривала, оценка embedding-качества"
priority: medium
allowed_tools: ["python", "bash", "mcp:vector_db"]
context_rules:
 include: ["src/embeddings/", "config/retrieval.yaml"]
 exclude: ["*.bin", "cache/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Настройка параметров FAISS/Chroma, выбор метрики расстояния, валидация recall@k.

## Алгоритм
1. Загрузить эмбеддинги, проверить размерность.
2. Запустить `python scripts/eval_retrieval.py --k 5,10,20`.
3. Подобрать `nprobe`/`ef_search` для баланса latency/accuracy.
4. Сохранить оптимальный конфиг в `агент-память/retrieval/`.

## Интеграции
- MCP: `vector_db` для live-запросов.
- `.claudeignore`: исключить `.faiss` индексы >500MB.

## Ограничения
- Запрет на full-scan в production-индексах.
- Лимит памяти процесса: 8GB.

## Вывод
JSON с `best_params`, `recall@k`, `avg_latency_ms`, `recommendations`.

## Фоллбэк
При OOM → переключиться на `IVF_PQ` и уменьшить `nlist`.
