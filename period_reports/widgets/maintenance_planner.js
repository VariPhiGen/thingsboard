// ThingsBoard latest-values widget "Maintenance Management" (CMMS): work orders, maintenance plans, technical documents,
// KPIs and the configuration of maintenance and predictive maintenance.
//
// No business value is defined in this file. Everything comes from ThingsBoard:
//  - asset "Maintenance Settings": cmms_settings (equipment profiles, meter key, priorities and response days, work-order
//    types, due windows, failure codes, document categories, condition-based rules, alerts, KPI periods, time zone) and
//    pm_templates (predictive-maintenance template for new equipment). Both are edited in the Settings tab.
//  - equipment = devices of the configured profiles; an equipment is meter-based (e.g. run hours) when it reports the
//    configured meter key; the predictive-maintenance service countdown can be restarted when it has a pm_config.
//  - plans / work orders: assets "Maintenance Plan" / "Work Order" (numbers PL-0001 / WO-YYYY-00001 are asset names,
//    unique in ThingsBoard), related to the equipment; fields are server attributes plan_* / wo_*, *_rev guards
//    concurrent edits; documents are GENERAL resources listed in maint_docs (equipment or "Maintenance Document Library").
// Lifecycle (the workflow itself): Scheduled -> In Progress <-> On Hold -> Completed -> Closed / Cancelled.
self.onInit = function () {
  var root = self.ctx.$container[0];
  var http = self.ctx.http;
  // data-model identifiers (schema names)
  var PLAN_T = 'Maintenance Plan', WO_T = 'Work Order', LIBRARY = 'Maintenance Document Library', SETTINGS = 'Maintenance Settings', REL = 'Maintenance';
  var S = {SCH: 'Scheduled', PRG: 'In Progress', HLD: 'On Hold', CMP: 'Completed', CLS: 'Closed', CAN: 'Cancelled'};
  var OPEN = [S.SCH, S.PRG, S.HLD], ACTIVE = OPEN.concat([S.CMP]);
  var TRANS = {};
  TRANS[S.SCH] = [S.PRG, S.HLD, S.CAN, S.CMP]; TRANS[S.PRG] = [S.HLD, S.CMP, S.CAN]; TRANS[S.HLD] = [S.PRG, S.CAN];
  TRANS[S.CMP] = [S.CLS, S.PRG]; TRANS[S.CLS] = []; TRANS[S.CAN] = [];
  var SEVERITIES = ['CRITICAL', 'MAJOR', 'MINOR', 'WARNING', 'INDETERMINATE'];   // ThingsBoard alarm severities
  var MAP_FIELDS = ['nominal_v', 'rated_a'];                                       // per-feeder maps in PM limits
  var WO_KEYS = ['wo_title', 'wo_type', 'wo_priority', 'wo_status', 'wo_source', 'wo_plan_id', 'wo_alarm_id', 'wo_equipment_id',
                 'wo_equipment_name', 'wo_due_date', 'wo_due_rh', 'wo_interval_rh', 'wo_assignee', 'wo_created_ts', 'wo_completed_ts',
                 'wo_closed_ts', 'wo_rev', 'wo_overdue_alerted', 'wo_detail'];
  var PLAN_KEYS = ['plan_title', 'plan_type', 'plan_priority', 'plan_strategy', 'plan_interval_days', 'plan_interval_rh', 'plan_lead_days',
                   'plan_next_due_date', 'plan_next_due_rh', 'plan_active', 'plan_equipment_id', 'plan_equipment_name', 'plan_rev', 'plan_detail'];

  var cfg = null, cfgRev = null, settingsId = null, templates = null;
  var equipment = [], plans = [], wos = [], general = {id: null, docs: []};
  var claims = jwt();
  var me = {user: claims.sub || '', name: ((claims.firstName || '') + ' ' + (claims.lastName || '')).trim() || claims.sub || ''};
  var state = {tab: 'wo', woFilter: 'open', equip: '', q: '', kpiDays: null, panel: null, error: '', pmEquip: ''};

  // ---------------------------------------------------------------- helpers
  function jwt() {
    try { return JSON.parse(atob(window.localStorage.getItem('jwt_token').split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))); } catch (e) { return {}; }
  }
  function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function ymd(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  // dates in the configured time zone of the site
  function siteDate(ts) { return new Date(Number(ts) + Number(cfg.timezone_offset_minutes) * 60000 + new Date().getTimezoneOffset() * 60000); }
  function today() { return ymd(siteDate(Date.now())); }
  function tsDay(ts) { return ymd(siteDate(ts)); }
  function parseYmd(s) { var p = String(s || '').split('-'); return p.length === 3 ? new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2])) : null; }
  function addDays(s, n) { var d = parseYmd(s); d.setDate(d.getDate() + n); return ymd(d); }
  function diffDays(a, b) { return Math.round((parseYmd(a) - parseYmd(b)) / 86400000); }
  function fmtDate(s) { var d = parseYmd(s); return d ? d.toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'}) : ''; }
  function fmtTs(ts) {
    if (!ts) return '';
    var d = siteDate(ts);
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
  function hasMeter(e) { return !!e && e.hasMeter; }
  function opts(list, val, blank) {
    return (blank ? '<option value=""></option>' : '') + list.map(function (x) {
      var v = typeof x === 'object' ? x.v : x, l = typeof x === 'object' ? x.l : x;
      return '<option value="' + esc(v) + '"' + (v === val ? ' selected' : '') + '>' + esc(l) + '</option>';
    }).join('');
  }
  function val(v) {
    if (v == null || v === '' || v === 'null') return null;
    if (typeof v !== 'string') return v;
    if (v === 'true' || v === 'false') return v === 'true';
    if (v.charAt(0) === '{' || v.charAt(0) === '[') { try { return JSON.parse(v); } catch (e) { return v; } }
    if (/^-?\d+(\.\d+)?$/.test(v)) return Number(v);
    return v;
  }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function hist(action, note, from, to) { return {ts: Date.now(), user: me.user, name: me.name, action: action, from: from || null, to: to || null, note: note || ''}; }
  function lines(s) { return String(s || '').split('\n').map(function (x) { return x.trim(); }).filter(Boolean); }

  // ---------------------------------------------------------------- settings access (cmms_settings)
  function priorities() { return cfg.priorities || []; }
  function pri(code) { for (var i = 0; i < priorities().length; i++) { if (priorities()[i].code === code) return priorities()[i]; } return null; }
  function priLabel(code) { var p = pri(code); return p ? p.code + ' - ' + p.label + ' (' + p.response_days + ' d)' : code; }
  function priOpts() { return priorities().map(function (p) { return {v: p.code, l: priLabel(p.code)}; }); }
  function type(name) { for (var i = 0; i < cfg.wo_types.length; i++) { if (cfg.wo_types[i].name === name) return cfg.wo_types[i]; } return {}; }
  function typeNames(filter) { return cfg.wo_types.filter(function (t) { return !filter || t[filter]; }).map(function (t) { return t.name; }); }
  function unit() { return cfg.meter.unit; }
  function meterWindow(i) { return Math.max(Number(cfg.meter_due_window.min_units), (Number(i) || 0) * Number(cfg.meter_due_window.pct_of_interval) / 100); }
  function attachCat(fname) { return /\.(jpe?g|png|gif|webp|heic|bmp)$/i.test(fname) ? cfg.attachment_categories.image : cfg.attachment_categories.other; }

  // ---------------------------------------------------------------- ThingsBoard access
  function attrUrl(t, id) { return '/api/plugins/telemetry/' + t + '/' + id; }
  function readAttrs(t, id, keys) {
    return req(http.get(attrUrl(t, id) + '/values/attributes/SERVER_SCOPE?keys=' + keys.join(','))).then(function (l) {
      var o = {}; (l || []).forEach(function (a) { o[a.key] = val(a.value); }); return o;
    });
  }
  function saveAttrs(t, id, obj) {
    var body = {};
    // ThingsBoard rejects the whole request for a null attribute value; "" clears a field (read back as null)
    Object.keys(obj).forEach(function (k) { var v = obj[k]; body[k] = v == null ? '' : (typeof v === 'object' ? JSON.stringify(v) : v); });
    return req(http.post(attrUrl(t, id) + '/attributes/SERVER_SCOPE', body));
  }
  function assetByName(name) { return req(http.get('/api/tenant/assets?assetName=' + encodeURIComponent(name))).then(function (a) { return a && a.id ? a.id.id : null; }, function () { return null; }); }
  function query(t, keys, prefix) {
    function page(n, acc) {
      return req(http.post('/api/entitiesQuery/find', {
        entityFilter: {type: 'assetType', assetTypes: [t], assetNameFilter: prefix || ''},
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
  function createNumbered(t, prefix, width, label) {
    return query(t, [], prefix).then(function (list) {
      var max = 0;
      list.forEach(function (x) { var m = new RegExp('^' + prefix.replace(/[-]/g, '\\-') + '(\\d+)$').exec(x.number || ''); if (m) max = Math.max(max, Number(m[1])); });
      function attempt(n, left) {
        var s = String(n); while (s.length < width) s = '0' + s;
        return req(http.post('/api/asset', {name: prefix + s, type: t, label: String(label).slice(0, 255)})).catch(function (e) {
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
  function guardedSave(rec, prefix, values) {
    return readAttrs('ASSET', rec.id, [prefix + 'rev']).then(function (cur) {
      var r = cur[prefix + 'rev'];
      if (r != null && rec.rev != null && Number(r) !== Number(rec.rev)) throw {message: rec.number + ' was changed by someone else meanwhile. Close this form and open it again.'};
      values[prefix + 'rev'] = Number(r || 0) + 1;
      return saveAttrs('ASSET', rec.id, values);
    });
  }

  // ---------------------------------------------------------------- domain rules (same as cmms/model.py)
  function dueState(w) {
    if (w.status === S.CLS || w.status === S.CAN) return 'closed';
    if (w.status === S.CMP) return 'done';
    if (w.due_rh != null) {
      var e = eq(w.equipment_id), m = e && e.meter;
      if (m == null) return 'unknown';
      var left = w.due_rh - m;
      return left < 0 ? 'overdue' : (left <= meterWindow(w.interval_rh) ? 'due' : 'upcoming');
    }
    if (!w.due_date) return 'unknown';
    var d = diffDays(w.due_date, today());
    return d < 0 ? 'overdue' : (d <= Number(cfg.due_soon_days) ? 'due' : 'upcoming');
  }
  function dueText(w) {
    if (w.due_rh != null) {
      var e = eq(w.equipment_id), m = e && e.meter;
      var b = 'at ' + w.due_rh + ' ' + unit();
      if (m == null || OPEN.indexOf(w.status) < 0) return b;
      var left = r1(w.due_rh - m);
      return b + ' (' + (left < 0 ? r1(-left) + ' over' : left + ' left') + ')';
    }
    if (!w.due_date) return '';
    if (OPEN.indexOf(w.status) < 0) return fmtDate(w.due_date);
    var d = diffDays(w.due_date, today());
    return fmtDate(w.due_date) + ' (' + (d < 0 ? (-d) + ' d over' : d === 0 ? 'today' : 'in ' + d + ' d') + ')';
  }
  function allowed(w, to) { return (TRANS[w.status] || []).indexOf(to) >= 0; }
  function planAfterCompletion(p, doneDate, doneRh) {
    if (p.strategy === 'meter') return {plan_next_due_rh: r1(Number(doneRh) + Number(p.interval_rh))};
    if (!(Number(p.interval_days) > 0)) return {plan_active: false};
    return {plan_next_due_date: addDays(doneDate, Number(p.interval_days))};
  }
  function planAfterSkip(p, w) {
    if (p.strategy === 'meter') return {plan_next_due_rh: r1(Number(w.due_rh != null ? w.due_rh : p.next_due_rh) + Number(p.interval_rh))};
    if (!(Number(p.interval_days) > 0)) return {plan_active: false};
    return {plan_next_due_date: addDays(w.due_date || p.next_due_date, Number(p.interval_days))};
  }
  function docState(d) {
    if (!d.expiry) return null;
    var n = diffDays(d.expiry, today());
    return n < 0 ? {k: 'expired', t: 'Expired ' + fmtDate(d.expiry)} : n <= Number(cfg.doc_expiry_alert_days) ? {k: 'expiring', t: 'Expires ' + fmtDate(d.expiry)} : {k: 'valid', t: 'Valid to ' + fmtDate(d.expiry)};
  }

  // ---------------------------------------------------------------- loading
  function loadSettings() {
    return assetByName(SETTINGS).then(function (id) {
      settingsId = id;
      if (!id) { cfg = null; return null; }
      return readAttrs('ASSET', id, ['cmms_settings', 'cmms_settings_rev', 'pm_templates']).then(function (a) {
        cfg = a.cmms_settings && typeof a.cmms_settings === 'object' ? a.cmms_settings : null;
        cfgRev = a.cmms_settings_rev;
        templates = a.pm_templates && typeof a.pm_templates === 'object' ? a.pm_templates : null;
      });
    });
  }
  function loadEquipment() {
    var found = [];
    return Promise.all((cfg.equipment_profiles || []).map(function (profile) {
      return req(http.get('/api/tenant/devices?pageSize=1000&page=0&type=' + encodeURIComponent(profile))).then(function (r) {
        (r.data || []).forEach(function (d) { found.push({id: d.id.id, name: d.name, type: d.type, meter: null, hasMeter: false, docs: [], pm: null}); });
      }, function () {});
    })).then(function () {
      found.sort(function (a, b) { return a.name.localeCompare(b.name); });
      var prev = {}; equipment.forEach(function (e) { prev[e.id] = e; });
      equipment = found.map(function (e) { return prev[e.id] ? Object.assign(prev[e.id], {name: e.name, type: e.type}) : e; });
    });
  }
  function loadMeters() {
    var k = cfg.meter.key, now = Date.now();
    return Promise.all(equipment.map(function (e) {
      return req(http.get('/api/plugins/telemetry/DEVICE/' + e.id + '/keys/timeseries')).then(function (keys) {
        e.hasMeter = (keys || []).indexOf(k) >= 0;
        if (!e.hasMeter) { e.meter = null; return null; }
        return req(http.get('/api/plugins/telemetry/DEVICE/' + e.id + '/values/timeseries?keys=' + encodeURIComponent(k) + '&startTs=' + (now - 3 * 86400000) +
          '&endTs=' + now + '&limit=200&agg=NONE&orderBy=DESC')).then(function (r) {
          e.meter = null;
          var pts = (r && r[k]) || [];
          for (var i = 0; i < pts.length; i++) {
            var v = Number(pts[i].value);
            if (isFinite(v) && v >= Number(cfg.meter.valid_min) && v < Number(cfg.meter.valid_below)) { e.meter = r1(v); break; }
          }
        });
      }, function () { e.hasMeter = false; });
    }));
  }
  function loadData() {
    var steps = [query(WO_T, WO_KEYS).then(function (l) { wos = l; }), query(PLAN_T, PLAN_KEYS).then(function (l) { plans = l; }), loadMeters()];
    equipment.forEach(function (e) {
      steps.push(readAttrs('DEVICE', e.id, ['maint_docs', 'pm_config']).then(function (a) {
        e.docs = a.maint_docs || [];
        e.pm = a.pm_config && typeof a.pm_config === 'object' ? a.pm_config : null;
      }, function () { e.docs = []; }));
    });
    steps.push(assetByName(LIBRARY).then(function (id) {
      general.id = id;
      return id ? readAttrs('ASSET', id, ['maint_docs']).then(function (a) { general.docs = a.maint_docs || []; }) : null;
    }));
    return Promise.all(steps).then(function () { state.error = ''; }, function (e) { state.error = 'Could not load maintenance data: ' + errText(e); });
  }
  function loadAll() {
    return loadSettings().then(function () {
      if (!cfg) { state.error = 'Maintenance settings are not configured (asset "' + SETTINGS + '", attribute cmms_settings). Run period_reports/deploy_dashboard.py once to create them.'; return null; }
      if (state.kpiDays == null) state.kpiDays = (cfg.alerts.kpi_periods_days || [])[0];
      return loadEquipment().then(loadData);
    });
  }
  function reload() { return loadAll().then(render); }
  function allDocs() {
    var out = general.docs.map(function (d) { return {d: d, owner: 'general', ownerName: 'All equipment'}; });
    equipment.forEach(function (e) { e.docs.forEach(function (d) { out.push({d: d, owner: e.id, ownerName: e.name}); }); });
    return out;
  }
  function findDoc(id) { var l = allDocs(); for (var i = 0; i < l.length; i++) { if (l[i].d.id === id) return l[i]; } return null; }
  function docsFor(eid) { var e = eq(eid); return general.docs.map(function (d) { return {d: d, o: 'All equipment'}; }).concat(((e || {}).docs || []).map(function (d) { return {d: d, o: e.name}; })); }

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
    var max = Number(cfg.max_upload_mb);
    if (file.size > max * 1048576) return Promise.reject({message: file.name + ' is larger than ' + max + ' MB'});
    var fd = new FormData();
    fd.append('file', file, file.name); fd.append('resourceType', 'GENERAL'); fd.append('title', title || file.name);
    return req(http.post('/api/resource/upload', fd)).then(function (r) {
      return {id: r.id.id, title: title || file.name, file: file.name, size: file.size, uploaded_by: me.name, uploaded_at: Date.now()};
    });
  }
  function appendDocs(owner, metas) {
    var t = owner === 'general' ? 'ASSET' : 'DEVICE', id = owner === 'general' ? general.id : owner;
    return readAttrs(t, id, ['maint_docs']).then(function (a) { return saveAttrs(t, id, {maint_docs: (a.maint_docs || []).concat(metas)}); });
  }
  function docLinks(ids) {
    return (ids || []).map(function (id) { var x = findDoc(id); return x ? '<span class="doc" data-doc="' + esc(id) + '">&#128196; ' + esc(x.d.title) + (x.d.revision ? ' (rev ' + esc(x.d.revision) + ')' : '') + '</span>' : ''; }).join('');
  }

  // ---------------------------------------------------------------- rendering
  function counts() {
    var c = {open: 0, overdue: 0, due: 0, progress: 0, hold: 0, verify: 0, closed: 0};
    wos.forEach(function (w) {
      var ds = dueState(w), o = OPEN.indexOf(w.status) >= 0;
      if (o) c.open++;
      if (o && ds === 'overdue') c.overdue++;
      if (o && ds === 'due') c.due++;
      if (w.status === S.PRG) c.progress++;
      if (w.status === S.HLD) c.hold++;
      if (w.status === S.CMP) c.verify++;
      if (w.status === S.CLS || w.status === S.CAN) c.closed++;
    });
    return c;
  }
  function render() {
    if (!cfg) { root.innerHTML = '<div class="mp"><div class="mp-err">' + esc(state.error) + '</div></div>'; return; }
    var c = counts();
    var expiring = allDocs().filter(function (x) { var s = docState(x.d); return s && s.k !== 'valid'; }).length;
    var h = '<div class="mp">' + (state.error ? '<div class="mp-err">' + esc(state.error) + '</div>' : '') +
      '<div class="mp-tabs">' + [['wo', 'Work orders', c.overdue], ['plans', 'Maintenance plans', 0], ['docs', 'Technical documents', expiring], ['kpi', 'KPIs', 0], ['settings', 'Settings', 0]].map(function (t) {
        return '<button class="mp-tab' + (state.tab === t[0] ? ' on' : '') + '" data-tab="' + t[0] + '">' + t[1] + (t[2] ? '<span class="n">' + t[2] + '</span>' : '') + '</button>';
      }).join('') + '</div><div class="mp-panel-slot"></div>';
    if (state.tab === 'wo') h += woView(c);
    else if (state.tab === 'plans') h += plansView();
    else if (state.tab === 'docs') h += docsView();
    else if (state.tab === 'kpi') h += kpiView();
    else h += settingsView();
    root.innerHTML = h + '</div>';
    var eqf = root.querySelector('.mp-eqf');
    if (eqf) eqf.addEventListener('change', function () { state.equip = eqf.value; render(); });
    var qf = root.querySelector('.mp-q');
    if (qf) qf.addEventListener('change', function () { state.q = qf.value; render(); });
    var kd = root.querySelector('.mp-kd');
    if (kd) kd.addEventListener('change', function () { state.kpiDays = Number(kd.value); render(); });
    if (state.tab === 'settings') bindSettings();
    if (state.panel) openPanel(state.panel.kind, state.panel.arg, true);
  }
  function equipSelect(cls, v, withAll, withGeneral, blank) {
    var o = (blank ? '<option value=""></option>' : '') + (withAll ? '<option value="">All equipment</option>' : '') +
      (withGeneral && general.id ? '<option value="general"' + (v === 'general' ? ' selected' : '') + '>All equipment (general document)</option>' : '');
    equipment.forEach(function (e) { o += '<option value="' + e.id + '"' + (v === e.id ? ' selected' : '') + '>' + esc(e.name) + '</option>'; });
    return '<select class="' + cls + '">' + o + '</select>';
  }
  function statusCls(s) { return {'In Progress': 's-progress', 'On Hold': 's-hold', Completed: 's-completed', Closed: 's-closed', Cancelled: 's-cancelled'}[s] || ''; }
  function woView(c) {
    var chips = [['open', 'Open', c.open, ''], ['overdue', 'Overdue', c.overdue, 'red'], ['due', 'Due within ' + cfg.due_soon_days + ' days', c.due, 'amber'], ['progress', 'In progress', c.progress, ''],
                 ['hold', 'On hold', c.hold, ''], ['verify', 'Awaiting verification', c.verify, 'amber'], ['closed', 'Closed / cancelled', c.closed, ''], ['all', 'All', wos.length, '']];
    var h = '<div class="mp-top">' + chips.map(function (x) {
      return '<span class="mp-chip ' + x[3] + (state.woFilter === x[0] ? ' active' : '') + '" data-filter="' + x[0] + '">' + esc(x[1]) + ' (' + x[2] + ')</span>';
    }).join('') + '</div><div class="mp-top">' + equipSelect('mp-eqf', state.equip, true) +
      '<input class="mp-q search" placeholder="Search number, title, assignee" value="' + esc(state.q) + '"><span class="mp-sp"></span>' +
      '<button class="mp-btn" data-act="newwo">+ New work order</button></div>';
    var q = state.q.toLowerCase();
    var rows = wos.filter(function (w) {
      if (state.equip && w.equipment_id !== state.equip) return false;
      if (q && ((w.number || '') + ' ' + (w.title || '') + ' ' + (w.assignee || '') + ' ' + (w.equipment_name || '')).toLowerCase().indexOf(q) < 0) return false;
      var ds = dueState(w), f = state.woFilter, o = OPEN.indexOf(w.status) >= 0;
      if (f === 'open') return o;
      if (f === 'overdue') return o && ds === 'overdue';
      if (f === 'due') return o && ds === 'due';
      if (f === 'progress') return w.status === S.PRG;
      if (f === 'hold') return w.status === S.HLD;
      if (f === 'verify') return w.status === S.CMP;
      if (f === 'closed') return w.status === S.CLS || w.status === S.CAN;
      return true;
    });
    var rank = {overdue: 0, due: 1, unknown: 2, upcoming: 3, done: 4, closed: 5};
    var porder = priorities().map(function (p) { return p.code; });
    rows.sort(function (a, b) { return (rank[dueState(a)] - rank[dueState(b)]) || (porder.indexOf(a.priority) - porder.indexOf(b.priority)) || String(b.number).localeCompare(String(a.number)); });
    if (!rows.length) return h + '<div class="mp-empty">' + (wos.length ? 'No work orders in this view.' : 'No work orders yet.') + '</div>';
    return h + '<table><thead><tr><th>WO number</th><th>Work</th><th>Equipment</th><th>Priority</th><th>Status</th><th>Due</th><th>Assigned to</th><th>Source</th></tr></thead><tbody>' +
      rows.map(function (w) {
        var ds = dueState(w), d = w.detail || {};
        return '<tr class="click' + (state.panel && state.panel.arg === w.id ? ' sel' : '') + '" data-act="viewwo" data-id="' + w.id + '"><td class="num">' + esc(w.number) + '</td>' +
          '<td><b>' + esc(w.title) + '</b><div class="sub"><span class="tag">' + esc(w.type) + '</span>' + ((d.checklist || []).length ? d.checklist.length + ' checklist steps' : '') + '</div></td>' +
          '<td class="nw">' + esc(w.equipment_name) + '</td><td><span class="pill pr-' + (porder.indexOf(w.priority) + 1) + '">' + esc(w.priority) + '</span></td>' +
          '<td><span class="st ' + statusCls(w.status) + '">' + esc(w.status) + '</span></td>' +
          '<td class="nw">' + (ds === 'overdue' || ds === 'due' ? '<span class="pill ' + ds + '">' + (ds === 'overdue' ? 'Overdue' : 'Due') + '</span> ' : '') + esc(dueText(w)) + '</td>' +
          '<td>' + esc(w.assignee || '-') + '</td><td class="nw sub">' + esc({plan: 'Plan ' + (d.plan_number || ''), alarm: 'Alarm', manual: 'Manual'}[w.source] || w.source || '') + '</td></tr>';
      }).join('') + '</tbody></table>';
  }
  function plansView() {
    var h = '<div class="mp-top"><span class="sub">Plans raise their work orders automatically when an occurrence enters its lead time.</span>' +
      '<span class="mp-sp"></span>' + equipSelect('mp-eqf', state.equip, true) + '<button class="mp-btn" data-act="newplan">+ New plan</button></div>';
    var rows = plans.filter(function (p) { return !state.equip || p.equipment_id === state.equip; });
    rows.sort(function (a, b) { return String(a.number).localeCompare(String(b.number)); });
    if (!rows.length) return h + '<div class="mp-empty">No maintenance plans yet.</div>';
    var porder = priorities().map(function (p) { return p.code; });
    return h + '<table><thead><tr><th>Plan</th><th>Work</th><th>Equipment</th><th>Interval</th><th>Next due</th><th>Priority</th><th>Assigned to</th><th>Last done</th><th>Status</th><th></th></tr></thead><tbody>' +
      rows.map(function (p) {
        var d = p.detail || {}, open = wos.filter(function (w) { return w.plan_id === p.id && ACTIVE.indexOf(w.status) >= 0; })[0];
        var e = eq(p.equipment_id);
        var next = p.strategy === 'meter' ? 'at ' + p.next_due_rh + ' ' + unit() + (e && e.meter != null ? '<div class="sub">now ' + e.meter + ' ' + esc(unit()) + '</div>' : '') : fmtDate(p.next_due_date);
        return '<tr><td class="num">' + esc(p.number) + '</td><td><b>' + esc(p.title) + '</b><div class="sub"><span class="tag">' + esc(p.type) + '</span>' +
          ((d.checklist || []).length ? d.checklist.length + ' steps' : '') + ((d.docs || []).length ? ' &middot; ' + d.docs.length + ' documents' : '') + '</div></td>' +
          '<td class="nw">' + esc(p.equipment_name) + '</td><td class="nw">' + (p.strategy === 'meter' ? 'Every ' + esc(p.interval_rh) + ' ' + esc(unit()) : 'Every ' + esc(p.interval_days) + ' days') +
          (p.strategy === 'meter' ? '' : '<div class="sub">raised ' + esc(p.lead_days) + ' days ahead</div>') + '</td><td class="nw">' + next + '</td>' +
          '<td><span class="pill pr-' + (porder.indexOf(p.priority) + 1) + '">' + esc(p.priority) + '</span></td><td>' + esc(d.assignee || '-') + '</td>' +
          '<td class="nw">' + (d.last_done_ts ? fmtTs(d.last_done_ts) + '<div class="sub">' + esc(d.last_wo || '') + '</div>' : '<span class="sub">never</span>') + '</td>' +
          '<td>' + (p.active === false ? '<span class="pill closed">Paused</span>' : open ? '<span class="pill upcoming">' + esc(open.number) + '</span>' : '<span class="pill done">Active</span>') + '</td>' +
          '<td><div class="acts"><button class="mp-btn small light" data-act="editplan" data-id="' + p.id + '">Edit</button>' +
          '<button class="mp-btn small light" data-act="toggleplan" data-id="' + p.id + '">' + (p.active === false ? 'Resume' : 'Pause') + '</button>' +
          (p.active !== false && !open ? '<button class="mp-btn small" data-act="raisenow" data-id="' + p.id + '" title="Raise the next work order now">Raise WO now</button>' : '') + '</div></td></tr>';
      }).join('') + '</tbody></table>';
  }
  function docsView() {
    var h = '<div class="mp-top"><span class="sub">Expiry dates are alerted ' + esc(cfg.doc_expiry_alert_days) + ' days ahead.</span><span class="mp-sp"></span>' +
      equipSelect('mp-eqf', state.equip, true) + '<button class="mp-btn" data-act="upload">+ Upload document</button></div>';
    var list = allDocs().filter(function (x) { return !state.equip || x.owner === state.equip || x.owner === 'general'; });
    list.sort(function (a, b) { return (b.d.uploaded_at || 0) - (a.d.uploaded_at || 0); });
    if (!list.length) return h + '<div class="mp-empty">No documents yet.</div>';
    return h + '<table><thead><tr><th>Document</th><th>Category</th><th>Rev</th><th>Validity</th><th>Equipment</th><th>File</th><th>Uploaded</th><th>Used by</th><th></th></tr></thead><tbody>' +
      list.map(function (x) {
        var st = docState(x.d);
        var used = plans.filter(function (p) { return ((p.detail || {}).docs || []).indexOf(x.d.id) >= 0; }).map(function (p) { return p.number; });
        return '<tr><td><span class="doc" data-doc="' + esc(x.d.id) + '">&#128196; ' + esc(x.d.title) + '</span>' + (x.d.doc_no ? '<div class="sub">' + esc(x.d.doc_no) + '</div>' : '') + '</td>' +
          '<td><span class="tag">' + esc(x.d.category || '') + '</span></td><td>' + esc(x.d.revision || '-') + '</td>' +
          '<td class="nw">' + (st ? '<span class="pill ' + st.k + '">' + esc(st.t) + '</span>' : '<span class="sub">-</span>') + '</td>' +
          '<td class="nw">' + esc(x.ownerName) + '</td><td class="nw">' + esc(x.d.file) + '<div class="sub">' + (x.d.size ? size(x.d.size) : '') + '</div></td>' +
          '<td class="nw">' + fmtTs(x.d.uploaded_at) + '<div class="sub">' + esc(x.d.uploaded_by) + '</div></td><td>' + (used.length ? esc(used.join(', ')) : '<span class="sub">-</span>') + '</td>' +
          '<td><div class="acts"><button class="mp-btn small light" data-doc="' + esc(x.d.id) + '">Download</button>' +
          '<button class="mp-btn small danger" data-act="deldoc" data-o="' + esc(x.owner) + '" data-d="' + esc(x.d.id) + '" title="Delete document">&times;</button></div></td></tr>';
      }).join('') + '</tbody></table>';
  }
  function kpis(list, start, end) {
    var dueIn = 0, onTime = 0, done = [];
    var planned = typeNames('planned'), corrective = typeNames('failure_codes');
    list.forEach(function (w) {
      if (w.status === S.CAN) return;
      var comp = w.completed_ts ? tsDay(w.completed_ts) : null;
      if (planned.indexOf(w.type) >= 0 && w.due_date && w.due_date >= start && w.due_date <= end) { dueIn++; if (comp && comp <= w.due_date) onTime++; }
      if (comp && comp >= start && comp <= end) done.push(w);
    });
    var corr = done.filter(function (w) { return corrective.indexOf(w.type) >= 0; });
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
    function card(v, l, hint) { return '<div class="mp-kpi"><div class="v">' + (v == null ? '--' : v) + '</div><div class="l">' + l + '</div><div class="h">' + hint + '</div></div>'; }
    var h = '<div class="mp-top"><b>Maintenance KPIs</b><span class="sub">' + fmtDate(start) + ' - ' + fmtDate(end) + '</span><span class="mp-sp"></span>' +
      '<select class="mp-kd">' + (cfg.alerts.kpi_periods_days || []).map(function (d) { return '<option value="' + d + '"' + (Number(d) === state.kpiDays ? ' selected' : '') + '>Last ' + d + ' days</option>'; }).join('') + '</select></div>' +
      '<div class="mp-kpis">' +
      card(k.pmc == null ? null : k.pmc + '%', 'PM compliance', k.pmOnTime + ' of ' + k.pmDue + ' planned WOs done by due date') +
      card(k.backlog, 'Open backlog', 'open work orders now') + card(k.overdue, 'Overdue', 'open and past due') +
      card(k.done, 'Completed', 'work orders completed in period') +
      card(k.planned == null ? null : k.planned + '%', 'Planned work', 'share of planned vs corrective') +
      card(k.mttr == null ? null : k.mttr + ' h', 'Mean time to repair', 'corrective: raised -> completed (' + k.corr + ')') +
      card(k.labour + ' h', 'Labour', 'hours booked on completed WOs') + card(k.downtime + ' h', 'Downtime', 'equipment downtime recorded') +
      card(k.cost.toLocaleString('en-IN'), 'Maintenance cost', 'parts and services on completed WOs') + '</div>';
    var rows = equipment.map(function (e) {
      var x = kpis(wos.filter(function (w) { return w.equipment_id === e.id; }), start, end);
      return '<tr><td>' + esc(e.name) + '</td><td>' + x.backlog + '</td><td>' + (x.overdue ? '<span class="pill overdue">' + x.overdue + '</span>' : 0) + '</td><td>' + x.done + '</td>' +
        '<td>' + x.corr + '</td><td>' + (x.pmc == null ? '--' : x.pmc + '%') + '</td><td>' + (x.mttr == null ? '--' : x.mttr + ' h') + '</td><td>' + x.downtime + '</td><td>' + x.cost.toLocaleString('en-IN') + '</td></tr>';
    }).join('');
    return h + '<table style="margin-top:10px"><thead><tr><th>Equipment</th><th>Open</th><th>Overdue</th><th>Completed</th><th>Corrective</th><th>PM compliance</th><th>MTTR</th><th>Downtime h</th><th>Cost</th></tr></thead><tbody>' + rows + '</tbody></table>' +
      '<div class="sub" style="margin-top:6px">Calculated only from work orders recorded here; "--" means no data in the period.</div>';
  }

  // ---------------------------------------------------------------- settings
  function listTxt(a) { return esc((a || []).join('\n')); }
  function settingsView() {
    var c = cfg;
    var pmList = equipment.filter(function (e) { return e.pm && e.pm.kind; });
    var noPm = equipment.filter(function (e) { return !(e.pm && e.pm.kind); });
    var sel = state.pmEquip && eq(state.pmEquip) ? state.pmEquip : (pmList[0] && pmList[0].id) || '';
    return '<div class="mp-set">' +
      '<div class="mp-panel"><h4>Maintenance settings</h4><div class="mp-grid">' +
      '<label>Site time zone (minutes from UTC)<input type="number" class="s-tz" step="1" value="' + esc(c.timezone_offset_minutes) + '"></label>' +
      '<label>"Due soon" window (days)<input type="number" class="s-soon" min="0" step="1" value="' + esc(c.due_soon_days) + '"></label>' +
      '<label>Meter telemetry key<input class="s-mkey" value="' + esc(c.meter.key) + '"></label>' +
      '<label>Meter unit<input class="s-munit" value="' + esc(c.meter.unit) + '"></label>' +
      '<label>Meter valid from<input type="number" class="s-mmin" step="any" value="' + esc(c.meter.valid_min) + '"></label>' +
      '<label>Meter valid below<input type="number" class="s-mmax" step="any" value="' + esc(c.meter.valid_below) + '"></label>' +
      '<label>Meter due window (% of interval)<input type="number" class="s-mwp" min="0" step="any" value="' + esc(c.meter_due_window.pct_of_interval) + '"></label>' +
      '<label>Meter due window (minimum units)<input type="number" class="s-mwm" min="0" step="any" value="' + esc(c.meter_due_window.min_units) + '"></label>' +
      '<label>Document expiry alert (days ahead)<input type="number" class="s-exp" min="0" step="1" value="' + esc(c.doc_expiry_alert_days) + '"></label>' +
      '<label>Maximum upload size (MB)<input type="number" class="s-mb" min="1" step="1" value="' + esc(c.max_upload_mb) + '"></label>' +
      '<label class="wide chk"><input type="checkbox" class="s-ver"' + (c.verification.different_user ? ' checked' : '') + '> Work must be verified by a different user than the one who recorded it</label>' +
      '<div class="mp-field wide">Equipment in scope (device profiles)<div class="mp-checks s-prof"><span class="sub">loading profiles…</span></div></div>' +
      '<div class="mp-field wide">Priorities (code, label, response days)<table class="mp-parts s-pri"><tbody>' + priorities().map(priRow).join('') + '</tbody></table><button class="mp-btn small light" data-act="addpri" style="align-self:flex-start">+ priority</button></div>' +
      '<div class="mp-field wide">Work-order types<table class="mp-parts s-types"><thead><tr><th>Name</th><th>Planned work</th><th>Allowed in plans</th><th>Failure codes required</th><th>Restarts PM service countdown</th><th></th></tr></thead><tbody>' +
      c.wo_types.map(typeRow).join('') + '</tbody></table><button class="mp-btn small light" data-act="addtype" style="align-self:flex-start">+ type</button></div>' +
      '<label>Failure problems (one per line)<textarea class="s-fp" rows="6">' + listTxt(c.failure_codes.problem) + '</textarea></label>' +
      '<label>Failure causes (one per line)<textarea class="s-fc" rows="6">' + listTxt(c.failure_codes.cause) + '</textarea></label>' +
      '<label>Maintenance actions (one per line)<textarea class="s-fa" rows="6">' + listTxt(c.failure_codes.action) + '</textarea></label>' +
      '<label>Document categories (one per line)<textarea class="s-cat" rows="6">' + listTxt(c.doc_categories) + '</textarea></label>' +
      '<label>Category of attached photos<input class="s-aimg" value="' + esc(c.attachment_categories.image) + '"></label>' +
      '<label>Category of other attachments<input class="s-aoth" value="' + esc(c.attachment_categories.other) + '"></label>' +
      '<h5 class="wide">Condition-based work orders (created by the server from alarms)</h5>' +
      '<label class="wide chk"><input type="checkbox" class="s-cbe"' + (c.condition_based.enabled ? ' checked' : '') + '> Create a work order for each matching active alarm</label>' +
      '<div class="mp-field">Alarm severities<div class="mp-checks s-cbs">' + SEVERITIES.map(function (s) { return '<label><input type="checkbox" value="' + s + '"' + (c.condition_based.severities.indexOf(s) >= 0 ? ' checked' : '') + '> ' + s + '</label>'; }).join('') + '</div></div>' +
      '<label>Alarm types (one per line, * = any text)<textarea class="s-cbt" rows="4">' + listTxt(c.condition_based.alarm_types) + '</textarea></label>' +
      '<label>Work-order type<select class="s-cbw">' + opts(typeNames(), c.condition_based.wo_type) + '</select></label>' +
      '<label>Priority<select class="s-cbp">' + opts(priOpts(), c.condition_based.priority) + '</select></label>' +
      '<h5 class="wide">Alerts and KPIs</h5>' +
      '<div class="mp-field">Alert overdue work orders of priority<div class="mp-checks s-od">' + priorities().map(function (p) { return '<label><input type="checkbox" value="' + esc(p.code) + '"' + (c.alerts.overdue_priorities.indexOf(p.code) >= 0 ? ' checked' : '') + '> ' + esc(priLabel(p.code)) + '</label>'; }).join('') + '</div></div>' +
      '<label class="chk"><input type="checkbox" class="s-de"' + (c.alerts.digest_enabled ? ' checked' : '') + '> Daily digest (Telegram + email)</label>' +
      '<label>Digest hour (site time, 0-23)<input type="number" class="s-dh" min="0" max="23" step="1" value="' + esc(c.alerts.digest_hour) + '"></label>' +
      '<label>KPI periods (days, comma separated)<input class="s-kp" value="' + esc((c.alerts.kpi_periods_days || []).join(', ')) + '"></label>' +
      '</div><div class="mp-row"><button class="mp-btn" data-act="savesettings">Save maintenance settings</button><span class="mp-status s-st1"></span></div></div>' +
      '<div class="mp-panel" style="margin-top:12px"><h4>Predictive maintenance</h4>' +
      (pmList.length ? '<div class="mp-top">Equipment <select class="s-pme">' + pmList.map(function (e) { return '<option value="' + e.id + '"' + (e.id === sel ? ' selected' : '') + '>' + esc(e.name) + ' (' + esc(e.pm.kind) + ')</option>'; }).join('') + '</select>' +
        '<label class="chk"><input type="checkbox" class="s-pmall"> Apply the engine settings to all equipment</label></div>' +
        '<div class="s-pmform">' + (sel ? pmForm(eq(sel)) : '') + '</div>' +
        '<div class="mp-row"><button class="mp-btn" data-act="savepm" data-id="' + sel + '">Save predictive-maintenance settings</button><span class="mp-status s-st2"></span></div>' : '<div class="mp-empty">No equipment has predictive maintenance configured.</div>') +
      (noPm.length && templates ? '<h5>Equipment without predictive maintenance</h5><div class="mp-top">' + noPm.map(function (e) {
        var k = templates.profiles && templates.profiles[e.type];
        return k ? '<button class="mp-btn small light" data-act="pmtemplate" data-id="' + e.id + '">Configure ' + esc(e.name) + ' from the ' + esc(k) + ' template</button>' : '<span class="sub">' + esc(e.name) + ': no template for profile ' + esc(e.type) + '</span>';
      }).join('') + '</div><div class="sub">Template values are a starting point: check nominal voltages, ratings and keys of the new equipment.</div>' : '') +
      '</div></div>';
  }
  function priRow(p) {
    return '<tr><td><input class="p-code" maxlength="8" value="' + esc(p.code) + '"></td><td><input class="p-lab" maxlength="40" value="' + esc(p.label) + '"></td>' +
      '<td><input class="p-days" type="number" min="0" step="1" value="' + esc(p.response_days) + '"></td><td><button class="mp-btn small danger" data-act="delrow">&times;</button></td></tr>';
  }
  function typeRow(t) {
    function cb(k) { return '<td style="text-align:center"><input type="checkbox" class="t-' + k + '"' + (t[k] ? ' checked' : '') + '></td>'; }
    return '<tr><td><input class="t-name" maxlength="40" value="' + esc(t.name) + '"></td>' + cb('planned') + cb('plan_allowed') + cb('failure_codes') + cb('pm_service_reset') +
      '<td><button class="mp-btn small danger" data-act="delrow">&times;</button></td></tr>';
  }
  // Generic editor of a pm_config section: numbers, texts, flags, number lists, text lists, per-feeder maps, nested groups.
  function field(path, v, label) {
    var dp = ' data-path="' + esc(path) + '"';
    if (MAP_FIELDS.indexOf(path.split('.').pop()) >= 0 && (v == null || typeof v === 'object')) {
      return '<label>' + esc(label) + ' (one per line: name = value)<textarea class="pm-map"' + dp + ' rows="4">' + esc(Object.keys(v || {}).map(function (k) { return k + ' = ' + v[k]; }).join('\n')) + '</textarea></label>';
    }
    if (v instanceof Array) {
      if (v.length && typeof v[0] === 'string') return '<label>' + esc(label) + ' (one per line)<textarea class="pm-slist"' + dp + ' rows="3">' + esc(v.join('\n')) + '</textarea></label>';
      return '<label>' + esc(label) + ' (comma separated)<input class="pm-nlist"' + dp + ' value="' + esc(v.join(', ')) + '"></label>';
    }
    if (v !== null && typeof v === 'object') {
      return '<fieldset class="mp-fs wide"><legend>' + esc(label) + '</legend><div class="mp-grid">' + Object.keys(v).filter(function (k) { return k.charAt(0) !== '_'; }).map(function (k) {
        return field(path + '.' + k, v[k], k.replace(/_/g, ' '));
      }).join('') + '</div></fieldset>';
    }
    if (typeof v === 'boolean') return '<label class="chk"><input type="checkbox" class="pm-bool"' + dp + (v ? ' checked' : '') + '> ' + esc(label) + '</label>';
    if (typeof v === 'string') return '<label>' + esc(label) + '<input class="pm-str"' + dp + ' value="' + esc(v) + '"></label>';
    return '<label>' + esc(label) + '<input type="number" step="any" class="pm-num"' + dp + ' value="' + esc(v == null ? '' : v) + '"></label>';
  }
  function pmForm(e) {
    var pm = e.pm;
    return '<div class="sub" style="margin:6px 0">Kind: <b>' + esc(pm.kind) + '</b>. Empty fields switch the related check off (shown on the dashboard as "not configured").</div>' +
      field('engine', pm.engine || {}, 'Engine (scoring, staleness, invalid codes)') + field('limits', pm.limits || {}, 'Limits and telemetry keys');
  }
  function readField(el) {
    var c = el.className;
    if (/pm-bool/.test(c)) return el.checked;
    if (/pm-num/.test(c)) return num(el.value);
    if (/pm-str/.test(c)) return el.value.trim() === '' ? null : el.value.trim();
    if (/pm-nlist/.test(c)) return el.value.split(',').map(function (x) { return x.trim(); }).filter(Boolean).map(Number).filter(function (x) { return isFinite(x); });
    if (/pm-slist/.test(c)) return lines(el.value);
    var m = {};
    lines(el.value).forEach(function (l) { var p = l.split('='); if (p.length === 2 && p[0].trim() && isFinite(Number(p[1]))) m[p[0].trim()] = Number(p[1]); });
    return m;
  }
  function setPath(o, p, v) { var a = p.split('.'); var c = o; for (var i = 0; i < a.length - 1; i++) { if (!c[a[i]] || typeof c[a[i]] !== 'object') c[a[i]] = {}; c = c[a[i]]; } c[a[a.length - 1]] = v; }
  function bindSettings() {
    var box = root.querySelector('.s-prof');
    req(http.get('/api/deviceProfileInfos?pageSize=200&page=0&sortProperty=name&sortOrder=ASC')).then(function (r) {
      var names = (r.data || []).map(function (p) { return p.name; });
      cfg.equipment_profiles.forEach(function (p) { if (names.indexOf(p) < 0) names.push(p); });
      box.innerHTML = names.map(function (n) { return '<label><input type="checkbox" value="' + esc(n) + '"' + (cfg.equipment_profiles.indexOf(n) >= 0 ? ' checked' : '') + '> ' + esc(n) + '</label>'; }).join('');
    }, function () { box.innerHTML = cfg.equipment_profiles.map(function (n) { return '<label><input type="checkbox" value="' + esc(n) + '" checked> ' + esc(n) + '</label>'; }).join(''); });
    var pme = root.querySelector('.s-pme');
    if (pme) pme.addEventListener('change', function () { state.pmEquip = pme.value; render(); });
  }
  function collectSettings() {
    var q = function (s) { return root.querySelector(s); };
    var checked = function (s) { return [].slice.call(root.querySelectorAll(s + ' input:checked')).map(function (c) { return c.value; }); };
    var pr = [].slice.call(root.querySelectorAll('.s-pri tr')).map(function (tr) {
      return {code: tr.querySelector('.p-code').value.trim(), label: tr.querySelector('.p-lab').value.trim(), response_days: num(tr.querySelector('.p-days').value)};
    }).filter(function (p) { return p.code; });
    var ty = [].slice.call(root.querySelectorAll('.s-types tbody tr')).map(function (tr) {
      var g = function (k) { return tr.querySelector('.t-' + k).checked; };
      return {name: tr.querySelector('.t-name').value.trim(), planned: g('planned'), plan_allowed: g('plan_allowed'), failure_codes: g('failure_codes'), pm_service_reset: g('pm_service_reset')};
    }).filter(function (t) { return t.name; });
    var n = clone(cfg);
    n.timezone_offset_minutes = num(q('.s-tz').value); n.due_soon_days = num(q('.s-soon').value);
    n.meter = {key: q('.s-mkey').value.trim(), unit: q('.s-munit').value.trim(), valid_min: num(q('.s-mmin').value), valid_below: num(q('.s-mmax').value)};
    n.meter_due_window = {pct_of_interval: num(q('.s-mwp').value), min_units: num(q('.s-mwm').value)};
    n.doc_expiry_alert_days = num(q('.s-exp').value); n.max_upload_mb = num(q('.s-mb').value);
    n.verification = {different_user: q('.s-ver').checked};
    n.equipment_profiles = checked('.s-prof');
    n.priorities = pr; n.wo_types = ty;
    n.failure_codes = {problem: lines(q('.s-fp').value), cause: lines(q('.s-fc').value), action: lines(q('.s-fa').value)};
    n.doc_categories = lines(q('.s-cat').value);
    n.attachment_categories = {image: q('.s-aimg').value.trim(), other: q('.s-aoth').value.trim()};
    n.condition_based = {enabled: q('.s-cbe').checked, severities: checked('.s-cbs'), alarm_types: lines(q('.s-cbt').value), wo_type: q('.s-cbw').value, priority: q('.s-cbp').value};
    n.alerts = {overdue_priorities: checked('.s-od'), digest_enabled: q('.s-de').checked, digest_hour: num(q('.s-dh').value),
                kpi_periods_days: q('.s-kp').value.split(',').map(function (x) { return num(x.trim()); }).filter(function (x) { return x > 0; })};
    var errs = [];
    [['timezone_offset_minutes', n.timezone_offset_minutes], ['due soon days', n.due_soon_days], ['meter valid range', n.meter.valid_min], ['meter valid range', n.meter.valid_below],
     ['meter window', n.meter_due_window.pct_of_interval], ['meter window', n.meter_due_window.min_units], ['document expiry days', n.doc_expiry_alert_days], ['upload size', n.max_upload_mb],
     ['digest hour', n.alerts.digest_hour]].forEach(function (x) { if (x[1] == null && errs.indexOf(x[0]) < 0) errs.push(x[0]); });
    if (!n.meter.key || !n.meter.unit) errs.push('meter key and unit');
    if (!n.equipment_profiles.length) errs.push('at least one equipment profile');
    if (!pr.length || pr.some(function (p) { return !p.label || p.response_days == null; })) errs.push('priorities (label and response days)');
    if (!ty.length) errs.push('work-order types');
    if (!n.failure_codes.problem.length || !n.failure_codes.cause.length || !n.failure_codes.action.length) errs.push('failure codes');
    if (!n.doc_categories.length || !n.attachment_categories.image || !n.attachment_categories.other) errs.push('document categories');
    if (n.condition_based.enabled && (!n.condition_based.severities.length || !n.condition_based.alarm_types.length)) errs.push('condition-based severities and alarm types');
    if (!n.alerts.kpi_periods_days.length) errs.push('KPI periods');
    return {cfg: n, errs: errs};
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
  function pstatus(t, k, scope) { var s = (scope || slot()).querySelector('.mp-status'); if (s) { s.textContent = t || ''; s.className = 'mp-status ' + (k || ''); } }
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
      var own = cfg.verification.different_user && (d.completed_by || {}).user === me.user;
      acts += '<button class="mp-btn ok" data-act="verify"' + (own ? ' disabled title="Another user must verify your work"' : '') + '>Verify &amp; close</button>' +
        '<button class="mp-btn warn" data-act="reject">Reject (rework)</button>' + (own ? '<span class="sub">You recorded this work, so another user must verify it.</span>' : '');
    }
    if (OPEN.indexOf(w.status) >= 0) acts += '<button class="mp-btn light" data-act="editwo">Edit</button>';
    if (allowed(w, S.CAN)) acts += '<button class="mp-btn danger" data-act="cancel">Cancel WO</button>';
    acts += '<button class="mp-btn light" data-act="print">Print job card</button><button class="mp-btn light" data-act="close">Close</button>';
    var res = d.results || [];
    var cl = (d.checklist || []).map(function (s, i) {
      var r = res[i];
      return '<div>' + (r && r.done ? '&#9745; ' : '&#9744; ') + esc(s) + (r && r.note ? ' <span class="sub">- ' + esc(r.note) + '</span>' : '') + '</div>';
    }).join('');
    var parts = (d.parts || []).map(function (p) { return esc(p.name) + ' x ' + esc(p.qty) + (p.rate ? ' @ ' + esc(p.rate) : ''); }).join('; ');
    slot().innerHTML = '<div class="mp-panel"><h4>' + esc(w.number) + ' &middot; ' + esc(w.title) + ' <span class="pill">' + esc(priLabel(w.priority)) + '</span>' +
      '<span class="st ' + statusCls(w.status) + '">' + esc(w.status) + '</span>' + (ds === 'overdue' ? '<span class="pill overdue">Overdue</span>' : '') + '</h4>' +
      '<div class="mp-kv"><div><b>Equipment</b>' + esc(w.equipment_name) + (hasMeter(e) && e.meter != null ? ' <span class="sub">(now ' + e.meter + ' ' + esc(unit()) + ')</span>' : '') + '</div>' +
      '<div><b>Type</b>' + esc(w.type) + '</div><div><b>Due</b>' + esc(dueText(w) || '-') + '</div><div><b>Assigned to</b>' + esc(w.assignee || '-') + '</div>' +
      '<div><b>Raised</b>' + fmtTs(w.created_ts) + '<div class="sub">' + esc({plan: 'from plan ' + (d.plan_number || ''), alarm: 'by alarm ' + (d.alarm_type || ''), manual: 'manually'}[w.source] || '') + '</div></div>' +
      (d.est_hours ? '<div><b>Estimated</b>' + esc(d.est_hours) + ' h</div>' : '') +
      (w.completed_ts ? '<div><b>Completed</b>' + fmtTs(w.completed_ts) + '<div class="sub">' + esc(d.technician || '') + (d.completed_by ? ', recorded by ' + esc(d.completed_by.name) : '') + '</div></div>' : '') +
      (w.closed_ts && w.status === S.CLS ? '<div><b>Verified</b>' + fmtTs(w.closed_ts) + '<div class="sub">' + esc((d.verified_by || {}).name || '') + '</div></div>' : '') + '</div>' +
      (d.description ? '<h5>Description</h5><div>' + esc(d.description) + '</div>' : '') +
      ((d.docs || []).length ? '<h5>Technical documents</h5><div>' + docLinks(d.docs) + '</div>' : '') +
      (cl ? '<h5>Checklist</h5>' + cl : '') +
      (d.work_done ? '<h5>Work done</h5><div>' + esc(d.work_done) + '</div><div class="mp-kv" style="margin-top:6px">' +
        (d.done_rh != null ? '<div><b>Meter</b>' + esc(d.done_rh) + ' ' + esc(unit()) + '</div>' : '') + '<div><b>Labour</b>' + esc(d.labour_hours || 0) + ' h</div><div><b>Downtime</b>' + esc(d.downtime_hours || 0) + ' h</div>' +
        '<div><b>Cost</b>' + esc(d.cost_total || 0) + '</div>' + (d.failure && d.failure.problem ? '<div><b>Failure</b>' + esc(d.failure.problem) + ' / ' + esc(d.failure.cause) + ' / ' + esc(d.failure.action) + '</div>' : '') + '</div>' +
        (parts ? '<div class="sub">Parts: ' + parts + '</div>' : '') + ((d.attachments || []).length ? '<div style="margin-top:4px">' + docLinks(d.attachments.map(function (a) { return a.id; })) + '</div>' : '') : '') +
      (d.hold_reason && w.status === S.HLD ? '<div class="mp-hl" style="margin-top:8px">On hold: ' + esc(d.hold_reason) + '</div>' : '') +
      (d.cancel_reason ? '<div class="mp-hl" style="margin-top:8px">Cancelled: ' + esc(d.cancel_reason) + '</div>' : '') +
      '<h5>History</h5><div class="mp-tl">' + (d.history || []).slice().reverse().map(function (x) {
        return '<div><b>' + esc(x.action) + '</b>' + (x.to ? ' &rarr; ' + esc(x.to) : '') + ' &middot; ' + fmtTs(x.ts) + ' &middot; ' + esc(x.name || x.user) + (x.note ? '<div class="sub">' + esc(x.note) + '</div>' : '') + '</div>';
      }).join('') + '</div><div class="mp-row">' + acts + '<span class="mp-status"></span></div></div>';
  }
  function docChecks(eid, selected) {
    var av = docsFor(eid);
    return av.length ? av.map(function (x) {
      return '<label><input type="checkbox" value="' + esc(x.d.id) + '"' + ((selected || []).indexOf(x.d.id) >= 0 ? ' checked' : '') + '> ' + esc(x.d.title) + ' <span class="sub">(' + esc(x.d.category) + ', ' + esc(x.o) + ')</span></label>';
    }).join('') : '<span class="sub">No documents for this equipment.</span>';
  }

  function woForm(arg) {
    var w = arg && arg.id ? byId(wos, arg.id) : null, d = (w && w.detail) || {};
    var e0 = w ? w.equipment_id : state.equip;
    slot().innerHTML = '<div class="mp-panel"><h4>' + (w ? 'Edit ' + esc(w.number) : 'New work order') + '</h4><div class="mp-grid">' +
      '<label>Equipment <span class="req">*</span>' + equipSelect('f-eq', e0, false, false, !w) + '</label>' +
      '<label class="wide">Title <span class="req">*</span><input class="f-title" maxlength="120" value="' + esc(w ? w.title : '') + '"></label>' +
      '<label>Type <span class="req">*</span><select class="f-type">' + opts(typeNames(), w ? w.type : '', !w) + '</select></label>' +
      '<label>Priority <span class="req">*</span><select class="f-pri">' + opts(priOpts(), w ? w.priority : '', !w) + '</select></label>' +
      '<label class="w-date">Due date <span class="req">*</span><input type="date" class="f-date" value="' + esc(w ? (w.due_date || '') : '') + '"><span class="sub">set from the priority response time; can be changed</span></label>' +
      '<label class="w-rh">Due at meter reading (' + esc(unit()) + ')<input type="number" class="f-rh" step="0.1" min="0" value="' + esc(w && w.due_rh != null ? w.due_rh : '') + '"></label>' +
      '<label>Assigned to<input class="f-asg" maxlength="80" value="' + esc(w ? w.assignee : '') + '"></label>' +
      '<label>Estimated hours<input type="number" class="f-est" step="0.25" min="0" value="' + esc(d.est_hours == null ? '' : d.est_hours) + '"></label>' +
      '<label class="wide">Description<textarea class="f-desc" rows="2" maxlength="1000">' + esc(d.description || '') + '</textarea></label>' +
      '<label class="wide">Checklist (one step per line)<textarea class="f-cl" rows="3">' + esc((d.checklist || []).join('\n')) + '</textarea></label>' +
      '<div class="mp-field wide">Technical documents<div class="mp-checks f-docs"></div></div>' +
      '</div><div class="mp-row"><button class="mp-btn" data-act="savewo">' + (w ? 'Save changes' : 'Create work order') + '</button><button class="mp-btn light" data-act="close">Cancel</button><span class="mp-status"></span></div></div>';
    var p = slot();
    function sync() {
      var ee = eq(p.querySelector('.f-eq').value);
      p.querySelector('.w-rh').style.display = hasMeter(ee) ? '' : 'none';
      p.querySelector('.f-docs').innerHTML = ee ? docChecks(ee.id, d.docs) : '<span class="sub">Choose the equipment first.</span>';
    }
    p.querySelector('.f-eq').addEventListener('change', sync);
    p.querySelector('.f-pri').addEventListener('change', function () {
      var pp = pri(p.querySelector('.f-pri').value);
      if (!w && pp) p.querySelector('.f-date').value = addDays(today(), Number(pp.response_days));
    });
    if (w) p.querySelector('.f-eq').disabled = true;
    sync();
    p.querySelector('[data-act="savewo"]').addEventListener('click', function () {
      var ee = eq(p.querySelector('.f-eq').value), title = p.querySelector('.f-title').value.trim(), due = p.querySelector('.f-date').value;
      var ty = p.querySelector('.f-type').value, pr = p.querySelector('.f-pri').value;
      if (!ee || !title || !ty || !pr || !due) { pstatus('Equipment, title, type, priority and due date are required.', 'bad'); return; }
      var f = {title: title, type: ty, priority: pr, due_date: due, due_rh: hasMeter(ee) ? num(p.querySelector('.f-rh').value) : null, assignee: p.querySelector('.f-asg').value.trim()};
      var det = clone(d);
      det.description = p.querySelector('.f-desc').value.trim();
      det.checklist = lines(p.querySelector('.f-cl').value);
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
        createWo({title: f.title, type: f.type, priority: f.priority, status: S.SCH, source: 'manual', plan_id: '', alarm_id: '', equipment_id: ee.id,
                  equipment_name: ee.name, due_date: f.due_date, due_rh: f.due_rh, interval_rh: null, assignee: f.assignee, created_ts: Date.now(),
                  completed_ts: null, closed_ts: null, overdue_alerted: false, detail: det})
          .then(function (r) { state.panel = {kind: 'wo', arg: r.id}; return reload(); }, fail);
      }
    });
  }
  function createWo(fields) {
    return createNumbered(WO_T, 'WO-' + today().slice(0, 4) + '-', 5, fields.title).then(function (asset) {
      var v = {wo_rev: 1}; Object.keys(fields).forEach(function (k) { v['wo_' + k] = fields[k]; });
      return saveAttrs('ASSET', asset.id.id, v).then(function () { return relate(fields.equipment_id, asset.id.id); }).then(function () { return {id: asset.id.id, number: asset.name}; });
    });
  }

  function transition(w, to, action, note, extra) {
    if (!allowed(w, to)) return Promise.reject({message: 'A work order in status ' + w.status + ' cannot be moved to ' + to});
    var d = clone(w.detail || {});
    d.history = (d.history || []).concat([hist(action, note, w.status, to)]);
    var v = {wo_status: to, wo_detail: d};
    if (extra) extra(v, d);
    return guardedSave(w, 'wo_', v);
  }
  function reasonForm(arg) {
    var w = byId(wos, arg.id);
    if (!w) return false;
    var label = {hold: 'Reason for hold', cancel: 'Reason for cancelling', reject: 'What must be reworked'}[arg.kind];
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
          var upd = planAfterSkip(p, w), pd = clone(p.detail || {});
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
    var d = w.detail || {}, e = eq(w.equipment_id), metered = hasMeter(e), ty = type(w.type);
    var corrective = !!ty.failure_codes;
    var svc = !!ty.pm_service_reset && !!(e && e.pm && e.pm.kind) && metered;
    var plan = byId(plans, w.plan_id);
    var needMeter = svc || (plan && plan.strategy === 'meter');
    slot().innerHTML = '<div class="mp-panel"><h4>Record work done &middot; ' + esc(w.number) + ' &middot; ' + esc(w.title) + '</h4>' +
      ((d.docs || []).length ? '<div class="sub" style="margin-bottom:6px">Documents: ' + docLinks(d.docs) + '</div>' : '') +
      ((d.checklist || []).length ? '<h5>Checklist <span class="req">*</span> (tick each step done; remark required for a step not done)</h5><div class="mp-checks c-cl" style="max-height:none">' + d.checklist.map(function (s, i) {
        return '<div class="mp-cl-row"><input type="checkbox" data-i="' + i + '"><span>' + esc(s) + '</span><input class="c-note" data-i="' + i + '" placeholder="Reading / remark"></div>';
      }).join('') + '</div>' : '') +
      '<div class="mp-grid" style="margin-top:10px">' +
      '<label>Work finished at <span class="req">*</span><input type="datetime-local" class="c-when" max="' + localNow() + '"></label>' +
      '<label>Technician / vendor <span class="req">*</span><input class="c-tech" maxlength="80" value="' + esc(w.assignee || '') + '"></label>' +
      '<label>Meter reading at work (' + esc(unit()) + ')' + (needMeter ? ' <span class="req">*</span>' : '') + '<input type="number" class="c-rh" step="0.1" min="0"' + (metered ? ' value="' + esc(e.meter == null ? '' : e.meter) + '"' : ' disabled') + '>' +
        (metered ? '<span class="sub">latest reading from the equipment</span>' : '') + '</label>' +
      '<label>Labour hours <span class="req">*</span><input type="number" class="c-lab" step="0.25" min="0"></label>' +
      '<label>Equipment downtime (h) <span class="req">*</span><input type="number" class="c-down" step="0.25" min="0"></label>' +
      '<label class="wide">Work done <span class="req">*</span><textarea class="c-desc" rows="3" maxlength="1500"></textarea></label>' +
      (corrective ? '<label>Failure (problem) <span class="req">*</span><select class="c-fp">' + opts(cfg.failure_codes.problem, '', true) + '</select></label>' +
        '<label>Cause <span class="req">*</span><select class="c-fc">' + opts(cfg.failure_codes.cause, '', true) + '</select></label>' +
        '<label>Action taken <span class="req">*</span><select class="c-fa">' + opts(cfg.failure_codes.action, '', true) + '</select></label>' : '') +
      '<div class="mp-field wide">Spare parts / services<table class="mp-parts"><thead><tr><th>Item</th><th style="width:90px">Qty</th><th style="width:120px">Rate</th></tr></thead><tbody class="c-parts">' +
      partRow() + '</tbody></table><button class="mp-btn small light" data-act="addpart" style="align-self:flex-start;margin-top:4px">+ row</button></div>' +
      '<label class="wide">Job card / photos / test reports<input type="file" class="c-files" multiple></label>' +
      (svc ? '<label class="wide mp-hl chk"><input type="checkbox" class="c-reset"> Scheduled service done: restart the predictive-maintenance service countdown from this meter reading</label>' : '') +
      '</div><div class="sub" style="margin-top:8px">' + (plan ? 'Plan ' + esc(plan.number) + ' moves to its next due point (' + (plan.strategy === 'meter' ? plan.interval_rh + ' ' + esc(unit()) : plan.interval_days + ' days') + ' after this work).' : '') +
      (cfg.verification.different_user ? ' After saving, another user verifies and closes the work order.' : '') + '</div>' +
      '<div class="mp-row"><button class="mp-btn ok" data-act="savedone">Save as completed</button><button class="mp-btn light" data-act="back">Back</button><span class="mp-status"></span></div></div>';
    var p = slot();
    p.querySelector('[data-act="addpart"]').addEventListener('click', function () {
      var tb = document.createElement('tbody'); tb.innerHTML = partRow(); p.querySelector('.c-parts').appendChild(tb.firstChild);
    });
    p.querySelector('[data-act="savedone"]').addEventListener('click', function () {
      var whenV = p.querySelector('.c-when').value, ts = whenV ? new Date(whenV).getTime() : NaN;
      var tech = p.querySelector('.c-tech').value.trim(), desc = p.querySelector('.c-desc').value.trim();
      var rh = metered ? num(p.querySelector('.c-rh').value) : null, lab = num(p.querySelector('.c-lab').value), down = num(p.querySelector('.c-down').value);
      var reset = !!(p.querySelector('.c-reset') && p.querySelector('.c-reset').checked);
      var results = [].slice.call(p.querySelectorAll('.c-cl input[type=checkbox]')).map(function (c) {
        var i = Number(c.getAttribute('data-i'));
        return {item: d.checklist[i], done: c.checked, note: (p.querySelector('.c-note[data-i="' + i + '"]').value || '').trim()};
      });
      var errs = [];
      if (!isFinite(ts) || ts > Date.now() + 60000) errs.push('the finish time (not in the future)');
      if (!tech) errs.push('the technician');
      if (!desc) errs.push('the work done');
      if (lab == null) errs.push('labour hours');
      if (down == null) errs.push('downtime hours (0 if none)');
      if ((reset || needMeter) && rh == null) errs.push('the meter reading at the time of work');
      var undone = results.filter(function (r) { return !r.done && !r.note; });
      if (undone.length) errs.push('a remark for each checklist step not done (' + undone.length + ')');
      var fail3 = corrective ? {problem: p.querySelector('.c-fp').value, cause: p.querySelector('.c-fc').value, action: p.querySelector('.c-fa').value} : null;
      if (fail3 && !(fail3.problem && fail3.cause && fail3.action)) errs.push('failure problem, cause and action');
      var parts = [].slice.call(p.querySelectorAll('.c-parts tr')).map(function (tr) {
        return {name: tr.querySelector('.p-n').value.trim(), qty: num(tr.querySelector('.p-q').value), rate: num(tr.querySelector('.p-r').value)};
      }).filter(function (x) { return x.name; });
      if (parts.some(function (x) { return x.qty == null || x.rate == null; })) errs.push('quantity and rate of each part');
      if (errs.length) { pstatus('Please enter ' + errs.join(', ') + '.', 'bad'); return; }
      var cost = Math.round(parts.reduce(function (s, x) { return s + x.qty * x.rate; }, 0) * 100) / 100;
      var files = [].slice.call(p.querySelector('.c-files').files || []);
      busy(true); pstatus(files.length ? 'Uploading ' + files.length + ' file(s)…' : 'Saving…');
      files.reduce(function (pr, f) {
        return pr.then(function (acc) {
          return uploadFile(f, w.number + ' - ' + f.name).then(function (meta) { meta.category = attachCat(f.name); meta.wo = w.number; acc.push(meta); return acc; });
        });
      }, Promise.resolve([])).then(function (att) {
        var rec = {type: w.type, description: desc, technician: tech, run_hours: rh, parts: parts.map(function (x) { return x.name + ' x' + x.qty; }).join(', ') || null,
                   cost: cost || null, next_due: null, service_reset: reset, logged_by: me.name, logged_at: Date.now(), wo_number: w.number, job_title: w.title,
                   checklist: results, labour_hours: lab, downtime_hours: down, failure: fail3, attachments: att.map(function (a) { return {id: a.id, title: a.title, file: a.file}; })};
        var planUpd = plan ? planAfterCompletion(plan, tsDay(ts), rh) : null;
        if (planUpd) rec.next_due = planUpd.plan_next_due_date || (planUpd.plan_next_due_rh != null ? planUpd.plan_next_due_rh + ' ' + unit() : null);
        return (att.length ? appendDocs(w.equipment_id, att) : Promise.resolve()).then(function () {
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
          var pd = clone(plan.detail || {});
          pd.last_done_ts = ts; pd.last_wo = w.number;
          pd.history = (pd.history || []).concat([hist('occurrence completed', w.number)]);
          planUpd.plan_detail = pd;
          return guardedSave(plan, 'plan_', planUpd);
        }).then(function () {
          if (!reset) return null;
          return readAttrs('DEVICE', w.equipment_id, ['pm_config']).then(function (a) {
            var pc = a.pm_config && typeof a.pm_config === 'object' ? a.pm_config : null;
            if (!pc || !pc.limits) throw {message: 'Work saved, but this equipment has no predictive-maintenance configuration to restart.'};
            pc.limits.service = pc.limits.service || {};
            pc.limits.service.last_service_run_hours = rh;
            if (plan && plan.strategy === 'meter' && Number(plan.interval_rh) > 0) pc.limits.service.interval_h = Number(plan.interval_rh);
            return saveAttrs('DEVICE', w.equipment_id, {pm_config: pc});
          });
        });
      }).then(function () { state.panel = {kind: 'wo', arg: w.id}; return reload(); }, fail);
    });
  }
  function partRow() { return '<tr><td><input class="p-n" maxlength="100"></td><td><input class="p-q" type="number" min="0" step="0.01"></td><td><input class="p-r" type="number" min="0" step="0.01"></td></tr>'; }

  function planForm(id) {
    var p = id ? byId(plans, id) : null, d = (p && p.detail) || {};
    var e0 = p ? p.equipment_id : state.equip;
    slot().innerHTML = '<div class="mp-panel"><h4>' + (p ? 'Edit plan ' + esc(p.number) : 'New maintenance plan') + '</h4><div class="mp-grid">' +
      '<label>Equipment <span class="req">*</span>' + equipSelect('f-eq', e0, false, false, !p) + '</label>' +
      '<label class="wide">Title <span class="req">*</span><input class="f-title" maxlength="120" value="' + esc(p ? p.title : '') + '"></label>' +
      '<label>Type <span class="req">*</span><select class="f-type">' + opts(typeNames('plan_allowed'), p ? p.type : '', !p) + '</select></label>' +
      '<label>Priority of raised WOs <span class="req">*</span><select class="f-pri">' + opts(priOpts(), p ? p.priority : '', !p) + '</select></label>' +
      '<label>Strategy <span class="req">*</span><select class="f-str"><option value=""></option><option value="time">Time-based (every N days)</option><option value="meter">Meter-based (every N ' + esc(unit()) + ')</option></select></label>' +
      '<label class="w-days">Interval (days) <span class="req">*</span><input type="number" class="f-days" min="1" step="1" value="' + esc(p && p.interval_days ? p.interval_days : '') + '"></label>' +
      '<label class="w-days">Next due date <span class="req">*</span><input type="date" class="f-date" value="' + esc(p ? (p.next_due_date || '') : '') + '"></label>' +
      '<label class="w-days">Raise WO days ahead <span class="req">*</span><input type="number" class="f-lead" min="0" step="1" value="' + esc(p && p.lead_days != null ? p.lead_days : '') + '"></label>' +
      '<label class="w-rh">Interval (' + esc(unit()) + ') <span class="req">*</span><input type="number" class="f-irh" min="1" step="any" value="' + esc(p && p.interval_rh ? p.interval_rh : '') + '"></label>' +
      '<label class="w-rh">Next due at (' + esc(unit()) + ') <span class="req">*</span><input type="number" class="f-nrh" min="0" step="0.1" value="' + esc(p && p.next_due_rh != null ? p.next_due_rh : '') + '"><span class="sub f-now"></span></label>' +
      '<label>Assigned to<input class="f-asg" maxlength="80" value="' + esc(d.assignee || '') + '"></label>' +
      '<label>Estimated hours<input type="number" class="f-est" min="0" step="0.25" value="' + esc(d.est_hours == null ? '' : d.est_hours) + '"></label>' +
      '<label class="wide">Checklist / task list (one step per line)<textarea class="f-cl" rows="4">' + esc((d.checklist || []).join('\n')) + '</textarea></label>' +
      '<div class="mp-field wide">Technical documents for this job<div class="mp-checks f-docs"></div></div>' +
      '<label class="wide">Safety / notes<input class="f-notes" maxlength="300" value="' + esc(d.notes || '') + '"></label>' +
      '</div><div class="mp-row"><button class="mp-btn" data-act="saveplan">' + (p ? 'Save changes' : 'Create plan') + '</button><button class="mp-btn light" data-act="close">Cancel</button><span class="mp-status"></span></div></div>';
    var s = slot();
    s.querySelector('.f-str').value = p ? p.strategy : '';
    if (p) s.querySelector('.f-eq').disabled = true;
    function sync() {
      var ee = eq(s.querySelector('.f-eq').value), str = s.querySelector('.f-str');
      str.querySelector('option[value="meter"]').disabled = !hasMeter(ee);
      if (!hasMeter(ee) && str.value === 'meter') str.value = '';
      var meter = str.value === 'meter', time = str.value === 'time';
      [].slice.call(s.querySelectorAll('.w-days')).forEach(function (x) { x.style.display = time ? '' : 'none'; });
      [].slice.call(s.querySelectorAll('.w-rh')).forEach(function (x) { x.style.display = meter ? '' : 'none'; });
      s.querySelector('.f-now').textContent = ee && ee.meter != null ? 'current reading: ' + ee.meter + ' ' + unit() : '';
      s.querySelector('.f-docs').innerHTML = ee ? docChecks(ee.id, d.docs) : '<span class="sub">Choose the equipment first.</span>';
    }
    s.querySelector('.f-eq').addEventListener('change', sync);
    s.querySelector('.f-str').addEventListener('change', sync);
    sync();
    s.querySelector('[data-act="saveplan"]').addEventListener('click', function () {
      var ee = eq(s.querySelector('.f-eq').value), title = s.querySelector('.f-title').value.trim(), str = s.querySelector('.f-str').value;
      var ty = s.querySelector('.f-type').value, pr = s.querySelector('.f-pri').value, meter = str === 'meter';
      var days = num(s.querySelector('.f-days').value), date = s.querySelector('.f-date').value, lead = num(s.querySelector('.f-lead').value);
      var irh = num(s.querySelector('.f-irh').value), nrh = num(s.querySelector('.f-nrh').value);
      if (!ee || !title || !ty || !pr || !str) { pstatus('Equipment, title, type, priority and strategy are required.', 'bad'); return; }
      if (meter ? !(irh > 0 && nrh != null) : !(days > 0 && date && lead != null)) { pstatus(meter ? 'Enter the interval and the next due meter reading.' : 'Enter the interval, the next due date and the lead days.', 'bad'); return; }
      var det = clone(d);
      det.assignee = s.querySelector('.f-asg').value.trim(); det.est_hours = num(s.querySelector('.f-est').value);
      det.checklist = lines(s.querySelector('.f-cl').value);
      det.docs = [].slice.call(s.querySelectorAll('.f-docs input:checked')).map(function (c) { return c.value; });
      det.notes = s.querySelector('.f-notes').value.trim();
      det.history = (det.history || []).concat([hist(p ? 'edited' : 'created', '')]);
      var v = {plan_title: title, plan_type: ty, plan_priority: pr, plan_strategy: str, plan_interval_days: meter ? null : days, plan_interval_rh: meter ? irh : null,
               plan_lead_days: meter ? null : lead, plan_next_due_date: meter ? null : date, plan_next_due_rh: meter ? nrh : null,
               plan_equipment_id: ee.id, plan_equipment_name: ee.name, plan_detail: det};
      busy(true); pstatus('Saving…');
      var go;
      if (p) go = guardedSave(p, 'plan_', v);
      else {
        v.plan_active = true; v.plan_rev = 1;
        go = createNumbered(PLAN_T, 'PL-', 4, title).then(function (a) { return saveAttrs('ASSET', a.id.id, v).then(function () { return relate(ee.id, a.id.id); }); });
      }
      go.then(function () { return done(p ? 'Plan saved.' : 'Plan created. Its work orders are raised automatically when due.'); }, fail);
    });
  }
  function raiseNow(p) {
    var d = p.detail || {}, meter = p.strategy === 'meter';
    return createWo({title: p.title, type: p.type, priority: p.priority, status: S.SCH, source: 'plan', plan_id: p.id, alarm_id: '',
                     equipment_id: p.equipment_id, equipment_name: p.equipment_name, due_date: meter ? '' : p.next_due_date, due_rh: meter ? p.next_due_rh : null,
                     interval_rh: meter ? p.interval_rh : null, assignee: d.assignee || '', created_ts: Date.now(), completed_ts: null, closed_ts: null, overdue_alerted: false,
                     detail: {description: d.notes || '', checklist: d.checklist || [], docs: d.docs || [], est_hours: d.est_hours, plan_number: p.number,
                              history: [hist('created', 'Raised from plan ' + p.number + ' ahead of schedule', null, S.SCH)]}});
  }

  function uploadForm() {
    slot().innerHTML = '<div class="mp-panel"><h4>Upload technical document</h4><div class="mp-grid">' +
      '<label>Equipment <span class="req">*</span>' + equipSelect('u-eq', state.equip, false, true, true) + '</label>' +
      '<label class="wide">Title <span class="req">*</span><input class="u-title" maxlength="120"></label>' +
      '<label>Category <span class="req">*</span><select class="u-cat">' + opts(cfg.doc_categories, '', true) + '</select></label>' +
      '<label>Document no.<input class="u-no" maxlength="40"></label>' +
      '<label>Revision<input class="u-rev" maxlength="20"></label>' +
      '<label>Valid until<input type="date" class="u-exp"><span class="sub">certificates, AMC, licences</span></label>' +
      '<label class="wide">File (max ' + esc(cfg.max_upload_mb) + ' MB) <span class="req">*</span><input type="file" class="u-file"></label>' +
      '</div><div class="mp-row"><button class="mp-btn" data-act="saveupload">Upload</button><button class="mp-btn light" data-act="close">Cancel</button><span class="mp-status"></span></div></div>';
    var p = slot();
    p.querySelector('[data-act="saveupload"]').addEventListener('click', function () {
      var file = p.querySelector('.u-file').files[0], target = p.querySelector('.u-eq').value, title = p.querySelector('.u-title').value.trim(), cat = p.querySelector('.u-cat').value;
      if (!file || !title || !target || !cat) { pstatus('Choose the equipment, a category and a file, and enter a title.', 'bad'); return; }
      busy(true); pstatus('Uploading…');
      uploadFile(file, title).then(function (meta) {
        meta.category = cat; meta.doc_no = p.querySelector('.u-no').value.trim() || null;
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
      '<table><tr><th>Work</th><td colspan="3"><b>' + esc(w.title) + '</b></td></tr><tr><th>Equipment</th><td>' + esc(w.equipment_name) + '</td><th>Type / priority</th><td>' + esc(w.type) + ' / ' + esc(priLabel(w.priority)) + '</td></tr>' +
      '<tr><th>Status</th><td>' + esc(w.status) + '</td><th>Due</th><td>' + esc(dueText(w)) + '</td></tr><tr><th>Assigned to</th><td>' + esc(w.assignee || '') + '</td><th>Estimated hours</th><td>' + esc(d.est_hours == null ? '' : d.est_hours) + '</td></tr>' +
      '<tr><th>Description</th><td colspan="3">' + esc(d.description || '') + '</td></tr>' +
      '<tr><th>Documents</th><td colspan="3">' + (d.docs || []).map(function (id) { var x = findDoc(id); return x ? esc(x.d.title) + (x.d.revision ? ' rev ' + esc(x.d.revision) : '') : ''; }).filter(Boolean).join('; ') + '</td></tr></table>' +
      (cl ? '<table><tr><th colspan="3">Checklist</th></tr>' + cl + '</table>' : '') +
      '<table><tr><th>Work done</th><td colspan="3" style="height:60px">' + esc(d.work_done || '') + '</td></tr><tr><th>Meter (' + esc(unit()) + ')</th><td>' + esc(d.done_rh == null ? '' : d.done_rh) + '</td><th>Labour / downtime h</th><td>' + esc(d.labour_hours == null ? '' : d.labour_hours) + ' / ' + esc(d.downtime_hours == null ? '' : d.downtime_hours) + '</td></tr>' +
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
    if (t.getAttribute('data-tab')) { state.tab = t.getAttribute('data-tab'); state.panel = null; render(); return; }
    if (t.getAttribute('data-filter')) { state.woFilter = t.getAttribute('data-filter'); render(); return; }
    var act = t.getAttribute('data-act');
    if (!act && t.getAttribute('data-doc')) { download(t.getAttribute('data-doc')); return; }
    var cur = state.panel && state.panel.kind === 'wo' ? byId(wos, state.panel.arg) : null;
    if (act === 'close') closePanel();
    else if (act === 'back') { if (state.panel && state.panel.arg) openPanel('wo', state.panel.arg.id || state.panel.arg); else closePanel(); }
    else if (act === 'viewwo') openPanel('wo', t.getAttribute('data-id'));
    else if (act === 'newwo') openPanel('newwo', null);
    else if (act === 'newplan') openPanel('plan', null);
    else if (act === 'editplan') openPanel('plan', t.getAttribute('data-id'));
    else if (act === 'upload') openPanel('upload');
    else if (act === 'delrow') { var tr = t.closest('tr'); if (tr) tr.remove(); }
    else if (act === 'addpri') { var tb = root.querySelector('.s-pri tbody'); var x = document.createElement('tbody'); x.innerHTML = priRow({code: '', label: '', response_days: ''}); tb.appendChild(x.firstChild); }
    else if (act === 'addtype') { var tb2 = root.querySelector('.s-types tbody'); var y = document.createElement('tbody'); y.innerHTML = typeRow({name: ''}); tb2.appendChild(y.firstChild); }
    else if (act === 'savesettings') {
      var box = root.querySelector('.s-st1').parentNode.parentNode;
      var r = collectSettings();
      if (r.errs.length) { pstatus('Please complete: ' + r.errs.join(', ') + '.', 'bad', box); return; }
      t.disabled = true; pstatus('Saving…', '', box);
      readAttrs('ASSET', settingsId, ['cmms_settings_rev']).then(function (a) {
        if (a.cmms_settings_rev != null && cfgRev != null && Number(a.cmms_settings_rev) !== Number(cfgRev)) throw {message: 'The settings were changed by someone else meanwhile; reload the page.'};
        return saveAttrs('ASSET', settingsId, {cmms_settings: r.cfg, cmms_settings_rev: Number(a.cmms_settings_rev || 0) + 1});
      }).then(function () { return reload(); }).then(function () { flash('Maintenance settings saved.'); }, function (e) { t.disabled = false; pstatus('Not saved: ' + errText(e), 'bad', box); });
    } else if (act === 'savepm') {
      var e = eq(t.getAttribute('data-id')), box2 = t.parentNode.parentNode;
      var form = root.querySelector('.s-pmform');
      var all = root.querySelector('.s-pmall').checked;
      t.disabled = true; pstatus('Saving…', '', box2);
      readAttrs('DEVICE', e.id, ['pm_config']).then(function (a) {
        var pc = a.pm_config && typeof a.pm_config === 'object' ? a.pm_config : {};
        var edited = {engine: clone(pc.engine || {}), limits: clone(pc.limits || {})};
        [].slice.call(form.querySelectorAll('[data-path]')).forEach(function (el) { setPath(edited, el.getAttribute('data-path'), readField(el)); });
        pc.engine = edited.engine; pc.limits = edited.limits;
        var jobs = [saveAttrs('DEVICE', e.id, {pm_config: pc})];
        if (all) {
          equipment.filter(function (o) { return o.id !== e.id && o.pm && o.pm.kind; }).forEach(function (o) {
            jobs.push(readAttrs('DEVICE', o.id, ['pm_config']).then(function (b) { var oc = b.pm_config; oc.engine = clone(edited.engine); return saveAttrs('DEVICE', o.id, {pm_config: oc}); }));
          });
        }
        return Promise.all(jobs);
      }).then(function () { return reload(); }).then(function () { flash('Predictive-maintenance settings saved; they apply from the next evaluation (within 5 minutes).'); },
        function (err) { t.disabled = false; pstatus('Not saved: ' + errText(err), 'bad', box2); });
    } else if (act === 'pmtemplate') {
      var ne = eq(t.getAttribute('data-id')), kindName = templates.profiles[ne.type];
      if (!window.confirm('Configure predictive maintenance of ' + ne.name + ' from the ' + kindName + ' template? Check its values afterwards.')) return;
      t.disabled = true;
      readAttrs('DEVICE', ne.id, ['pm_config']).then(function (a) {
        var pc = a.pm_config && typeof a.pm_config === 'object' ? a.pm_config : {};
        pc.kind = kindName; pc.engine = clone(templates.engine); pc.limits = clone(templates.kinds[kindName]);
        return saveAttrs('DEVICE', ne.id, {pm_config: pc});
      }).then(function () { state.pmEquip = ne.id; return reload(); }, function (err) { t.disabled = false; window.alert('Not saved: ' + errText(err)); });
    }
    else if (cur && act === 'editwo') openPanel('editwo', {id: cur.id});
    else if (cur && act === 'complete') openPanel('complete', cur.id);
    else if (cur && (act === 'hold' || act === 'cancel' || act === 'reject')) openPanel('reason', {id: cur.id, kind: act});
    else if (cur && act === 'print') printWo(cur);
    else if (cur && act === 'start') {
      busy(true);
      transition(cur, S.PRG, cur.status === S.HLD ? 'resumed' : 'started', '', function (v, d) { d.hold_reason = null; if (!d.started_ts) d.started_ts = Date.now(); })
        .then(function () { return reload(); }, fail);
    } else if (cur && act === 'verify') {
      if (cfg.verification.different_user && ((cur.detail || {}).completed_by || {}).user === me.user) { pstatus('Another user must verify your work.', 'bad'); return; }
      busy(true);
      transition(cur, S.CLS, 'verified and closed', '', function (v, d) { v.wo_closed_ts = Date.now(); d.verified_by = {user: me.user, name: me.name, ts: Date.now()}; })
        .then(function () { return reload(); }, fail);
    } else if (act === 'toggleplan') {
      var p = byId(plans, t.getAttribute('data-id'));
      var pd = clone(p.detail || {});
      pd.history = (pd.history || []).concat([hist(p.active === false ? 'resumed' : 'paused', '')]);
      guardedSave(p, 'plan_', {plan_active: p.active === false, plan_detail: pd}).then(reload, function (e2) { window.alert(errText(e2)); });
    } else if (act === 'raisenow') {
      var pl = byId(plans, t.getAttribute('data-id'));
      if (wos.some(function (w) { return w.plan_id === pl.id && ACTIVE.indexOf(w.status) >= 0; })) { window.alert('This plan already has an active work order.'); return; }
      t.disabled = true;
      raiseNow(pl).then(function (r2) { state.tab = 'wo'; state.panel = {kind: 'wo', arg: r2.id}; return reload(); }, function (e3) { t.disabled = false; window.alert('Not created: ' + errText(e3)); });
    } else if (act === 'deldoc') {
      var owner = t.getAttribute('data-o'), did = t.getAttribute('data-d'), xd = findDoc(did);
      var users = plans.filter(function (pp) { return ((pp.detail || {}).docs || []).indexOf(did) >= 0; }).map(function (pp) { return pp.number; });
      if (!xd || !window.confirm('Delete "' + xd.d.title + '"?' + (users.length ? ' It is linked to ' + users.join(', ') + '.' : '') + ' Work orders keep a reference to its title only.')) return;
      var tt = owner === 'general' ? 'ASSET' : 'DEVICE', oid = owner === 'general' ? general.id : owner;
      req(http.delete('/api/resource/' + did)).catch(function () { return null; }).then(function () {
        return readAttrs(tt, oid, ['maint_docs']).then(function (a) { return saveAttrs(tt, oid, {maint_docs: (a.maint_docs || []).filter(function (dd) { return dd.id !== did; })}); });
      }).then(function () {
        return Promise.all(plans.filter(function (pp) { return ((pp.detail || {}).docs || []).indexOf(did) >= 0; }).map(function (pp) {
          var pd2 = clone(pp.detail); pd2.docs = pd2.docs.filter(function (z) { return z !== did; });
          return guardedSave(pp, 'plan_', {plan_detail: pd2});
        }));
      }).then(reload, function (e4) { window.alert('Delete failed: ' + errText(e4)); });
    }
  });

  self._mpTimer = setInterval(function () { if (!state.panel && state.tab !== 'settings') reload(); }, 120000);   // scheduler / other users' changes, live meters
  root.innerHTML = '<div class="mp"><div class="mp-empty">Loading maintenance data…</div></div>';
  loadAll().then(render);
};

self.onDataUpdated = function () {};
self.typeParameters = function () { return {dataKeysOptional: true, singleEntity: false, hasDataPageLink: false}; };
self.onDestroy = function () { if (self._mpTimer) clearInterval(self._mpTimer); };
