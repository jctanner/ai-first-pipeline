function toggleVolSelectAll(master) {
  document.querySelectorAll('.vol-select').forEach(cb => cb.checked = master.checked);
}

function confirmClearVolumes() {
  const checked = document.querySelectorAll('.vol-select:checked');
  if (checked.length === 0) { alert('No volumes selected.'); return; }
  const names = Array.from(checked).map(cb => cb.value);
  document.getElementById('clear-volumes-list').innerHTML =
    names.map(n => '<code>' + n + '</code>').join('<br>');
  document.getElementById('clear-volumes-modal').showModal();
}

function executeClearVolumes() {
  const checked = document.querySelectorAll('.vol-select:checked');
  const volumes = Array.from(checked).map(cb => cb.value);
  fetch('/api/volumes/clear', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({volumes})
  })
  .then(r => r.json())
  .then(data => {
    document.getElementById('clear-volumes-modal').close();
    const cleared = Object.entries(data.results)
      .map(([k,v]) => k + ': ' + v.status + ' (' + v.deleted + ' items)')
      .join('\\n');
    let msg = 'Clear complete:\\n' + cleared;
    if (data.errors.length) msg += '\\n\\nErrors:\\n' + data.errors.join('\\n');
    alert(msg);
  })
  .catch(err => alert('Clear failed: ' + err));
}

function loadJobCount() {
  fetch('/api/jobs')
    .then(r => r.json())
    .then(data => {
      const jobs = data.jobs || [];
      document.getElementById('k8s-job-count').textContent =
        jobs.length + ' job(s) in cluster';
    })
    .catch(() => {
      document.getElementById('k8s-job-count').textContent = 'Unable to query jobs';
    });
}

function confirmDeleteJobs() {
  document.getElementById('delete-jobs-modal').showModal();
}

function executeDeleteJobs() {
  const btn = document.querySelector('#delete-jobs-modal button:last-child');
  btn.textContent = 'Deleting...';
  btn.disabled = true;
  fetch('/api/jobs/all', { method: 'DELETE' })
    .then(r => r.json())
    .then(data => {
      document.getElementById('delete-jobs-modal').close();
      btn.textContent = 'Confirm & Delete';
      btn.disabled = false;
      let msg = data.deleted + ' job(s) deleted.';
      if (data.errors && data.errors.length)
        msg += '\n\nErrors:\n' + data.errors.join('\n');
      alert(msg);
      loadJobCount();
    })
    .catch(err => {
      btn.textContent = 'Confirm & Delete';
      btn.disabled = false;
      alert('Delete failed: ' + err);
    });
}

document.addEventListener('DOMContentLoaded', loadJobCount);

function confirmClearObservatory() {
  document.getElementById('clear-observatory-modal').showModal();
}

function executeClearObservatory() {
  const btn = document.querySelector('#clear-observatory-modal button:last-child');
  btn.textContent = 'Clearing...';
  btn.disabled = true;
  fetch('/api/observatory/clear', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({})
  })
    .then(r => r.json())
    .then(data => {
      document.getElementById('clear-observatory-modal').close();
      btn.textContent = 'Confirm & Clear';
      btn.disabled = false;
      if (data.error) {
        alert('Clear failed: ' + data.error);
      } else {
        let msg = 'Observatory data cleared.';
        if (data.deleted !== undefined) msg = data.deleted + ' record(s) deleted.';
        alert(msg);
      }
    })
    .catch(err => {
      btn.textContent = 'Confirm & Clear';
      btn.disabled = false;
      alert('Clear failed: ' + err);
    });
}

function confirmClearMlflow() {
  document.getElementById('clear-mlflow-modal').showModal();
}

function executeClearMlflow() {
  const btn = document.querySelector('#clear-mlflow-modal button:last-child');
  btn.textContent = 'Clearing...';
  btn.disabled = true;
  fetch('/api/mlflow/clear', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({})
  })
  .then(r => r.json())
  .then(data => {
    document.getElementById('clear-mlflow-modal').close();
    btn.textContent = 'Confirm & Clear';
    btn.disabled = false;
    let msg = 'MLflow data cleared:\n' +
      data.traces_deleted + ' trace(s) deleted\n' +
      data.runs_deleted + ' run(s) deleted\n' +
      data.experiments_deleted + ' experiment(s) deleted';
    if (data.errors && data.errors.length) msg += '\n\nErrors:\n' + data.errors.join('\n');
    alert(msg);
  })
  .catch(err => {
    btn.textContent = 'Confirm & Clear';
    btn.disabled = false;
    alert('Clear failed: ' + err);
  });
}
