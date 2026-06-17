# Pipeline: Iterative Correction with Feedback Loop

Оркестратор итеративной коррекции текстового сжатия с обратной связью.
Замыкает цикл: генерация LLM -> валидация метрик -> подсказка -> перегенерация.

## Архитектура

```
                   +------------------+
                   |   test_cases.py  |
                   |  (5 примеров)    |
                   +--------+---------+
                            |
                            v
+-----------+    +------------------+    +-----------------+
|  .env     |--->|  orchestrator.py |--->| context_manager |
| (API keys)|    |  (главный цикл)  |    | compute_f1      |
+-----------+    +--------+---------+    | compute_sim     |
                          |              | estimate_tokens |
                          |              +-----------------+
                   +------v------+
                   |  logger.py  |
                   |  (JSONL)    |
                   +-------------+
                          |
                          v
                   +------+-------+
                   |  run_pilot   |
                   |  results.json|
                   +--------------+
```

### Компоненты

| Файл              | Назначение                                              |
|-------------------|---------------------------------------------------------|
| `orchestrator.py` | Главный оркестратор: цикл генерация-валидация-коррекция |
| `test_cases.py`   | 5 тестовых примеров с разными типами сущностей         |
| `run_pilot.py`    | Запуск пилота на всех примерах, сохранение результатов  |
| `logger.py`       | Логирование итераций в JSONL                            |

### Алгоритм

```
for iteration in 1..max_iterations:
    1. coder_agent генерирует текст через LLM API
    2. evaluator_agent валидирует: compute_f1 + compute_similarity
    3. Если F1 >= 0.95 И context_drift < 0.15 -> СХОДИТСЯ, выход
    4. Иначе: формируется hint на основе ошибок:
       - Какие entity types потеряны (precision/recall)
       - Семантический дрейф
       - Конкретные lost entities
    5. Перегенерация с hint в system prompt
    6. Логирование в JSONL
```

### Пороги схождения

- **F1 >= 0.95** — все сущности сохранены
- **context_drift < 0.15** — семантика не разрушилась
- Максимум **3 итерации** на тестовый кейс

## Интеграция

Оркестратор импортирует функции напрямую из `src/mcp_servers/context_manager/server.py`:
- `compute_f1(original, compressed)` — entity F1 по типам
- `compute_similarity(original, compressed)` — cosine TF-IDF similarity
- `estimate_tokens(text)` — оценка токенов
- `extract_entities(text)` — извлечение сущностей (для hint)

LLM вызовы: z.ai anthropic-compatible endpoint, модель `glm-4.7`.

## Запуск

```bash
cd /mldata/mcp_context_pipeline
python -m pipeline.run_pilot
```

### Требования

- Python 3.10+
- httpx, python-dotenv
- Доступ к z.ai API (ANTHROPIC_API_KEY в .env)
- `src/mcp_servers/context_manager/server.py` должен быть доступен для импорта

### Результаты

- `pipeline/results/pilot_results.json` — полные результаты пилота
- `pipeline/logs/<test_case>.jsonl` — лог итераций по каждому кейсу

### Формат лога (JSONL)

```json
{"timestamp": "2025-01-15T10:30:00Z", "test_case": "tc1", "iteration": 1,
 "f1": 0.65, "semantic_sim": 0.78, "context_drift": 0.22,
 "hint": "Потеряны сущности: email='ops@imbalanced.tech'...",
 "converged": false, "compression_ratio": 0.35, "latency_ms": 1200.5}
```

### Формат результатов

```json
{
  "run_timestamp": "...",
  "model": "glm-4.7",
  "total_cases": 5,
  "converged": 4,
  "avg_iterations": 2.1,
  "avg_final_f1": 0.93,
  "results": [...]
}
```
