# Метрика обратной совместимости API

Инструмент для количественной оценки breaking changes при сравнении двух версий OpenAPI спецификаций.

## Функционал

- Сравнение двух OpenAPI 3.0 спецификаций
- Определение типов breaking changes:
  - Удаление эндпоинта (severity: 2.0)
  - Удаление поля (severity: 1.0)
  - Изменение типа поля (severity: 0.5)
  - Удаление обязательного поля (severity: 0.8)
  - Добавление обязательного поля (severity: 0.3)
  - Изменение HTTP метода (severity: 1.5)

- Расчёт метрик:
  - Risk Score: сумма severity всех изменений
  - Compatibility Score: 1.0 - (risk_score / total_endpoints_v1)

## Установка

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Использование

### CLI

```bash
# Базовое сравнение
python src/compat_cli.py data/openapi_v1.json data/openapi_v2.json

# Детальный вывод
python src/compat_cli.py data/openapi_v1.json data/openapi_v2.json --detailed

# JSON вывод
python src/compat_cli.py data/openapi_v1.json data/openapi_v2.json --json

# Установка порога совместимости
python src/compat_cli.py data/openapi_v1.json data/openapi_v2.json --threshold 0.9
```

### Python API

```python
from src.api_compatibility import calculate_backwards_compatibility

report = calculate_backwards_compatibility("data/openapi_v1.json", "data/openapi_v2.json")

print(f"Compatibility Score: {report.compatibility_score}")
print(f"Risk Score: {report.risk_score}")

for change in report.changes:
    print(f"{change.change_type}: {change.description}")
```

## Тесты

```bash
pytest tests/test_api_compatibility.py -v
```

## Примеры

В каталоге `data/` содержатся 8 пар примеров OpenAPI спецификаций:

- `compat_example_1_*` - Products API (backward compatible, добавлено поле category)
- `compat_example_2_*` - Orders API (удалено поле created_at)
- `compat_example_3_*` - Comments API (backward compatible, string -> enum)
- `compat_example_4_*` - Blog API (удалён метод POST /api/posts)
- `compat_example_5_*` - Notifications API (изменён тип id: integer -> string)
- `compat_example_6_*` - Users API (удалено поле active)
- `compat_example_7_*` - Payments API (изменён тип amount: number -> integer)
- `compat_example_8_*` - Inventory API (удалены вложенные объекты location)

## Интерпретация результатов

- **Compatibility Score >= 0.8**: Хорошая совместимость
- **Compatibility Score 0.5 - 0.8**: Обнаружены breaking changes
- **Compatibility Score < 0.5**: Высокий риск breaking changes
