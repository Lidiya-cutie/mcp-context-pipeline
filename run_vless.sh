#!/bin/bash
# Скрипт для управления Xray VLESS клиентом

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source .env 2>/dev/null || true

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Проверка зависимостей
check_dependencies() {
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}[ERROR] Docker не установлен${NC}"
        exit 1
    fi
}

# Генерация конфигурации
generate_config() {
    echo "[INFO] Генерация конфигурации Xray..."

    python3 - << 'PYTHON_SCRIPT'
import os
import sys
sys.path.insert(0, 'src')

from dotenv import load_dotenv
from vless_client import setup_vless_from_env

load_dotenv('.env')

client = setup_vless_from_env()
if not client:
    print("[ERROR] Не удалось создать VLESS клиент")
    sys.exit(1)

config = client.save_config("xray-config/config.json")
print(f"[SUCCESS] Конфигурация сохранена: {config}")
PYTHON_SCRIPT

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}[SUCCESS] Конфигурация сгенерирована${NC}"
        return 0
    else
        echo -e "${RED}[ERROR] Ошибка генерации конфигурации${NC}"
        return 1
    fi
}

# Запуск Xray
start() {
    check_dependencies
    echo "[INFO] Запуск Xray VLESS клиента..."

    # Создаем директорию для конфигурации
    mkdir -p xray-config

    # Генерируем конфигурацию
    if ! generate_config; then
        exit 1
    fi

    # Запускаем через docker compose
    docker compose -f docker-compose-xray.yml up -d

    if [ $? -eq 0 ]; then
        SOCKS_PORT=${XRAY_SOCKS_PORT:-10809}
        HTTP_PORT=${XRAY_HTTP_PORT:-10808}
        echo -e "${GREEN}[SUCCESS] Xray запущен${NC}"
        echo -e "[INFO] SOCKS5 прокси: ${YELLOW}socks5://127.0.0.1:$SOCKS_PORT${NC}"
        echo -e "[INFO] HTTP прокси:  ${YELLOW}http://127.0.0.1:$HTTP_PORT${NC}"
        echo ""
        echo "Используйте эти URL в .env:"
        echo "  ALL_PROXY=socks5://127.0.0.1:$SOCKS_PORT"
        echo "  HTTP_PROXY=http://127.0.0.1:$HTTP_PORT"
    fi
}

# Остановка Xray
stop() {
    echo "[INFO] Остановка Xray..."
    docker compose -f docker-compose-xray.yml down
    echo -e "${GREEN}[SUCCESS] Xray остановлен${NC}"
}

# Перезапуск Xray
restart() {
    stop
    sleep 1
    start
}

# Статус
status() {
    echo "[INFO] Статус Xray контейнера:"
    docker compose -f docker-compose-xray.yml ps
}

# Логи
logs() {
    docker compose -f docker-compose-xray.yml logs -f --tail=100
}

# Тест подключения
test_connection() {
    echo "[INFO] Тест подключения через прокси..."

    SOCKS_PORT=${XRAY_SOCKS_PORT:-10809}
    HTTP_PORT=${XRAY_HTTP_PORT:-10808}

    # Тест HTTP прокси
    echo "[TEST] HTTP прокси..."
    curl -x "http://127.0.0.1:$HTTP_PORT" -s --connect-timeout 10 https://httpbin.org/ip

    if [ $? -eq 0 ]; then
        echo -e "\n${GREEN}[SUCCESS] HTTP прокси работает${NC}"
    else
        echo -e "\n${YELLOW}[WARN] HTTP прокси не отвечает${NC}"
    fi

    # Тест SOCKS5 прокси (если установлен curl с поддержкой socks5)
    echo "[TEST] SOCKS5 прокси..."
    curl -x "socks5://127.0.0.1:$SOCKS_PORT" -s --connect-timeout 10 https://httpbin.org/ip

    if [ $? -eq 0 ]; then
        echo -e "\n${GREEN}[SUCCESS] SOCKS5 прокси работает${NC}"
    else
        echo -e "\n${YELLOW}[WARN] SOCKS5 прокси не отвечает (требуется curl с поддержкой socks5)${NC}"
    fi
}

# Показать помощь
show_help() {
    cat << EOF
Управление Xray VLESS клиентом

Использование: $0 [команда]

Команды:
    start       Запустить Xray клиент
    stop        Остановить Xray клиент
    restart     Перезапустить Xray клиент
    status      Показать статус контейнера
    logs        Показать логи контейнера
    test        Тестировать подключение через прокси
    config      Пересоздать конфигурацию

Переменные окружения (.env):
    VLESS_URL              Прямая VLESS ссылка
    VLESS_SUBSCRIPTION     URL подписки Hiddify/V2Ray
    VLESS_SERVER_INDEX     Индекс сервера в подписке (по умолчанию 0)
    XRAY_SOCKS_PORT        Порт SOCKS5 (по умолчанию 10809)
    XRAY_HTTP_PORT         Порт HTTP (по умолчанию 10808)

Примеры:
    # Использование с подпиской Hiddify
    VLESS_SUBSCRIPTION="https://hiddify.com/..." ./run_vless.sh start

    # Использование с прямой VLESS ссылкой
    VLESS_URL="vless://uuid@host:port?..." ./run_vless.sh start

    # Выбор другого сервера из подписки
    VLESS_SERVER_INDEX=2 ./run_vless.sh start
EOF
}

# Обработка аргументов
case "${1:-}" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    test)
        test_connection
        ;;
    config)
        generate_config
        ;;
    *)
        show_help
        ;;
esac
