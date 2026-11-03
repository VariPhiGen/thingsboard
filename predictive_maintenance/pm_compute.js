// Predictive Maintenance compute script (body of the "PM Compute" transform node).
// Runs every 5 min per device (after dedup). Inputs:
//   msg                      latest telemetry message of the device (partial payloads are fine)
//   metadata.<key>           latest value of every relevant key as '{"ts":..,"value":..}'
//   metadata.<key> (FIRE)    pressure channels: JSON array of the recent values
//   metadata.ss_pm_state     engine state (EWMA trends, hysteresis, counters) from the previous run
//   metadata.ss_pm_baseline  per-key statistics from history (written by deploy_pm.py)
//   metadata.ss_pm_config    per-device configuration (server attribute pm_config):
//                              kind    DG | LT | RO | FIRE
//                              engine  scoring, hysteresis, staleness, invalid codes, time zone
//                              limits  telemetry keys, valid ranges and every threshold of the checks
// No threshold is defined in this script: a limit that is not configured skips its check and is reported as an
// INFO item; without engine/limits the device is reported as NOT CONFIGURED.
// Output msg: pm_* telemetry (plus the legacy DG keys used by the DG dashboards).
// Output metadata: pm_state_out (saved back as server attribute), pm_alarm (CRITICAL|WARNING|OK|SKIP)
// and the alarm/LLM fields.
// Written in ES5 with braces on every block. The ThingsBoard Nashorn sandbox checks loops with a regex and
// rejects the whole script when the words f-o-r, w-h-i-l-e or d-o appear in strings or comments, so
// texts avoid them (test_pm_compute.js enforces this).

var NOW = Number(metadata.ts);
if (!isFinite(NOW) || NOW <= 0) NOW = Date.now();
var HOUR = 3600000;
var DAY = 24 * HOUR;

function parseJson(s, d) {
  if (s === null || s === undefined || s === '') return d;
  if (typeof s === 'object') return s;
  try { return JSON.parse(s); } catch (e) { return d; }
}
var S = parseJson(metadata.ss_pm_state, {});
var BASE = parseJson(metadata.ss_pm_baseline, {});
var CFG = parseJson(metadata.ss_pm_config, {});
var E = CFG.engine || null;
var L = CFG.limits || null;
var kind = CFG.kind || '';
if (!S.m) S.m = {};
if (!S.sev) S.sev = {confirmed: 'OK', cand: 'OK', n: 0};
var name = metadata.deviceName || 'Device';
var out = {};

// ---------- configuration access ----------
var missing = [];
function path(obj, p) {
  var parts = p.split('.');
  var cur = obj;
  for (var i = 0; i < parts.length; i++) {
    if (cur === null || cur === undefined || typeof cur !== 'object') return undefined;
    cur = cur[parts[i]];
  }
  return cur;
}
// Configured value (any type) or undefined; a missing value is recorded once.
function cfgv(p) {
  var v = path(L, p);
  if (v === undefined || v === null || v === '') {
    if (missing.indexOf(p) < 0) missing.push(p);
    return undefined;
  }
  return v;
}
// Configured number or null (recorded as missing).
function lim(p) {
  var v = cfgv(p);
  if (v === undefined) return null;
  var n = Number(v);
  if (!isFinite(n)) {
    if (missing.indexOf(p) < 0) missing.push(p);
    return null;
  }
  return n;
}
// Optional number (not an error when absent, e.g. the rated kW of a DG).
function opt(p) {
  var v = path(L, p);
  if (v === undefined || v === null || v === '') return null;
  var n = Number(v);
  return isFinite(n) ? n : null;
}
var ENGINE_KEYS = ['stale_minutes', 'escalate_evals', 'relax_evals', 'penalty.CRITICAL', 'penalty.WARNING', 'penalty.INFO',
                   'health_bands.ok_min', 'health_bands.warning_min', 'risk_max_pct', 'invalid_codes', 'invalid_at_or_above',
                   'trend.reset_hours', 'trend.slope_smoothing', 'trend.min_interval_minutes', 'trend.min_evals',
                   'trend.slope_warmup_evals', 'rul_max_days', 'ai_summary_max_age_minutes', 'timezone_offset_minutes', 'max_issues'];
var engineMissing = [];
if (E) {
  for (var ek = 0; ek < ENGINE_KEYS.length; ek++) {
    var evv = path(E, ENGINE_KEYS[ek]);
    if (evv === undefined || evv === null || evv === '') engineMissing.push('engine.' + ENGINE_KEYS[ek]);
  }
}
var configured = !!(E && L && kind) && !engineMissing.length;

if (!configured) {
  var why = !kind ? 'equipment kind' : (!E ? 'engine settings' : (!L ? 'limits' : engineMissing.join(', ')));
  out.pm_status = 'NOT CONFIGURED';
  out.pm_mode = kind || 'UNKNOWN';
  out.pm_severity = 'NO DATA';
  out.pm_severity_raw = 'NO DATA';
  out.pm_health_score = '--';
  out.pm_risk_pct = '--';
  out.pm_rul_days = '--';
  out.pm_issue_count = 0;
  out.pm_top_issue = 'None';
  out.pm_data_quality_pct = '--';
  out.pm_issues = JSON.stringify([{sev: 'INFO', text: 'Predictive maintenance is not configured (' + why + ')',
    action: 'Configure this equipment in Maintenance Management > Settings > Predictive maintenance.'}]);
  out.pm_summary = out.pm_summary_auto = name + ': predictive maintenance is not configured (' + why + ').';
  out.pm_recommendation = out.pm_recommendation_auto = 'Configure this equipment in Maintenance Management > Settings > Predictive maintenance.';
  out.pm_summary_source = 'rules';
  metadata.pm_state_out = JSON.stringify(S);
  metadata.pm_alarm = 'SKIP';
  metadata.pm_alarm_message = out.pm_summary;
  metadata.pm_alarm_action = out.pm_recommendation;
  metadata.pm_health = '--';
  metadata.pm_risk = '--';
  return {msg: out, metadata: metadata, msgType: 'POST_TELEMETRY_REQUEST'};
}

var STALE_MS = Number(E.stale_minutes) * 60000;
var TZ_MS = Number(E.timezone_offset_minutes) * 60000;
var INVALID = E.invalid_codes;
var INVALID_MIN = Number(E.invalid_at_or_above);

// ---------- value access ----------
// Returns {v, ts} of the newest known value of key (message first, then fetched latest), or null.
function raw(key) {
  if (!key) return null;
  if (msg && msg[key] !== undefined && msg[key] !== null) return {v: msg[key], ts: NOW};
  var m = metadata[key];
  if (m === undefined || m === null || m === '') return null;
  var o = parseJson(m, null);
  if (o && typeof o === 'object' && !(o instanceof Array) && o.ts !== undefined) return {v: o.value, ts: Number(o.ts)};
  return {v: m, ts: NOW};
}
function fresh(key) {
  var r = raw(key);
  if (!r || NOW - r.ts > STALE_MS) return null;
  return r;
}
function key(name) { return cfgv('keys.' + name); }
// Numeric reading that is fresh, not a controller "not available" code and inside the configured valid range.
function numKey(k, rangePath) {
  var rg = cfgv(rangePath);
  if (!rg || !(rg instanceof Array) || rg.length !== 2) return null;
  var r = fresh(k);
  if (!r) return null;
  var v = r.v;
  if (v === null || v === '' || typeof v === 'boolean') return null;
  var n = Number(v);
  if (!isFinite(n) || INVALID.indexOf(n) >= 0 || n >= INVALID_MIN) return null;
  if (n < Number(rg[0]) || n > Number(rg[1])) return null;
  return n;
}
function num(name) { return numKey(key(name), 'valid.' + name); }
function bool(k) {
  var r = fresh(k);
  if (!r) return null;
  var v = r.v;
  if (v === true || v === 1 || v === '1' || ('' + v).toLowerCase() === 'true') return true;
  if (v === false || v === 0 || v === '0' || ('' + v).toLowerCase() === 'false') return false;
  return null;
}
function str(k) {
  var r = fresh(k);
  return r ? ('' + r.v) : null;
}
// Days since a known sensor last reported, when its newest value is older than the staleness limit (else null).
function staleDays(k) {
  var r = raw(k);
  if (!r || NOW - r.ts <= STALE_MS) return null;
  return (NOW - r.ts) / DAY;
}
function ageText(days) {
  if (days >= 1) return Math.round(days) + ' day' + (Math.round(days) === 1 ? '' : 's');
  return Math.max(1, Math.round(days * 24)) + ' h';
}
function base(k, stat) {
  var b = BASE[k];
  if (!b || b[stat] === undefined || b[stat] === null) return null;
  return Number(b[stat]);
}
function r1(x) { return Math.round(x * 10) / 10; }
function r2(x) { return Math.round(x * 100) / 100; }
var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function pad2(x) { return (x < 10 ? '0' : '') + x; }
// Site-local 'D Mon HH:MM' of a timestamp
function localStamp(ts) {
  var d = new Date(ts + TZ_MS);
  return d.getUTCDate() + ' ' + MONTHS[d.getUTCMonth()] + ' ' + pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes());
}
function localDay() { return Math.floor((NOW + TZ_MS) / DAY); }

// ---------- trends ----------
// EWMA level + EWMA slope (units per hour). Returns {f, s, n}. alpha: level smoothing.
function trend(tname, value, alpha) {
  var t = S.m[tname];
  if (!t || NOW - t.t > Number(E.trend.reset_hours) * HOUR || !isFinite(t.f)) {
    t = {f: value, s: 0, t: NOW, n: 1};
  } else {
    var dtH = (NOW - t.t) / HOUR;
    if (dtH <= 0) return t;
    var f = t.f + alpha * (value - t.f);
    if (dtH >= Number(E.trend.min_interval_minutes) / 60) {
      var inst = (f - t.f) / dtH;
      t.s = t.n < Number(E.trend.slope_warmup_evals) ? inst : t.s + Number(E.trend.slope_smoothing) * (inst - t.s);
    }
    t.f = f;
    t.t = NOW;
    t.n = Math.min(t.n + 1, 100000);
  }
  S.m[tname] = t;
  return t;
}
// Hours until the trend reaches limit (null when it is not heading there or the trend is too young).
function hoursTo(t, limit, minEvals) {
  if (!t || t.n < (minEvals || Number(E.trend.min_evals)) || !isFinite(t.s) || t.s === 0) return null;
  var h = (limit - t.f) / t.s;
  if (h <= 0 || h > Number(E.rul_max_days) * 24) return null;
  return h;
}

// ---------- issues ----------
var issues = [];
var rulHours = [];   // calendar hours until a predicted threshold breach
var expected = 0, present = 0;
function add(sev, text, action, penalty) {
  var p = penalty !== undefined && penalty !== null ? penalty : Number(E.penalty[sev]);
  issues.push({sev: sev, text: text, action: action || '', p: p});
}
function expect(v) { expected++; if (v !== null && v !== undefined) present++; return v; }
var mode = '';

// =====================================================================================
if (kind === 'DG') {
  var rpm = num('rpm');
  var status = str(key('status'));
  var runRpm = lim('running_rpm');
  var running = status === cfgv('running_status') || (rpm !== null && runRpm !== null && rpm > runRpm);
  mode = running ? 'RUNNING' : 'STANDBY';
  out.pm_dg_mode = mode;

  // Battery
  var bv = expect(num('battery'));
  if (bv !== null) {
    out.pm_battery_v = bv;
    var bCrit = lim('battery.crit_v'), bWarn = lim('battery.warn_v'), bFloor = lim('battery.trend_floor_v'), bOver = lim('battery.overcharge_v');
    if (!running) {
      var bt = trend('battery_off', bv, lim('battery.trend_alpha') || 0);
      // After a run the charger lifts the battery above its float level and it settles back over hours: that fall is
      // not a battery fault, so the falling trend only counts below the battery's normal standby (float) level.
      var bFloat = lim('battery.float_v');
      if (bFloat !== null && bt.f >= bFloat) bt.s = 0;
      if (bCrit !== null && bv < bCrit) add('CRITICAL', 'Battery ' + bv + ' V on standby (min ' + bCrit + ' V) - DG may fail to crank', 'Check battery charger and battery health now; arrange a replacement battery.');
      else if (bWarn !== null && bv < bWarn) add('WARNING', 'Battery low on standby: ' + bv + ' V', 'Check the battery charger output and electrolyte/terminals.');
      var fall = lim('battery.falling_v_per_h'), within = lim('battery.warn_within_h');
      if (bFloor !== null && fall !== null && bFloat !== null) {
        var hb = hoursTo(bt, bFloor, lim('battery.trend_min_evals'));
        if (hb !== null && bt.s < -fall) {
          rulHours.push(hb);
          if (within !== null && hb < within && (bWarn === null || bv >= bWarn)) add('WARNING', 'Battery falling ' + r2(-bt.s * 24) + ' V/day, reaches ' + bFloor + ' V in ~' + Math.round(hb) + ' h', 'Battery charger may be faulty - inspect before the next DG test.');
        }
      }
    } else if (bOver !== null && bv > bOver) {
      add('WARNING', 'Battery overcharging at ' + bv + ' V with the engine running', 'Check the charging alternator regulator.');
    }
  }

  // Fuel: filtered level, burn rate and autonomy come from the DG Fuel node (dg_fuel.js)
  var fuel = numKey(key('fuel_pct'), 'valid.fuel');
  if (fuel === null) fuel = numKey(key('fuel_raw'), 'valid.fuel');
  expect(fuel);
  var fLow = lim('fuel.low_pct'), fCrit = lim('fuel.critical_pct'), fFull = lim('fuel.full_pct');
  if (str(key('fuel_status')) === cfgv('fuel_sensor_error_status')) add('INFO', 'Fuel level sensor not reporting', 'Check the fuel sender wiring and the controller input.', lim('fuel.sensor_error_penalty'));
  if (fuel !== null) {
    out.pm_fuel_pct = fuel;
    var fTxt = fFull !== null && fuel >= fFull ? 'FULL (>=100%)' : fuel + '%';
    if (fCrit !== null && fuel < fCrit) add('CRITICAL', 'Fuel very low: ' + fTxt, 'Refuel immediately - backup runtime is at risk.');
    else if (fLow !== null && fuel < fLow) add('WARNING', 'Fuel low: ' + fTxt, 'Schedule refuelling.');
    var hf = num('fuel_runtime');
    if (hf !== null) {
      out.pm_fuel_runtime_h = hf;
      if (running) {
        rulHours.push(hf);
        var rc = lim('fuel.runtime_crit_h'), rw = lim('fuel.runtime_warn_h');
        if (rc !== null && hf < rc) add('CRITICAL', 'Fuel runs out in ~' + hf + ' h at current burn rate', 'Refuel now or transfer load.');
        else if (rw !== null && hf < rw) add('WARNING', 'Fuel lasts ~' + hf + ' h at current burn rate', 'Arrange refuelling.');
      } else {
        var req = opt('fuel.required_autonomy_h');
        if (req !== null && hf < req) add('WARNING', 'Fuel autonomy ' + hf + ' h is below the required ' + req + ' h', 'Top up the tank to restore the required backup runtime.');
      }
    }
  }

  // Running-only engine and alternator checks
  if (running) {
    var ct = expect(num('coolant'));
    if (ct !== null) {
      var cW = lim('coolant.warn_c'), cC = lim('coolant.crit_c'), clamp = cfgv('coolant.predict_clamp');
      var ctt = trend('coolant_run', ct, lim('coolant.trend_alpha') || 0);
      var pred = ctt.n >= Number(E.trend.slope_warmup_evals) ? ctt.f + ctt.s : ct;
      if (clamp && clamp.length === 2) out.predicted_coolant_1h = r1(Math.max(Number(clamp[0]), Math.min(Number(clamp[1]), pred)));
      if (cC !== null && ct >= cC) add('CRITICAL', 'Coolant ' + ct + ' C (limit ' + cC + ' C)', 'Reduce load and inspect radiator, fan belt and coolant level.');
      else if (cW !== null && ct >= cW) add('WARNING', 'Coolant high: ' + ct + ' C', 'Inspect radiator and coolant level.');
      else if (cC !== null && pred >= cC) add('WARNING', 'Coolant rising, predicted ' + r1(pred) + ' C in 1 h', 'Inspect radiator airflow and coolant level.');
      if (cC !== null) {
        var hc = hoursTo(ctt, cC, lim('coolant.rul_min_evals'));
        if (hc !== null) rulHours.push(hc);
      }
    }
    var op = expect(num('oil'));
    var oMin = lim('oil.min_rpm');
    if (op !== null && rpm !== null && oMin !== null && rpm > oMin) {
      var oC = lim('oil.crit_kpa'), oW = lim('oil.warn_kpa');
      if (oC !== null && op < oC) add('CRITICAL', 'Oil pressure ' + op + ' kPa at ' + rpm + ' rpm', 'Stop the DG and check oil level / oil pump.');
      else if (oW !== null && op < oW) add('WARNING', 'Oil pressure low: ' + op + ' kPa', 'Check oil level and filter.');
    }
    var fq = num('frequency');
    var fN = lim('frequency.nominal_hz');
    if (fq !== null && fN !== null) {
      var df = Math.abs(fq - fN), fC = lim('frequency.crit_dev_hz'), fW = lim('frequency.warn_dev_hz');
      if (fC !== null && df > fC) add('CRITICAL', 'Frequency ' + fq + ' Hz', 'Check governor / engine speed control.');
      else if (fW !== null && df > fW) add('WARNING', 'Frequency off-nominal: ' + fq + ' Hz', 'Check governor settings.');
    }
    var vv = num('voltage');
    var vn = lim('voltage.nominal_v');
    if (vv !== null && vn !== null) {
      var dv = Math.abs(vv - vn) / vn * 100, vC = lim('voltage.crit_pct'), vW = lim('voltage.warn_pct');
      if (vC !== null && dv > vC) add('CRITICAL', 'Output voltage ' + vv + ' V (nominal ' + vn + ' V)', 'Check the alternator voltage regulator (AVR).');
      else if (vW !== null && dv > vW) add('WARNING', 'Output voltage ' + vv + ' V off nominal', 'Check the alternator voltage regulator (AVR) settings.');
    }
    var pf = num('power_factor');
    var pkw = num('power');
    var pfMin = lim('power_factor.min'), pfKw = lim('power_factor.min_kw');
    if (pf !== null && pkw !== null && pfMin !== null && pfKw !== null && pkw > pfKw && pf < pfMin) add('WARNING', 'Low power factor ' + pf + ' at ' + pkw + ' kW', 'Review load / capacitor bank.');
    var ratedKw = opt('load.rated_kw');
    if (pkw !== null && ratedKw) {
      var load = pkw / ratedKw * 100, lC = lim('load.crit_pct'), lW = lim('load.warn_pct');
      out.pm_load_pct = r1(load);
      if (lC !== null && load > lC) add('CRITICAL', 'DG overloaded: ' + r1(load) + '% of ' + ratedKw + ' kW', 'Shed load immediately.');
      else if (lW !== null && load > lW) add('WARNING', 'DG load high: ' + r1(load) + '%', 'Avoid adding load.');
    }
  } else {
    out.predicted_coolant_1h = '--';
  }

  // Controller alarm
  // Controller alarm (latched on the panel until it is reset). S.ca = {code, since}: when the alarm first became active.
  var ca = num('common_alarm');
  if (ca !== null && ca !== 0) {
    if (!S.ca || !S.ca.since) S.ca = {since: NOW};
    S.ca.code = ca;
    var names = L && L.alarm_codes && typeof L.alarm_codes === 'object' ? L.alarm_codes : {};
    var caName = names['' + ca] ? names['' + ca] + ' (code ' + ca + ')' : 'code ' + ca;
    add('WARNING', 'Controller alarm active' + (S.ca.since ? ' since ' + localStamp(S.ca.since) : '') + ' - ' + caName,
      'Check the alarm list on the DG control panel, correct the cause and reset the alarm on the panel.');
  } else if (ca === 0) {
    S.ca = null;
  }

  // Service due (run hours), only from the real last-service record (closed preventive work order)
  var rh = expect(num('run_hours'));
  var lastSvc = opt('service.last_service_run_hours');
  var interval = lim('service.interval_h');
  if (rh !== null && lastSvc !== null && interval !== null) {
    var due = lastSvc + interval - rh;
    out.pm_service_due_h = r1(due);
    out.rul_hours = Math.max(0, r1(due));
    var sOver = lim('service.overdue_crit_h'), sSoon = lim('service.due_soon_h');
    if (sOver !== null && due < -sOver) add('CRITICAL', 'Service overdue by ' + Math.round(-due) + ' run-hours', 'Carry out the scheduled service (oil, filters) now.');
    else if (due < 0) add('WARNING', 'Service overdue by ' + Math.round(-due) + ' run-hours', 'Schedule the service and close it as a preventive work order in Maintenance Management.');
    else if (sSoon !== null && due < sSoon) add('INFO', 'Service due in ' + Math.round(due) + ' run-hours', 'Plan the next service.', lim('service.due_soon_penalty'));
  } else {
    out.pm_service_due_h = '--';
    out.rul_hours = '--';
    if (lastSvc === null) add('INFO', 'Service schedule not set up - last service not yet logged', 'Record the last DG service as a completed preventive work order in Maintenance Management (Reports & Maintenance dashboard) to start the service countdown.', 0);
  }
  // Exercise (standby DG must run regularly). The controller sometimes nudges the run-hour counter with the
  // engine stopped, so only a rise of at least exercise.min_run_increase_h counts as a run.
  var minInc = lim('exercise.min_run_increase_h');
  if (rh !== null && minInc !== null) {
    if (running || S.lastRh === undefined || rh < S.lastRh) {
      S.lastRh = rh;
    } else if (rh >= S.lastRh + minInc) {
      S.lastRunTs = NOW;
      S.lastRh = rh;
    }
  }
  if (running) S.lastRunTs = NOW;
  var exDays = lim('exercise.days'), exLong = lim('exercise.long_factor');
  if (S.lastRunTs) {
    var idleDays = (NOW - S.lastRunTs) / DAY;
    out.pm_days_since_run = r1(idleDays);
    if (exDays !== null && exLong !== null && idleDays > exDays * exLong) add('WARNING', 'DG idle ' + Math.round(idleDays) + ' days', 'Run a no-load/load test to confirm standby readiness.', lim('exercise.long_penalty'));
    else if (exDays !== null && idleDays > exDays) add('WARNING', 'DG idle ' + Math.round(idleDays) + ' days (test every ' + exDays + ' days)', 'Schedule the weekly test run.', lim('exercise.penalty'));
  }

  // Start counter (many starts per day = failed/short starts)
  var st = num('starts');
  if (st !== null) {
    var day = localDay();
    if (!S.starts || S.starts.day !== day) S.starts = {day: day, base: st};
    var startsToday = st - S.starts.base;
    out.pm_starts_today = startsToday;
    var maxStarts = lim('starts.max_per_day');
    if (maxStarts !== null && startsToday > maxStarts) add('WARNING', startsToday + ' engine starts today', 'Check failed or short starts (battery, starter, fuel).');
  }

// =====================================================================================
} else if (kind === 'LT') {
  mode = 'LT';
  var sfx = cfgv('feeder_suffix') || {};
  var feeders = [];
  if (sfx.voltage) {
    for (var mk in metadata) {
      if (mk.indexOf('ss_') !== 0 && mk.length > sfx.voltage.length && mk.slice(-sfx.voltage.length) === sfx.voltage) feeders.push(mk.slice(0, -sfx.voltage.length));
    }
  }
  feeders.sort();
  var fsum = {};
  for (var i = 0; i < feeders.length; i++) {
    var fd = feeders[i];
    var label = fd.replace(/_/g, ' ');
    var V = numKey(fd + sfx.voltage, 'valid.voltage');
    var I = sfx.current ? numKey(fd + sfx.current, 'valid.current') : null;
    var P = sfx.power ? numKey(fd + sfx.power, 'valid.power') : null;
    var F = sfx.frequency ? numKey(fd + sfx.frequency, 'valid.frequency') : null;
    expect(V);
    if (V === null) {
      fsum[fd] = 'NO DATA';
      add('INFO', label + ': meter not reporting', 'Check the energy meter of ' + label + ' and its communication cable.', lim('no_data_penalty'));
      continue;
    }
    var fstate = 'OK';
    var nominal = lim('nominal_v.' + fd);
    if (nominal !== null) {
      var vt = trend(fd + '_v', V, lim('voltage.trend_alpha') || 0);
      var dev = (vt.f - nominal) / nominal * 100, lvC = lim('voltage.crit_pct'), lvW = lim('voltage.warn_pct');
      if (lvC !== null && Math.abs(dev) > lvC) { add('CRITICAL', label + ' voltage ' + r1(vt.f) + ' V (' + r1(dev) + '% from ' + nominal + ' V)', 'Check supply / transformer tap and connected equipment.'); fstate = 'CRITICAL'; }
      else if (lvW !== null && Math.abs(dev) > lvW) { add('WARNING', label + ' voltage ' + r1(vt.f) + ' V (' + r1(dev) + '%)', 'Monitor supply voltage; check transformer tap.'); fstate = 'WARNING'; }
    }
    var lfN = lim('frequency.nominal_hz');
    if (F !== null && lfN !== null) {
      var ftr = trend(fd + '_f', F, lim('frequency.trend_alpha') || 0);
      var dfq = Math.abs(ftr.f - lfN), lfC = lim('frequency.crit_dev_hz'), lfW = lim('frequency.warn_dev_hz');
      if (lfC !== null && dfq > lfC) { add('CRITICAL', label + ' frequency ' + r2(ftr.f) + ' Hz', 'Check supply source.'); fstate = 'CRITICAL'; }
      else if (lfW !== null && dfq > lfW) { add('WARNING', label + ' frequency ' + r2(ftr.f) + ' Hz', 'Monitor supply frequency.'); if (fstate === 'OK') fstate = 'WARNING'; }
    }
    if (I !== null) {
      var it = trend(fd + '_i', I, lim('current.trend_alpha') || 0);
      var rated = opt('rated_a.' + fd);
      var p95 = base(fd + sfx.current, 'p95');
      if (rated) {
        var lp = it.f / rated * 100, cC2 = lim('current.load_crit_pct'), cW2 = lim('current.load_warn_pct');
        if (cC2 !== null && lp > cC2) { add('CRITICAL', label + ' overloaded: ' + Math.round(it.f) + ' A (' + Math.round(lp) + '% of ' + rated + ' A)', 'Shed or redistribute load.'); fstate = 'CRITICAL'; }
        else if (cW2 !== null && lp > cW2) { add('WARNING', label + ' load ' + Math.round(lp) + '% of rating', 'Plan load redistribution.'); if (fstate === 'OK') fstate = 'WARNING'; }
      } else {
        var pkF = lim('current.peak_factor'), pkMin = lim('current.peak_min_a'), pkEv = lim('current.peak_min_evals');
        if (p95 !== null && pkF !== null && pkMin !== null && pkEv !== null && p95 > pkMin && it.n >= pkEv && it.f > p95 * pkF) {
          add('WARNING', label + ' current ' + Math.round(it.f) + ' A is ' + Math.round((it.f / p95 - 1) * 100) + '% above its normal peak (' + Math.round(p95) + ' A)', 'Check this feeder: newly added load or a developing fault.');
          if (fstate === 'OK') fstate = 'WARNING';
        }
      }
      // Power factor from P, V, I
      var pfMinI = lim('power_factor.min_current_a'), pfShare = lim('power_factor.min_share_of_peak'), pfMax = lim('power_factor.max_plausible');
      var pf3 = lim('power_factor.three_phase_above_v'), pfLow = lim('power_factor.min');
      if (P !== null && pfMinI !== null && pfShare !== null && pfMax !== null && pf3 !== null && pfLow !== null && I > pfMinI && (p95 === null || I > pfShare * p95)) {
        var kva = (V > pf3 ? Math.sqrt(3) * V * I : V * I) / 1000;
        var pfv = kva > 0 ? Math.abs(P) / kva : null;
        if (pfv !== null && pfv <= pfMax) {
          var pft = trend(fd + '_pf', Math.min(1, pfv), lim('power_factor.trend_alpha') || 0);
          if (pft.n >= (lim('power_factor.min_evals') || 0) && pft.f < pfLow) { add('WARNING', label + ' power factor ' + r2(pft.f), 'Check capacitor bank / reactive load.', lim('power_factor.penalty')); if (fstate === 'OK') fstate = 'WARNING'; }
        }
      }
    }
    fsum[fd] = fstate;
  }
  out.pm_feeders = JSON.stringify(fsum);

// =====================================================================================
} else if (kind === 'RO') {
  mode = 'RO';
  var tds = expect(num('tds'));
  var med = base(key('tds'), 'median');
  var warnT = lim('tds.warn_ppm'), critT = lim('tds.crit_ppm');
  if (tds !== null) {
    var tt = trend('tds', tds, lim('tds.trend_alpha') || 0);
    out.pm_tds_avg = r1(tt.f);
    if (critT !== null && tt.f > critT) add('CRITICAL', 'Product water TDS ' + Math.round(tt.f) + ' ppm (limit ' + critT + ')', 'Stop drinking-water supply; inspect RO membrane and O-rings.');
    else if (warnT !== null && tt.f > warnT) add('WARNING', 'Product water TDS ' + Math.round(tt.f) + ' ppm (normal ~' + Math.round(med || 0) + ')', 'Clean the RO membrane or plan its replacement.');
    // Long-term TDS trend = least-squares slope of the daily average TDS (local days) over the configured number of
    // completed days; it is reported only with enough days, enough samples per day and a good fit (R2).
    var tDays = lim('tds.trend_days'), tMinDays = lim('tds.trend_min_days'), tMinN = lim('tds.trend_min_samples_per_day'), tR2 = lim('tds.trend_min_r2');
    var slope = null, nDays = 0;
    if (tDays !== null && tMinDays !== null && tMinN !== null && tR2 !== null) {
      var tdsDay = localDay();
      if (!S.tdsDays) S.tdsDays = [];
      var curB = S.tdsDays.length ? S.tdsDays[S.tdsDays.length - 1] : null;
      if (!curB || curB.d !== tdsDay) {
        curB = {d: tdsDay, s: 0, n: 0};
        S.tdsDays.push(curB);
      }
      curB.s += tds;
      curB.n++;
      var keptDays = [];
      for (var di = 0; di < S.tdsDays.length; di++) {
        if (S.tdsDays[di].d > tdsDay - (tDays + 1)) keptDays.push(S.tdsDays[di]);
      }
      S.tdsDays = keptDays;
      var xs = [], ys = [];
      for (var dj = 0; dj < S.tdsDays.length; dj++) {
        var bd = S.tdsDays[dj];
        if (bd.d < tdsDay && bd.n >= tMinN) {
          xs.push(bd.d);
          ys.push(bd.s / bd.n);
        }
      }
      nDays = xs.length;
      if (xs.length >= tMinDays) {
        var mx = 0, my = 0;
        for (var a1 = 0; a1 < xs.length; a1++) {
          mx += xs[a1];
          my += ys[a1];
        }
        mx /= xs.length;
        my /= xs.length;
        var sxy = 0, sxx = 0;
        for (var a2 = 0; a2 < xs.length; a2++) {
          sxy += (xs[a2] - mx) * (ys[a2] - my);
          sxx += (xs[a2] - mx) * (xs[a2] - mx);
        }
        if (sxx > 0) {
          slope = sxy / sxx;
          // Fit quality: a rise-and-fall is not a steady trend, so it is not extrapolated
          var ssTot = 0, ssRes = 0;
          for (var a3 = 0; a3 < xs.length; a3++) {
            var fit = my + slope * (xs[a3] - mx);
            ssRes += (ys[a3] - fit) * (ys[a3] - fit);
            ssTot += (ys[a3] - my) * (ys[a3] - my);
          }
          var fitR2 = ssTot > 0 ? 1 - ssRes / ssTot : 0;
          out.pm_tds_trend_r2 = r2(fitR2);
          if (fitR2 < tR2) slope = null;
        }
      }
    }
    out.pm_tds_trend_ppm_day = slope === null ? '--' : r2(slope);
    out.pm_tds_trend_days = nDays;
    var tMinSlope = lim('tds.trend_min_ppm_per_day'), tWithin = lim('tds.warn_within_days');
    if (slope !== null && warnT !== null && tMinSlope !== null && slope > tMinSlope && tt.f < warnT) {
      var ht = (warnT - tt.f) / slope * 24;
      if (ht > 0 && ht <= Number(E.rul_max_days) * 24) {
        rulHours.push(ht);
        if (tWithin !== null && ht < tWithin * 24) add('WARNING', 'TDS rising ' + r1(slope) + ' ppm/day over ' + nDays + ' days - reaches ' + warnT + ' ppm in ~' + Math.round(ht / 24) + ' days', 'Plan membrane cleaning / replacement.', lim('tds.trend_penalty'));
      }
    }
  }
  var tc = expect(num('temperature'));
  if (tc !== null) {
    var tcC = lim('temperature.crit_c'), tcW = lim('temperature.warn_c');
    if (tcC !== null && tc > tcC) add('CRITICAL', 'Water temperature ' + tc + ' C (membrane max ' + tcC + ' C)', 'Stop the RO to protect the membrane.');
    else if (tcW !== null && tc > tcW) add('WARNING', 'Water temperature high: ' + tc + ' C', 'Check feed water source / plant room ventilation.');
  }
  var ph = num('ph');
  if (raw(key('ph')) !== null) expect(ph);
  if (ph !== null) {
    var pcl = lim('ph.crit_low'), pch = lim('ph.crit_high'), pwl = lim('ph.warn_low'), pwh = lim('ph.warn_high');
    if ((pcl !== null && ph < pcl) || (pch !== null && ph > pch)) add('CRITICAL', 'pH ' + ph, 'Stop supply and check dosing.');
    else if ((pwl !== null && ph < pwl) || (pwh !== null && ph > pwh)) add('WARNING', 'pH out of range: ' + ph, 'Check dosing / remineralisation.');
  }
  var pr = num('pressure');
  if (raw(key('pressure')) !== null) expect(pr);
  var watch = cfgv('sensors_to_watch') || {};
  for (var wk in watch) {
    var sdays = staleDays(key(wk));
    if (sdays !== null) add('INFO', watch[wk] + ' not reporting (last reading ' + ageText(sdays) + ' ago)', 'Check the ' + watch[wk] + ' and its wiring; related checks resume once it reports again.', lim('sensor_offline_penalty'));
  }
  var prMed = base(key('pressure'), 'median'), prDev = lim('pressure.dev_pct');
  if (pr !== null && prMed && prDev !== null) {
    var prt = trend('pressure', pr, lim('pressure.trend_alpha') || 0);
    var pd = (prt.f - prMed) / prMed * 100;
    if (Math.abs(pd) > prDev) add('WARNING', 'Pressure ' + r1(prt.f) + ' bar (' + Math.round(pd) + '% from normal ' + prMed + ')', pd > 0 ? 'Membrane/pre-filter may be fouling - check differential pressure.' : 'Check pump and pre-filters.');
  }
  if (bool(key('tds_online')) === false) add('WARNING', 'TDS sensor offline', 'Check the TDS sensor connection.');
  if (bool(key('flow_online')) === false) add('INFO', 'Flow sensor offline - water flow checks unavailable', 'Repair the flow sensor to restore water flow and membrane checks.', lim('sensor_offline_penalty'));

// =====================================================================================
} else if (kind === 'FIRE') {
  mode = 'FIRE';
  var ignore = cfgv('ignore_channels') || [];
  var pats = cfgv('channel_patterns') || [];
  var res = [];
  for (var pi = 0; pi < pats.length; pi++) {
    res.push(new RegExp(pats[pi]));
  }
  var chans = [];
  for (var ck in metadata) {
    for (var ri = 0; ri < res.length; ri++) {
      var cm = res[ri].exec(ck);
      if (cm) {
        chans.push({key: ck, n: Number(cm[1])});
        break;
      }
    }
  }
  chans.sort(function (a, b) { return a.n - b.n; });
  var flapN = lim('flap_changes');
  var lowList = [], flapList = [], okCount = 0;
  for (var c = 0; c < chans.length; c++) {
    var ch = chans[c];
    if (ignore.indexOf(ch.n) >= 0) continue;
    var hist = parseJson(metadata[ch.key], null);
    var vals = [];
    if (hist instanceof Array) {
      for (var j = 0; j < hist.length; j++) {
        var hv = hist[j] && hist[j].value !== undefined ? hist[j].value : hist[j];
        vals.push(hv === true || hv === 1 || hv === '1' || ('' + hv).toLowerCase() === 'true');
      }
    }
    if (!vals.length) continue;   // no data in the window: channel not in use on this device
    expect(true);
    var changes = 0;
    for (var q = 1; q < vals.length; q++) {
      if (vals[q] !== vals[q - 1]) changes++;
    }
    if (flapN !== null && changes >= flapN) flapList.push(ch.n + ' (' + changes + ' changes)');
    else if (!vals[vals.length - 1]) lowList.push(ch.n);
    else okCount++;
  }
  out.pm_cylinders_ok = okCount;
  out.pm_cylinders_low = lowList.length;
  out.pm_cylinders_unstable = flapList.length;
  var maxPen = lim('max_penalty'), win = lim('window_minutes');
  if (lowList.length) add('WARNING', 'Low pressure on cylinder(s) ' + lowList.join(', '), 'Inspect and recharge these cylinders; check the pressure switch if the cylinder gauge reads normal.', Math.min(maxPen || 0, (lim('low_penalty_per_channel') || 0) * lowList.length));
  if (flapList.length) add('WARNING', 'Unstable pressure signal on cylinder(s) ' + flapList.join(', ') + ' in the last ' + win + ' min', 'Check the pressure switch, its wiring and connections.', Math.min(maxPen || 0, (lim('flap_penalty_per_channel') || 0) * flapList.length));
  var relays = cfgv('relay_keys') || [];
  for (var rr = 0; rr < relays.length; rr++) {
    var rl = relays[rr].replace(/_online$/, '').replace(/_/g, ' ');
    if (bool(relays[rr]) === false) add('WARNING', rl.charAt(0).toUpperCase() + rl.slice(1) + ' offline', 'Check the relay module power / network.');
  }
} else {
  mode = 'UNKNOWN';
}

if (missing.length) add('INFO', 'Some checks are not configured: ' + missing.slice(0, 8).join(', ') + (missing.length > 8 ? ' (+' + (missing.length - 8) + ' more)' : ''),
  'Set these limits in Maintenance Management > Settings > Predictive maintenance.', 0);

// ---------- scoring ----------
var rawSev = 'OK', penalty = 0;
for (var x = 0; x < issues.length; x++) {
  penalty += Number(issues[x].p) || 0;
  if (issues[x].sev === 'CRITICAL') rawSev = 'CRITICAL';
  else if (issues[x].sev === 'WARNING' && rawSev !== 'CRITICAL') rawSev = 'WARNING';
}
var noData = expected > 0 && present === 0;
var score = Math.max(0, 100 - penalty);
// Health bands follow severity: OK >= ok_min, WARNING >= warning_min, CRITICAL below
var okMin = Number(E.health_bands.ok_min), warnMin = Number(E.health_bands.warning_min);
if (rawSev === 'CRITICAL') score = Math.min(score, warnMin - 1);
else if (rawSev === 'WARNING') score = Math.max(warnMin, Math.min(score, okMin - 1));
else score = Math.max(okMin, score);

// Hysteresis on severity
var RANK = {OK: 0, WARNING: 1, CRITICAL: 2};
var sv = S.sev;
if (!noData) {
  if (rawSev === sv.confirmed) { sv.cand = rawSev; sv.n = 0; }
  else {
    if (sv.cand === rawSev) sv.n++; else { sv.cand = rawSev; sv.n = 1; }
    var need = RANK[rawSev] > RANK[sv.confirmed] ? Number(E.escalate_evals) : Number(E.relax_evals);
    if (sv.n >= need) { sv.confirmed = rawSev; sv.n = 0; }
  }
}
var sev = sv.confirmed;

issues.sort(function (a, b) { return (RANK[b.sev] || 0) - (RANK[a.sev] || 0) || b.p - a.p; });
var real = [];
for (var y = 0; y < issues.length; y++) {
  if (issues[y].sev !== 'INFO') real.push(issues[y]);
}
var top = real.length ? real[0] : null;

var rul = null;
for (var z = 0; z < rulHours.length; z++) {
  if (rul === null || rulHours[z] < rul) rul = rulHours[z];
}

var autoSummary, autoAction;
if (noData) {
  autoSummary = name + ': no fresh telemetry in the last ' + E.stale_minutes + ' min - predictive checks paused.';
  autoAction = 'Check gateway power, network and meter link.';
} else if (!real.length) {
  var MODE_LABEL = {RUNNING: 'running', STANDBY: 'standby', LT: 'LT panel feeders', RO: 'RO plant', FIRE: 'fire suppression'};
  autoSummary = name + ' (' + (MODE_LABEL[mode] || mode.toLowerCase()) + '): all monitored parameters within normal limits.';
  autoAction = issues.length ? issues[0].action : 'No action needed; continue routine monitoring.';
} else {
  var parts = [];
  for (var w = 0; w < real.length && w < 3; w++) {
    parts.push(real[w].text);
  }
  autoSummary = name + ': ' + parts.join('; ') + (real.length > 3 ? ' (+' + (real.length - 3) + ' more)' : '') + '.';
  autoAction = top.action;
}

out.pm_status = noData ? 'NO DATA' : 'ACTIVE';
out.pm_mode = mode;
out.pm_health_score = noData ? '--' : score;
out.pm_risk_pct = noData ? '--' : Math.max(0, Math.min(Number(E.risk_max_pct), 100 - score));
out.pm_severity = noData ? 'NO DATA' : sev;
out.pm_severity_raw = rawSev;
out.pm_rul_days = rul === null ? '--' : r1(rul / 24);
out.pm_issue_count = real.length;
out.pm_top_issue = top ? top.text : 'None';
out.pm_data_quality_pct = expected ? Math.round(present / expected * 100) : 100;
var il = [], maxIssues = Number(E.max_issues);
for (var u = 0; u < issues.length && u < maxIssues; u++) {
  il.push({sev: issues[u].sev, text: issues[u].text, action: issues[u].action});
}
out.pm_issues = JSON.stringify(il);
out.pm_summary_auto = autoSummary.substring(0, 300);
out.pm_recommendation_auto = autoAction.substring(0, 300);

// Template summary stands in until the LLM writes one, and whenever the facts behind the last LLM text
// change: severity, presence of a predicted RUL, or the issues and their actions (numbers ignored, so live readings
// inside an issue text keep the LLM text until the next AI summary).
var sigParts = [out.pm_severity, out.pm_rul_days === '--' ? 'norul' : 'rul'];
for (var g = 0; g < issues.length; g++) {
  sigParts.push(issues[g].sev + ':' + (issues[g].text + ' / ' + issues[g].action).replace(/[0-9.,+-]+/g, '#'));
}
var sig = sigParts.join('|');
var llm = raw('pm_summary');
var llmStale = !llm || NOW - llm.ts > Number(E.ai_summary_max_age_minutes) * 60000 || S.lastSev !== out.pm_severity || S.lastSig !== sig;
S.lastSig = sig;
if (llmStale) {
  out.pm_summary = out.pm_summary_auto;
  out.pm_recommendation = out.pm_recommendation_auto;
  out.pm_summary_source = 'rules';
}
S.lastSev = out.pm_severity;

// Legacy keys read by the DG dashboards
if (kind === 'DG') {
  out.health_score = out.pm_health_score;
  out.failure_risk_pct = out.pm_risk_pct;
  out.severity = out.pm_severity;
  out.anomaly = !noData && sev !== 'OK';
  if (out.rul_hours === undefined) out.rul_hours = '--';
  out.ai_mode = 'hybrid';
  out.ai_status = noData ? 'PAUSED' : 'ACTIVE';
  out.ai_reason = noData ? 'No fresh telemetry' : (mode === 'RUNNING' ? 'Running checks: engine, alternator, fuel, battery' : 'Standby checks: battery, fuel, service, exercise');
  if (llmStale) {
    out.summary = out.pm_summary;
    out.maintenance_recommendation = out.pm_recommendation;
  }
}

S.v = 1;
S.t = NOW;
metadata.pm_state_out = JSON.stringify(S);
metadata.pm_alarm = noData ? 'SKIP' : sev;
metadata.pm_alarm_message = autoSummary.substring(0, 400);
metadata.pm_alarm_action = autoAction.substring(0, 300);
metadata.pm_health = '' + out.pm_health_score;
metadata.pm_risk = '' + out.pm_risk_pct;
return {msg: out, metadata: metadata, msgType: 'POST_TELEMETRY_REQUEST'};
