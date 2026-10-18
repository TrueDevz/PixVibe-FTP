import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

@dataclass
class ActiveTransfer:
    transfer_id: str
    token: str
    client_ip: str
    start_byte: int
    end_byte: int
    current_byte: int
    total_file_size: int
    start_time: float
    last_update_time: float
    bytes_since_last_calc: int = 0
    current_speed_mbps: float = 0.0  # MegaBytes per second

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
    file_path: str
    file_name: str
    file_size: int
    password: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    download_count: int = 0
    total_bytes_sent: int = 0

    @property
    def formatted_size(self) -> str:
        size = float(self.file_size)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"

class TransferManager:
    """Manages active file shares, security tokens, and live bandwidth tracking."""

    def __init__(self):
        self.shares: Dict[str, ShareItem] = {}
        self.active_transfers: Dict[str, ActiveTransfer] = {}

    def add_share(self, file_path: str, password: Optional[str] = None) -> ShareItem:
        path = Path(file_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        token = secrets.token_urlsafe(8)
        file_size = path.stat().st_size
        share = ShareItem(
            token=token,
            file_path=str(path),
            file_name=path.name,
            file_size=file_size,
            password=password.strip() if password and password.strip() else None,
        )
        self.shares[token] = share
        return share

    def remove_share(self, token: str) -> bool:
        if token in self.shares:
            del self.shares[token]
            # Cancel active transfers for this token
            transfers_to_remove = [tid for tid, tr in self.active_transfers.items() if tr.token == token]
            for tid in transfers_to_remove:
                del self.active_transfers[tid]
            return True
        return False

    def get_share(self, token: str) -> Optional[ShareItem]:
        return self.shares.get(token)

    def start_transfer(self, token: str, client_ip: str, start_byte: int, end_byte: int) -> ActiveTransfer:
        share = self.get_share(token)
        if not share:
            raise KeyError(f"Share token not found: {token}")

        transfer_id = secrets.token_hex(6)
        now = time.time()
        transfer = ActiveTransfer(
            transfer_id=transfer_id,
            token=token,
            client_ip=client_ip,
            start_byte=start_byte,
            end_byte=end_byte,
            current_byte=start_byte,
            total_file_size=share.file_size,
            start_time=now,
            last_update_time=now,
        )
        self.active_transfers[transfer_id] = transfer
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
        return {
            "total_active_downloads": len(self.active_transfers),
            "total_speed_mbps": round(total_speed, 2),
            "shares_count": len(self.shares),
            "active_transfers": [
                {
                    "transfer_id": tr.transfer_id,
                    "token": tr.token,
                    "file_name": self.shares[tr.token].file_name if tr.token in self.shares else "Unknown",
                    "client_ip": tr.client_ip,
                    "percentage": tr.percentage,
                    "current_gb": round(tr.current_byte / (1024**3), 2),
                    "total_gb": round(tr.total_file_size / (1024**3), 2),
                    "speed_mbps": round(tr.current_speed_mbps, 2),
                }
                for tr in self.active_transfers.values()
            ],
        }

# Global manager instance
transfer_manager = TransferManager()
