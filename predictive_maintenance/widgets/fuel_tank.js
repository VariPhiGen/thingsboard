// Markdown/HTML card text function: DG fuel tank faceplate (ISA-101 high-performance HMI style).
// Grey when normal, colour only for abnormal states (amber LOW, red LOW-LOW), "BAD PV" when the sensor fails.
// Data keys are addressed by label (see FUEL_KEYS in deploy_pm.py).
function esc(s) {
  return ('' + (s === undefined || s === null ? '' : s)).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\{/g, '&#123;').replace(/\}/g, '&#125;');
}
function val(r, k) {
  var v = r ? r[k] : undefined;
  return (v === undefined || v === null || v === '' || v === '--') ? null : v;
}
function isTrue(v) { return v === true || v === 'true'; }
function ago(ts) {
  var n = Number(ts);
  if (!isFinite(n) || n <= 0) return null;
  var m = Math.max(0, Math.round((Date.now() - n) / 60000));
  return m < 60 ? m + ' min ago' : (m < 2880 ? Math.round(m / 60) + ' h ago' : Math.round(m / 1440) + ' d ago');
}
function stamp(ts) {
  var n = Number(ts);
  if (!isFinite(n) || n <= 0) return null;
  var d = new Date(n);
  return d.toLocaleDateString(undefined, {day: '2-digit', month: 'short'}) + ' ' + d.toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit', hour12: false});
}

var r = (data && data.length) ? data[0] : null;
var INK = '#1f2933', MUTED = '#6b7785', LINE = '#d9dee4', TRACK = '#eef1f4', NORMAL = '#6b7785';
var AMBER = '#c77700', RED = '#c62828';
var status = val(r, 'Status') || 'SENSOR ERROR';
var lvl = val(r, 'Level');
var bad = status === 'SENSOR ERROR' || lvl === null;
var level = bad ? 0 : Math.max(0, Math.min(100, Number(lvl)));
var full = isTrue(val(r, 'Full'));
var lo = Number(val(r, 'Low') || 30), ll = Number(val(r, 'Critical') || 15);
var abn = status === 'CRITICAL' ? RED : (status === 'LOW' ? AMBER : null);
var fillCol = abn || NORMAL;

// ---- level indicator (HTML so it stretches to the full height of the faceplate) ----
// Position inside the track: bottom = 6px + (100% - 12px) * p / 100
function at(p) { return 'calc(6px + (100% - 12px) * ' + (p / 100) + ')'; }
var scale = '';
var marks = [0, 25, 50, 75, 100];
for (var i = 0; i < marks.length; i++) {
  scale += '<div style="position:absolute;left:0;width:18px;bottom:' + at(marks[i]) + ';transform:translateY(50%);text-align:right;font-size:9px;line-height:9px;color:' + MUTED + ';">' + marks[i] + '</div>' +
    '<div style="position:absolute;left:21px;width:5px;height:1px;bottom:' + at(marks[i]) + ';background:' + MUTED + ';"></div>';
}
function limit(p, col, tag) {
  return '<div style="position:absolute;left:26px;width:30px;height:2px;bottom:' + at(p) + ';transform:translateY(50%);background:' + col + ';"></div>' +
    '<div style="position:absolute;left:58px;bottom:' + at(p) + ';transform:translateY(50%);font-size:9px;line-height:9px;font-weight:700;color:' + col + ';">' + tag + '</div>';
}
var bar = '<div style="position:relative;height:100%;min-height:140px;width:72px;">' + scale +
  '<div style="position:absolute;left:28px;width:26px;top:6px;bottom:6px;background:' + TRACK + ';border:1px solid ' + (bad ? MUTED : LINE) + ';' + (bad ? 'border-style:dashed;' : '') + 'box-sizing:border-box;">' +
  (bad ? '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:' + MUTED + ';">?</div>'
       : '<div style="position:absolute;left:0;right:0;bottom:0;height:' + level + '%;background:' + fillCol + ';border-top:2px solid ' + INK + ';box-sizing:border-box;"></div>') +
  '</div>' +
  (full && !bad ? '<div style="position:absolute;left:35px;top:-4px;width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;border-bottom:7px solid ' + MUTED + ';" title="Above sensor range"></div>' : '') +
  limit(lo, AMBER, 'L') + limit(ll, RED, 'LL') +
  '</div>';

// ---- primary value ----
var big = bad ? '----' : (full ? '&ge;100.0' : level.toFixed(1));
var chip = '';
if (bad) chip = '<span style="background:' + MUTED + ';color:#fff;">BAD PV</span>';
else if (status === 'CRITICAL') chip = '<span style="background:' + RED + ';color:#fff;">LOW-LOW</span>';
else if (status === 'LOW') chip = '<span style="background:' + AMBER + ';color:#fff;">LOW</span>';
else if (full) chip = '<span style="border:1px solid ' + MUTED + ';color:' + MUTED + ';">SENSOR MAX</span>';
else chip = '<span style="border:1px solid ' + LINE + ';color:' + MUTED + ';">NORMAL</span>';
chip = chip.replace('<span style="', '<span style="display:inline-block;font-size:9px;font-weight:700;letter-spacing:.5px;padding:1px 6px;border-radius:2px;');
if (isTrue(val(r, 'Drop'))) chip += ' <span style="display:inline-block;font-size:9px;font-weight:700;letter-spacing:.5px;padding:1px 6px;border-radius:2px;background:' + RED + ';color:#fff;">FUEL DROP</span>';

var cap = val(r, 'Capacity'), litres = val(r, 'Litres');
var ge = full && !bad ? '&ge; ' : '';
var volume = litres !== null ? ge + Number(litres).toLocaleString() + ' L' + (cap ? '<span style="color:' + MUTED + ';font-weight:400;"> / ' + Number(cap).toLocaleString() + ' L</span>' : '') : '<span style="color:' + MUTED + ';font-weight:400;">Capacity not set</span>';
var rt = val(r, 'Runtime'), burn = val(r, 'Burn'), lph = val(r, 'BurnLph'), basis = val(r, 'Basis');
var autonomy = rt !== null ? (full ? '&ge; ' : '') + esc(rt) + ' h' : '--';

function kv(label, value, sub, alignRight) {
  return '<div style="min-width:0;' + (alignRight ? 'text-align:right;' : '') + '">' +
    '<div style="font-size:9px;font-weight:600;letter-spacing:.6px;color:' + MUTED + ';">' + label + '</div>' +
    '<div style="font-size:13px;font-weight:600;color:' + INK + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + value + '</div>' +
    (sub ? '<div style="font-size:10px;color:' + MUTED + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + sub + '</div>' : '') + '</div>';
}

var head = '<div style="display:flex;flex-direction:column;gap:8px;min-width:0;flex:1;">' +
  '<div><div style="font-size:9px;font-weight:600;letter-spacing:.6px;color:' + MUTED + ';">LEVEL</div>' +
  '<div style="display:flex;align-items:baseline;gap:4px;"><span style="font-size:30px;font-weight:600;color:' + (abn || INK) + ';line-height:1.05;font-variant-numeric:tabular-nums;">' + big + '</span>' +
  '<span style="font-size:13px;color:' + MUTED + ';">%</span></div><div style="margin-top:3px;">' + chip + '</div></div>' +
  kv('VOLUME', volume) +
  kv('AUTONOMY', autonomy, burn !== null ? 'at ' + esc(burn) + ' %/h' + (basis ? ' &middot; ' + esc(basis) : '') : esc(basis || '')) +
  '</div>';

var rfp = val(r, 'RefuelPct'), rfl = val(r, 'RefuelL'), rfFull = isTrue(val(r, 'RefuelFull'));
var refuel = rfp !== null ? (rfFull ? '&ge; +' : '+') + esc(rfp) + ' %' : '--';
var rfTs = val(r, 'RefuelTs');
var ev = val(r, 'Event');
var evTs = r ? r['Event|ts'] : null;
var upd = r ? r['Level|ts'] : null;

var grid = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 12px;padding-top:8px;border-top:1px solid ' + LINE + ';">' +
  kv('BURN RATE', burn !== null ? esc(burn) + ' %/h' : '--', lph !== null ? esc(lph) + ' L/h' : '') +
  kv('LAST REFUEL', refuel, (rfTs ? stamp(rfTs) : '') + (rfl !== null ? ' &middot; ' + (rfFull ? '&ge; ' : '') + esc(rfl) + ' L' : ''), true) +
  '</div>';
var event = '<div style="padding-top:8px;border-top:1px solid ' + LINE + ';min-width:0;">' +
  '<div style="font-size:9px;font-weight:600;letter-spacing:.6px;color:' + MUTED + ';">LAST EVENT' + (evTs && ev !== null ? ' &middot; ' + stamp(evTs) : '') + '</div>' +
  '<div style="font-size:11px;color:' + INK + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + esc(ev || '') + '">' + (ev !== null ? esc(ev).replace(/&gt;=/g, '&ge;') : 'None recorded') + '</div></div>';
var foot = '<div style="display:flex;justify-content:space-between;font-size:9px;color:' + MUTED + ';">' +
  '<span>Fuel sender &middot; ' + (bad ? 'no valid reading' : (full ? 'at full scale' : 'OK')) + '</span>' +
  '<span>' + (upd ? 'Updated ' + ago(upd) : '') + '</span></div>';

return '<div style="height:100%;box-sizing:border-box;padding:6px 12px 8px;display:flex;flex-direction:column;gap:8px;font-family:Roboto,Arial,sans-serif;background:#fff;overflow:hidden;">' +
  '<div style="flex:1;min-height:0;display:flex;gap:10px;">' +
  '<div style="flex:0 0 72px;width:72px;min-height:0;padding:4px 0;box-sizing:border-box;">' + bar + '</div>' + head + '</div>' +
  grid + event + foot + '</div>';
