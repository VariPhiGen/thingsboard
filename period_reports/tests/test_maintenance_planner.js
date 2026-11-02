// End-to-end test of the Maintenance Management widget in jsdom against a fake ThingsBoard that behaves like the real
// one where it matters: null attribute values are rejected (HTTP 500), duplicate asset names are rejected (HTTP 400),
// entity-query values come back as strings.
// Run: NODE_PATH=<a node_modules folder containing jsdom> node period_reports/tests/test_maintenance_planner.js
const {JSDOM} = require('jsdom');
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const SRC = fs.readFileSync(path.join(__dirname, '..', 'widgets', 'maintenance_planner.js'), 'utf8');

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
const devices = {dg1: {name: 'DG SET1', type: 'woodward_kg1500'}, ro: {name: 'RO Plant System', type: 'RO System Profile'}};
db.assets.lib = {name: 'Maintenance Document Library', type: 'Maintenance Library'};
const httpErr = (status, message) => { const e = new Error(message); e.status = status; e.error = {message}; return e; };
function obs(fn) { return {subscribe(ok, err) { setTimeout(() => { let r; try { r = fn(); } catch (e) { if (err) err(e); return; } ok(r); }, 0); }}; }
function ent(url) { const m = /telemetry\/(DEVICE|ASSET)\/([^/]+)\//.exec(url); return m[2]; }
const http = {
  get(url) {
    return obs(() => {
      const u = new URL('http://x' + url);
      if (u.pathname.startsWith('/api/device/')) return devices[u.pathname.split('/')[3]];
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

// ------------------------------------------------------------- widget harness
let container, self;
function mount(user) {
  login(user[0], user[1]);
  document.body.innerHTML = '<div id="w"></div>';
  container = document.getElementById('w');
  if (self && self.onDestroy) self.onDestroy();
  self = {ctx: {$container: [container], http, datasources: [{entityId: 'dg1', entityName: 'DG SET1'}, {entityId: 'ro', entityName: 'RO Plant System'}],
                data: [{datasource: {entityId: 'dg1'}, data: [[1, '166.1'], [2, 'error']]}]}};
  new Function('self', SRC)(self);
  self.onInit();
}
const tick = (n = 1) => new Promise((r) => setTimeout(r, 15 * n));
const $ = (s) => container.querySelector(s);
const $$ = (s) => [...container.querySelectorAll(s)];
const click = (el) => { assert.ok(el, 'element to click not found'); el.dispatchEvent(new window.MouseEvent('click', {bubbles: true})); };
function set(sel, v) { const el = $(sel); assert.ok(el, sel + ' missing'); el.value = v; el.dispatchEvent(new window.Event('change', {bubbles: true})); }
const tab = (name) => click($$('[data-tab]').find((b) => b.getAttribute('data-tab') === name));
const status = () => ($('.mp-status') || {}).textContent || '';
const openWo = (num) => click($$('tr[data-act="viewwo"]').find((r) => r.textContent.includes(num)));
const act = (a) => click($('[data-act="' + a + '"]'));
const YEAR = new Date().getFullYear();
const pad = (n) => (n < 10 ? '0' : '') + n;
const ymd = (d) => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
const plusDays = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return ymd(d); };
let passed = 0;
async function t(name, fn) { await fn(); passed++; console.log('ok -', name); }

(async () => {
  mount(['tech@site', 'Ravi']); await tick(6);

  await t('empty state; run hours ignore the "error" reading', async () => {
    assert.ok(/No work orders yet/.test(container.textContent));
  });

  await t('upload a certificate with revision and expiry to the general library', async () => {
    tab('docs'); await tick(); act('upload'); await tick();
    set('.u-eq', 'general'); set('.u-title', 'Fire NOC'); set('.u-cat', 'Certificate'); set('.u-rev', '2'); set('.u-exp', plusDays(20));
    Object.defineProperty($('.u-file'), 'files', {value: [new window.File(['%PDF'], 'noc.pdf')]});
    act('saveupload'); await tick(8);
    const docs = J(A('lib').maint_docs);
    assert.strictEqual(docs.length, 1); assert.strictEqual(docs[0].revision, '2'); assert.strictEqual(docs[0].expiry, plusDays(20));
    assert.ok(/Expires/.test(container.textContent)); assert.ok($('.mp-tab .n'), 'tab badge for expiring document');
  });

  await t('create a run-hours plan for the DG (validation, numbering, relation)', async () => {
    tab('plans'); await tick(); act('newplan'); await tick();
    set('.f-eq', 'dg1'); set('.f-str', 'meter'); act('saveplan'); await tick();
    assert.ok(/title are required/.test(status()));
    set('.f-title', '250 h service'); set('.f-irh', '250'); set('.f-nrh', '250'); set('.f-asg', 'Ravi'); set('.f-pri', 'P2');
    $('.f-cl').value = 'Change engine oil\nReplace oil filter';
    act('saveplan'); await tick(8);
    const pid = Object.keys(db.assets).find((k) => db.assets[k].name === 'PL-0001');
    assert.ok(pid); assert.strictEqual(A(pid).plan_strategy, 'meter'); assert.strictEqual(A(pid).plan_next_due_rh, 250);
    assert.ok(db.relations.some((r) => r.from.id === 'dg1' && r.to.id === pid && r.type === 'Maintenance'));
    assert.ok(/PL-0001/.test(container.textContent) && /Every 250 run-h/.test(container.textContent));
  });

  await t('create a 30-day RO plan (run-hours strategy not offered for non-DG)', async () => {
    act('newplan'); await tick();
    set('.f-eq', 'ro');
    assert.ok($('.f-str option[value="meter"]').disabled);
    set('.f-title', 'Membrane cleaning'); set('.f-days', '30'); set('.f-date', plusDays(3)); set('.f-type', 'Preventive');
    act('saveplan'); await tick(8);
    assert.ok(/PL-0002/.test(container.textContent));
  });

  await t('raise a work order from a plan: number, checklist and due copied', async () => {
    const btn = $$('[data-act="raisenow"]')[0]; click(btn); await tick(10);
    const w = woByNum(`WO-${YEAR}-00001`);
    assert.ok(w.id, 'WO created');
    assert.strictEqual(w.a.wo_status, 'Scheduled'); assert.strictEqual(w.a.wo_source, 'plan'); assert.strictEqual(w.a.wo_due_rh, 250);
    assert.deepStrictEqual(w.d.checklist, ['Change engine oil', 'Replace oil filter']);
    assert.ok(/Start work/.test(container.textContent), 'detail panel opened');
  });

  await t('manual corrective P1 WO; numbering retries after a concurrent duplicate', async () => {
    db.assets.race = {name: `WO-${YEAR}-00002`, type: 'Work Order'}; db.hiddenNames.add(`WO-${YEAR}-00002`);   // created by someone else meanwhile
    tab('wo'); await tick(); act('newwo'); await tick();
    set('.f-eq', 'ro'); set('.f-title', 'TDS probe reading erratic'); set('.f-type', 'Corrective'); set('.f-pri', 'P1');
    assert.strictEqual($('.f-date').value, plusDays(1));
    act('savewo'); await tick(10);
    const w = woByNum(`WO-${YEAR}-00003`);
    assert.ok(w.id, 'took the next free number'); assert.strictEqual(w.a.wo_priority, 'P1'); assert.strictEqual(w.a.wo_due_rh, '');
  });

  await t('start, hold (reason required), resume', async () => {
    act('start'); await tick(8);
    assert.strictEqual(woByNum(`WO-${YEAR}-00003`).a.wo_status, 'In Progress');
    act('hold'); await tick(); act('savereason'); await tick();
    assert.ok(/reason/i.test(status()));
    set('.r-txt', 'Waiting for spare probe'); act('savereason'); await tick(8);
    assert.strictEqual(woByNum(`WO-${YEAR}-00003`).a.wo_status, 'On Hold');
    assert.ok(/Waiting for spare probe/.test(container.textContent));
    act('start'); await tick(8);
    assert.strictEqual(woByNum(`WO-${YEAR}-00003`).a.wo_status, 'In Progress');
  });

  await t('complete corrective WO: failure codes + labour required; parts costed; record written', async () => {
    act('complete'); await tick();
    set('.c-desc', 'Probe replaced and calibrated'); set('.c-lab', '');
    act('savedone'); await tick();
    assert.ok(/labour hours/.test(status()) && /failure problem, cause and action/.test(status()));
    set('.c-lab', '1.5'); set('.c-down', '0.5'); set('.c-fp', 'Instrument / sensor fault'); set('.c-fc', 'Wear / ageing'); set('.c-fa', 'Replace');
    const rows = $$('.c-parts tr'); rows[0].querySelector('.p-n').value = 'TDS probe'; rows[0].querySelector('.p-q').value = '1'; rows[0].querySelector('.p-r').value = '4500';
    rows[1].querySelector('.p-n').value = 'Calibration fluid'; rows[1].querySelector('.p-q').value = '2'; rows[1].querySelector('.p-r').value = '250';
    set('.c-tech', 'Vendor Aqua'); act('savedone'); await tick(12);
    const w = woByNum(`WO-${YEAR}-00003`);
    assert.strictEqual(w.a.wo_status, 'Completed'); assert.strictEqual(w.d.cost_total, 5000); assert.strictEqual(w.d.labour_hours, 1.5);
    assert.deepStrictEqual(w.d.failure, {problem: 'Instrument / sensor fault', cause: 'Wear / ageing', action: 'Replace'});
    assert.strictEqual(w.d.completed_by.user, 'tech@site');
    const rec = db.ts.find((x) => x.rec.wo_number === `WO-${YEAR}-00003`);
    assert.ok(rec && rec.id === 'ro' && rec.rec.downtime_hours === 0.5);
  });

  await t('the completer cannot verify own work', async () => {
    assert.ok($('[data-act="verify"]').disabled);
    assert.ok(/another user must verify/i.test(container.textContent));
  });

  await t('complete the DG plan WO: checklist remark rule, run hours, plan advances, PM countdown restarts', async () => {
    db.attrs.dg1 = Object.assign(db.attrs.dg1 || {}, {pm_config: JSON.stringify({kind: 'DG', last_service_run_hours: '', service_interval_h: 250})});
    tab('wo'); await tick(); openWo(`WO-${YEAR}-00001`); await tick(); act('complete'); await tick();
    assert.strictEqual($('.c-rh').value, '166.1'); assert.ok($('.c-reset').checked);
    set('.c-desc', 'Oil and filter changed'); set('.c-lab', '2');
    $$('.c-cl input[type=checkbox]')[0].checked = true;
    act('savedone'); await tick();
    assert.ok(/remark for each checklist step not done \(1\)/.test(status()));
    $$('.c-note')[1].value = 'Filter not in stock - next visit';
    act('savedone'); await tick(14);
    const w = woByNum(`WO-${YEAR}-00001`);
    assert.strictEqual(w.a.wo_status, 'Completed');
    const pid = Object.keys(db.assets).find((k) => db.assets[k].name === 'PL-0001');
    assert.strictEqual(A(pid).plan_next_due_rh, 416.1);
    assert.strictEqual(J(A(pid).plan_detail).last_wo, `WO-${YEAR}-00001`);
    const cfg = J(A('dg1').pm_config);
    assert.strictEqual(cfg.last_service_run_hours, 166.1); assert.strictEqual(cfg.service_interval_h, 250); assert.strictEqual(cfg.kind, 'DG');
  });

  await t('another user verifies and closes; history records who did what', async () => {
    mount(['supervisor@site', 'Meena']); await tick(8);
    click($$('[data-filter]').find((c) => c.getAttribute('data-filter') === 'verify')); await tick();
    openWo(`WO-${YEAR}-00003`); await tick();
    assert.ok(!$('[data-act="verify"]').disabled);
    act('verify'); await tick(8);
    const w = woByNum(`WO-${YEAR}-00003`);
    assert.strictEqual(w.a.wo_status, 'Closed'); assert.strictEqual(w.d.verified_by.user, 'supervisor@site');
    assert.deepStrictEqual(w.d.history.map((h) => h.action), ['created', 'started', 'put on hold', 'resumed', 'completed', 'verified and closed']);
    assert.deepStrictEqual([...new Set(w.d.history.map((h) => h.user))], ['tech@site', 'supervisor@site']);
  });

  await t('verifier rejects the DG WO back to rework', async () => {
    click($$('[data-filter]').find((c) => c.getAttribute('data-filter') === 'verify')); await tick();
    openWo(`WO-${YEAR}-00001`); await tick(); act('reject'); await tick();
    set('.r-txt', 'Oil filter still pending'); act('savereason'); await tick(8);
    const w = woByNum(`WO-${YEAR}-00001`);
    assert.strictEqual(w.a.wo_status, 'In Progress'); assert.strictEqual(w.a.wo_completed_ts, ''); assert.strictEqual(w.d.rework, 1);
  });

  await t('a concurrent change is detected instead of being overwritten', async () => {
    const w = woByNum(`WO-${YEAR}-00001`);
    db.attrs[w.id].wo_rev = Number(db.attrs[w.id].wo_rev) + 5;                       // someone else saved meanwhile
    act('hold'); await tick(); set('.r-txt', 'x'); act('savereason'); await tick(8);
    assert.ok(/changed by someone else/.test(status()), status());
    assert.strictEqual(woByNum(`WO-${YEAR}-00001`).a.wo_status, 'In Progress');
  });

  await t('cancelling a plan WO skips that occurrence (plan moves one interval)', async () => {
    mount(['supervisor@site', 'Meena']); await tick(8);
    tab('plans'); await tick();
    click($$('[data-act="raisenow"]')[0]); await tick(10);                            // RO plan, due in 3 days
    const roWo = woByNum(`WO-${YEAR}-00004`);
    assert.strictEqual(roWo.a.wo_due_date, plusDays(3));
    act('cancel'); await tick(); set('.r-txt', 'Plant shut for civil work'); act('savereason'); await tick(12);
    assert.strictEqual(woByNum(`WO-${YEAR}-00004`).a.wo_status, 'Cancelled');
    const pid = Object.keys(db.assets).find((k) => db.assets[k].name === 'PL-0002');
    assert.strictEqual(A(pid).plan_next_due_date, plusDays(33));
  });

  await t('KPIs are computed from the recorded work orders only', async () => {
    tab('kpi'); await tick();
    const txt = container.textContent;
    assert.ok(/Completed/.test(txt) && /INR 5,000/.test(txt), txt.slice(0, 600));
    assert.ok(/Mean time to repair/.test(txt));
  });

  await t('print job card contains checklist and sign-off lines', async () => {
    tab('wo'); await tick(); click($$('[data-filter]').find((c) => c.getAttribute('data-filter') === 'all')); await tick();
    openWo(`WO-${YEAR}-00001`); await tick(); act('print');
    assert.ok(printed && printed.includes(`WO-${YEAR}-00001`) && printed.includes('Change engine oil') && printed.includes('Verified by'));
  });

  await t('no null attribute value was ever sent; no unexpected alerts', async () => {
    assert.deepStrictEqual(alerts, []);
  });
  console.log(passed + ' tests passed');
  self.onDestroy();
})().catch((e) => { console.error('FAIL:', e.stack || e.message); process.exit(1); });
