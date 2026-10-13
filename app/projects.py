"""Saved projects / previous edits, persisted server-side as JSON.

Every saved edit keeps its source (link or upload), trim, title, caption,
caption style, quality and last generated download — so closing the tab
never loses work. The frontend also mirrors this into localStorage.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

_lock = threading.Lock()


class ProjectStore:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def _load(self) -> list[dict]:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save(self, items: list[dict]):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=1)
        os.replace(tmp, self.path)

    def list(self) -> list[dict]:
        with _lock:
            return sorted(self._load(), key=lambda p: -p.get("updated", 0))

    def upsert(self, project: dict) -> dict:
        with _lock:
            items = self._load()
            pid = project.get("id") or uuid.uuid4().hex[:12]
            now = time.time()
            old = next((p for p in items if p["id"] == pid), None)
            record = {**project, "id": pid, "updated": now,
                      "created": (old or {}).get("created", now)}
            items = [p for p in items if p["id"] != pid] + [record]
            self._save(items[-200:])          # keep the newest 200 projects
            return record

    def delete(self, pid: str) -> bool:
        with _lock:
            items = self._load()
            kept = [p for p in items if p["id"] != pid]
            self._save(kept)
            return len(kept) != len(items)
