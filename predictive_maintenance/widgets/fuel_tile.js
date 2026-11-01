// Markdown/HTML card text function: compact DG fuel KPI tile (top row), ISA-101 style:
// neutral when normal, amber LOW, red LOW-LOW, "BAD PV" on sensor failure. Data keys are addressed by label.
function esc(s) {
  return ('' + (s === undefined || s === null ? '' : s)).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\{/g, '&#123;').replace(/\}/g, '&#125;');
}
function val(r, k) {
  var v = r ? r[k] : undefined;
  return (v === undefined || v === null || v === '' || v === '--') ? null : v;
}
var r = (data && data.length) ? data[0] : null;
var INK = '#1f2933', MUTED = '#6b7785', LINE = '#d9dee4', TRACK = '#eef1f4', NORMAL = '#6b7785';
var AMBER = '#c77700', RED = '#c62828';
var status = val(r, 'Status') || 'SENSOR ERROR';
var lvl = val(r, 'Level');
var bad = status === 'SENSOR ERROR' || lvl === null;
var level = bad ? 0 : Math.max(0, Math.min(100, Number(lvl)));
var full = val(r, 'Full') === true || val(r, 'Full') === 'true';
var lo = Number(val(r, 'Low') || 30), ll = Number(val(r, 'Critical') || 15);
var abn = status === 'CRITICAL' ? RED : (status === 'LOW' ? AMBER : null);
var chip;
if (bad) chip = ['BAD PV', MUTED, '#fff'];
else if (status === 'CRITICAL') chip = ['LOW-LOW', RED, '#fff'];
else if (status === 'LOW') chip = ['LOW', AMBER, '#fff'];
else if (full) chip = ['SENSOR MAX', null, MUTED];
else chip = ['NORMAL', null, MUTED];
var chipHtml = '<span style="font-size:9px;font-weight:700;letter-spacing:.5px;padding:1px 6px;border-radius:2px;' +
  (chip[1] ? 'background:' + chip[1] + ';' : 'border:1px solid ' + LINE + ';') + 'color:' + chip[2] + ';">' + chip[0] + '</span>';
var rt = val(r, 'Runtime'), litres = val(r, 'Litres');
var sub = [];
if (litres !== null) sub.push((full ? '&ge; ' : '') + Number(litres).toLocaleString() + ' L');
if (rt !== null) sub.push((full ? '&ge; ' : '') + esc(rt) + ' h autonomy');
// Horizontal bar with L / LL limit marks
var bar = '<div style="position:relative;height:8px;background:' + TRACK + ';border:1px solid ' + LINE + ';">' +
  (bad ? '' : '<div style="position:absolute;left:0;top:0;bottom:0;width:' + level + '%;background:' + (abn || NORMAL) + ';"></div>') +
  '<div style="position:absolute;left:' + lo + '%;top:-3px;bottom:-3px;width:2px;background:' + AMBER + ';"></div>' +
  '<div style="position:absolute;left:' + ll + '%;top:-3px;bottom:-3px;width:2px;background:' + RED + ';"></div></div>';
return '<div style="height:100%;box-sizing:border-box;padding:10px 12px;display:flex;flex-direction:column;justify-content:space-between;gap:4px;font-family:Roboto,Arial,sans-serif;background:#fff;">' +
  '<div style="display:flex;justify-content:space-between;align-items:center;gap:6px;"><span style="font-size:11px;font-weight:600;letter-spacing:.6px;color:' + MUTED + ';">FUEL LEVEL</span>' + chipHtml + '</div>' +
  '<div style="display:flex;align-items:baseline;gap:4px;"><span style="font-size:28px;font-weight:600;color:' + (abn || INK) + ';line-height:1;font-variant-numeric:tabular-nums;">' +
  (bad ? '----' : (full ? '&ge;100.0' : level.toFixed(1))) + '</span><span style="font-size:12px;color:' + MUTED + ';">%</span></div>' +
  bar +
  '<div style="font-size:10px;color:' + MUTED + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + (sub.length ? sub.join(' &middot; ') : (bad ? 'No valid reading in 5 min' : '&nbsp;')) + '</div>' +
  '</div>';
