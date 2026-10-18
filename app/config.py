import json
import os
import socket
from pathlib import Path
from typing import Optional

import sys

if getattr(sys, "frozen", False):
    # PyInstaller bundle directory for internal assets (templates, static)
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    APP_DIR = BUNDLE_DIR / "app"
    STATIC_DIR = APP_DIR / "static"
    TEMPLATES_DIR = APP_DIR / "templates"
    
    # Persistent writable directory for settings and history
    EXE_DIR = Path(sys.executable).parent
    try:
        # Check if EXE_DIR is writable (e.g. portable mode)
        test_file = EXE_DIR / ".write_test"
        test_file.touch()
        test_file.unlink()
        BASE_DIR = EXE_DIR
    except Exception:
        # Fall back to %APPDATA%\PixVibeFTP if installed in Program Files
        BASE_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "PixVibeFTP"
        BASE_DIR.mkdir(parents=True, exist_ok=True)
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    APP_DIR = Path(__file__).resolve().parent
    STATIC_DIR = APP_DIR / "static"
    TEMPLATES_DIR = APP_DIR / "templates"

CONFIG_FILE = BASE_DIR / "settings.json"
BIN_DIR = BASE_DIR / "bin"
BIN_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_PORT = 8000
CHUNK_SIZE = 1024 * 1024  # 1 MB chunk buffer

DEFAULT_SETTINGS = {
    "tunnel_provider": "ngrok",  # "ngrok", "cloudflare_quick", or "cloudflare_token"
    "ngrok_domain": "unmobbed-corrina-mustily.ngrok-free.dev",
    "ngrok_authtoken": "",
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
