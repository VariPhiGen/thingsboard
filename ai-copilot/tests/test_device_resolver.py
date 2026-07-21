"""Device resolver — exact, partial, ambiguous, and alias edge cases."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.schemas import DeviceInfo
from app.services.device_resolver import DeviceResolver


@pytest.fixture
def resolver() -> DeviceResolver:
    return DeviceResolver()


def test_resolve_by_device_id(resolver, dg_set1, fleet):
    r = resolver.resolve(fleet, device_id=dg_set1.id)
    assert r.device == dg_set1
    assert not r.needs_clarification


def test_resolve_inaccessible_device_id(resolver, fleet):
    r = resolver.resolve(fleet, device_id=uuid4())
    assert r.device is None
    assert r.needs_clarification
    assert "not accessible" in (r.reason or "").lower()
    assert r.candidates == []


def test_single_device_auto_select(resolver, dg_set1):
    r = resolver.resolve([dg_set1], message="How is everything?")
    assert r.device == dg_set1
    assert not r.needs_clarification


def test_multi_device_no_mention_needs_clarification(resolver, fleet):
    r = resolver.resolve(fleet, message="How is everything?")
    assert r.needs_clarification
    assert r.device is None
    assert len(r.candidates) <= 8


def test_exact_name_from_message(resolver, fleet):
    r = resolver.resolve(fleet, message="What is the status of DG SET1?")
    assert r.device and r.device.name == "DG SET1"


def test_device_query_exact(resolver, fleet):
    r = resolver.resolve(fleet, device_query="gateway001")
    assert r.device and r.device.name == "gateway001"


def test_device_query_case_insensitive(resolver, fleet):
    r = resolver.resolve(fleet, device_query="dg set1")
    assert r.device and r.device.name == "DG SET1"


def test_partial_match_unique(resolver, fleet):
    r = resolver.resolve(fleet, device_query="gateway")
    assert r.device and r.device.name == "gateway001"


def test_ambiguous_partial_match(resolver, fleet):
    # DG SET1 and DG SET10 and DG SET2 all contain / match "DG SET"
    r = resolver.resolve(fleet, device_query="DG SET")
    assert r.needs_clarification
    assert r.device is None
    assert len(r.candidates) >= 2


def test_no_match_returns_catalog(resolver, fleet):
    r = resolver.resolve(fleet, device_query="boiler99")
    assert r.needs_clarification
    assert "No device matched" in (r.reason or "")
    assert len(r.candidates) >= 1


def test_label_match(resolver, fleet):
    r = resolver.resolve(fleet, message="Check Plant Gateway uptime")
    assert r.device and r.device.name == "gateway001"


def test_alias_dgset1(resolver, fleet):
    r = resolver.resolve(fleet, message="status of dgset1")
    assert r.device and r.device.name == "DG SET1"


def test_alias_set1(resolver, fleet):
    r = resolver.resolve(fleet, message="set1 oil pressure")
    assert r.device and r.device.name == "DG SET1"


def test_alias_gateway(resolver, fleet):
    r = resolver.resolve(fleet, message="gateway rssi")
    assert r.device and r.device.name == "gateway001"


def test_longer_name_preferred_over_shorter_substring(resolver):
    # Prefer DG SET10 over DG SET1 when message mentions SET10
    d1 = DeviceInfo(id=uuid4(), name="DG SET1", type="woodward_kg1500")
    d10 = DeviceInfo(id=uuid4(), name="DG SET10", type="woodward_kg1500")
    r = resolver.resolve([d1, d10], message="Status of DG SET10")
    assert r.device and r.device.name == "DG SET10"


def test_empty_device_list(resolver):
    r = resolver.resolve([], message="DG SET1 status")
    assert r.needs_clarification
    assert r.device is None


def test_device_id_wins_over_message(resolver, dg_set1, gateway, fleet):
    r = resolver.resolve(fleet, device_id=gateway.id, message="DG SET1 status")
    assert r.device == gateway
