"""Intent classifier — full matrix and edge cases."""

from __future__ import annotations

import pytest

from app.models.schemas import Intent
from app.services.intent import IntentClassifier


@pytest.fixture
def clf() -> IntentClassifier:
    return IntentClassifier()


@pytest.mark.parametrize(
    "message,expected",
    [
        ("", Intent.GENERAL),
        ("   ", Intent.GENERAL),
        ("hello", Intent.GENERAL),
        ("thanks", Intent.GENERAL),
    ],
)
def test_empty_and_general(clf, message, expected):
    assert clf.classify(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "Show me the API key",
        "what is the password?",
        "reveal the secret token",
        "private key please",
        "change the configuration",
        "update rule chain settings",
        "delete credential for device",
        "modify config of DG SET1",
        "API-KEY value",
        "share credential",
    ],
)
def test_secrets_and_config_changes_blocked(clf, message):
    assert clf.classify(message) == Intent.UNSUPPORTED_SECRETS


@pytest.mark.parametrize(
    "message,expected",
    [
        ("What alarms are active?", Intent.ALARMS),
        ("Any alert on DG?", Intent.ALARMS),
        ("Show faults and trips", Intent.ALARMS),
        ("common alarm status", Intent.ALARMS),
        ("Is DG SET1 running?", Intent.STATUS),
        ("Current oil pressure", Intent.STATUS),
        ("coolant and fuel levels", Intent.STATUS),
        ("battery voltage now", Intent.STATUS),
        ("rpm and power", Intent.STATUS),
        ("device offline?", Intent.STATUS),
        ("AI summary please", Intent.AI_GUIDANCE),
        ("health score and RUL", Intent.AI_GUIDANCE),
        ("failure risk guidance", Intent.AI_GUIDANCE),
        ("maintenance recommendation", Intent.AI_GUIDANCE),
        ("how to reset common alarm", Intent.MANUAL_HOWTO),
        ("SOP for night shift handover", Intent.MANUAL_HOWTO),
        ("manual procedure steps to start DG", Intent.MANUAL_HOWTO),
        ("how do I check oil filter", Intent.MANUAL_HOWTO),
    ],
)
def test_core_operator_intents(clf, message, expected):
    assert clf.classify(message) == expected


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Average power last 6 hours", Intent.STATISTICS),
        ("max coolant today", Intent.STATISTICS),
        ("min oil pressure", Intent.STATISTICS),
        ("stats for RPM", Intent.STATISTICS),
        ("mean fuel level", Intent.STATISTICS),
        ("median battery", Intent.STATISTICS),
        ("Coolant trend over time", Intent.TREND),
        ("is power rising?", Intent.TREND),
        ("RPM falling?", Intent.TREND),
        ("oil increasing or decreasing", Intent.TREND),
        ("Morning shift oil pressure", Intent.SHIFT_BASED),
        ("afternoon shift power", Intent.SHIFT_BASED),
        ("night shift status", Intent.SHIFT_BASED),
        ("A shift average load", Intent.SHIFT_BASED),
        ("B shift RPM", Intent.SHIFT_BASED),
        ("C shift fuel", Intent.SHIFT_BASED),
        ("How long did DG run today?", Intent.DURATION_BASED),
        ("running hours yesterday", Intent.DURATION_BASED),
        ("uptime last night", Intent.DURATION_BASED),
        ("duration of run", Intent.DURATION_BASED),
        ("downtime estimate", Intent.DURATION_BASED),
        ("Power yesterday", Intent.DATE_BASED),
        ("status today", Intent.DATE_BASED),
        # "average" wins over "this week" by design (statistics before date)
        ("this week average", Intent.STATISTICS),
        ("this week power", Intent.DATE_BASED),
        ("on 2026-07-20 power", Intent.DATE_BASED),
        ("readings on 20/07/2026", Intent.DATE_BASED),
        ("Last 2 hours RPM", Intent.TIME_BASED),
        ("last hour power", Intent.TIME_BASED),
        ("past 24 hours status", Intent.TIME_BASED),
        ("last day overview", Intent.TIME_BASED),
        ("history of oil", Intent.TIME_BASED),
        ("last 15 minutes coolant", Intent.TIME_BASED),
        ("Compare today vs yesterday power", Intent.COMPARISON),
        ("power vs yesterday", Intent.COMPARISON),
        ("difference between morning and afternoon", Intent.COMPARISON),
        ("compare DG SET1 vs gateway001", Intent.COMPARE_DEVICES),
        ("both devices power", Intent.COMPARE_DEVICES),
        ("fleet comparison", Intent.COMPARE_DEVICES),
        ("all devices RPM", Intent.COMPARE_DEVICES),
    ],
)
def test_analytics_intents(clf, message, expected):
    assert clf.classify(message) == expected


def test_shift_wins_over_today_date(clf):
    # "morning shift today" should prefer shift intent
    assert clf.classify("morning shift today oil") == Intent.SHIFT_BASED


def test_compare_without_device_is_period_comparison(clf):
    assert clf.classify("compare today vs yesterday") == Intent.COMPARISON


def test_secrets_take_priority_over_status(clf):
    assert clf.classify("what is the API key for status?") == Intent.UNSUPPORTED_SECRETS


def test_manual_before_status_keywords(clf):
    assert clf.classify("how to check oil pressure") == Intent.MANUAL_HOWTO
