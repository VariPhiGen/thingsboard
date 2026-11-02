// Replays dg_fuel.js over historical samples to bootstrap fuel_state (learned burn rate, last refuel).
// Usage: node replay_fuel.js samples.json   (samples: [[ts, raw fuel level, run status, rpm], ...] ascending;
//        telemetry keys come from config.limits.keys)
// Prints {"state": ..., "events": [[ts, text], ...], "alarms": [[ts, alarm, message], ...]}
var fs = require('fs');
var path = require('path');
var body = fs.readFileSync(path.join(__dirname, 'dg_fuel.js'), 'utf8');
var fuel = new Function('msg', 'metadata', 'msgType', body);
var input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
var state = '', events = [], alarms = [];
var config = input.config ? JSON.stringify(input.config) : '';
var K = (input.config && input.config.limits && input.config.limits.keys) || {};
for (var i = 0; i < input.samples.length; i++) {
  var s = input.samples[i];
  var md = {ts: '' + s[0], deviceName: input.name || 'DG', ss_fuel_state: state, ss_pm_config: config,
    };
  md[K.status] = s[2] || '';
  md[K.rpm] = s[3] === null || s[3] === undefined ? '' : '' + s[3];
  var m = {};
  m[K.fuel_raw] = s[1];
  var r = fuel(m, md, 'POST_TELEMETRY_REQUEST');
  state = r.metadata.fuel_state_out;
  if (r.msg.fuel_event) events.push([s[0], r.msg.fuel_event]);
  if (r.metadata.fuel_alarm !== 'NONE') alarms.push([s[0], r.metadata.fuel_alarm, r.metadata.fuel_alarm_message]);
}
console.log(JSON.stringify({state: JSON.parse(state || '{}'), events: events, alarms: alarms}));
