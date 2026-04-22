# PII Guard - Модуль маскирования чувствительных данных

## Обзор

PII Guard - критический компонент безопасности (Security Phase 3), который предотвращает утечку персональных данных (PII - Personally Identifiable Information) во внешние LLM (OpenAI, Claude и др.).

## Возможности

- **Автоматическое обнаружение PII**: Использует Microsoft Presidio для NER и regex-распознавания
- **Поддержка множества сущностей**: Email, телефоны, имена, адреса, паспорта, ИНН, кредитные карты
- **Кроссплатформенность**: Работает на Windows и Linux
- **Специфика РФ**: Включает распознаватели для российских документов
- **Безопасность**: Все данные маскируются перед отправкой во внешние API

## Поддерживаемые типы сущностей

| Сущность | Presidio Type | Плейсхолдер | Описание |
|----------|---------------|-------------|----------|
| Email | `EMAIL_ADDRESS` | `[MASKED_EMAIL]` | Адреса электронной почты |
| Телефон | `PHONE_NUMBER` | `[MASKED_PHONE]` | Номера телефонов |
| Имя | `PERSON` | `[MASKED_NAME]` | Имена людей (NER) |
| Адрес | `LOCATION/ADDRESS` | `[MASKED_ADDRESS]` | Адреса и локации |
| Паспорт РФ | `RU_PASSPORT` | `[MASKED_ID]` | Российские паспорта |
| ИНН | `RU_INN` | `[MASKED_ID]` | Налоговые номера |
| Кредитная карта | `CREDIT_CARD` | `[MASKED_CARD]` | Номера карт |
| SSN | `US_SSN` | `[MASKED_ID]` | Социальные номера США |

## Использование

### Базовое использование

```python
from src.pii_guard import get_pii_guard

# Получить инстанс PII Guard
guard = get_pii_guard()

# Маскировать текст
text = "Меня зовут Иван Иванов, телефон +7 (999) 123-45-67, email ivan@example.com"
masked = guard.mask(text, language='en')

print(f"Original: {text}")
print(f"Masked:   {masked}")
# Output: Меня зовут [MASKED_NAME], телефон [MASKED_PHONE], email [MASKED_EMAIL]
```

### Получение статистики

```python
# Получить информацию о найденных сущностях
stats = guard.get_statistics(text, language='en')
# Output: {'RU_PHONE': 1, 'EMAIL_ADDRESS': 1, 'URL': 1, 'PHONE_NUMBER': 1}
```

### Использование с Secure Middleware

```python
from src.secure_middleware import create_secure_middleware

# Создать безопасное middleware
middleware = create_secure_middleware(
    provider='anthropic',
    model='claude-sonnet-4-20250514'
)

# Отправить запрос с автоматическим маскированием
response = await middleware.chat([
    {"role": "user", "content": "Contact me at ivan@example.com"}
])
# PII будет автоматически замаскирован перед отправкой в LLM
```

## Интеграция в MCP сервер

PII Guard автоматически интегрирован в MCP сервер через `SecureLLMMiddleware`:

```python
# В server.py
from secure_middleware import SecureLLMMiddleware

middleware = SecureLLMMiddleware(
    provider='anthropic',
    api_key=anthropic_api_key,
    model=ANTHROPIC_MODEL
)

# При вызове LLM автоматически применяется маскирование
summary = await middleware.summarize(text, language='ru')
```

## Настройка

### Переменные окружения

```env
# Включить/выключить маскирование PII
ENABLE_PII_MASKING=true

# Провайдер LLM
LLM_PROVIDER=anthropic

# Модель
ANTHROPIC_MODEL=claude-sonnet-4-20250514
```

### Настройка PII Guard

```python
from src.pii_guard import PIIGuard

# Создать PII Guard с настройками
guard = PIIGuard(
    language='ru',              # Язык по умолчанию
    score_threshold=0.4,        # Порог уверенности (0.0-1.0)
    enable_custom_entities=True # Включить российские сущности
)
```

## Тестирование

### Запуск тестов полноты

```bash
# Тест на 100 шаблонов
python tests/test_pii_completeness.py --count 100

# Тест на 20 шаблонов (быстрый)
python tests/test_pii_completeness.py --count 20 --quiet
```

### Интеграционные тесты

```bash
# Тест интеграции с MCP пайплайном
python tests/test_pii_integration.py
```

### Метрики тестов

- **Recall (Полнота)**: Доля найденных PII от всех внедренных
- **Precision (Точность)**: Доля верно найденных сущностей
- **Leakage Check**: Отсутствие оригинальных данных в выходном тексте

## Примеры результатов тестов

```
Total Tests: 100
Successful Masks: 100 (100.0%)
Leakage Detected: 0
Failed Tests: 0

Entity Detection Statistics:
  PERSON              :  88
  PHONE_NUMBER        :  60
  RU_PASSPORT         :  38
  EMAIL_ADDRESS       :  35
  RU_PHONE            :  28
  RU_INN              :  13
  CREDIT_CARD         :  11

✓ EXCELLENT: PII masking is working correctly!
```

## Ограничения

1. **NER модели**: Presidio поддерживает NER только для английского языка из коробки
2. **Русский язык**: Для русского языка используются только regex-распознаватели
3. **Ложные срабатывания**: Возможны при наличии чисел, похожих на ИНН или паспорта

## Безопасность

- ✅ Все данные маскируются ПЕРЕД отправкой во внешние API
- ✅ Используются плейсхолдеры вместо реальных данных
- ✅ Логирование безопасности для аудита
- ✅ TTL для данных в Redis
- ✅ Поддержка российских документов (паспорт, ИНН)

## Troubleshooting

### PII не маскируется

Проверьте настройки:
```env
ENABLE_PII_MASKING=true
```

### Проблемы с русским языком

Убедитесь, что включены кастомные распознаватели:
```python
guard = PIIGuard(enable_custom_entities=True)
```

### Не обнаруживаются сущности

Проверьте порог уверенности:
```python
guard = PIIGuard(score_threshold=0.3)  # Снизить порог
```

## Лицензия

MIT License

## Контакты

Для вопросов и предложений создайте issue в репозитории.
