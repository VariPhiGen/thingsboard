"""Telemetry helpers — normalization, keys, flatten, fetch edge cases."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.tools.telemetry import (
    AI_KEYS,
    DG_KEYS,
    GATEWAY_KEYS,
    fetch_active_alarms,
    fetch_ai_scores,
    fetch_history,
    fetch_latest_snapshot,
    flatten_latest,
    keys_for_device,
    normalize_value,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "N/A"),
        ("", "N/A"),
        (32767, "N/A"),
        (30000, "N/A"),
        (30000.1, "N/A"),
        (1500, "1500"),
        (1500.0, "1500"),
        (128.90, "128.9"),
        (128.901, "128.9"),
        ("RUNNING", "RUNNING"),
        ("12.50", "12.5"),
    ],
)
def test_normalize_value_matrix(raw, expected):
    assert normalize_value(raw) == expected


def test_keys_for_device_gateway_by_name_and_type():
    assert keys_for_device("gateway001") == GATEWAY_KEYS + AI_KEYS
    assert "rssi" in keys_for_device("Plant Box", "gateway")
    assert keys_for_device("DG SET1", "woodward_kg1500") == DG_KEYS


def test_flatten_latest_empty():
    values, ts = flatten_latest({})
    assert values == {}
    assert ts is None


def test_flatten_latest_picks_first_point_and_max_ts():
    raw = {
        "power_kw": [{"ts": 100, "value": "10"}, {"ts": 50, "value": "1"}],
        "engine_rpm": [{"ts": 200, "value": "1500"}],
        "empty": [],
    }
    values, ts = flatten_latest(raw)
    assert values["Power (kW)"] == "10"
    assert values["Engine RPM"] == "1500"
    assert ts == 200


@pytest.mark.asyncio
async def test_fetch_latest_snapshot():
    class FakeClient:
        async def latest_telemetry(self, device_id, keys):
            return {"power_kw": [{"ts": 99, "value": "42"}], "engine_rpm": [{"ts": 98, "value": "32767"}]}

    snap = await fetch_latest_snapshot(FakeClient(), uuid4(), "DG SET1", "woodward_kg1500")
    assert snap["deviceName"] == "DG SET1"
    assert snap["values"]["Power (kW)"] == "42"
    assert snap["values"]["Engine RPM"] == "N/A"
    assert snap["lastTelemetryTs"] == 99


@pytest.mark.asyncio
async def test_fetch_active_alarms_details_shapes():
    class FakeClient:
        async def active_alarms(self, device_id):
            return {
                "data": [
                    {"severity": "CRITICAL", "type": "High Coolant", "status": "ACTIVE_UNACK", "details": {"message": "hot"}},
                    {"severity": "MAJOR", "type": "Oil", "status": "ACTIVE_ACK", "details": "low"},
                    {"severity": "MINOR", "type": "X", "status": "ACTIVE_UNACK", "details": None},
                ]
            }

    alarms = await fetch_active_alarms(FakeClient(), uuid4())
    assert len(alarms) == 3
    assert alarms[0]["details"] == "hot"
    assert alarms[1]["details"] == "low"
    assert alarms[2]["details"] is None


@pytest.mark.asyncio
async def test_fetch_ai_scores_and_history():
    class FakeClient:
        async def latest_telemetry(self, device_id, keys):
            assert set(keys) == set(AI_KEYS)
            return {"health_score": [{"ts": 1, "value": "88"}]}

        async def history_telemetry(self, device_id, keys, start_ts, end_ts, limit=20):
            return {
                "power_kw": [{"ts": 2, "value": "20"}, {"ts": 1, "value": "10"}],
                "empty": [],
            }

    scores = await fetch_ai_scores(FakeClient(), uuid4())
    assert scores["Health Score"] == "88"

    hist = await fetch_history(FakeClient(), uuid4(), "DG SET1", 0, 1000)
    assert hist["Power (kW)"]["points"] == 2
    assert hist["Power (kW)"]["first"] == "10"
    assert hist["Power (kW)"]["last"] == "20"
