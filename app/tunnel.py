import atexit
import os
import re
import subprocess
import threading
import time
from typing import Optional

class CloudflareTunnelManager:
    """Manages the lifecycle of a cloudflared quick tunnel."""

    def __init__(self, port: int):
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.public_url: Optional[str] = None
        self.status = "stopped"  # stopped, connecting, connected, error
        self.error_message: Optional[str] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        atexit.register(self.stop)

    def start(self) -> bool:
        if self.process and self.process.poll() is None:
            return True  # Already running

        self.status = "connecting"
        self.error_message = None
        self.public_url = None
        self._stop_event.clear()

        # Locate cloudflared binary
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

        # Wait up to 15 seconds for URL
        start_time = time.time()
        while time.time() - start_time < 15:
            if self.public_url:
                self.status = "connected"
                return True
            if self.process.poll() is not None:
                self.status = "error"
                if not self.error_message:
                    self.error_message = f"cloudflared exited unexpectedly with code {self.process.returncode}"
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
                
                # Check for tunnel URL
                match = url_pattern.search(line)
                if match and not self.public_url:
                    self.public_url = match.group(0)
                    self.status = "connected"

                # Check for errors
                if "ERR" in line or "error" in line.lower():
                    if "Cannot determine default configuration path" not in line:
                        # Log but don't immediately fail unless critical
                        pass
        except Exception as e:
            self.error_message = str(e)
        finally:
            if self.process and self.process.poll() is not None and self.status != "stopped":
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
        return {
            "status": self.status,
            "public_url": self.public_url,
            "error_message": self.error_message,
            "port": self.port,
        }
