#!/bin/bash
# Скрипт для запуска Hiddify Next в Docker

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source .env 2>/dev/null || true

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Проверка подписки
if [ -z "$VLESS_SUBSCRIPTION" ]; then
    echo -e "${RED}[ERROR] VLESS_SUBSCRIPTION не задан${NC}"
    exit 1
fi

echo "[INFO] Запуск Hiddify Next Docker..."
echo "[INFO] Подписка: ${VLESS_SUBSCRIPTION:0:30}..."

# Запускаем Hiddify Next
docker run -d \
    --name hiddify-next \
    --restart unless-stopped \
    -p 1080:1080 \
    -p 1081:1081 \
    -e SUBSCRIPTION_URL="$VLESS_SUBSCRIPTION" \
    ghcr.io/hiddify/hiddify-next:latest

if [ $? -eq 0 ]; then
    echo -e "${GREEN}[SUCCESS] Hiddify Next запущен${NC}"
    echo -e "[INFO] SOCKS5 прокси: ${YELLOW}socks5://127.0.0.1:1080${NC}"
    echo -e "[INFO] HTTP прокси:  ${YELLOW}http://127.0.0.1:1081${NC}"
    echo ""
    echo "Добавьте в .env:"
    echo "  ALL_PROXY=socks5://127.0.0.1:1080"
else
    echo -e "${RED}[ERROR] Ошибка запуска Hiddify Next${NC}"
    exit 1
fi
