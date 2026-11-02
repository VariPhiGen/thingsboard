// Run: NODE_PATH=<a node_modules folder containing jsdom> node period_reports/tests/test_maintenance_planner.js
// End-to-end test of maintenance_planner.js in jsdom against an in-memory fake ThingsBoard API.
const {JSDOM} = require('jsdom');
const fs = require('fs');
const assert = require('assert');
const SRC = fs.readFileSync(require('path').join(__dirname, '..', 'widgets', 'maintenance_planner.js'), 'utf8');

const dom = new JSDOM('<!doctype html><div id="w"></div>', {url: 'https://viot.example/'});
const {window} = dom;
global.window = window; global.document = window.document; global.FormData = window.FormData;
global.Blob = window.Blob; global.URL = window.URL; global.URL.createObjectURL = () => 'blob:x'; global.URL.revokeObjectURL = () => {};
global.atob = window.atob; global.HTMLElement = window.HTMLElement;
window.Element.prototype.scrollIntoView = function () {};
window.confirm = () => true; window.alert = (m) => { throw new Error('alert: ' + m); };
const payload = Buffer.from(JSON.stringify({firstName: 'Asha', lastName: 'Rao', sub: 'asha@x', tenantId: 't1'})).toString('base64');
window.localStorage.setItem('jwt_token', 'h.' + payload + '.s');

// ---- fake ThingsBoard
const attrs = {};            // "DEVICE/dg1" -> {key: value}
const ts = [];               // posted timeseries
const resources = {};
let rid = 0;
const devices = {dg1: {type: 'woodward_kg1500'}, ro: {type: 'RO System Profile'}};
const LIB = 'lib1';
function obs(fn) { return {subscribe(ok, err) { setTimeout(() => { try { ok(fn()); } catch (e) { if (err) err(e); } }, 0); }}; }
function ent(url) { const m = /telemetry\/(DEVICE|ASSET)\/([^/]+)\//.exec(url); return m[1] + '/' + m[2]; }
const http = {
  get(url) {
    return obs(() => {
      if (url.startsWith('/api/device/')) return devices[url.split('/')[3]];
      if (url.startsWith('/api/tenant/assets?assetName=')) return {id: {id: LIB}};
      if (url.includes('/values/attributes/SERVER_SCOPE')) {
        const keys = new URL('http://x' + url).searchParams.get('keys').split(',');
        const a = attrs[ent(url)] || {};
        return keys.filter((k) => a[k] !== undefined).map((k) => ({key: k, value: a[k]}));
      }
      if (url.includes('/download')) return new Blob(['x']);
      throw new Error('GET ' + url);
    });
  },
  post(url, body) {
    return obs(() => {
      if (url === '/api/resource/upload') {
        assert.ok(body instanceof window.FormData);
        const id = 'r' + (++rid); resources[id] = {title: body.get('title'), type: body.get('resourceType')}; return {id: {id}};
      }
      if (url.endsWith('/attributes/SERVER_SCOPE')) { const e = ent(url.replace('/attributes', '/x/attributes')); attrs[e] = Object.assign(attrs[e] || {}, body); return null; }
      if (url.endsWith('/timeseries/ANY')) { ts.push({url, body}); return null; }
      throw new Error('POST ' + url);
    });
  },
  delete(url) { return obs(() => { delete resources[url.split('/')[3]]; return null; }); },
};
function entFix(u) { return u; }

// ---- widget
const container = document.getElementById('w');
const self = {ctx: {$container: [container], http,
  datasources: [{entityId: 'dg1', entityName: 'DG SET1'}, {entityId: 'ro', entityName: 'RO Plant System'}],
  data: [{datasource: {entityId: 'dg1'}, data: [[Date.now(), '166.18']]}]}};
new Function('self', SRC)(self);
self.onInit();
const tick = () => new Promise((r) => setTimeout(r, 30));
const $ = (s) => container.querySelector(s);
const click = (el) => el.dispatchEvent(new window.MouseEvent('click', {bubbles: true}));
function set(sel, v) { const el = $(sel); el.value = v; el.dispatchEvent(new window.Event('change', {bubbles: true})); }
const jobs = (d) => JSON.parse((attrs['DEVICE/' + d] || {}).maint_jobs || '[]');
let passed = 0;
async function t(name, fn) { await fn(); passed++; console.log('ok -', name); }

(async () => {
  await tick(); await tick();
  await t('renders empty schedule with tabs and counters', async () => {
    assert.ok(/No open maintenance jobs/.test(container.textContent));
    assert.ok(/Open jobs: 0/.test(container.textContent));
  });

  await t('upload a general document to the library asset', async () => {
    click([...container.querySelectorAll('[data-tab]')][1]); await tick();
    click($('[data-act="upload"]')); await tick();
    set('.u-eq', 'general'); set('.u-title', 'Woodward manual'); set('.u-cat', 'Manual');
    const file = new window.File(['%PDF'], 'manual.pdf', {type: 'application/pdf'});
    Object.defineProperty($('.u-file'), 'files', {value: [file]});
    click($('[data-act="saveupload"]')); await tick(); await tick(); await tick();
    const docs = JSON.parse(attrs['ASSET/lib1'].maint_docs);
    assert.strictEqual(docs.length, 1); assert.strictEqual(docs[0].title, 'Woodward manual'); assert.strictEqual(docs[0].category, 'Manual');
    assert.strictEqual(resources[docs[0].id].type, 'GENERAL');
    assert.ok(/Woodward manual/.test(container.textContent));
  });

  await t('create a run-hours DG service job linked to the document', async () => {
    click([...container.querySelectorAll('[data-tab]')][0]); await tick();
    click($('[data-act="new"]')); await tick();
    set('.f-eq', 'dg1'); set('.f-title', '250 h service'); set('.f-kind', 'run_hours'); set('.f-every', '250');
    set('.f-rh', '170'); set('.f-asg', 'Ravi (vendor)'); $('.f-cl').value = 'Change engine oil\nReplace oil filter';
    container.querySelector('.f-docs input').checked = true;
    click($('[data-act="savejob"]')); await tick(); await tick(); await tick();
    const j = jobs('dg1');
    assert.strictEqual(j.length, 1); assert.strictEqual(j[0].kind, 'run_hours'); assert.strictEqual(j[0].next_rh, 170);
    assert.deepStrictEqual(j[0].checklist, ['Change engine oil', 'Replace oil filter']); assert.strictEqual(j[0].docs.length, 1);
    assert.ok(/Due in 3\.8 run-h/.test(container.textContent), container.textContent.slice(0, 400));
  });

  await t('create a 30-day RO job that is overdue', async () => {
    click($('[data-act="new"]')); await tick();
    set('.f-eq', 'ro');
    assert.ok($('.f-kind option[value="run_hours"]').disabled, 'run-hours option only for DG');
    set('.f-title', 'Membrane cleaning'); set('.f-kind', 'days'); set('.f-every', '30');
    const d = new Date(); d.setDate(d.getDate() - 2); set('.f-date', d.toISOString().slice(0, 10));
    click($('[data-act="savejob"]')); await tick(); await tick(); await tick();
    assert.ok(/Overdue by 2 days/.test(container.textContent));
    assert.ok(/Overdue: 1/.test(container.textContent));
  });

  await t('complete the DG service: record, checklist, next due, service countdown', async () => {
    attrs['DEVICE/dg1'].pm_config = JSON.stringify({kind: 'DG', last_service_run_hours: null, service_interval_h: 250});
    const btn = [...container.querySelectorAll('[data-act="complete"]')].find((b) => b.getAttribute('data-e') === 'dg1');
    click(btn); await tick();
    assert.ok($('.c-reset').checked, 'reset ticked by default for a DG preventive service');
    container.querySelectorAll('.c-cl input')[0].checked = true;
    set('.c-desc', 'Oil and filter changed'); set('.c-rh', '166.2');
    click($('[data-act="savedone"]')); for (let i = 0; i < 8; i++) await tick();
    const rec = JSON.parse(ts[0].body[0].values.maintenance_record);
    assert.strictEqual(rec.job_title, '250 h service'); assert.strictEqual(rec.technician, 'Ravi (vendor)');
    assert.deepStrictEqual(rec.checklist, [{item: 'Change engine oil', done: true}, {item: 'Replace oil filter', done: false}]);
    assert.strictEqual(rec.service_reset, true); assert.strictEqual(rec.logged_by, 'Asha Rao');
    const j = jobs('dg1')[0];
    assert.strictEqual(j.next_rh, 416.2); assert.strictEqual(j.last_done_rh, 166.2);
    const cfg = JSON.parse(attrs['DEVICE/dg1'].pm_config);
    assert.strictEqual(cfg.last_service_run_hours, 166.2); assert.strictEqual(cfg.service_interval_h, 250); assert.strictEqual(cfg.kind, 'DG');
  });

  await t('complete the RO job: next due 30 days after the work date', async () => {
    const btn = [...container.querySelectorAll('[data-act="complete"]')].find((b) => b.getAttribute('data-e') === 'ro');
    click(btn); await tick();
    assert.ok($('.c-rh').disabled);
    set('.c-tech', 'Plant operator'); set('.c-desc', 'CIP done');
    click($('[data-act="savedone"]')); for (let i = 0; i < 8; i++) await tick();
    const j = jobs('ro')[0];
    const exp = new Date(); exp.setDate(exp.getDate() + 30);
    const pad = (n) => (n < 10 ? '0' : '') + n;
    assert.strictEqual(j.next_date, exp.getFullYear() + '-' + pad(exp.getMonth() + 1) + '-' + pad(exp.getDate()));
    assert.ok(/In 30 days/.test(container.textContent));
  });

  await t('one-time job is marked completed and leaves the open list', async () => {
    click($('[data-act="new"]')); await tick();
    set('.f-eq', 'ro'); set('.f-title', 'Replace TDS probe'); set('.f-kind', 'once');
    set('.f-date', new Date().toISOString().slice(0, 10));
    click($('[data-act="savejob"]')); await tick(); await tick(); await tick();
    const btn = [...container.querySelectorAll('[data-act="complete"]')].find((b) => b.closest('tr').textContent.includes('Replace TDS probe'));
    click(btn); await tick();
    set('.c-tech', 'Vendor'); set('.c-desc', 'Probe replaced');
    click($('[data-act="savedone"]')); for (let i = 0; i < 8; i++) await tick();
    const j = jobs('ro').find((x) => x.title === 'Replace TDS probe');
    assert.strictEqual(j.active, false);
    assert.ok(!/Replace TDS probe/.test($('table').textContent));
    click(container.querySelector('[data-filter="done"]')); await tick();
    assert.ok(/Replace TDS probe/.test(container.textContent));
  });

  await t('a click runs its action once (no stacked handlers after re-renders)', async () => {
    let n = 0; const orig = http.post; http.post = (u, b) => { if (u.endsWith('/attributes/SERVER_SCOPE')) n++; return orig(u, b); };
    click(container.querySelector('[data-filter="open"]')); await tick();
    const del = [...container.querySelectorAll('[data-act="deljob"]')].find((b) => b.getAttribute('data-e') === 'ro');
    click(del); for (let i = 0; i < 5; i++) await tick();
    http.post = orig;
    assert.strictEqual(n, 1, 'delete wrote ' + n + ' times');
  });

  await t('deleting a document unlinks it from jobs', async () => {
    click([...container.querySelectorAll('[data-tab]')][1]); await tick();
    click($('[data-act="deldoc"]')); for (let i = 0; i < 8; i++) await tick();
    assert.strictEqual(JSON.parse(attrs['ASSET/lib1'].maint_docs).length, 0);
    assert.strictEqual(jobs('dg1')[0].docs.length, 0);
    assert.strictEqual(Object.keys(resources).length, 0);
  });
  console.log(passed + ' tests passed');
})().catch((e) => { console.error('FAIL:', e.message); process.exit(1); });
