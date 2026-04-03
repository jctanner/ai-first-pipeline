"""Flask web application for the bug bash reporting dashboard."""

import json
import os
import queue
import shutil
import stat
import threading

from flask import Flask, render_template_string, jsonify, abort, Response, request
from jinja2 import DictLoader, ChoiceLoader

from lib.report_data import (
    load_all_issues, load_single_issue, load_activity,
    load_pipeline_status, tail_activity_log,
    compute_summary_stats, compute_component_readiness,
)
from lib.paths import discover_models, model_workspace
from lib.rfe_data import load_rfe_issues, load_single_rfe, load_strat_issues
from lib.stats import compute_all_stats

# ---------------------------------------------------------------------------
# In-memory pipeline state (single-process Flask dev server)
# ---------------------------------------------------------------------------

_pipeline_state = {
    "running": False,
    "manifest": None,       # full manifest from controller
    "jobs": {},             # (issue_key, model) -> {status, phase, started_at, ...}
    "events": [],           # recent events for SSE replay (capped)
    "sse_subscribers": [],  # list of queue.Queue for SSE push
}
_state_lock = threading.Lock()
_MAX_EVENTS = 5000


def _broadcast_sse(data: dict) -> None:
    """Push a JSON event to all SSE subscriber queues."""
    msg = json.dumps(data)
    with _state_lock:
        dead = []
        for i, q in enumerate(_pipeline_state["sse_subscribers"]):
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(i)
        # Remove dead/full queues in reverse order
        for i in reversed(dead):
            _pipeline_state["sse_subscribers"].pop(i)


def _handle_manifest(payload: dict) -> None:
    """Process a manifest message — resets all prior state."""
    with _state_lock:
        _pipeline_state["running"] = True
        _pipeline_state["manifest"] = payload
        _pipeline_state["events"] = []
        _pipeline_state["jobs"] = {}
        for job in payload.get("jobs", []):
            jk = (job["key"], job["model"])
            _pipeline_state["jobs"][jk] = {
                "key": job["key"],
                "model": job["model"],
                "status": "pending",
                "phase": None,
                "started_at": None,
                "completed_at": None,
                "error": None,
            }
    _broadcast_sse(payload)


def _handle_event(payload: dict) -> None:
    """Process an individual event — updates job state in place."""
    issue_key = payload.get("issue_key", "")
    model = payload.get("model", "")
    event = payload.get("event", "")
    phase = payload.get("phase", "")
    timestamp = payload.get("timestamp", "")

    with _state_lock:
        # Append to recent events (capped)
        _pipeline_state["events"].append(payload)
        if len(_pipeline_state["events"]) > _MAX_EVENTS:
            _pipeline_state["events"] = _pipeline_state["events"][-_MAX_EVENTS:]

        jk = (issue_key, model)
        job = _pipeline_state["jobs"].get(jk)

        if event == "pipeline_completed" or event == "pipeline_failed":
            _pipeline_state["running"] = False
        elif event == "issue_started":
            if job:
                job["status"] = "running"
                job["started_at"] = timestamp
        elif event == "started":
            if job:
                job["status"] = "running"
                job["phase"] = phase
        elif event == "completed":
            if job:
                job["phase"] = phase
                # Only mark completed if this is the issue_completed event
                # Individual phase completions just update the phase
        elif event == "failed":
            if job:
                job["phase"] = phase
                job["error"] = payload.get("error")
        elif event == "issue_completed":
            if job:
                job["status"] = "completed"
                job["completed_at"] = timestamp
        elif event == "skipped":
            if job:
                job["phase"] = phase

    _broadcast_sse(payload)


def _get_queue_snapshot() -> dict:
    """Return a snapshot of the full queue state from memory."""
    with _state_lock:
        manifest = _pipeline_state["manifest"]
        jobs_list = sorted(
            _pipeline_state["jobs"].values(),
            key=lambda j: (j["key"], j["model"]),
        )
        counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        for j in jobs_list:
            s = j["status"]
            if s in counts:
                counts[s] += 1

        # Per-model breakdown
        model_counts: dict[str, dict[str, int]] = {}
        for j in jobs_list:
            m = j["model"]
            if m not in model_counts:
                model_counts[m] = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
            s = j["status"]
            if s in model_counts[m]:
                model_counts[m][s] += 1

        return {
            "running": _pipeline_state["running"],
            "manifest": manifest,
            "total_jobs": len(jobs_list),
            "counts": counts,
            "model_counts": model_counts,
            "jobs": jobs_list,
        }

# ---------------------------------------------------------------------------
# Jinja2 templates (inline — no templates directory needed)
# ---------------------------------------------------------------------------

LAYOUT = """\
<!doctype html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Pipeline Dashboard{% endblock %}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    :root { --pico-font-size: 87.5%; }
    nav { margin-bottom: 1rem; }
    .score-red { color: #c0392b; font-weight: bold; }
    .score-yellow { color: #d4a017; font-weight: bold; }
    .score-green { color: #27ae60; font-weight: bold; }
    .badge {
      display: inline-block; padding: 0.15em 0.5em; border-radius: 4px;
      font-size: 0.85em; font-weight: 600;
    }
    .badge-bug { background: #e74c3c; color: #fff; }
    .badge-enhancement { background: #3498db; color: #fff; }
    .badge-feature-request { background: #9b59b6; color: #fff; }
    .badge-task { background: #7f8c8d; color: #fff; }
    .badge-default { background: #95a5a6; color: #fff; }
    .badge-fix-ai-fixable { background: #27ae60; color: #fff; }
    .badge-fix-already-fixed { background: #2980b9; color: #fff; }
    .badge-fix-not-a-bug { background: #8e44ad; color: #fff; }
    .badge-fix-docs-only { background: #16a085; color: #fff; }
    .badge-fix-upstream-required { background: #d35400; color: #fff; }
    .badge-fix-insufficient-info { background: #f39c12; color: #fff; }
    .badge-fix-ai-could-not-fix { background: #c0392b; color: #fff; }
    .badge-val-pass { background: #27ae60; color: #fff; }
    .badge-val-fail { background: #c0392b; color: #fff; }
    .badge-val-skip { background: #95a5a6; color: #fff; }
    .badge-val-timeout { background: #d35400; color: #fff; }
    .val-cmd { margin-bottom: 0.8em; padding: 0.5em; border-radius: 4px; font-size: 0.9em; }
    .val-cmd-pass { background: #eafaf1; border-left: 3px solid #27ae60; }
    .val-cmd-fail { background: #fdedec; border-left: 3px solid #c0392b; }
    .badge-correction { background: #e67e22; color: #fff; }
    .badge-approach-change { background: #c0392b; color: #fff; }
    .badge-minor-fix { background: #27ae60; color: #fff; }
    .correction-block { padding: 0.5em; margin-bottom: 0.8em; border-left: 3px solid #e67e22; background: #fef5e7; border-radius: 4px; font-size: 0.9em; }
    .correction-block p { margin-bottom: 0.3em; }
    .val-cmd code { font-size: 0.85em; }
    .val-cmd pre { font-size: 0.8em; max-height: 12em; overflow-y: auto; margin: 0.3em 0 0 0; }
    table { font-size: 0.9em; }
    th.sortable { cursor: pointer; user-select: none; }
    th.sortable:hover { text-decoration: underline; }
    th.sortable::after { content: ' \\2195'; opacity: 0.3; }
    .truncate { max-width: 300px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .filter-bar { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; align-items: end; }
    .filter-bar label { margin-bottom: 0; }
    .filter-bar select { margin-bottom: 0; padding: 0.4em 0.6em; }
    details { margin-bottom: 1rem; }
    summary { font-weight: 600; font-size: 1.1em; cursor: pointer; }
    .detail-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; align-items: start; }
    @media (max-width: 1200px) { .detail-columns { grid-template-columns: 1fr; } }
    .detail-left, .detail-right { min-width: 0; }
    .issue-text { font-size: 0.9em; padding: 0.5em; background: #f8f9fa; border-radius: 4px; }
    .issue-text p { margin-bottom: 0.5em; }
    .issue-text pre { background: #1e1e1e; color: #f0f0f0; padding: 0.8em; border-radius: 4px; overflow-x: auto; font-size: 0.9em; }
    .issue-text code { background: #e8e8e8; padding: 0.1em 0.3em; border-radius: 3px; font-size: 0.9em; }
    .issue-text pre code { background: none; padding: 0; color: inherit; }
    .issue-text blockquote { border-left: 3px solid #bbb; margin: 0.5em 0; padding-left: 0.8em; color: #555; }
    .issue-text table { font-size: 0.85em; }
    .issue-text h1, .issue-text h2, .issue-text h3, .issue-text h4, .issue-text h5, .issue-text h6 { margin-top: 0.8em; margin-bottom: 0.3em; }
    .issue-text ul, .issue-text ol { margin: 0.3em 0; padding-left: 1.5em; }
    .issue-text img { max-width: 100%; }
    .action-bar {
      padding: 0.5em 1em;
      margin-bottom: 0.5em;
      background: #fff3cd;
      border: 1px solid #ffc107;
      border-radius: 4px;
      display: flex;
      align-items: center;
      gap: 1em;
    }
    .btn-reset {
      background: #c0392b;
      color: white;
      border: none;
      padding: 0.3em 1em;
      border-radius: 4px;
      cursor: pointer;
    }
    .comment-block { font-size: 0.9em; padding: 0.5em; margin-bottom: 0.5em; background: #f0f4f8; border-radius: 4px; border-left: 3px solid #3498db; }
    .comment-block p { margin-bottom: 0.3em; }
    .comment-meta { font-size: 0.85em; color: #555; margin-bottom: 0.3em; }
    pre.patch {
      background: #1e1e1e; color: #d4d4d4; padding: 1em;
      border-radius: 6px; overflow-x: auto; font-size: 0.85em;
    }
    pre.patch .diff-add { color: #6a9955; }
    pre.patch .diff-del { color: #f44747; }
    pre.patch .diff-hunk { color: #569cd6; }
    .score-bar {
      background: #ecf0f1; border-radius: 4px; height: 1.4em;
      position: relative; overflow: hidden; min-width: 120px;
    }
    .score-bar-fill {
      height: 100%; border-radius: 4px;
      display: flex; align-items: center; justify-content: center;
      font-size: 0.8em; font-weight: bold; color: #fff;
      min-width: 2em;
    }
    /* --- Type badges --- */
    .badge-type-bug { background: #e74c3c; color: #fff; }
    .badge-type-rfe { background: #3498db; color: #fff; }
    .badge-type-strategy { background: #9b59b6; color: #fff; }
    /* --- Size badges --- */
    .badge-size-s { background: #27ae60; color: #fff; }
    .badge-size-m { background: #f1c40f; color: #333; }
    .badge-size-l { background: #e67e22; color: #fff; }
    .badge-size-xl { background: #e74c3c; color: #fff; }
    /* --- Recommendation badges --- */
    .badge-rec-submit, .badge-rec-approve { background: #27ae60; color: #fff; }
    .badge-rec-revise { background: #f1c40f; color: #333; }
    .badge-rec-split { background: #3498db; color: #fff; }
    .badge-rec-reject { background: #e74c3c; color: #fff; }
    /* --- Feasibility badges --- */
    .badge-feas-feasible { background: #27ae60; color: #fff; }
    .badge-feas-infeasible { background: #e74c3c; color: #fff; }
    .badge-feas-indeterminate { background: #95a5a6; color: #fff; }
    /* --- Security badges --- */
    .badge-sec-pass { background: #27ae60; color: #fff; }
    .badge-sec-concerns { background: #f1c40f; color: #333; }
    .badge-sec-fail { background: #e74c3c; color: #fff; }
    /* --- Tier badges --- */
    .badge-tier-light { background: #95a5a6; color: #fff; }
    .badge-tier-standard { background: #3498db; color: #fff; }
    .badge-tier-deep { background: #8e44ad; color: #fff; }
    /* --- Rubric dots --- */
    .rubric-dot {
      display: inline-block; width: 12px; height: 12px;
      border-radius: 50%; vertical-align: middle;
    }
    .rubric-0 { background: #e74c3c; }
    .rubric-1 { background: #f1c40f; }
    .rubric-2 { background: #27ae60; }
    /* --- Tab navigation --- */
    .tab-nav {
      display: flex; border-bottom: 2px solid #ddd;
      margin-bottom: 1rem; gap: 0;
    }
    .tab-nav button {
      background: none; border: none; border-bottom: 3px solid transparent;
      padding: 0.6em 1.2em; cursor: pointer;
      font-size: 0.95em; font-weight: 600; color: #555;
    }
    .tab-nav button:hover { color: #111; background: rgba(0,0,0,0.03); }
    .tab-nav button.active {
      color: #111; border-bottom-color: #3498db;
    }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }
    /* --- Attention flag --- */
    .attention-flag { color: #e74c3c; font-weight: bold; }
  </style>
</head>
<body>
  <nav class="container-fluid">
    <ul><li><strong><a href="/">Pipeline Dashboard</a></strong></li></ul>
    <ul><li><a href="/">Dashboard</a></li><li><a href="/activity">Activity</a></li><li><a href="/readiness">Readiness</a></li><li><a href="/stats">Stats</a></li><li><a href="/summary">Summary</a></li></ul>
  </nav>
  <main class="container-fluid">
    {% block content %}{% endblock %}
  </main>
  {% block scripts %}{% endblock %}
</body>
</html>
"""

DASHBOARD = """\
{% extends "layout.html" %}
{% block title %}Pipeline Dashboard{% endblock %}
{% block content %}
<style>
  #issues-table tr.pipeline-pending td { background: rgba(0, 0, 0, 0.05); }
  #issues-table tr.pipeline-pending td:first-child { box-shadow: inset 3px 0 0 #bbb; }
  #issues-table tr.pipeline-active td { background: rgba(39, 174, 96, 0.12); animation: pulse-green 2s ease-in-out infinite; }
  #issues-table tr.pipeline-active td:first-child { box-shadow: inset 3px 0 0 #27ae60; }
  @keyframes pulse-green { 0%,100% { background: rgba(39,174,96,0.06); } 50% { background: rgba(39,174,96,0.18); } }
</style>

<div class="tab-nav">
  <button class="active" onclick="switchTab('all')">All Issues ({{ all_issues|length }})</button>
  <button onclick="switchTab('rfes')">RFEs ({{ rfe_issues|length }})</button>
  <button onclick="switchTab('strategies')">Strategies ({{ strat_issues|length }})</button>
  <button onclick="switchTab('bugs')">Bugs ({{ rows|length }})</button>
</div>

<div id="tab-all" class="tab-panel active">
  {% include "tab_all.html" %}
</div>
<div id="tab-rfes" class="tab-panel">
  {% include "tab_rfes.html" %}
</div>
<div id="tab-strategies" class="tab-panel">
  {% include "tab_strategies.html" %}
</div>
<div id="tab-bugs" class="tab-panel">
  {% include "tab_bugs.html" %}
</div>
{% endblock %}

{% block scripts %}
<script>
// --- Tab switching ---
function switchTab(name) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-nav button').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  // Find the clicked button by matching tab name in onclick
  document.querySelectorAll('.tab-nav button').forEach(b => {
    if (b.getAttribute('onclick') === "switchTab('" + name + "')") b.classList.add('active');
  });
  window.location.hash = name;
}
// Restore tab from URL hash
(function() {
  const hash = window.location.hash.replace('#', '');
  if (hash && document.getElementById('tab-' + hash)) switchTab(hash);
})();

// --- Generic sorting for any table ---
function setupSorting(tableId) {
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
          va = (a.cells[col]?.textContent || '').trim().toLowerCase();
          vb = (b.cells[col]?.textContent || '').trim().toLowerCase();
        }
        if (va < vb) return asc ? -1 : 1;
        if (va > vb) return asc ? 1 : -1;
        return 0;
      });
      rows.forEach(r => tbody.appendChild(r));
    });
  });
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

// Init sorting on all tables
setupSorting('all-table');
setupSorting('issues-table');
setupSorting('rfe-table');
setupSorting('strat-table');
</script>
{% endblock %}
"""

# ---------------------------------------------------------------------------
# Tab templates — included by DASHBOARD via {% include %}
# ---------------------------------------------------------------------------

TAB_ALL_ISSUES = """\
<h2>All Issues (<span id="all-row-count">{{ all_issues|length }}</span>)</h2>
<div class="filter-bar" id="all-filter-bar">
  <label>
    Type
    <select data-attr="type" onchange="applyTabFilters('all-table','all-filter-bar','all-row-count')">
      <option value="">All</option>
      <option value="bug">Bug</option>
      <option value="rfe">RFE</option>
      <option value="strategy">Strategy</option>
    </select>
  </label>
  <label>
    Status
    <select data-attr="status" onchange="applyTabFilters('all-table','all-filter-bar','all-row-count')">
      <option value="">All</option>
      {% for v in all_statuses %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Priority
    <select data-attr="priority" onchange="applyTabFilters('all-table','all-filter-bar','all-row-count')">
      <option value="">All</option>
      {% for v in all_priorities %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Search
    <input type="text" oninput="applyTabFilters('all-table','all-filter-bar','all-row-count')" placeholder="text search&hellip;" style="margin-bottom:0; padding:0.4em 0.6em;">
  </label>
</div>
<div style="overflow-x:auto;">
<table role="grid" id="all-table">
  <thead>
    <tr>
      <th class="sortable" data-col="0">Type</th>
      <th class="sortable" data-col="1">Key</th>
      <th class="sortable" data-col="2">Summary</th>
      <th class="sortable" data-col="3">Status</th>
      <th class="sortable" data-col="4">Priority</th>
      <th class="sortable" data-col="5" data-type="number">Quality</th>
      <th class="sortable" data-col="6">Recommendation</th>
      <th class="sortable" data-col="7">Security</th>
      <th class="sortable" data-col="8">Attention</th>
    </tr>
  </thead>
  <tbody>
    {% for item in all_issues %}
    <tr data-type="{{ item.type }}" data-status="{{ item.status }}" data-priority="{{ item.priority }}">
      <td><span class="badge badge-type-{{ item.type }}">{{ item.type }}</span></td>
      <td><a href="{{ item.detail_url }}">{{ item.key }}</a></td>
      <td class="truncate" title="{{ item.title }}">{{ item.title[:80] }}{% if item.title|length > 80 %}&hellip;{% endif %}</td>
      <td>{{ item.status }}</td>
      <td>{{ item.priority }}</td>
      <td data-sort-value="{{ item.quality_score }}">
        <span class="{{ item.quality_class }}">{{ item.quality_display }}</span>
      </td>
      <td>
        {% if item.recommendation %}
          <span class="badge badge-rec-{{ item.recommendation }}">{{ item.recommendation }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      <td>
        {% if item.security_verdict %}
          <span class="badge badge-sec-{{ item.security_verdict|lower }}">{{ item.security_verdict }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      <td>
        {% if item.attention %}<span class="attention-flag">&#9888;</span>{% else %}&mdash;{% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
</div>
"""

TAB_BUGS = """\
<h2>Bugs (<span id="bug-row-count">{{ rows|length }}</span>)</h2>

<div class="filter-bar">
  <label>
    Model
    <select id="filter-model" onchange="applyBugFilters()">
      <option value="">All</option>
      {% for v in model_names %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Status
    <select id="filter-status" onchange="applyBugFilters()">
      <option value="">All</option>
      {% for v in statuses %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Triage
    <select id="filter-triage" onchange="applyBugFilters()">
      <option value="">All</option>
      {% for v in triages %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Issue Type
    <select id="filter-issuetype" onchange="applyBugFilters()">
      <option value="">All</option>
      {% for v in issue_types %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Component
    <select id="filter-component" onchange="applyBugFilters()">
      <option value="">All</option>
      {% for v in components %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Arch Context
    <select id="filter-context" onchange="applyBugFilters()">
      <option value="">All</option>
      {% for v in context_ratings %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Arch Docs
    <select id="filter-archdocs" onchange="applyBugFilters()">
      <option value="">All</option>
      {% for v in arch_docs_values %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Src Code
    <select id="filter-srccode" onchange="applyBugFilters()">
      <option value="">All</option>
      {% for v in src_code_values %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Fix
    <select id="filter-fix" onchange="applyBugFilters()">
      <option value="">All</option>
      {% for v in fix_recommendations %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Test Context
    <select id="filter-testctx" onchange="applyBugFilters()">
      <option value="">All</option>
      {% for v in test_context_ratings %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Write Test
    <select id="filter-writetest" onchange="applyBugFilters()">
      <option value="">All</option>
      {% for v in write_test_decisions %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    AI Eligible
    <select id="filter-eligible" onchange="applyBugFilters()">
      <option value="">All</option>
      <option value="yes">Eligible for fix</option>
      <option value="no">Excluded from fix</option>
    </select>
  </label>
  <label>
    Search
    <input type="text" id="filter-text" oninput="applyBugFilters()" placeholder="text search&hellip;" style="margin-bottom:0; padding:0.4em 0.6em;">
  </label>
</div>

<div class="action-bar" id="action-bar" style="display:none;">
  <span id="selected-count">0</span> selected &mdash;
  <button class="btn-reset" onclick="confirmReset()">Reset Selected</button>
</div>

<dialog id="reset-modal">
  <article>
    <h3>Reset Workspace</h3>
    <p>This will delete all analysis results (completeness, context-map,
    fix-attempt, test-plan, write-test) for <strong id="reset-count">0</strong>
    issue&times;model pairs. They will be re-processed on the next pipeline run.</p>
    <p id="reset-list" style="max-height:200px; overflow-y:auto; font-size:0.85em;"></p>
    <footer>
      <button class="secondary" onclick="document.getElementById('reset-modal').close()">Cancel</button>
      <button onclick="executeReset()">Confirm Reset</button>
    </footer>
  </article>
</dialog>

<div style="overflow-x:auto;">
<table role="grid" id="issues-table">
  <thead>
    <tr>
      <th><input type="checkbox" id="select-all" onchange="toggleSelectAll(this)"></th>
      <th class="sortable" data-col="1">Key</th>
      <th class="sortable" data-col="2">Model</th>
      <th class="sortable" data-col="3">Summary</th>
      <th class="sortable" data-col="4">Status</th>
      <th class="sortable" data-col="5">Priority</th>
      <th class="sortable" data-col="6">Components</th>
      <th class="sortable" data-col="7">Issue<br>Type</th>
      <th class="sortable" data-col="8" data-type="number">Bug<br>Quality</th>
      <th class="sortable" data-col="9">AI<br>Type</th>
      <th class="sortable" data-col="10">Triage</th>
      <th class="sortable" data-col="11">Arch<br>Context</th>
      <th class="sortable" data-col="12" data-type="number">Arch<br>Quality</th>
      <th class="sortable" data-col="13">Arch<br>Docs</th>
      <th class="sortable" data-col="14">Src<br>Code</th>
      <th class="sortable" data-col="15">Test<br>Context</th>
      <th class="sortable" data-col="16">Fix</th>
      <th class="sortable" data-col="17">Confidence</th>
      <th class="sortable" data-col="18">Test<br>Effort</th>
      <th class="sortable" data-col="19">Write<br>Test</th>
      <th class="sortable" data-col="20">Processed</th>
    </tr>
  </thead>
  <tbody>
    {% for row in rows %}
    <tr
      data-key="{{ row.key }}"
      data-model="{{ row.model }}"
      data-status="{{ row.status }}"
      data-triage="{{ row.completeness.triage_recommendation if row.completeness else '' }}"
      data-issuetype="{{ row.completeness.issue_type_assessment.classified_type if row.completeness and row.completeness.issue_type_assessment else '' }}"
      data-components="{{ row.components|join('||') }}"
      data-context="{{ row.context_map.overall_rating if row.context_map and row.context_map.overall_rating is defined else '' }}"
      data-fix="{{ row.fix_attempt.recommendation if row.fix_attempt and row.fix_attempt.recommendation is defined else '' }}"
      data-testctx="{{ row.test_context_rating }}"
      data-archdocs="{{ row.arch_docs }}"
      data-srccode="{{ row.src_code }}"
      data-writetest="{{ row.write_test.decision if row.write_test and row.write_test.decision is defined else '' }}"
      data-eligible="{% if row.status in ['In Progress', 'Review', 'Testing', 'Closed', 'Done'] %}no{% elif row.completeness and row.completeness.overall_score is defined and row.completeness.overall_score < 5 %}no{% elif row.context_map and row.context_map.overall_rating == 'no-context' %}no{% else %}yes{% endif %}"
    >
      <td><input type="checkbox" class="row-select" data-key="{{ row.key }}" data-model="{{ row.model }}"></td>
      <td><a href="/issue/{{ row.key }}{% if row.model %}?model={{ row.model }}{% endif %}">{{ row.key }}</a></td>
      <td>{{ row.model or '&mdash;'|safe }}</td>
      <td class="truncate" title="{{ row.summary }}">{{ row.summary[:80] }}{% if row.summary|length > 80 %}&hellip;{% endif %}</td>
      <td>{{ row.status }}</td>
      <td>{{ row.priority }}</td>
      <td>{{ row.components|join(', ') }}</td>
      <td>{{ row.issue_type }}</td>
      <td data-sort-value="{{ row.completeness.overall_score if row.completeness and row.completeness.overall_score is defined else -1 }}">
        {% if row.completeness and row.completeness.overall_score is defined %}
          {% set score = row.completeness.overall_score %}
          <span class="{{ 'score-red' if score < 40 else ('score-yellow' if score < 80 else 'score-green') }}">{{ score }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      <td>
        {% if row.completeness and row.completeness.issue_type_assessment %}
          {% set itype = row.completeness.issue_type_assessment.classified_type %}
          <span class="badge badge-{{ itype if itype in ('bug','enhancement','feature-request','task') else 'default' }}">{{ itype }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      <td>{{ row.completeness.triage_recommendation if row.completeness and row.completeness.triage_recommendation is defined else '&mdash;'|safe }}</td>
      <td>{{ row.context_map.overall_rating if row.context_map and row.context_map.overall_rating is defined else '&mdash;'|safe }}</td>
      <td data-sort-value="{{ row.context_map.context_helpfulness.overall_score if row.context_map and row.context_map.context_helpfulness else -1 }}">
        {% if row.context_map and row.context_map.context_helpfulness %}
          {% set hs = row.context_map.context_helpfulness.overall_score %}
          <span class="{{ 'score-red' if hs < 40 else ('score-yellow' if hs < 80 else 'score-green') }}">{{ hs }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      <td>
        {% if row.arch_docs %}
          <span class="badge {{ 'badge-val-pass' if row.arch_docs == 'all' else ('badge-default' if row.arch_docs == 'partial' else 'badge-val-fail') }}">{{ row.arch_docs }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      <td>
        {% if row.src_code %}
          <span class="badge {{ 'badge-val-pass' if row.src_code == 'all' else ('badge-default' if row.src_code == 'partial' else 'badge-val-fail') }}">{{ row.src_code }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      <td>
        {% if row.test_context_rating %}
          <span class="badge {{ 'badge-val-pass' if row.test_context_rating == 'high' else ('badge-default' if row.test_context_rating == 'medium' else 'badge-val-fail') }}">{{ row.test_context_rating }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      <td>
        {% if row.fix_attempt %}
          <span class="badge badge-fix-{{ row.fix_attempt.recommendation }}">{{ row.fix_attempt.recommendation }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      <td>{{ row.fix_attempt.confidence if row.fix_attempt and row.fix_attempt.confidence is defined else '&mdash;'|safe }}</td>
      <td>{{ row.test_plan.effort_estimate if row.test_plan and row.test_plan.effort_estimate is defined else '&mdash;'|safe }}</td>
      <td>
        {% if row.write_test %}
          <span class="badge {{ 'badge-val-pass' if row.write_test.decision == 'write-test' else 'badge-default' }}">{{ row.write_test.decision }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      <td>{{ row.last_processed or '&mdash;'|safe }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
</div>
"""

TAB_RFES = """\
<h2>RFEs (<span id="rfe-row-count">{{ rfe_issues|length }}</span>)</h2>
<div class="filter-bar" id="rfe-filter-bar">
  <label>
    Status
    <select data-attr="status" onchange="applyTabFilters('rfe-table','rfe-filter-bar','rfe-row-count')">
      <option value="">All</option>
      {% for v in rfe_statuses %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Priority
    <select data-attr="priority" onchange="applyTabFilters('rfe-table','rfe-filter-bar','rfe-row-count')">
      <option value="">All</option>
      {% for v in rfe_priorities %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Size
    <select data-attr="size" onchange="applyTabFilters('rfe-table','rfe-filter-bar','rfe-row-count')">
      <option value="">All</option>
      <option value="S">S</option><option value="M">M</option>
      <option value="L">L</option><option value="XL">XL</option>
    </select>
  </label>
  <label>
    Recommendation
    <select data-attr="recommendation" onchange="applyTabFilters('rfe-table','rfe-filter-bar','rfe-row-count')">
      <option value="">All</option>
      {% for v in rfe_recommendations %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Feasibility
    <select data-attr="feasibility" onchange="applyTabFilters('rfe-table','rfe-filter-bar','rfe-row-count')">
      <option value="">All</option>
      <option value="feasible">feasible</option>
      <option value="infeasible">infeasible</option>
      <option value="indeterminate">indeterminate</option>
    </select>
  </label>
  <label>
    Pass/Fail
    <select data-attr="pass" onchange="applyTabFilters('rfe-table','rfe-filter-bar','rfe-row-count')">
      <option value="">All</option>
      <option value="true">Pass</option>
      <option value="false">Fail</option>
    </select>
  </label>
  <label>
    Attention
    <select data-attr="attention" onchange="applyTabFilters('rfe-table','rfe-filter-bar','rfe-row-count')">
      <option value="">All</option>
      <option value="true">Needs Attention</option>
    </select>
  </label>
  <label>
    Search
    <input type="text" oninput="applyTabFilters('rfe-table','rfe-filter-bar','rfe-row-count')" placeholder="text search&hellip;" style="margin-bottom:0; padding:0.4em 0.6em;">
  </label>
</div>
<div style="overflow-x:auto;">
<table role="grid" id="rfe-table">
  <thead>
    <tr>
      <th class="sortable" data-col="0">Key</th>
      <th class="sortable" data-col="1">Title</th>
      <th class="sortable" data-col="2">Priority</th>
      <th class="sortable" data-col="3">Size</th>
      <th class="sortable" data-col="4">Status</th>
      <th class="sortable" data-col="5" data-type="number">Score</th>
      <th class="sortable" data-col="6">Pass</th>
      <th class="sortable" data-col="7">Recommendation</th>
      <th class="sortable" data-col="8">Feasibility</th>
      <th class="sortable" data-col="9">WHAT</th>
      <th class="sortable" data-col="10">WHY</th>
      <th class="sortable" data-col="11">HOW</th>
      <th class="sortable" data-col="12">Not Task</th>
      <th class="sortable" data-col="13">Right-Sized</th>
      <th class="sortable" data-col="14">Auto-Revised</th>
      <th class="sortable" data-col="15">Attention</th>
      <th class="sortable" data-col="16" data-type="number">Delta</th>
    </tr>
  </thead>
  <tbody>
    {% for rfe in rfe_issues %}
    {% set rev = rfe.review %}
    <tr
      data-status="{{ rfe.status|default('') }}"
      data-priority="{{ rfe.priority|default('') }}"
      data-size="{{ rfe.size|default('') }}"
      data-recommendation="{{ rev.recommendation if rev else '' }}"
      data-feasibility="{{ rev.feasibility if rev else '' }}"
      data-pass="{{ rev.pass|string|lower if rev and rev.pass is defined else '' }}"
      data-attention="{{ rev.needs_attention|string|lower if rev and rev.needs_attention is defined else 'false' }}"
    >
      <td><a href="/rfe/{{ rfe.key }}">{{ rfe.key }}</a></td>
      <td class="truncate" title="{{ rfe.title|default('') }}">{{ rfe.title|default('')|truncate(80) }}</td>
      <td>{{ rfe.priority|default('&mdash;'|safe) }}</td>
      <td>
        {% if rfe.size %}
          <span class="badge badge-size-{{ rfe.size|lower }}">{{ rfe.size }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      <td>{{ rfe.status|default('&mdash;'|safe) }}</td>
      <td data-sort-value="{{ rev.score if rev and rev.score is defined else -1 }}">
        {% if rev and rev.score is defined %}
          {% set sc = rev.score %}
          <span class="{{ 'score-red' if sc < 5 else ('score-yellow' if sc < 8 else 'score-green') }}">{{ sc }}/10</span>
        {% else %}&mdash;{% endif %}
      </td>
      <td>
        {% if rev and rev.pass is defined %}
          {% if rev.pass %}&#10003;{% else %}&#10007;{% endif %}
        {% else %}&mdash;{% endif %}
      </td>
      <td>
        {% if rev and rev.recommendation %}
          <span class="badge badge-rec-{{ rev.recommendation }}">{{ rev.recommendation }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      <td>
        {% if rev and rev.feasibility %}
          <span class="badge badge-feas-{{ rev.feasibility }}">{{ rev.feasibility }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      {# Rubric dots: WHAT, WHY, HOW, Not Task, Right-Sized #}
      {% for dim in ['what','why','open_to_how','not_a_task','right_sized'] %}
      <td>
        {% if rev and rev.scores and rev.scores[dim] is defined %}
          <span class="rubric-dot rubric-{{ rev.scores[dim] }}" title="{{ dim }}: {{ rev.scores[dim] }}/2"></span>
        {% else %}&mdash;{% endif %}
      </td>
      {% endfor %}
      <td>
        {% if rev and rev.auto_revised %}
          <span class="badge badge-rec-split">yes</span>
        {% elif rev %}no{% else %}&mdash;{% endif %}
      </td>
      <td>
        {% if rev and rev.needs_attention %}<span class="attention-flag">&#9888;</span>{% else %}&mdash;{% endif %}
      </td>
      <td data-sort-value="{{ (rev.score - rev.before_score) if rev and rev.score is not none and rev.before_score is not none else 0 }}">
        {% if rev and rev.score is not none and rev.before_score is not none %}
          {% set delta = rev.score - rev.before_score %}
          {% if delta > 0 %}+{{ delta }}{% else %}{{ delta }}{% endif %}
        {% else %}&mdash;{% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
</div>
"""

RFE_DETAIL = """\
{% extends "layout.html" %}
{% block title %}{{ rfe.key }} - RFE Detail{% endblock %}
{% block content %}
{% set rev = rfe.review %}
<hgroup>
  <h2>{{ rfe.key }}: {{ rfe.title|default('Untitled RFE') }}</h2>
</hgroup>
<p><a href="/">&larr; Back to dashboard</a></p>

{# --- Issue metadata --- #}
<div style="display:flex; gap:1.5rem; flex-wrap:wrap; margin-bottom:1rem; font-size:0.95em;">
  <span><strong>Priority:</strong> {{ rfe.priority|default('—') }}</span>
  <span><strong>Size:</strong> {% if rfe.size %}<span class="badge badge-size-{{ rfe.size|lower }}">{{ rfe.size }}</span>{% else %}—{% endif %}</span>
  <span><strong>Status:</strong> {{ rfe.status|default('—') }}</span>
</div>

{# =============== Score Summary (always visible) =============== #}
{% if rev %}
<div style="background:#f8f9fa; border-radius:6px; padding:1rem; margin-bottom:1.5rem;">
  <div style="display:flex; gap:2rem; flex-wrap:wrap; align-items:start;">

    {# -- Score bar + rubric -- #}
    <div style="flex:1; min-width:250px;">
      {% if rev.score is not none %}
      {% set sc = rev.score %}
      {% set pct = (sc * 10)|int %}
      {% set bar_color = '#c0392b' if sc < 5 else ('#d4a017' if sc < 8 else '#27ae60') %}
      <div style="margin-bottom:0.8em;">
        <strong>Overall: </strong>
        <span class="{{ 'score-red' if sc < 5 else ('score-yellow' if sc < 8 else 'score-green') }}">{{ sc }}/10</span>
        <div class="score-bar" style="margin-top:0.3em;">
          <div class="score-bar-fill" style="width:{{ pct }}%; background:{{ bar_color }};">{{ sc }}/10</div>
        </div>
      </div>
      {% endif %}
      <div style="display:flex; gap:0.8rem; flex-wrap:wrap; font-size:0.9em;">
        {% for dim_key, dim_label in [('what','WHAT'),('why','WHY'),('open_to_how','HOW'),('not_a_task','Not Task'),('right_sized','Right-Sized')] %}
        <span>
          {{ dim_label }}:
          {% if rev.scores and rev.scores[dim_key] is defined %}
            <span class="rubric-dot rubric-{{ rev.scores[dim_key] }}" title="{{ rev.scores[dim_key] }}/2"></span>
            {{ rev.scores[dim_key] }}/2
            {% if rev.auto_revised and rev.before_scores and rev.before_scores[dim_key] is defined %}
              <span style="opacity:0.5;" title="before">(was {{ rev.before_scores[dim_key] }}/2)</span>
            {% endif %}
          {% else %}—{% endif %}
        </span>
        {% endfor %}
      </div>
    </div>

    {# -- Verdict badges -- #}
    <div style="display:flex; gap:0.6rem; flex-wrap:wrap; align-items:center; font-size:0.9em;">
      {% if rev.pass is defined %}
        {% if rev.pass %}<span class="badge badge-val-pass">PASS</span>
        {% else %}<span class="badge badge-val-fail">FAIL</span>{% endif %}
      {% endif %}
      {% if rev.recommendation %}
        <span class="badge badge-rec-{{ rev.recommendation }}">{{ rev.recommendation }}</span>
      {% endif %}
      {% if rev.feasibility %}
        <span class="badge badge-feas-{{ rev.feasibility }}">{{ rev.feasibility }}</span>
      {% endif %}
      {% if rev.auto_revised %}
        <span class="badge badge-rec-split">auto-revised</span>
        {% if rev.before_score is not none %}
          <span style="font-size:0.85em; opacity:0.7;">(was {{ rev.before_score }}/10)</span>
        {% endif %}
      {% endif %}
    </div>

  </div>
</div>
{% else %}
<p><em>No review data available for this RFE.</em></p>
{% endif %}

{# =============== Content Tabs =============== #}
<div class="tab-nav" id="rfe-tab-nav">
  <button class="active" onclick="switchRfeTab('feedback')">Assessor Feedback</button>
  <button onclick="switchRfeTab('feasibility')">Feasibility</button>
  <button onclick="switchRfeTab('original')">Original Description</button>
  <button onclick="switchRfeTab('revised')">New Description</button>
  {% if rfe.comments_body %}<button onclick="switchRfeTab('comments')">Comments</button>{% endif %}
</div>

<div id="rfe-tab-feedback" class="tab-panel active">
{% if rev and rev._body %}
  <div class="issue-text md-content">{{ rev._body|e }}</div>
{% else %}
  <p><em>No assessor feedback available.</em></p>
{% endif %}
</div>

<div id="rfe-tab-feasibility" class="tab-panel">
{% if rfe.feasibility_body %}
  <div class="issue-text md-content">{{ rfe.feasibility_body|e }}</div>
{% else %}
  <p><em>No feasibility analysis available.</em></p>
{% endif %}
</div>

<div id="rfe-tab-original" class="tab-panel">
{% if rfe.original_body %}
  <div class="issue-text md-content">{{ rfe.original_body|e }}</div>
{% else %}
  <p><em>No original description available.</em></p>
{% endif %}
</div>

<div id="rfe-tab-revised" class="tab-panel">
  <div class="issue-text md-content">{{ rfe._body|default('No content available.')|e }}</div>
</div>

{% if rfe.comments_body %}
<div id="rfe-tab-comments" class="tab-panel">
  <div class="issue-text md-content">{{ rfe.comments_body|e }}</div>
</div>
{% endif %}

{% endblock %}

{% block scripts %}
<script>
function switchRfeTab(name) {
  document.querySelectorAll('#rfe-tab-nav ~ .tab-panel').forEach(function(p) {
    p.classList.remove('active');
  });
  document.querySelectorAll('#rfe-tab-nav button').forEach(function(b) {
    b.classList.remove('active');
  });
  document.getElementById('rfe-tab-' + name).classList.add('active');
  document.querySelectorAll('#rfe-tab-nav button').forEach(function(b) {
    if (b.getAttribute('onclick') === "switchRfeTab('" + name + "')") b.classList.add('active');
  });
  // Render markdown in newly-visible tab if not yet rendered
  var panel = document.getElementById('rfe-tab-' + name);
  if (typeof marked !== 'undefined') {
    panel.querySelectorAll('.md-content:not([data-rendered])').forEach(function(el) {
      el.innerHTML = marked.parse(el.textContent);
      el.setAttribute('data-rendered', '1');
    });
  }
  window.location.hash = name;
}
document.addEventListener('DOMContentLoaded', function() {
  // Render markdown in the default active tab
  if (typeof marked !== 'undefined') {
    document.querySelectorAll('.tab-panel.active .md-content').forEach(function(el) {
      el.innerHTML = marked.parse(el.textContent);
      el.setAttribute('data-rendered', '1');
    });
  }
  // Restore tab from URL hash
  var hash = window.location.hash.replace('#', '');
  if (hash && document.getElementById('rfe-tab-' + hash)) {
    switchRfeTab(hash);
  }
});
</script>
{% endblock %}
"""

TAB_STRATEGIES = """\
<h2>Strategies (<span id="strat-row-count">{{ strat_issues|length }}</span>)</h2>
<div class="filter-bar" id="strat-filter-bar">
  <label>
    Status
    <select data-attr="status" onchange="applyTabFilters('strat-table','strat-filter-bar','strat-row-count')">
      <option value="">All</option>
      {% for v in strat_statuses %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Priority
    <select data-attr="priority" onchange="applyTabFilters('strat-table','strat-filter-bar','strat-row-count')">
      <option value="">All</option>
      {% for v in strat_priorities %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Recommendation
    <select data-attr="recommendation" onchange="applyTabFilters('strat-table','strat-filter-bar','strat-row-count')">
      <option value="">All</option>
      {% for v in strat_recommendations %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
    </select>
  </label>
  <label>
    Security
    <select data-attr="secverdict" onchange="applyTabFilters('strat-table','strat-filter-bar','strat-row-count')">
      <option value="">All</option>
      <option value="PASS">PASS</option>
      <option value="CONCERNS">CONCERNS</option>
      <option value="FAIL">FAIL</option>
    </select>
  </label>
  <label>
    Search
    <input type="text" oninput="applyTabFilters('strat-table','strat-filter-bar','strat-row-count')" placeholder="text search&hellip;" style="margin-bottom:0; padding:0.4em 0.6em;">
  </label>
</div>
<div style="overflow-x:auto;">
<table role="grid" id="strat-table">
  <thead>
    <tr>
      <th class="sortable" data-col="0">Key</th>
      <th class="sortable" data-col="1">Title</th>
      <th class="sortable" data-col="2">Source RFE</th>
      <th class="sortable" data-col="3">Priority</th>
      <th class="sortable" data-col="4">Status</th>
      <th class="sortable" data-col="5">Recommendation</th>
      <th class="sortable" data-col="6">Feasibility</th>
      <th class="sortable" data-col="7">Testability</th>
      <th class="sortable" data-col="8">Scope</th>
      <th class="sortable" data-col="9">Architecture</th>
      <th class="sortable" data-col="10">Sec Verdict</th>
      <th class="sortable" data-col="11">Sec Tier</th>
      <th class="sortable" data-col="12" data-type="number">Sec Risks</th>
      <th class="sortable" data-col="13" data-type="number">Critical</th>
      <th class="sortable" data-col="14" data-type="number">High</th>
      <th class="sortable" data-col="15" data-type="number">Medium</th>
    </tr>
  </thead>
  <tbody>
    {% for st in strat_issues %}
    {% set rev = st.review %}
    {% set sec = st.security %}
    {% set reviewers = rev.reviewers if rev and rev.reviewers else {} %}
    {% set rc = sec.risk_count if sec and sec.risk_count else {} %}
    {% set total_risks = (rc.critical|default(0)) + (rc.high|default(0)) + (rc.medium|default(0)) %}
    <tr
      data-status="{{ st.status|default('') }}"
      data-priority="{{ st.priority|default('') }}"
      data-recommendation="{{ rev.recommendation if rev and rev.recommendation else '' }}"
      data-secverdict="{{ sec.verdict|default('')|upper if sec else '' }}"
    >
      <td>{{ st.key }}</td>
      <td class="truncate" title="{{ st.title|default('') }}">{{ st.title|default('')|truncate(80) }}</td>
      <td>{{ st.source_rfe|default('&mdash;'|safe) }}</td>
      <td>{{ st.priority|default('&mdash;'|safe) }}</td>
      <td>{{ st.status|default('&mdash;'|safe) }}</td>
      <td>
        {% if rev and rev.recommendation %}
          <span class="badge badge-rec-{{ rev.recommendation }}">{{ rev.recommendation }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      {# Reviewer verdicts: feasibility, testability, scope, architecture #}
      {% for rname in ['feasibility','testability','scope','architecture'] %}
      <td>
        {% if reviewers[rname] %}
          <span class="badge badge-rec-{{ reviewers[rname] }}">{{ reviewers[rname] }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      {% endfor %}
      <td>
        {% if sec and sec.verdict %}
          <span class="badge badge-sec-{{ sec.verdict|lower }}">{{ sec.verdict }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      <td>
        {% if sec and sec.review_tier %}
          <span class="badge badge-tier-{{ sec.review_tier }}">{{ sec.review_tier }}</span>
        {% else %}&mdash;{% endif %}
      </td>
      <td data-sort-value="{{ total_risks }}">
        <span class="{{ 'score-green' if total_risks == 0 else ('score-yellow' if total_risks <= 2 else 'score-red') }}">{{ total_risks }}</span>
      </td>
      <td data-sort-value="{{ rc.critical|default(0) }}">
        <span class="{{ 'score-red' if rc.critical|default(0) > 0 else '' }}">{{ rc.critical|default(0) }}</span>
      </td>
      <td data-sort-value="{{ rc.high|default(0) }}">
        <span class="{{ 'score-red' if rc.high|default(0) > 0 else '' }}">{{ rc.high|default(0) }}</span>
      </td>
      <td data-sort-value="{{ rc.medium|default(0) }}">
        <span class="{{ 'score-yellow' if rc.medium|default(0) > 0 else '' }}">{{ rc.medium|default(0) }}</span>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
</div>
"""

DETAIL = """\
{% extends "layout.html" %}
{% block title %}{{ issue.key }} - Bug Bash{% endblock %}
{% block content %}
<hgroup>
  <h2>{{ issue.key }}: {{ issue.summary }}</h2>
</hgroup>
<p><a href="/">&larr; Back to dashboard</a></p>

{% if available_models and available_models|length > 1 %}
<div style="margin-bottom: 1rem;">
  <label><strong>Model:</strong>
    <select onchange="window.location.href='/issue/{{ issue.key }}?model=' + this.value;">
      {% for m in available_models %}
      <option value="{{ m }}"{% if m == selected_model %} selected{% endif %}>{{ m }}</option>
      {% endfor %}
    </select>
  </label>
</div>
{% elif selected_model %}
<p><strong>Model:</strong> {{ selected_model }}</p>
{% endif %}

<div class="detail-columns">

{# =============== LEFT COLUMN: Issue Data =============== #}
<div class="detail-left">

<details open>
  <summary>Issue Details</summary>
  <table>
    <tbody>
      <tr><td><strong>Status</strong></td><td>{{ issue.status }}</td></tr>
      <tr><td><strong>Priority</strong></td><td>{{ issue.priority }}</td></tr>
      <tr><td><strong>Type</strong></td><td>{{ issue.issue_type }}</td></tr>
      <tr><td><strong>Components</strong></td><td>{{ issue.components|join(', ') or '—' }}</td></tr>
      <tr><td><strong>Labels</strong></td><td>{{ issue.labels|join(', ') or '—' }}</td></tr>
      <tr><td><strong>Assignee</strong></td><td>{{ issue.assignee }}</td></tr>
      <tr><td><strong>Reporter</strong></td><td>{{ issue.reporter or '—' }}</td></tr>
      <tr><td><strong>Affected Versions</strong></td><td>{{ issue.versions|join(', ') if issue.versions else '—' }}</td></tr>
      <tr><td><strong>Fix Versions</strong></td><td>{{ issue.fix_versions|join(', ') if issue.fix_versions else '—' }}</td></tr>
      <tr><td><strong>Created</strong></td><td>{{ issue.created[:10] if issue.created else '—' }}</td></tr>
      <tr><td><strong>Updated</strong></td><td>{{ issue.updated[:10] if issue.updated else '—' }}</td></tr>
    </tbody>
  </table>
</details>

<details open>
  <summary>Description</summary>
  <div class="issue-text">{{ issue.description_html|safe }}</div>
</details>

{% if issue.comments_html %}
<details open>
  <summary>Comments ({{ issue.comments_html|length }})</summary>
  {% for comment in issue.comments_html %}
  <div class="comment-block">
    <div class="comment-meta"><strong>{{ comment.author }}</strong> &mdash; {{ comment.created[:10] if comment.created else '' }}</div>
    {{ comment.body_html|safe }}
  </div>
  {% endfor %}
</details>
{% endif %}

{% if issue.attachments %}
<details>
  <summary>Attachments ({{ issue.attachments|length }})</summary>
  <ul>
    {% for a in issue.attachments %}
    <li><code>{{ a }}</code></li>
    {% endfor %}
  </ul>
</details>
{% endif %}

</div>{# end detail-left #}

{# =============== RIGHT COLUMN: Analysis =============== #}
<div class="detail-right">

{# ---- Completeness ---- #}
<details open>
  <summary>Completeness Analysis</summary>
  {% if issue.completeness %}
    {% set c = issue.completeness %}
    {% if c.overall_score is defined %}
    <p>
      <strong>Overall Score:</strong>
      <span class="{{ 'score-red' if c.overall_score < 40 else ('score-yellow' if c.overall_score < 80 else 'score-green') }}">
        {{ c.overall_score }} / 100
      </span>
    </p>
    <div class="score-bar">
      <div class="score-bar-fill" style="width:{{ c.overall_score }}%; background:{{ '#c0392b' if c.overall_score < 40 else ('#d4a017' if c.overall_score < 80 else '#27ae60') }};">
        {{ c.overall_score }}
      </div>
    </div>
    {% else %}
    <p><em>Completeness data is incomplete (missing overall_score).</em></p>
    {% endif %}

    <h4>Dimensions</h4>
    <table>
      <thead><tr><th>Dimension</th><th>Weight</th><th>Score</th><th>Weighted</th><th>Justification</th></tr></thead>
      <tbody>
        {% for d in c.dimensions %}
        <tr>
          <td>{{ d.name }}</td>
          <td>{{ d.weight }}</td>
          <td>{{ d.score }}</td>
          <td>{{ d.weighted_score }}</td>
          <td>{{ d.justification }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    {% if c.missing_information %}
    <h4>Missing Information</h4>
    <ul>
      {% for item in c.missing_information %}
      <li>{{ item }}</li>
      {% endfor %}
    </ul>
    {% endif %}

    {% if c.issue_type_assessment %}
    <h4>Issue Type Assessment</h4>
    <p>
      <strong>Type:</strong> <span class="badge badge-{{ c.issue_type_assessment.classified_type if c.issue_type_assessment.classified_type in ('bug','enhancement','feature-request','task') else 'default' }}">{{ c.issue_type_assessment.classified_type }}</span>
      &middot; <strong>Confidence:</strong> {{ c.issue_type_assessment.confidence }}
    </p>
    <p>{{ c.issue_type_assessment.justification }}</p>
    {% endif %}

    <h4>Triage Recommendation</h4>
    <p><strong>{{ c.triage_recommendation }}</strong></p>
  {% else %}
    <p><em>No completeness analysis available.</em></p>
  {% endif %}
</details>

{# ---- Context Map ---- #}
<details open>
  <summary>Context Map</summary>
  {% if issue.context_map %}
    {% set cm = issue.context_map %}
    <p><strong>Overall Rating:</strong> {{ cm.overall_rating }}</p>

    {% if cm.identified_components %}
    <h4>Identified Components</h4>
    <ul>
      {% for comp in cm.identified_components %}
      <li>{{ comp }}</li>
      {% endfor %}
    </ul>
    {% endif %}

    {% if cm.context_entries %}
    <h4>Context Entries</h4>
    <table>
      <thead><tr><th>Source</th><th>Relevance</th><th>Content</th></tr></thead>
      <tbody>
        {% for entry in cm.context_entries %}
        <tr>
          <td>{{ entry.source if entry.source is defined else '' }}</td>
          <td>{{ entry.relevance if entry.relevance is defined else '' }}</td>
          <td>{{ entry.content if entry.content is defined else (entry.summary if entry.summary is defined else '') }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}

    {% if cm.relevant_files %}
    <h4>Relevant Files</h4>
    <ul>
      {% for f in cm.relevant_files %}
      <li><code>{{ f }}</code></li>
      {% endfor %}
    </ul>
    {% endif %}

    {% if cm.missing_context %}
    <h4>Missing Context</h4>
    <ul>
      {% for item in cm.missing_context %}
      <li>{{ item }}</li>
      {% endfor %}
    </ul>
    {% endif %}

    {% if cm.context_helpfulness %}
    <h4>Context Helpfulness: {{ cm.context_helpfulness.overall_score }} / 100</h4>
    <div class="score-bar">
      <div class="score-bar-fill" style="width:{{ cm.context_helpfulness.overall_score }}%; background:{{ '#c0392b' if cm.context_helpfulness.overall_score < 40 else ('#d4a017' if cm.context_helpfulness.overall_score < 80 else '#27ae60') }};">
        {{ cm.context_helpfulness.overall_score }}
      </div>
    </div>
    <table>
      <thead><tr><th>Dimension</th><th>Score</th><th>Justification</th></tr></thead>
      <tbody>
        <tr>
          <td>Coverage</td>
          <td>{{ cm.context_helpfulness.coverage.score }}</td>
          <td>{{ cm.context_helpfulness.coverage.justification }}</td>
        </tr>
        <tr>
          <td>Depth</td>
          <td>{{ cm.context_helpfulness.depth.score }}</td>
          <td>{{ cm.context_helpfulness.depth.justification }}</td>
        </tr>
        <tr>
          <td>Freshness</td>
          <td>{{ cm.context_helpfulness.freshness.score }}</td>
          <td>{{ cm.context_helpfulness.freshness.justification }}</td>
        </tr>
      </tbody>
    </table>
    {% endif %}

    {% if cm.repos_and_files_used %}
    <h4>Repos &amp; Files Used</h4>
    <ul>
      {% for entry in cm.repos_and_files_used %}
      <li>
        <strong>{{ entry.repository }}</strong>
        {% if entry.files %}
        <ul>
          {% for f in entry.files %}
          <li><code>{{ f }}</code></li>
          {% endfor %}
        </ul>
        {% endif %}
      </li>
      {% endfor %}
    </ul>
    {% endif %}

    {% if cm.repos_and_files_needed %}
    <h4>Repos &amp; Files Needed (Gaps)</h4>
    <ul>
      {% for entry in cm.repos_and_files_needed %}
      <li>
        <strong>{{ entry.repository }}</strong>
        {% if entry.files %}
        <ul>
          {% for f in entry.files %}
          <li><code>{{ f }}</code></li>
          {% endfor %}
        </ul>
        {% endif %}
        <br><em>Reason: {{ entry.reason }}</em>
      </li>
      {% endfor %}
    </ul>
    {% endif %}

    {% if cm.affected_versions %}
    <h4>Affected Versions</h4>
    <ul>
      {% for v in cm.affected_versions %}
      <li>{{ v }}</li>
      {% endfor %}
    </ul>
    {% endif %}
  {% else %}
    <p><em>No context map available.</em></p>
  {% endif %}
</details>

{# ---- Fix Attempt ---- #}
<details open>
  <summary>Fix Attempt</summary>
  {% if issue.fix_attempt %}
    {% set fa = issue.fix_attempt %}
    <p><strong>Recommendation:</strong> <span class="badge badge-fix-{{ fa.recommendation }}">{{ fa.recommendation }}</span> &middot; <strong>Confidence:</strong> {{ fa.confidence }}</p>

    {% if fa.target_repo %}
    <p><strong>Target Repository:</strong> <code>{{ fa.target_repo }}</code></p>
    {% endif %}

    {% if fa.upstream_consideration %}
    <p><strong>Upstream Consideration:</strong> {{ fa.upstream_consideration }}</p>
    {% endif %}

    <h4>Root Cause Hypothesis</h4>
    <p>{{ fa.root_cause_hypothesis }}</p>

    {% if fa.affected_files %}
    <h4>Affected Files</h4>
    <table>
      <thead><tr><th>File</th><th>Change</th></tr></thead>
      <tbody>
        {% for af in fa.affected_files %}
        <tr>
          <td><code>{{ af.file if af.file is defined else (af.path if af.path is defined else '') }}</code></td>
          <td>{{ af.change if af.change is defined else (af.description if af.description is defined else '') }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}

    <h4>Fix Description</h4>
    <p>{{ fa.fix_description }}</p>

    {% if fa.patch %}
    <h4>Patch</h4>
    <pre class="patch">{{ fa.patch }}</pre>
    {% endif %}

    {% if fa.risks %}
    <h4>Risks</h4>
    <ul>{% for r in fa.risks %}<li>{{ r }}</li>{% endfor %}</ul>
    {% endif %}

    {% if fa.blockers %}
    <h4>Blockers</h4>
    <ul>{% for b in fa.blockers %}<li>{{ b }}</li>{% endfor %}</ul>
    {% endif %}

    {% if fa.validation %}
    <h4>Patch Validation</h4>
    {% set last_iter = fa.validation[-1] %}
    <p>
      <strong>Result:</strong>
      {% if last_iter.all_passed %}
        <span class="badge badge-val-pass">PASSED</span>
      {% else %}
        <span class="badge badge-val-fail">FAILED</span>
      {% endif %}
      &middot; <strong>Iterations:</strong> {{ fa.validation | length }}
    </p>

    {% for vi in fa.validation %}
    <details{% if loop.last %} open{% endif %}>
      <summary>Iteration {{ vi.iteration }}{% if vi.full_suite is defined and vi.full_suite %} (full suite){% endif %}{% if vi.all_passed %} — <span class="badge badge-val-pass">passed</span>{% else %} — <span class="badge badge-val-fail">failed</span>{% endif %}</summary>
      {% for vr in vi.results %}
      <p><strong>{{ vr.repo_name }}</strong>
        {% if vr.skipped is defined and vr.skipped %}
          — <span class="badge badge-val-skip">skipped</span> {{ vr.skip_reason if vr.skip_reason is defined else '' }}
        {% elif vr.overall_passed is defined and vr.overall_passed %}
          — <span class="badge badge-val-pass">passed</span>
        {% else %}
          —
          {% if vr.lint_passed is defined %}
            {% if vr.lint_passed %}<span class="badge badge-val-pass">lint ok</span>{% else %}<span class="badge badge-val-fail">lint fail</span>{% endif %}
          {% endif %}
          {% if vr.selective_tests_passed is defined and vr.selective_tests_passed is not none %}
            {% if vr.selective_tests_passed %}<span class="badge badge-val-pass">tests ok</span>{% else %}<span class="badge badge-val-fail">tests fail</span>{% endif %}
          {% elif vr.full_tests_passed is defined and vr.full_tests_passed is not none %}
            {% if vr.full_tests_passed %}<span class="badge badge-val-pass">tests ok</span>{% else %}<span class="badge badge-val-fail">tests fail</span>{% endif %}
          {% endif %}
        {% endif %}
      </p>
      {% if vr.test_context_helpfulness is defined and vr.test_context_helpfulness %}
      <p style="font-size:0.9em;">
        <strong>Test context helpfulness:</strong>
        <span class="badge {{ 'badge-val-pass' if vr.test_context_helpfulness.rating == 'high' else ('badge-default' if vr.test_context_helpfulness.rating == 'medium' else 'badge-val-fail') }}">
          {{ vr.test_context_helpfulness.rating }}
        </span>
        {% if vr.test_context_helpfulness.explanation is defined %}
          &mdash; {{ vr.test_context_helpfulness.explanation }}
        {% endif %}
      </p>
      {% endif %}
      {% if vr.summary is defined and vr.summary %}
      <p style="font-size:0.9em;"><em>{{ vr.summary }}</em></p>
      {% endif %}
      {% if not (vr.skipped is defined and vr.skipped) and vr.commands_run is defined and vr.commands_run %}
        {% for cmd in vr.commands_run %}
        <div class="val-cmd {{ 'val-cmd-pass' if cmd.passed else 'val-cmd-fail' }}">
          <code>{{ cmd.command }}</code>
          &nbsp;
          {% if cmd.exit_code is defined and cmd.exit_code == -1 %}
            <span class="badge badge-val-timeout">timeout</span>
          {% elif cmd.passed is defined and cmd.passed %}
            <span class="badge badge-val-pass">exit {{ cmd.exit_code if cmd.exit_code is defined else 0 }}</span>
          {% else %}
            <span class="badge badge-val-fail">exit {{ cmd.exit_code if cmd.exit_code is defined else '?' }}</span>
          {% endif %}
          {% if cmd.category is defined %}
          <span style="opacity:0.6; font-size:0.85em">({{ cmd.category }})</span>
          {% endif %}
          {% if cmd.output_summary is defined and cmd.output_summary and cmd.output_summary.strip() %}
          <pre>{{ cmd.output_summary.strip() }}</pre>
          {% endif %}
        </div>
        {% endfor %}
      {% endif %}
      {% endfor %}
    </details>
    {% endfor %}
    {% endif %}

    {% if fa.self_corrections %}
    <h4>Self-Corrections ({{ fa.self_corrections|length }})</h4>
    <p>The fix agent identified and corrected the following mistakes during validation retries:</p>
    {% for sc in fa.self_corrections %}
    <details{% if loop.last %} open{% endif %}>
      <summary>
        <span class="badge badge-correction">{{ sc.mistake_category }}</span>
        &middot; Trigger: {{ sc.failure_trigger }}
        &middot; After iteration {{ sc.after_iteration }}
        {% if sc.was_original_approach_wrong %}
          <span class="badge badge-approach-change">approach changed</span>
        {% else %}
          <span class="badge badge-minor-fix">minor fix</span>
        {% endif %}
      </summary>
      <div class="correction-block">
        <p><strong>What went wrong:</strong> {{ sc.what_went_wrong }}</p>
        <p><strong>What was changed:</strong> {{ sc.what_was_changed }}</p>
        {% if sc.files_modified %}
        <p><strong>Files modified:</strong></p>
        <ul>
          {% for f in sc.files_modified %}
          <li><code>{{ f }}</code></li>
          {% endfor %}
        </ul>
        {% endif %}
      </div>
    </details>
    {% endfor %}
    {% endif %}
  {% else %}
    <p><em>No fix attempt available.</em></p>
    <p><strong>Reason:</strong>
    {% if not issue.completeness %}
      Completeness analysis has not been run yet.
    {% elif issue.completeness.overall_score is defined and issue.completeness.overall_score < 5 %}
      Completeness score too low ({{ issue.completeness.overall_score }}/100, needs &ge; 5).
    {% elif not issue.context_map %}
      Context map has not been run yet.
    {% elif issue.context_map.overall_rating is defined and issue.context_map.overall_rating == 'no-context' %}
      No architecture context available for this issue.
    {% elif issue.status is defined and issue.status in ['Review', 'Testing'] %}
      Issue has active work (status: {{ issue.status }}).
    {% else %}
      Fix attempt phase has not been run for this issue yet.
    {% endif %}
    </p>
  {% endif %}
</details>

{# ---- Test Plan ---- #}
<details open>
  <summary>Test Plan</summary>
  {% if issue.test_plan %}
    {% set tp = issue.test_plan %}
    <p><strong>Effort Estimate:</strong> {{ tp.effort_estimate }}</p>

    {% if tp.decision_rationale %}
    <h4>Decision Rationale</h4>
    <p>{{ tp.decision_rationale }}</p>
    {% endif %}

    {% if tp.target_test_repos %}
    <h4>Target Test Repositories</h4>
    <table>
      <thead><tr><th>Repo</th><th>Test Directory</th><th>Framework</th><th>Run Command</th></tr></thead>
      <tbody>
        {% for r in tp.target_test_repos %}
        <tr>
          <td><code>{{ r.repo }}</code></td>
          <td><code>{{ r.test_directory }}</code></td>
          <td>{{ r.framework }}</td>
          <td><code>{{ r.run_command }}</code></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}

    {% if tp.unit_tests %}
    <h4>Unit Tests</h4>
    <table>
      <thead><tr><th>Description</th><th>File</th><th>Expected</th></tr></thead>
      <tbody>
        {% for t in tp.unit_tests %}
        <tr>
          <td>{{ t.description if t.description is defined else '' }}</td>
          <td><code>{{ t.file if t.file is defined else '' }}</code></td>
          <td>{{ t.expected if t.expected is defined else '' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}

    {% if tp.integration_tests %}
    <h4>Integration Tests</h4>
    <table>
      <thead><tr><th>Description</th><th>Components</th><th>Expected</th></tr></thead>
      <tbody>
        {% for t in tp.integration_tests %}
        <tr>
          <td>{{ t.description if t.description is defined else '' }}</td>
          <td>{{ t.components|join(', ') if t.components is defined else '' }}</td>
          <td>{{ t.expected if t.expected is defined else '' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}

    {% if tp.regression_tests %}
    <h4>Regression Tests</h4>
    <table>
      <thead><tr><th>Description</th><th>Before Fix</th><th>After Fix</th></tr></thead>
      <tbody>
        {% for t in tp.regression_tests %}
        <tr>
          <td>{{ t.description if t.description is defined else '' }}</td>
          <td>{{ t.before_fix if t.before_fix is defined else '' }}</td>
          <td>{{ t.after_fix if t.after_fix is defined else '' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}

    {% if tp.manual_verification_steps %}
    <h4>Manual Verification Steps</h4>
    <ol>
      {% for step in tp.manual_verification_steps %}
      <li>{{ step }}</li>
      {% endfor %}
    </ol>
    {% endif %}

    {% if tp.environment_requirements %}
    <h4>Environment Requirements</h4>
    <table>
      <tbody>
        {% if tp.environment_requirements.ocp_version %}
        <tr><td><strong>OCP Version</strong></td><td>{{ tp.environment_requirements.ocp_version }}</td></tr>
        {% endif %}
        {% if tp.environment_requirements.rhoai_version %}
        <tr><td><strong>RHOAI Version</strong></td><td>{{ tp.environment_requirements.rhoai_version }}</td></tr>
        {% endif %}
        {% if tp.environment_requirements.platform %}
        <tr><td><strong>Platform</strong></td><td>{{ tp.environment_requirements.platform }}</td></tr>
        {% endif %}
        {% if tp.environment_requirements.special_config %}
        <tr><td><strong>Special Config</strong></td><td>{{ tp.environment_requirements.special_config }}</td></tr>
        {% endif %}
      </tbody>
    </table>
    {% endif %}

    {% if tp.qe_coverage_note %}
    <h4>QE Coverage Note</h4>
    <p>{{ tp.qe_coverage_note }}</p>
    {% endif %}
  {% else %}
    <p><em>No test plan available.</em></p>
  {% endif %}
</details>

{# ---- Write Test ---- #}
<details open>
  <summary>Write Test</summary>
  {% if issue.write_test %}
    {% set wt = issue.write_test %}
    <p>
      <strong>Decision:</strong>
      <span class="badge {{ 'badge-val-pass' if wt.decision == 'write-test' else 'badge-default' }}">{{ wt.decision }}</span>
      {% if wt.confidence %}
      &middot; <strong>Confidence:</strong> {{ wt.confidence }}
      {% endif %}
    </p>

    <h4>Justification</h4>
    <p>{{ wt.justification }}</p>

    {% if wt.decision == 'write-test' %}
      {% if wt.test_file %}
      <p><strong>Test File:</strong> <code>{{ wt.test_file }}</code></p>
      {% endif %}

      {% if wt.test_markers %}
      <p><strong>Markers:</strong>
        {% for m in wt.test_markers %}
          <span class="badge badge-default">{{ m }}</span>
        {% endfor %}
      </p>
      {% endif %}

      {% if wt.test_description %}
      <h4>Test Description</h4>
      <p>{{ wt.test_description }}</p>
      {% endif %}

      {% if wt.patch %}
      <h4>Test Patch</h4>
      <pre class="patch">{{ wt.patch }}</pre>
      {% else %}
      <p><em>Patch not captured. Re-run the write-test phase to generate the diff.</em></p>
      {% endif %}
    {% endif %}

    {% if wt.risks %}
    <h4>Risks</h4>
    <ul>{% for r in wt.risks %}<li>{{ r }}</li>{% endfor %}</ul>
    {% endif %}

    {% if wt.cluster_requirements %}
    <h4>Cluster Requirements</h4>
    <p>{{ wt.cluster_requirements }}</p>
    {% endif %}
  {% else %}
    <p><em>No write-test analysis available.</em></p>
  {% endif %}
</details>

</div>{# end detail-right #}

</div>{# end detail-columns #}
{% endblock %}
"""


ACTIVITY = """\
{% extends "layout.html" %}
{% block title %}Activity - Bug Bash{% endblock %}
{% block content %}
<style>
  #pipeline-status {
    padding: 1em; margin-bottom: 1.5rem; border-radius: 6px;
    border: 1px solid #ddd; background: #f8f9fa;
  }
  #pipeline-status.running { border-color: #27ae60; background: #eafaf1; }
  #pipeline-status .status-indicator {
    display: inline-block; width: 10px; height: 10px; border-radius: 50%;
    margin-right: 0.5em; background: #95a5a6;
  }
  #pipeline-status.running .status-indicator { background: #27ae60; animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
  #pipeline-status .config-details { font-size: 0.9em; color: #555; margin-top: 0.5em; }
  .badge-skipped { background: #95a5a6; color: #fff; }
  #progress-summary {
    padding: 1em; margin-bottom: 1.5rem; border-radius: 6px;
    border: 1px solid #ddd; background: #f8f9fa; display: none;
  }
  #progress-summary .progress-bar-outer {
    background: #e0e0e0; border-radius: 4px; height: 22px;
    margin: 0.7em 0; overflow: hidden;
  }
  #progress-summary .progress-bar-inner {
    background: #27ae60; height: 100%; border-radius: 4px;
    transition: width 0.4s ease;
  }
  #progress-summary .counts { display: flex; gap: 1.5em; flex-wrap: wrap; margin-top: 0.5em; }
  #progress-summary .counts span { font-size: 0.95em; }
  #progress-summary .model-breakdown { margin-top: 0.7em; font-size: 0.9em; color: #555; }
</style>

<h2>Activity</h2>

<div id="pipeline-status">
  <strong><span class="status-indicator"></span> Pipeline: <span id="pipeline-label">Idle</span></strong>
  <div class="config-details" id="pipeline-config" style="display:none;"></div>
</div>

<div id="progress-summary">
  <strong>Progress</strong>
  <div class="progress-bar-outer"><div class="progress-bar-inner" id="progress-bar" style="width:0%"></div></div>
  <div class="counts">
    <span>Total: <strong id="cnt-total">0</strong></span>
    <span style="color:#3498db">Pending: <strong id="cnt-pending">0</strong></span>
    <span style="color:#f39c12">Running: <strong id="cnt-running">0</strong></span>
    <span style="color:#27ae60">Completed: <strong id="cnt-completed">0</strong></span>
    <span style="color:#c0392b">Failed: <strong id="cnt-failed">0</strong></span>
  </div>
  <div class="model-breakdown" id="model-breakdown"></div>
</div>

<div id="currently-processing">
{% if in_progress %}
<details open>
  <summary>Currently Processing (<span id="ip-count">{{ in_progress|length }}</span>)</summary>
  <table role="grid">
    <thead>
      <tr><th>Issue</th><th>Phase</th><th>Model</th><th>Started</th></tr>
    </thead>
    <tbody id="ip-tbody">
      {% for e in in_progress %}
      <tr id="ip-{{ e.issue_key }}-{{ e.model }}">
        <td><a href="/issue/{{ e.issue_key }}">{{ e.issue_key }}</a></td>
        <td><span class="badge badge-default" id="ip-phase-{{ e.issue_key }}-{{ e.model }}">{{ e.phase }}</span></td>
        <td>{{ e.model }}</td>
        <td>{{ e.timestamp[:19] | replace('T', ' ') }} UTC</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</details>
{% else %}
<p id="currently-processing-none"><em>No agents currently running.</em></p>
{% endif %}
</div>

<details open>
  <summary>Recent History (<span id="history-count">{{ history|length }}</span>)</summary>
  {% if history %}
  <table role="grid" id="history-table">
    <thead>
      <tr><th>Issue</th><th>Phase</th><th>Result</th><th>Model</th><th>Duration</th><th>Timestamp</th><th>Error</th></tr>
    </thead>
    <tbody id="history-tbody">
      {% for e in history %}
      <tr>
        <td><a href="/issue/{{ e.issue_key }}">{{ e.issue_key }}</a></td>
        <td><span class="badge badge-default">{{ e.phase }}</span></td>
        <td>
          {% if e.event == 'completed' %}
            <span style="color:#27ae60;font-weight:bold;">completed</span>
          {% elif e.event == 'orphaned' %}
            <span style="color:#d4a017;font-weight:bold;">orphaned</span>
          {% elif e.event == 'skipped' %}
            <span class="badge badge-skipped">skipped</span>
          {% else %}
            <span style="color:#c0392b;font-weight:bold;">failed</span>
          {% endif %}
        </td>
        <td>{{ e.model }}</td>
        <td>{% if e.duration_seconds %}{{ e.duration_seconds | int // 60 }}m {{ e.duration_seconds | int % 60 }}s{% else %}&mdash;{% endif %}</td>
        <td>{{ e.timestamp[:19] | replace('T', ' ') }} UTC</td>
        <td class="truncate">{{ e.error or '' }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <table role="grid" id="history-table" style="display:none;">
    <thead>
      <tr><th>Issue</th><th>Phase</th><th>Result</th><th>Model</th><th>Duration</th><th>Timestamp</th><th>Error</th></tr>
    </thead>
    <tbody id="history-tbody"></tbody>
  </table>
  <p id="history-empty"><em>No activity recorded yet.</em></p>
  {% endif %}
</details>
{% endblock %}

{% block scripts %}
<script>
(function() {
  // --- Initial state from queue API (debounced to 1 req/sec max) ---
  var _queueTimer = null;
  function loadQueueState() {
    if (_queueTimer) return;  // already scheduled
    _queueTimer = setTimeout(function() {
      _queueTimer = null;
      fetch('/api/pipeline/queue')
        .then(r => r.json())
        .then(state => {
          if (state.running) {
            setPipelineRunning(state.manifest || {});
          }
          updateProgressSummary(state);
        })
        .catch(() => {});
    }, 1000);
  }
  // Immediate first load (bypass debounce)
  fetch('/api/pipeline/queue')
    .then(r => r.json())
    .then(state => {
      if (state.running) {
        setPipelineRunning(state.manifest || {});
      }
      updateProgressSummary(state);
    })
    .catch(() => {});

  // --- SSE live updates ---
  const evtSource = new EventSource('/api/events');
  evtSource.onmessage = function(event) {
    try {
      const data = JSON.parse(event.data);
      handleEvent(data);
    } catch(e) {}
  };

  function handleEvent(data) {
    const msgType = data.type;
    const evt = data.event;
    const issueKey = data.issue_key;
    const phase = data.phase;
    const model = data.model || '';

    // Manifest resets everything
    if (msgType === 'manifest') {
      setPipelineRunning(data);
      // Refresh queue state from server
      loadQueueState();
      return;
    }

    switch(evt) {
      case 'pipeline_started':
        setPipelineRunning(data);
        break;
      case 'pipeline_completed':
      case 'pipeline_failed':
        setPipelineIdle(evt);
        loadQueueState();
        break;
      case 'issue_started':
        addInProgressRow(issueKey, 'starting', model, data.timestamp || '');
        loadQueueState();
        break;
      case 'issue_completed':
        removeInProgressRow(issueKey, model);
        loadQueueState();
        break;
      case 'started':
        updatePhase(issueKey, model, phase);
        if (!document.getElementById('ip-' + issueKey + '-' + model)) {
          addInProgressRow(issueKey, phase, model, data.timestamp || '');
        }
        loadQueueState();
        break;
      case 'completed':
      case 'failed':
      case 'skipped':
        addHistoryRow(data);
        loadQueueState();
        break;
    }
  }

  function updateProgressSummary(state) {
    const el = document.getElementById('progress-summary');
    if (!state.total_jobs) { el.style.display = 'none'; return; }
    el.style.display = 'block';
    const c = state.counts || {};
    document.getElementById('cnt-total').textContent = state.total_jobs;
    document.getElementById('cnt-pending').textContent = c.pending || 0;
    document.getElementById('cnt-running').textContent = c.running || 0;
    document.getElementById('cnt-completed').textContent = c.completed || 0;
    document.getElementById('cnt-failed').textContent = c.failed || 0;
    const done = (c.completed || 0) + (c.failed || 0);
    const pct = state.total_jobs ? Math.round(100 * done / state.total_jobs) : 0;
    document.getElementById('progress-bar').style.width = pct + '%';

    // Per-model breakdown
    const mc = state.model_counts || {};
    const parts = [];
    for (const [m, counts] of Object.entries(mc)) {
      const short = m.replace('claude-', '');
      const mDone = (counts.completed || 0) + (counts.failed || 0);
      const mTotal = (counts.pending || 0) + (counts.running || 0) + mDone;
      parts.push(short + ': ' + mDone + '/' + mTotal);
    }
    document.getElementById('model-breakdown').textContent = parts.length ? 'Per model: ' + parts.join(' | ') : '';
  }

  function setPipelineRunning(info) {
    const el = document.getElementById('pipeline-status');
    el.classList.add('running');
    document.getElementById('pipeline-label').textContent = 'Running';
    const config = document.getElementById('pipeline-config');
    config.style.display = 'block';
    const parts = [];
    if (info.models) parts.push('Models: ' + info.models.join(', '));
    else if (info.model) parts.push('Model: ' + info.model);
    if (info.total_issues) parts.push('Issues: ' + info.total_issues);
    if (info.max_concurrent) parts.push('Concurrent: ' + info.max_concurrent);
    const ts = info.started_at || info.timestamp || '';
    if (ts) parts.push('Started: ' + ts.substring(0, 19).replace('T', ' ') + ' UTC');
    config.textContent = parts.join(' | ');
  }

  function setPipelineIdle(evt) {
    const el = document.getElementById('pipeline-status');
    el.classList.remove('running');
    const label = evt === 'pipeline_failed' ? 'Failed' : 'Completed';
    document.getElementById('pipeline-label').textContent = label;
    document.getElementById('pipeline-config').style.display = 'none';
  }

  function ensureInProgressTable() {
    const wrapper = document.getElementById('currently-processing');
    const noneMsg = document.getElementById('currently-processing-none');
    if (noneMsg) noneMsg.remove();
    let tbody = document.getElementById('ip-tbody');
    if (!tbody) {
      wrapper.innerHTML = '<details open>' +
        '<summary>Currently Processing (<span id="ip-count">0</span>)</summary>' +
        '<table role="grid"><thead><tr><th>Issue</th><th>Phase</th><th>Model</th><th>Started</th></tr></thead>' +
        '<tbody id="ip-tbody"></tbody></table></details>';
      tbody = document.getElementById('ip-tbody');
    }
    return tbody;
  }

  function addInProgressRow(issueKey, phase, model, timestamp) {
    const tbody = ensureInProgressTable();
    const rowId = 'ip-' + issueKey + '-' + model;
    if (document.getElementById(rowId)) {
      updatePhase(issueKey, model, phase);
      return;
    }
    const tr = document.createElement('tr');
    tr.id = rowId;
    const ts = timestamp ? timestamp.substring(0, 19).replace('T', ' ') + ' UTC' : '';
    tr.innerHTML = '<td><a href="/issue/' + issueKey + '">' + issueKey + '</a></td>' +
      '<td><span class="badge badge-default" id="ip-phase-' + issueKey + '-' + model + '">' + phase + '</span></td>' +
      '<td>' + (model || '') + '</td>' +
      '<td>' + ts + '</td>';
    tbody.appendChild(tr);
    updateIpCount();
  }

  function removeInProgressRow(issueKey, model) {
    const row = document.getElementById('ip-' + issueKey + '-' + model);
    if (row) row.remove();
    updateIpCount();
  }

  function updatePhase(issueKey, model, phase) {
    const badge = document.getElementById('ip-phase-' + issueKey + '-' + model);
    if (badge) badge.textContent = phase;
  }

  function updateIpCount() {
    const tbody = document.getElementById('ip-tbody');
    const count = document.getElementById('ip-count');
    if (tbody && count) {
      count.textContent = tbody.querySelectorAll('tr').length;
    }
  }

  function addHistoryRow(data) {
    const table = document.getElementById('history-table');
    if (table) table.style.display = '';
    const emptyMsg = document.getElementById('history-empty');
    if (emptyMsg) emptyMsg.remove();

    const tbody = document.getElementById('history-tbody');
    if (!tbody) return;

    const tr = document.createElement('tr');
    const evt = data.event;
    let resultHtml;
    if (evt === 'completed') {
      resultHtml = '<span style="color:#27ae60;font-weight:bold;">completed</span>';
    } else if (evt === 'skipped') {
      resultHtml = '<span class="badge badge-skipped">skipped</span>';
    } else {
      resultHtml = '<span style="color:#c0392b;font-weight:bold;">failed</span>';
    }
    const dur = data.duration_seconds
      ? Math.floor(data.duration_seconds / 60) + 'm ' + Math.floor(data.duration_seconds % 60) + 's'
      : (data.reason || '&mdash;');
    const ts = data.timestamp ? data.timestamp.substring(0, 19).replace('T', ' ') + ' UTC' : '';

    tr.innerHTML = '<td><a href="/issue/' + data.issue_key + '">' + data.issue_key + '</a></td>' +
      '<td><span class="badge badge-default">' + data.phase + '</span></td>' +
      '<td>' + resultHtml + '</td>' +
      '<td>' + (data.model || '') + '</td>' +
      '<td>' + dur + '</td>' +
      '<td>' + ts + '</td>' +
      '<td class="truncate">' + (data.error || data.reason || '') + '</td>';
    tbody.insertBefore(tr, tbody.firstChild);

    const countEl = document.getElementById('history-count');
    if (countEl) countEl.textContent = tbody.querySelectorAll('tr').length;
  }
})();
</script>
{% endblock %}
"""

STATS = """\
{% extends "layout.html" %}
{% block title %}Statistics - Bug Bash{% endblock %}
{% block content %}
<style>
  .stats-section { margin-bottom: 2rem; }
  .stats-section h3 { border-bottom: 2px solid #ddd; padding-bottom: 0.3em; }
  .sig { color: #27ae60; font-weight: bold; }
  .not-sig { color: #95a5a6; }
  .corr-table td, .corr-table th { text-align: center; padding: 0.3em 0.5em; font-size: 0.85em; }
  .corr-pos { background: rgba(39, 174, 96, var(--intensity)); }
  .corr-neg { background: rgba(192, 57, 43, var(--intensity)); }
  .contingency td { text-align: center; }
  .metric-card {
    display: inline-block; padding: 0.8em 1.2em; margin: 0.3em;
    border-radius: 6px; background: #f0f4f8; border: 1px solid #ddd;
    text-align: center;
  }
  .metric-card .value { font-size: 1.6em; font-weight: bold; }
  .metric-card .label { font-size: 0.85em; color: #555; }
  .box-plot-bar {
    display: flex; align-items: center; height: 20px;
    position: relative; background: #ecf0f1; border-radius: 3px;
    margin: 2px 0; min-width: 200px;
  }
  .box-plot-iqr {
    position: absolute; height: 100%; background: rgba(52, 152, 219, 0.5);
    border-radius: 3px;
  }
  .box-plot-median {
    position: absolute; height: 100%; width: 2px; background: #c0392b;
  }
  .interpret { font-size: 0.9em; color: #555; background: #f8f9fa; padding: 0.8em; border-radius: 4px; margin-top: 0.5em; border-left: 3px solid #3498db; }
</style>

<h2>Statistical Analysis</h2>

<div style="margin-bottom: 1.5rem;">
  <div class="metric-card">
    <div class="value">{{ s.n_issues }}</div>
    <div class="label">Total Issues</div>
  </div>
  <div class="metric-card">
    <div class="value">{{ s.n_with_fix }}</div>
    <div class="label">With Fix Attempt</div>
  </div>
  <div class="metric-card">
    <div class="value">{{ s.n_fixable }}</div>
    <div class="label">AI-Fixable</div>
  </div>
  <div class="metric-card">
    <div class="value">{{ "%.0f" | format(s.n_fixable / s.n_with_fix * 100) }}%</div>
    <div class="label">Fix Rate</div>
  </div>
</div>

{# ==================== CORRELATION MATRIX ==================== #}
<div class="stats-section">
  <h3>Spearman Rank Correlation Matrix</h3>
  <p>N = {{ s.correlation.n }} issues with all numeric fields present.</p>
  {% if s.correlation.matrix %}
  <div style="overflow-x:auto;">
  <table class="corr-table" role="grid">
    <thead>
      <tr>
        <th></th>
        {% for f in s.correlation.fields %}
        <th>{{ f | replace('_', ' ') | title }}</th>
        {% endfor %}
      </tr>
    </thead>
    <tbody>
      {% for i in range(s.correlation.fields | length) %}
      <tr>
        <th>{{ s.correlation.fields[i] | replace('_', ' ') | title }}</th>
        {% for j in range(s.correlation.fields | length) %}
        {% set rho = s.correlation.matrix[i][j] %}
        {% set p = s.correlation.pvalues[i][j] %}
        {% set intensity = (rho|abs * 0.7) %}
        <td style="--intensity: {{ intensity }};"
            class="{{ 'corr-pos' if rho > 0 else 'corr-neg' }}"
            title="rho={{ rho }}, p={{ p }}">
          {{ rho }}{% if p < 0.05 and i != j %}*{% endif %}
        </td>
        {% endfor %}
      </tr>
      {% endfor %}
    </tbody>
  </table>
  </div>
  <p class="interpret">
    * = statistically significant (p &lt; 0.05). Colour intensity reflects magnitude.
    Positive correlations (green) mean both variables increase together.
    Strong correlations (|rho| &gt; 0.5) suggest meaningful relationships.
  </p>
  {% else %}
  <p><em>Not enough data for correlation analysis.</em></p>
  {% endif %}
</div>

{# ==================== CHI-SQUARED TESTS ==================== #}
<div class="stats-section">
  <h3>Chi-Squared Independence Tests</h3>
  <p>Tests whether categorical variables are statistically associated.</p>

  <table role="grid">
    <thead>
      <tr>
        <th>Test</th>
        <th>N</th>
        <th>&chi;&sup2;</th>
        <th>df</th>
        <th>p-value</th>
        <th>Cram&eacute;r's V</th>
        <th>Significant?</th>
      </tr>
    </thead>
    <tbody>
      {% for t in s.chi_squared %}
      <tr>
        <td>{{ t.label }}</td>
        <td>{{ t.n }}</td>
        <td>{{ t.chi2 }}</td>
        <td>{{ t.dof }}</td>
        <td>{{ "%.4f" | format(t.p_value) }}</td>
        <td>{{ t.cramers_v }}</td>
        <td><span class="{{ 'sig' if t.significant else 'not-sig' }}">{{ "Yes" if t.significant else "No" }}</span></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <p class="interpret">
    p &lt; 0.05 means the association is unlikely due to chance.
    Cram&eacute;r's V measures effect size: 0.1 = small, 0.3 = medium, 0.5 = large.
  </p>

  {# Show contingency tables for significant results #}
  {% for t in s.chi_squared %}
  {% if t.significant %}
  <details>
    <summary>{{ t.label }} &mdash; Contingency Table</summary>
    <div style="overflow-x:auto;">
    <table class="contingency" role="grid">
      <thead>
        <tr>
          <th>{{ t.var1 | replace('_', ' ') | title }}</th>
          {% for col in t.cols %}
          <th>{{ col }}</th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for i in range(t.rows | length) %}
        <tr>
          <td><strong>{{ t.rows[i] }}</strong></td>
          {% for j in range(t.cols | length) %}
          <td>{{ t.table[i][j] }}</td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
    </div>
  </details>
  {% endif %}
  {% endfor %}
</div>

{# ==================== GROUP COMPARISON TESTS ==================== #}
<div class="stats-section">
  <h3>Group Comparison Tests</h3>
  <p>Do numeric measures differ significantly across groups?</p>

  {# Kruskal-Wallis tests #}
  {% set kw_tests = s.group_tests | selectattr('test', 'equalto', 'kruskal-wallis') | list %}
  {% if kw_tests %}
  <h4>Kruskal-Wallis H-Tests (numeric score by fix recommendation)</h4>
  <table role="grid">
    <thead>
      <tr><th>Measure</th><th>H-statistic</th><th>p-value</th><th>Significant?</th></tr>
    </thead>
    <tbody>
      {% for t in kw_tests %}
      <tr>
        <td>{{ t.label }}</td>
        <td>{{ t.h_stat }}</td>
        <td>{{ "%.4f" | format(t.p_value) }}</td>
        <td><span class="{{ 'sig' if t.significant else 'not-sig' }}">{{ "Yes" if t.significant else "No" }}</span></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  {# Box plot data for significant KW tests #}
  {% for t in kw_tests %}
  {% if t.significant %}
  <details open>
    <summary>{{ t.label }} &mdash; Group Distributions</summary>
    <table role="grid">
      <thead>
        <tr><th>Fix Recommendation</th><th>N</th><th>Median</th><th>Mean</th><th>Std</th><th>Q1</th><th>Q3</th><th>Distribution (0-100)</th></tr>
      </thead>
      <tbody>
        {% for g in t.groups %}
        <tr>
          <td><span class="badge badge-fix-{{ g.group }}">{{ g.group }}</span></td>
          <td>{{ g.n }}</td>
          <td>{{ g.median }}</td>
          <td>{{ g.mean }}</td>
          <td>{{ g.std }}</td>
          <td>{{ g.q1 }}</td>
          <td>{{ g.q3 }}</td>
          <td>
            <div class="box-plot-bar">
              <div class="box-plot-iqr" style="left:{{ g.q1 }}%;width:{{ g.q3 - g.q1 }}%;"></div>
              <div class="box-plot-median" style="left:{{ g.median }}%;"></div>
            </div>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </details>
  {% endif %}
  {% endfor %}
  {% endif %}

  {# Mann-Whitney U tests #}
  {% set mw_tests = s.group_tests | selectattr('test', 'equalto', 'mann-whitney-u') | list %}
  {% if mw_tests %}
  <h4>Mann-Whitney U Tests (binary predictor vs numeric outcome)</h4>
  <table role="grid">
    <thead>
      <tr><th>Test</th><th>U-statistic</th><th>p-value</th><th>Significant?</th>
      <th>Group</th><th>N</th><th>Median</th><th>Mean</th></tr>
    </thead>
    <tbody>
      {% for t in mw_tests %}
      <tr>
        <td rowspan="{{ t.groups | length }}">{{ t.label }}</td>
        <td rowspan="{{ t.groups | length }}">{{ t.u_stat }}</td>
        <td rowspan="{{ t.groups | length }}">{{ "%.4f" | format(t.p_value) }}</td>
        <td rowspan="{{ t.groups | length }}"><span class="{{ 'sig' if t.significant else 'not-sig' }}">{{ "Yes" if t.significant else "No" }}</span></td>
        <td>{{ t.groups[0].group }}</td>
        <td>{{ t.groups[0].n }}</td>
        <td>{{ t.groups[0].median }}</td>
        <td>{{ t.groups[0].mean }}</td>
      </tr>
      {% for g in t.groups[1:] %}
      <tr>
        <td>{{ g.group }}</td>
        <td>{{ g.n }}</td>
        <td>{{ g.median }}</td>
        <td>{{ g.mean }}</td>
      </tr>
      {% endfor %}
      {% endfor %}
    </tbody>
  </table>
  <p class="interpret">
    Mann-Whitney U tests whether two groups have significantly different distributions.
    Architecture doc / source checkout availability are binary predictors.
    Note: Very skewed group sizes (e.g. 437 vs 5) reduce test power.
  </p>
  {% endif %}
</div>

{# ==================== LOGISTIC REGRESSION ==================== #}
{% if s.logistic %}
<div class="stats-section">
  <h3>Logistic Regression: Predicting AI-Fixable</h3>
  <p>Binary outcome: fix_recommendation = "ai-fixable" vs all others.</p>

  <div style="margin-bottom: 1em;">
    <div class="metric-card">
      <div class="value">{{ s.logistic.n }}</div>
      <div class="label">Observations</div>
    </div>
    <div class="metric-card">
      <div class="value">{{ "%.1f" | format(s.logistic.base_rate * 100) }}%</div>
      <div class="label">Base Rate (fixable)</div>
    </div>
    <div class="metric-card">
      <div class="value">{{ "%.1f" | format(s.logistic.accuracy * 100) }}%</div>
      <div class="label">Model Accuracy</div>
    </div>
    <div class="metric-card">
      <div class="value">{{ s.logistic.pseudo_r2 }}</div>
      <div class="label">McFadden Pseudo-R&sup2;</div>
    </div>
  </div>

  <table role="grid">
    <thead>
      <tr><th>Feature</th><th>Coefficient</th><th>Std Error</th><th>z-value</th><th>p-value</th><th>Odds Ratio</th><th>Significant?</th></tr>
    </thead>
    <tbody>
      {% for c in s.logistic.coefficients %}
      <tr>
        <td><strong>{{ c.feature | replace('_', ' ') | title }}</strong></td>
        <td>{{ c.coefficient }}</td>
        <td>{{ c.std_error if c.std_error is not none else '&mdash;' | safe }}</td>
        <td>{{ c.z_value }}</td>
        <td>{{ "%.4f" | format(c.p_value) }}</td>
        <td>{{ c.odds_ratio }}</td>
        <td><span class="{{ 'sig' if c.significant else 'not-sig' }}">{{ "Yes" if c.significant else "No" }}</span></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <p class="interpret">
    {{ s.logistic.note }}<br>
    Odds Ratio &gt; 1 means the feature increases the chance of AI-fixable; &lt; 1 means it decreases it.<br>
    Pseudo-R&sup2; indicates model fit (0 = no better than guessing the base rate; 1 = perfect).
    Values of 0.2-0.4 are considered good for logistic regression.
  </p>
</div>
{% endif %}

{# ==================== KEY FINDINGS ==================== #}
<div class="stats-section">
  <h3>Interpretation Guide</h3>
  <div class="interpret">
    <strong>What to look for:</strong>
    <ul>
      <li><strong>Correlation matrix:</strong> Large |rho| values with * show numeric measures that move together. If bug_quality and context_helpfulness both correlate strongly with fix_confidence, they're both useful predictors.</li>
      <li><strong>Chi-squared tests:</strong> Significant results mean the row/column categories are not independent. Look at the contingency table to see which combinations occur more/less than expected.</li>
      <li><strong>Kruskal-Wallis:</strong> If significant, the group medians/means show which fix recommendations are associated with higher/lower scores. The box plot bars visualise the spread.</li>
      <li><strong>Logistic regression:</strong> The significant coefficients tell you which inputs actually matter for predicting fixability, after controlling for the others. This is the most actionable analysis.</li>
      <li><strong>Architecture docs:</strong> With {{ s.n_with_fix - 5 }}/{{ s.n_with_fix }} issues having architecture docs, the binary has_arch_doc variable has very low variance. Its statistical power is limited. The <em>context_helpfulness</em> score (which incorporates doc quality) is a better measure.</li>
    </ul>
  </div>
</div>

{% endblock %}
"""

SUMMARY_LANDING = """\
{% extends "layout.html" %}
{% block title %}Summary - Bug Bash{% endblock %}
{% block content %}
<style>
  .summary-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; margin-top: 1rem; }
  .summary-card { border: 1px solid #ddd; border-radius: 8px; padding: 1.5em; background: #f8f9fa; }
  .summary-card h3 { margin-top: 0; }
  .summary-card p { color: #555; }
  .summary-card a { text-decoration: none; }
</style>
<h2>Bug Bash Summary Reports</h2>
<p>Narrative summaries of the AI bug-fixing pipeline results, tailored for different audiences.
All reports are generated from the same underlying data ({{ s.total }} issues analyzed).</p>

<div class="summary-cards">
  <div class="summary-card">
    <h3><a href="/summary/executive">Executive Summary</a></h3>
    <p>High-level outcomes and strategic takeaways. Key metrics, fix rates, and actionable recommendations
    for leadership. No statistical jargon.</p>
    <a href="/summary/executive">View report &rarr;</a>
  </div>
  <div class="summary-card">
    <h3><a href="/summary/developer">Developer Guide</a></h3>
    <p>Practical breakdown for engineers. Which bugs are fixable, where the gaps are,
    component-level results, and how to use the AI outputs effectively.</p>
    <a href="/summary/developer">View report &rarr;</a>
  </div>
  <div class="summary-card">
    <h3><a href="/summary/statistician">Statistical Analysis</a></h3>
    <p>Full methodological detail. Score distributions, correlation structures,
    predictor analysis, effect sizes, and caveats for data-literate readers.</p>
    <a href="/summary/statistician">View report &rarr;</a>
  </div>
</div>
{% endblock %}
"""

SUMMARY_EXECUTIVE = """\
{% extends "layout.html" %}
{% block title %}Executive Summary - Bug Bash{% endblock %}
{% block content %}
<style>
  .prose { max-width: 800px; line-height: 1.7; font-size: 1em; }
  .prose h2 { border-bottom: 2px solid #ddd; padding-bottom: 0.3em; margin-top: 2em; }
  .prose h3 { margin-top: 1.5em; }
  .kpi-row { display: flex; gap: 1rem; flex-wrap: wrap; margin: 1.5em 0; }
  .kpi { text-align: center; padding: 1em 1.5em; border-radius: 8px; background: #f0f4f8; border: 1px solid #ddd; min-width: 120px; }
  .kpi .value { font-size: 2em; font-weight: bold; }
  .kpi .label { font-size: 0.85em; color: #555; }
  .kpi-green .value { color: #27ae60; }
  .kpi-yellow .value { color: #d4a017; }
  .kpi-red .value { color: #c0392b; }
  .highlight-box { background: #eafaf1; border-left: 4px solid #27ae60; padding: 1em 1.5em; margin: 1.5em 0; border-radius: 4px; }
  .caution-box { background: #fef9e7; border-left: 4px solid #f39c12; padding: 1em 1.5em; margin: 1.5em 0; border-radius: 4px; }
  .prose table { font-size: 0.95em; }
</style>

<div class="prose">
<p><a href="/summary">&larr; All summaries</a></p>
<h1>Executive Summary</h1>
<p>AI-assisted analysis of {{ s.total }} RHOAIENG bug reports, evaluating each for completeness,
available architecture context, fixability, and test planning.</p>

<h2>Key Results</h2>

<div class="kpi-row">
  <div class="kpi kpi-green">
    <div class="value">{{ s.total }}</div>
    <div class="label">Bugs Analyzed</div>
  </div>
  <div class="kpi kpi-green">
    <div class="value">{{ s.n_fixable }}</div>
    <div class="label">AI-Fixable</div>
  </div>
  <div class="kpi kpi-green">
    <div class="value">{{ s.fix_rate_of_analyzed }}%</div>
    <div class="label">Fix Rate (analyzed)</div>
  </div>
  <div class="kpi kpi-yellow">
    <div class="value">{{ s.fix_rate_of_total }}%</div>
    <div class="label">Fix Rate (all bugs)</div>
  </div>
</div>

<div class="highlight-box">
<strong>Bottom line:</strong> Of the {{ s.with_fix_attempt }} bugs that reached the fix-attempt phase,
{{ s.n_fixable }} ({{ s.fix_rate_of_analyzed }}%) received an AI-generated fix recommendation with proposed patches.
Across the full backlog of {{ s.total }} bugs, {{ s.fix_rate_of_total }}% are directly addressable by AI.
</div>

<h2>Pipeline Coverage</h2>
<p>Every bug passed through four analysis phases:</p>
<table>
  <thead><tr><th>Phase</th><th>Bugs Processed</th><th>Coverage</th></tr></thead>
  <tbody>
    <tr><td>Completeness scoring</td><td>{{ s.with_completeness }}</td><td>{{ (s.with_completeness * 100 / s.total) | round(0) | int }}%</td></tr>
    <tr><td>Context mapping</td><td>{{ s.with_context_map }}</td><td>{{ (s.with_context_map * 100 / s.total) | round(0) | int }}%</td></tr>
    <tr><td>Fix attempt</td><td>{{ s.with_fix_attempt }}</td><td>{{ (s.with_fix_attempt * 100 / s.total) | round(0) | int }}%</td></tr>
    <tr><td>Test planning</td><td>{{ s.with_test_plan }}</td><td>{{ (s.with_test_plan * 100 / s.total) | round(0) | int }}%</td></tr>
  </tbody>
</table>
<p>{{ s.total - s.with_fix_attempt }} bugs were filtered out before the fix phase, primarily due to
insufficient architecture context (no relevant source code or docs found), issue already in active
review, or no identifiable components. Triage classification does not gate the fix phase.</p>

<h2>Bug Report Quality</h2>
<p>The average bug report completeness score is <strong>{{ s.comp_dist.avg }}/100</strong>
(median {{ s.comp_dist.median }}). The majority of bugs are triaged as needing more information:</p>
<table>
  <thead><tr><th>Triage Category</th><th>Count</th><th>Share</th></tr></thead>
  <tbody>
  {% for cat, count in s.triage_recommendations.items() %}
    <tr><td>{{ cat }}</td><td>{{ count }}</td><td>{{ (count * 100 / s.total) | round(1) }}%</td></tr>
  {% endfor %}
  </tbody>
</table>

<div class="caution-box">
<strong>Opportunity:</strong> {{ s.triage_recommendations.get('needs-enrichment', 0) + s.triage_recommendations.get('needs-info', 0) }}
of {{ s.total }} bugs ({{ ((s.triage_recommendations.get('needs-enrichment', 0) + s.triage_recommendations.get('needs-info', 0)) * 100 / s.total) | round(0) | int }}%)
were classified as needing enrichment or more information. Improving bug report templates and encouraging
reporters to include reproduction steps, expected vs actual behavior, and version details could
meaningfully increase the AI fix rate.
</div>

<h2>Architecture Context Availability</h2>
<p>Fix quality depends on the AI having access to relevant source code and architecture documentation:</p>
<table>
  <thead><tr><th>Context Level</th><th>Bugs</th><th>Share</th></tr></thead>
  <tbody>
  {% for rating, count in s.context_ratings.items() %}
    <tr><td>{{ rating }}</td><td>{{ count }}</td><td>{{ (count * 100 / s.total) | round(1) }}%</td></tr>
  {% endfor %}
  </tbody>
</table>

<h2>Fix Confidence</h2>
<p>Of the {{ s.n_fixable }} AI-fixable bugs:</p>
<table>
  <thead><tr><th>Confidence Level</th><th>Count</th></tr></thead>
  <tbody>
  {% for conf, count in s.confidences.items() %}
    <tr><td>{{ conf }}</td><td>{{ count }}</td></tr>
  {% endfor %}
  </tbody>
</table>

<h2>Agent Ready vs Actual Readiness</h2>
<p>The org-wide bug bash directs participants to use
<a href="https://ugiordan.github.io/ai-bug-automation-readiness/report.html">Agent Ready</a>
scores to prioritize which repos to work on. Our pipeline data shows this is not an effective
prioritization signal.</p>

<div class="caution-box">
<strong>Key finding:</strong> Agent Ready scores (which measure repo structure) and pipeline readiness
scores (which measure actual AI fix success) have a Spearman correlation of <strong>-0.125</strong>
&mdash; essentially zero. Knowing a repo's Agent Ready score tells you nothing about whether
AI can fix bugs filed against it.
</div>

<p>Agent Ready evaluates whether a repo has a README, CLAUDE.md, test infrastructure, and CI.
Most repos in the ecosystem score 70-88 on this measure &mdash; the variance is too low to
differentiate. Meanwhile, actual fix rates range from 0% to 100% depending on bug report quality
and architecture context availability, neither of which Agent Ready measures.</p>

<p>Components where Agent Ready scores highest (88) but AI fix rates are lowest include
Documentation (15.4% fix rate), DevOps (8.3%), and Internal Processes (0%). These components
have well-structured repos but unfixable bugs &mdash; because the bugs are about content,
infrastructure, or process rather than code.</p>

<p>See the <a href="/readiness">Readiness page</a> for the full per-component comparison.</p>

<h2>Recommendations</h2>
<ol>
  <li><strong>Prioritize bug report quality.</strong> The single largest constraint on AI fixability
  is incomplete bug reports. Invest in templates and triage processes that ensure reproduction steps,
  environment details, and expected behavior are captured upfront.</li>
  <li><strong>Expand architecture context.</strong> {{ s.context_ratings.get('no-context', 0) }} bugs
  ({{ s.coverage_pct.none }}%) had no architecture context. Adding architecture documentation and
  source checkouts for under-covered components directly increases fix eligibility.</li>
  <li><strong>Focus human review on high-confidence fixes.</strong> {{ s.confidences.get('high', 0) }}
  fixes were rated high-confidence. These are the best candidates for expedited human review and merge.</li>
  <li><strong>Use AI-generated test plans.</strong> {{ s.with_test_plan }} test plans were generated,
  with {{ s.efforts.get('lightweight', 0) }} classified as lightweight effort. These can accelerate
  verification of both AI and human fixes.</li>
  <li><strong>Do not rely on Agent Ready scores for bug prioritization.</strong> Use component fix rate
  history and context helpfulness scores instead. Components with context helpfulness above 55 have
  fix rates above 80%; components below 30 have fix rates below 50%.</li>
</ol>
</div>
{% endblock %}
"""

SUMMARY_DEVELOPER = """\
{% extends "layout.html" %}
{% block title %}Developer Guide - Bug Bash{% endblock %}
{% block content %}
<style>
  .prose { max-width: 900px; line-height: 1.7; font-size: 1em; }
  .prose h2 { border-bottom: 2px solid #ddd; padding-bottom: 0.3em; margin-top: 2em; }
  .prose h3 { margin-top: 1.5em; }
  .prose code { background: #e8e8e8; padding: 0.1em 0.3em; border-radius: 3px; font-size: 0.9em; }
  .prose pre { background: #1e1e1e; color: #d4d4d4; padding: 1em; border-radius: 6px; overflow-x: auto; font-size: 0.85em; }
  .info-box { background: #eaf2f8; border-left: 4px solid #3498db; padding: 1em 1.5em; margin: 1.5em 0; border-radius: 4px; }
  .warn-box { background: #fef9e7; border-left: 4px solid #f39c12; padding: 1em 1.5em; margin: 1.5em 0; border-radius: 4px; }
  .prose table { font-size: 0.9em; }
  .bar { display: inline-block; height: 1em; border-radius: 2px; vertical-align: middle; }
  .bar-fix { background: #27ae60; }
  .bar-nofix { background: #c0392b; }
  .bar-other { background: #95a5a6; }
</style>

<div class="prose">
<p><a href="/summary">&larr; All summaries</a></p>
<h1>Developer Guide</h1>
<p>Practical breakdown of the AI bug analysis pipeline results for {{ s.total }} RHOAIENG issues.
Use this to understand which bugs have AI-generated fixes, where the gaps are, and how to
work with the outputs.</p>

<h2>Fix Recommendation Breakdown</h2>
<p>Each bug that reached the fix-attempt phase received one of these classifications:</p>
<table>
  <thead><tr><th>Recommendation</th><th>Count</th><th>What It Means</th></tr></thead>
  <tbody>
    <tr>
      <td><span class="badge badge-fix-ai-fixable">ai-fixable</span></td>
      <td>{{ s.fix_recommendations.get('ai-fixable', 0) }}</td>
      <td>AI produced a patch with root cause analysis. Ready for human review.</td>
    </tr>
    <tr>
      <td><span class="badge badge-fix-ai-could-not-fix">ai-could-not-fix</span></td>
      <td>{{ s.fix_recommendations.get('ai-could-not-fix', 0) }}</td>
      <td>AI analyzed the bug but couldn't produce a viable fix. Often due to insufficient context, complex cross-component issues, or missing reproduction details.</td>
    </tr>
    <tr>
      <td><span class="badge badge-fix-already-fixed">already-fixed</span></td>
      <td>{{ s.fix_recommendations.get('already-fixed', 0) }}</td>
      <td>Evidence suggests the bug is already resolved in the current codebase.</td>
    </tr>
    <tr>
      <td><span class="badge badge-fix-upstream-required">upstream-required</span></td>
      <td>{{ s.fix_recommendations.get('upstream-required', 0) + s.fix_recommendations.get('submit_upstream', 0) }}</td>
      <td>Fix needs to go through an upstream project first.</td>
    </tr>
    <tr>
      <td><span class="badge badge-fix-not-a-bug">not-a-bug</span></td>
      <td>{{ s.fix_recommendations.get('not-a-bug', 0) }}</td>
      <td>Analysis suggests this is expected behavior or a misunderstanding.</td>
    </tr>
    <tr>
      <td><span class="badge badge-fix-docs-only">docs-only</span></td>
      <td>{{ s.fix_recommendations.get('docs-only', 0) }}</td>
      <td>No code change needed; a documentation update would resolve the issue.</td>
    </tr>
    <tr>
      <td><span class="badge badge-fix-insufficient-info">insufficient-info</span></td>
      <td>{{ s.fix_recommendations.get('insufficient-info', 0) }}</td>
      <td>Not enough information in the bug report to attempt a fix.</td>
    </tr>
  </tbody>
</table>
<p>{{ s.total - s.with_fix_attempt }} bugs never reached the fix phase due to missing prerequisites
(no architecture context, issue in active review, or no identifiable components).</p>

<h2>Triage Classifications</h2>
<p>The completeness phase assigns a triage label to each bug. These describe bug report quality
but <strong>do not gate the fix phase</strong> &mdash; bugs of all triage classifications proceed
to fix-attempt if they meet the other prerequisites.</p>

<table>
  <thead><tr><th>Triage Classification</th><th>Count</th><th>What It Means</th></tr></thead>
  <tbody>
    <tr>
      <td>ai-fixable</td>
      <td>{{ s.triage_recommendations.get('ai-fixable', 0) }}</td>
      <td>Bug report has sufficient detail (reproduction steps, expected behavior, environment) for a direct fix attempt.</td>
    </tr>
    <tr>
      <td>needs-enrichment</td>
      <td>{{ s.triage_recommendations.get('needs-enrichment', 0) }}</td>
      <td>Bug report exists but lacks some details. Fix attempts still proceed &mdash; the AI works with what's available, but fix quality may be lower.</td>
    </tr>
    <tr>
      <td>needs-info</td>
      <td>{{ s.triage_recommendations.get('needs-info', 0) }}</td>
      <td>Bug report is sparse. Fix attempts still proceed but are more likely to result in <code>ai-could-not-fix</code> or <code>insufficient-info</code>.</td>
    </tr>
  </tbody>
</table>

<h2>Why Bugs Get Skipped</h2>
<p>The pipeline skips bugs before the fix phase for structural reasons, not triage classification:</p>
<ul>
  <li><strong>No context</strong> (context rating = "no-context") &mdash; the context-map phase found no relevant architecture docs or source code for the bug's components.</li>
  <li><strong>Active work</strong> (status = Review or Testing) &mdash; someone is already working on the issue.</li>
  <li><strong>Low completeness</strong> (score &lt; 0) &mdash; the bug report scored below the minimum threshold.</li>
  <li><strong>No components identified</strong> &mdash; the context-map couldn't determine which repos to clone.</li>
</ul>
<p>{{ s.total - s.with_fix_attempt }} of {{ s.total }} bugs were filtered out for one of these reasons.</p>

<h2>Context Quality</h2>
<p>The AI's ability to produce good fixes depends heavily on having relevant source code and
architecture documentation. The context helpfulness score (0-100) measures this across three dimensions:</p>

<table>
  <thead><tr><th>Dimension</th><th>Avg Score</th><th>Median</th><th>P25-P75</th></tr></thead>
  <tbody>
    <tr><td>Overall helpfulness</td><td>{{ s.ctx_dist.avg }}</td><td>{{ s.ctx_dist.median }}</td><td>{{ s.ctx_dist.p25 }}-{{ s.ctx_dist.p75 }}</td></tr>
    <tr><td>Coverage</td><td>{{ s.cov_dist.avg }}</td><td>{{ s.cov_dist.median }}</td><td>{{ s.cov_dist.p25 }}-{{ s.cov_dist.p75 }}</td></tr>
    <tr><td>Depth</td><td>{{ s.depth_dist.avg }}</td><td>{{ s.depth_dist.median }}</td><td>{{ s.depth_dist.p25 }}-{{ s.depth_dist.p75 }}</td></tr>
    <tr><td>Freshness</td><td>{{ s.fresh_dist.avg }}</td><td>{{ s.fresh_dist.median }}</td><td>{{ s.fresh_dist.p25 }}-{{ s.fresh_dist.p75 }}</td></tr>
  </tbody>
</table>

<div class="info-box">
<strong>Coverage</strong> measures whether the relevant components are represented.
<strong>Depth</strong> measures whether the available context is detailed enough.
<strong>Freshness</strong> measures whether the context is from a recent enough version.
Low freshness scores often mean the architecture docs are from an older release.
</div>

<h2>Component Breakdown</h2>
<p>Top 15 components by issue volume, showing how many received AI-fixable recommendations:</p>

<table>
  <thead><tr><th>Component</th><th>Total</th><th>AI-Fixable</th><th>Fix Rate</th><th>Could Not Fix</th></tr></thead>
  <tbody>
  {% for c in s.component_breakdown %}
    <tr>
      <td>{{ c.name }}</td>
      <td>{{ c.total }}</td>
      <td>{{ c.ai_fixable }}</td>
      <td>
        <span class="bar bar-fix" style="width:{{ c.fix_rate * 0.8 }}px;"></span>
        {{ c.fix_rate }}%
      </td>
      <td>{{ c.not_fixable }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>

<h2>Test Plan Effort Estimates</h2>
<p>AI-generated test plans classify verification effort as:</p>
<table>
  <thead><tr><th>Effort Level</th><th>Count</th><th>Description</th></tr></thead>
  <tbody>
    <tr>
      <td>lightweight</td>
      <td>{{ s.efforts.get('lightweight', 0) }}</td>
      <td>Unit tests or simple functional checks. Can be run in CI without special infrastructure.</td>
    </tr>
    <tr>
      <td>moderate</td>
      <td>{{ s.efforts.get('moderate', 0) }}</td>
      <td>Integration tests requiring component setup. May need a test cluster or specific configuration.</td>
    </tr>
    <tr>
      <td>heavy</td>
      <td>{{ s.efforts.get('heavy', 0) }}</td>
      <td>End-to-end or multi-component testing requiring full environment setup.</td>
    </tr>
  </tbody>
</table>

<h2>How to Use the Fix Outputs</h2>
<div class="info-box">
<p>For each AI-fixable bug, the pipeline produces:</p>
<ul>
  <li><strong>Root cause hypothesis</strong> - explanation of what's likely going wrong</li>
  <li><strong>Affected files</strong> - specific files and the changes needed</li>
  <li><strong>Patch</strong> - a diff you can apply (review carefully; these are AI-generated)</li>
  <li><strong>Risks</strong> - potential side effects the AI identified</li>
  <li><strong>Test plan</strong> - suggested tests to verify the fix</li>
</ul>
<p>View individual issues at <code>/issue/RHOAIENG-NNNN</code> to see the full analysis.
Use the <a href="/">dashboard</a> filters to find high-confidence, AI-fixable bugs in your component.</p>
</div>

<div class="warn-box">
<strong>Caveat:</strong> AI-generated patches require human review. The confidence rating reflects
the AI's self-assessment, not a guarantee of correctness. High-confidence fixes are more likely
to be correct but should still be reviewed for edge cases and side effects.
</div>

<h2>Agent Ready Scores vs Pipeline Results</h2>
<p>The bug bash planning references
<a href="https://ugiordan.github.io/ai-bug-automation-readiness/report.html">Agent Ready</a>
scores as a way to assess which repos are ready for AI-assisted work. Agent Ready evaluates
repo structure (README, CLAUDE.md, test infra, CI, PR templates) across 20 checks. However,
these scores do not predict whether AI can fix bugs in those repos.</p>

<div class="warn-box">
<strong>The two metrics do not correlate.</strong> Spearman rho = -0.125 between Agent Ready
scores and pipeline-derived readiness. Agent Ready scores cluster in the 70-88 range across
most repos, providing no differentiation. Meanwhile, fix rates vary from 0% to 100%.
</div>

<h3>What Actually Predicts Fixability</h3>
<p>If you're deciding which bugs to work on, use these signals instead of Agent Ready:</p>
<table>
  <thead><tr><th>Signal</th><th>Where to Find It</th><th>Why It Matters</th></tr></thead>
  <tbody>
    <tr>
      <td>Context helpfulness &gt; 55</td>
      <td><a href="/">Dashboard</a>, Context Quality column</td>
      <td>Components above 55 have fix rates &gt; 80%. Below 30 = fix rates &lt; 50%.</td>
    </tr>
    <tr>
      <td>Triage = <code>ai-fixable</code></td>
      <td><a href="/">Dashboard</a>, Triage column</td>
      <td>Bug report is complete enough for AI to attempt a fix.</td>
    </tr>
    <tr>
      <td>Component fix rate history</td>
      <td><a href="/readiness">Readiness page</a></td>
      <td>AI Core Dashboard (90%), AI Pipelines (91%), Model Serving (88%) work well. Documentation (15%), DevOps (8%) do not.</td>
    </tr>
    <tr>
      <td>Completeness score &ge; 40</td>
      <td><a href="/">Dashboard</a>, Bug Quality column</td>
      <td>Higher completeness means more information for the AI to work with.</td>
    </tr>
  </tbody>
</table>

<h3>When Agent Ready Scores Are Useful</h3>
<p>Agent Ready is still useful for one thing: identifying repos that lack basic prerequisites
for AI agent work (no CLAUDE.md, no test infrastructure, no build scripts). Repos scoring
below 40 genuinely need structural improvements. But for repos scoring 60+, the score tells
you nothing about bug fixability.</p>

<p>See the <a href="/readiness">Readiness page</a> for the full per-component breakdown comparing
both scores, and the <a href="/docs/agent-ready-analysis.md">detailed analysis</a> for methodology.</p>
</div>
{% endblock %}
"""

SUMMARY_STATISTICIAN = """\
{% extends "layout.html" %}
{% block title %}Statistical Analysis - Bug Bash{% endblock %}
{% block content %}
<style>
  .prose { max-width: 900px; line-height: 1.7; font-size: 1em; }
  .prose h2 { border-bottom: 2px solid #ddd; padding-bottom: 0.3em; margin-top: 2em; }
  .prose h3 { margin-top: 1.5em; }
  .prose code { background: #e8e8e8; padding: 0.1em 0.3em; border-radius: 3px; font-size: 0.9em; }
  .meth-box { background: #f0f4f8; border-left: 4px solid #8e44ad; padding: 1em 1.5em; margin: 1.5em 0; border-radius: 4px; }
  .finding-box { background: #eafaf1; border-left: 4px solid #27ae60; padding: 1em 1.5em; margin: 1.5em 0; border-radius: 4px; }
  .caveat-box { background: #fdedec; border-left: 4px solid #c0392b; padding: 1em 1.5em; margin: 1.5em 0; border-radius: 4px; }
  .prose table { font-size: 0.9em; }
</style>

<div class="prose">
<p><a href="/summary">&larr; All summaries</a></p>
<h1>Statistical Analysis Report</h1>
<p>Detailed statistical summary of the AI bug analysis pipeline across {{ s.total }} RHOAIENG issues.
For interactive visualizations and test results, see the <a href="/stats">Stats page</a>.</p>

<h2>Data Overview</h2>

<div class="meth-box">
<strong>Population:</strong> {{ s.total }} issues from RHOAIENG Jira project.
This is a census of the active bug backlog, not a sample, so inferential statistics
are used to characterize effect magnitudes rather than to generalize to a larger population.
</div>

<h3>Phase Completion Rates</h3>
<table>
  <thead><tr><th>Phase</th><th>N</th><th>Rate</th><th>Notes</th></tr></thead>
  <tbody>
    <tr><td>Completeness</td><td>{{ s.with_completeness }}</td><td>{{ (s.with_completeness * 100 / s.total) | round(1) }}%</td><td>All issues scored</td></tr>
    <tr><td>Context map</td><td>{{ s.with_context_map }}</td><td>{{ (s.with_context_map * 100 / s.total) | round(1) }}%</td><td>All issues mapped</td></tr>
    <tr><td>Fix attempt</td><td>{{ s.with_fix_attempt }}</td><td>{{ (s.with_fix_attempt * 100 / s.total) | round(1) }}%</td><td>Filtered by context availability, issue status, component identification (not triage classification)</td></tr>
    <tr><td>Test plan</td><td>{{ s.with_test_plan }}</td><td>{{ (s.with_test_plan * 100 / s.total) | round(1) }}%</td><td>Generated for all issues</td></tr>
  </tbody>
</table>

<h2>Outcome Variable: Fix Recommendation</h2>
<p>The primary outcome is the fix recommendation, a categorical variable with {{ s.fix_recommendations | length }} levels:</p>
<table>
  <thead><tr><th>Category</th><th>N</th><th>Proportion</th></tr></thead>
  <tbody>
  {% for cat, count in s.fix_recommendations.items() %}
    <tr>
      <td>{{ cat }}</td>
      <td>{{ count }}</td>
      <td>{{ (count * 100 / s.with_fix_attempt) | round(1) }}%</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
<p>For binary modeling, this is collapsed to <code>ai-fixable</code> (1) vs all others (0),
yielding a base rate of {{ s.fix_rate_of_analyzed }}% among the {{ s.with_fix_attempt }} issues
that reached the fix phase.</p>

<h2>Predictor Distributions</h2>

<h3>Completeness Score (Bug Report Quality)</h3>
<table>
  <thead><tr><th>Statistic</th><th>Value</th></tr></thead>
  <tbody>
    <tr><td>N</td><td>{{ s.comp_dist.n }}</td></tr>
    <tr><td>Mean</td><td>{{ s.comp_dist.avg }}</td></tr>
    <tr><td>Median</td><td>{{ s.comp_dist.median }}</td></tr>
    <tr><td>IQR</td><td>{{ s.comp_dist.p25 }} - {{ s.comp_dist.p75 }}</td></tr>
    <tr><td>Range</td><td>{{ s.comp_dist.min }} - {{ s.comp_dist.max }}</td></tr>
  </tbody>
</table>
<p>The distribution is roughly symmetric around the median of {{ s.comp_dist.median }}, with an IQR
of {{ s.comp_dist.p75 - s.comp_dist.p25 }} points. The moderate mean ({{ s.comp_dist.avg }}/100)
reflects that most bug reports lack several completeness dimensions.</p>

<h3>Context Helpfulness Score</h3>
<table>
  <thead><tr><th>Statistic</th><th>Value</th></tr></thead>
  <tbody>
    <tr><td>N</td><td>{{ s.ctx_dist.n }}</td></tr>
    <tr><td>Mean</td><td>{{ s.ctx_dist.avg }}</td></tr>
    <tr><td>Median</td><td>{{ s.ctx_dist.median }}</td></tr>
    <tr><td>IQR</td><td>{{ s.ctx_dist.p25 }} - {{ s.ctx_dist.p75 }}</td></tr>
    <tr><td>Range</td><td>{{ s.ctx_dist.min }} - {{ s.ctx_dist.max }}</td></tr>
  </tbody>
</table>
<p>This composite score (0-100) is derived from coverage, depth, and freshness sub-dimensions:</p>
<table>
  <thead><tr><th>Sub-dimension</th><th>N</th><th>Mean</th><th>Median</th><th>IQR</th></tr></thead>
  <tbody>
    <tr><td>Coverage</td><td>{{ s.cov_dist.n }}</td><td>{{ s.cov_dist.avg }}</td><td>{{ s.cov_dist.median }}</td><td>{{ s.cov_dist.p25 }}-{{ s.cov_dist.p75 }}</td></tr>
    <tr><td>Depth</td><td>{{ s.depth_dist.n }}</td><td>{{ s.depth_dist.avg }}</td><td>{{ s.depth_dist.median }}</td><td>{{ s.depth_dist.p25 }}-{{ s.depth_dist.p75 }}</td></tr>
    <tr><td>Freshness</td><td>{{ s.fresh_dist.n }}</td><td>{{ s.fresh_dist.avg }}</td><td>{{ s.fresh_dist.median }}</td><td>{{ s.fresh_dist.p25 }}-{{ s.fresh_dist.p75 }}</td></tr>
  </tbody>
</table>

<h3>Context Rating (Categorical)</h3>
<table>
  <thead><tr><th>Rating</th><th>N</th><th>%</th></tr></thead>
  <tbody>
  {% for rating, count in s.context_ratings.items() %}
    <tr><td>{{ rating }}</td><td>{{ count }}</td><td>{{ (count * 100 / s.total) | round(1) }}%</td></tr>
  {% endfor %}
  </tbody>
</table>

<h2>Key Statistical Findings</h2>
<p>The following summarizes results from the <a href="/stats">interactive statistics page</a>,
which runs Spearman correlations, chi-squared independence tests, Kruskal-Wallis H-tests,
Mann-Whitney U tests, and logistic regression on the full dataset.</p>

<div class="finding-box">
<strong>Context helpfulness is the strongest predictor of fixability.</strong>
In the logistic regression model (binary outcome: ai-fixable vs not), context_helpfulness
has the largest standardized coefficient among the continuous predictors.
The Kruskal-Wallis test confirms that context helpfulness scores differ significantly
across fix recommendation groups. Issues classified as <code>ai-fixable</code> have
substantially higher context helpfulness scores than those classified as
<code>ai-could-not-fix</code>.
</div>

<div class="finding-box">
<strong>Bug report quality (completeness score) has a secondary but significant effect.</strong>
It correlates positively with context helpfulness (the two are not independent - better-documented bugs
tend to have better-identified components and thus better context retrieval).
The partial effect after controlling for context helpfulness is smaller than the
bivariate association suggests.
</div>

<div class="finding-box">
<strong>Chi-squared tests show strong association between context rating and fix recommendation.</strong>
Issues with <code>full-context</code> ratings are disproportionately classified as
<code>ai-fixable</code>. Issues with <code>no-context</code> are disproportionately
classified as <code>ai-could-not-fix</code>. The effect size (Cramer's V) indicates
a medium-to-large practical association.
</div>

<h2>Confidence Distribution</h2>
<p>Among the {{ s.n_fixable }} AI-fixable issues, self-reported confidence levels are:</p>
<table>
  <thead><tr><th>Confidence</th><th>N</th><th>%</th></tr></thead>
  <tbody>
  {% for conf, count in s.confidences.items() %}
    <tr><td>{{ conf }}</td><td>{{ count }}</td><td>{{ (count * 100 / s.with_fix_attempt) | round(1) }}%</td></tr>
  {% endfor %}
  </tbody>
</table>
<p>Note: confidence is an ordinal self-assessment by the AI model (low / medium / high),
not a calibrated probability. It should be treated as a rough signal for prioritization rather
than a statistical confidence interval.</p>

<h2>Methodological Notes</h2>
<div class="meth-box">
<ul>
  <li><strong>Correlation:</strong> Spearman rank correlation is used throughout because the
  completeness and helpfulness scores are ordinal/bounded and may not be normally distributed.
  Spearman is robust to monotone nonlinearity.</li>
  <li><strong>Group tests:</strong> Kruskal-Wallis (non-parametric ANOVA) is used for multi-group
  comparisons because the outcome groups have unequal sizes and the score distributions may be
  non-normal. Mann-Whitney U is used for binary predictor tests.</li>
  <li><strong>Chi-squared:</strong> Applied to contingency tables of categorical variables.
  Cramer's V provides an effect size metric (0.1 = small, 0.3 = medium, 0.5 = large).</li>
  <li><strong>Logistic regression:</strong> IRLS implementation with standardized features.
  McFadden's pseudo-R-squared is reported for model fit. Odds ratios reflect the effect
  of a 1-SD change in the standardized predictor.</li>
</ul>
</div>

<h2>Agent Ready Scores: Construct Validity Analysis</h2>
<p>The <a href="https://ugiordan.github.io/ai-bug-automation-readiness/report.html">Agent Ready</a>
assessment tool scores repositories on 20 structural checks across 4 phases (Understand, Navigate,
Verify, Submit). The org-wide bug bash uses these scores to guide participants toward
"AI-ready" repos. We can evaluate the construct validity of this score by comparing it against
the pipeline's empirical readiness measure.</p>

<div class="finding-box">
<strong>Agent Ready scores do not predict AI fixability.</strong>
Spearman rank correlation between Agent Ready (best repo per component) and pipeline readiness
score: rho = -0.125, n = 42 components. The relationship is non-significant and slightly negative.
</div>

<h3>Why the Scores Diverge</h3>
<p>Agent Ready measures <em>repository structure</em> (does CLAUDE.md exist? are there tests?).
The pipeline measures <em>bug fixability</em> (can AI produce a correct patch given the bug report
and available context?). These are different constructs:</p>

<table>
  <thead><tr><th>Property</th><th>Agent Ready</th><th>Pipeline Readiness</th></tr></thead>
  <tbody>
    <tr><td>Unit of analysis</td><td>Repository</td><td>Jira component (aggregated bugs)</td></tr>
    <tr><td>Measurement type</td><td>Structural checklist (binary/ordinal per check)</td><td>Empirical outcome (fix rate, context scores)</td></tr>
    <tr><td>What it captures</td><td>Repo hygiene, documentation presence, CI setup</td><td>Bug report quality, architecture context quality, fix success</td></tr>
    <tr><td>Variance across ecosystem</td><td>Low (most repos score 70-88)</td><td>High (fix rates range 0-100%)</td></tr>
    <tr><td>Sensitivity to bug quality</td><td>None</td><td>High (completeness score is a significant predictor)</td></tr>
  </tbody>
</table>

<h3>Restricted Range Problem</h3>
<p>Agent Ready scores for odh repos cluster in a narrow band (IQR roughly 60-80). When a variable
has restricted range, correlations with other variables are attenuated toward zero even if a true
relationship exists in a broader population. However, the direction of the observed correlation
is negative, suggesting that even with expanded range, the relationship would be weak at best.</p>

<h3>Context Helpfulness Stratified by Agent Ready</h3>
<p>Stratifying components by Agent Ready tier shows that Agent Ready score does not differentiate
context helpfulness or fix rates:</p>
<table>
  <thead><tr><th>Context Helpfulness Range</th><th>Avg Fix Rate</th><th>Avg Agent Ready</th><th>N Components</th></tr></thead>
  <tbody>
    <tr><td>65+</td><td>~88%</td><td>~82</td><td>13</td></tr>
    <tr><td>40-64</td><td>~58%</td><td>~82</td><td>10</td></tr>
    <tr><td>&lt; 40</td><td>~23%</td><td>~83</td><td>12</td></tr>
  </tbody>
</table>
<p>Agent Ready averages are nearly identical across all context helpfulness tiers. The metric
has no discriminative power for the outcome of interest.</p>

<h3>False Positive Pattern</h3>
<p>The 10 largest gaps between pipeline and Agent Ready scores are uniformly in one direction:
Agent Ready overestimates readiness. The worst cases are components where bugs are about
infrastructure, process, or documentation rather than code (Documentation: AR=88, Pipeline=25;
DevOps: AR=88, Pipeline=22). Agent Ready evaluates the repository; the bugs are about something
else entirely.</p>

<p>See the <a href="/readiness">Readiness page</a> for interactive per-component data.</p>

<h2>Caveats and Limitations</h2>
<div class="caveat-box">
<ul>
  <li><strong>Non-independence of predictors:</strong> Bug quality, context availability, and
  triage recommendation are correlated. Multicollinearity affects coefficient stability
  in the logistic model. The individual predictor p-values should be interpreted cautiously.</li>
  <li><strong>AI self-assessment bias:</strong> Both the completeness score and the fix
  recommendation are AI-generated. The pipeline uses the same underlying model for scoring
  and fixing, so the "predictors" and "outcome" are not truly independent measurements.</li>
  <li><strong>Binary predictor imbalance:</strong> Nearly all issues (>98%) have architecture
  documentation available. The <code>has_arch_doc</code> variable therefore has very low variance,
  making Mann-Whitney and chi-squared tests underpowered for this predictor.
  The continuous <code>context_helpfulness</code> score is a better measure of context quality.</li>
  <li><strong>Selection bias in fix phase:</strong> The {{ s.total - s.with_fix_attempt }} issues
  that were filtered out before the fix phase are systematically different from those that
  entered it (lower completeness, less context). Statistics on fix outcomes apply only
  to the subset that reached that phase.</li>
  <li><strong>Census, not sample:</strong> Since this is the complete active backlog rather than
  a random sample, p-values should be interpreted as measures of effect magnitude rather than
  as inference about a larger population.</li>
  <li><strong>Agent Ready comparison caveat:</strong> The pipeline score and Agent Ready score
  operate at different levels of analysis (Jira component vs repository). The mapping between
  them is many-to-many: one component can touch multiple repos, and one repo can serve multiple
  components. The "best repo" and "average repo" variants of the Agent Ready comparison both
  yield the same conclusion (no correlation), but the mapping imprecision adds noise.</li>
</ul>
</div>
</div>
{% endblock %}
"""

COMPONENT_READINESS = """\
{% extends "layout.html" %}
{% block title %}Component Readiness - Bug Bash{% endblock %}
{% block content %}
<style>
  .readiness-intro { max-width: 900px; margin-bottom: 1.5rem; }
  .readiness-intro p { color: #555; line-height: 1.6; }
  .legend { display: flex; gap: 1.5rem; flex-wrap: wrap; margin-bottom: 1rem; font-size: 0.85em; }
  .legend-item { display: flex; align-items: center; gap: 0.3em; }
  .legend-swatch { width: 14px; height: 14px; border-radius: 3px; }
  .ar-score { font-weight: bold; }
  .ar-na { color: #95a5a6; font-style: italic; }
  .expand-btn { cursor: pointer; background: none; border: none; font-size: 1.1em; padding: 0 0.3em; }
  .detail-row { display: none; }
  .detail-row.show { display: table-row; }
  .detail-cell { padding: 0.8em 1em; background: #f8f9fa; }
  .detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  @media (max-width: 900px) { .detail-grid { grid-template-columns: 1fr; } }
  .detail-grid table { font-size: 0.85em; margin: 0; }
  .detail-grid h4 { margin: 0 0 0.3em 0; font-size: 0.95em; }
  .mini-bar { display: inline-block; height: 0.9em; border-radius: 2px; vertical-align: middle; }
  .cmp-row { cursor: pointer; }
  .cmp-row:hover { background: #f0f4f8; }
  .gap-indicator { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 0.3em; }
  .gap-high { background: #c0392b; }
  .gap-med { background: #f39c12; }
  .gap-low { background: #27ae60; }
  .gap-na { background: #bdc3c7; }
</style>

<div class="readiness-intro">
<h2>Component Readiness</h2>
<p>Per-component comparison of pipeline-derived readiness (based on fix rates, context quality,
and bug report completeness) with <a href="https://ugiordan.github.io/ai-bug-automation-readiness/report.html" target="_blank">Agent Ready</a>
repo scores (based on repo structure, documentation, and CI maturity).</p>
<p><strong>Pipeline Score</strong> = 50% fix rate + 30% context helpfulness + 20% completeness (0-100 scale).
<strong>Agent Ready</strong> scores are from the 2026-03-17 assessment of opendatahub-io repos.</p>
</div>

<div class="legend">
  <div class="legend-item"><div class="legend-swatch" style="background:#27ae60;"></div> 80+ (Ready)</div>
  <div class="legend-item"><div class="legend-swatch" style="background:#d4a017;"></div> 60-79 (Partial)</div>
  <div class="legend-item"><div class="legend-swatch" style="background:#e67e22;"></div> 40-59 (Needs Work)</div>
  <div class="legend-item"><div class="legend-swatch" style="background:#c0392b;"></div> &lt;40 (Not Ready)</div>
</div>

<div style="overflow-x:auto;">
<table role="grid" id="readiness-table">
  <thead>
    <tr>
      <th></th>
      <th class="sortable" data-col="1">Component</th>
      <th class="sortable" data-col="2" data-type="number">Bugs</th>
      <th class="sortable" data-col="3" data-type="number">Fix<br>Attempts</th>
      <th class="sortable" data-col="4" data-type="number">AI-<br>Fixable</th>
      <th class="sortable" data-col="5" data-type="number">Fix<br>Rate</th>
      <th class="sortable" data-col="6" data-type="number">Pipeline<br>Score</th>
      <th class="sortable" data-col="7" data-type="number">Agent Ready<br>(Best Repo)</th>
      <th class="sortable" data-col="8" data-type="number">Agent Ready<br>(Avg Repos)</th>
      <th class="sortable" data-col="9" data-type="number">Context<br>Helpfulness</th>
      <th class="sortable" data-col="10" data-type="number">Bug Report<br>Quality</th>
      <th>Gap</th>
    </tr>
  </thead>
  <tbody>
    {% for c in components %}
    <tr class="cmp-row" onclick="toggleDetail('{{ loop.index }}')">
      <td><button class="expand-btn" id="btn-{{ loop.index }}">&#9654;</button></td>
      <td>{{ c.name }}</td>
      <td>{{ c.total }}</td>
      <td>{{ c.with_fix }}</td>
      <td>{{ c.fixable }}</td>
      <td data-sort-value="{{ c.fix_rate }}">
        <span class="mini-bar" style="width:{{ [c.fix_rate * 0.6, 1] | max }}px; background:{{ '#27ae60' if c.fix_rate >= 60 else ('#d4a017' if c.fix_rate >= 30 else '#c0392b') }};"></span>
        {{ c.fix_rate }}%
      </td>
      <td data-sort-value="{{ c.pipeline_score }}">
        <span class="{{ 'score-green' if c.pipeline_score >= 80 else ('score-yellow' if c.pipeline_score >= 60 else 'score-red') }}">
          {{ c.pipeline_score }}
        </span>
      </td>
      <td data-sort-value="{{ c.agent_ready_best if c.agent_ready_best is not none else -1 }}">
        {% if c.agent_ready_best is not none %}
          <span class="ar-score {{ 'score-green' if c.agent_ready_best >= 80 else ('score-yellow' if c.agent_ready_best >= 60 else 'score-red') }}">
            {{ c.agent_ready_best }}
          </span>
        {% else %}
          <span class="ar-na">n/a</span>
        {% endif %}
      </td>
      <td data-sort-value="{{ c.agent_ready_avg if c.agent_ready_avg is not none else -1 }}">
        {% if c.agent_ready_avg is not none %}
          <span class="ar-score {{ 'score-green' if c.agent_ready_avg >= 80 else ('score-yellow' if c.agent_ready_avg >= 60 else 'score-red') }}">
            {{ c.agent_ready_avg }}
          </span>
        {% else %}
          <span class="ar-na">n/a</span>
        {% endif %}
      </td>
      <td data-sort-value="{{ c.ctx_avg }}">
        <span class="{{ 'score-green' if c.ctx_avg >= 70 else ('score-yellow' if c.ctx_avg >= 40 else 'score-red') }}">
          {{ c.ctx_avg }}
        </span>
      </td>
      <td data-sort-value="{{ c.comp_avg }}">
        <span class="{{ 'score-green' if c.comp_avg >= 70 else ('score-yellow' if c.comp_avg >= 40 else 'score-red') }}">
          {{ c.comp_avg }}
        </span>
      </td>
      <td>
        {% if c.agent_ready_best is not none %}
          {% set gap = (c.pipeline_score - c.agent_ready_best) | abs %}
          <span class="gap-indicator {{ 'gap-high' if gap > 25 else ('gap-med' if gap > 10 else 'gap-low') }}"></span>
          {% if c.pipeline_score > c.agent_ready_best %}+{% elif c.pipeline_score < c.agent_ready_best %}-{% endif %}{{ gap }}
        {% else %}
          <span class="gap-indicator gap-na"></span>
        {% endif %}
      </td>
    </tr>
    <tr class="detail-row" id="detail-{{ loop.index }}">
      <td colspan="12" class="detail-cell">
        <div class="detail-grid">
          <div>
            <h4>Mapped Repositories</h4>
            {% if c.top_repos %}
            <table>
              <thead><tr><th>Repo</th><th>Issues</th><th>Agent Ready</th></tr></thead>
              <tbody>
              {% for r in c.top_repos %}
                <tr>
                  <td><code>{{ r.name }}</code></td>
                  <td>{{ r.issues }}</td>
                  <td>
                    {% if r.agent_ready_score is not none %}
                      <span class="{{ 'score-green' if r.agent_ready_score >= 80 else ('score-yellow' if r.agent_ready_score >= 60 else 'score-red') }}">
                        {{ r.agent_ready_score }}
                      </span>
                    {% else %}
                      <span class="ar-na">n/a</span>
                    {% endif %}
                  </td>
                </tr>
              {% endfor %}
              </tbody>
            </table>
            {% else %}
            <p><em>No repos identified in context maps.</em></p>
            {% endif %}
          </div>
          <div>
            <h4>Context Dimensions</h4>
            <table>
              <tbody>
                <tr><td>Coverage</td><td>{{ c.cov_avg }}</td></tr>
                <tr><td>Depth</td><td>{{ c.depth_avg }}</td></tr>
                <tr><td>Freshness</td><td>{{ c.fresh_avg }}</td></tr>
              </tbody>
            </table>

            <h4>Context Ratings</h4>
            <table>
              <tbody>
              {% for rating, count in c.ctx_ratings.items() %}
                <tr><td>{{ rating }}</td><td>{{ count }}</td></tr>
              {% endfor %}
              </tbody>
            </table>

            {% if c.confidences %}
            <h4>Fix Confidence</h4>
            <table>
              <tbody>
              {% for conf, count in c.confidences.items() %}
                <tr><td>{{ conf }}</td><td>{{ count }}</td></tr>
              {% endfor %}
              </tbody>
            </table>
            {% endif %}

            {% if c.efforts %}
            <h4>Test Effort</h4>
            <table>
              <tbody>
              {% for eff, count in c.efforts.items() %}
                <tr><td>{{ eff }}</td><td>{{ count }}</td></tr>
              {% endfor %}
              </tbody>
            </table>
            {% endif %}
          </div>
        </div>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
</div>

<details style="margin-top:1.5rem;">
  <summary>About These Scores</summary>
  <div style="max-width:800px; line-height:1.6; padding:1em 0;">
    <p><strong>Pipeline Score</strong> is computed from this project's AI bug-fixing pipeline data:
    50% weight on the fix rate (percentage of analyzed bugs that received an AI-fixable recommendation),
    30% on average context helpfulness (how useful the available architecture documentation was),
    and 20% on average bug report completeness.</p>

    <p><strong>Agent Ready Score</strong> is from the
    <a href="https://ugiordan.github.io/ai-bug-automation-readiness/report.html">Agent Ready assessment</a>
    (2026-03-17 snapshot). It evaluates repository structure across 20 checks in 4 phases:
    Understand (README, CLAUDE.md, architecture docs), Navigate (project structure, type annotations),
    Verify (test infrastructure, CI), and Submit (PR templates, conventional commits).
    Scores are 0-100 with a verify-phase gate.</p>

    <p><strong>Gap</strong> shows the absolute difference between pipeline score and Agent Ready best repo score.
    A positive gap means pipeline score exceeds Agent Ready; negative means Agent Ready exceeds pipeline.
    Large gaps may indicate that one metric is capturing something the other misses, or that the
    Jira component maps to repos with different characteristics than expected.</p>

    <p><strong>Color coding:</strong> Green (80+) = ready, Yellow (60-79) = partially ready,
    Orange (40-59) = needs work, Red (&lt;40) = not ready. Applied to both pipeline and Agent Ready scores.</p>
  </div>
</details>
{% endblock %}

{% block scripts %}
<script>
function toggleDetail(idx) {
  const row = document.getElementById('detail-' + idx);
  const btn = document.getElementById('btn-' + idx);
  if (row.classList.contains('show')) {
    row.classList.remove('show');
    btn.innerHTML = '&#9654;';
  } else {
    row.classList.add('show');
    btn.innerHTML = '&#9660;';
  }
}

// Column sorting
document.querySelectorAll('#readiness-table th.sortable').forEach(th => {
  th.addEventListener('click', (e) => {
    e.stopPropagation();
    const table = document.getElementById('readiness-table');
    const tbody = table.querySelector('tbody');
    const col = parseInt(th.dataset.col);
    const isNum = th.dataset.type === 'number';
    const asc = th.dataset.dir !== 'asc';
    th.dataset.dir = asc ? 'asc' : 'desc';
    document.querySelectorAll('#readiness-table th.sortable').forEach(h => { if (h !== th) delete h.dataset.dir; });

    // Collect row pairs (main + detail) — use .children to avoid
    // selecting nested <tr> elements inside detail-row inner tables
    const pairs = [];
    const rows = Array.from(tbody.children);
    for (let i = 0; i < rows.length; i += 2) {
      pairs.push([rows[i], rows[i + 1]]);
    }
    pairs.sort((a, b) => {
      let va, vb;
      if (isNum) {
        va = parseFloat(a[0].cells[col].dataset.sortValue ?? a[0].cells[col].textContent) || -1;
        vb = parseFloat(b[0].cells[col].dataset.sortValue ?? b[0].cells[col].textContent) || -1;
      } else {
        va = a[0].cells[col].textContent.trim().toLowerCase();
        vb = b[0].cells[col].textContent.trim().toLowerCase();
      }
      if (va < vb) return asc ? -1 : 1;
      if (va > vb) return asc ? 1 : -1;
      return 0;
    });
    pairs.forEach(([main, detail]) => { tbody.appendChild(main); tbody.appendChild(detail); });
  });
});
</script>
{% endblock %}
"""

# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.jinja_loader = ChoiceLoader([
        DictLoader({
            "layout.html": LAYOUT,
            "tab_all.html": TAB_ALL_ISSUES,
            "tab_bugs.html": TAB_BUGS,
            "tab_rfes.html": TAB_RFES,
            "rfe_detail.html": RFE_DETAIL,
            "tab_strategies.html": TAB_STRATEGIES,
        }),
        app.jinja_loader,
    ])

    @app.route("/")
    def dashboard():
        issues = load_all_issues()

        # Flatten issues into one row per model
        rows = []
        for issue in issues:
            models = issue.get("models", {})
            if models:
                for mid, mdata in models.items():
                    row = {**issue}
                    row["model"] = mid
                    row["completeness"] = mdata.get("completeness")
                    row["context_map"] = mdata.get("context_map")
                    row["fix_attempt"] = mdata.get("fix_attempt")
                    row["test_plan"] = mdata.get("test_plan")
                    row["write_test"] = mdata.get("write_test")
                    rows.append(row)
            else:
                row = {**issue, "model": ""}
                rows.append(row)

        # Extract test-context helpfulness rating from last validation iteration
        _rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
        for row in rows:
            fa = row.get("fix_attempt")
            if fa and fa.get("validation"):
                last_iter = fa["validation"][-1]
                ratings = [
                    vr["test_context_helpfulness"]["rating"]
                    for vr in last_iter.get("results", [])
                    if vr.get("test_context_helpfulness", {}).get("rating")
                ]
                # Use the worst (lowest) rating across repos
                row["test_context_rating"] = (
                    min(ratings, key=lambda r: _rank.get(r, -1)) if ratings else ""
                )
            else:
                row["test_context_rating"] = ""

        # Summarise per-component arch-doc and source-checkout availability
        for row in rows:
            cm = row.get("context_map")
            entries = cm.get("context_entries", []) if cm else []
            if entries:
                has_arch = [e.get("architecture_doc", "not found") != "not found" for e in entries]
                has_src = [e.get("source_checkout", "not found") != "not found" for e in entries]
                row["arch_docs"] = "all" if all(has_arch) else ("partial" if any(has_arch) else "none")
                row["src_code"] = "all" if all(has_src) else ("partial" if any(has_src) else "none")
            else:
                row["arch_docs"] = ""
                row["src_code"] = ""

        model_names = sorted({r["model"] for r in rows if r["model"]})

        # Collect unique filter values
        statuses = sorted({r["status"] for r in rows})
        triages = sorted({
            r["completeness"]["triage_recommendation"]
            for r in rows if r.get("completeness") and "triage_recommendation" in r["completeness"]
        })
        issue_types = sorted({
            r["completeness"]["issue_type_assessment"]["classified_type"]
            for r in rows
            if r.get("completeness") and r["completeness"].get("issue_type_assessment")
        })
        context_ratings = sorted({
            r["context_map"]["overall_rating"]
            for r in rows if r.get("context_map") and "overall_rating" in r["context_map"]
        })
        components = sorted({
            c for r in rows for c in r.get("components", []) if c
        })
        fix_recommendations = sorted({
            r["fix_attempt"]["recommendation"]
            for r in rows if r.get("fix_attempt") and r["fix_attempt"].get("recommendation")
        })
        test_context_ratings = sorted({
            r["test_context_rating"]
            for r in rows if r["test_context_rating"]
        })
        arch_docs_values = sorted({r["arch_docs"] for r in rows if r["arch_docs"]})
        src_code_values = sorted({r["src_code"] for r in rows if r["src_code"]})
        write_test_decisions = sorted({
            r["write_test"]["decision"]
            for r in rows if r.get("write_test") and r["write_test"].get("decision")
        })

        # --- RFE data ---
        rfe_issues = load_rfe_issues()
        rfe_statuses = sorted({r.get("status", "") for r in rfe_issues if r.get("status")})
        rfe_priorities = sorted({r.get("priority", "") for r in rfe_issues if r.get("priority")})
        rfe_recommendations = sorted({
            r["review"]["recommendation"]
            for r in rfe_issues if r.get("review") and r["review"].get("recommendation")
        })

        # --- Strategy data ---
        strat_issues = load_strat_issues()
        strat_statuses = sorted({s.get("status", "") for s in strat_issues if s.get("status")})
        strat_priorities = sorted({s.get("priority", "") for s in strat_issues if s.get("priority")})
        strat_recommendations = sorted({
            s["review"]["recommendation"]
            for s in strat_issues if s.get("review") and s["review"].get("recommendation")
        })

        # --- Build unified all-issues list ---
        all_issues = []

        # Bugs: deduplicate by issue key (one row per issue, not per model)
        seen_bug_keys = set()
        for row in rows:
            k = row["key"]
            if k in seen_bug_keys:
                continue
            seen_bug_keys.add(k)
            comp = row.get("completeness")
            score = comp.get("overall_score", -1) if comp else -1
            rec = ""
            fa = row.get("fix_attempt")
            if fa:
                rec = fa.get("recommendation", "")
            all_issues.append({
                "type": "bug",
                "key": k,
                "title": row.get("summary", ""),
                "status": row.get("status", ""),
                "priority": row.get("priority", ""),
                "quality_score": score,
                "quality_display": str(score) if score >= 0 else "\u2014",
                "quality_class": (
                    "score-red" if score < 40 else ("score-yellow" if score < 80 else "score-green")
                ) if score >= 0 else "",
                "recommendation": rec,
                "security_verdict": "",
                "attention": bool(comp and comp.get("triage_recommendation")),
                "detail_url": f"/issue/{k}",
            })

        # RFEs
        for rfe in rfe_issues:
            rev = rfe.get("review")
            score = rev.get("score", -1) if rev else -1
            all_issues.append({
                "type": "rfe",
                "key": rfe["key"],
                "title": rfe.get("title", ""),
                "status": rfe.get("status", ""),
                "priority": rfe.get("priority", ""),
                "quality_score": score,
                "quality_display": f"{score}/10" if score >= 0 else "\u2014",
                "quality_class": (
                    "score-red" if score < 5 else ("score-yellow" if score < 8 else "score-green")
                ) if score >= 0 else "",
                "recommendation": rev.get("recommendation", "") if rev else "",
                "security_verdict": "",
                "attention": bool(rev and rev.get("needs_attention")),
                "detail_url": f"/#rfes",
            })

        # Strategies
        for st in strat_issues:
            rev = st.get("review")
            sec = st.get("security")
            verdict = sec.get("verdict", "") if sec else ""
            # Attention if any reviewer says reject OR security verdict is CONCERNS or FAIL
            attention = False
            if rev and rev.get("reviewers"):
                attention = any(v == "reject" for v in rev["reviewers"].values())
            if verdict.upper() in ("CONCERNS", "FAIL", "CONCERNS_CRITICAL"):
                attention = True
            all_issues.append({
                "type": "strategy",
                "key": st["key"],
                "title": st.get("title", ""),
                "status": st.get("status", ""),
                "priority": st.get("priority", ""),
                "quality_score": -1,
                "quality_display": rev.get("recommendation", "\u2014") if rev else "\u2014",
                "quality_class": "",
                "recommendation": rev.get("recommendation", "") if rev else "",
                "security_verdict": verdict.upper() if verdict else "",
                "attention": attention,
                "detail_url": f"/#strategies",
            })

        all_statuses = sorted({i["status"] for i in all_issues if i["status"]})
        all_priorities = sorted({i["priority"] for i in all_issues if i["priority"]})

        return render_template_string(
            DASHBOARD,
            # Bug tab data
            rows=rows,
            model_names=model_names,
            statuses=statuses,
            triages=triages,
            issue_types=issue_types,
            context_ratings=context_ratings,
            components=components,
            fix_recommendations=fix_recommendations,
            test_context_ratings=test_context_ratings,
            arch_docs_values=arch_docs_values,
            src_code_values=src_code_values,
            write_test_decisions=write_test_decisions,
            # RFE tab data
            rfe_issues=rfe_issues,
            rfe_statuses=rfe_statuses,
            rfe_priorities=rfe_priorities,
            rfe_recommendations=rfe_recommendations,
            # Strategy tab data
            strat_issues=strat_issues,
            strat_statuses=strat_statuses,
            strat_priorities=strat_priorities,
            strat_recommendations=strat_recommendations,
            # All-issues tab data
            all_issues=all_issues,
            all_statuses=all_statuses,
            all_priorities=all_priorities,
        )

    @app.route("/issue/<key>")
    def issue_detail(key):
        issue = load_single_issue(key)
        if issue is None:
            abort(404)

        # Model selection: use ?model= query param or first available
        available_models = discover_models(key)
        selected_model = request.args.get("model")
        if selected_model and selected_model in available_models:
            # Flatten selected model's data to top-level keys
            mdata = issue.get("models", {}).get(selected_model, {})
            if mdata:
                issue["completeness"] = mdata.get("completeness", issue.get("completeness"))
                issue["context_map"] = mdata.get("context_map", issue.get("context_map"))
                issue["fix_attempt"] = mdata.get("fix_attempt", issue.get("fix_attempt"))
                issue["test_plan"] = mdata.get("test_plan", issue.get("test_plan"))
                issue["write_test"] = mdata.get("write_test", issue.get("write_test"))
        elif available_models:
            selected_model = available_models[0]

        return render_template_string(
            DETAIL, issue=issue,
            available_models=available_models,
            selected_model=selected_model or "",
        )

    @app.route("/rfe/<key>")
    def rfe_detail(key):
        rfe = load_single_rfe(key)
        if rfe is None:
            abort(404)
        return render_template_string(RFE_DETAIL, rfe=rfe)

    @app.route("/activity")
    def activity():
        in_progress, history = load_activity()
        return render_template_string(ACTIVITY, in_progress=in_progress, history=history)

    @app.route("/stats")
    def stats():
        s = compute_all_stats()
        return render_template_string(STATS, s=s)

    @app.route("/summary")
    def summary_landing():
        model = request.args.get("model") or None
        s = compute_summary_stats(model=model)
        return render_template_string(SUMMARY_LANDING, s=s)

    @app.route("/summary/executive")
    def summary_executive():
        model = request.args.get("model") or None
        s = compute_summary_stats(model=model)
        return render_template_string(SUMMARY_EXECUTIVE, s=s)

    @app.route("/summary/developer")
    def summary_developer():
        model = request.args.get("model") or None
        s = compute_summary_stats(model=model)
        return render_template_string(SUMMARY_DEVELOPER, s=s)

    @app.route("/summary/statistician")
    def summary_statistician():
        model = request.args.get("model") or None
        s = compute_summary_stats(model=model)
        return render_template_string(SUMMARY_STATISTICIAN, s=s)

    @app.route("/readiness")
    def readiness():
        model = request.args.get("model") or None
        components = compute_component_readiness(model=model)
        return render_template_string(COMPONENT_READINESS, components=components)

    @app.route("/api/issues")
    def api_issues():
        issues = load_all_issues()
        return jsonify(issues)

    @app.route("/api/rfes")
    def api_rfes():
        return jsonify(load_rfe_issues())

    @app.route("/api/strategies")
    def api_strategies():
        return jsonify(load_strat_issues())

    @app.route("/api/stats")
    def api_stats():
        return jsonify(compute_all_stats())

    @app.route("/api/pipeline/status")
    def api_pipeline_status():
        return jsonify(load_pipeline_status())

    @app.route("/api/pipeline/queue")
    def api_pipeline_queue():
        return jsonify(_get_queue_snapshot())

    @app.route("/api/events/push", methods=["POST"])
    def api_events_push():
        payload = request.get_json(force=True)
        if not payload:
            return jsonify({"error": "empty payload"}), 400
        msg_type = payload.get("type", "event")
        if msg_type == "manifest":
            _handle_manifest(payload)
        else:
            _handle_event(payload)
        return jsonify({"ok": True})

    @app.route("/api/events")
    def api_events():
        def generate():
            q = queue.Queue(maxsize=1000)
            with _state_lock:
                _pipeline_state["sse_subscribers"].append(q)
                # Replay recent events so the client catches up
                for evt in _pipeline_state["events"]:
                    q.put_nowait(json.dumps(evt))
            try:
                while True:
                    try:
                        msg = q.get(timeout=30)
                        yield f"data: {msg}\n\n"
                    except queue.Empty:
                        # Send keepalive comment to prevent proxy/browser timeout
                        yield ": keepalive\n\n"
            except GeneratorExit:
                with _state_lock:
                    try:
                        _pipeline_state["sse_subscribers"].remove(q)
                    except ValueError:
                        pass

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.route("/api/workspace/reset", methods=["POST"])
    def api_reset_workspace():
        """Delete model workspace directories for selected issue*model pairs."""
        data = request.get_json()
        pairs = data.get("pairs", [])
        results = []
        for pair in pairs:
            key, mid = pair["key"], pair["model"]
            ws = model_workspace(key, mid)
            if ws.exists():
                # Ensure all dirs are writable so rmtree can descend and delete.
                # Skip broken symlinks and other non-existent entries.
                for dirpath, dirnames, filenames in os.walk(ws):
                    try:
                        os.chmod(dirpath, stat.S_IRWXU)
                    except (FileNotFoundError, OSError):
                        pass
                    for fn in filenames:
                        try:
                            os.chmod(os.path.join(dirpath, fn), stat.S_IWUSR | stat.S_IRUSR)
                        except (FileNotFoundError, OSError):
                            pass
                shutil.rmtree(ws)
                results.append({"key": key, "model": mid, "status": "deleted"})
            else:
                results.append({"key": key, "model": mid, "status": "not_found"})
        return jsonify({"results": results})

    return app
