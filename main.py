import sys
import threading
import time
import webbrowser
import uvicorn
from app.config import find_available_port, DEFAULT_PORT, load_settings
from app.server import app, tunnel_manager

def open_browser(port: int):
    time.sleep(1.2)
    url = f"http://127.0.0.1:{port}"
    print(f"\n[LocalFTP] Opening Web Dashboard: {url}")
    webbrowser.open(url)

def main():
    print("=" * 60)
    print("  🚀 LocalFTP - High-Speed 30GB+ Direct File Transmitter")
    print("=" * 60)

    port = find_available_port(DEFAULT_PORT)
    tunnel_manager.port = port

    # Auto start tunnel in background
    def _start_tunnel():
        settings = load_settings()
        provider = settings.get("tunnel_provider", "ngrok")
        domain = settings.get("ngrok_domain", "").strip()

        if provider == "ngrok" and not domain:
            print("[LocalFTP] ℹ️ Ngrok domain not set yet. Please enter it in the dashboard (Tunnel Settings).")
            return

        print(f"[LocalFTP] Starting Tunnel Provider: {provider.upper()}...")
        tunnel_manager.start()
        if tunnel_manager.public_url:
            print(f"[LocalFTP] 🌐 Static Public Internet URL Ready: {tunnel_manager.public_url}")

    threading.Thread(target=_start_tunnel, daemon=True).start()

    # Auto open dashboard in default browser
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
    except (KeyboardInterrupt, SystemExit):
        print("\n[LocalFTP] Shutting down...")
    finally:
        tunnel_manager.stop()

if __name__ == "__main__":
    main()
