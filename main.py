import copy
import io
import multiprocessing
import os
import sys
import threading
import time
import webbrowser
import uvicorn
import uvicorn.config

# In PyInstaller windowed mode (console=False), standard streams are None
class NullWriter:
    def write(self, s):
        pass
    def flush(self):
        pass
    def isatty(self):
        return False

if sys.stdout is None:
    sys.stdout = NullWriter()
if sys.stderr is None:
    sys.stderr = NullWriter()
if sys.stdin is None:
    sys.stdin = io.StringIO()

from app.config import find_available_port, DEFAULT_PORT, load_settings
from app.server import app, tunnel_manager

def open_browser(port: int):
    time.sleep(1.2)
    url = f"http://127.0.0.1:{port}"
    webbrowser.open(url)

def get_uvicorn_log_config():
    """Create a safe logging config that won't fail when no console is attached."""
    cfg = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    if "formatters" in cfg:
        if "default" in cfg["formatters"]:
            cfg["formatters"]["default"]["use_colors"] = False
        if "access" in cfg["formatters"]:
            cfg["formatters"]["access"]["use_colors"] = False
    return cfg

def main():
    port = find_available_port(DEFAULT_PORT)
    tunnel_manager.port = port

    # Auto start tunnel in background
    def _start_tunnel():
        settings = load_settings()
        provider = settings.get("tunnel_provider", "ngrok")
        domain = settings.get("ngrok_domain", "").strip()

        if provider == "ngrok" and not domain:
            return

        tunnel_manager.start()

    threading.Thread(target=_start_tunnel, daemon=True).start()

    # Auto open dashboard in default browser
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    log_cfg = get_uvicorn_log_config()

    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_config=log_cfg, log_level="warning")
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        tunnel_manager.stop()

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
