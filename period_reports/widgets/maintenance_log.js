// ThingsBoard latest-values widget "Maintenance Log": records maintenance work as telemetry
// maintenance_record (JSON) on the equipment at the time the work was done, lists recent records and can
// reset the predictive-maintenance service counter of a DG (server attribute pm_config.last_service_run_hours).
// Datasource: alias of all monitored equipment, data key run_hours (used to pre-fill run hours).
self.onInit = function () {
  var root = self.ctx.$container[0];
  var http = self.ctx.http;
  var TYPES = ['Preventive service', 'Corrective repair', 'Inspection', 'Test run', 'Calibration',
               'Part replacement', 'Cleaning', 'Other'];
  var DG_TYPE = 'woodward_kg1500';
  var equipment = [];      // {id, name, type, runHours}
  var records = [];

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function user() {
    try {
      var p = JSON.parse(atob(window.localStorage.getItem('jwt_token').split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
      return ((p.firstName || '') + ' ' + (p.lastName || '')).trim() || p.sub || '';
    } catch (e) { return ''; }
  }
  function localNow() {
    var d = new Date(Date.now() - new Date().getTimezoneOffset() * 60000);
    return d.toISOString().slice(0, 16);
  }
  function when(ts) {
    var d = new Date(ts);
    return d.toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'}) + ' ' +
      d.toLocaleTimeString('en-GB', {hour: '2-digit', minute: '2-digit'});
  }

  root.innerHTML =
    '<div class="ml">' +
    ' <form class="ml-form" autocomplete="off">' +
    '  <label>Equipment<select name="dev" required></select></label>' +
    '  <label>Date &amp; time of work<input type="datetime-local" name="when" required></label>' +
    '  <label>Type<select name="type">' + TYPES.map(function (t) { return '<option>' + t + '</option>'; }).join('') + '</select></label>' +
    '  <label class="wide">Work done<textarea name="desc" rows="2" maxlength="600" required placeholder="e.g. Engine oil and oil filter changed, air filter cleaned"></textarea></label>' +
    '  <label>Technician<input name="tech" maxlength="80" required placeholder="Name / vendor"></label>' +
    '  <label>Run hours at work<input type="number" name="rh" step="0.1" min="0" placeholder="DG only"></label>' +
    '  <label>Parts used<input name="parts" maxlength="200" placeholder="Optional"></label>' +
    '  <label>Cost (INR)<input type="number" name="cost" step="1" min="0" placeholder="Optional"></label>' +
    '  <label>Next due<input type="date" name="next"></label>' +
    '  <label class="wide chk"><input type="checkbox" name="reset"> This was the scheduled service: restart the DG service-due counter from these run hours</label>' +
    '  <div class="wide ml-actions"><button type="submit" class="ml-btn">Save record</button><span class="ml-status"></span></div>' +
    ' </form>' +
    ' <div class="ml-list-head">Recent maintenance <span class="ml-count"></span></div>' +
    ' <div class="ml-list"></div>' +
    '</div>';

  var form = root.querySelector('.ml-form');
  function f(n) { return form.querySelector('[name="' + n + '"]'); }
  function status(t, kind) { var s = root.querySelector('.ml-status'); s.textContent = t || ''; s.className = 'ml-status ' + (kind || ''); }
  f('when').value = localNow();
  f('when').max = localNow();

  function current() {
    var id = f('dev').value;
    for (var i = 0; i < equipment.length; i++) if (equipment[i].id === id) return equipment[i];
    return null;
  }
  function syncForm() {
    var e = current();
    var isDg = e && e.type === DG_TYPE;
    f('rh').disabled = !isDg;
    if (isDg && !f('rh').value && e.runHours != null) f('rh').value = e.runHours;
    if (!isDg) f('rh').value = '';
    var showReset = isDg && f('type').value === 'Preventive service';
    form.querySelector('.chk').style.display = showReset ? '' : 'none';
    if (!showReset) f('reset').checked = false;
  }

  function loadEquipment() {
    var seen = {};
    equipment = [];
    (self.ctx.datasources || []).forEach(function (ds) {
      if (!ds.entityId || seen[ds.entityId]) return;
      seen[ds.entityId] = true;
      equipment.push({id: ds.entityId, name: ds.entityName, type: ds.entityType === 'DEVICE' ? null : ds.entityType});
    });
    // device types (profiles) decide which form fields apply
    return Promise.all(equipment.map(function (e) {
      return new Promise(function (resolve) {
        http.get('/api/device/' + e.id).subscribe(function (d) { e.type = d.type; resolve(); }, function () { resolve(); });
      });
    })).then(function () {
      equipment.sort(function (a, b) { return a.name.localeCompare(b.name); });
      f('dev').innerHTML = equipment.map(function (e) { return '<option value="' + e.id + '">' + esc(e.name) + '</option>'; }).join('');
      updateRunHours();
      syncForm();
    });
  }

  function updateRunHours() {
    (self.ctx.data || []).forEach(function (d) {
      var id = d.datasource && d.datasource.entityId;
      var v = d.data && d.data.length ? Number(d.data[d.data.length - 1][1]) : NaN;
      equipment.forEach(function (e) { if (e.id === id && isFinite(v) && v < 30000) e.runHours = Math.round(v * 10) / 10; });
    });
  }

  function loadRecords() {
    var now = Date.now();
    return Promise.all(equipment.map(function (e) {
      return new Promise(function (resolve) {
        http.get('/api/plugins/telemetry/DEVICE/' + e.id + '/values/timeseries?keys=maintenance_record&startTs=0&endTs=' + now + '&limit=50')
          .subscribe(function (r) {
            resolve((r.maintenance_record || []).map(function (p) {
              var v; try { v = JSON.parse(p.value); } catch (x) { v = {description: p.value}; }
              return {ts: p.ts, dev: e, rec: v};
            }));
          }, function () { resolve([]); });
      });
    })).then(function (lists) {
      records = [].concat.apply([], lists).sort(function (a, b) { return b.ts - a.ts; });
      renderList();
    });
  }

  function renderList() {
    root.querySelector('.ml-count').textContent = records.length ? '(' + records.length + ')' : '';
    var el = root.querySelector('.ml-list');
    if (!records.length) {
      el.innerHTML = '<div class="ml-empty">No maintenance recorded yet. Records appear here and in the period reports.</div>';
      return;
    }
    el.innerHTML = '<table><thead><tr><th>When</th><th>Equipment</th><th>Type</th><th>Work done</th><th>Technician</th><th>Run-h</th><th></th></tr></thead><tbody>' +
      records.slice(0, 40).map(function (r, i) {
        var x = r.rec || {};
        var sub = [x.parts ? 'Parts: ' + esc(x.parts) : '', x.cost ? 'INR ' + esc(x.cost) : '', x.next_due ? 'Next due ' + esc(x.next_due) : '',
                   x.service_reset ? 'Service counter reset' : ''].filter(Boolean).join(' &middot; ');
        return '<tr><td class="nw">' + when(r.ts) + '</td><td>' + esc(r.dev.name) + '</td><td><span class="tag">' + esc(x.type || 'Maintenance') +
          '</span></td><td>' + esc(x.description) + (sub ? '<div class="sub">' + sub + '</div>' : '') + '</td><td>' + esc(x.technician) +
          (x.logged_by ? '<div class="sub">logged by ' + esc(x.logged_by) + '</div>' : '') + '</td><td class="r">' + esc(x.run_hours == null ? '' : x.run_hours) +
          '</td><td><button class="ml-del" data-i="' + i + '" title="Delete this record">&times;</button></td></tr>';
      }).join('') + '</tbody></table>';
    el.querySelectorAll('.ml-del').forEach(function (b) {
      b.addEventListener('click', function () { del(records[Number(b.getAttribute('data-i'))]); });
    });
  }

  function del(r) {
    if (!r || !window.confirm('Delete this maintenance record of ' + r.dev.name + ' (' + when(r.ts) + ')?')) return;
    http.delete('/api/plugins/telemetry/DEVICE/' + r.dev.id + '/timeseries/delete?keys=maintenance_record&startTs=' + r.ts +
      '&endTs=' + (r.ts + 1) + '&deleteAllDataForKeys=false&rewriteLatestIfDeleted=true')
      .subscribe(function () { status('Record deleted.', 'ok'); loadRecords(); },
                 function (e) { status('Delete failed: ' + ((e.error && e.error.message) || e.status), 'bad'); });
  }

  function resetServiceCounter(e, runHours) {
    return new Promise(function (resolve, reject) {
      http.get('/api/plugins/telemetry/DEVICE/' + e.id + '/values/attributes/SERVER_SCOPE?keys=pm_config').subscribe(function (attrs) {
        var cfg = {};
        (attrs || []).forEach(function (a) {
          if (a.key === 'pm_config') { try { cfg = typeof a.value === 'string' ? JSON.parse(a.value) : a.value; } catch (x) { cfg = {}; } }
        });
        cfg.last_service_run_hours = runHours;
        http.post('/api/plugins/telemetry/DEVICE/' + e.id + '/attributes/SERVER_SCOPE', {pm_config: JSON.stringify(cfg)})
          .subscribe(function () { resolve(); }, reject);
      }, reject);
    });
  }

  form.addEventListener('change', function (ev) {
    if (ev.target && ev.target.name === 'dev') f('rh').value = '';   // new equipment: take its run hours
    syncForm();
  });
  self._mlDataUpdated = function () { updateRunHours(); syncForm(); };
  form.addEventListener('submit', function (ev) {
    ev.preventDefault();
    var e = current();
    if (!e) return;
    var ts = new Date(f('when').value).getTime();
    if (!isFinite(ts) || ts > Date.now() + 60000) { status('Enter a date and time that is not in the future.', 'bad'); return; }
    var rh = f('rh').value === '' ? null : Number(f('rh').value);
    if (f('reset').checked && rh == null) { status('Enter the run hours at which the service was done.', 'bad'); return; }
    var rec = {type: f('type').value, description: f('desc').value.trim(), technician: f('tech').value.trim(),
               run_hours: rh, parts: f('parts').value.trim() || null, cost: f('cost').value === '' ? null : Number(f('cost').value),
               next_due: f('next').value || null, service_reset: f('reset').checked, logged_by: user(), logged_at: Date.now()};
    var btn = form.querySelector('.ml-btn');
    btn.disabled = true;
    status('Saving…', '');
    http.post('/api/plugins/telemetry/DEVICE/' + e.id + '/timeseries/ANY', [{ts: ts, values: {maintenance_record: JSON.stringify(rec)}}])
      .subscribe(function () {
        var done = rec.service_reset ? resetServiceCounter(e, rh) : Promise.resolve();
        done.then(function () {
          status('Saved' + (rec.service_reset ? ' and service counter restarted at ' + rh + ' run-h' : '') + '.', 'ok');
        }, function () {
          status('Record saved, but the service counter could not be updated (permission?).', 'bad');
        }).then(function () {
          f('desc').value = ''; f('parts').value = ''; f('cost').value = ''; f('next').value = ''; f('reset').checked = false;
          f('when').value = localNow();
          btn.disabled = false;
          loadRecords();
        });
      }, function (err) {
        btn.disabled = false;
        status('Could not save: ' + ((err.error && err.error.message) || err.status), 'bad');
      });
  });

  loadEquipment().then(loadRecords);
};

self.onDataUpdated = function () {
  if (self._mlDataUpdated) self._mlDataUpdated();
};

self.typeParameters = function () {
  return {dataKeysOptional: true, singleEntity: false, hasDataPageLink: false};
};

self.onDestroy = function () {};
