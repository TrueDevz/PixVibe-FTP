import mimetypes
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

def detect_file_category(filename: str, mime: Optional[str]) -> str:
    ext = Path(filename).suffix.lower()
    if ext in [".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".flv", ".wmv"]:
        return "video"
    if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico"]:
        return "image"
    if ext in [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma"]:
        return "audio"
    if ext == ".pdf":
        return "pdf"
    if ext in [".txt", ".md", ".json", ".csv", ".log", ".xml", ".html", ".css", ".js", ".py", ".c", ".cpp", ".sql"]:
        return "document"
    if mime:
        if mime.startswith("video/"):
            return "video"
        if mime.startswith("image/"):
            return "image"
        if mime.startswith("audio/"):
            return "audio"
    return "other"

def get_content_type(file_name: str) -> str:
    mime, _ = mimetypes.guess_type(file_name)
    if mime:
        return mime
    ext = Path(file_name).suffix.lower()
    custom_types = {
        ".mkv": "video/x-matroska",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".webp": "image/webp",
        ".flac": "audio/flac",
        ".pdf": "application/pdf",
        ".json": "application/json",
        ".md": "text/markdown",
        ".txt": "text/plain; charset=utf-8",
    }
    return custom_types.get(ext, "application/octet-stream")

def format_bytes(bytes_count: int) -> str:
    size = float(bytes_count)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

@dataclass
class FileEntry:
    file_id: str
    file_path: str
    file_name: str
    file_size: int
    mime_type: str
    category: str

    @property
    def formatted_size(self) -> str:
        return format_bytes(self.file_size)

@dataclass
class ActiveTransfer:
    transfer_id: str
    token: str
    file_id: str
    client_ip: str
    start_byte: int
    end_byte: int
    current_byte: int
    total_file_size: int
    start_time: float
    last_update_time: float
    bytes_since_last_calc: int = 0
    current_speed_mbps: float = 0.0

    def update_progress(self, bytes_transferred: int):
        self.current_byte += bytes_transferred
        self.bytes_since_last_calc += bytes_transferred
        now = time.time()
        elapsed = now - self.last_update_time
        if elapsed >= 1.0:
            self.current_speed_mbps = (self.bytes_since_last_calc / (1024 * 1024)) / elapsed
            self.bytes_since_last_calc = 0
            self.last_update_time = now

    @property
    def percentage(self) -> float:
        if self.total_file_size <= 0:
            return 0.0
        return min(100.0, round((self.current_byte / self.total_file_size) * 100, 2))

@dataclass
class ShareItem:
    token: str
    title: str
    files: List[FileEntry]
    password: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    download_count: int = 0
    total_bytes_sent: int = 0

    @property
    def total_size(self) -> int:
        return sum(f.file_size for f in self.files)

    @property
    def formatted_size(self) -> str:
        return format_bytes(self.total_size)

    def get_file(self, file_id: str) -> Optional[FileEntry]:
        for f in self.files:
            if f.file_id == file_id:
                return f
        return None

    def get_first_file(self) -> Optional[FileEntry]:
        return self.files[0] if self.files else None

class TransferManager:
    """Manages active file shares (multi-file collections), security tokens, and live bandwidth tracking."""

    def __init__(self):
        self.shares: Dict[str, ShareItem] = {}
        self.active_transfers: Dict[str, ActiveTransfer] = {}

    def add_share(
        self,
        file_paths: List[str],
        password: Optional[str] = None,
        title: Optional[str] = None
    ) -> ShareItem:
        if not file_paths:
            raise ValueError("No files provided for share")

        valid_files: List[FileEntry] = []
        for fp in file_paths:
            path = Path(fp).resolve()
            if path.is_file():
                size = path.stat().st_size
                mime = get_content_type(path.name)
                cat = detect_file_category(path.name, mime)
                file_entry = FileEntry(
                    file_id=secrets.token_hex(4),
                    file_path=str(path),
                    file_name=path.name,
                    file_size=size,
                    mime_type=mime,
                    category=cat,
                )
                valid_files.append(file_entry)

        if not valid_files:
            raise FileNotFoundError("None of the specified files could be found on disk")

        token = secrets.token_urlsafe(8)
        share_title = title.strip() if title and title.strip() else (
            valid_files[0].file_name if len(valid_files) == 1 else f"Bundle ({len(valid_files)} files)"
        )

        share = ShareItem(
            token=token,
            title=share_title,
            files=valid_files,
            password=password.strip() if password and password.strip() else None,
        )
        self.shares[token] = share
        return share

    def remove_share(self, token: str) -> bool:
        if token in self.shares:
            del self.shares[token]
            transfers_to_remove = [tid for tid, tr in self.active_transfers.items() if tr.token == token]
            for tid in transfers_to_remove:
                del self.active_transfers[tid]
            return True
        return False

    def get_share(self, token: str) -> Optional[ShareItem]:
        return self.shares.get(token)

    def start_transfer(
        self,
        token: str,
        file_id: str,
        client_ip: str,
        start_byte: int,
        end_byte: int,
        total_size: int
    ) -> ActiveTransfer:
        transfer_id = secrets.token_hex(6)
        now = time.time()
        transfer = ActiveTransfer(
            transfer_id=transfer_id,
            token=token,
            file_id=file_id,
            client_ip=client_ip,
            start_byte=start_byte,
            end_byte=end_byte,
            current_byte=start_byte,
            total_file_size=total_size,
            start_time=now,
            last_update_time=now,
        )
        self.active_transfers[transfer_id] = transfer
        share = self.get_share(token)
        if share:
            share.download_count += 1
        return transfer

    def update_transfer(self, transfer_id: str, bytes_sent: int):
        transfer = self.active_transfers.get(transfer_id)
        if transfer:
            transfer.update_progress(bytes_sent)
            share = self.shares.get(transfer.token)
            if share:
                share.total_bytes_sent += bytes_sent

    def end_transfer(self, transfer_id: str):
        if transfer_id in self.active_transfers:
            del self.active_transfers[transfer_id]

    def get_stats(self) -> dict:
        total_speed = sum(tr.current_speed_mbps for tr in self.active_transfers.values())
        active_list = []
        for tr in self.active_transfers.values():
            share = self.shares.get(tr.token)
            file_name = "Unknown"
            if share:
                target_file = share.get_file(tr.file_id)
                if target_file:
                    file_name = target_file.file_name
                elif share.files:
                    file_name = share.files[0].file_name

            active_list.append({
                "transfer_id": tr.transfer_id,
                "token": tr.token,
                "file_name": file_name,
                "client_ip": tr.client_ip,
                "percentage": tr.percentage,
                "current_gb": round(tr.current_byte / (1024**3), 2),
                "total_gb": round(tr.total_file_size / (1024**3), 2),
                "speed_mbps": round(tr.current_speed_mbps, 2),
            })

        return {
            "total_active_downloads": len(self.active_transfers),
            "total_speed_mbps": round(total_speed, 2),
            "shares_count": len(self.shares),
            "active_transfers": active_list,
        }

transfer_manager = TransferManager()
