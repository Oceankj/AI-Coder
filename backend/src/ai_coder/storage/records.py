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

    async def read_recent(self, limit: int = 1000) -> list[dict]:
        return await asyncio.to_thread(self._read_recent, limit)

    def _read_recent(self, limit: int) -> list[dict]:
        # Bound both I/O and memory for the recent-records UI. Concurrent writes
        # can leave a partial line; skip it rather than failing the entire view.
        max_bytes = 1024 * 1024
        try:
            with self.path.open("rb") as stream:
                stream.seek(0, 2)
                offset = max(0, stream.tell() - max_bytes)
                stream.seek(offset)
                lines = stream.read(max_bytes).splitlines()
                if offset:
                    lines = lines[1:]  # The first line may start mid-record.
        except FileNotFoundError:
            return []
        records = []
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(record, dict):
                records.append(record)
            if len(records) >= limit:
                break
        return records
