#!/bin/bash

# ====================================
# MCP Context Pipeline - Linux/Unix Runner
# ====================================
# This script launches the pipeline on Linux/Mac
# while using Linux containers via Docker

set -e

echo "===================================="
echo "MCP Context Pipeline - Starting..."
echo "===================================="
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 is not installed"
    echo "Please install Python 3.10+ from your package manager"
    exit 1
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "[ERROR] Docker is not installed"
    echo "Please install Docker from https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is available
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null 2>&1; then
    echo "[ERROR] Docker Compose is not installed"
    echo "Please install Docker Compose"
    exit 1
fi

# Use docker-compose or docker compose based on what's available
if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    COMPOSE_CMD="docker compose"
fi

echo "[INFO] Starting Docker services (Redis, PostgreSQL)..."
$COMPOSE_CMD up -d

echo ""
echo "[INFO] Waiting for services to be ready..."
sleep 3

echo ""
echo "===================================="
echo "Select action:"
echo "===================================="
echo "1. Start interactive session"
echo "2. Run basic functionality test"
echo "3. Run stress test (100k tokens)"
echo "4. Run checkpoint recovery test"
echo "5. Run all tests"
echo "6. Run Context7 integration test"
echo "7. Run Context7 quick test"
echo "8. Stop Docker services"
echo "9. View logs"
echo "===================================="
read -p "Enter your choice (1-9): " choice

echo ""

case $choice in
    1)
        echo "[INFO] Starting interactive session..."
        python3 src/host_orchestrator.py
        ;;
    2)
        echo "[INFO] Running basic functionality test..."
        python3 src/test_pipeline.py 1
        ;;
    3)
        echo "[INFO] Running stress test..."
        python3 src/test_pipeline.py 2
        ;;
    4)
        echo "[INFO] Running checkpoint recovery test..."
        python3 src/test_pipeline.py 3
        ;;
    5)
        echo "[INFO] Running all tests..."
        python3 src/test_pipeline.py 4
        ;;
    6)
        echo "[INFO] Running Context7 integration test..."
        python3 tests/test_context7_integration.py
        ;;
    7)
        echo "[INFO] Running Context7 quick test..."
        python3 src/test_context7_quick.py
        ;;
    8)
        echo "[INFO] Stop Docker services..."
        $COMPOSE_CMD down
        echo "[INFO] Services stopped"
        ;;
    9)
        echo "[INFO] Viewing Docker logs..."
        $COMPOSE_CMD logs -f
        ;;
    *)
        echo "[ERROR] Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "Done!"
