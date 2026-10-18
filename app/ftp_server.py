import os
import threading
from typing import Optional
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
from app.config import BASE_DIR

class LocalFTPServer:
    """Manages an optional background pyftpdlib FTP server on port 2121."""

    def __init__(self, port: int = 2121, shared_dir: Optional[str] = None):
        self.port = port
        self.shared_dir = shared_dir or str(BASE_DIR)
        self.server: Optional[FTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.is_running = False

    def start(self, username: str = "user", password: str = "12345", shared_dir: Optional[str] = None):
        if self.is_running:
            return

        if shared_dir:
            self.shared_dir = shared_dir

        if not os.path.exists(self.shared_dir):
            os.makedirs(self.shared_dir, exist_ok=True)

        authorizer = DummyAuthorizer()
        # Full read-write permissions: 'elradfmwMT' or read-only 'elr'
        authorizer.add_user(username, password, self.shared_dir, perm="elradfmwMT")
        authorizer.add_anonymous(self.shared_dir, perm="elr")

        handler = FTPHandler
        handler.authorizer = authorizer
        handler.banner = "LocalFTP High-Speed File Server Ready."

        self.server = FTPServer(("0.0.0.0", self.port), handler)
        self.is_running = True

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self.server.serve_forever()
        except Exception:
            pass
        finally:
            self.is_running = False

    def stop(self):
        if self.server:
            try:
                self.server.close_all()
            except Exception:
                pass
            self.server = None
        self.is_running = False

    def get_info(self) -> dict:
        return {
            "is_running": self.is_running,
            "port": self.port,
            "shared_dir": self.shared_dir,
        }

ftp_service = LocalFTPServer()
