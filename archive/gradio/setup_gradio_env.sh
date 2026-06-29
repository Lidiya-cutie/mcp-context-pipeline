#!/bin/bash
# ============================================
# setup_gradio_env.sh — Настройка окружения для Gradio MCP Pipeline
# Запуск: bash /mldata/mcp_context_pipeline/setup_gradio_env.sh
# ============================================

set -e

PROJECT_DIR="/mldata/mcp_context_pipeline"
VENV_DIR="$PROJECT_DIR/venv"
REQUIREMENTS="$PROJECT_DIR/requirements.txt"

echo "=== MCP Context Pipeline — Настройка окружения ==="
echo "Project: $PROJECT_DIR"
echo ""

# 1. Проверка Python
if ! command -v python3 &>/dev/null; then
    echo "❌ Python3 не найден. Установите: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✅ Python $PY_VERSION найден"

# 2. Пересоздание venv если сломан
NEED_RECREATE=false
if [ ! -f "$VENV_DIR/bin/python3" ]; then
    NEED_RECREATE=true
    echo "⚠️  venv отсутствует или сломан — пересоздаём"
else
    echo "✅ venv существует"
fi

if [ "$NEED_RECREATE" = true ]; then
    rm -rf "$VENV_DIR"
    python3 -m venv "$VENV_DIR"
    echo "✅ venv создан: $VENV_DIR"
fi

# 3. Установка зависимостей
PIP="$VENV_DIR/bin/pip3"

if [ -f "$REQUIREMENTS" ]; then
    echo "📦 Установка зависимостей из requirements.txt..."
    "$PIP" install --upgrade pip --quiet 2>/dev/null
    "$PIP" install -r "$REQUIREMENTS" --quiet 2>/dev/null || {
        echo "⚠️  Не все пакеты установились. Попробуем по одному..."
        while IFS= read -r line; do
            # Skip comments and empty lines
            [[ "$line" =~ ^#.*$ ]] && continue
            [[ -z "$line" ]] && continue
            echo "  Устанавливаем: $line"
            "$PIP" install "$line" --quiet 2>/dev/null || echo "  ⚠️  Не удалось: $line"
        done < "$REQUIREMENTS"
    }
    echo "✅ Зависимости установлены"
else
    echo "⚠️  requirements.txt не найден — устанавливаем минимальный набор"
    "$PIP" install gradio httpx --quiet 2>/dev/null
fi

# 4. Установка presidio (PII masking)
echo "📦 Проверка Microsoft Presidio..."
if ! "$VENV_DIR/bin/python3" -c "import presidio_analyzer" 2>/dev/null; then
    "$PIP" install presidio-analyzer presidio-anonymizer --quiet 2>/dev/null || {
        echo "⚠️  Presidio не установлен — PII masking будет недоступен"
    }
fi

# 5. Проверка socksio
echo "📦 Проверка socksio..."
if ! "$VENV_DIR/bin/python3" -c "import socksio" 2>/dev/null; then
    echo "⚠️  socksio не установлен — SOCKS proxy будет недоступен"
    echo "   Установка: $PIP install socksio"
    "$PIP" install socksio --quiet 2>/dev/null && echo "✅ socksio установлен" || echo "⚠️  socksio не установлен (не критично)"
fi

# 6. Проверка Gradio версии
GRADIO_VER=$("$VENV_DIR/bin/python3" -c "import gradio; print(gradio.__version__)" 2>/dev/null || echo "NOT INSTALLED")
echo "📦 Gradio: $GRADIO_VER"

# 7. Настройка .env если нет
if [ ! -f "$PROJECT_DIR/.env" ]; then
    if [ -f "$PROJECT_DIR/.env.example" ]; then
        cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
        echo "✅ .env создан из .env.example — отредактируйте proxy-настройки"
    else
        echo "⚠️  .env не найден — переменные окружения нужно задать вручную"
    fi
else
    echo "✅ .env существует"
fi

echo ""
echo "=== Готово! ==="
echo "Запуск Gradio: bash $PROJECT_DIR/run_gradio.sh"
echo "Или: $VENV_DIR/bin/python3 $PROJECT_DIR/gradio_ui.py"
echo ""
echo "Для проверки: bash $PROJECT_DIR/verify_gradio.sh"
