#!/bin/bash
# ============================================
# run_nicegui.sh — Запуск NiceGUI-консоли (mcp_ui.py) с автопроверкой окружения
# ============================================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "venv не найден: $VENV_PYTHON"
    echo "Создать: python3 -m venv venv && venv/bin/pip install -r requirements.txt nicegui"
    exit 1
fi

if ! "$VENV_PYTHON" -c "import nicegui" 2>/dev/null; then
    echo "NiceGUI не установлен в venv. Установка: $VENV_PYTHON -m pip install nicegui"
    exit 1
fi

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

detect_proxy() {
    local proxy_var="$1"
    local proxy_url="${!proxy_var}"
    [ -z "$proxy_url" ] && return
    local host_port
    host_port=$(echo "$proxy_url" | sed -E 's|.*://([^/]+).*|\1|')
    if ! timeout 2 bash -c "echo >/dev/tcp/${host_port%%:*}/${host_port##*:}" 2>/dev/null; then
        echo "$proxy_var=$proxy_url — proxy не отвечает, убираем"
        unset "$proxy_var"
    else
        echo "$proxy_var=$proxy_url — proxy доступен"
    fi
}

echo "=== Проверка proxy ==="
detect_proxy HTTP_PROXY
detect_proxy HTTPS_PROXY
detect_proxy ALL_PROXY

for key in NO_PROXY no_proxy; do
    existing="${!key:-}"
    for value in localhost 127.0.0.1 ::1; do
        if ! echo "$existing" | grep -q "$value"; then
            export "$key=${existing:+$existing,}$value"
        fi
    done
done
echo "NO_PROXY=$NO_PROXY"

if [ -n "${ALL_PROXY:-}" ] || [ -n "${HTTP_PROXY:-}" ]; then
    SOCKSIO_OK=$("$VENV_PYTHON" -c "import socksio; print('ok')" 2>/dev/null || echo "missing")
    if [ "$SOCKSIO_OK" = "missing" ]; then
        case "${ALL_PROXY:-}" in socks5*|socks5h*|socks4*) unset ALL_PROXY ;; esac
        case "${HTTP_PROXY:-}" in socks5*|socks5h*|socks4*) unset HTTP_PROXY ;; esac
    fi
fi

echo ""
echo "=== Запуск NiceGUI Console (mcp_ui.py) ==="
echo "Python: $VENV_PYTHON"
echo "Адрес:  http://0.0.0.0:7860"
echo ""

cd "$PROJECT_DIR"
exec "$VENV_PYTHON" mcp_ui.py
