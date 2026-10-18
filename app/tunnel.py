import atexit
import os
import re
import subprocess
import threading
import time
from typing import Optional
from app.config import load_settings, save_settings

class CloudflareTunnelManager:
    """Manages the lifecycle of quick tunnels and persistent named tunnels."""

    def __init__(self, port: int):
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.public_url: Optional[str] = None
        self.status = "stopped"  # stopped, connecting, connected, error
        self.error_message: Optional[str] = None
        self.tunnel_type = "quick"  # "quick" or "token"
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._auto_reconnect = True
        atexit.register(self.stop)

    def start(self, tunnel_type: Optional[str] = None, token: Optional[str] = None, custom_domain: Optional[str] = None) -> bool:
        if self.process and self.process.poll() is None:
            return True

        settings = load_settings()
        self.tunnel_type = tunnel_type or settings.get("tunnel_type", "quick")
        token = token if token is not None else settings.get("tunnel_token", "")
        custom_domain = custom_domain if custom_domain is not None else settings.get("custom_domain", "")

        self.status = "connecting"
        self.error_message = None
        self.public_url = None
        self._stop_event.clear()

        if self.tunnel_type == "token" and token.strip():
            # Persistent Named Tunnel
            cmd = ["cloudflared", "tunnel", "run", "--token", token.strip()]
            domain = custom_domain.strip()
            if domain:
                if not domain.startswith("http://") and not domain.startswith("https://"):
                    domain = f"https://{domain}"
                self.public_url = domain
        else:
            # Quick Anonymous Tunnel
            self.tunnel_type = "quick"
            cmd = ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{self.port}"]

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except FileNotFoundError:
            self.status = "error"
            self.error_message = "cloudflared executable not found in PATH."
            return False
        except Exception as e:
            self.status = "error"
            self.error_message = str(e)
            return False

        self._reader_thread = threading.Thread(target=self._monitor_output, daemon=True)
        self._reader_thread.start()

        # For token tunnel with known domain, mark connected quickly
        if self.tunnel_type == "token" and self.public_url:
            time.sleep(1.0)
            self.status = "connected"
            return True

        # Wait up to 15s for quick tunnel URL
        start_time = time.time()
        while time.time() - start_time < 15:
            if self.public_url:
                self.status = "connected"
                return True
            if self.process.poll() is not None:
                self.status = "error"
                if not self.error_message:
                    self.error_message = f"cloudflared exited with code {self.process.returncode}"
                return False
            time.sleep(0.3)

        if not self.public_url:
            self.status = "error"
            self.error_message = "Timed out waiting for Cloudflare Tunnel URL."
            return False

        return True

    def _monitor_output(self):
        url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
        if not self.process or not self.process.stdout:
            return

        try:
            for line in iter(self.process.stdout.readline, ""):
                if self._stop_event.is_set():
                    break
                if not line:
                    break

                # Match Quick Tunnel URL
                if self.tunnel_type == "quick":
                    match = url_pattern.search(line)
                    if match and not self.public_url:
                        self.public_url = match.group(0)
                        self.status = "connected"

                # If token tunnel is active
                if "Registered tunnel connection" in line:
                    self.status = "connected"
        except Exception as e:
            self.error_message = str(e)
        finally:
            if self.process and self.process.poll() is not None and not self._stop_event.is_set():
                self.status = "stopped"

    def stop(self):
        self._stop_event.set()
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        self.public_url = None
        self.status = "stopped"

    def get_info(self) -> dict:
        settings = load_settings()
        return {
            "status": self.status,
            "public_url": self.public_url,
            "error_message": self.error_message,
            "port": self.port,
            "tunnel_type": self.tunnel_type,
            "custom_domain": settings.get("custom_domain", ""),
            "has_token": bool(settings.get("tunnel_token", "")),
        }
