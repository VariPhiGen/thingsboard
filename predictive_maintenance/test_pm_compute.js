// Offline tests for pm_compute.js: node predictive_maintenance/test_pm_compute.js
var fs = require('fs');
var path = require('path');
var assert = require('assert');
var body = fs.readFileSync(path.join(__dirname, 'pm_compute.js'), 'utf8');
var compute = new Function('msg', 'metadata', 'msgType', body);


// ---- configuration as migrate_config.py writes it: seed template + values derived from the device baseline
var SEED = JSON.parse(fs.readFileSync(path.join(__dirname, 'pm_seed.json'), 'utf8'));
var MAP = {fuel_low_pct: 'fuel.low_pct', fuel_critical_pct: 'fuel.critical_pct', fuel_tank_capacity_l: 'fuel.tank_capacity_l',
           required_autonomy_h: 'fuel.required_autonomy_h', service_interval_h: 'service.interval_h',
           last_service_run_hours: 'service.last_service_run_hours', exercise_days: 'exercise.days', ignore_channels: 'ignore_channels',
           rated_kw: 'load.rated_kw'};
function setPath(o, p, v) { var a = p.split('.'); var c = o; for (var i = 0; i < a.length - 1; i++) { c = c[a[i]] = c[a[i]] || {}; } c[a[a.length - 1]] = v; }
function buildCfg(type, overrides, baseline) {
  var kind = SEED.profiles[type];
  if (!kind) return {};
  var lim = JSON.parse(JSON.stringify(SEED.kinds[kind]));
  baseline = baseline || {};
  if (kind === 'DG') {
    var bm = baseline.battery_voltage && baseline.battery_voltage.median;
    var D = SEED.derive, NV = D.nominal_voltage;
    if (bm && bm <= D.battery_12v_if_median_at_or_below_v) { ['crit_v', 'warn_v', 'trend_floor_v', 'overcharge_v'].forEach(function (k) { lim.battery[k] = lim.battery[k] / 2; }); lim.battery.falling_v_per_h /= 2; }
    var vm = baseline.voltage && baseline.voltage.median;
    if (vm) lim.voltage.nominal_v = vm > NV.three_phase_if_median_above_v ? NV.three_phase_v : NV.single_phase_v;
  }
  if (kind === 'LT') {
    Object.keys(baseline).forEach(function (k) { var m = /^(.+)_voltage$/.exec(k); var NV2 = SEED.derive.nominal_voltage; if (m && baseline[k].median) lim.nominal_v[m[1]] = baseline[k].median > NV2.three_phase_if_median_above_v ? NV2.three_phase_v : NV2.single_phase_v; });
  }
  if (kind === 'RO' && baseline.tds_ppm && baseline.tds_ppm.median) { var TW = SEED.derive.tds_warn; lim.tds.warn_ppm = Math.min(TW.max_ppm, Math.max(TW.min_ppm, baseline.tds_ppm.median * TW.factor_of_median)); }
  Object.keys(overrides || {}).forEach(function (k) { setPath(lim, MAP[k] || k, overrides[k]); });
  return {kind: kind, engine: JSON.parse(JSON.stringify(SEED.engine)), limits: lim};
}

var NOW = 1793520000000;
var CUR = NOW;   // evaluation time of the current run; latest values are stamped relative to it
function L(v, ageMin) { return JSON.stringify({ts: CUR - (ageMin || 0) * 60000, value: v}); }
function run(type, latest, opts) {
  opts = opts || {};
  var md = {ts: '' + (opts.ts || NOW), deviceType: type, deviceName: opts.name || 'Test'};
  for (var k in latest) md[k] = latest[k];
  if (opts.state) md.ss_pm_state = JSON.stringify(opts.state);
  if (opts.baseline) md.ss_pm_baseline = JSON.stringify(opts.baseline);
  md.ss_pm_config = JSON.stringify(opts.rawConfig !== undefined ? opts.rawConfig : buildCfg(type, opts.config, opts.baseline));
  return compute(opts.msg || {}, md, 'POST_TELEMETRY_REQUEST');
}
// Repeat runs carrying state forward (5 min apart)
function runN(n, type, latestFn, opts) {
  var st = opts && opts.state, r;
  for (var i = 0; i < n; i++) {
    var ts = NOW + i * 300000;
    CUR = ts;
    var o = Object.assign({}, opts, {ts: ts, state: st});
    r = run(type, latestFn(i, ts), o);
    st = JSON.parse(r.metadata.pm_state_out);
  }
  CUR = NOW;
  return r;
}
var passed = 0;

// ThingsBoard's Nashorn sandbox rejects scripts where f-o-r / w-h-i-l-e / d-o / function are not followed by a
// braced block, and its regex also matches those words inside strings and comments.
(function sandboxCheck() {
  var lines = body.split('\n'), bad = [];
  for (var i = 0; i < lines.length; i++) {
    var l = lines[i];
    if (/\b(while|do)\b/.test(l)) bad.push((i + 1) + ': ' + l.trim());
    else if (/\bfor\b/.test(l) && !/^\s*for \(var [^)]*\) \{\s*$/.test(l)) bad.push((i + 1) + ': ' + l.trim());
    else if (/\bfunction\b/.test(l) && !/function\s*\w*\s*\([^)]*\)\s*\{/.test(l)) bad.push((i + 1) + ': ' + l.trim());
  }
  assert.deepStrictEqual(bad, [], 'Nashorn sandbox would reject:\n' + bad.join('\n'));
  console.log('ok - script passes the Nashorn braces check');
})();
function t(name, fn) { fn(); passed++; console.log('ok -', name); }

t('DG standby healthy (sensors 32767 are not a fault)', function () {
  var r = run('woodward_kg1500', {
    dg_status: L('OFF'), engine_rpm: L(32767), coolant_temp: L(32767), oil_pressure: L(32767),
    battery_voltage: L(26.7), fuel_level: L(98), run_hours: L(132.27), engine_starts: L(335), common_alarm: L(0)
  }, {state: {lastRunTs: NOW - 2 * 86400000}});
  assert.strictEqual(r.msg.pm_severity, 'OK');
  assert.strictEqual(r.msg.pm_mode, 'STANDBY');
  assert.ok(r.msg.pm_health_score >= 80);
  assert.strictEqual(r.msg.ai_status, 'ACTIVE');
  assert.strictEqual(r.msg.health_score, r.msg.pm_health_score);
  assert.strictEqual(r.metadata.pm_alarm, 'OK');
  assert.ok(!/not configured/.test(r.msg.pm_issues), 'a fully configured DG reports no missing limits: ' + r.msg.pm_issues);
});

t('every check of every kind finds its limits in the seed configuration', function () {
  var samples = {
    woodward_kg1500: {dg_status: L('RUNNING'), engine_rpm: L(1500), coolant_temp: L(80), oil_pressure: L(400), battery_voltage: L(27.5),
      fuel_level: L(70), fuel_level_pct: L(70), fuel_runtime_h: L(5), frequency: L(50), voltage: L(415), power_factor: L(0.9), power_kw: L(100),
      common_alarm: L(0), run_hours: L(100), engine_starts: L(5)},
    'LT Panels Profile': {A_voltage: L(415), A_current: L(100), A_power: L(60), A_frequency: L(50)},
    'RO System Profile': {tds_ppm: L(60), temperature_c: L(30), ph: L(7.2), pressure: L(5), tds_online: L(true), flow_online: L(true)},
    'LT Panel Fire Profile': {cylinder_pressure_1: JSON.stringify([{ts: NOW, value: '1'}]), relay_1_online: L(true)}
  };
  Object.keys(samples).forEach(function (type) {
    var r = run(type, samples[type], {baseline: {voltage: {median: 415}, A_voltage: {median: 415}, tds_ppm: {median: 60}, pressure: {median: 5}}});
    assert.ok(!/not configured/.test(r.msg.pm_issues), type + ': ' + r.msg.pm_issues);
    assert.strictEqual(r.msg.pm_status, 'ACTIVE', type);
  });
});

t('no configuration -> NOT CONFIGURED, nothing assumed; a missing limit skips only its check', function () {
  var r = run('woodward_kg1500', {dg_status: L('OFF'), battery_voltage: L(20)}, {rawConfig: {}});
  assert.strictEqual(r.msg.pm_status, 'NOT CONFIGURED');
  assert.strictEqual(r.metadata.pm_alarm, 'SKIP');
  var cfg = buildCfg('woodward_kg1500', {});
  delete cfg.limits.battery.crit_v; delete cfg.limits.battery.warn_v;
  var r2 = run('woodward_kg1500', {dg_status: L('OFF'), battery_voltage: L(20), fuel_level: L(80), run_hours: L(10)}, {rawConfig: cfg});
  assert.ok(!/Battery 20 V on standby/.test(r2.msg.pm_issues), 'no battery check without its limits');
  assert.ok(/Some checks are not configured: battery.crit_v, battery.warn_v/.test(r2.msg.pm_issues), r2.msg.pm_issues);
  var cfg3 = buildCfg('woodward_kg1500', {});
  cfg3.limits.battery.crit_v = 21;
  var r3 = runN(2, 'woodward_kg1500', function () { return {dg_status: L('OFF'), battery_voltage: L(22), fuel_level: L(80), run_hours: L(10)}; }, {rawConfig: cfg3});
  assert.ok(!/Battery 22 V on standby \(min/.test(r3.msg.pm_issues) && /Battery low on standby: 22 V/.test(r3.msg.pm_issues), 'edited limit is used: ' + r3.msg.pm_issues);
});

t('DG low battery needs 2 runs before CRITICAL is confirmed', function () {
  var lat = function () { return {dg_status: L('OFF'), battery_voltage: L(22.5), fuel_level: L(80), run_hours: L(10)}; };
  var r1 = run('woodward_kg1500', lat());
  assert.strictEqual(r1.msg.pm_severity_raw, 'CRITICAL');
  assert.strictEqual(r1.msg.pm_severity, 'OK');
  var r2 = runN(2, 'woodward_kg1500', lat);
  assert.strictEqual(r2.msg.pm_severity, 'CRITICAL');
  assert.ok(r2.msg.pm_health_score <= 39);
  assert.strictEqual(r2.metadata.pm_alarm, 'CRITICAL');
});

t('DG running: coolant high + oil pressure low', function () {
  var r = runN(3, 'woodward_kg1500', function () {
    return {dg_status: L('RUNNING'), engine_rpm: L(1500), coolant_temp: L(97), oil_pressure: L(200),
      battery_voltage: L(27.5), fuel_level: L(70), frequency: L(50.1), voltage: L(238), run_hours: L(100)};
  }, {baseline: {voltage: {median: 238}}});   // this DG's nominal output (230 V) comes from its own history
  assert.strictEqual(r.msg.pm_severity, 'WARNING');
  assert.ok(/Coolant high/.test(r.msg.pm_issues));
  assert.ok(/Oil pressure low/.test(r.msg.pm_issues));
  assert.notStrictEqual(r.msg.predicted_coolant_1h, '--');
});

t('DG stale values (older than 15 min) are ignored', function () {
  var r = run('woodward_kg1500', {battery_voltage: L(20, 60), fuel_level: L(5, 60), run_hours: L(10, 60)});
  assert.strictEqual(r.msg.pm_status, 'NO DATA');
  assert.strictEqual(r.metadata.pm_alarm, 'SKIP');
});

t('DG service overdue and not exercised', function () {
  var r = runN(2, 'woodward_kg1500', function () {
    return {dg_status: L('OFF'), battery_voltage: L(26.5), fuel_level: L(90), run_hours: L(420)};
  }, {config: {service_interval_h: 250, last_service_run_hours: 100, exercise_days: 7}, state: {lastRunTs: NOW - 20 * 86400000, lastRh: 420}});
  assert.ok(/Service overdue by 70/.test(r.msg.pm_issues));
  assert.ok(/DG idle 20 days/.test(r.msg.pm_issues));
  assert.strictEqual(r.msg.rul_hours, 0);
});

t('DG battery declining trend predicts RUL', function () {
  var r = runN(40, 'woodward_kg1500', function (i) {
    return {dg_status: L('OFF'), battery_voltage: L(26 - i * 0.02), fuel_level: L(90), run_hours: L(10)};
  });
  assert.notStrictEqual(r.msg.pm_rul_days, '--');
  assert.ok(r.msg.pm_rul_days < 3, 'rul ' + r.msg.pm_rul_days);
});

t('LT feeders: N/A meters are INFO, healthy feeders OK, PF computed', function () {
  var r = run('LT Panels Profile', {
    UPS_Room_1_voltage: L(411.6), UPS_Room_1_current: L(388), UPS_Room_1_power: L(253), UPS_Room_1_frequency: L(50.0),
    Transformer_1_voltage: L('N/A'), Transformer_1_current: L('N/A'), Transformer_1_power: L('N/A'), Transformer_1_frequency: L('N/A'),
    UPS_Panel_2_voltage: L(230.8, 9000)
  }, {baseline: {UPS_Room_1_voltage: {median: 411}, UPS_Room_1_current: {p95: 423}}});
  assert.strictEqual(r.msg.pm_severity_raw, 'OK');
  var f = JSON.parse(r.msg.pm_feeders);
  assert.strictEqual(f.UPS_Room_1, 'OK');
  assert.strictEqual(f.Transformer_1, 'NO DATA');
  assert.strictEqual(f.UPS_Panel_2, 'NO DATA');
});

t('LT under-voltage and overload vs history', function () {
  var r = runN(8, 'LT Panels Profile', function () {
    return {EVM_Charger_voltage: L(370), EVM_Charger_current: L(300), EVM_Charger_power: L(170), EVM_Charger_frequency: L(50)};
  }, {baseline: {EVM_Charger_voltage: {median: 411}, EVM_Charger_current: {p95: 206}}});
  assert.strictEqual(r.msg.pm_severity, 'CRITICAL');
  assert.ok(/above its normal peak/.test(r.msg.pm_issues));
});

t('RO healthy, flow sensor offline is INFO only', function () {
  var r = run('RO System Profile', {tds_ppm: L(57), temperature_c: L(30), tds_online: L(true), flow_online: L(false), ph: L(7.4, 30000)},
    {baseline: {tds_ppm: {median: 57}}});
  assert.strictEqual(r.msg.pm_severity_raw, 'OK');
  assert.ok(/Flow sensor offline/.test(r.msg.pm_issues));
  assert.ok(/pH sensor not reporting/.test(r.msg.pm_issues));
});

t('RO TDS rising trend (daily averages) gives membrane RUL', function () {
  var today = Math.floor((NOW + 19800000) / 86400000);
  var days = [];
  for (var d = 6; d >= 1; d--) {
    days.push({d: today - d, s: (100 + (6 - d) * 2) * 288, n: 288});   // 100, 102 ... 110 ppm/day averages
  }
  var r = run('RO System Profile', {tds_ppm: L(112), temperature_c: L(30)},
    {baseline: {tds_ppm: {median: 100}}, state: {m: {tds: {f: 112, s: 0, t: NOW - 300000, n: 500}}, tdsDays: days}});
  assert.strictEqual(r.msg.pm_tds_trend_ppm_day, 2);
  assert.strictEqual(r.msg.pm_tds_trend_days, 6);
  assert.strictEqual(r.msg.pm_rul_days, 44);   // (200 - 112) / 2 ppm per day
  assert.ok(!/TDS rising/.test(r.msg.pm_issues), 'no warning when more than 30 days remain');
});

t('RO rise-and-fall over 14 days (real site pattern) is not extrapolated', function () {
  var today = Math.floor((NOW + 19800000) / 86400000);
  var avgs = [47.4, 56.5, 59.3, 76.0, 89.9, 103.1, 106.5, 109.1, 104.3, 100.9, 111.3, 82.6, 57.2, 46.4];
  var days = [];
  for (var d = 0; d < avgs.length; d++) {
    days.push({d: today - avgs.length + d, s: avgs[d] * 288, n: 288});
  }
  var r = run('RO System Profile', {tds_ppm: L(53), temperature_c: L(31.8)},
    {baseline: {tds_ppm: {median: 102}}, state: {m: {tds: {f: 45.6, s: 0, t: NOW - 300000, n: 500}}, tdsDays: days}});
  assert.strictEqual(r.msg.pm_tds_trend_ppm_day, '--');
  assert.ok(r.msg.pm_tds_trend_r2 < 0.5);
  assert.strictEqual(r.msg.pm_rul_days, '--');
});

t('RO swings inside one day are not reported as a ppm/day trend', function () {
  var r = runN(150, 'RO System Profile', function (i) {
    return {tds_ppm: L(i < 75 ? 34 : 56), temperature_c: L(30)};
  }, {baseline: {tds_ppm: {median: 40}}});
  assert.strictEqual(r.msg.pm_tds_trend_ppm_day, '--');
  assert.strictEqual(r.msg.pm_rul_days, '--');
});

t('RO pH / pressure sensors silent for days are reported and lower data quality', function () {
  var r = run('RO System Profile', {tds_ppm: L(53), temperature_c: L(31.8), ph: L(7.4, 34 * 1440), pressure: L(5, 34 * 1440)},
    {baseline: {tds_ppm: {median: 102}}});
  assert.ok(/pH sensor not reporting \(last reading 34 days ago\)/.test(r.msg.pm_issues), r.msg.pm_issues);
  assert.ok(/Pressure sensor not reporting/.test(r.msg.pm_issues));
  assert.strictEqual(r.msg.pm_data_quality_pct, 50);
  assert.strictEqual(r.msg.pm_severity_raw, 'OK');
});

t('DG without a real service record shows service due as unknown', function () {
  var r = run('woodward_kg1500', {dg_status: L('OFF'), battery_voltage: L(26.4), fuel_level: L(100), run_hours: L(166.18)});
  assert.strictEqual(r.msg.pm_service_due_h, '--');
  assert.strictEqual(r.msg.rul_hours, '--');
  assert.ok(/Service schedule not set up/.test(r.msg.pm_issues));
  assert.strictEqual(r.msg.pm_severity_raw, 'OK');
  var r2 = run('woodward_kg1500', {dg_status: L('OFF'), battery_voltage: L(26.4), fuel_level: L(100), run_hours: L(166.18)},
    {config: {last_service_run_hours: 0}});
  assert.strictEqual(r2.msg.pm_service_due_h, 83.8);
});

t('DG run-hour counter nudge of 0.02 h while stopped is not a run', function () {
  var st = {lastRunTs: NOW - 3 * 86400000, lastRh: 119.86};
  var r = run('woodward_kg1500', {dg_status: L('OFF'), engine_rpm: L(32767), battery_voltage: L(26.7), fuel_level: L(100), run_hours: L(119.88)}, {state: st});
  assert.strictEqual(r.msg.pm_days_since_run, 3);
  var r2 = run('woodward_kg1500', {dg_status: L('OFF'), battery_voltage: L(26.7), fuel_level: L(100), run_hours: L(120.4)}, {state: st});
  assert.strictEqual(r2.msg.pm_days_since_run, 0);
});

t('Fire: flapping and low channels detected, stale channels skipped', function () {
  var flap = [], low = [], ok = [];
  for (var i = 0; i < 12; i++) {
    flap.push({ts: NOW - i * 75000, value: i % 2 ? '1' : '0'});
    low.push({ts: NOW - i * 75000, value: '0'});
    ok.push({ts: NOW - i * 75000, value: 'true'});
  }
  var r = run('LT Panel Fire Profile', {
    fire_suppression_1_pressure: JSON.stringify(low), fire_suppression_5_pressure: JSON.stringify(flap),
    cylinder_pressure_2: JSON.stringify(ok), fire_suppression_9_pressure: '[]',
    fire_suppression_1_high_pressure: L(true), relay_1_online: L(true)
  });
  assert.strictEqual(r.msg.pm_cylinders_low, 1);
  assert.strictEqual(r.msg.pm_cylinders_unstable, 1);
  assert.strictEqual(r.msg.pm_cylinders_ok, 1);
  assert.strictEqual(r.msg.pm_severity_raw, 'WARNING');
});

t('Fire: ignore_channels respected', function () {
  var low = [{ts: NOW, value: 'false'}];
  var r = run('LT Panel Fire Profile', {cylinder_pressure_9: JSON.stringify(low)}, {config: {ignore_channels: [9]}});
  assert.strictEqual(r.msg.pm_severity_raw, 'OK');
});

t('Severity relaxes only after 3 runs', function () {
  var st = {sev: {confirmed: 'WARNING', cand: 'WARNING', n: 0}};
  var lat = function () { return {tds_ppm: L(57), temperature_c: L(30)}; };
  var r = runN(2, 'RO System Profile', lat, {state: st, baseline: {tds_ppm: {median: 57}}});
  assert.strictEqual(r.msg.pm_severity, 'WARNING');
  r = runN(3, 'RO System Profile', lat, {state: st, baseline: {tds_ppm: {median: 57}}});
  assert.strictEqual(r.msg.pm_severity, 'OK');
});

t('LLM summary kept while fresh and the facts are unchanged', function () {
  var lat = {tds_ppm: L(57), temperature_c: L(30), pm_summary: L('LLM text', 10)};
  var first = run('RO System Profile', lat, {state: {lastSev: 'OK'}});
  var st = JSON.parse(first.metadata.pm_state_out);
  var r = run('RO System Profile', lat, {state: st});
  assert.strictEqual(r.msg.pm_summary, undefined);
  r = run('RO System Profile', lat, {state: Object.assign({}, st, {lastSev: 'WARNING'})});
  assert.ok(r.msg.pm_summary);
});

t('LLM summary replaced at once when the issues or RUL behind it change', function () {
  var lat = {tds_ppm: L(57), temperature_c: L(30), pm_summary: L('LLM text with 140 days', 10)};
  var st = JSON.parse(run('RO System Profile', lat, {state: {lastSev: 'OK'}}).metadata.pm_state_out);
  // a sensor goes silent: new INFO issue -> rules summary immediately
  var r = run('RO System Profile', {tds_ppm: L(57), temperature_c: L(30), ph: L(7.4, 3000), pm_summary: L('LLM text with 140 days', 10)}, {state: st});
  assert.strictEqual(r.msg.pm_summary_source, 'rules');
  assert.ok(!/140 days/.test(r.msg.pm_summary));
  // a live number changing inside the same issue does not discard the LLM text
  var lv = function (v) { return {dg_status: L('OFF'), battery_voltage: L(v), fuel_level: L(80), run_hours: L(10), pm_summary: L('LLM', 5)}; };
  var s1 = JSON.parse(run('woodward_kg1500', lv(23.8), {config: {last_service_run_hours: 0},
    state: {sev: {confirmed: 'WARNING', cand: 'WARNING', n: 0}, lastSev: 'WARNING'}}).metadata.pm_state_out);
  var r2 = run('woodward_kg1500', lv(23.7), {state: s1, config: {last_service_run_hours: 0}});
  assert.strictEqual(r2.msg.pm_summary, undefined);
});

t('DG fuel uses the filtered level and warns when autonomy is below the requirement', function () {
  var r = run('woodward_kg1500', {dg_status: L('OFF'), battery_voltage: L(26.5), run_hours: L(10),
    fuel_level: L('error'), fuel_level_pct: L(62), fuel_runtime_h: L(3.8)}, {config: {required_autonomy_h: 8}});
  assert.strictEqual(r.msg.pm_fuel_pct, 62);
  assert.ok(/autonomy 3.8 h is below the required 8 h/.test(r.msg.pm_issues), r.msg.pm_issues);
  var r2 = run('woodward_kg1500', {dg_status: L('OFF'), battery_voltage: L(26.5), run_hours: L(10), fuel_level_pct: L(100), fuel_runtime_h: L(6.2)});
  assert.strictEqual(r2.msg.pm_severity_raw, 'OK');
});

console.log(passed + ' tests passed');
