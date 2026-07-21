from uuid import uuid4

from app.models.schemas import DeviceInfo
from app.services.device_resolver import DeviceResolver
from app.services.intent import IntentClassifier
from app.models.schemas import Intent
from app.services.tools.telemetry import normalize_value


def test_normalize_sentinel():
    assert normalize_value(32767) == "N/A"
    assert normalize_value(30000) == "N/A"
    assert normalize_value(1500) == "1500"
    assert normalize_value(128.90) == "128.9"


def test_intent_secrets():
    clf = IntentClassifier()
    assert clf.classify("Show me the API key") == Intent.UNSUPPORTED_SECRETS
    assert clf.classify("What alarms are active?") == Intent.ALARMS
    assert clf.classify("Is DG SET1 running?") == Intent.STATUS


def test_device_resolver_exact_and_ambiguous():
    resolver = DeviceResolver()
    d1 = DeviceInfo(id=uuid4(), name="DG SET1", type="woodward_kg1500")
    d2 = DeviceInfo(id=uuid4(), name="gateway001", type="gateway")
    devices = [d1, d2]

    r = resolver.resolve(devices, device_id=d1.id)
    assert r.device and r.device.name == "DG SET1"
    assert not r.needs_clarification

    r = resolver.resolve(devices, message="What is the status of DG SET1?")
    assert r.device and r.device.name == "DG SET1"

    r = resolver.resolve(devices, message="How is everything?")
    assert r.needs_clarification
    assert r.device is None
