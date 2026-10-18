import atexit
import os
import re
import subprocess
import threading
import time
from typing import Optional
from app.config import load_settings, save_settings

class TunnelManager:
    """Manages ngrok and cloudflared tunnels."""

    def __init__(self, port: int):
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.public_url: Optional[str] = None
        self.status = "stopped"  # stopped, connecting, connected, error
        self.error_message: Optional[str] = None
        self.provider = "ngrok"  # "ngrok", "cloudflare_quick", "cloudflare_token"
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        atexit.register(self.stop)

    def start(self, provider: Optional[str] = None) -> bool:
        if self.process and self.process.poll() is None:
            return True

        settings = load_settings()
        self.provider = provider or settings.get("tunnel_provider", "ngrok")
        self.status = "connecting"
        self.error_message = None
        self.public_url = None
        self._stop_event.clear()

        cmd = []
        if self.provider == "ngrok":
            domain = settings.get("ngrok_domain", "").strip()
            if not domain:
                domain = "unmobbed-corrina-mustily.ngrok-free.dev"
            cmd = ["ngrok", "http", str(self.port), "--url", domain, "--log=stdout"]
            expected_url = domain if domain.startswith("http") else f"https://{domain}"

        elif self.provider == "cloudflare_token":
            token = settings.get("cf_tunnel_token", "").strip()
            domain = settings.get("cf_custom_domain", "").strip()
            if not token:
                self.status = "error"
                self.error_message = "Cloudflare Tunnel Token is required."
                return False
            cmd = ["cloudflared", "tunnel", "run", "--token", token]
            expected_url = domain if domain.startswith("http") else f"https://{domain}" if domain else None

        else:
            # cloudflare_quick
            self.provider = "cloudflare_quick"
            cmd = ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{self.port}"]
            expected_url = None

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
            executable = cmd[0]
            self.status = "error"
            self.error_message = f"Executable '{executable}' not found in PATH."
            return False
        except Exception as e:
            self.status = "error"
            self.error_message = str(e)
            return False

        self._reader_thread = threading.Thread(target=self._monitor_output, daemon=True)
        self._reader_thread.start()

        # If we have a predetermined static URL (like ngrok or cf_token), wait for healthy startup
        start_time = time.time()
        timeout = 15.0

        while time.time() - start_time < timeout:
            if self.public_url:
                self.status = "connected"
                return True

            if self.process.poll() is not None:
                self.status = "error"
                if not self.error_message:
                    self.error_message = f"Tunnel exited with code {self.process.returncode}"
                return False
            time.sleep(0.3)

        # Fallback if expected_url is known and process is still running healthy
        if expected_url and self.process and self.process.poll() is None:
            self.public_url = expected_url
            self.status = "connected"
            return True

        if not self.public_url:
            self.status = "error"
            self.error_message = "Timed out waiting for tunnel URL."
            return False

        return True

    def _monitor_output(self):
        cf_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
        ngrok_pattern = re.compile(r"url=(https://[a-zA-Z0-9.-]+)")

        if not self.process or not self.process.stdout:
            return

        try:
            for line in iter(self.process.stdout.readline, ""):
                if self._stop_event.is_set():
                    break
                if not line:
                    break

                # Ngrok output matching
                if self.provider == "ngrok":
                    match = ngrok_pattern.search(line)
                    if match:
                        self.public_url = match.group(1)
                        self.status = "connected"
                    if "lvl=eror" in line or "ERR_NGROK" in line:
                        self.error_message = line.strip()

                # Cloudflare Quick Tunnel matching
                elif self.provider == "cloudflare_quick":
                    match = cf_pattern.search(line)
                    if match and not self.public_url:
                        self.public_url = match.group(0)
                        self.status = "connected"

                # Cloudflare Token matching
                elif self.provider == "cloudflare_token":
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
            "provider": self.provider,
            "ngrok_domain": settings.get("ngrok_domain", ""),
            "cf_custom_domain": settings.get("cf_custom_domain", ""),
        }
