// End-to-end test of the Maintenance Management widget in jsdom against a fake ThingsBoard that behaves like the real
// one where it matters: null attribute values are rejected (HTTP 500), duplicate asset names are rejected (HTTP 400),
// entity-query values come back as strings. All configuration comes from cmms/settings_seed.json and pm_seed.json.
// Run: NODE_PATH=<a node_modules folder containing jsdom> node period_reports/tests/test_maintenance_planner.js
const {JSDOM} = require('jsdom');
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const ROOT = path.join(__dirname, '..', '..');
const SRC = fs.readFileSync(path.join(ROOT, 'period_reports', 'widgets', 'maintenance_planner.js'), 'utf8');
const SEED = JSON.parse(fs.readFileSync(path.join(ROOT, 'cmms', 'settings_seed.json'), 'utf8'));
const PM_SEED = JSON.parse(fs.readFileSync(path.join(ROOT, 'predictive_maintenance', 'pm_seed.json'), 'utf8'));
delete SEED._note;

const dom = new JSDOM('<!doctype html><div id="w"></div>', {url: 'https://viot.example/'});
const {window} = dom;
Object.assign(global, {window, document: window.document, FormData: window.FormData, Blob: window.Blob, atob: window.atob});
global.URL = window.URL; URL.createObjectURL = () => 'blob:x'; URL.revokeObjectURL = () => {};
window.Element.prototype.scrollIntoView = function () {};
window.confirm = () => true;
let alerts = []; window.alert = (m) => alerts.push(m);
let printed = null; window.open = () => ({document: {write: (h) => { printed = h; }, close() {}}});
function login(sub, first) {
  window.localStorage.setItem('jwt_token', 'h.' + Buffer.from(JSON.stringify({sub, firstName: first, lastName: '', tenantId: 't1'})).toString('base64') + '.s');
}

// ------------------------------------------------------------- fake ThingsBoard
const db = {assets: {}, attrs: {}, relations: [], ts: [], resources: {}, hiddenNames: new Set()};
let seq = 0;
const devices = {dg1: {name: 'DG SET1', type: 'woodward_kg1500', keys: ['run_hours', 'battery_voltage']},
                 ro: {name: 'RO Plant System', type: 'RO System Profile', keys: ['tds_ppm']},
                 x9: {name: 'Unrelated meter', type: 'Some Other Profile', keys: ['run_hours']}};
db.assets.lib = {name: 'Maintenance Document Library', type: 'Maintenance Library'};
db.assets.set = {name: 'Maintenance Settings', type: 'Maintenance Settings'};
db.attrs.set = {cmms_settings: JSON.stringify(SEED), cmms_settings_rev: 1, pm_templates: JSON.stringify(PM_SEED)};
const dgPm = {kind: 'DG', engine: PM_SEED.engine, limits: JSON.parse(JSON.stringify(PM_SEED.kinds.DG))};
delete dgPm.limits.battery._scale_from_baseline; delete dgPm.limits.voltage._from_baseline;
db.attrs.dg1 = {pm_config: JSON.stringify(dgPm)};
const httpErr = (status, message) => { const e = new Error(message); e.status = status; e.error = {message}; return e; };
function obs(fn) { return {subscribe(ok, err) { setTimeout(() => { let r; try { r = fn(); } catch (e) { if (err) err(e); return; } ok(r); }, 0); }}; }
function ent(url) { const m = /telemetry\/(DEVICE|ASSET)\/([^/]+)\//.exec(url); return m[2]; }
const http = {
  get(url) {
    return obs(() => {
      const u = new URL('http://x' + url);
      if (u.pathname === '/api/tenant/devices') {
        return {data: Object.keys(devices).filter((k) => devices[k].type === u.searchParams.get('type')).map((k) => ({id: {id: k}, name: devices[k].name, type: devices[k].type})), hasNext: false};
      }
      if (u.pathname === '/api/deviceProfileInfos') return {data: ['woodward_kg1500', 'RO System Profile', 'Some Other Profile'].map((n) => ({name: n}))};
      if (/\/keys\/timeseries$/.test(u.pathname)) return devices[u.pathname.split('/')[5]].keys;
      if (/\/values\/timeseries$/.test(u.pathname)) {
        return u.pathname.includes('/dg1/') ? {run_hours: [{ts: 3, value: 'error'}, {ts: 2, value: '32767'}, {ts: 1, value: '166.1'}]} : {};
      }
      if (u.pathname === '/api/tenant/assets') {
        const id = Object.keys(db.assets).find((k) => db.assets[k].name === u.searchParams.get('assetName'));
        if (!id) throw httpErr(404, 'not found');
        return {id: {id}, name: db.assets[id].name};
      }
      if (u.pathname.endsWith('/values/attributes/SERVER_SCOPE')) {
        const a = db.attrs[ent(url)] || {};
        return u.searchParams.get('keys').split(',').filter((k) => k in a).map((k) => ({key: k, value: a[k]}));
      }
      if (u.pathname.endsWith('/download')) return new Blob(['x']);
      throw new Error('GET ' + url);
    });
  },
  post(url, body) {
    return obs(() => {
      if (url === '/api/entitiesQuery/find') {
        const f = body.entityFilter;
        const rows = Object.keys(db.assets).filter((id) => f.assetTypes.includes(db.assets[id].type) && db.assets[id].name.startsWith(f.assetNameFilter || '') && !db.hiddenNames.has(db.assets[id].name))
          .map((id) => ({entityId: {id}, latest: {ENTITY_FIELD: {name: {value: db.assets[id].name}},
            SERVER_ATTRIBUTE: Object.fromEntries(body.latestValues.map((k) => [k.key, {ts: 1, value: (db.attrs[id] || {})[k.key] == null ? '' : String(db.attrs[id][k.key])}]))}}));
        return {data: rows, hasNext: false};
      }
      if (url === '/api/asset') {
        if (Object.values(db.assets).some((a) => a.name === body.name)) throw httpErr(400, 'Asset with such name already exists!');
        const id = 'a' + (++seq); db.assets[id] = {name: body.name, type: body.type}; return {id: {id}, name: body.name};
      }
      if (url === '/api/relation') { db.relations.push(body); return null; }
      if (url === '/api/resource/upload') { const id = 'r' + (++seq); db.resources[id] = body.get('title'); return {id: {id}}; }
      if (url.endsWith('/attributes/SERVER_SCOPE')) {
        for (const k of Object.keys(body)) if (body[k] === null || body[k] === undefined) throw httpErr(500, "Can't parse value: null");
        const id = /telemetry\/(?:DEVICE|ASSET)\/([^/]+)\/attributes/.exec(url)[1];
        db.attrs[id] = Object.assign(db.attrs[id] || {}, body); return null;
      }
      if (url.endsWith('/timeseries/ANY')) { db.ts.push({id: /DEVICE\/([^/]+)\//.exec(url)[1], rec: JSON.parse(body[0].values.maintenance_record), ts: body[0].ts}); return null; }
      throw new Error('POST ' + url);
    });
  },
  delete(url) { return obs(() => { delete db.resources[url.split('/')[3]]; return null; }); },
};
const A = (id) => db.attrs[id] || {};
const J = (s) => (typeof s === 'string' && s ? JSON.parse(s) : s);
const woByNum = (n) => { const id = Object.keys(db.assets).find((k) => db.assets[k].name === n); return {id, a: A(id), d: J(A(id).wo_detail)}; };
const planId = (n) => Object.keys(db.assets).find((k) => db.assets[k].name === n);

// ------------------------------------------------------------- widget harness
let container, self;
function mount(user) {
  login(user[0], user[1]);
  document.body.innerHTML = '<div id="w"></div>';
  container = document.getElementById('w');
  if (self && self.onDestroy) self.onDestroy();
  self = {ctx: {$container: [container], http, datasources: [], data: []}};
  new Function('self', SRC)(self);
  self.onInit();
}
const tick = (n = 1) => new Promise((r) => setTimeout(r, 15 * n));
const $ = (s) => container.querySelector(s);
const $$ = (s) => [...container.querySelectorAll(s)];
const click = (el) => { assert.ok(el, 'element to click not found'); el.dispatchEvent(new window.MouseEvent('click', {bubbles: true})); };
function set(sel, v) { const el = $(sel); assert.ok(el, sel + ' missing'); el.value = v; el.dispatchEvent(new window.Event('change', {bubbles: true})); }
const tab = (name) => click($$('[data-tab]').find((b) => b.getAttribute('data-tab') === name));
const status = () => ($('.mp-panel-slot .mp-status') || {}).textContent || '';
const openWo = (num) => click($$('tr[data-act="viewwo"]').find((r) => r.textContent.includes(num)));
const act = (a) => click($('[data-act="' + a + '"]'));
const pad = (n) => (n < 10 ? '0' : '') + n;
const siteNow = () => new Date(Date.now() + SEED.timezone_offset_minutes * 60000 + new Date().getTimezoneOffset() * 60000);
const ymd = (d) => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
const plusDays = (n) => { const d = siteNow(); d.setDate(d.getDate() + n); return ymd(d); };
const YEAR = siteNow().getFullYear();
const workTime = () => { const d = new Date(Date.now() - 3600000 - new Date().getTimezoneOffset() * 60000); return d.toISOString().slice(0, 16); };
let passed = 0;
async function t(name, fn) { await fn(); passed++; console.log('ok -', name); }

(async () => {
  mount(['tech@site', 'Ravi']); await tick(8);

  await t('equipment comes from the configured profiles; meter reading skips text and invalid codes', async () => {
    assert.ok(/No work orders yet/.test(container.textContent));
    act('newwo'); await tick();
    const names = $$('.f-eq option').map((o) => o.textContent).filter(Boolean);
    assert.deepStrictEqual(names, ['DG SET1', 'RO Plant System']);                 // the third device's profile is not configured
    assert.strictEqual($('.f-type').value, ''); assert.strictEqual($('.f-pri').value, ''); assert.strictEqual($('.f-date').value, '');  // no defaults
    act('close'); await tick();
  });

  await t('upload a certificate (category, revision, expiry) to the general library', async () => {
    tab('docs'); await tick(); act('upload'); await tick();
    set('.u-eq', 'general'); set('.u-title', 'Fire NOC'); set('.u-rev', '2'); set('.u-exp', plusDays(20));
    Object.defineProperty($('.u-file'), 'files', {value: [new window.File(['%PDF'], 'noc.pdf')]});
    act('saveupload'); await tick(2);
    assert.ok(/category/.test(status()));
    set('.u-cat', 'Certificate'); act('saveupload'); await tick(8);
    const docs = J(A('lib').maint_docs);
    assert.strictEqual(docs.length, 1); assert.strictEqual(docs[0].category, 'Certificate'); assert.strictEqual(docs[0].expiry, plusDays(20));
    assert.ok(/Expires/.test(container.textContent));
  });

  await t('meter-based plan only for equipment that reports the meter; values entered, not defaulted', async () => {
    tab('plans'); await tick(); act('newplan'); await tick();
    set('.f-eq', 'ro'); assert.ok($('.f-str option[value="meter"]').disabled, 'RO has no meter');
    set('.f-eq', 'dg1'); assert.ok(!$('.f-str option[value="meter"]').disabled);
    assert.ok(/current reading: 166.1 run-h/.test(container.textContent));
    set('.f-title', '250 h service'); set('.f-type', 'Preventive'); set('.f-pri', 'P2'); set('.f-str', 'meter');
    act('saveplan'); await tick(); assert.ok(/interval and the next due meter reading/.test(status()));
    set('.f-irh', '250'); set('.f-nrh', '250'); set('.f-asg', 'Ravi'); $('.f-cl').value = 'Change engine oil\nReplace oil filter';
    act('saveplan'); await tick(8);
    const pid = planId('PL-0001');
    assert.strictEqual(A(pid).plan_strategy, 'meter'); assert.strictEqual(A(pid).plan_next_due_rh, 250); assert.strictEqual(A(pid).plan_priority, 'P2');
    assert.ok(db.relations.some((r) => r.from.id === 'dg1' && r.to.id === pid));
  });

  await t('time-based plan needs interval, next due date and lead days', async () => {
    act('newplan'); await tick();
    set('.f-eq', 'ro'); set('.f-title', 'Membrane cleaning'); set('.f-type', 'Preventive'); set('.f-pri', 'P3'); set('.f-str', 'time');
    set('.f-days', '30'); set('.f-date', plusDays(3)); act('saveplan'); await tick();
    assert.ok(/lead days/.test(status()));
    set('.f-lead', '7'); act('saveplan'); await tick(8);
    assert.strictEqual(A(planId('PL-0002')).plan_lead_days, 7);
  });

  await t('raise a WO from a plan; type list for plans comes from settings', async () => {
    click($$('[data-act="raisenow"]')[0]); await tick(10);
    const w = woByNum(`WO-${YEAR}-00001`);
    assert.strictEqual(w.a.wo_status, 'Scheduled'); assert.strictEqual(w.a.wo_due_rh, 250);
    assert.deepStrictEqual(w.d.checklist, ['Change engine oil', 'Replace oil filter']);
  });

  await t('manual WO: due date follows the configured response days of the priority; numbering retries', async () => {
    db.assets.race = {name: `WO-${YEAR}-00002`, type: 'Work Order'}; db.hiddenNames.add(`WO-${YEAR}-00002`);
    tab('wo'); await tick(); act('newwo'); await tick();
    set('.f-eq', 'ro'); set('.f-title', 'TDS probe reading erratic'); set('.f-type', 'Corrective'); set('.f-pri', 'P1');
    assert.strictEqual($('.f-date').value, plusDays(SEED.priorities[0].response_days));
    act('savewo'); await tick(10);
    const w = woByNum(`WO-${YEAR}-00003`);
    assert.ok(w.id); assert.strictEqual(w.a.wo_priority, 'P1');
  });

  await t('start, hold (reason required), resume', async () => {
    act('start'); await tick(8);
    act('hold'); await tick(); act('savereason'); await tick(); assert.ok(/reason/i.test(status()));
    set('.r-txt', 'Waiting for spare probe'); act('savereason'); await tick(8);
    assert.strictEqual(woByNum(`WO-${YEAR}-00003`).a.wo_status, 'On Hold');
    act('start'); await tick(8);
    assert.strictEqual(woByNum(`WO-${YEAR}-00003`).a.wo_status, 'In Progress');
  });

  await t('complete corrective WO: every value entered (time, labour, downtime, failure codes, part qty+rate)', async () => {
    act('complete'); await tick();
    assert.strictEqual($('.c-when').value, ''); assert.strictEqual($('.c-lab').value, ''); assert.strictEqual($('.c-down').value, '');
    set('.c-desc', 'Probe replaced'); act('savedone'); await tick();
    ['finish time', 'labour hours', 'downtime hours', 'failure problem'].forEach((x) => assert.ok(status().includes(x), status()));
    set('.c-when', workTime()); set('.c-lab', '1.5'); set('.c-down', '0.5');
    set('.c-fp', SEED.failure_codes.problem[7]); set('.c-fc', SEED.failure_codes.cause[0]); set('.c-fa', SEED.failure_codes.action[0]);
    const rows = $$('.c-parts tr'); rows[0].querySelector('.p-n').value = 'TDS probe'; rows[0].querySelector('.p-q').value = '1';
    act('savedone'); await tick(); assert.ok(/quantity and rate/.test(status()));
    rows[0].querySelector('.p-r').value = '4500'; set('.c-tech', 'Vendor Aqua'); act('savedone'); await tick(12);
    const w = woByNum(`WO-${YEAR}-00003`);
    assert.strictEqual(w.a.wo_status, 'Completed'); assert.strictEqual(w.d.cost_total, 4500); assert.strictEqual(w.d.downtime_hours, 0.5);
    assert.ok(db.ts.some((x) => x.rec.wo_number === `WO-${YEAR}-00003` && x.id === 'ro'));
  });

  await t('the completer cannot verify own work (verification.different_user)', async () => {
    assert.ok($('[data-act="verify"]').disabled);
  });

  await t('DG plan WO: reset only when ticked; PM countdown written to pm_config.limits.service', async () => {
    tab('wo'); await tick(); openWo(`WO-${YEAR}-00001`); await tick(); act('complete'); await tick();
    assert.strictEqual($('.c-rh').value, '166.1'); assert.strictEqual($('.c-reset').checked, false);
    set('.c-when', workTime()); set('.c-desc', 'Oil and filter changed'); set('.c-lab', '2'); set('.c-down', '0');
    $$('.c-cl input[type=checkbox]')[0].checked = true; $$('.c-note')[1].value = 'Filter not in stock';
    $('.c-reset').checked = true;
    act('savedone'); await tick(14);
    assert.strictEqual(woByNum(`WO-${YEAR}-00001`).a.wo_status, 'Completed');
    assert.strictEqual(A(planId('PL-0001')).plan_next_due_rh, 416.1);
    const pc = J(A('dg1').pm_config);
    assert.strictEqual(pc.limits.service.last_service_run_hours, 166.1); assert.strictEqual(pc.limits.service.interval_h, 250); assert.strictEqual(pc.kind, 'DG');
  });

  await t('another user verifies and closes; full history', async () => {
    mount(['supervisor@site', 'Meena']); await tick(8);
    click($$('[data-filter]').find((c) => c.getAttribute('data-filter') === 'verify')); await tick();
    openWo(`WO-${YEAR}-00003`); await tick(); act('verify'); await tick(8);
    const w = woByNum(`WO-${YEAR}-00003`);
    assert.strictEqual(w.a.wo_status, 'Closed');
    assert.deepStrictEqual(w.d.history.map((h) => h.action), ['created', 'started', 'put on hold', 'resumed', 'completed', 'verified and closed']);
  });

  await t('reject back to rework; concurrent change detected', async () => {
    click($$('[data-filter]').find((c) => c.getAttribute('data-filter') === 'verify')); await tick();
    openWo(`WO-${YEAR}-00001`); await tick(); act('reject'); await tick(); set('.r-txt', 'Filter pending'); act('savereason'); await tick(8);
    const w = woByNum(`WO-${YEAR}-00001`);
    assert.strictEqual(w.a.wo_status, 'In Progress');
    db.attrs[w.id].wo_rev = Number(db.attrs[w.id].wo_rev) + 5;
    act('hold'); await tick(); set('.r-txt', 'x'); act('savereason'); await tick(8);
    assert.ok(/changed by someone else/.test(status()), status());
  });

  await t('cancelling a plan WO skips the occurrence', async () => {
    mount(['supervisor@site', 'Meena']); await tick(8);
    tab('plans'); await tick(); click($$('[data-act="raisenow"]')[0]); await tick(10);
    act('cancel'); await tick(); set('.r-txt', 'Plant shut'); act('savereason'); await tick(12);
    assert.strictEqual(woByNum(`WO-${YEAR}-00004`).a.wo_status, 'Cancelled');
    assert.strictEqual(A(planId('PL-0002')).plan_next_due_date, plusDays(33));
  });

  await t('KPIs use the configured periods and type flags', async () => {
    tab('kpi'); await tick();
    assert.deepStrictEqual($$('.mp-kd option').map((o) => Number(o.value)), SEED.alerts.kpi_periods_days);
    assert.ok(/4,500/.test(container.textContent) && /Mean time to repair/.test(container.textContent));
  });

  await t('print job card', async () => {
    tab('wo'); await tick(); click($$('[data-filter]').find((c) => c.getAttribute('data-filter') === 'all')); await tick();
    openWo(`WO-${YEAR}-00001`); await tick(); act('print');
    assert.ok(printed.includes(`WO-${YEAR}-00001`) && printed.includes('Change engine oil') && printed.includes('Verified by'));
  });

  await t('settings tab: edit priorities and due window; values are used immediately; validation', async () => {
    tab('settings'); await tick(4);
    assert.strictEqual($$('.s-prof input:checked').length, SEED.equipment_profiles.length);   // configured profiles stay listed
    assert.ok($$('.s-prof input').some((c) => c.value === 'Some Other Profile' && !c.checked));
    set('.s-soon', '10');
    $$('.s-pri tr')[0].querySelector('.p-days').value = '2';
    act('savesettings'); await tick(10);
    const saved = J(A('set').cmms_settings);
    assert.strictEqual(saved.due_soon_days, 10); assert.strictEqual(saved.priorities[0].response_days, 2); assert.strictEqual(A('set').cmms_settings_rev, 2);
    assert.ok(/Due within 10 days/.test((tab('wo'), await tick(), container.textContent)));
    tab('settings'); await tick(4);
    $$('.s-prof input').forEach((c) => { c.checked = false; });
    act('savesettings'); await tick(2);
    assert.ok(/at least one equipment profile/.test(container.textContent));
    assert.strictEqual(J(A('set').cmms_settings).equipment_profiles.length, SEED.equipment_profiles.length, 'invalid settings not saved');
  });

  await t('predictive-maintenance editor: limits, maps and engine saved to pm_config', async () => {
    tab('settings'); await tick(4);
    const crit = $$('[data-path="limits.battery.crit_v"]')[0]; crit.value = '22.5';
    const cap = $$('[data-path="limits.fuel.tank_capacity_l"]')[0]; cap.value = '990';
    const stale = $$('[data-path="engine.stale_minutes"]')[0]; stale.value = '20';
    const codes = $$('[data-path="limits.alarm_codes"]')[0]; codes.value = '288 = Mains failure\n\n 320= Breaker trip ';
    click($('[data-act="savepm"]')); await tick(10);
    const pc = J(A('dg1').pm_config);
    assert.strictEqual(pc.limits.battery.crit_v, 22.5); assert.strictEqual(pc.limits.fuel.tank_capacity_l, 990); assert.strictEqual(pc.engine.stale_minutes, 20);
    assert.strictEqual(pc.limits.service.last_service_run_hours, 166.1, 'other values kept');
    assert.deepStrictEqual(pc.limits.valid.rpm, [0, 3000]);
    assert.deepStrictEqual(pc.limits.alarm_codes, {'288': 'Mains failure', '320': 'Breaker trip'}, 'controller alarm names saved as text');
  });

  await t('equipment without predictive maintenance is configured from the template', async () => {
    const btn = $$('[data-act="pmtemplate"]').find((b) => b.textContent.includes('RO Plant System'));
    click(btn); await tick(10);
    const pc = J(A('ro').pm_config);
    assert.strictEqual(pc.kind, 'RO'); assert.strictEqual(pc.limits.keys.tds, PM_SEED.kinds.RO.keys.tds);
  });

  await t('Work done tab: work recorded without a work order (2 steps, nothing saved until the work is saved)', async () => {
    tab('done'); await tick(4);
    const before = Object.values(db.assets).filter((a) => a.type === 'Work Order').length;
    const listed = $$('tr[data-act="viewwo"]').length;
    assert.ok(listed >= 1, 'completed / verified work is listed');
    act('newdone'); await tick();
    assert.strictEqual($('.d-eq').value, ''); assert.strictEqual($('.d-type').value, ''); assert.strictEqual($('.d-pri').value, '');
    act('donenext'); await tick(); assert.ok(/required/.test(status()), status());
    set('.d-eq', 'dg1'); set('.d-type', SEED.wo_types.find((x) => x.pm_service_reset).name); set('.d-title', 'Annual service by OEM');
    assert.strictEqual($('.d-rep').style.display, 'none', 'reported time only for corrective work');
    act('donenext'); await tick();
    assert.ok($('.c-reset'), 'PM countdown restart offered for DG preventive work');
    act('back'); await tick();
    assert.strictEqual($('.d-title').value, 'Annual service by OEM', 'step 1 values kept on Back');
    act('close'); await tick(4);
    assert.strictEqual(Object.values(db.assets).filter((a) => a.type === 'Work Order').length, before, 'abandoned form creates no work order');
    act('newdone'); await tick();
    set('.d-eq', 'dg1'); set('.d-type', SEED.wo_types.find((x) => x.pm_service_reset).name); set('.d-title', 'Annual service by OEM');
    act('donenext'); await tick();
    set('.c-when', workTime()); set('.c-tech', 'OEM engineer'); set('.c-rh', '170'); set('.c-lab', '3'); set('.c-down', '1'); set('.c-desc', 'Oil, filters, belts');
    $('.c-reset').checked = true;
    act('savedone'); await tick(16);
    const id = Object.keys(db.assets).filter((k) => db.assets[k].type === 'Work Order').find((k) => A(k).wo_title === 'Annual service by OEM');
    const a = A(id), d = J(a.wo_detail);
    assert.strictEqual(a.wo_status, 'Completed'); assert.strictEqual(a.wo_source, 'direct'); assert.strictEqual(a.wo_due_date, '', 'no due date: not counted in PM compliance');
    assert.strictEqual(a.wo_assignee, 'OEM engineer'); assert.strictEqual(a.wo_priority, '');
    assert.deepStrictEqual(d.history.map((h) => h.action), ['created', 'completed']);
    assert.strictEqual(J(A('dg1').pm_config).limits.service.last_service_run_hours, 170);
    assert.ok(db.ts.some((x) => x.id === 'dg1' && x.rec.wo_number === db.assets[id].name && x.rec.run_hours === 170), 'maintenance_record written');
    tab('done'); await tick(4);
    assert.strictEqual($$('tr[data-act="viewwo"]').length, listed + 1);
    assert.ok($$('tr[data-act="viewwo"]')[0].textContent.includes('Annual service by OEM'), 'newest first');
    assert.ok(/Awaiting verification/.test($$('tr[data-act="viewwo"]')[0].textContent));
  });

  await t('corrective work recorded afterwards counts in MTTR only with its reported time', async () => {
    act('newdone'); await tick();
    set('.d-eq', 'ro'); set('.d-type', SEED.wo_types.find((x) => x.failure_codes).name); set('.d-title', 'Pump seal leak');
    assert.strictEqual($('.d-rep').style.display, '');
    set('.d-reported', workTime()); act('donenext'); await tick();
    set('.c-when', workTime()); set('.c-tech', 'Plumber'); set('.c-lab', '1'); set('.c-down', '1'); set('.c-desc', 'Seal replaced');
    set('.c-fp', SEED.failure_codes.problem[0]); set('.c-fc', SEED.failure_codes.cause[0]); set('.c-fa', SEED.failure_codes.action[0]);
    act('savedone'); await tick(14);
    const id = Object.keys(db.assets).find((k) => A(k).wo_title === 'Pump seal leak');
    assert.strictEqual(A(id).wo_status, 'Completed');
    assert.ok(J(A(id).wo_detail).reported_ts > 0);
  });

  await t('missing settings: clear message, nothing assumed', async () => {
    const keep = db.attrs.set.cmms_settings; delete db.attrs.set.cmms_settings;
    mount(['tech@site', 'Ravi']); await tick(8);
    assert.ok(/Maintenance settings are not configured/.test(container.textContent));
    db.attrs.set.cmms_settings = keep;
  });

  await t('no null attribute value was ever sent; no unexpected alerts', async () => {
    assert.deepStrictEqual(alerts, []);
  });
  console.log(passed + ' tests passed');
  self.onDestroy();
})().catch((e) => { console.error('FAIL:', e.stack || e.message); process.exit(1); });
