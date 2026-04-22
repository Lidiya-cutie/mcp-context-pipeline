"""Модуль для запуска Xray клиента с VLESS конфигурацией.

Позволяет использовать VLESS подписки (Hiddify, V2Ray) для обхода ограничений.
"""

import os
import json
import yaml
import subprocess
import time
import re
from typing import Optional, Dict, Any
from pathlib import Path


class VLESSClient:
    """Клиент для управления Xray с VLESS конфигурацией."""

    def __init__(self, config_path: Optional[str] = None, listen_port: int = 10809):
        """
        Инициализация VLESS клиента.

        Args:
            config_path: Путь к файлу конфигурации Xray (json/yaml)
            listen_port: Порт для SOCKS5 прокси
        """
        self.listen_port = listen_port
        self.http_port = listen_port + 1
        self.config_path = config_path
        self.container_name = "mcp-xray-vless"
        self._config: Optional[Dict[str, Any]] = None

    @staticmethod
    def parse_vless_url(vless_url: str) -> Dict[str, Any]:
        """
        Парсинг VLESS ссылки.

        Args:
            vless_url: VLESS ссылка (vless://...)

        Returns:
            Словарь с параметрами подключения
        """
        if not vless_url.startswith("vless://"):
            raise ValueError("Не VLESS ссылка")

        try:
            import base64
            from urllib.parse import unquote, parse_qs, urlparse

            # vless://uuid@host:port?params#remarks
            decoded = unquote(vless_url)

            # Извлекаем UUID и хост
            match = re.match(r"vless://([^@]+)@([^:]+):(\d+)(.*)", decoded)
            if not match:
                raise ValueError("Неверный формат VLESS ссылки")

            uuid, host, port, rest = match.groups()

            # Парсим параметры
            params = {}
            if "?" in rest:
                # Извлекаем часть после ?
                query_part = rest.split("?")[1]
                # Удаляем remarks если есть
                if "#" in query_part:
                    query_part = query_part.split("#")[0]

                for key, value in parse_qs(query_part).items():
                    params[key] = value[0] if value else ""

            # Извлекаем remarks (название)
            remarks = ""
            if "#" in rest:
                remarks = rest.split("#", 1)[1]

            return {
                "uuid": uuid,
                "host": host,
                "port": int(port),
                "remarks": remarks or "VLESS",
                "params": params
            }

        except Exception as e:
            raise ValueError(f"Ошибка парсинга VLESS: {e}")

    @staticmethod
    def parse_subscription(subscription_url: str) -> list:
        """
        Парсинг подписки (base64 encoded список ссылок).

        Args:
            subscription_url: URL подписки

        Returns:
            Список VLESS ссылок
        """
        import base64
        import requests

        try:
            response = requests.get(subscription_url, timeout=10)
            response.raise_for_status()

            # Декодируем base64
            decoded = base64.b64decode(response.text.strip()).decode("utf-8")

            # Разбиваем на строки
            links = [line.strip() for line in decoded.splitlines() if line.strip()]

            return links

        except Exception as e:
            raise ValueError(f"Ошибка получения подписки: {e}")

    def generate_xray_config(
        self,
        vless_url: Optional[str] = None,
        subscription_url: Optional[str] = None,
        server_index: int = 0
    ) -> Dict[str, Any]:
        """
        Генерация конфигурации Xray.

        Args:
            vless_url: Прямая VLESS ссылка
            subscription_url: URL подписки (будет использована если vless_url не указан)
            server_index: Индекс сервера в подписке (по умолчанию 0)

        Returns:
            Конфигурация Xray в формате dict
        """
        if vless_url:
            vless_links = [vless_url]
        elif subscription_url:
            vless_links = self.parse_subscription(subscription_url)
            if not vless_links:
                raise ValueError("Подписка не содержит ссылок")
            vless_url = vless_links[server_index]
        elif self.config_path:
            # Читаем существующую конфигурацию
            config_file = Path(self.config_path)
            if config_file.suffix in [".yaml", ".yml"]:
                with open(config_file) as f:
                    return yaml.safe_load(f)
            else:
                with open(config_file) as f:
                    return json.load(f)
        else:
            raise ValueError("Не указана VLESS ссылка или подписка")

        # Парсим VLESS
        vless_config = self.parse_vless_url(vless_url)

        # Генерируем конфигурацию Xray
        config = {
            "log": {
                "loglevel": "warning"
            },
            "inbounds": [
                {
                    "port": self.listen_port,
                    "protocol": "socks",
                    "settings": {
                        "auth": "noauth",
                        "udp": True
                    },
                    "tag": "socks-in"
                },
                {
                    "port": self.http_port,
                    "protocol": "http",
                    "settings": {},
                    "tag": "http-in"
                }
            ],
            "outbounds": [
                {
                    "protocol": "vless",
                    "settings": {
                        "vnext": [
                            {
                                "address": vless_config["host"],
                                "port": vless_config["port"],
                                "users": [
                                    {
                                        "id": vless_config["uuid"],
                                        "encryption": "none"
                                    }
                                ]
                            }
                        ]
                    },
                    "streamSettings": {
                        "network": vless_config["params"].get("network") or vless_config["params"].get("type", "tcp"),
                        "security": vless_config["params"].get("security", "none")
                    },
                    "tag": "proxy-out"
                },
                {
                    "protocol": "freedom",
                    "settings": {},
                    "tag": "direct"
                }
            ],
            "routing": {
                "domainStrategy": "IPIfNonMatch",
                "rules": [
                    {
                        "type": "field",
                        "ip": ["geoip:private"],
                        "outboundTag": "direct"
                    },
                    {
                        "type": "field",
                        "domain": ["geosite:category-ads-all"],
                        "outboundTag": "block"
                    },
                    {
                        "type": "field",
                        "network": "tcp,udp",
                        "outboundTag": "proxy-out"
                    }
                ]
            }
        }

        # Добавляем TLS если указан
        if vless_config["params"].get("security") == "tls":
            config["outbounds"][0]["streamSettings"]["tlsSettings"] = {
                "serverName": vless_config["params"].get("sni", vless_config["host"]),
                "allowInsecure": vless_config["params"].get("allowInsecure", "false") == "true"
            }

        # Добавляем Reality если указан
        if vless_config["params"].get("security") == "reality":
            sni = vless_config["params"].get("sni", "www.microsoft.com")
            reality_settings = {
                "serverName": sni.split(":")[0],
                "shortId": vless_config["params"].get("sid", ""),
                "publicKey": vless_config["params"].get("pbk", ""),
                "fingerprint": vless_config["params"].get("fp", "chrome"),
                "spiderX": vless_config["params"].get("spx", "/")
            }
            config["outbounds"][0]["streamSettings"]["realitySettings"] = reality_settings
            # Добавляем flow если указан
            flow = vless_config["params"].get("flow")
            if flow:
                config["outbounds"][0]["settings"]["vnext"][0]["users"][0]["flow"] = flow

        # Добавляем WebSocket если указан
        network_type = vless_config["params"].get("network") or vless_config["params"].get("type")
        if network_type == "ws":
            ws_path = vless_config["params"].get("path", "/")
            ws_host = vless_config["params"].get("host", vless_config["host"])

            config["outbounds"][0]["streamSettings"]["wsSettings"] = {
                "path": ws_path,
                "headers": {
                    "Host": ws_host
                }
            }

        self._config = config
        return config

    def save_config(self, output_path: str) -> str:
        """
        Сохранение конфигурации в файл.

        Args:
            output_path: Путь для сохранения

        Returns:
            Путь к сохраненному файлу
        """
        if not self._config:
            raise ValueError("Конфигурация не сгенерирована. Сначала вызовите generate_xray_config().")

        output_file = Path(output_path)
        with open(output_file, "w") as f:
            json.dump(self._config, f, indent=2)

        return str(output_file)

    def start_docker(
        self,
        image: str = "ghcr.io/xtls/xray-core:latest",
        auto_remove: bool = False
    ) -> bool:
        """
        Запуск Xray в Docker контейнере.

        Args:
            image: Docker образ Xray
            auto_remove: Удалять контейнер при остановке

        Returns:
            True если контейнер запущен успешно
        """
        if not self._config:
            raise ValueError("Конфигурация не сгенерирована")

        # Сохраняем конфигурацию
        config_dir = Path("/tmp/mcp-xray-config")
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "config.json"

        with open(config_file, "w") as f:
            json.dump(self._config, f, indent=2)

        # Останавливаем старый контейнер если есть
        try:
            subprocess.run(
                ["docker", "rm", "-f", self.container_name],
                capture_output=True
            )
        except:
            pass

        # Запускаем новый контейнер
        cmd = [
            "docker", "run", "-d",
            "--name", self.container_name,
            "-p", f"{self.listen_port}:10809",
            "-p", f"{self.http_port}:10808",
            "-v", f"{config_dir}:/etc/xray",
            image
        ]

        if auto_remove:
            cmd.insert(4, "--rm")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            container_id = result.stdout.strip()

            # Ждем запуска
            time.sleep(2)

            # Проверяем статус
            status = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Status}}", self.container_name],
                capture_output=True,
                text=True
            )

            if "running" in status.stdout:
                print(f"[SUCCESS] Xray контейнер запущен: {container_id}")
                print(f"[INFO] SOCKS5 прокси: 127.0.0.1:{self.listen_port}")
                print(f"[INFO] HTTP прокси: 127.0.0.1:{self.http_port}")
                return True
            else:
                print(f"[ERROR] Контейнер не запущен. Статус: {status.stdout}")
                return False

        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Ошибка запуска Docker: {e}")
            print(f"[STDERR] {e.stderr}")
            return False

    def stop(self) -> bool:
        """
        Остановка Xray контейнера.

        Returns:
            True если контейнер остановлен
        """
        try:
            result = subprocess.run(
                ["docker", "rm", "-f", self.container_name],
                capture_output=True,
                text=True
            )

            if "removed" in result.stdout or "already removed" in result.stderr:
                print(f"[INFO] Xray контейнер остановлен")
                return True
            return False

        except Exception as e:
            print(f"[ERROR] Ошибка остановки: {e}")
            return False

    def status(self) -> Dict[str, Any]:
        """
        Проверка статуса контейнера.

        Returns:
            Словарь со статусом
        """
        try:
            result = subprocess.run(
                ["docker", "inspect", self.container_name],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                return {"running": False, "error": "Контейнер не найден"}

            data = json.loads(result.stdout)
            state = data[0]["State"]

            return {
                "running": state["Running"],
                "status": state["Status"],
                "started_at": state.get("StartedAt"),
                "socks_port": self.listen_port,
                "http_port": self.http_port
            }

        except Exception as e:
            return {"running": False, "error": str(e)}

    def get_proxy_url(self, protocol: str = "socks5") -> str:
        """
        Получить URL прокси для использования в приложении.

        Args:
            protocol: Тип прокси (socks5, http)

        Returns:
            URL прокси
        """
        port = self.listen_port if protocol == "socks5" else self.http_port
        return f"{protocol}://127.0.0.1:{port}"


def setup_vless_from_env() -> Optional[VLESSClient]:
    """
    Настройка VLESS клиента из переменных окружения.

    Переменные окружения:
    - VLESS_URL: Прямая VLESS ссылка
    - VLESS_SUBSCRIPTION: URL подписки
    - VLESS_SERVER_INDEX: Индекс сервера в подписке (по умолчанию 0)
    - XRAY_LISTEN_PORT: Порт для SOCKS5 (по умолчанию 10809)

    Returns:
        Настроенный экземпляр VLESSClient или None
    """
    vless_url = os.getenv("VLESS_URL")
    subscription_url = os.getenv("VLESS_SUBSCRIPTION")
    listen_port = int(
        os.getenv("XRAY_LISTEN_PORT")
        or os.getenv("XRAY_SOCKS_PORT")
        or "10809"
    )
    http_port = int(os.getenv("XRAY_HTTP_PORT", str(listen_port + 1)))

    if not vless_url and not subscription_url:
        print("[WARN] VLESS_URL или VLESS_SUBSCRIPTION не указаны")
        return None

    client = VLESSClient(listen_port=listen_port)
    client.http_port = http_port

    try:
        server_index = int(os.getenv("VLESS_SERVER_INDEX", "0"))
        client.generate_xray_config(
            vless_url=vless_url,
            subscription_url=subscription_url,
            server_index=server_index
        )
        return client

    except Exception as e:
        print(f"[ERROR] Ошибка генерации конфигурации: {e}")
        return None
