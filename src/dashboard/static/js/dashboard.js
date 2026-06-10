// --- Tab switching ---
function switchTab(name) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.remove('active', 'text-gray-900', 'dark:text-white', 'border-primary-600');
    b.classList.add('text-gray-500', 'dark:text-gray-400', 'border-transparent');
  });
  var panel = document.getElementById('tab-' + name);
  if (panel) panel.classList.add('active');
  document.querySelectorAll('.tab-btn').forEach(b => {
    if (b.getAttribute('onclick') === "switchTab('" + name + "')") {
      b.classList.add('active', 'text-gray-900', 'dark:text-white', 'border-primary-600');
      b.classList.remove('text-gray-500', 'dark:text-gray-400', 'border-transparent');
    }
  });
  window.location.hash = name;
}
// Restore tab from URL hash
(function() {
  const hash = window.location.hash.replace('#', '');
  if (hash && document.getElementById('tab-' + hash)) switchTab(hash);
})();

// --- Generic sorting for any table ---
function setupSorting(tableId, defaultCol) {
  const table = document.getElementById(tableId);
  if (!table) return;
  table.querySelectorAll('th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const tbody = table.querySelector('tbody');
      const col = parseInt(th.dataset.col);
      const isNum = th.dataset.type === 'number';
      const rows = Array.from(tbody.querySelectorAll('tr'));
      const asc = th.dataset.dir !== 'asc';
      th.dataset.dir = asc ? 'asc' : 'desc';
      table.querySelectorAll('th.sortable').forEach(h => { if (h !== th) delete h.dataset.dir; });
      rows.sort((a, b) => {
        let va, vb;
        if (isNum) {
          va = parseFloat(a.cells[col]?.dataset.sortValue ?? a.cells[col]?.textContent) || -1;
          vb = parseFloat(b.cells[col]?.dataset.sortValue ?? b.cells[col]?.textContent) || -1;
        } else {
          va = (a.cells[col]?.textContent || '').trim();
          vb = (b.cells[col]?.textContent || '').trim();
          return asc ? va.localeCompare(vb, undefined, {numeric: true}) : vb.localeCompare(va, undefined, {numeric: true});
        }
        if (va < vb) return asc ? -1 : 1;
        if (va > vb) return asc ? 1 : -1;
        return 0;
      });
      rows.forEach(r => tbody.appendChild(r));
    });
  });
  // Trigger default ascending sort on the specified column
  if (defaultCol !== undefined) {
    const th = table.querySelector('th.sortable[data-col="' + defaultCol + '"]');
    if (th) th.click();
  }
}

// --- Generic tab filtering ---
function applyTabFilters(tableId, filterBarId, countSpanId) {
  const bar = document.getElementById(filterBarId);
  if (!bar) return;
  const selects = bar.querySelectorAll('select');
  const textInput = bar.querySelector('input[type="text"]');
  const text = textInput ? textInput.value.toLowerCase() : '';
  document.querySelectorAll('#' + tableId + ' tbody tr').forEach(row => {
    let show = true;
    if (text && !row.textContent.toLowerCase().includes(text)) show = false;
    selects.forEach(sel => {
      const attr = sel.dataset.attr;
      const val = sel.value;
      if (val && attr) {
        if (row.dataset[attr] !== val) show = false;
      }
    });
    row.style.display = show ? '' : 'none';
  });
  const visible = document.querySelectorAll('#' + tableId + ' tbody tr:not([style*="display: none"])').length;
  const countEl = document.getElementById(countSpanId);
  if (countEl) countEl.textContent = visible;
}

// --- Bug tab: existing filter + checkbox logic ---
function applyBugFilters() {
  const model = document.getElementById('filter-model').value;
  const status = document.getElementById('filter-status').value;
  const triage = document.getElementById('filter-triage').value;
  const issuetype = document.getElementById('filter-issuetype').value;
  const component = document.getElementById('filter-component').value;
  const context = document.getElementById('filter-context').value;
  const fix = document.getElementById('filter-fix').value;
  const testctx = document.getElementById('filter-testctx').value;
  const archdocs = document.getElementById('filter-archdocs').value;
  const srccode = document.getElementById('filter-srccode').value;
  const writetest = document.getElementById('filter-writetest').value;
  const eligible = document.getElementById('filter-eligible').value;
  const text = document.getElementById('filter-text').value.toLowerCase();
  document.querySelectorAll('#issues-table tbody tr').forEach(row => {
    let show = true;
    if (text && !row.textContent.toLowerCase().includes(text)) show = false;
    if (model && row.dataset.model !== model) show = false;
    if (status && row.dataset.status !== status) show = false;
    if (triage && row.dataset.triage !== triage) show = false;
    if (issuetype && row.dataset.issuetype !== issuetype) show = false;
    if (component && !row.dataset.components.split('||').includes(component)) show = false;
    if (context && row.dataset.context !== context) show = false;
    if (fix && row.dataset.fix !== fix) show = false;
    if (testctx && row.dataset.testctx !== testctx) show = false;
    if (archdocs && row.dataset.archdocs !== archdocs) show = false;
    if (srccode && row.dataset.srccode !== srccode) show = false;
    if (writetest && row.dataset.writetest !== writetest) show = false;
    if (eligible && row.dataset.eligible !== eligible) show = false;
    row.style.display = show ? '' : 'none';
  });
  const visible = document.querySelectorAll('#issues-table tbody tr:not([style*="display: none"])').length;
  document.getElementById('bug-row-count').textContent = visible;
  document.querySelectorAll('#issues-table tbody tr[style*="display: none"] .row-select')
    .forEach(cb => { cb.checked = false; });
  updateActionBar();
}

function toggleSelectAll(el) {
  document.querySelectorAll('#issues-table tbody tr:not([style*="display: none"]) .row-select')
    .forEach(cb => { cb.checked = el.checked; });
  updateActionBar();
}

function updateActionBar() {
  const checked = document.querySelectorAll('.row-select:checked');
  const bar = document.getElementById('action-bar');
  document.getElementById('selected-count').textContent = checked.length;
  bar.style.display = checked.length > 0 ? '' : 'none';
}

document.addEventListener('change', e => {
  if (e.target.classList.contains('row-select')) updateActionBar();
});

function confirmReset() {
  const checked = document.querySelectorAll('.row-select:checked');
  document.getElementById('reset-count').textContent = checked.length;
  const list = Array.from(checked).map(cb =>
    `${cb.dataset.key} (${cb.dataset.model})`
  ).join('<br>');
  document.getElementById('reset-list').innerHTML = list;
  document.getElementById('reset-modal').showModal();
}

function executeReset() {
  const checked = document.querySelectorAll('.row-select:checked');
  const pairs = Array.from(checked).map(cb => ({
    key: cb.dataset.key, model: cb.dataset.model
  }));
  fetch('/api/workspace/reset', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({pairs})
  })
  .then(r => r.json())
  .then(data => {
    document.getElementById('reset-modal').close();
    const deleted = data.results.filter(r => r.status === 'deleted').length;
    alert(`Reset complete: ${deleted} workspace(s) deleted.`);
    location.reload();
  })
  .catch(err => alert('Reset failed: ' + err));
}

// Init bug tab
applyBugFilters();

// --- Pipeline active-row highlighting ---
function highlightActiveRows(queueState) {
  const pending = new Set();
  const active = new Set();
  (queueState.jobs || []).forEach(j => {
    const id = j.key + '|' + j.model;
    if (j.status === 'pending') pending.add(id);
    else if (j.status === 'running') active.add(id);
  });
  document.querySelectorAll('#issues-table tbody tr').forEach(row => {
    const id = row.dataset.key + '|' + row.dataset.model;
    row.classList.toggle('pipeline-pending', pending.has(id));
    row.classList.toggle('pipeline-active', active.has(id));
  });
}

(function() {
  function pollQueue() {
    fetch('/api/pipeline/queue')
      .then(r => r.json())
      .then(highlightActiveRows)
      .catch(() => {});
  }
  pollQueue();

  const evtSource = new EventSource('/api/events');
  evtSource.onmessage = function(event) {
    try {
      const data = JSON.parse(event.data);
      const evt = data.event || data.type;
      if (['manifest','issue_started','issue_completed','started','pipeline_completed','pipeline_failed'].includes(evt)) {
        pollQueue();
      }
    } catch(e) {}
  };
})();

// Init sorting on all tables (default sort by Key column)
setupSorting('all-table', 0);
setupSorting('issues-table', 1);
setupSorting('rfe-table', 0);
setupSorting('strat-table', 0);
setupSorting('epic-table', 0);
