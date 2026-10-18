import os
import socket
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"

# Network & Server Settings
DEFAULT_PORT = 8000
CHUNK_SIZE = 1024 * 1024  # 1 MB chunk buffer for high-throughput 30GB streaming

def get_local_ip() -> str:
    """Detect the machine's primary local LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Using Google Public DNS to find default route interface without sending data
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def find_available_port(start_port: int = DEFAULT_PORT) -> int:
    """Find an available port starting from start_port."""
    port = start_port
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
            port += 1
    return start_port
