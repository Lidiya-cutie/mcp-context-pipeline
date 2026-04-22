@echo off
REM ====================================
REM MCP Context Pipeline - Windows Runner
REM ====================================
REM This script launches the pipeline on Windows
REM while using Linux containers via Docker

echo ====================================
echo MCP Context Pipeline - Starting...
echo ====================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

REM Check if Docker is running
docker ps >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running
    echo Please start Docker Desktop
    pause
    exit /b 1
)

echo [INFO] Starting Docker services (Redis, PostgreSQL)...
docker-compose up -d

echo.
echo [INFO] Waiting for services to be ready...
timeout /t 3 /nobreak >nul

echo.
echo ====================================
echo Select action:
echo ====================================
echo 1. Start interactive session
echo 2. Run basic functionality test
echo 3. Run stress test (100k tokens)
echo 4. Run checkpoint recovery test
echo 5. Run all tests
echo 6. Run Context7 integration test
echo 7. Run Context7 quick test
echo 8. Stop Docker services
echo ====================================

set /p choice="Enter your choice (1-8): "

echo.

if "%choice%"=="1" (
    echo [INFO] Starting interactive session...
    python src/host_orchestrator.py
) else if "%choice%"=="2" (
    echo [INFO] Running basic functionality test...
    python src/test_pipeline.py 1
) else if "%choice%"=="3" (
    echo [INFO] Running stress test...
    python src/test_pipeline.py 2
) else if "%choice%"=="4" (
    echo [INFO] Running checkpoint recovery test...
    python src/test_pipeline.py 3
) else if "%choice%"=="5" (
    echo [INFO] Running all tests...
    python src/test_pipeline.py 4
) else if "%choice%"=="6" (
    echo [INFO] Running Context7 integration test...
    python tests/test_context7_integration.py
) else if "%choice%"=="7" (
    echo [INFO] Running Context7 quick test...
    python src/test_context7_quick.py
) else if "%choice%"=="8" (
    echo [INFO] Stopping Docker services...
    docker-compose down
    echo [INFO] Services stopped
) else (
    echo [ERROR] Invalid choice
)

echo.
echo Press any key to exit...
pause >nul
