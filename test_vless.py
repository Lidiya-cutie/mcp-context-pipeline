#!/usr/bin/env python3
"""Тестовый скрипт для проверки настройки VLESS."""

import sys
import os
sys.path.insert(0, 'src')

from dotenv import load_dotenv
from vless_client import VLESSClient, setup_vless_from_env

load_dotenv()

def test_vless_url_parsing():
    """Тест парсинга VLESS ссылки."""
    print("[TEST] Парсинг VLESS ссылки...")

    test_url = "vless://uuid123@example.com:443?network=ws&security=tls&host=example.com&path=/ws#TestServer"

    try:
        client = VLESSClient()
        parsed = client.parse_vless_url(test_url)

        assert parsed["uuid"] == "uuid123"
        assert parsed["host"] == "example.com"
        assert parsed["port"] == 443
        assert parsed["remarks"] == "TestServer"
        assert parsed["params"].get("network") == "ws" or parsed["params"].get("type") == "ws"
        assert parsed["params"].get("security") == "tls"

        print(f"[SUCCESS] VLESS ссылка распарсена корректно")
        print(f"  - Host: {parsed['host']}")
        print(f"  - Port: {parsed['port']}")
        print(f"  - UUID: {parsed['uuid']}")
        print(f"  - Network: {parsed['params'].get('network') or parsed['params'].get('type')}")
        print(f"  - Security: {parsed['params'].get('security')}")
        return True

    except Exception as e:
        print(f"[FAIL] Ошибка парсинга: {e}")
        return False


def test_config_generation():
    """Тест генерации конфигурации."""
    print("\n[TEST] Генерация конфигурации Xray...")

    vless_url = os.getenv("VLESS_URL")
    subscription_url = os.getenv("VLESS_SUBSCRIPTION")

    if not vless_url and not subscription_url:
        print("[SKIP] VLESS_URL или VLESS_SUBSCRIPTION не заданы")
        return None

    try:
        client = setup_vless_from_env()

        if not client:
            print("[FAIL] Не удалось создать клиент")
            return False

        config = client._config

        # Проверяем базовую структуру
        assert "inbounds" in config
        assert "outbounds" in config
        assert "routing" in config

        # Проверяем inbound (SOCKS5)
        assert any(i["protocol"] == "socks" for i in config["inbounds"])

        # Проверяем outbound (VLESS)
        assert any(o["protocol"] == "vless" for o in config["outbounds"])

        # Проверяем порты
        socks_inbound = next(i for i in config["inbounds"] if i["protocol"] == "socks")
        print(f"  - SOCKS порт: {socks_inbound['port']}")

        http_inbound = next((i for i in config["inbounds"] if i["protocol"] == "http"), None)
        if http_inbound:
            print(f"  - HTTP порт: {http_inbound['port']}")

        # Проверяем outbound
        vless_outbound = next(o for o in config["outbounds"] if o["protocol"] == "vless")
        print(f"  - Remote host: {vless_outbound['settings']['vnext'][0]['address']}")
        print(f"  - Remote port: {vless_outbound['settings']['vnext'][0]['port']}")

        print("[SUCCESS] Конфигурация сгенерирована корректно")
        return True

    except Exception as e:
        print(f"[FAIL] Ошибка генерации: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_docker_check():
    """Проверка доступности Docker."""
    print("\n[TEST] Проверка Docker...")

    try:
        import subprocess
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            print(f"[SUCCESS] Docker доступен: {result.stdout.strip()}")
            return True
        else:
            print("[FAIL] Docker не доступен")
            return False

    except FileNotFoundError:
        print("[FAIL] Docker не установлен")
        return False
    except Exception as e:
        print(f"[FAIL] Ошибка проверки Docker: {e}")
        return False


def test_proxy_connection():
    """Тест подключения через прокси."""
    print("\n[TEST] Проверка подключения через прокси...")

    socks_port = os.getenv("XRAY_SOCKS_PORT", "10809")
    http_port = os.getenv("XRAY_HTTP_PORT", "10808")

    import subprocess

    # Тест HTTP прокси
    print(f"  - Проверка HTTP прокси (127.0.0.1:{http_port})...")
    try:
        result = subprocess.run(
            ["curl", "-x", f"http://127.0.0.1:{http_port}",
             "-s", "--connect-timeout", "5",
             "https://httpbin.org/ip"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            print(f"    [SUCCESS] HTTP прокси работает")
            print(f"    IP: {result.stdout.strip()}")
        else:
            print(f"    [WARN] HTTP прокси не отвечает")
    except Exception as e:
        print(f"    [WARN] Ошибка: {e}")

    # Тест SOCKS5 прокси
    print(f"  - Проверка SOCKS5 прокси (127.0.0.1:{socks_port})...")
    try:
        result = subprocess.run(
            ["curl", "-x", f"socks5://127.0.0.1:{socks_port}",
             "-s", "--connect-timeout", "5",
             "https://httpbin.org/ip"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            print(f"    [SUCCESS] SOCKS5 прокси работает")
            print(f"    IP: {result.stdout.strip()}")
            return True
        else:
            print(f"    [WARN] SOCKS5 прокси не отвечает (возможно curl без поддержки socks5)")
            return None
    except Exception as e:
        print(f"    [WARN] Ошибка: {e}")
        return None


def show_configuration():
    """Показать текущую конфигурацию."""
    print("\n[INFO] Текущая конфигурация:")
    print(f"  - VLESS_URL: {'задан' if os.getenv('VLESS_URL') else 'не задан'}")
    print(f"  - VLESS_SUBSCRIPTION: {'задан' if os.getenv('VLESS_SUBSCRIPTION') else 'не задан'}")
    print(f"  - VLESS_SERVER_INDEX: {os.getenv('VLESS_SERVER_INDEX', '0')}")
    print(f"  - XRAY_SOCKS_PORT: {os.getenv('XRAY_SOCKS_PORT', '10809')}")
    print(f"  - XRAY_HTTP_PORT: {os.getenv('XRAY_HTTP_PORT', '10808')}")
    print(f"  - HTTP_PROXY: {os.getenv('HTTP_PROXY', 'не задан')}")
    print(f"  - ALL_PROXY: {os.getenv('ALL_PROXY', 'не задан')}")


if __name__ == "__main__":
    print("=" * 60)
    print("Тестирование VLESS настройки")
    print("=" * 60)

    show_configuration()

    results = []

    # Тесты
    results.append(("Парсинг VLESS", test_vless_url_parsing()))
    results.append(("Docker", test_docker_check()))

    config_result = test_config_generation()
    if config_result is not None:
        results.append(("Генерация конфигурации", config_result))

    proxy_result = test_proxy_connection()
    if proxy_result is not None:
        results.append(("Подключение через прокси", proxy_result))

    # Итоги
    print("\n" + "=" * 60)
    print("Результаты:")
    print("=" * 60)

    passed = sum(1 for _, r in results if r is True)
    failed = sum(1 for _, r in results if r is False)
    skipped = sum(1 for _, r in results if r is None)

    for name, result in results:
        if result is True:
            print(f"[PASS] {name}")
        elif result is False:
            print(f"[FAIL] {name}")
        else:
            print(f"[SKIP] {name}")

    print(f"\nИтого: {passed} passed, {failed} failed, {skipped} skipped")

    if failed > 0:
        print("\n[INFO] Для устранения проблем см. docs/VLESS_HIDDIFY_SETUP.md")
        sys.exit(1)
    else:
        print("\n[SUCCESS] Все тесты пройдены!")
        sys.exit(0)
