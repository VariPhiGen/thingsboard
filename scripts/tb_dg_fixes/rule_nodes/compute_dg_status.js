// Runs only after 'Has Valid DG Reading'. RPM decides when valid, otherwise power.
// dg_status changes only after the new state has held for HOLD_MS, so a Modbus read error or the
// engine coasting down during a stop cannot flap the status (and the DG Offline alarm / Telegram).
// State lives in server attributes dg_state_* (fetched by 'Fetch DG State', saved by 'Save DG State').
var HOLD_MS = {RUNNING: 60000, OFF: 120000};

function valid(v, lo, hi) {
  if (v === null || typeof v === 'undefined' || v === '') return null;
  var n = Number(v);
  if (!isFinite(n) || n === 32767 || n === 65535 || n < lo || n > hi) return null;
  return n;
}
function state(v) {
  return (v === 'RUNNING' || v === 'OFF') ? v : null;
}

var rpm = valid(msg.engine_rpm, 0, 3000);
var pwr = valid(msg.power_kw, 0, 5000);
var running = rpm !== null ? (rpm > 100 || (pwr !== null && pwr > 5)) : pwr > 5;
var raw = running ? 'RUNNING' : 'OFF';

var ts = Number(metadata.ts);
if (!isFinite(ts) || ts <= 0) ts = Date.now();

// First message after deployment: continue from the last saved dg_status
var confirmed = state(metadata.ss_dg_state_confirmed) || state(metadata.dg_status) || raw;
var candidate = state(metadata.ss_dg_state_candidate);
var since = Number(metadata.ss_dg_state_candidate_ts);
if (candidate !== raw || !isFinite(since) || since <= 0) {
  candidate = raw;
  since = ts;
}
if (raw !== confirmed && ts - since >= HOLD_MS[raw]) {
  confirmed = raw;
}

metadata.dg_state_confirmed = confirmed;
metadata.dg_state_candidate = candidate;
metadata.dg_state_candidate_ts = '' + since;
return {msg: {dg_status: confirmed}, metadata: metadata, msgType: 'POST_TELEMETRY_REQUEST'};
