# Author: Ching Kao
# Student ID: 85768427
"""Read-only UI projection of gateway lifecycle records."""
import json


def write_events(settings, events):
    settings.llm_record_path.parent.mkdir(parents=True, exist_ok=True)
    settings.llm_record_path.write_text("\n".join(json.dumps(event) for event in events) + '\n{"torn":', encoding="utf-8")


def test_records_merge_sort_and_allowlist(client, settings):
    common = {"callId": "first", "requestId": "request-1", "caller": "chat", "model": "alias"}
    write_events(settings, [
        {**common, "event": "started", "timestamp": "2026-11-20T10:00:00Z", "apiKey": "never-return", "messages": ["private"]},
        {**common, "event": "completed", "timestamp": "2026-11-20T10:00:30Z", "durationMs": 30000, "providerMs": 29000, "inputTokens": 79, "outputTokens": 42, "totalTokens": 158, "resolvedModel": "actual-model", "status": 200},
        {"callId": "second", "caller": "agent", "role": "coder", "event": "started", "timestamp": "2026-11-20T11:00:00Z"},
        {"callId": "invalid", "caller": "unknown", "event": "completed", "timestamp": "bad"},
        ["not an event"],
    ])
    response = client.get('/api/llm/records')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    records = response.json()
    assert [record['callId'] for record in records] == ['second', 'first']
    assert records[0]['event'] == 'started'
    assert records[0]['durationMs'] is None
    assert records[1]['event'] == 'completed'
    assert records[1]['startedAt'] is not None and records[1]['finishedAt'] is not None
    assert records[1]['totalTokens'] == 158
    assert records[1]['resolvedModel'] == 'actual-model'
    assert 'never-return' not in response.text and 'private' not in response.text
    assert len(client.get('/api/llm/records?limit=1').json()) == 1


def test_missing_records_and_invalid_limit(client):
    assert client.get('/api/llm/records').json() == []
    for limit in (0, 201, 'bad'):
        assert client.get(f'/api/llm/records?limit={limit}').status_code == 400


def test_failed_call_without_start_and_unreadable_path(client, settings):
    write_events(settings, [{"callId": "failed", "caller": "chat", "event": "failed", "timestamp": "2026-11-20T11:00:00Z", "errorCode": "GEMINI_RATE_LIMIT", "providerStatus": 429}])
    record = client.get('/api/llm/records').json()[0]
    assert record['startedAt'] is None and record['finishedAt'] is not None
    assert record['providerStatus'] == 429
    assert record['inputTokens'] is None
    settings.llm_record_path.unlink()
    settings.llm_record_path.mkdir()
    response = client.get('/api/llm/records')
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'RECORDS_UNAVAILABLE'


def test_reader_bounds_large_lines_and_skips_corruption(client, settings):
    settings.llm_record_path.parent.mkdir(parents=True, exist_ok=True)
    event = {"callId": "recent", "caller": "chat", "event": "cancelled", "timestamp": "2026-11-20T11:00:00Z"}
    settings.llm_record_path.write_bytes(b'x' * (2 * 1024 * 1024) + b'\ninvalid\n' + json.dumps(event).encode() + b'\n')
    assert client.get('/api/llm/records').json()[0]['callId'] == 'recent'
