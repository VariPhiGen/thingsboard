"""Deploy the hybrid Predictive Maintenance engine to ThingsBoard.

  python3 predictive_maintenance/deploy_pm.py --dry-run   # show what would change
  python3 predictive_maintenance/deploy_pm.py             # apply

Steps (all idempotent):
  1. Per device: baselines from the last 7 days of history -> server attribute pm_baseline;
     default settings merged into server attribute pm_config (values already set in ThingsBoard win);
     DG standby bootstrap (last run time) into pm_state when it does not exist yet.
  2. Rule chain "Predictive Maintenance" (created or replaced):
     dedup 5 min -> per-type fetch -> PM Compute (pm_compute.js) -> save pm_* telemetry + state,
     PM alarms (CRITICAL -> Telegram), and every 15 min a Gemini summary/recommendation.
  3. Root Rule Chain: the old DG-only AI path is removed and 'Save Timeseries' forwards to the
     new chain. A backup of the root chain is written next to this script before any change.
  4. Dashboard "Predictive Maintenance" (created or replaced).
"""
import argparse
import json
import os
import re
import statistics
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(HERE)
CHAIN_NAME = 'Predictive Maintenance'
DASHBOARD_TITLE = 'Predictive Maintenance'
AI_MODEL_ID = 'd78b28f0-810f-11f1-a760-b3ba4cbe1b98'
TELEGRAM_URL = 'http://172.23.0.1:5051'
SEED = json.load(open(os.path.join(HERE, 'pm_seed.json')))
KINDS = SEED['profiles']   # device profile -> equipment kind (template; each device keeps its kind in pm_config)
ALARM_CRITICAL = 'Predictive Maintenance - Critical'
ALARM_WARNING = 'Predictive Maintenance - Warning'
ALARM_FUEL_DROP = 'Fuel Drop While DG Off'
FIRST_NODE = 30   # 'Fetch PM Config' -> 'Route': configured equipment to the PM path, DG fuel messages also to the fuel path
# Nodes of the previous DG-only AI path in the Root Rule Chain (replaced by the new chain)
OLD_AI_NODES = {'Save AI Predictive Telemetry', 'DG AI Dedup 1m', 'Only DG Telemetry', 'DG SET1 AI Predictive',
                'Clamp AI Outputs', 'If CRITICAL Equipment', 'AI Predictive Alert', 'Sanitize DG Sensors',
                'Core Sensors Valid', 'Sensor Fault Fallback'}

# Telemetry keys fetched by the rule chain, from the template (pm_seed.json)
_K = SEED['kinds']
DG_KEYS = sorted(set(_K['DG']['keys'].values()))
RO_KEYS = sorted(set(_K['RO']['keys'].values()))
FIRE_KEYS = list(_K['FIRE']['relay_keys'])
BASELINE_KEYS = {
    'DG': [_K['DG']['keys'][k] for k in ('battery', 'fuel_raw', 'run_hours', 'voltage')],
    'RO': [_K['RO']['keys'][k] for k in ('tds', 'temperature', 'ph', 'pressure')],
}
LT_KEY = re.compile(r'^(.+)(' + '|'.join(re.escape(v) for v in _K['LT']['feeder_suffix'].values()) + r')$')
FIRE_CHANNEL = re.compile('|'.join('(?:%s)' % p for p in _K['FIRE']['channel_patterns']))


def load_env():
    env = {}
    with open(os.path.join(ROOT_DIR, '.env')) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k] = v
    return env


class TB:
    """Tenant session via infra_reports (TB_TENANT_USER/PASS, or sysadmin impersonation of the tenant)."""
    def __init__(self):
        from infra_reports.config import load_settings
        from infra_reports.tb_client import ThingsBoardClient
        c = ThingsBoardClient.connect(load_settings())
        self.base, self.h = c.base_url, dict(c._headers, **{"Content-Type": "application/json"})

    def get(self, path, **params):
        r = requests.get(self.base + path, headers=self.h, params=params, timeout=120)
        r.raise_for_status()
        return r.json() if r.text else None

    def post(self, path, body):
        r = requests.post(self.base + path, headers=self.h, json=body, timeout=120)
        if not r.ok:
            raise RuntimeError(f"POST {path} failed: {r.status_code} {r.text[:500]}")
        return r.json() if r.text else None


def node(type_, name, config, x, y, config_version=0):
    return {"type": type_, "name": name, "configuration": config, "configurationVersion": config_version,
            "debugSettings": {"failuresEnabled": True, "allEnabled": False, "allEnabledUntil": 0},
            "singletonMode": False, "queueName": None, "additionalInfo": {"layoutX": x, "layoutY": y, "description": ""}}


def is_sentinel(v):
    """Controller 'not available' codes, from the engine configuration of the template."""
    return v in SEED['engine']['invalid_codes'] or v >= SEED['engine']['invalid_at_or_above']


# ------------------------------------------------------------------ step 1: device data
def baseline(tb, did, keys, now):
    """median/p5/p95/p99 per key from 15-minute averages over the last 7 days (server allows ~700 intervals)."""
    out = {}
    if not keys:
        return out
    for i in range(0, len(keys), 20):
        chunk = keys[i:i + 20]
        data = tb.get(f"/api/plugins/telemetry/DEVICE/{did}/values/timeseries", keys=",".join(chunk),
                      startTs=now - 7 * 86400000, endTs=now, interval=900000, agg="AVG", limit=1000)
        for k, vals in (data or {}).items():
            nums = []
            for v in vals:
                try:
                    n = float(v['value'])
                except (TypeError, ValueError):
                    continue
                if n == n and not is_sentinel(n):
                    nums.append(n)
            if len(nums) >= 12:
                q = statistics.quantiles(nums, n=100)
                out[k] = {"median": round(statistics.median(nums), 3), "p5": round(q[4], 3), "p95": round(q[94], 3),
                          "p99": round(q[98], 3), "n": len(nums)}
    return out


def last_run_ts(tb, did, now, limits, days=60):
    """(exact time of the newest running sample, latest valid run-hour reading) from the device's own history.
    Running = configured running status, or rpm above the configured running rpm."""
    k = limits['keys']
    last = None
    for d in range(days):
        r = tb.get(f"/api/plugins/telemetry/DEVICE/{did}/values/timeseries", keys=f"{k['status']},{k['rpm']}",
                   startTs=now - (d + 1) * 86400000, endTs=now - d * 86400000, limit=50000, agg='NONE', orderBy='DESC') or {}
        hits = [v['ts'] for v in r.get(k['status'], []) if v['value'] == limits['running_status']]
        for v in r.get(k['rpm'], []):
            try:
                rpm = float(v['value'])
            except (TypeError, ValueError):
                continue
            if rpm > limits['running_rpm'] and not is_sentinel(rpm):
                hits.append(v['ts'])
        if hits:
            last = max(hits)
            break
    # Latest valid run-hour reading (AVG, not MAX: the gateway sometimes sends text)
    data = tb.get(f"/api/plugins/telemetry/DEVICE/{did}/values/timeseries", keys=k['run_hours'],
                  startTs=now - 7 * 86400000, endTs=now, interval=3 * 3600000, agg="AVG", limit=1000)
    pts = []
    for v in (data or {}).get(k['run_hours'], []):
        try:
            n = float(v['value'])
        except (TypeError, ValueError):
            continue
        if n == n and not is_sentinel(n):
            pts.append((v['ts'], n))
    pts.sort()
    return last, (pts[-1][1] if pts else None)


def fuel_replay(tb, did, name, config, days=14):
    """Replays dg_fuel.js (node) over the last `days` of fuel_level history; returns its final state and events."""
    import subprocess
    import tempfile
    now = int(time.time() * 1000)
    K = config['limits']['keys']
    rows = []
    for d in range(days, 0, -1):
        r = tb.get(f"/api/plugins/telemetry/DEVICE/{did}/values/timeseries", keys=f"{K['fuel_raw']},{K['rpm']},{K['status']}",
                   startTs=now - d * 86400000, endTs=now - (d - 1) * 86400000, limit=50000, agg='NONE', orderBy='ASC')
        rows += [(v['ts'], k, v['value']) for k, vs in (r or {}).items() for v in vs]
    rows.sort()
    status = rpm = None
    samples = []
    for ts, k, v in rows:
        if k == K['status']:
            status = v
        elif k == K['rpm']:
            rpm = v
        else:
            samples.append([ts, v, status, rpm])
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        json.dump({"name": name, "config": config, "samples": samples}, f)
        path = f.name
    try:
        out = subprocess.check_output(['node', os.path.join(HERE, 'replay_fuel.js'), path])
    finally:
        os.unlink(path)
    return json.loads(out)


def alarm_onset(tb, did, now, limits, days=30):
    """(code, ts) of the controller common alarm when it is active now: ts = first sample of the current active
    period, from the device's own history (None when the alarm is not active or its start is not in the history)."""
    key = limits['keys']['common_alarm']
    since, code = None, None
    for d in range(days):
        r = tb.get(f"/api/plugins/telemetry/DEVICE/{did}/values/timeseries", keys=key, startTs=now - (d + 1) * 86400000,
                   endTs=now - d * 86400000, limit=50000, agg='NONE', orderBy='DESC') or {}
        for v in r.get(key, []):
            try:
                n = float(v['value'])
            except (TypeError, ValueError):
                continue                                        # gateway read errors are not a state
            if is_sentinel(n):
                continue
            if n == 0:
                return (code, since) if code is not None else None
            if code is None:
                code = n
            since = v['ts']
    return None


def server_attrs(tb, did, keys):
    res = tb.get(f"/api/plugins/telemetry/DEVICE/{did}/values/attributes/SERVER_SCOPE", keys=",".join(keys)) or []
    out = {}
    for a in res:
        v = a['value']
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                pass
        out[a['key']] = v
    return out


class _MigrateTb:
    """Adapter giving migrate_config.new_config the calls it needs on top of TB."""
    def __init__(self, tb):
        self.tb = tb

    def attrs(self, eid, keys, etype="DEVICE"):
        return server_attrs(self.tb, eid, keys)

    def history_values(self, eid, key, days):
        now = int(time.time() * 1000)
        r = self.tb.get(f"/api/plugins/telemetry/DEVICE/{eid}/values/timeseries", keys=key, startTs=now - days * 86400000,
                        endTs=now, limit=50000, agg='NONE') or {}
        out = []
        for p in r.get(key, []):
            try:
                out.append(float(p['value']))
            except (TypeError, ValueError):
                pass
        return out


def prepare_devices(tb, dry):
    now = int(time.time() * 1000)
    devices = [d for d in tb.get('/api/tenant/deviceInfos', pageSize=500, page=0)['data'] if d['type'] in KINDS]
    keysets = {'LT': set(), 'FIRE_CH': set()}
    report = []
    for d in devices:
        did, kind = d['id']['id'], KINDS[d['type']]
        keys = tb.get(f"/api/plugins/telemetry/DEVICE/{did}/keys/timeseries") or []
        if kind == 'LT':
            keysets['LT'].update(k for k in keys if LT_KEY.match(k))
            bkeys = [k for k in keys if LT_KEY.match(k)]
        elif kind == 'FIRE':
            keysets['FIRE_CH'].update(k for k in keys if FIRE_CHANNEL.match(k))
            bkeys = []
        else:
            bkeys = [k for k in BASELINE_KEYS.get(kind, []) if k in keys]
        bl = baseline(tb, did, bkeys, now)
        existing = server_attrs(tb, did, ['pm_config', 'pm_state', 'fuel_state'])
        if not dry:
            tb.post(f"/api/plugins/telemetry/DEVICE/{did}/attributes/SERVER_SCOPE", {"pm_baseline": json.dumps(bl)})
        cfg, notes = new_config(_MigrateTb(tb), {"id": did, "name": d['name']}, kind, existing.get('pm_config'))
        state = existing.get('pm_state') if isinstance(existing.get('pm_state'), dict) else None
        attrs = {"pm_config": json.dumps(cfg)}
        note = '; '.join(notes)
        if kind == 'DG':
            lr, rh = last_run_ts(tb, did, now, cfg['limits'])
            if state is None:
                state = {"m": {}, "sev": {"confirmed": "OK", "cand": "OK", "n": 0}}
                if lr:
                    state["lastRunTs"] = lr
                if rh is not None:
                    state["lastRh"] = rh
            note += f" | run_hours={rh} last_run={time.strftime('%Y-%m-%d %H:%M', time.localtime(lr / 1000)) if lr else 'unknown'}"
        if kind == 'DG' and state is not None:
            onset = alarm_onset(tb, did, now, cfg['limits'])
            if onset and (not isinstance(state.get('ca'), dict) or (state['ca'].get('since') or now) > onset[1]):
                state['ca'] = {"code": onset[0], "since": onset[1]}
                attrs["pm_state"] = json.dumps(state)
                note += f" | controller alarm {onset[0]:g} since {time.strftime('%Y-%m-%d %H:%M', time.localtime(onset[1] / 1000))}"
        if state is not None and 'pm_state' not in existing:
            attrs["pm_state"] = json.dumps(state)
        if kind == 'DG' and 'fuel_state' not in existing:
            fr = fuel_replay(tb, did, d['name'], cfg)
            attrs["fuel_state"] = json.dumps(fr['state'])
            if not dry and fr['events']:
                # Fuel event log from history, at the original timestamps
                tb.post(f"/api/plugins/telemetry/DEVICE/{did}/timeseries/ANY",
                        [{"ts": ts, "values": {"fuel_event": text}} for ts, text in fr['events']])
            note += (f" | fuel bootstrap: burn={fr['state'].get('burn')}%/h from {fr['state'].get('burnN')} runs,"
                     f" refuels={sum(1 for e in fr['events'] if e[1].startswith('Refuel'))}, drops={len(fr['alarms'])}")
        report.append(f"  {d['name']:<30} {kind:<5} baseline keys={len(bl):<3} {note}")
        if not dry:
            tb.post(f"/api/plugins/telemetry/DEVICE/{did}/attributes/SERVER_SCOPE", attrs)
    return devices, keysets, report


# ------------------------------------------------------------------ step 2: PM rule chain
from predictive_maintenance.migrate_config import ROUTE_JS, SWITCH_JS, new_config   # routing by pm_config.kind

STATE_JS = """return {msg: {pm_state: metadata.pm_state_out}, metadata: metadata, msgType: 'POST_ATTRIBUTES_REQUEST'};
"""


FUEL_STATE_JS = """return {msg: {fuel_state: metadata.fuel_state_out}, metadata: metadata, msgType: 'POST_ATTRIBUTES_REQUEST'};
"""

FUEL_ALARM_SWITCH_JS = """return [metadata.fuel_alarm || 'NONE'];
"""

FUEL_ALARM_DETAILS_JS = """return {
  message: metadata.fuel_alarm_message,
  recommendation: 'Inspect the tank, drain valve and fuel lines; check the site log of authorised transfers.',
  source: 'DG fuel monitoring'
};
"""

ALARM_SWITCH_JS = """return [metadata.pm_alarm || 'SKIP'];
"""

ALARM_DETAILS_JS = """return {
  message: metadata.pm_alarm_message,
  recommendation: metadata.pm_alarm_action,
  health_score: metadata.pm_health,
  failure_risk_pct: metadata.pm_risk,
  source: 'Predictive Maintenance engine'
};
"""

CLEAR_DETAILS_JS = """var details = {};
if (metadata.prevAlarmDetails) details = JSON.parse(metadata.prevAlarmDetails);
details.cleared_reason = 'Condition back to normal: ' + (metadata.pm_alarm_message || '');
return details;
"""

LLM_SYSTEM = (
    "You are a maintenance engineer assistant for a facility with diesel generators (DG sets), "
    "LT electrical panels / UPS feeders, an RO water plant and fire-suppression cylinders. "
    "You receive the output of a deterministic predictive-maintenance engine (fields pm_*; pm_issues is a JSON list of "
    "{sev,text,action}). That output is authoritative: never change the severity, never invent readings or issues "
    "that are not in the input.\n"
    "Your text is shown to the facility's client on a dashboard: write short, plain English for a site manager. "
    "Never mention field names, configuration keys, variables or code (nothing with underscores such as pm_config, "
    "last_service_run_hours, pm_rul_days, rated_a), and do not mention the engine, JSON or AI. Use the issue texts and "
    "actions as written; for service records refer to Maintenance Management (preventive work orders).\n"
    "Respond with ONE JSON object only, no markdown, with keys:\n"
    "summary: max 220 characters - overall condition and the most important issues in plain words. You may name "
    "cylinders, feeders and alarm codes, but do not quote live readings, days left, health score or risk: the "
    "dashboard shows those next to your text and they change between your updates. If pm_severity is OK say the "
    "equipment is healthy and mention any INFO items briefly.\n"
    "recommendation: max 160 characters - one concrete next action for the most severe issue."
)
LLM_USER = "Equipment: ${deviceName} (${deviceType}). Predictive engine result JSON: $[*]"

LLM_OUT_JS = """function clean(v, n) {
  if (v === null || v === undefined) return '';
  return ('' + v).replace(/\\s+/g, ' ').trim().substring(0, n);
}
// Gemini sometimes varies the key names; accept the common variants
var s = clean(msg.summary || msg.Summary || msg.condition, 300);
var r = clean(msg.recommendation || msg.Recommendation || msg.maintenance_recommendation || msg.action, 300);
// Client-facing text: reject an answer that leaks internal names (snake_case keys such as pm_config)
var internal = /[A-Za-z0-9]+_[A-Za-z0-9_]+|json/i;
if (!s || !r || internal.test(s) || internal.test(r)) {
  return {msg: {pm_summary_source: 'ai_invalid'}, metadata: metadata, msgType: 'POST_TELEMETRY_REQUEST'};
}
var out = {pm_summary: s, pm_recommendation: r, pm_summary_source: 'ai'};
var pmCfg = {};
try { pmCfg = JSON.parse(metadata.ss_pm_config || '{}'); } catch (e) { pmCfg = {}; }
if (pmCfg.kind === 'DG') {
  out.summary = s;
  out.maintenance_recommendation = r;
}
return {msg: out, metadata: metadata, msgType: 'POST_TELEMETRY_REQUEST'};
"""


def fetch_node(name, latest, x, y):
    return node('org.thingsboard.rule.engine.metadata.TbGetAttributesNode', name, {
        "fetchTo": "METADATA", "clientAttributeNames": [], "sharedAttributeNames": [],
        "serverAttributeNames": ["pm_state", "pm_baseline", "pm_config"],
        "latestTsKeyNames": sorted(set(latest) | {"pm_summary"}),
        "tellFailureIfAbsent": False, "getLatestValueWithTs": True}, x, y, 1)


def js_transform(name, script, x, y):
    return node('org.thingsboard.rule.engine.transform.TbTransformMsgNode', name,
                {"scriptLang": "JS", "jsScript": script, "tbelScript": "return {msg: msg, metadata: metadata, msgType: msgType};"}, x, y)


def build_pm_chain(keysets):
    compute_js = open(os.path.join(HERE, 'pm_compute.js')).read()
    N = [
        node('org.thingsboard.rule.engine.deduplication.TbMsgDeduplicationNode', 'Every 5 min per device',
             {"interval": 300, "strategy": "LAST", "outMsgType": None, "maxPendingMsgs": 1000, "maxRetries": 3}, 300, 150, 1),  # 0
        node('org.thingsboard.rule.engine.filter.TbJsSwitchNode', 'Equipment Type',
             {"scriptLang": "JS", "jsScript": SWITCH_JS, "tbelScript": "return ['Other'];"}, 560, 150),  # 1
        fetch_node('Fetch DG Data', DG_KEYS, 820, 30),  # 2
        fetch_node('Fetch LT Data', sorted(keysets['LT']), 820, 130),  # 3
        fetch_node('Fetch RO Data', RO_KEYS, 820, 230),  # 4
        fetch_node('Fetch Fire Data', FIRE_KEYS, 820, 330),  # 5
        node('org.thingsboard.rule.engine.metadata.TbGetTelemetryNode', 'Fire Channels Last 15 min', {
            "startInterval": _K['FIRE']['window_minutes'], "endInterval": 0, "startIntervalPattern": "", "endIntervalPattern": "",
            "useMetadataIntervalPatterns": False, "startIntervalTimeUnit": "MINUTES", "endIntervalTimeUnit": "MINUTES",
            "fetchMode": "ALL", "orderBy": "ASC", "aggregation": "NONE", "limit": 1000,
            "latestTsKeyNames": sorted(keysets['FIRE_CH'])}, 1080, 330, 2),  # 6
        js_transform('PM Compute', compute_js, 1340, 150),  # 7
        node('org.thingsboard.rule.engine.telemetry.TbMsgTimeseriesNode', 'Save PM Telemetry',
             {"defaultTTL": 0, "useServerTs": False, "processingSettings": {"type": "ON_EVERY_MESSAGE"}}, 1620, 30, 1),  # 8
        js_transform('PM State', STATE_JS, 1620, 110),  # 9
        node('org.thingsboard.rule.engine.telemetry.TbMsgAttributesNode', 'Save PM State', {
            "processingSettings": {"type": "ON_EVERY_MESSAGE"}, "scope": "SERVER_SCOPE", "notifyDevice": False,
            "sendAttributesUpdatedNotification": False, "updateAttributesOnlyOnValueChange": False}, 1880, 110, 3),  # 10
        node('org.thingsboard.rule.engine.filter.TbJsSwitchNode', 'PM Alarm Level',
             {"scriptLang": "JS", "jsScript": ALARM_SWITCH_JS, "tbelScript": "return ['SKIP'];"}, 1620, 260),  # 11
    ]

    def create_alarm(name, atype, sev, x, y):
        return node('org.thingsboard.rule.engine.action.TbCreateAlarmNode', name, {
            "scriptLang": "JS", "alarmDetailsBuildJs": ALARM_DETAILS_JS, "alarmDetailsBuildTbel": "return {};",
            "alarmType": atype, "severity": sev, "propagate": False, "propagateToOwner": False,
            "propagateToTenant": False, "useMessageAlarmData": False, "overwriteAlarmDetails": True,
            "dynamicSeverity": False, "relationTypes": []}, x, y)

    def clear_alarm(name, atype, x, y):
        return node('org.thingsboard.rule.engine.action.TbClearAlarmNode', name, {
            "scriptLang": "JS", "alarmDetailsBuildJs": CLEAR_DETAILS_JS, "alarmDetailsBuildTbel": "return {};",
            "alarmType": atype}, x, y)

    N += [
        create_alarm('Create PM Critical', ALARM_CRITICAL, 'CRITICAL', 1880, 200),  # 12
        create_alarm('Create PM Warning', ALARM_WARNING, 'WARNING', 1880, 280),  # 13
        clear_alarm('Clear PM Critical', ALARM_CRITICAL, 1880, 360),  # 14
        clear_alarm('Clear PM Warning', ALARM_WARNING, 1880, 440),  # 15
        node('org.thingsboard.rule.engine.rest.TbRestApiCallNode', 'Telegram Webhook (PM Critical)', {
            "restEndpointUrlPattern": TELEGRAM_URL, "requestMethod": "POST", "maxParallelRequestsCount": 0,
            "headers": {"Content-Type": "application/json"}, "readTimeoutMs": 0, "maxInMemoryBufferSizeInKb": 256,
            "requestBodyTemplate": None}, 2140, 280, 3),  # 16
        node('org.thingsboard.rule.engine.deduplication.TbMsgDeduplicationNode', 'Every 15 min (AI summary)',
             {"interval": 900, "strategy": "LAST", "outMsgType": None, "maxPendingMsgs": 100, "maxRetries": 3}, 1620, 560, 1),  # 17
        node('org.thingsboard.rule.engine.ai.TbAiNode', 'Gemini PM Summary', {
            "modelId": {"entityType": "AI_MODEL", "id": AI_MODEL_ID}, "systemPrompt": LLM_SYSTEM, "userPrompt": LLM_USER,
            "resourceIds": None, "responseFormat": {"type": "JSON"}, "timeoutSeconds": 60, "forceAck": True}, 1880, 560),  # 18
        js_transform('AI Summary Fields', LLM_OUT_JS, 2140, 560),  # 19
        node('org.thingsboard.rule.engine.telemetry.TbMsgTimeseriesNode', 'Save AI Summary',
             {"defaultTTL": 0, "useServerTs": False, "processingSettings": {"type": "ON_EVERY_MESSAGE"}}, 2400, 560, 1),  # 20
    ]
    fuel_js = open(os.path.join(HERE, 'dg_fuel.js')).read()
    N += [
        node('org.thingsboard.rule.engine.filter.TbJsSwitchNode', 'Route',
             {"scriptLang": "JS", "jsScript": ROUTE_JS, "tbelScript": "return ['PM'];"}, 60, 300),  # 21
        node('org.thingsboard.rule.engine.metadata.TbGetAttributesNode', 'Fetch Fuel Context', {
            "fetchTo": "METADATA", "clientAttributeNames": [], "sharedAttributeNames": [],
            "serverAttributeNames": ["fuel_state", "pm_config"], "latestTsKeyNames": [_K['DG']['keys']['status'], _K['DG']['keys']['rpm']],
            "tellFailureIfAbsent": False, "getLatestValueWithTs": False}, 300, 760, 1),  # 22
        js_transform('DG Fuel', fuel_js, 560, 760),  # 23
        node('org.thingsboard.rule.engine.telemetry.TbMsgTimeseriesNode', 'Save Fuel Telemetry',
             {"defaultTTL": 0, "useServerTs": False, "processingSettings": {"type": "ON_EVERY_MESSAGE"}}, 820, 680, 1),  # 24
        js_transform('Fuel State', FUEL_STATE_JS, 820, 760),  # 25
        node('org.thingsboard.rule.engine.telemetry.TbMsgAttributesNode', 'Save Fuel State', {
            "processingSettings": {"type": "ON_EVERY_MESSAGE"}, "scope": "SERVER_SCOPE", "notifyDevice": False,
            "sendAttributesUpdatedNotification": False, "updateAttributesOnlyOnValueChange": False}, 1080, 760, 3),  # 26
        node('org.thingsboard.rule.engine.filter.TbJsSwitchNode', 'Fuel Alarm',
             {"scriptLang": "JS", "jsScript": FUEL_ALARM_SWITCH_JS, "tbelScript": "return ['NONE'];"}, 820, 860),  # 27
        node('org.thingsboard.rule.engine.action.TbCreateAlarmNode', 'Create Fuel Drop Alarm', {
            "scriptLang": "JS", "alarmDetailsBuildJs": FUEL_ALARM_DETAILS_JS, "alarmDetailsBuildTbel": "return {};",
            "alarmType": ALARM_FUEL_DROP, "severity": "CRITICAL", "propagate": False, "propagateToOwner": False,
            "propagateToTenant": False, "useMessageAlarmData": False, "overwriteAlarmDetails": True,
            "dynamicSeverity": False, "relationTypes": []}, 1080, 840),  # 28
        node('org.thingsboard.rule.engine.action.TbClearAlarmNode', 'Clear Fuel Drop Alarm', {
            "scriptLang": "JS", "alarmDetailsBuildJs": CLEAR_DETAILS_JS, "alarmDetailsBuildTbel": "return {};",
            "alarmType": ALARM_FUEL_DROP}, 1080, 920),  # 29
        node('org.thingsboard.rule.engine.metadata.TbGetAttributesNode', 'Fetch PM Config', {
            "fetchTo": "METADATA", "clientAttributeNames": [], "sharedAttributeNames": [], "serverAttributeNames": ["pm_config"],
            "latestTsKeyNames": [], "tellFailureIfAbsent": False, "getLatestValueWithTs": False}, 60, 520, 1),  # 30
    ]
    C = [(30, 21, 'Success'), (21, 0, 'PM'), (21, 22, 'FUEL'), (22, 23, 'Success'), (23, 24, 'Success'), (23, 25, 'Success'),
         (25, 26, 'Success'), (23, 27, 'Success'), (27, 28, 'DROP'), (27, 29, 'CLEAR_DROP'),
         (28, 16, 'Created'), (29, 16, 'Cleared'),
         (0, 1, 'Success'), (1, 2, 'DG'), (1, 3, 'LT'), (1, 4, 'RO'), (1, 5, 'FIRE'), (5, 6, 'Success'),
         (2, 7, 'Success'), (3, 7, 'Success'), (4, 7, 'Success'), (6, 7, 'Success'),
         (7, 8, 'Success'), (7, 9, 'Success'), (9, 10, 'Success'), (7, 11, 'Success'), (7, 17, 'Success'),
         (11, 12, 'CRITICAL'), (11, 15, 'CRITICAL'), (11, 13, 'WARNING'), (11, 14, 'WARNING'),
         (11, 14, 'OK'), (11, 15, 'OK'), (12, 16, 'Created'), (14, 16, 'Cleared'),
         (17, 18, 'Success'), (18, 19, 'Success'), (19, 20, 'Success')]
    return N, [{"fromIndex": a, "toIndex": b, "type": t} for a, b, t in C]


NASHORN_FOR = re.compile(r'^\s*for \(var [^)]*\) \{\s*$')
NASHORN_FN = re.compile(r'function\s*\w*\s*\([^)]*\)\s*\{')


def nashorn_problems(script):
    """Lines ThingsBoard's Nashorn sandbox rejects: it wants braces after f-o-r/w-h-i-l-e/d-o/function and
    its regex also matches those words inside strings and comments."""
    bad = []
    for i, line in enumerate(script.split('\n'), 1):
        if re.search(r'\b(while|do)\b', line) or (re.search(r'\bfor\b', line) and not NASHORN_FOR.match(line)) \
                or (re.search(r'\bfunction\b', line) and not NASHORN_FN.search(line)):
            bad.append(f"{i}: {line.strip()}")
    return bad


def deploy_chain(tb, keysets, dry):
    chains = tb.get('/api/ruleChains', pageSize=200, page=0, type='CORE')['data']
    rc = next((c for c in chains if c['name'] == CHAIN_NAME), None)
    nodes, conns = build_pm_chain(keysets)
    for n in nodes:
        for field in ('jsScript', 'alarmDetailsBuildJs'):
            script = n['configuration'].get(field)
            if script and n['configuration'].get('scriptLang', 'JS') == 'JS':
                bad = nashorn_problems(script)
                if bad:
                    raise SystemExit(f"Node '{n['name']}' {field} would be rejected by the Nashorn sandbox:\n  " + "\n  ".join(bad))
    if dry:
        return (rc['id']['id'] if rc else None), f"  {len(nodes)} nodes, {len(conns)} connections ({'update' if rc else 'create'})"
    if not rc:
        rc = tb.post('/api/ruleChain', {"name": CHAIN_NAME, "type": "CORE", "debugMode": False,
                                        "additionalInfo": {"description": "Hybrid predictive maintenance for DG, LT panels, RO and fire suppression"}})
    md = {"ruleChainId": rc['id'], "firstNodeIndex": FIRST_NODE, "nodes": nodes, "connections": conns, "ruleChainConnections": []}
    tb.post('/api/ruleChain/metadata', md)
    return rc['id']['id'], f"  {len(nodes)} nodes, {len(conns)} connections"


# ------------------------------------------------------------------ step 3: root chain
def patch_root(tb, pm_chain_id, dry):
    chains = tb.get('/api/ruleChains', pageSize=200, page=0, type='CORE')['data']
    root = next(c for c in chains if c.get('root'))
    md = tb.get(f"/api/ruleChain/{root['id']['id']}/metadata")
    backup = os.path.join(HERE, f"root_rule_chain_backup_{time.strftime('%Y%m%d_%H%M%S')}.json")
    nodes = md['nodes']
    removed = [i for i, n in enumerate(nodes) if n['name'] in OLD_AI_NODES]
    save_idx = next(i for i, n in enumerate(nodes) if n['name'] == 'Save Timeseries')
    has_input = any(n['type'].endswith('TbRuleChainInputNode') and n['name'] == CHAIN_NAME for n in nodes)
    if not removed and has_input:
        return "  already patched"
    msg = f"  remove old AI nodes: {[nodes[i]['name'] for i in removed]}; add '{CHAIN_NAME}' input after 'Save Timeseries'"
    if dry:
        return msg
    with open(backup, 'w') as f:
        json.dump(md, f, indent=2)
    keep = [i for i in range(len(nodes)) if i not in removed]
    remap = {old: new for new, old in enumerate(keep)}
    new_nodes = [nodes[i] for i in keep]
    conns = [{"fromIndex": remap[c['fromIndex']], "toIndex": remap[c['toIndex']], "type": c['type']}
             for c in md['connections'] if c['fromIndex'] in remap and c['toIndex'] in remap]
    if not has_input:
        n = node('org.thingsboard.rule.engine.flow.TbRuleChainInputNode', CHAIN_NAME,
                 {"ruleChainId": pm_chain_id, "forwardMsgToDefaultRuleChain": False}, 760, 560, 1)
        new_nodes.append(n)
        conns.append({"fromIndex": remap[save_idx], "toIndex": len(new_nodes) - 1, "type": "Success"})
    md['nodes'] = new_nodes
    md['connections'] = conns
    md['firstNodeIndex'] = remap[md['firstNodeIndex']]
    tb.post('/api/ruleChain/metadata', md)
    return msg + f"\n  backup: {backup}"


def clear_old_ai_alarms(tb, devices, dry):
    out = []
    for d in devices:
        res = tb.get(f"/api/alarm/DEVICE/{d['id']['id']}", pageSize=50, page=0, searchStatus='ACTIVE')['data']
        for a in res:
            if a['type'] == 'AI Predictive Alert':
                out.append(f"  clear '{a['type']}' on {d['name']}")
                if not dry:
                    tb.post(f"/api/alarm/{a['id']['id']}/clear", {})
    return out


# ------------------------------------------------------------------ step 4: dashboard
OVERVIEW_JS = r"""
function esc(s) {
  return ('' + (s === undefined || s === null ? '' : s)).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\{/g, '&#123;').replace(/\}/g, '&#125;');
}
var COL = {OK: '#2e7d32', WARNING: '#ef6c00', CRITICAL: '#c62828', 'NO DATA': '#757575'};
var BG = {OK: '#e8f5e9', WARNING: '#fff3e0', CRITICAL: '#ffebee', 'NO DATA': '#f5f5f5'};
var ORDER = {CRITICAL: 0, WARNING: 1, 'NO DATA': 2, OK: 3};
var rows = (data || []).slice().filter(function (r) { return r && r.entityName; });
rows.sort(function (a, b) {
  var d = (ORDER[a.Severity] === undefined ? 4 : ORDER[a.Severity]) - (ORDER[b.Severity] === undefined ? 4 : ORDER[b.Severity]);
  return d !== 0 ? d : ('' + a.entityName).localeCompare('' + b.entityName);
});
var counts = {OK: 0, WARNING: 0, CRITICAL: 0, 'NO DATA': 0};
var cards = '';
for (var i = 0; i < rows.length; i++) {
  var r = rows[i];
  var sev = r.Severity || 'NO DATA';
  if (counts[sev] === undefined) sev = 'NO DATA';
  counts[sev]++;
  var c = COL[sev], bg = BG[sev];
  var h = Number(r.Health);
  var hasH = isFinite(h) && r.Health !== '' && r.Health !== '--';
  var pct = hasH ? Math.max(0, Math.min(100, h)) : 0;
  var dash = (pct / 100 * 163.4).toFixed(1);
  var ring = '<svg viewBox="0 0 64 64" style="width:64px;height:64px;flex:none;">' +
    '<circle cx="32" cy="32" r="26" fill="none" stroke="#eceff1" stroke-width="7"></circle>' +
    '<circle cx="32" cy="32" r="26" fill="none" stroke="' + c + '" stroke-width="7" stroke-linecap="round" stroke-dasharray="' + dash + ' 163.4" transform="rotate(-90 32 32)"></circle>' +
    '<text x="32" y="37" text-anchor="middle" font-size="15" font-weight="700" fill="#263238">' + (hasH ? Math.round(h) : '--') + '</text></svg>';
  var issues = [];
  try { issues = JSON.parse(r.Issues || '[]'); } catch (e) { issues = []; }
  var il = '';
  for (var j = 0; j < issues.length && j < 4; j++) {
    var it = issues[j];
    var ic = it.sev === 'CRITICAL' ? '#c62828' : (it.sev === 'WARNING' ? '#ef6c00' : '#78909c');
    il += '<div style="display:flex;gap:6px;align-items:flex-start;margin-top:3px;"><span style="flex:none;width:8px;height:8px;border-radius:50%;background:' + ic + ';margin-top:5px;"></span><span>' + esc(it.text) + '</span></div>';
  }
  if (!il) il = '<div style="color:#78909c;margin-top:3px;">No issues detected</div>';
  var rul = (r.RUL === undefined || r.RUL === '' || r.RUL === '--') ? 'No trend' : esc(r.RUL) + ' days';
  var risk = (r.Risk === undefined || r.Risk === '' || r.Risk === '--') ? '--' : esc(r.Risk) + '%';
  cards += '<div style="flex:1 1 360px;max-width:calc(33.33% - 12px);min-width:320px;background:#fff;border-radius:10px;border:1px solid #e0e0e0;border-top:4px solid ' + c + ';padding:12px 14px;box-sizing:border-box;box-shadow:0 1px 3px rgba(0,0,0,.08);">' +
    '<div style="display:flex;gap:12px;align-items:center;">' + ring +
    '<div style="flex:1;min-width:0;"><div style="font-size:15px;font-weight:600;color:#263238;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + esc(r.entityName) + '</div>' +
    '<div style="margin-top:4px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;">' +
    '<span style="background:' + bg + ';color:' + c + ';border:1px solid ' + c + ';border-radius:12px;padding:1px 9px;font-size:11px;font-weight:700;">' + esc(sev) + '</span>' +
    (r.Mode ? '<span style="font-size:11px;color:#607d8b;">' + esc(r.Mode) + '</span>' : '') + '</div></div>' +
    '<div style="text-align:right;font-size:11px;color:#607d8b;line-height:1.5;">Risk <b style="color:#263238;font-size:13px;">' + risk + '</b><br>Days left <b style="color:#263238;font-size:13px;">' + rul + '</b><br>Data quality <b style="color:#263238;">' + esc(r.Quality === undefined ? '--' : r.Quality) + '%</b></div></div>' +
    '<div style="font-size:12px;color:#37474f;margin-top:8px;">' + il + '</div>' +
    '<div style="font-size:12px;color:#455a64;margin-top:8px;padding-top:8px;border-top:1px dashed #e0e0e0;">' + esc(r.Summary) + '</div>' +
    '<div style="font-size:12px;color:#1565c0;margin-top:4px;"><b>Action:</b> ' + esc(r.Recommendation) + '</div>' +
    '</div>';
}
var head = '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;">';
var keys = ['CRITICAL', 'WARNING', 'OK', 'NO DATA'];
for (var k = 0; k < keys.length; k++) {
  head += '<div style="background:' + BG[keys[k]] + ';color:' + COL[keys[k]] + ';border-radius:8px;padding:6px 14px;font-weight:700;font-size:13px;">' + keys[k] + ': ' + counts[keys[k]] + '</div>';
}
head += '<div style="margin-left:auto;font-size:11px;color:#78909c;align-self:center;">Health 80-100 OK, 40-79 Warning, 0-39 Critical. Days left = forecast days until a reading reaches its limit (shown when a steady trend is found).</div></div>';
return '<div style="padding:12px;font-family:Roboto,sans-serif;box-sizing:border-box;">' + head +
  '<div style="display:flex;flex-wrap:wrap;gap:12px;">' + cards + '</div></div>';
"""


def build_dashboard(tb, existing):
    alias_id = 'pm-all-equipment'
    aliases = {alias_id: {"id": alias_id, "alias": "All monitored equipment", "filter": {
        "type": "deviceType", "resolveMultiple": True, "deviceTypes": sorted(KINDS), "deviceType": None,
        "deviceNameFilter": ""}}}
    keys = [('pm_health_score', 'Health'), ('pm_severity', 'Severity'), ('pm_risk_pct', 'Risk'),
            ('pm_rul_days', 'RUL'), ('pm_issues', 'Issues'), ('pm_summary', 'Summary'),
            ('pm_recommendation', 'Recommendation'), ('pm_mode', 'Mode'), ('pm_data_quality_pct', 'Quality')]
    overview = {
        "typeFullFqn": "system.cards.markdown_card", "type": "latest", "sizeX": 24, "sizeY": 13, "row": 0, "col": 0,
        "id": "pm_overview",
        "config": {
            "title": "Equipment Health", "showTitle": True, "showTitleIcon": False, "dropShadow": True,
            "enableFullscreen": True, "backgroundColor": "#f7f9fa", "color": "rgba(0,0,0,0.87)", "padding": "0px",
            "titleStyle": {"fontSize": "16px", "fontWeight": 600},
            "datasources": [{"type": "entity", "name": "", "entityAliasId": alias_id, "dataKeys": [
                {"name": k, "type": "timeseries", "label": l, "color": "#2196f3", "settings": {}} for k, l in keys]}],
            "timewindow": {"realtime": {"realtimeType": 0, "interval": 1000, "timewindowMs": 60000}},
            "settings": {"useMarkdownTextFunction": True, "markdownTextFunction": OVERVIEW_JS, "markdownTextPattern": "",
                         "applyDefaultMarkdownStyle": False, "markdownCss": ""}}}
    chart_type = tb.get('/api/widgetType', fqn='system.charts.basic_timeseries')
    chart_cfg = json.loads(chart_type['descriptor']['defaultConfig'])
    chart_cfg.update({
        "title": "Health score trend (hourly average)", "showTitle": True, "useDashboardTimewindow": False,
        "displayTimewindow": True, "showLegend": True,
        "datasources": [{"type": "entity", "name": "", "entityAliasId": alias_id, "dataKeys": [
            # No key-level aggregationType: on a data key it means "one aggregated value for the whole window",
            # which leaves a line chart empty. The hourly AVG comes from the widget timewindow below.
            {"name": "pm_health_score", "type": "timeseries", "label": "${entityName}", "color": "#2196f3",
             "settings": {}}]}],
        "timewindow": {"selectedTab": 0, "realtime": {"realtimeType": 0, "timewindowMs": 7 * 86400000,
                                                      "interval": 3600000},
                       "aggregation": {"type": "AVG", "limit": 2000}},
    })
    chart_cfg.setdefault("settings", {})
    chart = {"typeFullFqn": "system.charts.basic_timeseries", "type": "timeseries", "sizeX": 24, "sizeY": 7,
             "row": 13, "col": 0, "id": "pm_health_trend", "config": chart_cfg}
    widgets = {"pm_overview": overview, "pm_health_trend": chart}
    cfg = {
        "description": "Hybrid predictive maintenance: rule-based health scoring with trends, AI summaries",
        "widgets": widgets,
        "states": {"default": {"name": "Predictive Maintenance", "root": True, "layouts": {"main": {
            "widgets": {w: {"sizeX": v["sizeX"], "sizeY": v["sizeY"], "row": v["row"], "col": v["col"]} for w, v in widgets.items()},
            "gridSettings": {"backgroundColor": "#eeeeee", "columns": 24, "margin": 10, "backgroundSizeMode": "100%"}}}}},
        "entityAliases": aliases, "filters": {},
        "timewindow": {"displayValue": "", "selectedTab": 0,
                       "realtime": {"realtimeType": 0, "interval": 1000, "timewindowMs": 60000}},
        "settings": {"stateControllerId": "entity", "showTitle": True, "showDashboardsSelect": True,
                     "showEntitiesSelect": True, "showDashboardTimewindow": True, "showDashboardExport": True,
                     "toolbarAlwaysOpen": True}}
    body = {"title": DASHBOARD_TITLE, "configuration": cfg}
    if existing:
        body["id"] = existing["id"]
        body["version"] = existing.get("version")
    return body


DG_DASHBOARDS = ['09c06030-81cc-11f1-a760-b3ba4cbe1b98', '12254780-b373-11f1-9522-c1f9998e0221',
                 'e643c300-b406-11f1-9522-c1f9998e0221']
FUEL_TILE_ID = 'f8e7d6c5-b4a3-4291-8f6d-5e4d3c2b1a09'     # was a value card (top KPI row)
FUEL_TANK_ID = 'a1b2c3d4-e5f6-7890-abcd-ef1234567891'     # was a digital speedometer
ENGINE_CHART_ID = '2a3ff8c1-8eef-4027-bdc9-1c5ceb5496fd'
FUEL_KEYS = [('fuel_level_pct', 'Level'), ('fuel_status', 'Status'), ('fuel_full_scale', 'Full'),
             ('fuel_low_pct', 'Low'), ('fuel_critical_pct', 'Critical'), ('fuel_capacity_l', 'Capacity'),
             ('fuel_litres', 'Litres'), ('fuel_runtime_h', 'Runtime'), ('fuel_burn_basis', 'Basis'),
             ('fuel_burn_pct_h', 'Burn'), ('fuel_burn_lph', 'BurnLph'), ('fuel_last_refuel_ts', 'RefuelTs'),
             ('fuel_last_refuel_pct', 'RefuelPct'), ('fuel_last_refuel_l', 'RefuelL'),
             ('fuel_last_refuel_full', 'RefuelFull'), ('fuel_event', 'Event'), ('fuel_drop_active', 'Drop')]


def fuel_card(old, script, title, show_title):
    alias = old['config']['datasources'][0]['entityAliasId']
    cfg = {
        "title": title, "showTitle": show_title, "showTitleIcon": False, "dropShadow": True, "enableFullscreen": True,
        "backgroundColor": "#FFFFFF", "color": "rgba(0, 0, 0, 0.87)", "padding": "0px",
        "titleStyle": {"fontSize": "16px", "fontWeight": 400},
        "datasources": [{"type": "entity", "name": "", "entityAliasId": alias, "filterId": None, "dataKeys": [
            {"name": k, "type": "timeseries", "label": l, "color": "#CA8A04", "settings": {}} for k, l in FUEL_KEYS]}],
        "timewindow": {"realtime": {"realtimeType": 0, "interval": 1000, "timewindowMs": 60000}},
        "settings": {"useMarkdownTextFunction": True, "markdownTextFunction": script, "markdownTextPattern": "",
                     "applyDefaultMarkdownStyle": False, "markdownCss": ""}}
    return {"typeFullFqn": "system.cards.markdown_card", "type": "latest", "sizeX": old.get('sizeX'),
            "sizeY": old.get('sizeY'), "row": old.get('row'), "col": old.get('col'), "id": old['id'], "config": cfg}


def patch_dg_dashboards(tb, dry):
    tile_js = open(os.path.join(HERE, 'widgets', 'fuel_tile.js')).read()
    tank_js = open(os.path.join(HERE, 'widgets', 'fuel_tank.js')).read()
    out = []
    for did in DG_DASHBOARDS:
        dash = tb.get(f"/api/dashboard/{did}")
        w = dash['configuration']['widgets']
        changes = []
        if FUEL_TILE_ID in w:
            w[FUEL_TILE_ID] = fuel_card(w[FUEL_TILE_ID], tile_js, 'Fuel Level', False)
            changes.append('fuel tile')
        if FUEL_TANK_ID in w:
            w[FUEL_TANK_ID] = fuel_card(w[FUEL_TANK_ID], tank_js, 'Fuel Tank', True)
            changes.append('fuel tank panel')
        chart = w.get(ENGINE_CHART_ID)
        if chart:
            for ds in chart['config'].get('datasources', []):
                for dk in ds.get('dataKeys', []):
                    if dk['name'] in (_K['DG']['keys']['fuel_raw'], _K['DG']['keys']['fuel_pct']):
                        dk['name'] = _K['DG']['keys']['fuel_pct']
                        dk['label'] = 'Fuel Level (filtered)'
                        changes.append('chart fuel series')
        if dry:
            out.append(f"  {dash['title']}: {', '.join(changes)}")
            continue
        backup = os.path.join(HERE, f"dashboard_{did}_backup.json")
        if not os.path.exists(backup):
            with open(backup, 'w') as f:
                json.dump(tb.get(f"/api/dashboard/{did}"), f, indent=2)
        tb.post('/api/dashboard', dash)
        out.append(f"  {dash['title']}: {', '.join(changes)}")
    return out


def deploy_dashboard(tb, dry):
    dashes = tb.get('/api/tenant/dashboards', pageSize=200, page=0)['data']
    existing = next((d for d in dashes if d['title'] == DASHBOARD_TITLE), None)
    if existing:
        existing = tb.get(f"/api/dashboard/{existing['id']['id']}")
    body = build_dashboard(tb, existing)
    if dry:
        return f"  {'update' if existing else 'create'} dashboard '{DASHBOARD_TITLE}'"
    res = tb.post('/api/dashboard', body)
    return f"  dashboard id {res['id']['id']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    dry = args.dry_run
    tb = TB()
    print("1. Devices (baselines from last 7 days, pm_config from pm_seed.json + device history):")
    devices, keysets, report = prepare_devices(tb, dry)
    print("\n".join(report))
    print(f"   LT keys: {len(keysets['LT'])}, fire channels: {sorted(keysets['FIRE_CH'])}")
    print("2. Rule chain:")
    chain_id, msg = deploy_chain(tb, keysets, dry)
    print(msg)
    print("3. Root Rule Chain:")
    print(patch_root(tb, chain_id, dry))
    for line in clear_old_ai_alarms(tb, devices, dry):
        print(line)
    print("4. Dashboard:")
    print(deploy_dashboard(tb, dry))
    print("5. DG dashboards (fuel):")
    for line in patch_dg_dashboards(tb, dry):
        print(line)
    print("DRY RUN - nothing changed" if dry else "Done.")


if __name__ == '__main__':
    sys.exit(main())
