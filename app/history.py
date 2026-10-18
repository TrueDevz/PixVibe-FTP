import datetime
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional
from app.config import BASE_DIR

HISTORY_FILE = BASE_DIR / "history.json"

class HistoryManager:
    """Manages persistent link sharing history grouped by date."""

    def __init__(self):
        self.file_path = HISTORY_FILE
        self._ensure_file()

    def _ensure_file(self):
        if not self.file_path.is_file():
            self._save([])

    def _load(self) -> List[dict]:
        if self.file_path.is_file():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save(self, items: List[dict]):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)

    def record_share(
        self,
        token: str,
        title: str,
        files_info: List[dict],
        total_size_str: str,
        total_bytes: int,
        password_protected: bool,
        public_url: Optional[str],
        local_url: str,
        short_url: Optional[str] = None
    ):
        items = self._load()
        now = time.time()
        dt = datetime.datetime.fromtimestamp(now)
        date_key = dt.strftime("%Y-%m-%d")
        date_display = dt.strftime("%B %d, %Y")
        time_display = dt.strftime("%I:%M %p")

        entry = {
            "id": token,
            "token": token,
            "title": title,
            "created_at": now,
            "date_key": date_key,
            "date_display": date_display,
            "time_display": time_display,
            "files_count": len(files_info),
            "files": files_info,
            "total_size": total_size_str,
            "total_bytes": total_bytes,
            "password_protected": password_protected,
            "public_url": public_url,
            "short_url": short_url or public_url,
            "local_url": local_url,
            "status": "active"
        }

        # Keep newest at front, avoid exact duplicate token
        items = [it for it in items if it.get("token") != token]
        items.insert(0, entry)
        self._save(items)

    def mark_stopped(self, token: str):
        items = self._load()
        updated = False
        for it in items:
            if it.get("token") == token:
                it["status"] = "stopped"
                updated = True
        if updated:
            self._save(items)

    def update_urls(self, token: str, public_url: Optional[str], short_url: Optional[str] = None):
        items = self._load()
        updated = False
        for it in items:
            if it.get("token") == token:
                if public_url:
                    it["public_url"] = public_url
                if short_url:
                    it["short_url"] = short_url
                updated = True
        if updated:
            self._save(items)

    def delete_entry(self, entry_id: str) -> bool:
        items = self._load()
        initial_len = len(items)
        items = [it for it in items if it.get("id") != entry_id and it.get("token") != entry_id]
        if len(items) != initial_len:
            self._save(items)
            return True
        return False

    def clear_all(self):
        self._save([])

    def get_grouped_history(self, active_tokens: Optional[set] = None) -> List[dict]:
        """
        Returns history grouped by date:
        [
          {
            "date": "Today - October 19, 2026",
            "date_key": "2026-10-19",
            "items": [...]
          },
          ...
        ]
        """
        items = self._load()
        today_key = datetime.datetime.now().strftime("%Y-%m-%d")
        yesterday_key = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

        # Update dynamic active status if active_tokens provided
        if active_tokens is not None:
            for it in items:
                it["status"] = "active" if it.get("token") in active_tokens else "stopped"

        grouped: Dict[str, dict] = {}
        for it in items:
            dk = it.get("date_key", "Earlier")
            if dk not in grouped:
                display = it.get("date_display", dk)
                if dk == today_key:
                    title = f"Today — {display}"
                elif dk == yesterday_key:
                    title = f"Yesterday — {display}"
                else:
                    title = display

                grouped[dk] = {
                    "date": title,
                    "date_key": dk,
                    "items": []
                }
            grouped[dk]["items"].append(it)

        # Sort dates descending
        sorted_groups = sorted(grouped.values(), key=lambda g: g["date_key"], reverse=True)
        return sorted_groups

history_manager = HistoryManager()
