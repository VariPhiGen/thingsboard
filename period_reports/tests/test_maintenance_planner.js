// End-to-end test of the Maintenance Management widget: the widget runs in jsdom and talks over HTTP to the real CMMS API
// (cmms/api.py), which runs on an in-memory ThingsBoard (cmms/tests/fake_tb.py) that behaves like the real one where it
// matters (null attribute values rejected, duplicate asset names rejected, entity-query values as strings, customer
// scoping, users identified by their token). Users of every maintenance role sign in in turn. All configuration comes
// from cmms/settings_seed.json and pm_seed.json.
// Run: NODE_PATH=<a node_modules folder containing jsdom> node period_reports/tests/test_maintenance_planner.js
const {JSDOM} = require('jsdom');
const {spawn} = require('child_process');
const readline = require('readline');
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
Object.assign(global, {window, document: window.document});
global.URL.createObjectURL = () => 'blob:x'; global.URL.revokeObjectURL = () => {};
window.Element.prototype.scrollIntoView = function () {};
window.confirm = () => true;
let alerts = []; window.alert = (m) => alerts.push(m);
let printed = null; window.open = () => ({document: {write: (h) => { printed = h; }, close() {}}});
let downloads = 0; window.HTMLAnchorElement.prototype.click = function () { downloads++; };

// ------------------------------------------------------------- CMMS API on the fake ThingsBoard
let server, API, IDS, SET_ID, LIB_ID;
function startServer() {
  return new Promise((resolve, reject) => {
    server = spawn('python3', ['-m', 'cmms.tests.e2e_server'], {cwd: ROOT, stdio: ['pipe', 'pipe', 'inherit']});
    server.on('error', reject);
    readline.createInterface({input: server.stdout}).once('line', (l) => {
      const info = JSON.parse(l);
      API = 'http://127.0.0.1:' + info.port; IDS = info.ids; SET_ID = info.settings_id; LIB_ID = info.library_id;
      resolve();
    });
  });
}
let inflight = 0;
const realFetch = global.fetch;
global.fetch = (...a) => { inflight++; return realFetch(...a).finally(() => setTimeout(() => { inflight--; }, 5)); };
const tick = (n = 1) => new Promise((r) => setTimeout(r, 10 * n));
async function settle() {
  for (let quiet = 0; quiet < 3;) { await tick(); quiet = inflight ? 0 : quiet + 1; }
}
let db = null;
async function sync() { db = await (await realFetch(API + '/__test/db')).json(); }
const testPost = (p, body) => realFetch(API + p, {method: 'POST', body: JSON.stringify(body)});
const A = (id) => db.attrs[id] || {};
const J = (s) => (typeof s === 'string' && s ? JSON.parse(s) : s);
const idOf = (n) => Object.keys(db.assets).find((k) => db.assets[k].name === n);
const woByNum = (n) => { const id = idOf(n); return {id, a: A(id), d: J(A(id).wo_detail)}; };
const uidOf = (first) => Object.keys(db.users).find((k) => db.users[k].firstName === first);

// ------------------------------------------------------------- widget harness
let container, self;
async function mount(token) {
  window.localStorage.setItem('jwt_token', 'tok-' + token);
  document.body.innerHTML = '<div id="w"></div>';
  container = document.getElementById('w');
  if (self && self.onDestroy) self.onDestroy();
  const http = {get: () => ({subscribe(ok) { setTimeout(() => ok({}), 0); }})};      // token refresh hook only
  self = {ctx: {$container: [container], http, settings: {apiUrl: API + '/cmms/v1'}, datasources: [], data: []}};
  new Function('self', SRC)(self);
  self.onInit();
  await settle();
}
const $ = (s) => container.querySelector(s);
const $$ = (s) => [...container.querySelectorAll(s)];
const click = (el) => { assert.ok(el, 'element to click not found'); el.dispatchEvent(new window.MouseEvent('click', {bubbles: true})); };
function set(sel, v) { const el = $(sel); assert.ok(el, sel + ' missing'); el.value = v; el.dispatchEvent(new window.Event('change', {bubbles: true})); }
const tab = async (name) => { click($$('[data-tab]').find((b) => b.getAttribute('data-tab') === name)); await settle(); };
const chip = async (f) => { click($$('[data-filter]').find((c) => c.getAttribute('data-filter') === f)); await settle(); };
const status = () => ($('.mp-panel-slot .mp-status') || {}).textContent || '';
const openWo = async (num) => { click($$('tr[data-act="viewwo"]').find((r) => r.textContent.includes(num))); await settle(); };
const act = async (a) => { click($('[data-act="' + a + '"]')); await settle(); };
const has = (a) => !!$('[data-act="' + a + '"]');
const files = (sel, list) => Object.defineProperty($(sel), 'files', {value: list, configurable: true});
const pad = (n) => (n < 10 ? '0' : '') + n;
const siteNow = () => new Date(Date.now() + SEED.timezone_offset_minutes * 60000 + new Date().getTimezoneOffset() * 60000);
const ymd = (d) => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
const plusDays = (n) => { const d = siteNow(); d.setDate(d.getDate() + n); return ymd(d); };
const YEAR = siteNow().getFullYear();
const startTime = () => { const d = new Date(Date.now() - 3 * 3600000 - new Date().getTimezoneOffset() * 60000); return d.toISOString().slice(0, 16); };
const workTime = () => { const d = new Date(Date.now() - 3600000 - new Date().getTimezoneOffset() * 60000); return d.toISOString().slice(0, 16); };
let passed = 0;
async function t(name, fn) { await fn(); passed++; console.log('ok -', name); }

(async () => {
  await startServer();
  await mount('sup');

  await t('supervisor: equipment of the configured profiles assigned to the customer; no defaults in forms', async () => {
    assert.ok(/No work orders yet/.test(container.textContent));
    assert.ok(/Sunil · Supervisor/.test($('.mp-who').textContent));
    assert.ok(!$$('[data-tab]').some((b) => b.getAttribute('data-tab') === 'settings'), 'settings only for admins');
    await act('newwo');
    const names = $$('.f-eq option').map((o) => o.textContent).filter(Boolean);
    assert.deepStrictEqual(names, ['DG SET1', 'RO Plant System']);   // LT Panel 2: other customer; Unrelated meter: profile not configured
    assert.strictEqual($('.f-type').value, ''); assert.strictEqual($('.f-pri').value, ''); assert.strictEqual($('.f-date').value, '');
    await act('close');
  });

  await t('upload a certificate (category, revision, expiry); the all-equipment library is the tenant\'s', async () => {
    await tab('docs'); await act('upload');
    assert.ok(!$$('.u-eq option').some((o) => o.value === 'general'), 'customer supervisors do not change the shared library');
    set('.u-eq', IDS.dg1); set('.u-title', 'Pressure vessel certificate'); set('.u-rev', '2'); set('.u-exp', plusDays(20));
    files('.u-file', [new File(['%PDF'], 'noc.pdf', {type: 'application/pdf'})]);
    await act('saveupload');
    assert.ok(/category/.test(status()));
    set('.u-cat', 'Certificate'); await act('saveupload'); await sync();
    const docs = J(A(IDS.dg1).maint_docs);
    assert.strictEqual(docs.length, 1); assert.strictEqual(docs[0].category, 'Certificate'); assert.strictEqual(docs[0].expiry, plusDays(20));
    assert.strictEqual(docs[0].uploaded_by, 'Sunil');
    assert.ok(/Expires/.test(container.textContent));
    click($$('[data-doc]')[0]); await settle();
    assert.strictEqual(downloads, 1, 'download through the API');
  });

  await t('meter-based plan only for equipment that reports the meter; assignee from the user list', async () => {
    await tab('plans'); await act('newplan');
    set('.f-eq', IDS.ro); assert.ok($('.f-str option[value="meter"]').disabled, 'RO has no meter');
    set('.f-eq', IDS.dg1); assert.ok(!$('.f-str option[value="meter"]').disabled);
    assert.ok(/current reading: 166.1 run-h/.test(container.textContent));
    assert.ok($$('datalist option').map((o) => o.value).includes('Ravi'), 'technicians listed as assignees');
    set('.f-title', '250 h service'); set('.f-type', 'Preventive'); set('.f-pri', 'P2'); set('.f-str', 'meter');
    await act('saveplan'); assert.ok(/interval and the next due meter reading/.test(status()));
    set('.f-irh', '250'); set('.f-nrh', '250'); set('.f-asg', 'Ravi'); $('.f-cl').value = 'Change engine oil\nReplace oil filter';
    await act('saveplan'); await sync();
    const pid = idOf('PL-0001');
    assert.strictEqual(A(pid).plan_strategy, 'meter'); assert.strictEqual(A(pid).plan_next_due_rh, 250); assert.strictEqual(A(pid).plan_priority, 'P2');
    assert.strictEqual(J(A(pid).plan_detail).assignee_id, uidOf('Ravi'));
    assert.ok(db.relations.some((r) => r.from.id === IDS.dg1 && r.to.id === pid));
  });

  await t('time-based plan needs interval, next due date and lead days', async () => {
    await act('newplan');
    set('.f-eq', IDS.ro); set('.f-title', 'Membrane cleaning'); set('.f-type', 'Preventive'); set('.f-pri', 'P3'); set('.f-str', 'time');
    set('.f-days', '30'); set('.f-date', plusDays(3)); await act('saveplan');
    assert.ok(/lead days/.test(status()));
    set('.f-lead', '7'); await act('saveplan'); await sync();
    assert.strictEqual(A(idOf('PL-0002')).plan_lead_days, 7);
  });

  await t('raise a WO from a plan: assignee and checklist carried over', async () => {
    click($$('[data-act="raisenow"]')[0]); await settle(); await sync();
    const w = woByNum(`WO-${YEAR}-00001`);
    assert.strictEqual(w.a.wo_status, 'Scheduled'); assert.strictEqual(w.a.wo_due_rh, 250); assert.strictEqual(w.a.wo_assignee_id, uidOf('Ravi'));
    assert.deepStrictEqual(w.d.checklist, ['Change engine oil', 'Replace oil filter']);
    assert.strictEqual(w.d.history[0].name, 'Sunil', 'history carries the verified user');
  });

  await t('manual WO: due date follows the configured response days of the priority; numbering retries', async () => {
    await testPost('/__test/hide', {name: `WO-${YEAR}-00002`, type: 'Work Order'});
    await tab('wo'); await act('newwo');
    set('.f-eq', IDS.ro); set('.f-title', 'TDS probe reading erratic'); set('.f-type', 'Corrective'); set('.f-pri', 'P1');
    assert.strictEqual($('.f-date').value, plusDays(SEED.priorities[0].response_days));
    await act('savewo'); await sync();
    const w = woByNum(`WO-${YEAR}-00003`);
    assert.ok(w.id); assert.strictEqual(w.a.wo_priority, 'P1'); assert.strictEqual(w.a.wo_assignee, '');
  });

  await t('technician: My work, takes unassigned work on start, hold (reason required), resume; no supervisor actions', async () => {
    await mount('tech');
    assert.ok(/Ravi · Technician/.test($('.mp-who').textContent));
    assert.ok(!has('newwo') && has('newreq'), 'technicians raise requests, not work orders');
    await chip('mine');
    assert.ok($$('tr[data-act="viewwo"]').some((r) => r.textContent.includes(`WO-${YEAR}-00001`)));
    assert.ok(!$$('tr[data-act="viewwo"]').some((r) => r.textContent.includes(`WO-${YEAR}-00003`)), 'unassigned work is not "mine"');
    await chip('open'); await openWo(`WO-${YEAR}-00003`);
    assert.ok(!has('editwo') && !has('cancel'), 'no edit / cancel for technicians');
    await act('start'); await sync();
    assert.strictEqual(woByNum(`WO-${YEAR}-00003`).a.wo_assignee, 'Ravi', 'unassigned work taken by the technician');
    await act('hold'); await act('savereason'); assert.ok(/reason/i.test(status()));
    set('.r-txt', 'Waiting for spare probe'); await act('savereason'); await sync();
    assert.strictEqual(woByNum(`WO-${YEAR}-00003`).a.wo_status, 'On Hold');
    await act('start'); await sync();
    assert.strictEqual(woByNum(`WO-${YEAR}-00003`).a.wo_status, 'In Progress');
  });

  await t('another technician cannot work on it', async () => {
    await mount('tech2'); await openWo(`WO-${YEAR}-00003`);
    assert.ok(!has('complete') && !has('hold'));
    assert.ok(/Assigned to Ravi/.test(container.textContent));
  });

  await t('complete corrective WO: every value entered (time, labour, downtime, failure codes, part qty+rate)', async () => {
    await mount('tech'); await openWo(`WO-${YEAR}-00003`); await act('complete');
    assert.strictEqual($('.c-when').value, ''); assert.strictEqual($('.c-lab').value, ''); assert.strictEqual($('.c-down').value, '');
    set('.c-desc', 'Probe replaced'); await act('savedone');
    ['start time', 'finish time', 'labour hours', 'downtime hours', 'failure problem', 'condition after the work'].forEach((x) => assert.ok(status().includes(x), status()));
    assert.strictEqual($('.c-tech').value, 'Ravi', 'technician: the signed-in user who took the work');
    set('.c-start', startTime()); set('.c-when', workTime()); set('.c-cond', 'In service'); set('.c-lab', '1.5'); set('.c-down', '0.5');
    set('.c-fp', SEED.failure_codes.problem[7]); set('.c-fc', SEED.failure_codes.cause[0]); set('.c-fa', SEED.failure_codes.action[0]);
    const rows = $$('.c-parts tr'); rows[0].querySelector('.p-n').value = 'TDS probe'; rows[0].querySelector('.p-q').value = '1';
    await act('savedone'); assert.ok(/quantity and rate/.test(status()));
    rows[0].querySelector('.p-r').value = '4500'; set('.c-tech', 'Vendor Aqua');
    files('.c-files', [new File(['jpg'], 'probe.jpg', {type: 'image/jpeg'})]);
    await act('savedone'); await sync();
    const w = woByNum(`WO-${YEAR}-00003`);
    assert.strictEqual(w.a.wo_status, 'Completed'); assert.strictEqual(w.d.cost_total, 4500); assert.strictEqual(w.d.downtime_hours, 0.5);
    assert.strictEqual(w.d.completed_by.name, 'Ravi'); assert.strictEqual(w.d.attachments[0].file, 'probe.jpg');
    assert.ok(db.ts.some((x) => J(x.values.maintenance_record).wo_number === `WO-${YEAR}-00003` && x.id === IDS.ro));
    assert.ok(!has('verify'), 'technicians do not verify');
  });

  await t('DG plan WO: reset only when ticked; PM countdown written to pm_config.limits.service', async () => {
    await tab('wo'); await openWo(`WO-${YEAR}-00001`); await act('complete');
    assert.strictEqual($('.c-rh').value, '166.1'); assert.strictEqual($('.c-reset').checked, false);
    set('.c-start', startTime()); set('.c-when', workTime()); set('.c-cond', 'In service'); set('.c-desc', 'Oil and filter changed'); set('.c-lab', '2'); set('.c-down', '0');
    $$('.c-cl input[type=checkbox]')[0].checked = true; $$('.c-note')[1].value = 'Filter not in stock';
    $('.c-reset').checked = true;
    await act('savedone'); await sync();
    assert.strictEqual(woByNum(`WO-${YEAR}-00001`).a.wo_status, 'Completed');
    assert.strictEqual(A(idOf('PL-0001')).plan_next_due_rh, 416.1);
    const pc = J(A(IDS.dg1).pm_config);
    assert.strictEqual(pc.limits.service.last_service_run_hours, 166.1); assert.strictEqual(pc.limits.service.interval_h, 250); assert.strictEqual(pc.kind, 'DG');
  });

  await t('supervisor verifies and closes; full history with real users', async () => {
    await mount('sup'); await chip('verify');
    await openWo(`WO-${YEAR}-00003`); await act('verify'); await sync();
    const w = woByNum(`WO-${YEAR}-00003`);
    assert.strictEqual(w.a.wo_status, 'Closed');
    assert.deepStrictEqual(w.d.history.map((h) => h.action + ':' + h.name),
      ['created:Sunil', 'started:Ravi', 'put on hold:Ravi', 'resumed:Ravi', 'completed:Ravi', 'verified and closed:Sunil']);
  });

  await t('reject back to rework; concurrent change detected', async () => {
    await chip('verify'); await openWo(`WO-${YEAR}-00001`); await act('reject'); set('.r-txt', 'Filter pending'); await act('savereason'); await sync();
    const w = woByNum(`WO-${YEAR}-00001`);
    assert.strictEqual(w.a.wo_status, 'In Progress');
    await testPost('/__test/attr', {id: w.id, key: 'wo_rev', value: Number(w.a.wo_rev) + 5});
    await act('hold'); set('.r-txt', 'x'); await act('savereason');
    assert.ok(/changed by someone else/.test(status()), status());
  });

  await t('the person who recorded the work cannot verify it', async () => {
    await mount('sup'); await openWo(`WO-${YEAR}-00001`); await act('complete');
    set('.c-start', startTime()); set('.c-when', workTime()); set('.c-cond', 'In service'); set('.c-desc', 'Filter fitted'); set('.c-lab', '1'); set('.c-down', '0');
    $$('.c-cl input[type=checkbox]').forEach((c) => { c.checked = true; });
    await act('savedone');
    assert.ok($('[data-act="verify"]').disabled, 'own work');
  });

  await t('cancelling a plan WO skips the occurrence', async () => {
    await tab('plans'); click($$('[data-act="raisenow"]')[0]); await settle();
    await act('cancel'); set('.r-txt', 'Plant shut'); await act('savereason'); await sync();
    assert.strictEqual(woByNum(`WO-${YEAR}-00004`).a.wo_status, 'Cancelled');
    assert.strictEqual(A(idOf('PL-0002')).plan_next_due_date, plusDays(33));
  });

  await t('work request: requester raises it with a photo, supervisor approves and assigns, technician gets it', async () => {
    await mount('req');
    assert.ok(/Priya · Requester/.test($('.mp-who').textContent));
    assert.ok(has('newreq') && !has('newwo'));
    await act('newreq'); await act('savereq'); assert.ok(/describe the problem/.test(status()));
    set('.q-eq', IDS.dg1); set('.q-title', 'Oil leak under DG'); set('.q-desc', 'Drops near the sump since morning');
    files('.q-files', [new File(['jpg'], 'leak.jpg', {type: 'image/jpeg'})]);
    await act('savereq'); await sync();
    const num = `WO-${YEAR}-00005`;
    let w = woByNum(num);
    assert.strictEqual(w.a.wo_status, 'Requested'); assert.strictEqual(w.d.requested_by.name, 'Priya'); assert.strictEqual(w.d.attachments[0].file, 'leak.jpg');
    assert.ok(has('withdraw') && !has('approve'));
    await mount('sup'); await chip('requests'); await openWo(num);
    assert.ok(has('approve') && has('rejectreq'));
    await act('approve');
    assert.strictEqual($('.f-title').value, 'Oil leak under DG'); assert.strictEqual($('.f-type').value, '');
    set('.f-type', 'Corrective'); set('.f-pri', 'P2'); set('.f-asg', 'Mohan');
    await act('savewo'); await sync();
    w = woByNum(num);
    assert.strictEqual(w.a.wo_status, 'Scheduled'); assert.strictEqual(w.a.wo_assignee_id, uidOf('Mohan')); assert.strictEqual(w.a.wo_due_date, plusDays(SEED.priorities[1].response_days));
    assert.strictEqual(w.d.approved_by.name, 'Sunil');
    await mount('tech2'); await chip('mine');
    assert.ok($$('tr[data-act="viewwo"]').some((r) => r.textContent.includes(num)));
  });

  await t('viewer: sees everything, changes nothing', async () => {
    await mount('view');
    assert.ok(!has('newwo') && !has('newreq'));
    await openWo(`WO-${YEAR}-00005`);
    assert.ok(!has('start') && !has('complete') && !has('cancel') && !has('editwo') && has('print'));
    await tab('done'); assert.ok(!has('newdone'));
    await tab('plans'); assert.ok(!has('newplan') && !has('editplan'));
    await tab('docs'); assert.ok(!has('upload') && !has('deldoc') && $$('[data-doc]').length >= 1);
    const r = await realFetch(API + '/cmms/v1/action/wo_create', {method: 'POST', headers: {'X-Authorization': 'Bearer tok-view'}, body: '{}'});
    assert.strictEqual(r.status, 403, 'the server refuses it too');
  });

  await t('KPIs use the configured periods and type flags', async () => {
    await mount('sup'); await tab('kpi');
    assert.deepStrictEqual($$('.mp-kd option').map((o) => Number(o.value)), SEED.alerts.kpi_periods_days);
    assert.ok(/4,500/.test(container.textContent) && /Mean time to repair/.test(container.textContent));
  });

  await t('print job card', async () => {
    await tab('wo'); await chip('all'); await openWo(`WO-${YEAR}-00001`); click($('[data-act="print"]'));
    assert.ok(printed.includes(`WO-${YEAR}-00001`) && printed.includes('Change engine oil') && printed.includes('Verified by'));
  });

  await t('admin: settings tab, edit priorities and due window; values are used immediately; validation', async () => {
    await mount('admin'); await tab('settings'); await settle();
    assert.strictEqual($$('.s-prof input:checked').length, SEED.equipment_profiles.length);
    assert.ok($$('.s-prof input').some((c) => c.value === 'Some Other Profile' && !c.checked));
    set('.s-soon', '10');
    $$('.s-pri tr')[0].querySelector('.p-days').value = '2';
    await act('savesettings'); await sync();
    const saved = J(A(SET_ID).cmms_settings);
    assert.strictEqual(saved.due_soon_days, 10); assert.strictEqual(saved.priorities[0].response_days, 2); assert.strictEqual(A(SET_ID).cmms_settings_rev, 2);
    await tab('wo'); assert.ok(/Due within 10 days/.test(container.textContent));
    await tab('settings'); await settle();
    $$('.s-prof input').forEach((c) => { c.checked = false; });
    await act('savesettings');
    assert.ok(/at least one equipment profile/.test(container.textContent));
    await sync();
    assert.strictEqual(J(A(SET_ID).cmms_settings).equipment_profiles.length, SEED.equipment_profiles.length, 'invalid settings not saved');
  });

  await t('predictive-maintenance editor: limits, maps and engine saved to pm_config', async () => {
    await tab('settings'); await settle();
    $$('[data-path="limits.battery.crit_v"]')[0].value = '22.5';
    $$('[data-path="limits.fuel.tank_capacity_l"]')[0].value = '990';
    $$('[data-path="engine.stale_minutes"]')[0].value = '20';
    $$('[data-path="limits.alarm_codes"]')[0].value = '288 = Mains failure\n\n 320= Breaker trip ';
    click($('[data-act="savepm"]')); await settle(); await sync();
    const pc = J(A(IDS.dg1).pm_config);
    assert.strictEqual(pc.limits.battery.crit_v, 22.5); assert.strictEqual(pc.limits.fuel.tank_capacity_l, 990); assert.strictEqual(pc.engine.stale_minutes, 20);
    assert.strictEqual(pc.limits.service.last_service_run_hours, 166.1, 'other values kept');
    assert.deepStrictEqual(pc.limits.valid.rpm, [0, 3000]);
    assert.deepStrictEqual(pc.limits.alarm_codes, {'288': 'Mains failure', '320': 'Breaker trip'}, 'controller alarm names saved as text');
  });

  await t('equipment without predictive maintenance is configured from the template', async () => {
    const btn = $$('[data-act="pmtemplate"]').find((b) => b.textContent.includes('RO Plant System'));
    click(btn); await settle(); await sync();
    const pc = J(A(IDS.ro).pm_config);
    assert.strictEqual(pc.kind, 'RO'); assert.strictEqual(pc.limits.keys.tds, PM_SEED.kinds.RO.keys.tds);
  });

  await t('users and roles: admin gives a customer user a role', async () => {
    await tab('settings'); await settle();
    const row = $$('.s-users tr').find((r) => r.textContent.includes('Nobody'));
    assert.ok(row && row.textContent.includes('Developer'));
    assert.ok($$('.s-users tr').find((r) => r.textContent.includes('Admin')).textContent.includes('always'));
    const sel = row.querySelector('.s-role'); assert.strictEqual(sel.value, '');
    sel.value = 'viewer'; sel.dispatchEvent(new window.Event('change', {bubbles: true})); await settle(); await sync();
    assert.strictEqual(J(A(SET_ID).cmms_roles)[uidOf('Nobody')].role, 'viewer');
    await mount('none');
    assert.ok(/Nobody · Viewer/.test($('.mp-who').textContent));
  });

  await t('Work done tab: work recorded without a work order (2 steps, nothing saved until the work is saved)', async () => {
    await mount('tech'); await tab('done');
    await sync();
    const before = Object.values(db.assets).filter((a) => a.type === 'Work Order').length;
    const listed = $$('tr[data-act="viewwo"]').length;
    assert.ok(listed >= 1, 'completed / verified work is listed');
    await act('newdone');
    assert.strictEqual($('.d-eq').value, ''); assert.strictEqual($('.d-type').value, ''); assert.strictEqual($('.d-pri').value, '');
    await act('donenext'); assert.ok(/required/.test(status()), status());
    set('.d-eq', IDS.dg1); set('.d-type', SEED.wo_types.find((x) => x.pm_service_reset).name); set('.d-title', 'Annual service by OEM');
    assert.strictEqual($('.d-rep').style.display, 'none', 'reported time only for corrective work');
    await act('donenext');
    assert.ok($('.c-reset'), 'PM countdown restart offered for DG preventive work');
    await act('back');
    assert.strictEqual($('.d-title').value, 'Annual service by OEM', 'step 1 values kept on Back');
    await act('close'); await sync();
    assert.strictEqual(Object.values(db.assets).filter((a) => a.type === 'Work Order').length, before, 'abandoned form creates no work order');
    await act('newdone');
    set('.d-eq', IDS.dg1); set('.d-type', SEED.wo_types.find((x) => x.pm_service_reset).name); set('.d-title', 'Annual service by OEM');
    await act('donenext');
    set('.c-start', startTime()); set('.c-when', workTime()); set('.c-cond', 'In service'); set('.c-tech', 'OEM engineer'); set('.c-rh', '170'); set('.c-lab', '3'); set('.c-down', '1'); set('.c-desc', 'Oil, filters, belts');
    $('.c-reset').checked = true;
    await act('savedone'); await sync();
    const id = Object.keys(db.assets).filter((k) => db.assets[k].type === 'Work Order').find((k) => A(k).wo_title === 'Annual service by OEM');
    const a = A(id), d = J(a.wo_detail);
    assert.strictEqual(a.wo_status, 'Completed'); assert.strictEqual(a.wo_source, 'direct'); assert.strictEqual(a.wo_due_date, '', 'no due date: not counted in PM compliance');
    assert.strictEqual(a.wo_assignee, 'OEM engineer'); assert.strictEqual(a.wo_priority, '');
    assert.deepStrictEqual(d.history.map((h) => h.action), ['created', 'completed']);
    assert.strictEqual(J(A(IDS.dg1).pm_config).limits.service.last_service_run_hours, 170);
    assert.ok(db.ts.some((x) => x.id === IDS.dg1 && J(x.values.maintenance_record).wo_number === db.assets[id].name && J(x.values.maintenance_record).run_hours === 170), 'maintenance_record written');
    await tab('done');
    assert.strictEqual($$('tr[data-act="viewwo"]').length, listed + 1);
    assert.ok($$('tr[data-act="viewwo"]')[0].textContent.includes('Annual service by OEM'), 'newest first');
    assert.ok(/Awaiting verification/.test($$('tr[data-act="viewwo"]')[0].textContent));
  });

  await t('Record work done: equipment out of service, limitation required, follow-up request raised and linked', async () => {
    await act('newdone');
    set('.d-eq', IDS.dg1); set('.d-type', SEED.wo_types.find((x) => x.failure_codes).name); set('.d-title', 'DG not starting');
    set('.d-reported', startTime()); await act('donenext');
    set('.c-start', startTime()); set('.c-when', workTime()); set('.c-lab', '2'); set('.c-down', '3'); set('.c-desc', 'Starter motor found burnt');
    assert.ok(/elapsed 2 h/.test($('.c-dur').textContent));
    set('.c-fp', SEED.failure_codes.problem[0]); set('.c-fc', SEED.failure_codes.cause[0]); set('.c-fa', SEED.failure_codes.action[0]);
    set('.c-cond', 'Out of service');
    assert.ok($('.c-fu').checked, 'follow-up suggested when out of service');
    assert.strictEqual($('.c-cnote-w').style.display, '');
    await act('savedone');
    assert.ok(/limitation/.test(status()) && /follow-up work/.test(status()), status());
    set('.c-cnote', 'Waiting for new starter motor'); set('.c-fut', 'Replace starter motor');
    await act('savedone'); await sync();
    const id = Object.keys(db.assets).find((k) => A(k).wo_title === 'DG not starting');
    const d = J(A(id).wo_detail);
    assert.strictEqual(d.condition_after, 'Out of service'); assert.strictEqual(d.follow_up.title, 'Replace starter motor');
    const f = woByNum(d.follow_up.number);
    assert.strictEqual(f.a.wo_status, 'Requested'); assert.strictEqual(f.d.follow_up_of.number, db.assets[id].name);
    assert.ok(/Follow-up request/.test(container.textContent) && /Out of service/.test(container.textContent));
    await tab('done');
    assert.ok(/Out of service/.test($$('tr[data-act="viewwo"]')[0].textContent));
  });

  await t('corrective work recorded afterwards counts in MTTR only with its reported time', async () => {
    await act('newdone');
    set('.d-eq', IDS.ro); set('.d-type', SEED.wo_types.find((x) => x.failure_codes).name); set('.d-title', 'Pump seal leak');
    assert.strictEqual($('.d-rep').style.display, '');
    set('.d-reported', workTime()); await act('donenext');
    set('.c-start', startTime()); set('.c-when', workTime()); set('.c-cond', 'In service'); set('.c-tech', 'Plumber'); set('.c-lab', '1'); set('.c-down', '1'); set('.c-desc', 'Seal replaced');
    set('.c-fp', SEED.failure_codes.problem[0]); set('.c-fc', SEED.failure_codes.cause[0]); set('.c-fa', SEED.failure_codes.action[0]);
    await act('savedone'); await sync();
    const id = Object.keys(db.assets).find((k) => A(k).wo_title === 'Pump seal leak');
    assert.strictEqual(A(id).wo_status, 'Completed');
    assert.ok(J(A(id).wo_detail).reported_ts > 0);
  });

  await t('other customer sees only its own equipment; user without a role is refused', async () => {
    await mount('c2');
    assert.ok(/No work orders yet/.test(container.textContent), 'no work of the other customer');
    await testPost('/__test/attr', {id: SET_ID, key: 'cmms_roles', value: JSON.stringify({})});
    await mount('tech');
    assert.ok(/no maintenance role/.test(container.textContent));
  });

  await t('missing settings: clear message, nothing assumed', async () => {
    await testPost('/__test/attr', {id: SET_ID, key: 'cmms_settings', value: null});
    await mount('admin');
    assert.ok(/Maintenance settings are not configured/.test(container.textContent));
  });

  await t('no unexpected alerts', async () => {
    assert.deepStrictEqual(alerts, []);
  });
  console.log(passed + ' tests passed');
  self.onDestroy();
  server.stdin.end();
})().catch((e) => { console.error('FAIL:', e.stack || e.message); if (server) server.kill(); process.exit(1); });
