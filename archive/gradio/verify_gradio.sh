#!/bin/bash
# ============================================
# verify_gradio.sh — Проверка готовности Gradio к запуску
# ============================================

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"

PASS=0
FAIL=0

echo "=== Проверка Gradio MCP Pipeline ==="
echo ""

# 1. Python
if [ -f "$VENV_PYTHON" ]; then
    VER=$("$VENV_PYTHON" --version 2>&1)
    echo "✅ Python (venv): $VER"
    PASS=$((PASS+1))
else
    echo "❌ Python venv не найден: $VENV_PYTHON"
    echo "   Запустите: bash $PROJECT_DIR/setup_gradio_env.sh"
    FAIL=$((FAIL+1))
fi

# 2. Gradio
GRADIO=$("$VENV_PYTHON" -c "import gradio; print(gradio.__version__)" 2>/dev/null || echo "")
if [ -n "$GRADIO" ]; then
    echo "✅ Gradio: $GRADIO"
    PASS=$((PASS+1))
else
    echo "❌ Gradio не установлен"
    FAIL=$((FAIL+1))
fi

# 3. Ключевые модули
for mod in host_orchestrator pii_guard context7_client; do
    STATUS=$("$VENV_PYTHON" -c "import sys; sys.path.insert(0,'$PROJECT_DIR/src'); import $mod; print('ok')" 2>/dev/null || echo "missing")
    if [ "$STATUS" = "ok" ]; then
        echo "✅ $mod"
        PASS=$((PASS+1))
    else
        echo "⚠️  $mod — не импортируется"
        FAIL=$((FAIL+1))
    fi
done

# 4. MCP-серверы
MCP_COUNT=$(ls -d "$PROJECT_DIR/src/mcp_servers"/*/ 2>/dev/null | wc -l)
if [ "$MCP_COUNT" -ge 27 ]; then
    echo "✅ MCP-серверы: $MCP_COUNT"
    PASS=$((PASS+1))
else
    echo "⚠️  MCP-серверы: $MCP_COUNT (ожидается 27+)"
    FAIL=$((FAIL+1))
fi

# 5. .env
if [ -f "$PROJECT_DIR/.env" ]; then
    echo "✅ .env"
    PASS=$((PASS+1))
else
    echo "⚠️  .env не найден"
    FAIL=$((FAIL+1))
fi

# 6. Docker
if command -v docker &>/dev/null; then
    if docker info &>/dev/null; then
        echo "✅ Docker доступен"
        PASS=$((PASS+1))
    else
        echo "⚠️  Docker установлен, но не запущен"
        FAIL=$((FAIL+1))
    fi
else
    echo "⚠️  Docker не установлен (опционально)"
fi

# 7. Proxy
for var in HTTP_PROXY HTTPS_PROXY ALL_PROXY; do
    if [ -n "${!var}" ]; then
        echo "ℹ️  $var=${!var}"
    fi
done

# 8. Smoke test — import gradio_ui
IMPORT=$("$VENV_PYTHON" -c "
import sys
sys.path.insert(0, '$PROJECT_DIR/src')
import importlib.util
spec = importlib.util.spec_from_file_location('gradio_ui', '$PROJECT_DIR/gradio_ui.py')
mod = importlib.util.module_from_spec(spec)
print('import ok')
" 2>&1)
if echo "$IMPORT" | grep -q "import ok"; then
    echo "✅ gradio_ui.py импортируется"
    PASS=$((PASS+1))
else
    echo "⚠️  gradio_ui.py — ошибка импорта:"
    echo "$IMPORT" | tail -3 | sed 's/^/   /'
    FAIL=$((FAIL+1))
fi

echo ""
echo "=== Результат: $PASS пройдено, $FAIL проблем ==="
