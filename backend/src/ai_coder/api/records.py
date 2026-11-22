# Author: Ching Kao
# Student ID: 85768427
"""Read-only projection of shared AI-call records for the UI."""
from datetime import timezone

from fastapi import APIRouter, Query, Request, Response
from pydantic import ValidationError

from ai_coder.api.errors import ApiError
from ai_coder.api.schemas import AICallRecord
from ai_coder.storage.records import JsonlRecords
from ai_coder.models import AICallEvent

router = APIRouter(prefix="/api/llm")


@router.get("/records", response_model=list[AICallRecord])
async def list_records(request: Request, response: Response, limit: int = Query(default=100, ge=1, le=200)):
    response.headers["Cache-Control"] = "no-store"
    try:
        events = await JsonlRecords(request.app.state.settings.llm_record_path).read_recent()
    except OSError:
        raise ApiError(503, "RECORDS_UNAVAILABLE", "Could not read AI call records. Check the backend record path permissions.") from None
    calls: dict[str, dict] = {}
    allowed = {"callId", "requestId", "caller", "role", "model", "resolvedModel",
               "status", "providerStatus", "durationMs", "providerMs", "inputTokens",
               "outputTokens", "totalTokens", "errorCode", "event"}
    valid_events = {event.value for event in AICallEvent}
    # Reader returns newest first; merge in write order so completion wins.
    for event in reversed(events):
        call_id = event.get("callId")
        if not isinstance(call_id, str) or not call_id or event.get("event") not in valid_events:
            continue
        call = calls.setdefault(call_id, {})
        call.update({key: value for key, value in event.items() if key in allowed})
        if event["event"] == AICallEvent.STARTED:
            call["startedAt"] = event.get("timestamp")
        else:
            call["finishedAt"] = event.get("timestamp")
    records = []
    for call in calls.values():
        try:
            record = AICallRecord.model_validate(call)
        except ValidationError:
            continue
        if record.started_at is None and record.finished_at is None:
            continue
        records.append(record)
    def timestamp(record):
        moment = record.started_at or record.finished_at
        return moment.replace(tzinfo=timezone.utc).timestamp() if moment.tzinfo is None else moment.timestamp()
    return sorted(records, key=timestamp, reverse=True)[:limit]
