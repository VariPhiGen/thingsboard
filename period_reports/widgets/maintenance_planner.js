// ThingsBoard latest-values widget "Maintenance Management" (CMMS): work orders, maintenance plans, technical documents, KPIs.
//
// Data model (shared with the server-side scheduler, thingsboard/cmms):
//  - Maintenance plans and work orders are ThingsBoard assets of type "Maintenance Plan" / "Work Order", related to the
//    equipment device (relation "Maintenance"). The asset name is the number (PL-0001, WO-2026-00001); ThingsBoard keeps
//    asset names unique, so numbering is safe with several users and the scheduler. Fields are server attributes
//    plan_* / wo_*; *_rev guards against overwriting someone else's change.
//  - Documents are ThingsBoard GENERAL resources; their list (title, category, revision, expiry) is the server attribute
//    maint_docs on the equipment, or on the asset "Maintenance Document Library" for documents of all equipment.
//  - Completing a work order also writes telemetry maintenance_record on the equipment (Maintenance Log, period
//    reports), advances the plan and, for a DG preventive service, restarts the Predictive Maintenance service countdown.
// Lifecycle: Scheduled -> In Progress <-> On Hold -> Completed -> Closed (verified by another user); Cancelled.
// Datasource: alias of all monitored equipment, data key run_hours (live DG run hours).
self.onInit = function () {
  var root = self.ctx.$container[0];
  var http = self.ctx.http;
  var DG_TYPE = 'woodward_kg1500';
  var PLAN_T = 'Maintenance Plan', WO_T = 'Work Order', LIBRARY = 'Maintenance Document Library', REL = 'Maintenance';
  var WO_TYPES = ['Preventive', 'Inspection', 'Corrective', 'Statutory', 'Calibration', 'Condition-based'];
  var PLANNED = {Preventive: 1, Inspection: 1, Statutory: 1, Calibration: 1};
  var PRI = {P1: 'P1 - Emergency (24 h)', P2: 'P2 - Urgent (3 days)', P3: 'P3 - Normal (7 days)', P4: 'P4 - Low (30 days)'};
  var PRI_DAYS = {P1: 1, P2: 3, P3: 7, P4: 30};
  var S = {SCH: 'Scheduled', PRG: 'In Progress', HLD: 'On Hold', CMP: 'Completed', CLS: 'Closed', CAN: 'Cancelled'};
  var OPEN = [S.SCH, S.PRG, S.HLD], ACTIVE = OPEN.concat([S.CMP]);
  var TRANS = {};
  TRANS[S.SCH] = [S.PRG, S.HLD, S.CAN, S.CMP]; TRANS[S.PRG] = [S.HLD, S.CMP, S.CAN]; TRANS[S.HLD] = [S.PRG, S.CAN];
  TRANS[S.CMP] = [S.CLS, S.PRG]; TRANS[S.CLS] = []; TRANS[S.CAN] = [];
  var F_PROBLEM = ['Fails to start', 'Fails while running', 'Overheating', 'Abnormal noise / vibration', 'Leakage', 'Low output / performance',
                   'Electrical fault', 'Instrument / sensor fault', 'Low pressure', 'Structural damage', 'Other'];
  var F_CAUSE = ['Wear / ageing', 'Lack of maintenance', 'Contamination', 'Operating error', 'Design / installation', 'Power supply',
                 'Material defect', 'External / environment', 'Unknown'];
  var F_ACTION = ['Replace', 'Repair', 'Adjust / calibrate', 'Clean', 'Refill / recharge', 'Tighten / secure', 'Settings / software change',
                  'Temporary fix', 'No fault found'];
  var CATS = ['Manual', 'SOP / Procedure', 'Checklist', 'Drawing / Diagram', 'Warranty / AMC', 'Certificate', 'Statutory licence',
              'Service report', 'Photo', 'Other'];
  var WO_KEYS = ['wo_title', 'wo_type', 'wo_priority', 'wo_status', 'wo_source', 'wo_plan_id', 'wo_alarm_id', 'wo_equipment_id',
                 'wo_equipment_name', 'wo_due_date', 'wo_due_rh', 'wo_interval_rh', 'wo_assignee', 'wo_created_ts', 'wo_completed_ts',
                 'wo_closed_ts', 'wo_rev', 'wo_overdue_alerted', 'wo_detail'];
  var PLAN_KEYS = ['plan_title', 'plan_type', 'plan_priority', 'plan_strategy', 'plan_interval_days', 'plan_interval_rh', 'plan_lead_days',
                   'plan_next_due_date', 'plan_next_due_rh', 'plan_active', 'plan_equipment_id', 'plan_equipment_name', 'plan_rev', 'plan_detail'];

  var equipment = [], plans = [], wos = [], general = {id: null, docs: []};
  var claims = jwt();
  var me = {user: claims.sub || '', name: ((claims.firstName || '') + ' ' + (claims.lastName || '')).trim() || claims.sub || ''};
  var state = {tab: 'wo', woFilter: 'open', equip: '', q: '', kpiDays: 30, panel: null, error: ''};

  // ---------------------------------------------------------------- helpers
  function jwt() {
    try { return JSON.parse(atob(window.localStorage.getItem('jwt_token').split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))); } catch (e) { return {}; }
  }
  function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function ymd(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function today() { return ymd(new Date()); }
  function parseYmd(s) { var p = String(s || '').split('-'); return p.length === 3 ? new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2])) : null; }
  function addDays(s, n) { var d = parseYmd(s); d.setDate(d.getDate() + n); return ymd(d); }
  function diffDays(a, b) { return Math.round((parseYmd(a) - parseYmd(b)) / 86400000); }
  function fmtDate(s) { var d = parseYmd(s); return d ? d.toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'}) : ''; }
  function fmtTs(ts) {
    if (!ts) return '';
    var d = new Date(Number(ts));
    return d.toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'}) + ' ' + d.toLocaleTimeString('en-GB', {hour: '2-digit', minute: '2-digit'});
  }
  function localNow() { var d = new Date(Date.now() - new Date().getTimezoneOffset() * 60000); return d.toISOString().slice(0, 16); }
  function size(n) { return n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'; }
  function r1(x) { return Math.round(x * 10) / 10; }
  function num(v) { return v === '' || v == null || !isFinite(Number(v)) ? null : Number(v); }
  function errText(e) { return (e && e.error && e.error.message) || (e && e.message) || (e && e.status) || 'error'; }
  function req(o) { return new Promise(function (res, rej) { o.subscribe(res, rej); }); }
  function byId(list, id) { for (var i = 0; i < list.length; i++) { if (list[i].id === id) return list[i]; } return null; }
  function eq(id) { return byId(equipment, id); }
  function isDg(e) { return !!e && e.type === DG_TYPE; }
  function opts(list, val, labels) { return list.map(function (x) { return '<option value="' + esc(x) + '"' + (x === val ? ' selected' : '') + '>' + esc(labels ? labels[x] : x) + '</option>'; }).join(''); }
  function val(v) {
    if (v == null || v === '' || v === 'null') return null;
    if (typeof v !== 'string') return v;
    if (v === 'true' || v === 'false') return v === 'true';
    if (v.charAt(0) === '{' || v.charAt(0) === '[') { try { return JSON.parse(v); } catch (e) { return v; } }
    if (/^-?\d+(\.\d+)?$/.test(v)) return Number(v);
    return v;
  }
  function hist(action, note, from, to) { return {ts: Date.now(), user: me.user, name: me.name, action: action, from: from || null, to: to || null, note: note || ''}; }

  // ---------------------------------------------------------------- ThingsBoard access
  function attrUrl(type, id) { return '/api/plugins/telemetry/' + type + '/' + id; }
  function readAttrs(type, id, keys) {
    return req(http.get(attrUrl(type, id) + '/values/attributes/SERVER_SCOPE?keys=' + keys.join(','))).then(function (l) {
      var o = {}; (l || []).forEach(function (a) { o[a.key] = val(a.value); }); return o;
    });
  }
  function saveAttrs(type, id, obj) {
    var body = {};
    // ThingsBoard rejects the whole request for a null attribute value; "" clears a field (read back as null)
    Object.keys(obj).forEach(function (k) { var v = obj[k]; body[k] = v == null ? '' : (typeof v === 'object' ? JSON.stringify(v) : v); });
    return req(http.post(attrUrl(type, id) + '/attributes/SERVER_SCOPE', body));
  }
  function query(type, keys, prefix) {
    function page(n, acc) {
      return req(http.post('/api/entitiesQuery/find', {
        entityFilter: {type: 'assetType', assetTypes: [type], assetNameFilter: prefix || ''},
        pageLink: {page: n, pageSize: 500, sortOrder: {key: {type: 'ENTITY_FIELD', key: 'name'}, direction: 'ASC'}},
        entityFields: [{type: 'ENTITY_FIELD', key: 'name'}],
        latestValues: keys.map(function (k) { return {type: 'SERVER_ATTRIBUTE', key: k}; })
      })).then(function (r) {
        (r.data || []).forEach(function (row) {
          var o = {id: row.entityId.id, number: ((row.latest.ENTITY_FIELD || {}).name || {}).value};
          var a = row.latest.SERVER_ATTRIBUTE || {};
          Object.keys(a).forEach(function (k) { o[k.replace(/^(wo|plan)_/, '')] = val(a[k].value); });
          acc.push(o);
        });
        return r.hasNext ? page(n + 1, acc) : acc;
      });
    }
    return page(0, []);
  }
  // Next free number; ThingsBoard rejects a duplicate asset name, then the next number is tried.
  function createNumbered(type, prefix, width, label) {
    return query(type, [], prefix).then(function (list) {
      var max = 0;
      list.forEach(function (x) { var m = new RegExp('^' + prefix.replace(/[-]/g, '\\-') + '(\\d+)$').exec(x.number || ''); if (m) max = Math.max(max, Number(m[1])); });
      function attempt(n, left) {
        var s = String(n); while (s.length < width) s = '0' + s;
        return req(http.post('/api/asset', {name: prefix + s, type: type, label: String(label).slice(0, 255)})).catch(function (e) {
          if (left > 0 && e && e.status === 400) return attempt(n + 1, left - 1);
          throw e;
        });
      }
      return attempt(max + 1, 25);
    });
  }
  function relate(deviceId, assetId) {
    return req(http.post('/api/relation', {from: {entityType: 'DEVICE', id: deviceId}, to: {entityType: 'ASSET', id: assetId}, type: REL, typeGroup: 'COMMON'}));
  }
  // Optimistic concurrency: refuse to write when the record changed since it was loaded.
  function guardedSave(rec, prefix, values) {
    return readAttrs('ASSET', rec.id, [prefix + 'rev']).then(function (cur) {
      var r = cur[prefix + 'rev'];
      if (r != null && rec.rev != null && Number(r) !== Number(rec.rev)) {
        throw {message: rec.number + ' was changed by someone else meanwhile. Close this form and open it again.'};
      }
      values[prefix + 'rev'] = Number(r || 0) + 1;
      return saveAttrs('ASSET', rec.id, values);
    });
  }

  // ---------------------------------------------------------------- domain rules (same as cmms/model.py)
  function meterWindow(i) { return Math.max(10, (Number(i) || 0) * 0.1); }
  function dueState(w) {
    if (w.status === S.CLS || w.status === S.CAN) return 'closed';
    if (w.status === S.CMP) return 'done';
    if (w.due_rh != null) {
      var e = eq(w.equipment_id), rh = e && e.runHours;
      if (rh == null) return 'unknown';
      var left = w.due_rh - rh;
      return left < 0 ? 'overdue' : (left <= meterWindow(w.interval_rh) ? 'due' : 'upcoming');
    }
    if (!w.due_date) return 'unknown';
    var d = diffDays(w.due_date, today());
    return d < 0 ? 'overdue' : (d <= 7 ? 'due' : 'upcoming');
  }
  function dueText(w) {
    if (w.due_rh != null) {
      var e = eq(w.equipment_id), rh = e && e.runHours;
      var base = 'at ' + w.due_rh + ' run-h';
      if (rh == null || ACTIVE.indexOf(w.status) < 0 || w.status === S.CMP) return base;
      var left = r1(w.due_rh - rh);
      return base + ' (' + (left < 0 ? r1(-left) + ' h over' : left + ' h left') + ')';
    }
    if (!w.due_date) return '';
    if (OPEN.indexOf(w.status) < 0) return fmtDate(w.due_date);
    var d = diffDays(w.due_date, today());
    return fmtDate(w.due_date) + ' (' + (d < 0 ? (-d) + ' d over' : d === 0 ? 'today' : 'in ' + d + ' d') + ')';
  }
  function allowed(w, to) { return (TRANS[w.status] || []).indexOf(to) >= 0; }
  function planGenerationDue(p) {
    if (p.active === false) return false;
    if (p.strategy === 'meter') { var e = eq(p.equipment_id); return !!(e && e.runHours != null && p.next_due_rh != null && e.runHours >= p.next_due_rh - meterWindow(p.interval_rh)); }
    return !!p.next_due_date && diffDays(p.next_due_date, today()) <= Number(p.lead_days || 7);
  }
  function planAfterCompletion(p, doneDate, doneRh) {
    if (p.strategy === 'meter') return {plan_next_due_rh: r1(Number(doneRh) + Number(p.interval_rh))};
    if (!(Number(p.interval_days) > 0)) return {plan_active: false};
    return {plan_next_due_date: addDays(doneDate, Number(p.interval_days))};
  }
  function planAfterSkip(p, w) {
    if (p.strategy === 'meter') return {plan_next_due_rh: r1(Number(w.due_rh != null ? w.due_rh : p.next_due_rh) + Number(p.interval_rh))};
    if (!(Number(p.interval_days) > 0)) return {plan_active: false};
    return {plan_next_due_date: addDays(w.due_date || p.next_due_date || today(), Number(p.interval_days))};
  }
  function docState(d) {
    if (!d.expiry) return null;
    var n = diffDays(d.expiry, today());
    return n < 0 ? {k: 'expired', t: 'Expired ' + fmtDate(d.expiry)} : n <= 30 ? {k: 'expiring', t: 'Expires ' + fmtDate(d.expiry)} : {k: 'valid', t: 'Valid to ' + fmtDate(d.expiry)};
  }

  // ---------------------------------------------------------------- loading
  function loadEquipment() {
    var seen = {};
    equipment = [];
    (self.ctx.datasources || []).forEach(function (ds) {
      if (!ds.entityId || seen[ds.entityId]) return;
      seen[ds.entityId] = true;
      equipment.push({id: ds.entityId, name: ds.entityName, type: null, runHours: null, docs: []});
    });
    equipment.sort(function (a, b) { return a.name.localeCompare(b.name); });
    var lib = req(http.get('/api/tenant/assets?assetName=' + encodeURIComponent(LIBRARY))).then(function (a) { general.id = a && a.id ? a.id.id : null; }, function () { general.id = null; });
    return Promise.all(equipment.map(function (e) {
      return req(http.get('/api/device/' + e.id)).then(function (d) { e.type = d.type; }, function () {});
    }).concat([lib]));
  }
  function updateRunHours() {
    (self.ctx.data || []).forEach(function (d) {
      var e = eq(d.datasource && d.datasource.entityId);
      if (!e || !d.data) return;
      for (var i = d.data.length - 1; i >= 0; i--) {
        var v = Number(d.data[i][1]);
        if (isFinite(v) && v >= 0 && v < 30000) { e.runHours = r1(v); return; }
      }
    });
  }
  function loadData() {
    var steps = [query(WO_T, WO_KEYS).then(function (l) { wos = l; }), query(PLAN_T, PLAN_KEYS).then(function (l) { plans = l; })];
    equipment.forEach(function (e) {
      steps.push(readAttrs('DEVICE', e.id, ['maint_docs']).then(function (a) { e.docs = a.maint_docs || []; }, function () { e.docs = []; }));
    });
    if (general.id) steps.push(readAttrs('ASSET', general.id, ['maint_docs']).then(function (a) { general.docs = a.maint_docs || []; }, function () {}));
    return Promise.all(steps).then(function () { state.error = ''; }, function (e) { state.error = 'Could not load maintenance data: ' + errText(e); });
  }
  function reload() { return loadData().then(render); }
  function allDocs() {
    var out = general.docs.map(function (d) { return {d: d, owner: 'general', ownerName: 'All equipment'}; });
    equipment.forEach(function (e) { e.docs.forEach(function (d) { out.push({d: d, owner: e.id, ownerName: e.name}); }); });
    return out;
  }
  function findDoc(id) { var l = allDocs(); for (var i = 0; i < l.length; i++) { if (l[i].d.id === id) return l[i]; } return null; }
  function docsFor(eid) { return general.docs.map(function (d) { return {d: d, o: 'All equipment'}; }).concat(((eq(eid) || {}).docs || []).map(function (d) { return {d: d, o: eq(eid).name}; })); }

  // ---------------------------------------------------------------- documents
  function download(id) {
    var x = findDoc(id), name = (x && (x.d.file || x.d.title)) || 'document';
    http.get('/api/resource/' + id + '/download', {responseType: 'blob'}).subscribe(function (blob) {
      var url = URL.createObjectURL(blob), a = document.createElement('a');
      a.href = url; a.download = name; document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1000);
    }, function (e) { window.alert('Download failed: ' + errText(e)); });
  }
  function uploadFile(file, title) {
    if (file.size > 50 * 1048576) return Promise.reject({message: file.name + ' is larger than 50 MB'});
    var fd = new FormData();
    fd.append('file', file, file.name); fd.append('resourceType', 'GENERAL'); fd.append('title', title || file.name);
    return req(http.post('/api/resource/upload', fd)).then(function (r) {
      return {id: r.id.id, title: title || file.name, file: file.name, size: file.size, uploaded_by: me.name, uploaded_at: Date.now()};
    });
  }
  function appendDocs(owner, metas) {
    var type = owner === 'general' ? 'ASSET' : 'DEVICE', id = owner === 'general' ? general.id : owner;
    return readAttrs(type, id, ['maint_docs']).then(function (a) { return saveAttrs(type, id, {maint_docs: (a.maint_docs || []).concat(metas)}); });
  }
  function docLinks(ids) {
    return (ids || []).map(function (id) { var x = findDoc(id); return x ? '<span class="doc" data-doc="' + esc(id) + '">&#128196; ' + esc(x.d.title) + (x.d.revision ? ' (rev ' + esc(x.d.revision) + ')' : '') + '</span>' : ''; }).join('');
  }

  // ---------------------------------------------------------------- rendering
  function counts() {
    var c = {open: 0, overdue: 0, due: 0, progress: 0, hold: 0, verify: 0, closed: 0};
    wos.forEach(function (w) {
      var ds = dueState(w);
      if (OPEN.indexOf(w.status) >= 0) c.open++;
      if (OPEN.indexOf(w.status) >= 0 && ds === 'overdue') c.overdue++;
      if (OPEN.indexOf(w.status) >= 0 && ds === 'due') c.due++;
      if (w.status === S.PRG) c.progress++;
      if (w.status === S.HLD) c.hold++;
      if (w.status === S.CMP) c.verify++;
      if (w.status === S.CLS || w.status === S.CAN) c.closed++;
    });
    return c;
  }
  function render() {
    var c = counts();
    var expiring = allDocs().filter(function (x) { var s = docState(x.d); return s && s.k !== 'valid'; }).length;
    var h = '<div class="mp">' + (state.error ? '<div class="mp-err">' + esc(state.error) + '</div>' : '') +
      '<div class="mp-tabs">' + [['wo', 'Work orders', c.overdue], ['plans', 'Maintenance plans', 0], ['docs', 'Technical documents', expiring], ['kpi', 'KPIs', 0]].map(function (t) {
        return '<button class="mp-tab' + (state.tab === t[0] ? ' on' : '') + '" data-tab="' + t[0] + '">' + t[1] + (t[2] ? '<span class="n">' + t[2] + '</span>' : '') + '</button>';
      }).join('') + '</div><div class="mp-panel-slot"></div>';
    if (state.tab === 'wo') h += woView(c);
    else if (state.tab === 'plans') h += plansView();
    else if (state.tab === 'docs') h += docsView();
    else h += kpiView();
    root.innerHTML = h + '</div>';
    var eqf = root.querySelector('.mp-eqf');
    if (eqf) eqf.addEventListener('change', function () { state.equip = eqf.value; render(); });
    var qf = root.querySelector('.mp-q');
    if (qf) qf.addEventListener('change', function () { state.q = qf.value; render(); });
    var kd = root.querySelector('.mp-kd');
    if (kd) kd.addEventListener('change', function () { state.kpiDays = Number(kd.value); render(); });
    if (state.panel) openPanel(state.panel.kind, state.panel.arg, true);
  }
  function equipSelect(cls, v, withAll, withGeneral) {
    var o = (withAll ? '<option value="">All equipment</option>' : '') + (withGeneral && general.id ? '<option value="general"' + (v === 'general' ? ' selected' : '') + '>All equipment (general document)</option>' : '');
    equipment.forEach(function (e) { o += '<option value="' + e.id + '"' + (v === e.id ? ' selected' : '') + '>' + esc(e.name) + '</option>'; });
    return '<select class="' + cls + '">' + o + '</select>';
  }
  function statusCls(s) { return {Scheduled: '', 'In Progress': 's-progress', 'On Hold': 's-hold', Completed: 's-completed', Closed: 's-closed', Cancelled: 's-cancelled'}[s] || ''; }
  function woView(c) {
    var chips = [['open', 'Open', c.open, ''], ['overdue', 'Overdue', c.overdue, 'red'], ['due', 'Due within 7 days', c.due, 'amber'], ['progress', 'In progress', c.progress, ''],
                 ['hold', 'On hold', c.hold, ''], ['verify', 'Awaiting verification', c.verify, 'amber'], ['closed', 'Closed / cancelled', c.closed, ''], ['all', 'All', wos.length, '']];
    var h = '<div class="mp-top">' + chips.map(function (x) {
      return '<span class="mp-chip ' + x[3] + (state.woFilter === x[0] ? ' active' : '') + '" data-filter="' + x[0] + '">' + x[1] + ' (' + x[2] + ')</span>';
    }).join('') + '</div><div class="mp-top">' + equipSelect('mp-eqf', state.equip, true) +
      '<input class="mp-q search" placeholder="Search number, title, assignee" value="' + esc(state.q) + '"><span class="mp-sp"></span>' +
      '<button class="mp-btn" data-act="newwo">+ New work order</button></div>';
    var q = state.q.toLowerCase();
    var rows = wos.filter(function (w) {
      if (state.equip && w.equipment_id !== state.equip) return false;
      if (q && ((w.number || '') + ' ' + (w.title || '') + ' ' + (w.assignee || '') + ' ' + (w.equipment_name || '')).toLowerCase().indexOf(q) < 0) return false;
      var ds = dueState(w), f = state.woFilter;
      if (f === 'open') return OPEN.indexOf(w.status) >= 0;
      if (f === 'overdue') return OPEN.indexOf(w.status) >= 0 && ds === 'overdue';
      if (f === 'due') return OPEN.indexOf(w.status) >= 0 && ds === 'due';
      if (f === 'progress') return w.status === S.PRG;
      if (f === 'hold') return w.status === S.HLD;
      if (f === 'verify') return w.status === S.CMP;
      if (f === 'closed') return w.status === S.CLS || w.status === S.CAN;
      return true;
    });
    var rank = {overdue: 0, due: 1, unknown: 2, upcoming: 3, done: 4, closed: 5};
    rows.sort(function (a, b) {
      return (rank[dueState(a)] - rank[dueState(b)]) || String(a.priority).localeCompare(String(b.priority)) || String(b.number).localeCompare(String(a.number));
    });
    if (!rows.length) {
      return h + '<div class="mp-empty">' + (wos.length ? 'No work orders in this view.' : 'No work orders yet. Create maintenance plans (they raise preventive work orders automatically) or use "+ New work order" for corrective work.') + '</div>';
    }
    return h + '<table><thead><tr><th>WO number</th><th>Work</th><th>Equipment</th><th>Priority</th><th>Status</th><th>Due</th><th>Assigned to</th><th>Source</th></tr></thead><tbody>' +
      rows.map(function (w) {
        var ds = dueState(w), d = w.detail || {};
        return '<tr class="click' + (state.panel && state.panel.arg === w.id ? ' sel' : '') + '" data-act="viewwo" data-id="' + w.id + '"><td class="num">' + esc(w.number) + '</td>' +
          '<td><b>' + esc(w.title) + '</b><div class="sub"><span class="tag">' + esc(w.type) + '</span>' + ((d.checklist || []).length ? d.checklist.length + ' checklist steps' : '') + '</div></td>' +
          '<td class="nw">' + esc(w.equipment_name) + '</td><td><span class="pill ' + esc(w.priority) + '">' + esc(w.priority) + '</span></td>' +
          '<td><span class="st ' + statusCls(w.status) + '">' + esc(w.status) + '</span></td>' +
          '<td class="nw">' + (ds === 'overdue' || ds === 'due' ? '<span class="pill ' + ds + '">' + (ds === 'overdue' ? 'Overdue' : 'Due') + '</span> ' : '') + esc(dueText(w)) + '</td>' +
          '<td>' + esc(w.assignee || '-') + '</td><td class="nw sub">' + esc({plan: 'Plan ' + (d.plan_number || ''), alarm: 'Alarm', manual: 'Manual'}[w.source] || w.source || '') + '</td></tr>';
      }).join('') + '</tbody></table>';
  }
  function plansView() {
    var h = '<div class="mp-top"><span class="sub">Preventive maintenance plans raise work orders automatically when an occurrence enters its lead time (server checks every 10 minutes).</span>' +
      '<span class="mp-sp"></span>' + equipSelect('mp-eqf', state.equip, true) + '<button class="mp-btn" data-act="newplan">+ New plan</button></div>';
    var rows = plans.filter(function (p) { return !state.equip || p.equipment_id === state.equip; });
    rows.sort(function (a, b) { return String(a.number).localeCompare(String(b.number)); });
    if (!rows.length) return h + '<div class="mp-empty">No maintenance plans yet. Example: "DG 250 h service" every 250 run-hours, "RO membrane cleaning" every 30 days, "Fire cylinder inspection" every 90 days.</div>';
    return h + '<table><thead><tr><th>Plan</th><th>Work</th><th>Equipment</th><th>Interval</th><th>Next due</th><th>Priority</th><th>Assigned to</th><th>Last done</th><th>Status</th><th></th></tr></thead><tbody>' +
      rows.map(function (p) {
        var d = p.detail || {}, open = wos.filter(function (w) { return w.plan_id === p.id && ACTIVE.indexOf(w.status) >= 0; })[0];
        var e = eq(p.equipment_id);
        var next = p.strategy === 'meter' ? 'at ' + p.next_due_rh + ' run-h' + (e && e.runHours != null ? '<div class="sub">now ' + e.runHours + ' run-h</div>' : '') : fmtDate(p.next_due_date);
        return '<tr><td class="num">' + esc(p.number) + '</td><td><b>' + esc(p.title) + '</b><div class="sub"><span class="tag">' + esc(p.type) + '</span>' +
          ((d.checklist || []).length ? d.checklist.length + ' steps' : '') + ((d.docs || []).length ? ' &middot; ' + d.docs.length + ' documents' : '') + '</div></td>' +
          '<td class="nw">' + esc(p.equipment_name) + '</td><td class="nw">' + (p.strategy === 'meter' ? 'Every ' + p.interval_rh + ' run-h' : 'Every ' + p.interval_days + ' days') +
          (p.strategy === 'meter' ? '' : '<div class="sub">raised ' + (p.lead_days || 7) + ' days ahead</div>') + '</td><td class="nw">' + next + '</td>' +
          '<td><span class="pill ' + esc(p.priority) + '">' + esc(p.priority) + '</span></td><td>' + esc(d.assignee || '-') + '</td>' +
          '<td class="nw">' + (d.last_done_ts ? fmtTs(d.last_done_ts) + '<div class="sub">' + esc(d.last_wo || '') + '</div>' : '<span class="sub">never</span>') + '</td>' +
          '<td>' + (p.active === false ? '<span class="pill closed">Paused</span>' : open ? '<span class="pill upcoming">' + esc(open.number) + '</span>' : '<span class="pill done">Active</span>') + '</td>' +
          '<td><div class="acts"><button class="mp-btn small light" data-act="editplan" data-id="' + p.id + '">Edit</button>' +
          '<button class="mp-btn small light" data-act="toggleplan" data-id="' + p.id + '">' + (p.active === false ? 'Resume' : 'Pause') + '</button>' +
          (p.active !== false && !open ? '<button class="mp-btn small" data-act="raisenow" data-id="' + p.id + '" title="Raise the next work order now">Raise WO now</button>' : '') + '</div></td></tr>';
      }).join('') + '</tbody></table>';
  }
  function docsView() {
    var h = '<div class="mp-top"><span class="sub">Manuals, SOPs, checklists, drawings, AMC and certificates. Expiry dates are alerted 30 days ahead.</span><span class="mp-sp"></span>' +
      equipSelect('mp-eqf', state.equip, true) + '<button class="mp-btn" data-act="upload">+ Upload document</button></div>';
    var list = allDocs().filter(function (x) { return !state.equip || x.owner === state.equip || x.owner === 'general'; });
    list.sort(function (a, b) { return (b.d.uploaded_at || 0) - (a.d.uploaded_at || 0); });
    if (!list.length) return h + '<div class="mp-empty">No documents yet.</div>';
    return h + '<table><thead><tr><th>Document</th><th>Category</th><th>Rev</th><th>Validity</th><th>Equipment</th><th>File</th><th>Uploaded</th><th>Used by</th><th></th></tr></thead><tbody>' +
      list.map(function (x) {
        var st = docState(x.d);
        var used = plans.filter(function (p) { return ((p.detail || {}).docs || []).indexOf(x.d.id) >= 0; }).map(function (p) { return p.number; });
        return '<tr><td><span class="doc" data-doc="' + esc(x.d.id) + '">&#128196; ' + esc(x.d.title) + '</span>' + (x.d.doc_no ? '<div class="sub">' + esc(x.d.doc_no) + '</div>' : '') + '</td>' +
          '<td><span class="tag">' + esc(x.d.category || 'Other') + '</span></td><td>' + esc(x.d.revision || '-') + '</td>' +
          '<td class="nw">' + (st ? '<span class="pill ' + st.k + '">' + esc(st.t) + '</span>' : '<span class="sub">-</span>') + '</td>' +
          '<td class="nw">' + esc(x.ownerName) + '</td><td class="nw">' + esc(x.d.file) + '<div class="sub">' + (x.d.size ? size(x.d.size) : '') + '</div></td>' +
          '<td class="nw">' + fmtTs(x.d.uploaded_at) + '<div class="sub">' + esc(x.d.uploaded_by) + '</div></td><td>' + (used.length ? esc(used.join(', ')) : '<span class="sub">-</span>') + '</td>' +
          '<td><div class="acts"><button class="mp-btn small light" data-doc="' + esc(x.d.id) + '">Download</button>' +
          '<button class="mp-btn small danger" data-act="deldoc" data-o="' + esc(x.owner) + '" data-d="' + esc(x.d.id) + '" title="Delete document">&times;</button></div></td></tr>';
      }).join('') + '</tbody></table>';
  }
  function kpis(list, start, end) {
    var dueIn = 0, onTime = 0, done = [];
    list.forEach(function (w) {
      if (w.status === S.CAN) return;
      var comp = w.completed_ts ? ymd(new Date(Number(w.completed_ts))) : null;
      if (PLANNED[w.type] && w.due_date && w.due_date >= start && w.due_date <= end) { dueIn++; if (comp && comp <= w.due_date) onTime++; }
      if (comp && comp >= start && comp <= end) done.push(w);
    });
    var corr = done.filter(function (w) { return w.type === 'Corrective' || w.type === 'Condition-based'; });
    var mttr = corr.filter(function (w) { return w.created_ts && w.completed_ts; }).map(function (w) { return (w.completed_ts - w.created_ts) / 3600000; });
    var open = list.filter(function (w) { return OPEN.indexOf(w.status) >= 0; });
    var sum = function (a, f) { return a.reduce(function (s, w) { return s + (Number((w.detail || {})[f]) || 0); }, 0); };
    return {pmDue: dueIn, pmOnTime: onTime, pmc: dueIn ? r1(onTime * 100 / dueIn) : null, backlog: open.length,
            overdue: open.filter(function (w) { return dueState(w) === 'overdue'; }).length, done: done.length, corr: corr.length,
            mttr: mttr.length ? r1(mttr.reduce(function (a, b) { return a + b; }, 0) / mttr.length) : null,
            planned: done.length ? r1((done.length - corr.length) * 100 / done.length) : null,
            labour: r1(sum(done, 'labour_hours')), downtime: r1(sum(done, 'downtime_hours')), cost: Math.round(sum(done, 'cost_total'))};
  }
  function kpiView() {
    var end = today(), start = addDays(end, -(state.kpiDays - 1));
    var k = kpis(wos, start, end);
    function card(v, l, hint, cls) { return '<div class="mp-kpi ' + (cls || '') + '"><div class="v">' + (v == null ? '--' : v) + '</div><div class="l">' + l + '</div><div class="h">' + hint + '</div></div>'; }
    var h = '<div class="mp-top"><b>Maintenance KPIs</b><span class="sub">' + fmtDate(start) + ' - ' + fmtDate(end) + '</span><span class="mp-sp"></span>' +
      '<select class="mp-kd">' + [30, 90, 180, 365].map(function (d) { return '<option value="' + d + '"' + (d === state.kpiDays ? ' selected' : '') + '>Last ' + d + ' days</option>'; }).join('') + '</select></div>' +
      '<div class="mp-kpis">' +
      card(k.pmc == null ? null : k.pmc + '%', 'PM compliance', k.pmOnTime + ' of ' + k.pmDue + ' planned WOs done by due date', k.pmc == null ? '' : k.pmc >= 90 ? 'good' : k.pmc < 75 ? 'bad' : '') +
      card(k.backlog, 'Open backlog', 'open work orders now') + card(k.overdue, 'Overdue', 'open and past due', k.overdue ? 'bad' : 'good') +
      card(k.done, 'Completed', 'work orders completed in period') +
      card(k.planned == null ? null : k.planned + '%', 'Planned work', 'share of planned vs corrective', k.planned == null ? '' : k.planned >= 80 ? 'good' : '') +
      card(k.mttr == null ? null : k.mttr + ' h', 'Mean time to repair', 'corrective: raised -> completed (' + k.corr + ')') +
      card(k.labour + ' h', 'Labour', 'hours booked on completed WOs') + card(k.downtime + ' h', 'Downtime', 'equipment downtime recorded') +
      card('INR ' + k.cost.toLocaleString('en-IN'), 'Maintenance cost', 'parts and services on completed WOs') + '</div>';
    var rows = equipment.map(function (e) {
      var l = wos.filter(function (w) { return w.equipment_id === e.id; }), x = kpis(l, start, end);
      return '<tr><td>' + esc(e.name) + '</td><td>' + x.backlog + '</td><td>' + (x.overdue ? '<span class="pill overdue">' + x.overdue + '</span>' : 0) + '</td><td>' + x.done + '</td>' +
        '<td>' + x.corr + '</td><td>' + (x.pmc == null ? '--' : x.pmc + '%') + '</td><td>' + (x.mttr == null ? '--' : x.mttr + ' h') + '</td><td>' + x.downtime + '</td><td>' + x.cost.toLocaleString('en-IN') + '</td></tr>';
    }).join('');
    return h + '<table style="margin-top:10px"><thead><tr><th>Equipment</th><th>Open</th><th>Overdue</th><th>Completed</th><th>Corrective</th><th>PM compliance</th><th>MTTR</th><th>Downtime h</th><th>Cost INR</th></tr></thead><tbody>' + rows + '</tbody></table>' +
      '<div class="sub" style="margin-top:6px">KPIs are calculated only from work orders recorded here; "--" means no data in the period.</div>';
  }

  // ---------------------------------------------------------------- panels
  function slot() { return root.querySelector('.mp-panel-slot'); }
  function closePanel() { state.panel = null; render(); }
  function openPanel(kind, arg, keep) {
    state.panel = {kind: kind, arg: arg};
    var ok = ({wo: woDetail, newwo: woForm, editwo: woForm, complete: completeForm, reason: reasonForm, plan: planForm, upload: uploadForm})[kind](arg);
    if (ok === false) { state.panel = null; return; }
    if (!keep && slot().scrollIntoView) slot().scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }
  function pstatus(t, k) { var s = slot().querySelector('.mp-status'); if (s) { s.textContent = t || ''; s.className = 'mp-status ' + (k || ''); } }
  function busy(on) { [].slice.call(slot().querySelectorAll('button')).forEach(function (b) { b.disabled = on; }); }
  function fail(e) { busy(false); pstatus('Not saved: ' + errText(e), 'bad'); }
  function done(msg) { state.panel = null; return reload().then(function () { if (msg) flash(msg); }); }
  function flash(msg) { var s = root.querySelector('.mp-tabs'); if (s) { var d = document.createElement('div'); d.className = 'mp-hl'; d.textContent = msg; s.parentNode.insertBefore(d, s.nextSibling); setTimeout(function () { d.remove(); }, 6000); } }

  function woDetail(id) {
    var w = byId(wos, id);
    if (!w) return false;
    var d = w.detail || {}, ds = dueState(w), e = eq(w.equipment_id);
    var acts = '';
    if (allowed(w, S.PRG) && w.status !== S.CMP) acts += '<button class="mp-btn" data-act="start">' + (w.status === S.HLD ? 'Resume work' : 'Start work') + '</button>';
    if (allowed(w, S.CMP)) acts += '<button class="mp-btn ok" data-act="complete">Record work done</button>';
    if (allowed(w, S.HLD)) acts += '<button class="mp-btn warn" data-act="hold">Put on hold</button>';
    if (w.status === S.CMP) {
      var own = (d.completed_by || {}).user === me.user;
      acts += '<button class="mp-btn ok" data-act="verify"' + (own ? ' disabled title="Another user must verify your work"' : '') + '>Verify &amp; close</button>' +
        '<button class="mp-btn warn" data-act="reject">Reject (rework)</button>' + (own ? '<span class="sub">You recorded this work, so another user must verify it.</span>' : '');
    }
    if (OPEN.indexOf(w.status) >= 0) acts += '<button class="mp-btn light" data-act="editwo">Edit</button>';
    if (allowed(w, S.CAN)) acts += '<button class="mp-btn danger" data-act="cancel">Cancel WO</button>';
    acts += '<button class="mp-btn light" data-act="print">Print job card</button><button class="mp-btn light" data-act="close">Close</button>';
    var res = d.results || [];
    var cl = (d.checklist || []).map(function (s, i) {
      var r = res[i];
      return '<div>' + (r ? (r.done ? '&#9745; ' : '&#9744; ') : '&#9744; ') + esc(s) + (r && r.note ? ' <span class="sub">- ' + esc(r.note) + '</span>' : '') + '</div>';
    }).join('');
    var parts = (d.parts || []).map(function (p) { return esc(p.name) + ' x ' + esc(p.qty) + (p.rate ? ' @ INR ' + esc(p.rate) : ''); }).join('; ');
    slot().innerHTML = '<div class="mp-panel"><h4>' + esc(w.number) + ' &middot; ' + esc(w.title) + ' <span class="pill ' + esc(w.priority) + '">' + esc(PRI[w.priority] || w.priority) + '</span>' +
      '<span class="st ' + statusCls(w.status) + '">' + esc(w.status) + '</span>' + (ds === 'overdue' ? '<span class="pill overdue">Overdue</span>' : '') + '</h4>' +
      '<div class="mp-kv"><div><b>Equipment</b>' + esc(w.equipment_name) + (isDg(e) && e.runHours != null ? ' <span class="sub">(now ' + e.runHours + ' run-h)</span>' : '') + '</div>' +
      '<div><b>Type</b>' + esc(w.type) + '</div><div><b>Due</b>' + esc(dueText(w) || '-') + '</div><div><b>Assigned to</b>' + esc(w.assignee || '-') + '</div>' +
      '<div><b>Raised</b>' + fmtTs(w.created_ts) + '<div class="sub">' + esc({plan: 'from plan ' + (d.plan_number || ''), alarm: 'by alarm ' + (d.alarm_type || ''), manual: 'manually'}[w.source] || '') + '</div></div>' +
      (d.est_hours ? '<div><b>Estimated</b>' + esc(d.est_hours) + ' h</div>' : '') +
      (w.completed_ts ? '<div><b>Completed</b>' + fmtTs(w.completed_ts) + '<div class="sub">' + esc(d.technician || '') + (d.completed_by ? ', recorded by ' + esc(d.completed_by.name) : '') + '</div></div>' : '') +
      (w.closed_ts && w.status === S.CLS ? '<div><b>Verified</b>' + fmtTs(w.closed_ts) + '<div class="sub">' + esc((d.verified_by || {}).name || '') + '</div></div>' : '') + '</div>' +
      (d.description ? '<h5>Description</h5><div>' + esc(d.description) + '</div>' : '') +
      ((d.docs || []).length ? '<h5>Technical documents</h5><div>' + docLinks(d.docs) + '</div>' : '') +
      (cl ? '<h5>Checklist</h5>' + cl : '') +
      (d.work_done ? '<h5>Work done</h5><div>' + esc(d.work_done) + '</div><div class="mp-kv" style="margin-top:6px">' +
        (d.done_rh != null ? '<div><b>Run hours</b>' + esc(d.done_rh) + '</div>' : '') + '<div><b>Labour</b>' + esc(d.labour_hours || 0) + ' h</div><div><b>Downtime</b>' + esc(d.downtime_hours || 0) + ' h</div>' +
        '<div><b>Cost</b>INR ' + esc(d.cost_total || 0) + '</div>' + (d.failure && d.failure.problem ? '<div><b>Failure</b>' + esc(d.failure.problem) + ' / ' + esc(d.failure.cause) + ' / ' + esc(d.failure.action) + '</div>' : '') + '</div>' +
        (parts ? '<div class="sub">Parts: ' + parts + '</div>' : '') + ((d.attachments || []).length ? '<div style="margin-top:4px">' + docLinks(d.attachments.map(function (a) { return a.id; })) + '</div>' : '') : '') +
      (d.hold_reason && w.status === S.HLD ? '<div class="mp-hl" style="margin-top:8px">On hold: ' + esc(d.hold_reason) + '</div>' : '') +
      (d.cancel_reason ? '<div class="mp-hl" style="margin-top:8px">Cancelled: ' + esc(d.cancel_reason) + '</div>' : '') +
      '<h5>History</h5><div class="mp-tl">' + (d.history || []).slice().reverse().map(function (x) {
        return '<div><b>' + esc(x.action) + '</b>' + (x.to ? ' &rarr; ' + esc(x.to) : '') + ' &middot; ' + fmtTs(x.ts) + ' &middot; ' + esc(x.name || x.user) + (x.note ? '<div class="sub">' + esc(x.note) + '</div>' : '') + '</div>';
      }).join('') + '</div><div class="mp-row">' + acts + '<span class="mp-status"></span></div></div>';
  }

  function woForm(arg) {
    var w = arg && arg.id ? byId(wos, arg.id) : null, d = (w && w.detail) || {};
    var e0 = w ? w.equipment_id : (state.equip || (equipment[0] && equipment[0].id));
    var pri = w ? w.priority : 'P3';
    slot().innerHTML = '<div class="mp-panel"><h4>' + (w ? 'Edit ' + esc(w.number) : 'New work order') + '</h4><div class="mp-grid">' +
      '<label>Equipment <span class="req">*</span>' + equipSelect('f-eq', e0, false) + '</label>' +
      '<label class="wide">Title <span class="req">*</span><input class="f-title" maxlength="120" value="' + esc(w ? w.title : '') + '" placeholder="e.g. Coolant leak at radiator hose"></label>' +
      '<label>Type<select class="f-type">' + opts(WO_TYPES, w ? w.type : 'Corrective') + '</select></label>' +
      '<label>Priority<select class="f-pri">' + opts(['P1', 'P2', 'P3', 'P4'], pri, PRI) + '</select></label>' +
      '<label class="w-date">Due date <span class="req">*</span><input type="date" class="f-date" value="' + esc(w ? (w.due_date || '') : addDays(today(), PRI_DAYS[pri])) + '"></label>' +
      '<label class="w-rh">Due at run-hours<input type="number" class="f-rh" step="0.1" min="0" value="' + esc(w && w.due_rh != null ? w.due_rh : '') + '" placeholder="DG only, optional"></label>' +
      '<label>Assigned to<input class="f-asg" maxlength="80" value="' + esc(w ? w.assignee : '') + '" placeholder="Technician / vendor"></label>' +
      '<label>Estimated hours<input type="number" class="f-est" step="0.5" min="0" value="' + esc(d.est_hours || '') + '"></label>' +
      '<label class="wide">Description<textarea class="f-desc" rows="2" maxlength="1000">' + esc(d.description || '') + '</textarea></label>' +
      '<label class="wide">Checklist (one step per line)<textarea class="f-cl" rows="3">' + esc((d.checklist || []).join('\n')) + '</textarea></label>' +
      '<div class="mp-field wide">Technical documents<div class="mp-checks f-docs"></div></div>' +
      '</div><div class="mp-row"><button class="mp-btn" data-act="savewo">' + (w ? 'Save changes' : 'Create work order') + '</button><button class="mp-btn light" data-act="close">Cancel</button><span class="mp-status"></span></div></div>';
    var p = slot();
    function sync() {
      var ee = eq(p.querySelector('.f-eq').value);
      p.querySelector('.w-rh').style.display = isDg(ee) ? '' : 'none';
      var av = docsFor(ee && ee.id);
      p.querySelector('.f-docs').innerHTML = av.length ? av.map(function (x) {
        return '<label><input type="checkbox" value="' + esc(x.d.id) + '"' + ((d.docs || []).indexOf(x.d.id) >= 0 ? ' checked' : '') + '> ' + esc(x.d.title) + ' <span class="sub">(' + esc(x.d.category) + ', ' + esc(x.o) + ')</span></label>';
      }).join('') : '<span class="sub">No documents for this equipment yet.</span>';
    }
    p.querySelector('.f-eq').addEventListener('change', sync);
    p.querySelector('.f-pri').addEventListener('change', function () { if (!w) p.querySelector('.f-date').value = addDays(today(), PRI_DAYS[p.querySelector('.f-pri').value]); });
    if (w) p.querySelector('.f-eq').disabled = true;
    sync();
    p.querySelector('[data-act="savewo"]').addEventListener('click', function () {
      var ee = eq(p.querySelector('.f-eq').value), title = p.querySelector('.f-title').value.trim(), due = p.querySelector('.f-date').value;
      if (!ee || !title || !due) { pstatus('Equipment, title and due date are required.', 'bad'); return; }
      var rh = isDg(ee) ? num(p.querySelector('.f-rh').value) : null;
      var f = {title: title, type: p.querySelector('.f-type').value, priority: p.querySelector('.f-pri').value, due_date: due, due_rh: rh,
               assignee: p.querySelector('.f-asg').value.trim()};
      var det = JSON.parse(JSON.stringify(d));
      det.description = p.querySelector('.f-desc').value.trim();
      det.checklist = p.querySelector('.f-cl').value.split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
      det.docs = [].slice.call(p.querySelectorAll('.f-docs input:checked')).map(function (c) { return c.value; });
      det.est_hours = num(p.querySelector('.f-est').value);
      busy(true); pstatus('Saving…');
      if (w) {
        var changes = ['title', 'priority', 'due_date', 'due_rh', 'assignee', 'type'].filter(function (k) { return String(w[k] == null ? '' : w[k]) !== String(f[k] == null ? '' : f[k]); });
        det.history = (det.history || []).concat([hist('edited', changes.length ? 'Changed: ' + changes.join(', ') : 'Details updated')]);
        var v = {wo_detail: det}; Object.keys(f).forEach(function (k) { v['wo_' + k] = f[k]; });
        guardedSave(w, 'wo_', v).then(function () { state.panel = {kind: 'wo', arg: w.id}; return reload(); }, fail);
      } else {
        det.history = [hist('created', 'Raised manually', null, S.SCH)];
        var fields = {title: f.title, type: f.type, priority: f.priority, status: S.SCH, source: 'manual', plan_id: '', alarm_id: '', equipment_id: ee.id,
                      equipment_name: ee.name, due_date: f.due_date, due_rh: f.due_rh, interval_rh: null, assignee: f.assignee, created_ts: Date.now(),
                      completed_ts: null, closed_ts: null, overdue_alerted: false, detail: det};
        createWo(fields).then(function (r) { state.panel = {kind: 'wo', arg: r.id}; return reload(); }, fail);
      }
    });
  }
  function createWo(fields) {
    var year = String(new Date().getFullYear());
    return createNumbered(WO_T, 'WO-' + year + '-', 5, fields.title).then(function (asset) {
      var v = {wo_rev: 1}; Object.keys(fields).forEach(function (k) { v['wo_' + k] = fields[k]; });
      return saveAttrs('ASSET', asset.id.id, v).then(function () { return relate(fields.equipment_id, asset.id.id); }).then(function () { return {id: asset.id.id, number: asset.name}; });
    });
  }

  function transition(w, to, action, note, extra) {
    if (!allowed(w, to)) return Promise.reject({message: 'A work order in status ' + w.status + ' cannot be moved to ' + to});
    var d = JSON.parse(JSON.stringify(w.detail || {}));
    d.history = (d.history || []).concat([hist(action, note, w.status, to)]);
    var v = {wo_status: to, wo_detail: d};
    if (extra) extra(v, d);
    return guardedSave(w, 'wo_', v);
  }
  function reasonForm(arg) {
    var w = byId(wos, arg.id);
    if (!w) return false;
    var label = {hold: 'Reason for hold (waiting for spares, shutdown permit, vendor…)', cancel: 'Reason for cancelling', reject: 'What must be reworked'}[arg.kind];
    slot().innerHTML = '<div class="mp-panel"><h4>' + esc(w.number) + ' &middot; ' + esc({hold: 'Put on hold', cancel: 'Cancel work order', reject: 'Reject and send back for rework'}[arg.kind]) + '</h4>' +
      (arg.kind === 'cancel' && w.plan_id ? '<div class="mp-hl">This occurrence of the plan is skipped; the plan moves to its next interval.</div>' : '') +
      '<div class="mp-grid" style="margin-top:8px"><label class="wide">' + esc(label) + ' <span class="req">*</span><textarea class="r-txt" rows="2" maxlength="500"></textarea></label></div>' +
      '<div class="mp-row"><button class="mp-btn ' + (arg.kind === 'cancel' ? 'danger' : 'warn') + '" data-act="savereason">Confirm</button><button class="mp-btn light" data-act="back">Back</button><span class="mp-status"></span></div></div>';
    slot().querySelector('[data-act="savereason"]').addEventListener('click', function () {
      var txt = slot().querySelector('.r-txt').value.trim();
      if (!txt) { pstatus('Enter the reason.', 'bad'); return; }
      busy(true);
      var pr;
      if (arg.kind === 'hold') pr = transition(w, S.HLD, 'put on hold', txt, function (v, d) { d.hold_reason = txt; });
      else if (arg.kind === 'reject') pr = transition(w, S.PRG, 'rejected by verifier', txt, function (v, d) { d.rework = (d.rework || 0) + 1; v.wo_completed_ts = null; });
      else {
        pr = transition(w, S.CAN, 'cancelled', txt, function (v, d) { d.cancel_reason = txt; v.wo_closed_ts = Date.now(); }).then(function () {
          var p = byId(plans, w.plan_id);
          if (!p) return null;
          var upd = planAfterSkip(p, w), pd = JSON.parse(JSON.stringify(p.detail || {}));
          pd.history = (pd.history || []).concat([hist('occurrence skipped', w.number + ' cancelled: ' + txt)]);
          upd.plan_detail = pd;
          return guardedSave(p, 'plan_', upd);
        });
      }
      pr.then(function () { state.panel = {kind: 'wo', arg: w.id}; return reload(); }, fail);
    });
  }

  function completeForm(id) {
    var w = byId(wos, id);
    if (!w) return false;
    var d = w.detail || {}, e = eq(w.equipment_id), dg = isDg(e);
    var corrective = w.type === 'Corrective' || w.type === 'Condition-based';
    var svc = dg && w.type === 'Preventive';
    var plan = byId(plans, w.plan_id);
    slot().innerHTML = '<div class="mp-panel"><h4>Record work done &middot; ' + esc(w.number) + ' &middot; ' + esc(w.title) + '</h4>' +
      ((d.docs || []).length ? '<div class="sub" style="margin-bottom:6px">Documents: ' + docLinks(d.docs) + '</div>' : '') +
      ((d.checklist || []).length ? '<h5>Checklist <span class="req" style="color:#c62828">*</span> (tick each step done; note readings / findings)</h5><div class="mp-checks c-cl" style="max-height:none">' + d.checklist.map(function (s, i) {
        return '<div class="mp-cl-row"><input type="checkbox" data-i="' + i + '"><span>' + esc(s) + '</span><input class="c-note" data-i="' + i + '" placeholder="Reading / remark"></div>';
      }).join('') + '</div>' : '') +
      '<div class="mp-grid" style="margin-top:10px">' +
      '<label>Work finished at <span class="req">*</span><input type="datetime-local" class="c-when" value="' + localNow() + '" max="' + localNow() + '"></label>' +
      '<label>Technician / vendor <span class="req">*</span><input class="c-tech" maxlength="80" value="' + esc(w.assignee || '') + '"></label>' +
      '<label>Run hours at work' + (svc || (plan && plan.strategy === 'meter') ? ' <span class="req">*</span>' : '') + '<input type="number" class="c-rh" step="0.1" min="0"' + (dg ? ' value="' + esc(e.runHours == null ? '' : e.runHours) + '"' : ' disabled placeholder="DG only"') + '></label>' +
      '<label>Labour hours <span class="req">*</span><input type="number" class="c-lab" step="0.25" min="0" value="' + esc(d.est_hours || '') + '"></label>' +
      '<label>Equipment downtime (h)<input type="number" class="c-down" step="0.25" min="0" value="0"></label>' +
      '<label class="wide">Work done <span class="req">*</span><textarea class="c-desc" rows="3" maxlength="1500" placeholder="What was done, findings, measurements"></textarea></label>' +
      (corrective ? '<label>Failure (problem) <span class="req">*</span><select class="c-fp"><option value=""></option>' + opts(F_PROBLEM) + '</select></label>' +
        '<label>Cause <span class="req">*</span><select class="c-fc"><option value=""></option>' + opts(F_CAUSE) + '</select></label>' +
        '<label>Action taken <span class="req">*</span><select class="c-fa"><option value=""></option>' + opts(F_ACTION) + '</select></label>' : '') +
      '<div class="mp-field wide">Spare parts / services<table class="mp-parts"><thead><tr><th>Item</th><th style="width:90px">Qty</th><th style="width:120px">Rate (INR)</th></tr></thead><tbody class="c-parts">' +
      [0, 1, 2].map(function () { return '<tr><td><input class="p-n" maxlength="100"></td><td><input class="p-q" type="number" min="0" step="0.01"></td><td><input class="p-r" type="number" min="0" step="0.01"></td></tr>'; }).join('') +
      '</tbody></table><button class="mp-btn small light" data-act="addpart" style="align-self:flex-start;margin-top:4px">+ row</button></div>' +
      '<label class="wide">Job card / photos / test reports<input type="file" class="c-files" multiple></label>' +
      (svc ? '<label class="wide mp-hl" style="flex-direction:row;align-items:center;gap:8px;text-transform:none;font-size:13px;font-weight:500;letter-spacing:0"><input type="checkbox" class="c-reset" checked> ' +
        'Scheduled DG service done: restart the Predictive Maintenance service countdown from these run hours</label>' : '') +
      '</div><div class="sub" style="margin-top:8px">' + (plan ? 'Plan ' + esc(plan.number) + ' moves to its next due point (' + (plan.strategy === 'meter' ? plan.interval_rh + ' run-h' : plan.interval_days + ' days') + ' after this work).' : '') +
      ' After saving, another user verifies and closes the work order.</div>' +
      '<div class="mp-row"><button class="mp-btn ok" data-act="savedone">Save as completed</button><button class="mp-btn light" data-act="back">Back</button><span class="mp-status"></span></div></div>';
    var p = slot();
    p.querySelector('[data-act="addpart"]').addEventListener('click', function () {
      var tr = document.createElement('tr');
      tr.innerHTML = '<td><input class="p-n" maxlength="100"></td><td><input class="p-q" type="number" min="0" step="0.01"></td><td><input class="p-r" type="number" min="0" step="0.01"></td>';
      p.querySelector('.c-parts').appendChild(tr);
    });
    p.querySelector('[data-act="savedone"]').addEventListener('click', function () {
      var ts = new Date(p.querySelector('.c-when').value).getTime();
      var tech = p.querySelector('.c-tech').value.trim(), desc = p.querySelector('.c-desc').value.trim();
      var rh = dg ? num(p.querySelector('.c-rh').value) : null, lab = num(p.querySelector('.c-lab').value), down = num(p.querySelector('.c-down').value) || 0;
      var reset = !!(p.querySelector('.c-reset') && p.querySelector('.c-reset').checked);
      var results = [].slice.call(p.querySelectorAll('.c-cl input[type=checkbox]')).map(function (c) {
        var i = Number(c.getAttribute('data-i'));
        return {item: d.checklist[i], done: c.checked, note: (p.querySelector('.c-note[data-i="' + i + '"]').value || '').trim()};
      });
      var errs = [];
      if (!isFinite(ts) || ts > Date.now() + 60000) errs.push('a finish time that is not in the future');
      if (!tech) errs.push('the technician');
      if (!desc) errs.push('the work done');
      if (lab == null) errs.push('labour hours');
      if ((reset || (plan && plan.strategy === 'meter')) && rh == null) errs.push('the run hours at the time of work');
      var undone = results.filter(function (r) { return !r.done && !r.note; });
      if (undone.length) errs.push('a remark for each checklist step not done (' + undone.length + ')');
      var fail3 = corrective ? {problem: p.querySelector('.c-fp').value, cause: p.querySelector('.c-fc').value, action: p.querySelector('.c-fa').value} : null;
      if (fail3 && !(fail3.problem && fail3.cause && fail3.action)) errs.push('failure problem, cause and action');
      if (errs.length) { pstatus('Please enter ' + errs.join(', ') + '.', 'bad'); return; }
      var parts = [].slice.call(p.querySelectorAll('.c-parts tr')).map(function (tr) {
        return {name: tr.querySelector('.p-n').value.trim(), qty: num(tr.querySelector('.p-q').value) || 1, rate: num(tr.querySelector('.p-r').value) || 0};
      }).filter(function (x) { return x.name; });
      var cost = Math.round(parts.reduce(function (s, x) { return s + x.qty * x.rate; }, 0) * 100) / 100;
      var files = [].slice.call(p.querySelector('.c-files').files || []);
      busy(true); pstatus(files.length ? 'Uploading ' + files.length + ' file(s)…' : 'Saving…');
      files.reduce(function (pr, f) {
        return pr.then(function (acc) {
          return uploadFile(f, w.number + ' - ' + f.name).then(function (meta) {
            meta.category = /\.(jpe?g|png|gif|webp|heic)$/i.test(f.name) ? 'Photo' : 'Service report'; meta.wo = w.number; acc.push(meta); return acc;
          });
        });
      }, Promise.resolve([])).then(function (att) {
        var rec = {type: w.type, description: desc, technician: tech, run_hours: rh, parts: parts.map(function (x) { return x.name + ' x' + x.qty; }).join(', ') || null,
                   cost: cost || null, next_due: null, service_reset: reset, logged_by: me.name, logged_at: Date.now(), wo_number: w.number, job_title: w.title,
                   checklist: results, labour_hours: lab, downtime_hours: down, failure: fail3, attachments: att.map(function (a) { return {id: a.id, title: a.title, file: a.file}; })};
        var planUpd = plan ? planAfterCompletion(plan, ymd(new Date(ts)), rh) : null;
        if (planUpd) rec.next_due = planUpd.plan_next_due_date || (planUpd.plan_next_due_rh != null ? planUpd.plan_next_due_rh + ' run-h' : null);
        var steps = att.length ? appendDocs(w.equipment_id, att) : Promise.resolve();
        return steps.then(function () {
          return transition(w, S.CMP, 'completed', desc.slice(0, 200), function (v, dd) {
            v.wo_completed_ts = ts;
            dd.results = results; dd.work_done = desc; dd.technician = tech; dd.done_rh = rh; dd.labour_hours = lab; dd.downtime_hours = down;
            dd.parts = parts; dd.cost_total = cost; dd.failure = fail3; dd.attachments = rec.attachments; dd.service_reset = reset;
            dd.completed_by = {user: me.user, name: me.name, ts: Date.now()};
          });
        }).then(function () {
          return req(http.post('/api/plugins/telemetry/DEVICE/' + w.equipment_id + '/timeseries/ANY', [{ts: ts, values: {maintenance_record: JSON.stringify(rec)}}]));
        }).then(function () {
          if (!plan) return null;
          var pd = JSON.parse(JSON.stringify(plan.detail || {}));
          pd.last_done_ts = ts; pd.last_wo = w.number;
          pd.history = (pd.history || []).concat([hist('occurrence completed', w.number)]);
          planUpd.plan_detail = pd;
          return guardedSave(plan, 'plan_', planUpd);
        }).then(function () {
          if (!reset) return null;
          return readAttrs('DEVICE', w.equipment_id, ['pm_config']).then(function (a) {
            var cfg = a.pm_config && typeof a.pm_config === 'object' && !Array.isArray(a.pm_config) ? a.pm_config : {};
            cfg.last_service_run_hours = rh;
            if (plan && plan.strategy === 'meter' && Number(plan.interval_rh) > 0) cfg.service_interval_h = Number(plan.interval_rh);
            return saveAttrs('DEVICE', w.equipment_id, {pm_config: cfg});
          });
        });
      }).then(function () { state.panel = {kind: 'wo', arg: w.id}; return reload(); }, fail);
    });
  }

  function planForm(id) {
    var p = id ? byId(plans, id) : null, d = (p && p.detail) || {};
    var e0 = p ? p.equipment_id : (state.equip || (equipment[0] && equipment[0].id));
    slot().innerHTML = '<div class="mp-panel"><h4>' + (p ? 'Edit plan ' + esc(p.number) : 'New maintenance plan') + '</h4><div class="mp-grid">' +
      '<label>Equipment <span class="req">*</span>' + equipSelect('f-eq', e0, false) + '</label>' +
      '<label class="wide">Title <span class="req">*</span><input class="f-title" maxlength="120" value="' + esc(p ? p.title : '') + '" placeholder="e.g. DG 250 h service - engine oil, oil and fuel filters"></label>' +
      '<label>Type<select class="f-type">' + opts(['Preventive', 'Inspection', 'Statutory', 'Calibration'], p ? p.type : 'Preventive') + '</select></label>' +
      '<label>Priority of raised WOs<select class="f-pri">' + opts(['P1', 'P2', 'P3', 'P4'], p ? p.priority : 'P3', PRI) + '</select></label>' +
      '<label>Strategy<select class="f-str"><option value="time">Time-based (every N days)</option><option value="meter">Run-hours based (DG)</option></select></label>' +
      '<label class="w-days">Interval (days) <span class="req">*</span><input type="number" class="f-days" min="1" step="1" value="' + esc(p && p.interval_days ? p.interval_days : 30) + '"></label>' +
      '<label class="w-days">Next due date <span class="req">*</span><input type="date" class="f-date" value="' + esc(p ? (p.next_due_date || '') : addDays(today(), 30)) + '"></label>' +
      '<label class="w-days">Raise WO days ahead<input type="number" class="f-lead" min="0" max="60" step="1" value="' + esc(p && p.lead_days != null ? p.lead_days : 7) + '"></label>' +
      '<label class="w-rh">Interval (run-hours) <span class="req">*</span><input type="number" class="f-irh" min="1" step="1" value="' + esc(p && p.interval_rh ? p.interval_rh : 250) + '"></label>' +
      '<label class="w-rh">Next due at run-hours <span class="req">*</span><input type="number" class="f-nrh" min="0" step="0.1" value="' + esc(p && p.next_due_rh != null ? p.next_due_rh : '') + '"></label>' +
      '<label>Assigned to<input class="f-asg" maxlength="80" value="' + esc(d.assignee || '') + '" placeholder="Technician / vendor / AMC"></label>' +
      '<label>Estimated hours<input type="number" class="f-est" min="0" step="0.5" value="' + esc(d.est_hours || '') + '"></label>' +
      '<label class="wide">Checklist / task list (one step per line)<textarea class="f-cl" rows="4" placeholder="Drain and refill engine oil (15W-40, 18 L)&#10;Replace oil filter&#10;Check coolant level and belt tension">' + esc((d.checklist || []).join('\n')) + '</textarea></label>' +
      '<div class="mp-field wide">Technical documents for this job<div class="mp-checks f-docs"></div></div>' +
      '<label class="wide">Safety / notes<input class="f-notes" maxlength="300" value="' + esc(d.notes || '') + '" placeholder="e.g. Isolate DG and lock out the start circuit before work"></label>' +
      '</div><div class="mp-row"><button class="mp-btn" data-act="saveplan">' + (p ? 'Save changes' : 'Create plan') + '</button><button class="mp-btn light" data-act="close">Cancel</button><span class="mp-status"></span></div></div>';
    var s = slot();
    s.querySelector('.f-str').value = p ? p.strategy : 'time';
    if (p) s.querySelector('.f-eq').disabled = true;
    function sync() {
      var ee = eq(s.querySelector('.f-eq').value), str = s.querySelector('.f-str');
      str.querySelector('option[value="meter"]').disabled = !isDg(ee);
      if (!isDg(ee)) str.value = 'time';
      var meter = str.value === 'meter';
      [].slice.call(s.querySelectorAll('.w-days')).forEach(function (x) { x.style.display = meter ? 'none' : ''; });
      [].slice.call(s.querySelectorAll('.w-rh')).forEach(function (x) { x.style.display = meter ? '' : 'none'; });
      if (meter && !s.querySelector('.f-nrh').value && ee && ee.runHours != null) s.querySelector('.f-nrh').value = r1(ee.runHours + (Number(s.querySelector('.f-irh').value) || 250));
      var av = docsFor(ee && ee.id);
      s.querySelector('.f-docs').innerHTML = av.length ? av.map(function (x) {
        return '<label><input type="checkbox" value="' + esc(x.d.id) + '"' + ((d.docs || []).indexOf(x.d.id) >= 0 ? ' checked' : '') + '> ' + esc(x.d.title) + ' <span class="sub">(' + esc(x.d.category) + ', ' + esc(x.o) + ')</span></label>';
      }).join('') : '<span class="sub">No documents for this equipment yet - upload them in "Technical documents".</span>';
    }
    s.querySelector('.f-eq').addEventListener('change', sync);
    s.querySelector('.f-str').addEventListener('change', sync);
    sync();
    s.querySelector('[data-act="saveplan"]').addEventListener('click', function () {
      var ee = eq(s.querySelector('.f-eq').value), title = s.querySelector('.f-title').value.trim(), meter = s.querySelector('.f-str').value === 'meter';
      var days = num(s.querySelector('.f-days').value), date = s.querySelector('.f-date').value, irh = num(s.querySelector('.f-irh').value), nrh = num(s.querySelector('.f-nrh').value);
      if (!ee || !title) { pstatus('Equipment and title are required.', 'bad'); return; }
      if (meter ? !(irh > 0 && nrh != null) : !(days > 0 && date)) { pstatus(meter ? 'Enter the run-hour interval and the next due run-hours.' : 'Enter the interval in days and the next due date.', 'bad'); return; }
      var det = JSON.parse(JSON.stringify(d));
      det.assignee = s.querySelector('.f-asg').value.trim(); det.est_hours = num(s.querySelector('.f-est').value);
      det.checklist = s.querySelector('.f-cl').value.split('\n').map(function (x) { return x.trim(); }).filter(Boolean);
      det.docs = [].slice.call(s.querySelectorAll('.f-docs input:checked')).map(function (c) { return c.value; });
      det.notes = s.querySelector('.f-notes').value.trim();
      det.history = (det.history || []).concat([hist(p ? 'edited' : 'created', '')]);
      var v = {plan_title: title, plan_type: s.querySelector('.f-type').value, plan_priority: s.querySelector('.f-pri').value, plan_strategy: meter ? 'meter' : 'time',
               plan_interval_days: meter ? null : days, plan_interval_rh: meter ? irh : null, plan_lead_days: meter ? null : (num(s.querySelector('.f-lead').value) || 0),
               plan_next_due_date: meter ? null : date, plan_next_due_rh: meter ? nrh : null, plan_equipment_id: ee.id, plan_equipment_name: ee.name, plan_detail: det};
      busy(true); pstatus('Saving…');
      var pr;
      if (p) pr = guardedSave(p, 'plan_', v);
      else {
        v.plan_active = true; v.plan_rev = 1;
        pr = createNumbered(PLAN_T, 'PL-', 4, title).then(function (a) { return saveAttrs('ASSET', a.id.id, v).then(function () { return relate(ee.id, a.id.id); }); });
      }
      pr.then(function () { return done(p ? 'Plan saved.' : 'Plan created. Its work orders are raised automatically when due.'); }, fail);
    });
  }
  function raiseNow(p) {
    var d = p.detail || {}, meter = p.strategy === 'meter';
    var fields = {title: p.title, type: p.type || 'Preventive', priority: p.priority || 'P3', status: S.SCH, source: 'plan', plan_id: p.id, alarm_id: '',
                  equipment_id: p.equipment_id, equipment_name: p.equipment_name, due_date: meter ? '' : p.next_due_date, due_rh: meter ? p.next_due_rh : null,
                  interval_rh: meter ? p.interval_rh : null, assignee: d.assignee || '', created_ts: Date.now(), completed_ts: null, closed_ts: null, overdue_alerted: false,
                  detail: {description: d.notes || '', checklist: d.checklist || [], docs: d.docs || [], est_hours: d.est_hours, plan_number: p.number,
                           history: [hist('created', 'Raised from plan ' + p.number + ' ahead of schedule', null, S.SCH)]}};
    return createWo(fields);
  }

  function uploadForm() {
    slot().innerHTML = '<div class="mp-panel"><h4>Upload technical document</h4><div class="mp-grid">' +
      '<label>Equipment' + equipSelect('u-eq', state.equip || 'general', false, true) + '</label>' +
      '<label class="wide">Title <span class="req">*</span><input class="u-title" maxlength="120" placeholder="e.g. easYgen-3000 operator manual"></label>' +
      '<label>Category<select class="u-cat">' + opts(CATS) + '</select></label>' +
      '<label>Document no.<input class="u-no" maxlength="40" placeholder="Optional"></label>' +
      '<label>Revision<input class="u-rev" maxlength="20" placeholder="e.g. A, 2.1"></label>' +
      '<label>Valid until<input type="date" class="u-exp"><span class="sub">certificates, AMC, licences</span></label>' +
      '<label class="wide">File (max 50 MB) <span class="req">*</span><input type="file" class="u-file"></label>' +
      '</div><div class="mp-row"><button class="mp-btn" data-act="saveupload">Upload</button><button class="mp-btn light" data-act="close">Cancel</button><span class="mp-status"></span></div></div>';
    var p = slot();
    p.querySelector('[data-act="saveupload"]').addEventListener('click', function () {
      var file = p.querySelector('.u-file').files[0], target = p.querySelector('.u-eq').value, title = p.querySelector('.u-title').value.trim();
      if (!file || !title) { pstatus('Choose a file and enter a title.', 'bad'); return; }
      busy(true); pstatus('Uploading…');
      uploadFile(file, title).then(function (meta) {
        meta.category = p.querySelector('.u-cat').value; meta.doc_no = p.querySelector('.u-no').value.trim() || null;
        meta.revision = p.querySelector('.u-rev').value.trim() || null; meta.expiry = p.querySelector('.u-exp').value || null;
        return appendDocs(target, [meta]);
      }).then(function () { return done('Document uploaded.'); }, fail);
    });
  }

  // ---------------------------------------------------------------- print job card
  function printWo(w) {
    var d = w.detail || {};
    var cl = (d.checklist || []).map(function (s, i) {
      var r = (d.results || [])[i];
      return '<tr><td style="width:28px;text-align:center">' + (r && r.done ? '&#9745;' : '&#9744;') + '</td><td>' + esc(s) + '</td><td style="width:35%">' + esc(r && r.note || '') + '</td></tr>';
    }).join('');
    var html = '<!doctype html><html><head><meta charset="utf-8"><title>' + esc(w.number) + '</title><style>body{font:12px Arial,sans-serif;margin:24px;color:#111}' +
      'h1{font-size:18px;margin:0}table{width:100%;border-collapse:collapse;margin-top:8px}td,th{border:1px solid #999;padding:5px;text-align:left;vertical-align:top}' +
      'th{background:#eee;width:22%}.h{display:flex;justify-content:space-between;border-bottom:2px solid #000;padding-bottom:6px}.sig td{height:46px}</style></head><body>' +
      '<div class="h"><div><h1>Maintenance Work Order</h1>' + esc(w.number) + '</div><div style="text-align:right">Printed ' + fmtTs(Date.now()) + '<br>' + esc(me.name) + '</div></div>' +
      '<table><tr><th>Work</th><td colspan="3"><b>' + esc(w.title) + '</b></td></tr><tr><th>Equipment</th><td>' + esc(w.equipment_name) + '</td><th>Type / priority</th><td>' + esc(w.type) + ' / ' + esc(PRI[w.priority] || w.priority) + '</td></tr>' +
      '<tr><th>Status</th><td>' + esc(w.status) + '</td><th>Due</th><td>' + esc(dueText(w)) + '</td></tr><tr><th>Assigned to</th><td>' + esc(w.assignee || '') + '</td><th>Estimated hours</th><td>' + esc(d.est_hours || '') + '</td></tr>' +
      '<tr><th>Description</th><td colspan="3">' + esc(d.description || '') + '</td></tr>' +
      '<tr><th>Documents</th><td colspan="3">' + (d.docs || []).map(function (id) { var x = findDoc(id); return x ? esc(x.d.title) + (x.d.revision ? ' rev ' + esc(x.d.revision) : '') : ''; }).filter(Boolean).join('; ') + '</td></tr></table>' +
      (cl ? '<table><tr><th colspan="3">Checklist</th></tr>' + cl + '</table>' : '') +
      '<table><tr><th>Work done</th><td colspan="3" style="height:60px">' + esc(d.work_done || '') + '</td></tr><tr><th>Run hours</th><td>' + esc(d.done_rh == null ? '' : d.done_rh) + '</td><th>Labour / downtime h</th><td>' + esc(d.labour_hours == null ? '' : d.labour_hours) + ' / ' + esc(d.downtime_hours == null ? '' : d.downtime_hours) + '</td></tr>' +
      '<tr><th>Parts</th><td colspan="3">' + (d.parts || []).map(function (x) { return esc(x.name) + ' x ' + esc(x.qty); }).join('; ') + '</td></tr></table>' +
      '<table class="sig"><tr><th>Technician (name, sign, date)</th><td>' + esc(d.technician || '') + '</td></tr><tr><th>Verified by (name, sign, date)</th><td>' + esc((d.verified_by || {}).name || '') + '</td></tr></table>' +
      '<script>window.onload=function(){window.print()}<\/script></body></html>';
    var win = window.open('', '_blank');
    if (!win) { window.alert('Allow pop-ups to print the job card.'); return; }
    win.document.write(html); win.document.close();
  }

  // ---------------------------------------------------------------- events (bound once)
  root.addEventListener('click', function (ev) {
    var t = ev.target.closest('[data-act],[data-doc],[data-tab],[data-filter]');
    if (!t || !root.contains(t) || t.disabled) return;
    if (t.getAttribute('data-tab')) { state.tab = t.getAttribute('data-tab'); state.panel = null; state.equip = state.tab === 'kpi' ? '' : state.equip; render(); return; }
    if (t.getAttribute('data-filter')) { state.woFilter = t.getAttribute('data-filter'); render(); return; }
    var act = t.getAttribute('data-act');
    if (!act && t.getAttribute('data-doc')) { download(t.getAttribute('data-doc')); return; }
    var cur = state.panel && state.panel.kind === 'wo' ? byId(wos, state.panel.arg) : null;
    if (act === 'close') closePanel();
    else if (act === 'back') { if (state.panel && state.panel.arg) { var wid = state.panel.arg.id || state.panel.arg; openPanel('wo', wid); } else closePanel(); }
    else if (act === 'viewwo') openPanel('wo', t.getAttribute('data-id'));
    else if (act === 'newwo') openPanel('newwo', null);
    else if (act === 'newplan') openPanel('plan', null);
    else if (act === 'editplan') openPanel('plan', t.getAttribute('data-id'));
    else if (act === 'upload') openPanel('upload');
    else if (cur && act === 'editwo') openPanel('editwo', {id: cur.id});
    else if (cur && act === 'complete') openPanel('complete', cur.id);
    else if (cur && (act === 'hold' || act === 'cancel' || act === 'reject')) openPanel('reason', {id: cur.id, kind: act});
    else if (cur && act === 'print') printWo(cur);
    else if (cur && act === 'start') {
      busy(true);
      transition(cur, S.PRG, cur.status === S.HLD ? 'resumed' : 'started', '', function (v, d) { d.hold_reason = null; if (!d.started_ts) d.started_ts = Date.now(); })
        .then(function () { return reload(); }, fail);
    } else if (cur && act === 'verify') {
      if (((cur.detail || {}).completed_by || {}).user === me.user) { pstatus('Another user must verify your work.', 'bad'); return; }
      busy(true);
      transition(cur, S.CLS, 'verified and closed', '', function (v, d) { v.wo_closed_ts = Date.now(); d.verified_by = {user: me.user, name: me.name, ts: Date.now()}; })
        .then(function () { return reload(); }, fail);
    } else if (act === 'toggleplan') {
      var p = byId(plans, t.getAttribute('data-id'));
      var pd = JSON.parse(JSON.stringify(p.detail || {}));
      pd.history = (pd.history || []).concat([hist(p.active === false ? 'resumed' : 'paused', '')]);
      guardedSave(p, 'plan_', {plan_active: p.active === false, plan_detail: pd}).then(reload, function (e) { window.alert(errText(e)); });
    } else if (act === 'raisenow') {
      var pl = byId(plans, t.getAttribute('data-id'));
      if (wos.some(function (w) { return w.plan_id === pl.id && ACTIVE.indexOf(w.status) >= 0; })) { window.alert('This plan already has an active work order.'); return; }
      t.disabled = true;
      raiseNow(pl).then(function (r) { state.tab = 'wo'; state.panel = {kind: 'wo', arg: r.id}; return reload(); }, function (e) { t.disabled = false; window.alert('Not created: ' + errText(e)); });
    } else if (act === 'deldoc') {
      var owner = t.getAttribute('data-o'), did = t.getAttribute('data-d'), x = findDoc(did);
      var users = plans.filter(function (pp) { return ((pp.detail || {}).docs || []).indexOf(did) >= 0; }).map(function (pp) { return pp.number; });
      if (!x || !window.confirm('Delete "' + x.d.title + '"?' + (users.length ? ' It is linked to ' + users.join(', ') + '.' : '') + ' Work orders keep a reference to its title only.')) return;
      var type = owner === 'general' ? 'ASSET' : 'DEVICE', oid = owner === 'general' ? general.id : owner;
      req(http.delete('/api/resource/' + did)).catch(function () { return null; }).then(function () {
        return readAttrs(type, oid, ['maint_docs']).then(function (a) { return saveAttrs(type, oid, {maint_docs: (a.maint_docs || []).filter(function (dd) { return dd.id !== did; })}); });
      }).then(function () {
        return Promise.all(plans.filter(function (pp) { return ((pp.detail || {}).docs || []).indexOf(did) >= 0; }).map(function (pp) {
          var pd2 = JSON.parse(JSON.stringify(pp.detail)); pd2.docs = pd2.docs.filter(function (z) { return z !== did; });
          return guardedSave(pp, 'plan_', {plan_detail: pd2});
        }));
      }).then(reload, function (e) { window.alert('Delete failed: ' + errText(e)); });
    }
  });

  self._mpDataUpdated = function () {
    var before = equipment.map(function (e) { return e.runHours; }).join(',');
    updateRunHours();
    if (equipment.map(function (e) { return e.runHours; }).join(',') !== before && !state.panel) render();
  };
  self._mpTimer = setInterval(function () { if (!state.panel) reload(); }, 120000);   // pick up scheduler / other users' changes
  root.innerHTML = '<div class="mp"><div class="mp-empty">Loading maintenance data…</div></div>';
  loadEquipment().then(function () { updateRunHours(); return loadData(); }).then(render);
};

self.onDataUpdated = function () { if (self._mpDataUpdated) self._mpDataUpdated(); };
self.typeParameters = function () { return {dataKeysOptional: true, singleEntity: false, hasDataPageLink: false}; };
self.onDestroy = function () { if (self._mpTimer) clearInterval(self._mpTimer); };
