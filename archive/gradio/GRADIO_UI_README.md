# Gradio UI для MCP Context Pipeline

Визуальный интерфейс на базе Gradio для управления MCP Context Pipeline.

## Установка

Установите Gradio:

```bash
pip install -r requirements.txt
```

## Запуск

### Linux/Mac:

```bash
chmod +x run_gradio.sh
./run_gradio.sh
```

### Windows:

```cmd
run_gradio.bat
```

Или напрямую:

```bash
python gradio_ui.py
```

## Функционал

### Инициализация
- Инициализация Orchestrator для работы с пайплайном

### Статистика
- Отображение текущего состояния пайплайна
- Информация о сессиях, контексте и сжатии

### PII Маскирование
- Автоматическое маскирование персональных данных
- Поддержка русского и английского языков
- Обнаружение: email, телефоны, паспорта, ИНН, СНИЛС, карты

### Knowledge Bridge
- Поиск в корпоративной базе знаний
- Домены: api, security, db, python, deployment

### Context7 Документация
- Запрос документации для популярных библиотек
- torch, transformers, fastapi, anthropic, openai, redis, postgresql

### Управление сессиями
- Создание новых сессий
- Просмотр списка активных сессий
- Удаление сессий

### Системные логи
- Отображение последних операций
- Уровни: INFO, WARN, ERROR

## Доступ по адресу

http://localhost:7860
