import atexit
import io
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, Optional

from app.config import BASE_DIR, BIN_DIR, load_settings, save_settings

NGROK_ZIP_URL = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"
CLOUDFLARED_EXE_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

def find_tunnel_binary(tool_name: str) -> Optional[str]:
    """Find the path to the requested tunnel binary (ngrok or cloudflared)."""
    exe_name = f"{tool_name}.exe" if os.name == "nt" else tool_name

    # 1. Check in BIN_DIR
    p = BIN_DIR / exe_name
    if p.is_file():
        return str(p)

    # 2. Check next to app / executable
    p2 = BASE_DIR / exe_name
    if p2.is_file():
        return str(p2)

    # 3. Check system PATH
    found = shutil.which(tool_name) or shutil.which(exe_name)
    if found:
        return found

    # 4. Windows specific common install locations
    if os.name == "nt":
        candidates = [
            Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps")) / exe_name,
            Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\ngrok")) / exe_name,
            Path(r"C:\Program Files (x86)\cloudflared") / exe_name,
            Path(r"C:\Program Files\cloudflared") / exe_name,
        ]
        for c in candidates:
            if c.is_file():
                return str(c)

    return None

def download_tunnel_tool(tool_name: str) -> dict:
    """Download and extract ngrok or cloudflared into BIN_DIR."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    target_exe = BIN_DIR / f"{tool_name}.exe"

    headers = {"User-Agent": "PixVibeFTP/1.0"}

    try:
        if tool_name == "ngrok":
            req = urllib.request.Request(NGROK_ZIP_URL, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for member in zf.namelist():
                    if member.endswith("ngrok.exe") or member == "ngrok.exe":
                        with zf.open(member) as src, open(target_exe, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        break
            if not target_exe.is_file():
                return {"success": False, "error": "ngrok.exe not found inside downloaded archive"}
            return {"success": True, "path": str(target_exe)}

        elif tool_name == "cloudflared":
            req = urllib.request.Request(CLOUDFLARED_EXE_URL, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                with open(target_exe, "wb") as dst:
                    shutil.copyfileobj(resp, dst)
            if not target_exe.is_file():
                return {"success": False, "error": "Failed to save cloudflared.exe"}
            return {"success": True, "path": str(target_exe)}

        else:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        return {"success": False, "error": str(e)}

def get_tools_status() -> Dict[str, dict]:
    """Check if tunnel tools are installed and return their status."""
    return {
        "ngrok": {
            "installed": find_tunnel_binary("ngrok") is not None,
            "path": find_tunnel_binary("ngrok"),
        },
        "cloudflared": {
            "installed": find_tunnel_binary("cloudflared") is not None,
            "path": find_tunnel_binary("cloudflared"),
        },
    }

def kill_orphan_ngrok():
    """Kill any lingering orphan ngrok processes on Windows."""
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "ngrok.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception:
            pass

class TunnelManager:
    """Manages ngrok and cloudflared tunnels with automatic binary discovery and process cleanup."""

    def __init__(self, port: int):
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.public_url: Optional[str] = None
        self.status = "stopped"  # stopped, connecting, connected, error, not_configured
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
        expected_url = None

        if self.provider == "ngrok":
            binary = find_tunnel_binary("ngrok")
            if not binary:
                self.status = "error"
                self.error_message = "ngrok.exe not found. Click 'Auto-Download Ngrok' in Tunnel Settings."
                return False

            domain = settings.get("ngrok_domain", "").strip()
            if not domain:
                self.status = "not_configured"
                self.error_message = "Please configure your Ngrok domain in Tunnel Settings."
                return False

            authtoken = settings.get("ngrok_authtoken", "").strip()
            if authtoken:
                try:
                    subprocess.run(
                        [binary, "config", "add-authtoken", authtoken],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                except Exception:
                    pass

            kill_orphan_ngrok()
            time.sleep(0.5)

            clean_domain = domain.replace("https://", "").replace("http://", "").strip().rstrip("/")
            cmd = [binary, "http", str(self.port), "--url", clean_domain, "--pooling-enabled", "--log=stdout"]
            expected_url = f"https://{clean_domain}"

        elif self.provider == "cloudflare_token":
            binary = find_tunnel_binary("cloudflared")
            if not binary:
                self.status = "error"
                self.error_message = "cloudflared.exe not found. Click 'Auto-Download Cloudflared' in Tunnel Settings."
                return False

            token = settings.get("cf_tunnel_token", "").strip()
            domain = settings.get("cf_custom_domain", "").strip()
            if not token:
                self.status = "not_configured"
                self.error_message = "Cloudflare Tunnel Token is required."
                return False

            clean_domain = domain.replace("https://", "").replace("http://", "").strip().rstrip("/")
            cmd = [binary, "tunnel", "run", "--token", token]
            expected_url = f"https://{clean_domain}" if clean_domain else None

        else:
            # cloudflare_quick
            self.provider = "cloudflare_quick"
            binary = find_tunnel_binary("cloudflared")
            if not binary:
                self.status = "error"
                self.error_message = "cloudflared.exe not found. Click 'Auto-Download Cloudflared' in Tunnel Settings."
                return False

            cmd = [binary, "tunnel", "--url", f"http://127.0.0.1:{self.port}"]
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
            executable = cmd[0] if cmd else "tunnel"
            self.status = "error"
            self.error_message = f"Executable '{executable}' could not be started."
            return False
        except Exception as e:
            self.status = "error"
            self.error_message = str(e)
            return False

        self._reader_thread = threading.Thread(target=self._monitor_output, daemon=True)
        self._reader_thread.start()

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

                # Ngrok
                if self.provider == "ngrok":
                    match = ngrok_pattern.search(line)
                    if match:
                        self.public_url = match.group(1)
                        self.status = "connected"
                    if "lvl=eror" in line or "ERR_NGROK" in line or "failed to start tunnel" in line:
                        self.error_message = line.strip()
                        self.status = "error"

                # Cloudflare Quick
                elif self.provider == "cloudflare_quick":
                    match = cf_pattern.search(line)
                    if match and not self.public_url:
                        self.public_url = match.group(0)
                        self.status = "connected"

                # Cloudflare Token
                elif self.provider == "cloudflare_token":
                    if "Registered tunnel connection" in line:
                        self.status = "connected"
        except Exception as e:
            self.error_message = str(e)
        finally:
            if self.process and self.process.poll() is not None and not self._stop_event.is_set():
                if self.status != "error":
                    self.status = "stopped"

    def stop(self):
        self._stop_event.set()
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

        if self.provider == "ngrok":
            kill_orphan_ngrok()

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
            "ngrok_authtoken": settings.get("ngrok_authtoken", ""),
            "cf_custom_domain": settings.get("cf_custom_domain", ""),
            "tools": get_tools_status(),
        }
