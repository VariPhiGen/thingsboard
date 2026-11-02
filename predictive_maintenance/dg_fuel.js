// DG fuel processing (body of the "DG Fuel" transform node). Runs on every DG message carrying the raw fuel level.
// Inputs:
//   msg.<keys.fuel_raw>            raw controller value (% of the sensor's calibrated span, or 'error')
//   metadata.<keys.status/rpm>     latest run state
//   metadata.ss_fuel_state         filter buffer, learned burn rate, refuel/drop tracking (server attribute)
//   metadata.ss_pm_config          engine (invalid codes) and limits: keys, valid ranges, running_status/rpm and
//                                  limits.fuel (thresholds, filter and event-detection parameters, tank capacity)
// No parameter is defined in this script; without the configuration the node reports fuel_status NOT CONFIGURED.
// Output msg: fuel_* telemetry shown on the DG dashboards. The raw fuel level is left untouched.
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
var S = parseJson(metadata.ss_fuel_state, {});
var CFG = parseJson(metadata.ss_pm_config, {});
var E = CFG.engine || {};
var L = CFG.limits || {};
var K = L.keys || {};
var F = L.fuel || {};
var REQ = ['low_pct', 'critical_pct', 'full_pct', 'drop_alarm_pct', 'refuel_detect_pct', 'filter_window_min', 'filter_max_samples',
           'sensor_timeout_min', 'spike_pct', 'spike_tolerance_pct', 'spike_hold_stopped_min', 'spike_hold_running_min',
           'full_scale_input', 'valid_input', 'burn_min_run_h', 'burn_min_used_pct', 'burn_learn_min_h', 'burn_learn_min_used_pct',
           'burn_learn_weight', 'settle_min', 'event_window_min', 'refuel_end_min', 'refuel_step_pct', 'drop_hold_min'];
var miss = [];
for (var qi = 0; qi < REQ.length; qi++) {
  if (F[REQ[qi]] === undefined || F[REQ[qi]] === null || F[REQ[qi]] === '') miss.push('fuel.' + REQ[qi]);
}
if (!E.invalid_codes || E.invalid_at_or_above === undefined) miss.push('engine.invalid_codes');
if (!K.fuel_raw || !K.status || !K.rpm || !L.valid || !L.valid.rpm || L.running_rpm === undefined || !L.running_status) miss.push('keys / running state');
if (miss.length) {
  metadata.fuel_state_out = JSON.stringify(S);
  metadata.fuel_alarm = 'NONE';
  metadata.fuel_alarm_message = '';
  return {msg: {fuel_status: 'NOT CONFIGURED', fuel_sensor_ok: false, fuel_config_missing: miss.join(', ')}, metadata: metadata, msgType: 'POST_TELEMETRY_REQUEST'};
}

function num(v, lo, hi) {
  if (v === null || v === undefined || v === '' || typeof v === 'boolean') return null;
  var n = Number(v);
  if (!isFinite(n) || E.invalid_codes.indexOf(n) >= 0 || n >= Number(E.invalid_at_or_above)) return null;
  if (n < lo || n > hi) return null;
  return n;
}
function r1(x) { return Math.round(x * 10) / 10; }
function r2(x) { return Math.round(x * 100) / 100; }
function meta(k) {
  var m = metadata[k];
  var o = parseJson(m, null);
  return o && typeof o === 'object' && o.value !== undefined ? o.value : m;
}

var cap = Number(F.tank_capacity_l) || 0;
var LOW = Number(F.low_pct), CRIT = Number(F.critical_pct), FULL = Number(F.full_pct);
var DROP_PCT = Number(F.drop_alarm_pct), REFUEL_PCT = Number(F.refuel_detect_pct);
var WIN = Number(F.filter_window_min) * MIN, EVT = Number(F.event_window_min) * MIN;
if (!S.buf) S.buf = [];

// ---------- run state ----------
var rpm = num(msg[K.rpm] !== undefined ? msg[K.rpm] : meta(K.rpm), Number(L.valid.rpm[0]), Number(L.valid.rpm[1]));
var status = msg[K.status] || meta(K.status);
var running = status === L.running_status || (rpm !== null && rpm > Number(L.running_rpm));

// ---------- filter: median of the valid readings of the filter window ----------
var raw = num(msg[K.fuel_raw], Number(F.valid_input[0]), Number(F.valid_input[1]));
if (raw !== null) {
  raw = Math.min(raw, Number(F.full_scale_input));
  S.lastValidTs = NOW;
  // Spike rejection: the level cannot jump up quickly (a stopped DG is refuelled gradually, a running DG
  // only consumes). Some senders read full scale on a loose contact. An upward jump larger than spike_pct
  // is held back until it has persisted the configured hold time (stopped / running).
  if (S.level !== undefined && raw - S.level > Number(F.spike_pct)) {
    if (!S.pending || Math.abs(raw - S.pending.v) > Number(F.spike_tolerance_pct)) S.pending = {v: raw, since: NOW};
    var hold = (running ? Number(F.spike_hold_running_min) : Number(F.spike_hold_stopped_min)) * MIN;
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
  if (NOW - S.buf[i][0] <= WIN) keep.push(S.buf[i]);
}
S.buf = keep.slice(-Number(F.filter_max_samples));

var out = {};
var alarm = 'NONE', alarmMsg = '';
var sensorOk = S.lastValidTs && NOW - S.lastValidTs <= Number(F.sensor_timeout_min) * MIN;

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
    if (!S.run.capped && elH >= Number(F.burn_min_run_h) && used >= Number(F.burn_min_used_pct)) curBurn = used / elH;
    S.refuel = null;
    S.dropCand = null;
    S.base = {v: level, ts: NOW};
    S.high = {v: level, ts: NOW};
  } else {
    if (S.run) {
      var eh = (NOW - S.run.t0) / HOUR;
      var u = S.run.l0 - level;
      if (!S.run.capped && eh >= Number(F.burn_learn_min_h) && u >= Number(F.burn_learn_min_used_pct)) {
        var rate = u / eh, wgt = Number(F.burn_learn_weight);
        S.burn = S.burn ? r2((1 - wgt) * S.burn + wgt * rate) : r2(rate);
        S.burnN = (S.burnN || 0) + 1;
        S.burnTs = NOW;
      }
      S.run = null;
      S.base = {v: level, ts: NOW};
      S.high = {v: level, ts: NOW};
    }
    var settled = !S.lastRunTs || NOW - S.lastRunTs > Number(F.settle_min) * MIN;
    if (!settled) {
      // The level settles in the first minutes after a stop: re-anchor instead of reporting an event
      S.base = {v: level, ts: NOW};
      S.high = {v: level, ts: NOW};
    }
    if (!S.base || level < S.base.v || NOW - S.base.ts > EVT) S.base = {v: level, ts: NOW};
    if (!S.high || level > S.high.v || NOW - S.high.ts > EVT) S.high = {v: level, ts: NOW};

    // Refuel / drop events only once the engine has been stopped the settle time
    if (settled) {
      if (!S.refuel && level - S.base.v >= REFUEL_PCT) {
        S.refuel = {start: S.base.ts, from: S.base.v, to: level, last: NOW};
      } else if (S.refuel && level > S.refuel.to + Number(F.refuel_step_pct)) {
        S.refuel.to = level;
        S.refuel.last = NOW;
      }
      if (S.refuel && NOW - S.refuel.last > Number(F.refuel_end_min) * MIN) {
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
      // A drop must hold the configured time with the DG still stopped (a start or a sensor recovering is not a drop)
      if (!S.refuel && !S.dropActive && !S.dropCand && S.high.v - level >= DROP_PCT) {
        S.dropCand = {ts: NOW, from: S.high.v};
      }
      if (S.dropCand && S.dropCand.from - level < DROP_PCT) S.dropCand = null;
      if (S.dropCand && NOW - S.dropCand.ts >= Number(F.drop_hold_min) * MIN) {
        var dropped = S.dropCand.from - level;
        S.dropActive = {ts: NOW, from: r1(S.dropCand.from), to: r1(level)};
        out.fuel_event = 'Fuel drop -' + r1(dropped) + '% with DG stopped (' + r1(S.dropCand.from) + '% to ' + r1(level) + '%)';
        alarm = 'DROP';
        alarmMsg = metadata.deviceName + ': fuel dropped ' + r1(dropped) + '% (' + r1(S.dropCand.from) + '% to ' + r1(level) +
          '%) with the DG stopped and has stayed low ' + F.drop_hold_min + ' min. Possible leak or unauthorised draw.' + (cap ? ' About ' + Math.round(dropped * cap / 100) + ' L.' : '');
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
