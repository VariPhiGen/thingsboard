// Predictive Maintenance compute script (body of the "PM Compute" transform node).
// Runs every 5 min per device (after dedup). Inputs:
//   msg                      latest telemetry message of the device (partial payloads are fine)
//   metadata.<key>           latest value of every relevant key as '{"ts":..,"value":..}'
//   metadata.<key> (FIRE)    pressure channels: JSON array of the last 15 min of values
//   metadata.ss_pm_state     engine state (EWMA trends, hysteresis, counters) from the previous run
//   metadata.ss_pm_baseline  per-key statistics from history (written by deploy_pm.py)
//   metadata.ss_pm_config    per-device settings, editable in ThingsBoard (server attribute pm_config)
// Output msg: pm_* telemetry (plus the legacy DG keys used by the DG dashboards).
// Output metadata: pm_state_out (saved back as server attribute), pm_alarm (CRITICAL|WARNING|OK|SKIP)
// and the alarm/LLM fields.
// Written in ES5 with braces on every block. The ThingsBoard Nashorn sandbox checks loops with a regex and
// rejects the whole script when the words f-o-r, w-h-i-l-e or d-o appear in strings or comments, so
// texts avoid them (test_pm_compute.js enforces this).

var NOW = Number(metadata.ts);
if (!isFinite(NOW) || NOW <= 0) NOW = Date.now();
var STALE_MS = 15 * 60 * 1000;
var HOUR = 3600000;
var ESCALATE_EVALS = 2;   // raw severity must hold this many runs (~10 min) before it is confirmed upwards
var RELAX_EVALS = 3;      // ... and this many runs (~15 min) before it is confirmed downwards

function parseJson(s, d) {
  if (s === null || s === undefined || s === '') return d;
  if (typeof s === 'object') return s;
  try { return JSON.parse(s); } catch (e) { return d; }
}
var S = parseJson(metadata.ss_pm_state, {});
var BASE = parseJson(metadata.ss_pm_baseline, {});
var CFG = parseJson(metadata.ss_pm_config, {});
if (!S.m) S.m = {};
if (!S.sev) S.sev = {confirmed: 'OK', cand: 'OK', n: 0};

// ---------- value access ----------
// Returns {v, ts} of the newest known value of key (message first, then fetched latest), or null.
function raw(key) {
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
// Numeric reading that is fresh and not a controller "not available" code / out-of-range.
function num(key, lo, hi) {
  var r = fresh(key);
  if (!r) return null;
  var v = r.v;
  if (v === null || v === '' || typeof v === 'boolean') return null;
  var n = Number(v);
  if (!isFinite(n) || n === 32767 || n === 65535 || n >= 30000) return null;
  if (lo !== undefined && n < lo) return null;
  if (hi !== undefined && n > hi) return null;
  return n;
}
function bool(key) {
  var r = fresh(key);
  if (!r) return null;
  var v = r.v;
  if (v === true || v === 1 || v === '1' || ('' + v).toLowerCase() === 'true') return true;
  if (v === false || v === 0 || v === '0' || ('' + v).toLowerCase() === 'false') return false;
  return null;
}
function str(key) {
  var r = fresh(key);
  return r ? ('' + r.v) : null;
}
// Days since a known sensor last reported, when its newest value is older than STALE_MS (else null).
function staleDays(key) {
  var r = raw(key);
  if (!r || NOW - r.ts <= STALE_MS) return null;
  return (NOW - r.ts) / (24 * HOUR);
}
function ageText(days) {
  if (days >= 1) return Math.round(days) + ' day' + (Math.round(days) === 1 ? '' : 's');
  return Math.max(1, Math.round(days * 24)) + ' h';
}
function base(key, stat) {
  var b = BASE[key];
  if (!b || b[stat] === undefined || b[stat] === null) return null;
  return Number(b[stat]);
}
function r1(x) { return Math.round(x * 10) / 10; }
function r2(x) { return Math.round(x * 100) / 100; }

// ---------- trends ----------
// EWMA level + EWMA slope (units per hour). Returns {f, s, n}. alpha: level smoothing.
function trend(name, value, alpha) {
  var t = S.m[name];
  if (!t || NOW - t.t > 24 * HOUR || !isFinite(t.f)) {
    t = {f: value, s: 0, t: NOW, n: 1};
  } else {
    var dtH = (NOW - t.t) / HOUR;
    if (dtH <= 0) return t;
    var f = t.f + alpha * (value - t.f);
    if (dtH >= 1 / 60) {
      var inst = (f - t.f) / dtH;
      t.s = t.n < 3 ? inst : t.s + 0.15 * (inst - t.s);
    }
    t.f = f;
    t.t = NOW;
    t.n = Math.min(t.n + 1, 100000);
  }
  S.m[name] = t;
  return t;
}
// Hours until the trend reaches limit (null when it is not heading there or the trend is too young).
function hoursTo(t, limit, minEvals) {
  if (!t || t.n < (minEvals || 12) || !isFinite(t.s) || t.s === 0) return null;
  var h = (limit - t.f) / t.s;
  if (h <= 0 || h > 24 * 365) return null;
  return h;
}

// ---------- issues ----------
var issues = [];
var rulHours = [];   // calendar hours until a predicted threshold breach
var expected = 0, present = 0;
var out = {};
function add(sev, text, action, penalty) {
  var p = penalty !== undefined ? penalty : (sev === 'CRITICAL' ? 45 : (sev === 'WARNING' ? 15 : 3));
  issues.push({sev: sev, text: text, action: action || '', p: p});
}
function expect(v) { expected++; if (v !== null && v !== undefined) present++; return v; }

var type = metadata.deviceType || '';
var name = metadata.deviceName || 'Device';
var KINDS = {'woodward_kg1500': 'DG', 'LT Panels Profile': 'LT', 'RO System Profile': 'RO', 'LT Panel Fire Profile': 'FIRE'};
var kind = CFG.kind || KINDS[type] || '';
var mode = '';

// =====================================================================================
if (kind === 'DG') {
  var rpm = num('engine_rpm', 0, 3000);
  var status = str('dg_status');
  var running = status === 'RUNNING' || (rpm !== null && rpm > 300);
  mode = running ? 'RUNNING' : 'STANDBY';
  out.pm_dg_mode = mode;

  // Battery (12/24 V system from history)
  var bv = expect(num('battery_voltage', 5, 40));
  var sys24 = (base('battery_voltage', 'median') || 24) > 18;
  var k = sys24 ? 1 : 0.5;
  if (bv !== null) {
    out.pm_battery_v = bv;
    if (!running) {
      var bt = trend('battery_off', bv, 0.3);
      if (bv < 23.0 * k) add('CRITICAL', 'Battery ' + bv + ' V on standby (min ' + (23.0 * k) + ' V) - DG may fail to crank', 'Check battery charger and battery health now; arrange a replacement battery.');
      else if (bv < 24.4 * k) add('WARNING', 'Battery low on standby: ' + bv + ' V', 'Check the battery charger output and electrolyte/terminals.');
      var hb = hoursTo(bt, 24.0 * k, 24);
      if (hb !== null && bt.s < -0.01 * k) {
        rulHours.push(hb);
        if (hb < 72 && bv >= 24.4 * k) add('WARNING', 'Battery falling ' + r2(-bt.s * 24) + ' V/day, reaches ' + (24.0 * k) + ' V in ~' + Math.round(hb) + ' h', 'Battery charger may be faulty - inspect before the next DG test.');
      }
    } else if (bv > 29.5 * k) {
      add('WARNING', 'Battery overcharging at ' + bv + ' V with the engine running', 'Check the charging alternator regulator.');
    }
  }

  // Fuel: filtered level, burn rate and autonomy come from the DG Fuel node (dg_fuel.js)
  var fuel = num('fuel_level_pct', 0, 100);
  if (fuel === null) fuel = num('fuel_level', 0, 100);
  expect(fuel);
  var fLow = Number(CFG.fuel_low_pct) || 30, fCrit = Number(CFG.fuel_critical_pct) || 15;
  if (str('fuel_status') === 'SENSOR ERROR') add('INFO', 'Fuel level sensor not reporting', 'Check the fuel sender wiring and the controller input.', 5);
  if (fuel !== null) {
    out.pm_fuel_pct = fuel;
    var fTxt = fuel >= 99.95 ? 'FULL (>=100%)' : fuel + '%';
    if (fuel < fCrit) add('CRITICAL', 'Fuel very low: ' + fTxt, 'Refuel immediately - backup runtime is at risk.');
    else if (fuel < fLow) add('WARNING', 'Fuel low: ' + fTxt, 'Schedule refuelling.');
    var hf = num('fuel_runtime_h', 0, 100000);
    if (hf !== null) {
      out.pm_fuel_runtime_h = hf;
      if (running) {
        rulHours.push(hf);
        if (hf < 1.5) add('CRITICAL', 'Fuel runs out in ~' + hf + ' h at current burn rate', 'Refuel now or transfer load.');
        else if (hf < 4) add('WARNING', 'Fuel lasts ~' + hf + ' h at current burn rate', 'Arrange refuelling.');
      } else if (CFG.required_autonomy_h && hf < Number(CFG.required_autonomy_h)) {
        add('WARNING', 'Fuel autonomy ' + hf + ' h is below the required ' + CFG.required_autonomy_h + ' h', 'Top up the tank to restore the required backup runtime.');
      }
    }
  }

  // Running-only engine and alternator checks
  if (running) {
    var ct = num('coolant_temp', 20, 130);
    expect(ct);
    if (ct !== null) {
      var ctt = trend('coolant_run', ct, 0.4);
      var pred = ctt.n >= 3 ? ctt.f + ctt.s : ct;
      out.predicted_coolant_1h = r1(Math.max(-20, Math.min(150, pred)));
      if (ct >= 103) add('CRITICAL', 'Coolant ' + ct + ' C (limit 103 C)', 'Reduce load and inspect radiator, fan belt and coolant level.');
      else if (ct >= 95) add('WARNING', 'Coolant high: ' + ct + ' C', 'Inspect radiator and coolant level.');
      else if (pred >= 103) add('WARNING', 'Coolant rising, predicted ' + r1(pred) + ' C in 1 h', 'Inspect radiator airflow and coolant level.');
      var hc = hoursTo(ctt, 103, 3);
      if (hc !== null) rulHours.push(hc);
    }
    var op = num('oil_pressure', 0, 1000);
    expect(op);
    if (op !== null && rpm !== null && rpm > 1000) {
      if (op < 150) add('CRITICAL', 'Oil pressure ' + op + ' kPa at ' + rpm + ' rpm', 'Stop the DG and check oil level / oil pump.');
      else if (op < 250) add('WARNING', 'Oil pressure low: ' + op + ' kPa', 'Check oil level and filter.');
    }
    var fq = num('frequency', 1, 80);
    if (fq !== null) {
      var df = Math.abs(fq - 50);
      if (df > 2) add('CRITICAL', 'Frequency ' + fq + ' Hz', 'Check governor / engine speed control.');
      else if (df > 1) add('WARNING', 'Frequency off-nominal: ' + fq + ' Hz', 'Check governor settings.');
    }
    var vv = num('voltage', 50, 600);
    if (vv !== null) {
      var vn = vv > 300 ? 415 : 230;
      var dv = Math.abs(vv - vn) / vn;
      if (dv > 0.12) add('CRITICAL', 'Output voltage ' + vv + ' V (nominal ' + vn + ' V)', 'Check AVR / excitation.');
      else if (dv > 0.08) add('WARNING', 'Output voltage ' + vv + ' V off nominal', 'Check AVR settings.');
    }
    var pf = num('power_factor', 0, 1);
    var pkw = num('power_kw', 0, 5000);
    if (pf !== null && pkw !== null && pkw > 50 && pf < 0.8) add('WARNING', 'Low power factor ' + pf + ' at ' + pkw + ' kW', 'Review load / capacitor bank.');
    if (pkw !== null && CFG.rated_kw) {
      var load = pkw / Number(CFG.rated_kw) * 100;
      out.pm_load_pct = r1(load);
      if (load > 100) add('CRITICAL', 'DG overloaded: ' + r1(load) + '% of ' + CFG.rated_kw + ' kW', 'Shed load immediately.');
      else if (load > 90) add('WARNING', 'DG load high: ' + r1(load) + '%', 'Avoid adding load.');
    }
  } else {
    out.predicted_coolant_1h = '--';
  }

  // Controller alarm
  var ca = num('common_alarm', 0, 29999);
  if (ca !== null && ca !== 0) add('WARNING', 'Controller common alarm active (code ' + ca + ')', 'Read the alarm list on the Woodward controller.');

  // Service due (run hours). Only computed from the real last-service record entered in pm_config;
  // without it the due time is unknown and is shown as '--' (no assumed service history).
  var rh = expect(num('run_hours', 0, 200000));
  var lastSvcCfg = CFG.last_service_run_hours;
  var lastSvc = (lastSvcCfg === undefined || lastSvcCfg === null || lastSvcCfg === '') ? null : Number(lastSvcCfg);
  if (lastSvc !== null && !isFinite(lastSvc)) lastSvc = null;
  if (rh !== null && lastSvc !== null) {
    var interval = Number(CFG.service_interval_h) || 250;
    var due = lastSvc + interval - rh;
    out.pm_service_due_h = r1(due);
    out.rul_hours = Math.max(0, r1(due));
    if (due < -100) add('CRITICAL', 'Service overdue by ' + Math.round(-due) + ' run-hours', 'Carry out the scheduled service (oil, filters) now.');
    else if (due < 0) add('WARNING', 'Service overdue by ' + Math.round(-due) + ' run-hours', 'Schedule the service and update pm_config.last_service_run_hours.');
    else if (due < 25) add('INFO', 'Service due in ' + Math.round(due) + ' run-hours', 'Plan the next service.', 2);
  } else {
    out.pm_service_due_h = '--';
    out.rul_hours = '--';
    if (lastSvc === null) add('INFO', 'Service history not entered - service due time unknown', 'Enter the run-hours reading of the last DG service in pm_config.last_service_run_hours.', 0);
  }
  // Exercise (standby DG must run regularly). The controller sometimes nudges the run-hour counter by
  // 0.01-0.02 h with the engine stopped, so only a rise of at least 0.1 h (6 min) counts as a run.
  if (rh !== null) {
    if (running || S.lastRh === undefined || rh < S.lastRh) {
      S.lastRh = rh;
    } else if (rh >= S.lastRh + 0.1) {
      S.lastRunTs = NOW;
      S.lastRh = rh;
    }
  }
  if (running) S.lastRunTs = NOW;
  if (S.lastRunTs) {
    var idleDays = (NOW - S.lastRunTs) / (24 * HOUR);
    out.pm_days_since_run = r1(idleDays);
    var exDays = Number(CFG.exercise_days) || 7;
    if (idleDays > exDays * 2) add('WARNING', 'DG idle ' + Math.round(idleDays) + ' days', 'Run a no-load/load test to confirm standby readiness.', 20);
    else if (idleDays > exDays) add('WARNING', 'DG idle ' + Math.round(idleDays) + ' days (test every ' + exDays + ' days)', 'Schedule the weekly test run.', 10);
  }

  // Start counter (many starts per day = failed/short starts)
  var st = num('engine_starts', 0, 1000000);
  if (st !== null) {
    var day = Math.floor((NOW + 19800000) / (24 * HOUR));
    if (!S.starts || S.starts.day !== day) S.starts = {day: day, base: st};
    var today = st - S.starts.base;
    out.pm_starts_today = today;
    if (today > 6) add('WARNING', today + ' engine starts today', 'Check failed or short starts (battery, starter, fuel).');
  }

// =====================================================================================
} else if (kind === 'LT') {
  mode = 'LT';
  var feeders = [];
  for (var key in metadata) {
    var mm = /^(.+)_voltage$/.exec(key);
    if (mm && key.indexOf('ss_') !== 0) feeders.push(mm[1]);
  }
  feeders.sort();
  var fsum = {};
  var ratedA = CFG.rated_a || {};
  for (var i = 0; i < feeders.length; i++) {
    var fd = feeders[i];
    var label = fd.replace(/_/g, ' ');
    var V = num(fd + '_voltage', 1, 1000), I = num(fd + '_current', 0, 100000), P = num(fd + '_power', -100000, 100000), F = num(fd + '_frequency', 1, 100);
    expect(V);
    if (V === null) {
      fsum[fd] = 'NO DATA';
      add('INFO', label + ': meter not reporting', 'Check the meter / Modbus link of ' + label + '.', 2);
      continue;
    }
    var nominal = (CFG.nominal_v && CFG.nominal_v[fd]) || ((base(fd + '_voltage', 'median') || V) > 300 ? 415 : 230);
    var vt = trend(fd + '_v', V, 0.4);
    var dev = (vt.f - nominal) / nominal * 100;
    var fstate = 'OK';
    if (Math.abs(dev) > 10) { add('CRITICAL', label + ' voltage ' + r1(vt.f) + ' V (' + r1(dev) + '% from ' + nominal + ' V)', 'Check supply / transformer tap and connected equipment.'); fstate = 'CRITICAL'; }
    else if (Math.abs(dev) > 7.5) { add('WARNING', label + ' voltage ' + r1(vt.f) + ' V (' + r1(dev) + '%)', 'Monitor supply voltage; check transformer tap.'); fstate = 'WARNING'; }
    if (F !== null) {
      var ftr = trend(fd + '_f', F, 0.4);
      var dfq = Math.abs(ftr.f - 50);
      if (dfq > 1) { add('CRITICAL', label + ' frequency ' + r2(ftr.f) + ' Hz', 'Check supply source.'); fstate = 'CRITICAL'; }
      else if (dfq > 0.6) { add('WARNING', label + ' frequency ' + r2(ftr.f) + ' Hz', 'Monitor supply frequency.'); if (fstate === 'OK') fstate = 'WARNING'; }
    }
    if (I !== null) {
      var it = trend(fd + '_i', I, 0.3);
      var rated = Number(ratedA[fd]);
      var p95 = base(fd + '_current', 'p95');
      if (rated > 0) {
        var lp = it.f / rated * 100;
        if (lp > 100) { add('CRITICAL', label + ' overloaded: ' + Math.round(it.f) + ' A (' + Math.round(lp) + '% of ' + rated + ' A)', 'Shed or redistribute load.'); fstate = 'CRITICAL'; }
        else if (lp > 90) { add('WARNING', label + ' load ' + Math.round(lp) + '% of rating', 'Plan load redistribution.'); if (fstate === 'OK') fstate = 'WARNING'; }
      } else if (p95 !== null && p95 > 5 && it.n >= 6 && it.f > p95 * 1.3) {
        add('WARNING', label + ' current ' + Math.round(it.f) + ' A is ' + Math.round((it.f / p95 - 1) * 100) + '% above its normal peak (' + Math.round(p95) + ' A)', 'Check added load or a developing fault; set pm_config.rated_a to get exact overload checks.');
        if (fstate === 'OK') fstate = 'WARNING';
      }
      // Power factor from P, V, I
      if (P !== null && I > 5 && (p95 === null || I > 0.1 * p95)) {
        var kva = (V > 300 ? 1.732 * V * I : V * I) / 1000;
        var pfv = kva > 0 ? Math.abs(P) / kva : null;
        if (pfv !== null && pfv <= 1.05) {
          var pft = trend(fd + '_pf', Math.min(1, pfv), 0.3);
          if (pft.n >= 3 && pft.f < 0.8) { add('WARNING', label + ' power factor ' + r2(pft.f), 'Check capacitor bank / reactive load.', 10); if (fstate === 'OK') fstate = 'WARNING'; }
        }
      }
    }
    fsum[fd] = fstate;
  }
  out.pm_feeders = JSON.stringify(fsum);

// =====================================================================================
} else if (kind === 'RO') {
  mode = 'RO';
  var tds = expect(num('tds_ppm', 0, 5000));
  var med = base('tds_ppm', 'median');
  var warnT = Number(CFG.tds_warn) || Math.min(300, Math.max(150, (med || 75) * 2));
  var critT = Number(CFG.tds_crit) || 500;
  if (tds !== null) {
    var tt = trend('tds', tds, 0.05);
    out.pm_tds_avg = r1(tt.f);
    if (tt.f > critT) add('CRITICAL', 'Product water TDS ' + Math.round(tt.f) + ' ppm (limit ' + critT + ')', 'Stop drinking-water supply; inspect RO membrane and O-rings.');
    else if (tt.f > warnT) add('WARNING', 'Product water TDS ' + Math.round(tt.f) + ' ppm (normal ~' + Math.round(med || 0) + ')', 'Clean (CIP) or plan membrane replacement.');
    // Long-term TDS trend = least-squares slope of the daily average TDS (IST days) over the last 14
    // completed days. Short swings within a day are not a membrane trend, so the trend stays '--'
    // until at least 3 full days (each with 4 h or more of readings) are available.
    var tdsDay = Math.floor((NOW + 19800000) / (24 * HOUR));
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
      if (S.tdsDays[di].d > tdsDay - 15) keptDays.push(S.tdsDays[di]);
    }
    S.tdsDays = keptDays;
    var xs = [], ys = [];
    for (var dj = 0; dj < S.tdsDays.length; dj++) {
      var bd = S.tdsDays[dj];
      if (bd.d < tdsDay && bd.n >= 48) {
        xs.push(bd.d);
        ys.push(bd.s / bd.n);
      }
    }
    var slope = null;
    if (xs.length >= 3) {
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
        // Fit quality: a rise-and-fall is not a steady trend, so it is not extrapolated (R2 below 0.5)
        var ssTot = 0, ssRes = 0;
        for (var a3 = 0; a3 < xs.length; a3++) {
          var fit = my + slope * (xs[a3] - mx);
          ssRes += (ys[a3] - fit) * (ys[a3] - fit);
          ssTot += (ys[a3] - my) * (ys[a3] - my);
        }
        var fitR2 = ssTot > 0 ? 1 - ssRes / ssTot : 0;
        out.pm_tds_trend_r2 = r2(fitR2);
        if (fitR2 < 0.5) slope = null;
      }
    }
    out.pm_tds_trend_ppm_day = slope === null ? '--' : r2(slope);
    out.pm_tds_trend_days = xs.length;
    if (slope !== null && slope > 0.5 && tt.f < warnT) {
      var ht = (warnT - tt.f) / slope * 24;
      if (ht > 0 && ht <= 24 * 365) {
        rulHours.push(ht);
        if (ht < 24 * 30) add('WARNING', 'TDS rising ' + r1(slope) + ' ppm/day over ' + xs.length + ' days - reaches ' + warnT + ' ppm in ~' + Math.round(ht / 24) + ' days', 'Plan membrane cleaning / replacement.', 10);
      }
    }
  }
  var tc = expect(num('temperature_c', -5, 90));
  if (tc !== null) {
    if (tc > 45) add('CRITICAL', 'Water temperature ' + tc + ' C (membrane max 45 C)', 'Stop the RO to protect the membrane.');
    else if (tc > 38) add('WARNING', 'Water temperature high: ' + tc + ' C', 'Check feed water source / plant room ventilation.');
  }
  var ph = num('ph', 0, 14);
  if (raw('ph') !== null) expect(ph);
  if (ph !== null) {
    if (ph < 6 || ph > 9) add('CRITICAL', 'pH ' + ph, 'Stop supply and check dosing.');
    else if (ph < 6.5 || ph > 8.5) add('WARNING', 'pH out of range: ' + ph, 'Check dosing / remineralisation.');
  }
  var pr = num('pressure', 0, 100);
  if (raw('pressure') !== null) expect(pr);
  var roSensors = [['ph', 'pH sensor'], ['pressure', 'Pressure sensor'], ['temperature_c', 'Temperature sensor']];
  for (var rs = 0; rs < roSensors.length; rs++) {
    var sdays = staleDays(roSensors[rs][0]);
    if (sdays !== null) add('INFO', roSensors[rs][1] + ' not reporting (last reading ' + ageText(sdays) + ' ago)', 'Check the ' + roSensors[rs][1] + ' wiring / transmitter; its checks are paused.', 5);
  }
  var prMed = base('pressure', 'median');
  if (pr !== null && prMed) {
    var prt = trend('pressure', pr, 0.2);
    var pd = (prt.f - prMed) / prMed * 100;
    if (Math.abs(pd) > 25) add('WARNING', 'Pressure ' + r1(prt.f) + ' bar (' + Math.round(pd) + '% from normal ' + prMed + ')', pd > 0 ? 'Membrane/pre-filter may be fouling - check differential pressure.' : 'Check pump and pre-filters.');
  }
  if (bool('tds_online') === false) add('WARNING', 'TDS sensor offline', 'Check the TDS sensor connection.');
  if (bool('flow_online') === false) add('INFO', 'Flow sensor offline - flow based checks unavailable', 'Repair the flow sensor to enable recovery/fouling prediction.', 5);

// =====================================================================================
} else if (kind === 'FIRE') {
  mode = 'FIRE';
  var ignore = CFG.ignore_channels || [];
  var chans = [];
  for (var ck in metadata) {
    var cm = /^(cylinder_pressure_|fire_suppression_)(\d+)(_pressure)?$/.exec(ck);
    if (cm && (cm[1] === 'cylinder_pressure_' ? !cm[3] : cm[3])) chans.push({key: ck, n: Number(cm[2])});
  }
  chans.sort(function (a, b) { return a.n - b.n; });
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
    if (!vals.length) continue;   // no data in the last 15 min: channel not in use on this device
    expect(true);
    var changes = 0;
    for (var q = 1; q < vals.length; q++) {
      if (vals[q] !== vals[q - 1]) changes++;
    }
    if (changes >= 4) flapList.push(ch.n + ' (' + changes + 'x)');
    else if (!vals[vals.length - 1]) lowList.push(ch.n);
    else okCount++;
  }
  out.pm_cylinders_ok = okCount;
  out.pm_cylinders_low = lowList.length;
  out.pm_cylinders_unstable = flapList.length;
  if (lowList.length) add('WARNING', 'Low pressure on cylinder(s) ' + lowList.join(', '), 'Inspect and recharge these cylinders; check the pressure switch if the cylinder gauge reads normal.', Math.min(45, 12 * lowList.length));
  if (flapList.length) add('WARNING', 'Unstable pressure signal on cylinder(s) ' + flapList.join(', ') + ' in 15 min', 'Check pressure-switch wiring and whether two gateways send data to this device.', Math.min(45, 10 * flapList.length));
  for (var rr = 0; rr <= 2; rr++) {
    var rk = rr === 0 ? 'relay_online' : 'relay_' + rr + '_online';
    if (bool(rk) === false) add('WARNING', 'Relay ' + (rr || '') + ' offline', 'Check the relay module power / network.');
  }
} else {
  mode = 'UNKNOWN';
}

// ---------- scoring ----------
var rawSev = 'OK', penalty = 0;
for (var x = 0; x < issues.length; x++) {
  penalty += issues[x].p;
  if (issues[x].sev === 'CRITICAL') rawSev = 'CRITICAL';
  else if (issues[x].sev === 'WARNING' && rawSev !== 'CRITICAL') rawSev = 'WARNING';
}
var noData = expected > 0 && present === 0;
var score = Math.max(0, 100 - penalty);
// Health bands follow severity: OK 80-100, WARNING 40-79, CRITICAL 0-39
if (rawSev === 'CRITICAL') score = Math.min(score, 39);
else if (rawSev === 'WARNING') score = Math.max(40, Math.min(score, 79));
else score = Math.max(80, score);

// Hysteresis on severity
var RANK = {OK: 0, WARNING: 1, CRITICAL: 2};
var sv = S.sev;
if (!noData) {
  if (rawSev === sv.confirmed) { sv.cand = rawSev; sv.n = 0; }
  else {
    if (sv.cand === rawSev) sv.n++; else { sv.cand = rawSev; sv.n = 1; }
    var need = RANK[rawSev] > RANK[sv.confirmed] ? ESCALATE_EVALS : RELAX_EVALS;
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
  autoSummary = name + ': no fresh telemetry in the last 15 min - predictive checks paused.';
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
out.pm_risk_pct = noData ? '--' : Math.max(0, Math.min(99, 100 - score));
out.pm_severity = noData ? 'NO DATA' : sev;
out.pm_severity_raw = rawSev;
out.pm_rul_days = rul === null ? '--' : r1(rul / 24);
out.pm_issue_count = real.length;
out.pm_top_issue = top ? top.text : 'None';
out.pm_data_quality_pct = expected ? Math.round(present / expected * 100) : 100;
var il = [];
for (var u = 0; u < issues.length && u < 12; u++) {
  il.push({sev: issues[u].sev, text: issues[u].text, action: issues[u].action});
}
out.pm_issues = JSON.stringify(il);
out.pm_summary_auto = autoSummary.substring(0, 300);
out.pm_recommendation_auto = autoAction.substring(0, 300);

// Template summary stands in until the LLM writes one, and whenever severity changes
var llm = raw('pm_summary');
var llmStale = !llm || NOW - llm.ts > 40 * 60 * 1000 || S.lastSev !== out.pm_severity;
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
