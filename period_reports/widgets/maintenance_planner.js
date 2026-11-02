// ThingsBoard latest-values widget "Maintenance Planner": maintenance job schedule, technical documents and work done.
//  - Jobs:      server attribute maint_jobs (JSON list) on each equipment device.
//  - Documents: files stored as ThingsBoard GENERAL resources; their list is the server attribute maint_docs on the
//               equipment (or on the asset "Maintenance Document Library" for documents that apply to all equipment).
//  - Work done: completing a job writes telemetry maintenance_record (same format as the Maintenance Log widget, so it
//               shows in the log and in the period reports), advances recurring jobs and, for a DG preventive service,
//               restarts the predictive-maintenance service countdown (pm_config.last_service_run_hours).
// Datasource: alias of all monitored equipment, data key run_hours (current run hours of the DG sets).
self.onInit = function () {
  var root = self.ctx.$container[0];
  var http = self.ctx.http;
  var DG_TYPE = 'woodward_kg1500';
  var TYPES = ['Preventive service', 'Inspection', 'Test run', 'Calibration', 'Cleaning', 'Part replacement',
               'Corrective repair', 'Statutory check', 'Other'];
  var CATS = ['Manual', 'SOP / Procedure', 'Checklist', 'Drawing / Diagram', 'Warranty / AMC', 'Certificate',
              'Service report', 'Photo', 'Other'];
  var SOON_DAYS = 7;
  var equipment = [];          // {id, name, type, runHours, jobs: [], docs: []}
  var LIBRARY = 'Maintenance Document Library';
  var general = {docs: [], id: null};   // asset holding the documents that apply to all equipment
  var claims = jwt();
  var state = {tab: 'schedule', filter: 'open', equip: '', panel: null};

  // ---------------------------------------------------------------- helpers
  function jwt() {
    try {
      return JSON.parse(atob(window.localStorage.getItem('jwt_token').split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    } catch (e) { return {}; }
  }
  function userName() { return ((claims.firstName || '') + ' ' + (claims.lastName || '')).trim() || claims.sub || ''; }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function uid() { return 'j' + Date.now().toString(36) + Math.floor(Math.random() * 1e6).toString(36); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function ymd(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function today() { return ymd(new Date()); }
  function parseYmd(s) { var p = String(s || '').split('-'); return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2])); }
  function addDays(s, n) { var d = parseYmd(s); d.setDate(d.getDate() + n); return ymd(d); }
  function diffDays(a, b) { return Math.round((parseYmd(a) - parseYmd(b)) / 86400000); }
  function fmtDate(s) { return s ? parseYmd(s).toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'}) : ''; }
  function fmtTs(ts) {
    var d = new Date(ts);
    return d.toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'}) + ' ' +
      d.toLocaleTimeString('en-GB', {hour: '2-digit', minute: '2-digit'});
  }
  function localNow() { var d = new Date(Date.now() - new Date().getTimezoneOffset() * 60000); return d.toISOString().slice(0, 16); }
  function size(n) { return n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'; }
  function r1(x) { return Math.round(x * 10) / 10; }
  function errText(e) { return (e && e.error && e.error.message) || (e && e.message) || (e && e.status) || 'error'; }
  function req(obs) { return new Promise(function (res, rej) { obs.subscribe(res, rej); }); }
  function byId(id) { for (var i = 0; i < equipment.length; i++) { if (equipment[i].id === id) return equipment[i]; } return null; }
  function isDg(e) { return e && e.type === DG_TYPE; }
  function parseAttr(list, key, d) {
    var out = d;
    (list || []).forEach(function (a) {
      if (a.key === key) { try { out = typeof a.value === 'string' ? JSON.parse(a.value) : a.value; } catch (x) { out = d; } }
    });
    return out;
  }
  function attrUrl(target) {
    return target === 'general' ? '/api/plugins/telemetry/ASSET/' + general.id : '/api/plugins/telemetry/DEVICE/' + target;
  }
  function readAttr(target, key) {
    return req(http.get(attrUrl(target) + '/values/attributes/SERVER_SCOPE?keys=' + key)).then(function (l) { return parseAttr(l, key, []); });
  }
  // read-modify-write so two people editing at once do not overwrite each other's entries
  function updateAttr(target, key, fn) {
    return readAttr(target, key).then(function (cur) {
      var next = fn(Array.isArray(cur) ? cur : []);
      var body = {}; body[key] = JSON.stringify(next);
      return req(http.post(attrUrl(target) + '/attributes/SERVER_SCOPE', body)).then(function () { return next; });
    });
  }
  function allDocs() {
    var out = general.docs.map(function (d) { return {d: d, owner: 'general', ownerName: 'All equipment'}; });
    equipment.forEach(function (e) { e.docs.forEach(function (d) { out.push({d: d, owner: e.id, ownerName: e.name}); }); });
    return out;
  }
  function findDoc(id) { var l = allDocs(); for (var i = 0; i < l.length; i++) { if (l[i].d.id === id) return l[i]; } return null; }

  // ---------------------------------------------------------------- status of a job
  function jobStatus(j, e) {
    if (j.active === false) return {k: 'done', t: 'Completed' + (j.last_done_ts ? ' ' + fmtTs(j.last_done_ts).slice(0, 11) : ''), s: 9e9};
    if (j.kind === 'run_hours') {
      var rh = e && e.runHours;
      if (rh == null || j.next_rh == null) return {k: 'unknown', t: 'Run hours not available', s: 5e8};
      var left = r1(j.next_rh - rh), win = Math.max(10, (Number(j.every) || 0) * 0.1);
      if (left < 0) return {k: 'overdue', t: 'Overdue by ' + r1(-left) + ' run-h', s: left};
      if (left <= win) return {k: 'due', t: 'Due in ' + left + ' run-h', s: 1e6 + left};
      return {k: 'upcoming', t: 'In ' + left + ' run-h', s: 2e6 + left};
    }
    var d = diffDays(j.next_date, today());
    if (!isFinite(d)) return {k: 'unknown', t: 'No due date', s: 5e8};
    if (d < 0) return {k: 'overdue', t: 'Overdue by ' + (-d) + ' day' + (d === -1 ? '' : 's'), s: d};
    if (d <= SOON_DAYS) return {k: 'due', t: d === 0 ? 'Due today' : 'Due in ' + d + ' day' + (d === 1 ? '' : 's'), s: 1e6 + d};
    return {k: 'upcoming', t: 'In ' + d + ' days', s: 2e6 + d};
  }
  function scheduleText(j) {
    if (j.kind === 'days') return 'Every ' + j.every + ' day' + (Number(j.every) === 1 ? '' : 's');
    if (j.kind === 'run_hours') return 'Every ' + j.every + ' run-h';
    return 'One-time';
  }
  function dueText(j) {
    if (j.active === false) return '';
    if (j.kind === 'run_hours') return j.next_rh == null ? '' : 'at ' + j.next_rh + ' run-h';
    return fmtDate(j.next_date);
  }

  // ---------------------------------------------------------------- loading
  function loadEquipment() {
    var seen = {};
    equipment = [];
    (self.ctx.datasources || []).forEach(function (ds) {
      if (!ds.entityId || seen[ds.entityId]) return;
      seen[ds.entityId] = true;
      equipment.push({id: ds.entityId, name: ds.entityName, type: null, runHours: null, jobs: [], docs: []});
    });
    equipment.sort(function (a, b) { return a.name.localeCompare(b.name); });
    var lib = req(http.get('/api/tenant/assets?assetName=' + encodeURIComponent(LIBRARY))).then(function (a) { general.id = a && a.id ? a.id.id : null; }, function () { general.id = null; });
    return Promise.all(equipment.map(function (e) {
      return req(http.get('/api/device/' + e.id)).then(function (d) { e.type = d.type; }, function () {});
    }).concat([lib]));
  }
  function updateRunHours() {
    (self.ctx.data || []).forEach(function (d) {
      var id = d.datasource && d.datasource.entityId;
      var v = d.data && d.data.length ? Number(d.data[d.data.length - 1][1]) : NaN;
      var e = byId(id);
      if (e && isFinite(v) && v >= 0 && v < 30000) e.runHours = r1(v);
    });
  }
  function loadData() {
    var jobs = equipment.map(function (e) {
      return req(http.get('/api/plugins/telemetry/DEVICE/' + e.id + '/values/attributes/SERVER_SCOPE?keys=maint_jobs,maint_docs'))
        .then(function (l) { e.jobs = parseAttr(l, 'maint_jobs', []); e.docs = parseAttr(l, 'maint_docs', []); }, function () {});
    });
    if (general.id) jobs.push(readAttr('general', 'maint_docs').then(function (d) { general.docs = d; }, function () { general.docs = []; }));
    return Promise.all(jobs);
  }
  function reload() { return loadData().then(render); }

  // ---------------------------------------------------------------- documents
  function download(id) {
    var x = findDoc(id);
    var name = (x && (x.d.file || x.d.title)) || 'document';
    http.get('/api/resource/' + id + '/download', {responseType: 'blob'}).subscribe(function (blob) {
      var url = URL.createObjectURL(blob), a = document.createElement('a');
      a.href = url; a.download = name; document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1000);
    }, function (e) { window.alert('Download failed: ' + errText(e)); });
  }
  function uploadFile(file, title) {
    var fd = new FormData();
    fd.append('file', file, file.name);
    fd.append('resourceType', 'GENERAL');
    fd.append('title', title || file.name);
    return req(http.post('/api/resource/upload', fd)).then(function (r) {
      return {id: r.id.id, title: title || file.name, file: file.name, size: file.size, uploaded_by: userName(), uploaded_at: Date.now()};
    });
  }
  function docLinks(ids) {
    return (ids || []).map(function (id) {
      var x = findDoc(id);
      return x ? '<span class="doc" data-doc="' + esc(id) + '" title="Download">&#128196; ' + esc(x.d.title) + '</span>' : '';
    }).join('');
  }

  // ---------------------------------------------------------------- rendering
  function counts() {
    var c = {overdue: 0, due: 0, upcoming: 0, done: 0, unknown: 0};
    equipment.forEach(function (e) { e.jobs.forEach(function (j) { c[jobStatus(j, e).k]++; }); });
    return c;
  }
  function render() {
    var c = counts();
    var chips = [['open', 'all', 'Open jobs: ' + (c.overdue + c.due + c.upcoming + c.unknown)], ['overdue', 'overdue', 'Overdue: ' + c.overdue],
                 ['due', 'due', 'Due within ' + SOON_DAYS + ' days: ' + c.due], ['upcoming', 'upcoming', 'Upcoming: ' + c.upcoming],
                 ['done', 'done', 'Completed: ' + c.done]];
    var html = '<div class="mp">' +
      '<div class="mp-tabs"><button class="mp-tab' + (state.tab === 'schedule' ? ' on' : '') + '" data-tab="schedule">Job schedule</button>' +
      '<button class="mp-tab' + (state.tab === 'docs' ? ' on' : '') + '" data-tab="docs">Technical documents</button></div>';
    if (state.tab === 'schedule') {
      html += '<div class="mp-top">' + chips.map(function (x) {
        return '<span class="mp-chip ' + x[1] + (state.filter === x[0] ? ' active' : '') + '" data-filter="' + x[0] + '">' + x[2] + '</span>';
      }).join('') + '<span class="mp-sp"></span>' + equipSelect('mp-eqf', state.equip, true) +
        '<button class="mp-btn" data-act="new">+ New job</button></div>';
      html += '<div class="mp-panel-slot"></div>' + jobsTable();
    } else {
      html += '<div class="mp-top"><span class="mp-note">Manuals, SOPs, checklists, drawings and certificates, stored in ThingsBoard and linked to jobs.</span>' +
        '<span class="mp-sp"></span>' + equipSelect('mp-eqf', state.equip, true) + '<button class="mp-btn" data-act="upload">+ Upload document</button></div>' +
        '<div class="mp-panel-slot"></div>' + docsTable();
    }
    root.innerHTML = html + '</div>';
    bind();
    if (state.panel) openPanel(state.panel.kind, state.panel.arg, true);
  }
  function equipSelect(cls, val, withAll, withGeneral) {
    var o = (withAll ? '<option value="">All equipment</option>' : '') +
      (withGeneral && general.id ? '<option value="general"' + (val === 'general' ? ' selected' : '') + '>All equipment (general document)</option>' : '');
    equipment.forEach(function (e) { o += '<option value="' + e.id + '"' + (val === e.id ? ' selected' : '') + '>' + esc(e.name) + '</option>'; });
    return '<select class="' + cls + '">' + o + '</select>';
  }
  function jobsTable() {
    var rows = [];
    equipment.forEach(function (e) {
      if (state.equip && state.equip !== e.id) return;
      e.jobs.forEach(function (j) {
        var st = jobStatus(j, e);
        var show = state.filter === 'open' ? st.k !== 'done' : st.k === state.filter;
        if (show) rows.push({e: e, j: j, st: st});
      });
    });
    rows.sort(function (a, b) { return a.st.s - b.st.s; });
    if (!rows.length) {
      return '<div class="mp-empty">' + (state.filter === 'open' ? 'No open maintenance jobs. Use "+ New job" to plan preventive maintenance, inspections and tests.' : 'No jobs in this view.') + '</div>';
    }
    return '<table><thead><tr><th>Status</th><th>Job</th><th>Equipment</th><th>Schedule</th><th>Next due</th><th>Assigned to</th>' +
      '<th>Documents</th><th>Last done</th><th></th></tr></thead><tbody>' + rows.map(function (r) {
        var j = r.j;
        var cl = (j.checklist || []).length;
        return '<tr><td class="nw"><span class="pill ' + r.st.k + '">' + esc(r.st.t) + '</span></td>' +
          '<td><b>' + esc(j.title) + '</b><div class="sub"><span class="tag">' + esc(j.type) + '</span>' + (cl ? ' &middot; ' + cl + ' checklist item' + (cl === 1 ? '' : 's') : '') +
          (j.notes ? ' &middot; ' + esc(j.notes) : '') + '</div></td>' +
          '<td class="nw">' + esc(r.e.name) + (isDg(r.e) && r.e.runHours != null ? '<div class="sub">now ' + r.e.runHours + ' run-h</div>' : '') + '</td>' +
          '<td class="nw">' + scheduleText(j) + '</td><td class="nw">' + esc(dueText(j)) + '</td><td>' + esc(j.assignee) + '</td>' +
          '<td>' + (docLinks(j.docs) || '<span class="sub">none</span>') + '</td>' +
          '<td class="nw">' + (j.last_done_ts ? fmtTs(j.last_done_ts) + (j.last_done_by ? '<div class="sub">' + esc(j.last_done_by) + '</div>' : '') : '<span class="sub">never</span>') + '</td>' +
          '<td><div class="acts">' + (j.active === false ? '' : '<button class="mp-btn small ok" data-act="complete" data-e="' + r.e.id + '" data-j="' + j.id + '">Complete</button>') +
          '<button class="mp-btn small light" data-act="edit" data-e="' + r.e.id + '" data-j="' + j.id + '">Edit</button>' +
          '<button class="mp-btn small danger" data-act="deljob" data-e="' + r.e.id + '" data-j="' + j.id + '" title="Delete job">&times;</button></div></td></tr>';
      }).join('') + '</tbody></table>';
  }
  function docsTable() {
    var list = allDocs().filter(function (x) { return !state.equip || x.owner === state.equip || x.owner === 'general'; });
    list.sort(function (a, b) { return (b.d.uploaded_at || 0) - (a.d.uploaded_at || 0); });
    if (!list.length) return '<div class="mp-empty">No documents yet. Upload manuals, SOPs and checklists so technicians have them with each job.</div>';
    return '<table><thead><tr><th>Document</th><th>Category</th><th>Equipment</th><th>File</th><th>Uploaded</th><th>Used by jobs</th><th></th></tr></thead><tbody>' +
      list.map(function (x) {
        var used = [];
        equipment.forEach(function (e) { e.jobs.forEach(function (j) { if ((j.docs || []).indexOf(x.d.id) >= 0) used.push(j.title + ' (' + e.name + ')'); }); });
        return '<tr><td><span class="doc" data-doc="' + esc(x.d.id) + '">&#128196; ' + esc(x.d.title) + '</span></td><td><span class="tag">' + esc(x.d.category || 'Other') + '</span></td>' +
          '<td class="nw">' + esc(x.ownerName) + '</td><td class="nw">' + esc(x.d.file) + '<div class="sub">' + (x.d.size ? size(x.d.size) : '') + '</div></td>' +
          '<td class="nw">' + (x.d.uploaded_at ? fmtTs(x.d.uploaded_at) : '') + '<div class="sub">' + esc(x.d.uploaded_by) + '</div></td>' +
          '<td>' + (used.length ? esc(used.join(', ')) : '<span class="sub">-</span>') + '</td>' +
          '<td><div class="acts"><button class="mp-btn small light" data-doc="' + esc(x.d.id) + '">Download</button>' +
          '<button class="mp-btn small danger" data-act="deldoc" data-o="' + esc(x.owner) + '" data-d="' + esc(x.d.id) + '" title="Delete document">&times;</button></div></td></tr>';
      }).join('') + '</tbody></table>';
  }

  // ---------------------------------------------------------------- panels (forms)
  function slot() { return root.querySelector('.mp-panel-slot'); }
  function closePanel() { state.panel = null; slot().innerHTML = ''; }
  function openPanel(kind, arg, keep) {
    state.panel = {kind: kind, arg: arg};
    if (kind === 'job') jobForm(arg);
    if (kind === 'complete') completeForm(arg);
    if (kind === 'upload') uploadForm();
    if (!keep) slot().scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }
  function pstatus(t, k) { var s = slot().querySelector('.mp-status'); if (s) { s.textContent = t || ''; s.className = 'mp-status ' + (k || ''); } }

  function jobForm(arg) {
    var e = arg && byId(arg.e), j = null;
    if (e && arg.j) e.jobs.forEach(function (x) { if (x.id === arg.j) j = x; });
    j = j || {kind: 'days', every: 30, type: 'Preventive service', next_date: addDays(today(), 30), checklist: [], docs: []};
    var eq = e ? e.id : (state.equip || (equipment[0] && equipment[0].id));
    slot().innerHTML = '<div class="mp-panel"><h4>' + (j.id ? 'Edit maintenance job' : 'New maintenance job') + '</h4><div class="mp-grid">' +
      '<label>Equipment' + equipSelect('f-eq', eq, false) + '</label>' +
      '<label class="wide">Job title<input class="f-title" maxlength="120" value="' + esc(j.title) + '" placeholder="e.g. 250 h service - engine oil, oil and fuel filters"></label>' +
      '<label>Type<select class="f-type">' + TYPES.map(function (t) { return '<option' + (t === j.type ? ' selected' : '') + '>' + t + '</option>'; }).join('') + '</select></label>' +
      '<label>Repeats<select class="f-kind"><option value="once">One-time</option><option value="days">Every N days</option><option value="run_hours">Every N run-hours (DG)</option></select></label>' +
      '<label class="w-every">Interval<input type="number" class="f-every" min="1" step="1" value="' + esc(j.every || '') + '"></label>' +
      '<label class="w-date">Next due date<input type="date" class="f-date" value="' + esc(j.next_date || '') + '"></label>' +
      '<label class="w-rh">Next due at run-hours<input type="number" class="f-rh" min="0" step="0.1" value="' + esc(j.next_rh == null ? '' : j.next_rh) + '"></label>' +
      '<label>Assigned to<input class="f-asg" maxlength="80" value="' + esc(j.assignee) + '" placeholder="Technician / vendor"></label>' +
      '<label class="wide">Checklist (one step per line)<textarea class="f-cl" rows="4" placeholder="Drain and refill engine oil&#10;Replace oil filter&#10;Check coolant level">' + esc((j.checklist || []).join('\n')) + '</textarea></label>' +
      '<div class="mp-field wide">Technical documents for this job<div class="mp-checks f-docs"></div></div>' +
      '<label class="wide">Notes<input class="f-notes" maxlength="300" value="' + esc(j.notes) + '" placeholder="Optional: safety notes, spares to keep ready"></label>' +
      '</div><div class="mp-row"><button class="mp-btn" data-act="savejob">' + (j.id ? 'Save changes' : 'Create job') + '</button>' +
      '<button class="mp-btn light" data-act="close">Cancel</button><span class="mp-status"></span></div></div>';
    var p = slot();
    p.querySelector('.f-kind').value = j.kind || 'days';
    function sync() {
      var ee = byId(p.querySelector('.f-eq').value), kind = p.querySelector('.f-kind').value;
      var rhOpt = p.querySelector('.f-kind option[value="run_hours"]');
      rhOpt.disabled = !isDg(ee);
      if (!isDg(ee) && kind === 'run_hours') { p.querySelector('.f-kind').value = kind = 'days'; }
      p.querySelector('.w-every').style.display = kind === 'once' ? 'none' : '';
      p.querySelector('.w-date').style.display = kind === 'run_hours' ? 'none' : '';
      p.querySelector('.w-rh').style.display = kind === 'run_hours' ? '' : 'none';
      if (kind === 'run_hours' && !p.querySelector('.f-rh').value && ee && ee.runHours != null) {
        p.querySelector('.f-rh').value = r1(ee.runHours + (Number(p.querySelector('.f-every').value) || 250));
      }
      var avail = general.docs.map(function (d) { return {d: d, o: 'All equipment'}; }).concat((ee ? ee.docs : []).map(function (d) { return {d: d, o: ee.name}; }));
      p.querySelector('.f-docs').innerHTML = avail.length ? avail.map(function (x) {
        return '<label><input type="checkbox" value="' + esc(x.d.id) + '"' + ((j.docs || []).indexOf(x.d.id) >= 0 ? ' checked' : '') + '> ' +
          esc(x.d.title) + ' <span class="sub">(' + esc(x.d.category || 'Other') + ', ' + esc(x.o) + ')</span></label>';
      }).join('') : '<span class="sub">No documents for this equipment yet - upload them in "Technical documents".</span>';
    }
    p.querySelector('.f-eq').addEventListener('change', sync);
    p.querySelector('.f-kind').addEventListener('change', sync);
    sync();
    p.querySelector('[data-act="savejob"]').addEventListener('click', function () {
      var ee = byId(p.querySelector('.f-eq').value), kind = p.querySelector('.f-kind').value;
      var title = p.querySelector('.f-title').value.trim(), every = Number(p.querySelector('.f-every').value);
      var date = p.querySelector('.f-date').value, rh = p.querySelector('.f-rh').value === '' ? null : Number(p.querySelector('.f-rh').value);
      if (!ee || !title) { pstatus('Enter the equipment and a job title.', 'bad'); return; }
      if (kind !== 'once' && !(every > 0)) { pstatus('Enter how often the job repeats.', 'bad'); return; }
      if (kind === 'run_hours' && rh == null) { pstatus('Enter the run-hours at which the job is next due.', 'bad'); return; }
      if (kind !== 'run_hours' && !date) { pstatus('Enter the next due date.', 'bad'); return; }
      var job = {id: j.id || uid(), title: title, type: p.querySelector('.f-type').value, kind: kind, every: kind === 'once' ? null : every,
                 next_date: kind === 'run_hours' ? null : date, next_rh: kind === 'run_hours' ? rh : null,
                 assignee: p.querySelector('.f-asg').value.trim(),
                 checklist: p.querySelector('.f-cl').value.split('\n').map(function (s) { return s.trim(); }).filter(Boolean),
                 docs: [].slice.call(p.querySelectorAll('.f-docs input:checked')).map(function (c) { return c.value; }),
                 notes: p.querySelector('.f-notes').value.trim(), active: true,
                 created_by: j.created_by || userName(), created_at: j.created_at || Date.now(), updated_by: userName(), updated_at: Date.now(),
                 last_done_ts: j.last_done_ts || null, last_done_by: j.last_done_by || null, last_done_rh: j.last_done_rh == null ? null : j.last_done_rh};
      pstatus('Saving…');
      var moved = e && e.id !== ee.id;
      var save = updateAttr(ee.id, 'maint_jobs', function (list) {
        return list.filter(function (x) { return x.id !== job.id; }).concat([job]);
      });
      if (moved) save = save.then(function () { return updateAttr(e.id, 'maint_jobs', function (l) { return l.filter(function (x) { return x.id !== job.id; }); }); });
      save.then(function () { state.panel = null; return reload(); }, function (err) { pstatus('Could not save: ' + errText(err), 'bad'); });
    });
  }

  function completeForm(arg) {
    var e = byId(arg.e), j = null;
    e.jobs.forEach(function (x) { if (x.id === arg.j) j = x; });
    if (!j) return;
    var dg = isDg(e);
    var svc = dg && j.type === 'Preventive service';
    slot().innerHTML = '<div class="mp-panel"><h4>Record work done: ' + esc(j.title) + ' &middot; ' + esc(e.name) + '</h4>' +
      ((j.docs || []).length ? '<div class="mp-note" style="margin-bottom:8px">Documents: ' + docLinks(j.docs) + '</div>' : '') +
      '<div class="mp-grid">' +
      ((j.checklist || []).length ? '<div class="mp-field wide">Checklist<div class="mp-checks c-cl">' + j.checklist.map(function (s, i) {
        return '<label><input type="checkbox" data-i="' + i + '"> ' + esc(s) + '</label>';
      }).join('') + '</div></div>' : '') +
      '<label>Date &amp; time of work<input type="datetime-local" class="c-when" value="' + localNow() + '" max="' + localNow() + '"></label>' +
      '<label>Technician<input class="c-tech" maxlength="80" value="' + esc(j.assignee) + '"></label>' +
      '<label>Run hours at work<input type="number" class="c-rh" step="0.1" min="0"' + (dg ? ' value="' + esc(e.runHours == null ? '' : e.runHours) + '"' : ' disabled placeholder="DG only"') + '></label>' +
      '<label class="wide">Work done<textarea class="c-desc" rows="3" maxlength="600" placeholder="What was done, findings, readings"></textarea></label>' +
      '<label>Parts used<input class="c-parts" maxlength="200" placeholder="Optional"></label>' +
      '<label>Cost (INR)<input type="number" class="c-cost" min="0" step="1" placeholder="Optional"></label>' +
      '<label>Attach job card / photos<input type="file" class="c-files" multiple></label>' +
      (svc ? '<label class="wide mp-hl" style="flex-direction:row;align-items:center;gap:8px;text-transform:none;font-size:13px;font-weight:500;letter-spacing:0">' +
        '<input type="checkbox" class="c-reset" checked> Scheduled service: restart the DG service countdown from these run hours' +
        (j.kind === 'run_hours' ? ' (interval ' + j.every + ' run-h)' : '') + '</label>' : '') +
      '</div><div class="mp-note" style="margin-top:8px">' +
      (j.kind === 'once' ? 'This one-time job will be marked completed.' : 'Next due: ' + (j.kind === 'days' ? j.every + ' days after the work date' : j.every + ' run-hours after the run hours entered') + '.') +
      '</div><div class="mp-row"><button class="mp-btn ok" data-act="savedone">Save work done</button>' +
      '<button class="mp-btn light" data-act="close">Cancel</button><span class="mp-status"></span></div></div>';
    var p = slot();
    p.querySelector('[data-act="savedone"]').addEventListener('click', function () {
      var ts = new Date(p.querySelector('.c-when').value).getTime();
      var tech = p.querySelector('.c-tech').value.trim(), desc = p.querySelector('.c-desc').value.trim();
      var rh = p.querySelector('.c-rh').value === '' ? null : Number(p.querySelector('.c-rh').value);
      var reset = !!(p.querySelector('.c-reset') && p.querySelector('.c-reset').checked);
      if (!isFinite(ts) || ts > Date.now() + 60000) { pstatus('Enter a work date and time that is not in the future.', 'bad'); return; }
      if (!tech || !desc) { pstatus('Enter the technician and the work done.', 'bad'); return; }
      if ((reset || j.kind === 'run_hours') && rh == null) { pstatus('Enter the run hours at which the work was done.', 'bad'); return; }
      var checks = [].slice.call(p.querySelectorAll('.c-cl input')).map(function (c) { return {item: j.checklist[Number(c.getAttribute('data-i'))], done: c.checked}; });
      var files = [].slice.call(p.querySelector('.c-files').files || []);
      var btn = p.querySelector('[data-act="savedone"]');
      btn.disabled = true;
      pstatus(files.length ? 'Uploading ' + files.length + ' file(s)…' : 'Saving…');
      var doneDate = ymd(new Date(ts));
      var nextDate = j.kind === 'days' ? addDays(doneDate, Number(j.every)) : null;
      var nextRh = j.kind === 'run_hours' ? r1(rh + Number(j.every)) : null;
      files.reduce(function (pr, file) {
        return pr.then(function (acc) {
          return uploadFile(file, j.title + ' - ' + file.name).then(function (meta) {
            meta.category = /\.(jpe?g|png|gif|webp|heic)$/i.test(file.name) ? 'Photo' : 'Service report';
            acc.push(meta); return acc;
          });
        });
      }, Promise.resolve([])).then(function (att) {
        var rec = {type: j.type, description: desc, technician: tech, run_hours: rh,
                   parts: p.querySelector('.c-parts').value.trim() || null,
                   cost: p.querySelector('.c-cost').value === '' ? null : Number(p.querySelector('.c-cost').value),
                   next_due: nextDate || (nextRh != null ? nextRh + ' run-h' : null), service_reset: reset,
                   logged_by: userName(), logged_at: Date.now(), job_id: j.id, job_title: j.title,
                   checklist: checks, attachments: att.map(function (a) { return {id: a.id, title: a.title, file: a.file}; })};
        var steps = [req(http.post('/api/plugins/telemetry/DEVICE/' + e.id + '/timeseries/ANY', [{ts: ts, values: {maintenance_record: JSON.stringify(rec)}}]))];
        if (att.length) steps.push(updateAttr(e.id, 'maint_docs', function (l) { return l.concat(att); }));
        return Promise.all(steps).then(function () {
          return updateAttr(e.id, 'maint_jobs', function (list) {
            return list.map(function (x) {
              if (x.id !== j.id) return x;
              var y = JSON.parse(JSON.stringify(x));
              y.last_done_ts = ts; y.last_done_by = tech; y.last_done_rh = rh;
              if (y.kind === 'once') { y.active = false; } else if (y.kind === 'days') { y.next_date = nextDate; } else { y.next_rh = nextRh; }
              return y;
            });
          });
        }).then(function () {
          if (!reset) return null;
          return req(http.get('/api/plugins/telemetry/DEVICE/' + e.id + '/values/attributes/SERVER_SCOPE?keys=pm_config')).then(function (attrs) {
            var cfg = parseAttr(attrs, 'pm_config', {});
            if (!cfg || typeof cfg !== 'object' || Array.isArray(cfg)) cfg = {};
            cfg.last_service_run_hours = rh;
            if (j.kind === 'run_hours' && Number(j.every) > 0) cfg.service_interval_h = Number(j.every);
            return req(http.post('/api/plugins/telemetry/DEVICE/' + e.id + '/attributes/SERVER_SCOPE', {pm_config: JSON.stringify(cfg)}));
          });
        });
      }).then(function () {
        state.panel = null;
        return reload();
      }, function (err) {
        btn.disabled = false;
        pstatus('Could not save: ' + errText(err), 'bad');
      });
    });
  }

  function uploadForm() {
    slot().innerHTML = '<div class="mp-panel"><h4>Upload technical document</h4><div class="mp-grid">' +
      '<label>Equipment' + equipSelect('u-eq', state.equip || 'general', false, true) + '</label>' +
      '<label class="wide">Title<input class="u-title" maxlength="120" placeholder="e.g. Woodward easYgen operator manual"></label>' +
      '<label>Category<select class="u-cat">' + CATS.map(function (c) { return '<option>' + c + '</option>'; }).join('') + '</select></label>' +
      '<label>File (max 50 MB)<input type="file" class="u-file"></label>' +
      '</div><div class="mp-row"><button class="mp-btn" data-act="saveupload">Upload</button>' +
      '<button class="mp-btn light" data-act="close">Cancel</button><span class="mp-status"></span></div></div>';
    var p = slot();
    p.querySelector('[data-act="saveupload"]').addEventListener('click', function () {
      var file = p.querySelector('.u-file').files[0], target = p.querySelector('.u-eq').value;
      var title = p.querySelector('.u-title').value.trim() || (file && file.name);
      if (!file) { pstatus('Choose a file.', 'bad'); return; }
      if (file.size > 50 * 1048576) { pstatus('File is larger than 50 MB.', 'bad'); return; }
      var btn = p.querySelector('[data-act="saveupload"]');
      btn.disabled = true;
      pstatus('Uploading…');
      uploadFile(file, title).then(function (meta) {
        meta.category = p.querySelector('.u-cat').value;
        return updateAttr(target, 'maint_docs', function (l) { return l.concat([meta]); });
      }).then(function () { state.panel = null; return reload(); }, function (err) {
        btn.disabled = false;
        pstatus('Upload failed: ' + errText(err), 'bad');
      });
    });
  }

  // ---------------------------------------------------------------- events
  function bind() {
    root.querySelectorAll('[data-tab]').forEach(function (b) {
      b.addEventListener('click', function () { state.tab = b.getAttribute('data-tab'); state.panel = null; render(); });
    });
    root.querySelectorAll('[data-filter]').forEach(function (b) {
      b.addEventListener('click', function () { state.filter = b.getAttribute('data-filter'); render(); });
    });
    var eqf = root.querySelector('.mp-eqf');
    if (eqf) eqf.addEventListener('change', function () { state.equip = eqf.value; render(); });
  }
  function onClick(ev) {
    var t = ev.target.closest('[data-act],[data-doc]');
    if (!t || !root.contains(t)) return;
    var act = t.getAttribute('data-act');
    if (!act && t.getAttribute('data-doc')) { download(t.getAttribute('data-doc')); return; }
    if (act === 'new') openPanel('job', null);
    else if (act === 'edit') openPanel('job', {e: t.getAttribute('data-e'), j: t.getAttribute('data-j')});
    else if (act === 'complete') openPanel('complete', {e: t.getAttribute('data-e'), j: t.getAttribute('data-j')});
    else if (act === 'upload') openPanel('upload');
    else if (act === 'close') closePanel();
    else if (act === 'deljob') {
      var e = byId(t.getAttribute('data-e')), id = t.getAttribute('data-j');
      var j = e.jobs.filter(function (x) { return x.id === id; })[0];
      if (!j || !window.confirm('Delete the job "' + j.title + '" of ' + e.name + '? Work already recorded stays in the Maintenance Log.')) return;
      updateAttr(e.id, 'maint_jobs', function (l) { return l.filter(function (x) { return x.id !== id; }); }).then(reload);
    } else if (act === 'deldoc') {
      var owner = t.getAttribute('data-o'), did = t.getAttribute('data-d'), x = findDoc(did);
      if (!x || !window.confirm('Delete the document "' + x.d.title + '"? It is removed from all jobs.')) return;
      req(http.delete('/api/resource/' + did)).catch(function () { return null; }).then(function () {
        return updateAttr(owner, 'maint_docs', function (l) { return l.filter(function (d) { return d.id !== did; }); });
      }).then(function () {
        return Promise.all(equipment.filter(function (e2) { return e2.jobs.some(function (j2) { return (j2.docs || []).indexOf(did) >= 0; }); }).map(function (e2) {
          return updateAttr(e2.id, 'maint_jobs', function (l) {
            return l.map(function (j2) { j2.docs = (j2.docs || []).filter(function (d) { return d !== did; }); return j2; });
          });
        }));
      }).then(reload, function (err) { window.alert('Delete failed: ' + errText(err)); });
    }
  }

  self._mpDataUpdated = function () {
    var before = JSON.stringify(equipment.map(function (e) { return e.runHours; }));
    updateRunHours();
    if (JSON.stringify(equipment.map(function (e) { return e.runHours; })) !== before && !state.panel) render();
  };
  root.addEventListener('click', onClick);   // once: render() only replaces the inner HTML
  root.innerHTML = '<div class="mp"><div class="mp-empty">Loading maintenance jobs…</div></div>';
  loadEquipment().then(function () { updateRunHours(); return loadData(); }).then(render);
};

self.onDataUpdated = function () {
  if (self._mpDataUpdated) self._mpDataUpdated();
};

self.typeParameters = function () {
  return {dataKeysOptional: true, singleEntity: false, hasDataPageLink: false};
};

self.onDestroy = function () {};
