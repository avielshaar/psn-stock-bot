"""Tiny JSON state store (atomic writes)."""
from __future__ import annotations

import json
import os
import tempfile


class StateStore:
    def __init__(self, path: str):
        self.path = path
        self.data = {}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except (OSError, ValueError):
                self.data = {}

    def get(self, asin: str) -> dict:
        return self.data.setdefault(asin, {
            "state": None, "alerted": False, "out_streak": 0,
            "bad_streak": 0, "health_alerted": False, "last_alert": 0,
        })

    def save(self):
        if not self.path:
            return
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
