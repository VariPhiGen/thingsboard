// ThingsBoard static widget "Equipment Report Download": builds daily/weekly/monthly/custom (<= 31 days)
// PDF or Excel reports through the period-reports API, authenticated with the signed-in user's JWT.
self.onInit = function () {
  var settings = self.ctx.settings || {};
  var API = (settings.apiUrl || 'https://n8n.variphi.com/reports-api/v1/period-reports').replace(/\/$/, '');
  var MAX_DAYS = 31;
  var root = self.ctx.$container[0];

  // ---- IST dates (the reports cover IST calendar days) ----
  function istToday() {
    return new Date(Date.now() + 5.5 * 3600000).toISOString().slice(0, 10);
  }
  function addDays(iso, n) {
    var d = new Date(iso + 'T00:00:00Z');
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }
  function daysBetween(a, b) {
    return Math.round((new Date(b + 'T00:00:00Z') - new Date(a + 'T00:00:00Z')) / 86400000) + 1;
  }
  function fmt(iso) {
    var d = new Date(iso + 'T00:00:00Z');
    return d.toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC'});
  }
  var today = istToday(), yesterday = addDays(today, -1);
  var prevMonth = (function () {
    var d = new Date(today + 'T00:00:00Z');
    d.setUTCDate(1);
    d.setUTCMonth(d.getUTCMonth() - 1);
    return d.toISOString().slice(0, 7);
  })();

  var state = {mode: 'daily', busy: false};
  root.innerHTML =
    '<div class="vr">' +
    '  <div class="vr-tabs">' +
    '    <button data-mode="daily" class="on">Daily</button><button data-mode="weekly">Weekly</button>' +
    '    <button data-mode="monthly">Monthly</button><button data-mode="custom">Custom</button>' +
    '  </div>' +
    '  <div class="vr-grid">' +
    '    <label class="f-day">Date<input type="date" name="day"></label>' +
    '    <label class="f-week">Week ending<input type="date" name="weekEnd"></label>' +
    '    <label class="f-month">Month<input type="month" name="month"></label>' +
    '    <label class="f-from">From<input type="date" name="from"></label>' +
    '    <label class="f-to">To<input type="date" name="to"></label>' +
    '    <label>Equipment<select name="equipment">' +
    '      <option value="all">All equipment</option><option value="dg">DG Sets</option>' +
    '      <option value="lt">LT Panels</option><option value="ro">RO Plant</option>' +
    '      <option value="fire">Fire Suppression</option></select></label>' +
    '  </div>' +
    '  <div class="vr-period"></div>' +
    '  <div class="vr-actions">' +
    '    <button class="vr-btn primary" data-fmt="pdf">Download PDF</button>' +
    '    <button class="vr-btn" data-fmt="xlsx">Download Excel</button>' +
    '  </div>' +
    '  <div class="vr-status"></div>' +
    '  <div class="vr-help">Includes equipment readings, runtime, energy, fuel, alarms, maintenance history and the ' +
    'predictive maintenance outlook. PDF for review and audit, Excel for the daily data.</div>' +
    '</div>';

  function q(sel) { return root.querySelector(sel); }
  function input(name) { return root.querySelector('[name="' + name + '"]'); }
  ['day', 'weekEnd', 'from', 'to'].forEach(function (n) { input(n).max = today; });
  input('month').max = today.slice(0, 7);
  input('day').value = yesterday;
  input('weekEnd').value = yesterday;
  input('month').value = prevMonth;
  input('from').value = addDays(yesterday, -6);
  input('to').value = yesterday;

  function period() {
    var s, e;
    if (state.mode === 'daily') { s = e = input('day').value; }
    else if (state.mode === 'weekly') { e = input('weekEnd').value; s = e ? addDays(e, -6) : ''; }
    else if (state.mode === 'monthly') {
      var m = input('month').value;
      if (m) {
        s = m + '-01';
        var next = new Date(s + 'T00:00:00Z');
        next.setUTCMonth(next.getUTCMonth() + 1);
        e = addDays(next.toISOString().slice(0, 10), -1);
        if (e > today) e = today;
      }
    } else { s = input('from').value; e = input('to').value; }
    if (!s || !e) return {error: 'Select the date(s).'};
    if (e < s) return {error: '"To" is before "From".'};
    if (e > today) return {error: 'The period cannot end in the future.'};
    var n = daysBetween(s, e);
    if (n > MAX_DAYS) return {error: 'A report covers at most ' + MAX_DAYS + ' days (selected ' + n + ').'};
    return {start: s, end: e, days: n};
  }

  function render() {
    root.querySelectorAll('.vr-tabs button').forEach(function (b) {
      b.classList.toggle('on', b.getAttribute('data-mode') === state.mode);
    });
    q('.f-day').style.display = state.mode === 'daily' ? '' : 'none';
    q('.f-week').style.display = state.mode === 'weekly' ? '' : 'none';
    q('.f-month').style.display = state.mode === 'monthly' ? '' : 'none';
    q('.f-from').style.display = q('.f-to').style.display = state.mode === 'custom' ? '' : 'none';
    var p = period();
    var el = q('.vr-period');
    if (p.error) { el.textContent = p.error; el.className = 'vr-period bad'; }
    else {
      el.className = 'vr-period';
      el.textContent = 'Period: ' + (p.days === 1 ? fmt(p.start) : fmt(p.start) + ' – ' + fmt(p.end)) +
        ' (' + p.days + ' day' + (p.days > 1 ? 's' : '') + ', IST)' + (p.end === today ? ' – today up to now' : '');
    }
    root.querySelectorAll('.vr-btn').forEach(function (b) { b.disabled = state.busy || !!p.error; });
  }

  function status(text, kind) {
    var el = q('.vr-status');
    el.textContent = text || '';
    el.className = 'vr-status' + (kind ? ' ' + kind : '');
  }

  function download(fmtName) {
    var p = period();
    if (p.error) return;
    var token = window.localStorage.getItem('jwt_token');
    if (!token) { status('Your ThingsBoard session has ended. Reload the page and sign in again.', 'bad'); return; }
    var url = API + '/download?start=' + p.start + '&end=' + p.end + '&equipment=' +
      encodeURIComponent(input('equipment').value) + '&format=' + fmtName;
    state.busy = true; render();
    var t0 = Date.now();
    status('Generating ' + (fmtName === 'pdf' ? 'PDF' : 'Excel') + ' report… a monthly report can take up to a minute.', 'busy');
    fetch(url, {headers: {'X-Authorization': 'Bearer ' + token}}).then(function (res) {
      if (!res.ok) {
        return res.json().catch(function () { return {}; }).then(function (j) {
          throw new Error(j.error || ('HTTP ' + res.status));
        });
      }
      var cd = res.headers.get('Content-Disposition') || '';
      var m = /filename="([^"]+)"/.exec(cd);
      var name = m ? m[1] : 'Equipment_Report.' + fmtName;
      return res.blob().then(function (blob) {
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = name;
        document.body.appendChild(a);
        a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
        status('Downloaded ' + name + ' (' + Math.round(blob.size / 1024) + ' KB, ' +
          Math.round((Date.now() - t0) / 1000) + ' s).', 'ok');
      });
    }).catch(function (err) {
      status('Could not create the report: ' + err.message, 'bad');
    }).then(function () { state.busy = false; render(); });
  }

  root.querySelectorAll('.vr-tabs button').forEach(function (b) {
    b.addEventListener('click', function () { state.mode = b.getAttribute('data-mode'); status(''); render(); });
  });
  root.querySelectorAll('input,select').forEach(function (el) { el.addEventListener('change', render); });
  root.querySelectorAll('.vr-btn').forEach(function (b) {
    b.addEventListener('click', function () { download(b.getAttribute('data-fmt')); });
  });
  render();
};

self.onDestroy = function () {};
