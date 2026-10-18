import json
import os
import socket
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"
CONFIG_FILE = BASE_DIR / "settings.json"

DEFAULT_PORT = 8000
CHUNK_SIZE = 1024 * 1024  # 1 MB chunk buffer

DEFAULT_SETTINGS = {
    "tunnel_provider": "ngrok",  # "ngrok", "cloudflare_quick", or "cloudflare_token"
    "ngrok_domain": "unmobbed-corrina-mustily.ngrok-free.dev",
    "cf_tunnel_token": "",
    "cf_custom_domain": "",
}

def load_settings() -> dict:
    if CONFIG_FILE.is_file():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged = dict(DEFAULT_SETTINGS)
                merged.update(data)
                return merged
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)

def save_settings(settings: dict):
    merged = dict(DEFAULT_SETTINGS)
    merged.update(settings)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)

def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def find_available_port(start_port: int = DEFAULT_PORT) -> int:
    port = start_port
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
            port += 1
    return start_port
