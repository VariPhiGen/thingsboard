// DG fuel processing (body of the "DG Fuel" transform node). Runs on every DG message carrying fuel_level.
// Inputs:
//   msg.fuel_level                 raw controller value (% of the sensor's calibrated span, or 'error')
//   metadata.dg_status / engine_rpm  latest run state
//   metadata.ss_fuel_state         filter buffer, learned burn rate, refuel/drop tracking (server attribute)
//   metadata.ss_pm_config          fuel_tank_capacity_l, fuel_low_pct, fuel_critical_pct, fuel_drop_alarm_pct,
//                                  fuel_refuel_detect_pct
// Output msg: fuel_* telemetry shown on the DG dashboards. The raw fuel_level is left untouched.
// Output metadata: fuel_state_out (saved back), fuel_alarm (DROP | CLEAR_DROP | NONE), fuel_alarm_message.
// Written in ES5 with braces on every block: the Nashorn sandbox rejects the words f-o-r, w-h-i-l-e and d-o
// in strings and comments, so texts avoid them (test_dg_fuel.js enforces this).

var NOW = Number(metadata.ts);
if (!isFinite(NOW) || NOW <= 0) NOW = Date.now();
var MIN = 60000, HOUR = 3600000;

function parseJson(s, d) {
  if (s === null || s === undefined || s === '') return d;
  if (typeof s === 'object') return s;
  try { return JSON.parse(s); } catch (e) { return d; }
}
function num(v, lo, hi) {
  if (v === null || v === undefined || v === '' || typeof v === 'boolean') return null;
  var n = Number(v);
  if (!isFinite(n) || n === 32767 || n === 65535 || n >= 30000) return null;
  if (n < lo || n > hi) return null;
  return n;
}
function r1(x) { return Math.round(x * 10) / 10; }
function r2(x) { return Math.round(x * 100) / 100; }

var S = parseJson(metadata.ss_fuel_state, {});
var CFG = parseJson(metadata.ss_pm_config, {});
var cap = Number(CFG.fuel_tank_capacity_l) || 0;
var LOW = Number(CFG.fuel_low_pct) || 30;
var CRIT = Number(CFG.fuel_critical_pct) || 15;
var DROP_PCT = Number(CFG.fuel_drop_alarm_pct) || 5;
var REFUEL_PCT = Number(CFG.fuel_refuel_detect_pct) || 5;
var FULL = 99.95;
if (!S.buf) S.buf = [];

// ---------- run state ----------
var rpm = num(msg.engine_rpm !== undefined ? msg.engine_rpm : metadata.engine_rpm, 0, 3000);
var status = msg.dg_status || metadata.dg_status;
var running = status === 'RUNNING' || (rpm !== null && rpm > 300);

// ---------- filter: median of the valid readings of the last 10 min (max 5) ----------
var raw = num(msg.fuel_level, 0, 110);
if (raw !== null) {
  raw = Math.min(raw, 100);
  S.lastValidTs = NOW;
  // Spike rejection: the level cannot jump up quickly (a stopped DG is refuelled gradually, a running DG
  // only consumes). Some senders read full scale (100) on a loose contact. An upward jump of more than 3%
  // is held back until it has persisted 3 min (stopped) / 10 min (running).
  if (S.level !== undefined && raw - S.level > 3) {
    if (!S.pending || Math.abs(raw - S.pending.v) > 1.5) S.pending = {v: raw, since: NOW};
    var hold = running ? 10 * MIN : 3 * MIN;
    if (NOW - S.pending.since >= hold) {
      S.buf = [[NOW, raw]];
      S.pending = null;
    } else {
      S.spikes = (S.spikes || 0) + 1;
    }
  } else {
    S.pending = null;
    S.buf.push([NOW, raw]);
  }
}
var keep = [];
for (var i = 0; i < S.buf.length; i++) {
  if (NOW - S.buf[i][0] <= 10 * MIN) keep.push(S.buf[i]);
}
S.buf = keep.slice(-5);

var out = {};
var alarm = 'NONE', alarmMsg = '';
var sensorOk = S.lastValidTs && NOW - S.lastValidTs <= 5 * MIN;

if (!S.buf.length || !sensorOk) {
  out.fuel_sensor_ok = false;
  out.fuel_status = 'SENSOR ERROR';
} else {
  var vals = [];
  for (var j = 0; j < S.buf.length; j++) {
    vals.push(S.buf[j][1]);
  }
  vals.sort(function (a, b) { return a - b; });
  var level = vals[Math.floor(vals.length / 2)];
  S.level = level;
  var full = level >= FULL;

  // ---------- burn rate (only measured once the level is below the sensor's full scale) ----------
  var curBurn = null;
  if (running) {
    S.lastRunTs = NOW;
    if (!S.run || (S.run.capped && !full)) S.run = {t0: NOW, l0: level, capped: full};
    var elH = (NOW - S.run.t0) / HOUR;
    var used = S.run.l0 - level;
    if (!S.run.capped && elH >= 1 / 6 && used >= 1) curBurn = used / elH;
    S.refuel = null;
    S.dropCand = null;
    S.base = {v: level, ts: NOW};
    S.high = {v: level, ts: NOW};
  } else {
    if (S.run) {
      var eh = (NOW - S.run.t0) / HOUR;
      var u = S.run.l0 - level;
      if (!S.run.capped && eh >= 1 / 3 && u >= 2) {
        var rate = u / eh;
        S.burn = S.burn ? r2(0.6 * S.burn + 0.4 * rate) : r2(rate);
        S.burnN = (S.burnN || 0) + 1;
        S.burnTs = NOW;
      }
      S.run = null;
      S.base = {v: level, ts: NOW};
      S.high = {v: level, ts: NOW};
    }
    var settled = !S.lastRunTs || NOW - S.lastRunTs > 10 * MIN;
    if (!settled) {
      // The level settles in the first minutes after a stop: re-anchor instead of reporting an event
      S.base = {v: level, ts: NOW};
      S.high = {v: level, ts: NOW};
    }
    if (!S.base || level < S.base.v || NOW - S.base.ts > HOUR) S.base = {v: level, ts: NOW};
    if (!S.high || level > S.high.v || NOW - S.high.ts > HOUR) S.high = {v: level, ts: NOW};

    // Refuel / drop events only once the engine has been stopped 10 min
    if (settled) {
      if (!S.refuel && level - S.base.v >= REFUEL_PCT) {
        S.refuel = {start: S.base.ts, from: S.base.v, to: level, last: NOW};
      } else if (S.refuel && level > S.refuel.to + 0.2) {
        S.refuel.to = level;
        S.refuel.last = NOW;
      }
      if (S.refuel && NOW - S.refuel.last > 10 * MIN) {
        var added = S.refuel.to - S.refuel.from;
        S.lastRefuel = {ts: S.refuel.last, from: r1(S.refuel.from), to: r1(S.refuel.to), pct: r1(added), full: S.refuel.to >= FULL};
        out.fuel_event = 'Refuel ' + (S.lastRefuel.full ? '>= +' : '+') + r1(added) + '% (' + r1(S.refuel.from) + '% to ' + (S.lastRefuel.full ? 'FULL' : r1(S.refuel.to) + '%') + ')';
        if (S.dropActive) {
          alarm = 'CLEAR_DROP';
          alarmMsg = metadata.deviceName + ': refuelled after the fuel drop.';
          S.dropActive = null;
        }
        S.refuel = null;
        S.base = {v: level, ts: NOW};
        S.high = {v: level, ts: NOW};
      }
      // A drop must hold 10 min with the DG still stopped (a start or a sensor recovering is not a drop)
      if (!S.refuel && !S.dropActive && !S.dropCand && S.high.v - level >= DROP_PCT) {
        S.dropCand = {ts: NOW, from: S.high.v};
      }
      if (S.dropCand && S.dropCand.from - level < DROP_PCT) S.dropCand = null;
      if (S.dropCand && NOW - S.dropCand.ts >= 10 * MIN) {
        var dropped = S.dropCand.from - level;
        S.dropActive = {ts: NOW, from: r1(S.dropCand.from), to: r1(level)};
        out.fuel_event = 'Fuel drop -' + r1(dropped) + '% with DG stopped (' + r1(S.dropCand.from) + '% to ' + r1(level) + '%)';
        alarm = 'DROP';
        alarmMsg = metadata.deviceName + ': fuel dropped ' + r1(dropped) + '% (' + r1(S.dropCand.from) + '% to ' + r1(level) +
          '%) with the DG stopped and has stayed low 10 min. Possible leak or unauthorised draw.' + (cap ? ' About ' + Math.round(dropped * cap / 100) + ' L.' : '');
        S.dropCand = null;
      }
    }
  }

  // ---------- outputs ----------
  out.fuel_sensor_ok = true;
  out.fuel_level_pct = r1(level);
  out.fuel_full_scale = full;
  out.fuel_status = full ? 'FULL' : (level < CRIT ? 'CRITICAL' : (level < LOW ? 'LOW' : 'OK'));
  out.fuel_low_pct = LOW;
  out.fuel_critical_pct = CRIT;
  var burn = curBurn !== null ? curBurn : (S.burn || null);
  out.fuel_burn_basis = curBurn !== null ? 'current run' : (S.burn ? 'learned from ' + (S.burnN || 1) + ' run(s)' : 'not learned yet');
  if (burn) {
    out.fuel_burn_pct_h = r2(burn);
    out.fuel_runtime_h = r1(level / burn);
  } else {
    out.fuel_burn_pct_h = '--';
    out.fuel_runtime_h = '--';
  }
  if (cap) {
    out.fuel_capacity_l = cap;
    out.fuel_litres = Math.round(level * cap / 100);
    out.fuel_burn_lph = burn ? r1(burn * cap / 100) : '--';
  }
  if (S.lastRefuel) {
    out.fuel_last_refuel_ts = S.lastRefuel.ts;
    out.fuel_last_refuel_pct = S.lastRefuel.pct;
    out.fuel_last_refuel_full = S.lastRefuel.full;
    if (cap) out.fuel_last_refuel_l = Math.round(S.lastRefuel.pct * cap / 100);
  }
  out.fuel_drop_active = !!S.dropActive;
}

S.v = 1;
metadata.fuel_state_out = JSON.stringify(S);
metadata.fuel_alarm = alarm;
metadata.fuel_alarm_message = alarmMsg;
return {msg: out, metadata: metadata, msgType: 'POST_TELEMETRY_REQUEST'};
