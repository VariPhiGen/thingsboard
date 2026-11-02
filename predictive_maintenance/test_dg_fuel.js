// Offline tests for dg_fuel.js: node predictive_maintenance/test_dg_fuel.js
var fs = require('fs');
var path = require('path');
var assert = require('assert');
var body = fs.readFileSync(path.join(__dirname, 'dg_fuel.js'), 'utf8');
var fuel = new Function('msg', 'metadata', 'msgType', body);
var passed = 0;
function t(name, fn) { fn(); passed++; console.log('ok -', name); }

t('script passes the Nashorn braces check', function () {
  var lines = body.split('\n'), bad = [];
  for (var i = 0; i < lines.length; i++) {
    var l = lines[i];
    if (/\b(while|do)\b/.test(l)) bad.push((i + 1) + ': ' + l.trim());
    else if (/\bfor\b/.test(l) && !/^\s*for \(var [^)]*\) \{\s*$/.test(l)) bad.push((i + 1) + ': ' + l.trim());
    else if (/\bfunction\b/.test(l) && !/function\s*\w*\s*\([^)]*\)\s*\{/.test(l)) bad.push((i + 1) + ': ' + l.trim());
  }
  assert.deepStrictEqual(bad, []);
});


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

var T0 = 1793520000000;
// Feeds a sequence of [minute, fuel_level, running] samples, carrying state forward. Returns all results.
function feed(samples, opts) {
  opts = opts || {};
  var state = opts.state ? JSON.stringify(opts.state) : '', res = [];
  for (var i = 0; i < samples.length; i++) {
    var s = samples[i];
    var md = {ts: '' + (T0 + s[0] * 60000), deviceName: 'DG Test', ss_fuel_state: state,
      dg_status: s[2] ? 'RUNNING' : 'OFF', engine_rpm: s[2] ? '1500' : '32767'};
    md.ss_pm_config = JSON.stringify(opts.rawConfig !== undefined ? opts.rawConfig : buildCfg('woodward_kg1500', opts.config));
    var r = fuel({fuel_level: s[1]}, md, 'POST_TELEMETRY_REQUEST');
    state = r.metadata.fuel_state_out;
    res.push(r);
  }
  return res;
}
function last(a) { return a[a.length - 1]; }
function ramp(fromMin, toMin, fromV, toV, running, step) {
  var out = [];
  for (var m = fromMin; m <= toMin; m += (step || 1)) {
    out.push([m, Math.round((fromV + (toV - fromV) * (m - fromMin) / (toMin - fromMin || 1)) * 10) / 10, running]);
  }
  return out;
}

t('median filter removes jitter; error readings keep the last valid level', function () {
  var r = feed([[0, 74.1, false], [1, 74.0, false], [2, 'error', false], [3, 80, false], [4, 74.1, false]]);
  assert.strictEqual(last(r).msg.fuel_level_pct, 74.1);
  assert.strictEqual(last(r).msg.fuel_status, 'OK');
  assert.strictEqual(r[2].msg.fuel_sensor_ok, true);
});

t('100 is reported as FULL (sensor full scale), not an exact level', function () {
  var r = feed([[0, 100, false], [1, 100, false], [2, 100, false]]);
  assert.strictEqual(last(r).msg.fuel_status, 'FULL');
  assert.strictEqual(last(r).msg.fuel_full_scale, true);
});

t('sensor error after 5 min without a valid reading', function () {
  var r = feed([[0, 80, false], [3, 'error', false], [7, 'error', false]]);
  assert.strictEqual(r[1].msg.fuel_sensor_ok, true);
  assert.strictEqual(last(r).msg.fuel_status, 'SENSOR ERROR');
});

t('LOW and CRITICAL bands', function () {
  assert.strictEqual(last(feed([[0, 25, false]])).msg.fuel_status, 'LOW');
  assert.strictEqual(last(feed([[0, 10, false]])).msg.fuel_status, 'CRITICAL');
  assert.strictEqual(last(feed([[0, 40, false]], {config: {fuel_low_pct: 50}})).msg.fuel_status, 'LOW');
});

t('burn rate measured only after leaving full scale, learned at run end, runtime + litres', function () {
  var s = [].concat(
    ramp(0, 20, 100, 100, true),          // capped: no measurement yet
    ramp(21, 140, 99.5, 75.5, true),      // 24% in ~2 h = ~12 %/h
    ramp(141, 160, 75.5, 75.5, false));
  var r = feed(s, {config: {fuel_tank_capacity_l: 1000}});
  var mid = r[100].msg;
  assert.strictEqual(mid.fuel_burn_basis, 'current run');
  assert.ok(Math.abs(mid.fuel_burn_pct_h - 12.1) < 1, 'burn ' + mid.fuel_burn_pct_h);
  var end = last(r).msg;
  assert.ok(/learned from 1 run/.test(end.fuel_burn_basis));
  assert.ok(Math.abs(end.fuel_runtime_h - 75.5 / 12.1) < 0.6, 'runtime ' + end.fuel_runtime_h);
  assert.strictEqual(end.fuel_litres, 755);
  assert.ok(end.fuel_burn_lph > 110 && end.fuel_burn_lph < 130);
});

t('refuel detected once, with amount and FULL flag', function () {
  var s = [].concat(ramp(0, 30, 83.3, 83.3, false), [[31, 87.6, false], [32, 97.6, false], [33, 100, false], [34, 100, false], [35, 100, false]],
    ramp(36, 60, 100, 100, false));
  var r = feed(s, {config: {fuel_tank_capacity_l: 1000}});
  var events = r.filter(function (x) { return x.msg.fuel_event; });
  assert.strictEqual(events.length, 1, JSON.stringify(events.map(function (e) { return e.msg.fuel_event; })));
  assert.ok(/Refuel >= \+16\.7% \(83\.3% to FULL\)/.test(events[0].msg.fuel_event), events[0].msg.fuel_event);
  assert.strictEqual(last(r).msg.fuel_last_refuel_full, true);
  assert.strictEqual(last(r).msg.fuel_last_refuel_l, 167);
});

t('no refuel/drop event from the level settling right after a run', function () {
  var s = [].concat(ramp(0, 60, 90, 80, true), [[61, 82, false], [62, 84, false], [63, 84, false]], ramp(64, 90, 84, 84, false));
  var r = feed(s);
  assert.strictEqual(r.filter(function (x) { return x.msg.fuel_event; }).length, 0);
});

t('fuel drop with DG stopped raises DROP once, refuel clears it', function () {
  var s = [].concat(ramp(0, 30, 90, 90, false), ramp(31, 50, 90, 82, false), ramp(51, 70, 82, 82, false),
    [[71, 95, false], [72, 95, false], [73, 95, false]], ramp(74, 100, 95, 95, false));
  var r = feed(s);
  var drops = r.filter(function (x) { return x.metadata.fuel_alarm === 'DROP'; });
  assert.strictEqual(drops.length, 1);
  assert.ok(/fuel dropped/.test(drops[0].metadata.fuel_alarm_message));
  assert.strictEqual(r.filter(function (x) { return x.metadata.fuel_alarm === 'CLEAR_DROP'; }).length, 1);
  assert.strictEqual(last(r).msg.fuel_drop_active, false);
});

t('jitter of +-0.5% never triggers events', function () {
  var s = [];
  for (var m = 0; m < 600; m++) s.push([m, 98 + ((m * 7) % 11) / 10 - 0.5, false]);
  var r = feed(s);
  assert.strictEqual(r.filter(function (x) { return x.msg.fuel_event || x.metadata.fuel_alarm !== 'NONE'; }).length, 0);
});

t('bootstrapped learned burn gives runtime on standby', function () {
  var r = feed([[0, 80, false]], {state: {burn: 12, burnN: 5}});
  assert.strictEqual(last(r).msg.fuel_runtime_h, 6.7);
  assert.ok(/learned from 5/.test(last(r).msg.fuel_burn_basis));
});

t('100 spike while running is rejected; sustained rise is accepted', function () {
  var s = [].concat(ramp(0, 15, 90, 89, true), [[16, 100, true], [17, 100, true], [18, 89, true]], ramp(19, 25, 89, 88.5, true));
  var r = feed(s);
  for (var i = 0; i < r.length; i++) assert.ok(r[i].msg.fuel_level_pct < 91, 'sample ' + i + ' = ' + r[i].msg.fuel_level_pct);
  assert.ok(JSON.parse(last(r).metadata.fuel_state_out).spikes >= 2);
  var r2 = feed([].concat(ramp(0, 15, 90, 90, false), ramp(16, 30, 100, 100, false)));
  assert.strictEqual(last(r2).msg.fuel_status, 'FULL');
});

t('drop just before a start is not an alarm', function () {
  var s = [].concat(ramp(0, 30, 100, 100, false), [[31, 93.7, false], [32, 90.3, false], [33, 90.3, false], [34, 90.3, false]],
    ramp(35, 80, 90.3, 85, true));
  var r = feed(s);
  assert.strictEqual(r.filter(function (x) { return x.metadata.fuel_alarm === 'DROP'; }).length, 0);
});

console.log(passed + ' tests passed');
