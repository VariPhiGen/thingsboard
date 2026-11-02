// Offline tests for pm_compute.js: node predictive_maintenance/test_pm_compute.js
var fs = require('fs');
var path = require('path');
var assert = require('assert');
var body = fs.readFileSync(path.join(__dirname, 'pm_compute.js'), 'utf8');
var compute = new Function('msg', 'metadata', 'msgType', body);

var NOW = 1793520000000;
var CUR = NOW;   // evaluation time of the current run; latest values are stamped relative to it
function L(v, ageMin) { return JSON.stringify({ts: CUR - (ageMin || 0) * 60000, value: v}); }
function run(type, latest, opts) {
  opts = opts || {};
  var md = {ts: '' + (opts.ts || NOW), deviceType: type, deviceName: opts.name || 'Test'};
  for (var k in latest) md[k] = latest[k];
  if (opts.state) md.ss_pm_state = JSON.stringify(opts.state);
  if (opts.baseline) md.ss_pm_baseline = JSON.stringify(opts.baseline);
  if (opts.config) md.ss_pm_config = JSON.stringify(opts.config);
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
  });
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
  assert.ok(/Service history not entered/.test(r.msg.pm_issues));
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

t('LLM summary kept while fresh and severity unchanged', function () {
  var r = run('RO System Profile', {tds_ppm: L(57), temperature_c: L(30), pm_summary: L('LLM text', 10)}, {state: {lastSev: 'OK'}});
  assert.strictEqual(r.msg.pm_summary, undefined);
  r = run('RO System Profile', {tds_ppm: L(57), temperature_c: L(30), pm_summary: L('LLM text', 10)}, {state: {lastSev: 'WARNING'}});
  assert.ok(r.msg.pm_summary);
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
