from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SENSITIVE_KEYS = {"api_key", "authorization", "token", "secret", "password"}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in SENSITIVE_KEYS else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


class TraceLogger:
    def __init__(self, path: Path):
        self.path = path

    def emit(self, run_id: str, event: str, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "event": event,
            "data": _sanitize(data),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
