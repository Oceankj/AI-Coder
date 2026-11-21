"""Small shared JSONL writer for HTTP and model-call metadata."""
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)


class JsonlRecords:
    def __init__(self, path: Path):
        self.path = path
        self._lock = Lock()

    def _append(self, fields: dict) -> None:
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), **fields}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def write(self, fields: dict) -> None:
        try:
            await asyncio.to_thread(self._append, fields)
        except OSError:
            logger.error("Could not write request metadata; check the configured record path permissions.")
