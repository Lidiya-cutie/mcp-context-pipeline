#!/bin/bash
# ============================================
# run_gradio.sh — Запуск Gradio с автопроверкой окружения
# ============================================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"

# 1. Проверка venv
if [ ! -f "$VENV_PYTHON" ]; then
    echo "⚠️  venv не найден — запускаем настройку..."
    bash "$PROJECT_DIR/setup_gradio_env.sh"
fi

# 2. Загрузка .env
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# 3. Autodetect proxy — если proxy не отвечает, убираем переменные
detect_proxy() {
    local proxy_var="$1"
    local proxy_url="${!proxy_var}"
    
    if [ -z "$proxy_url" ]; then
        return
    fi
    
    # Extract host:port from proxy URL
    local host_port
    host_port=$(echo "$proxy_url" | sed -E 's|.*://([^/]+).*|\1|')
    
    # Try to connect (2s timeout)
    if ! timeout 2 bash -c "echo >/dev/tcp/${host_port%%:*}/${host_port##*:}" 2>/dev/null; then
        echo "⚠️  $proxy_var=$proxy_url — proxy не отвечает, убираем"
        unset "$proxy_var"
    else
        echo "✅ $proxy_var=$proxy_url — proxy доступен"
    fi
}

echo "=== Проверка proxy ==="
detect_proxy HTTP_PROXY
detect_proxy HTTPS_PROXY
detect_proxy ALL_PROXY

# 4. NO_PROXY — всегда добавляем localhost
for key in NO_PROXY no_proxy; do
    existing="${!key:-}"
    for value in localhost 127.0.0.1 ::1; do
        if ! echo "$existing" | grep -q "$value"; then
            export "$key=${existing:+$existing,}$value"
        fi
    done
done
echo "✅ NO_PROXY=$NO_PROXY"

# 5. socksio fallback — если httpx ругается на socksio
if [ -n "$ALL_PROXY" ] || [ -n "$HTTP_PROXY" ]; then
    SOCKSIO_OK=$("$VENV_PYTHON" -c "import socksio; print('ok')" 2>/dev/null || echo "missing")
    if [ "$SOCKSIO_OK" = "missing" ]; then
        echo "⚠️  socksio не установлен — убираем SOCKS proxy из переменных"
        case "$ALL_PROXY" in
            socks5*|socks5h*|socks4*)
                unset ALL_PROXY
                echo "   ALL_PROXY сброшен"
                ;;
        esac
        case "$HTTP_PROXY" in
            socks5*|socks5h*|socks4*)
                unset HTTP_PROXY
                echo "   HTTP_PROXY сброшен"
                ;;
        esac
    fi
fi

# 6. Запуск
echo ""
echo "=== Запуск Gradio UI ==="
echo "Python: $VENV_PYTHON"
echo "Адрес: http://0.0.0.0:7860"
echo ""

cd "$PROJECT_DIR"
exec "$VENV_PYTHON" gradio_ui.py
