if (K8S_AVAILABLE) {
  // Submit job form
  document.getElementById('submit-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const skill = document.getElementById('skill').value;
    const issueRaw = document.getElementById('issue').value.trim();
    const issue = issueRaw ? issueRaw.toUpperCase() : '';
    const model = document.getElementById('model').value;
    const runner = document.getElementById('runner').value;
    const statusDiv = document.getElementById('submit-status');

    statusDiv.innerHTML = '<em style="color: #3498db;">Submitting job...</em>';

    try {
      const args = { model, runner };
      if (issue) args.issue = issue;
      const extraKwargs = document.getElementById('extra-kwargs').value.trim();
      if (extraKwargs) args.extra_kwargs = extraKwargs;
      if (document.getElementById('enable-strace').checked) args.strace = true;
      if (!document.getElementById('enable-mlflow').checked) args.mlflow = false;
      const response = await fetch('/api/jobs/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: skill, args })
      });

      const data = await response.json();

      if (response.ok) {
        statusDiv.innerHTML = '<strong style="color: #27ae60;">✓ Job submitted:</strong> ' + data.job_name;
        document.getElementById('submit-form').reset();
        document.getElementById('model').value = 'opus';
        document.getElementById('runner').value = 'cli';
        await refreshJobs();
        openJobModal(data.job_name);
      } else {
        statusDiv.innerHTML = '<strong style="color: #e74c3c;">✗ Error:</strong> ' + (data.error || 'Unknown error');
      }
    } catch (err) {
      statusDiv.innerHTML = '<strong style="color: #e74c3c;">✗ Error:</strong> ' + err.message;
    }
  });

  // Refresh jobs table
  async function refreshJobs() {
    try {
      const response = await fetch('/api/jobs');
      const jobs = await response.json();

      jobs.sort((a, b) => new Date(b.created) - new Date(a.created));

      document.getElementById('job-count').textContent = '(' + jobs.length + ')';

      const tbody = document.getElementById('jobs-tbody');

      if (jobs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: #95a5a6;">No jobs found</td></tr>';
        return;
      }

      tbody.innerHTML = jobs.map(job => {
        const statusClass = 'status-' + job.status;
        const duration = job.duration ? job.duration.toFixed(1) : '-';
        const created = new Date(job.created).toLocaleString();
        const runner = job.runner || 'cli';

        return `
          <tr onclick="openJobModal('${job.name}')" class="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50">
            <td class="px-4 py-3 font-mono text-xs">${job.name}</td>
            <td class="px-4 py-3">${SKILL_MAP[job.phase] || job.phase}</td>
            <td class="px-4 py-3">${job.issue.toUpperCase()}</td>
            <td class="px-4 py-3">${job.model}</td>
            <td class="px-4 py-3">${runner}</td>
            <td class="px-4 py-3 ${statusClass}">${job.status}</td>
            <td class="px-4 py-3">${created}</td>
            <td class="px-4 py-3">${duration}</td>
          </tr>
        `;
      }).join('');
    } catch (err) {
      console.error('Failed to refresh jobs:', err);
    }
  }

  // --- Job Detail Modal ---

  let logPollInterval = null;
  let currentModalJob = null;

  const STATUS_BADGE_CLASS = {
    pending: 'badge-val-skip',
    running: 'badge-fix-ai-fixable',
    completed: 'badge-val-pass',
    failed: 'badge-val-fail'
  };

  async function openJobModal(jobName) {
    currentModalJob = jobName;
    const modal = document.getElementById('job-modal');
    const logEl = document.getElementById('modal-log-content');

    document.getElementById('modal-job-name').textContent = jobName;
    logEl.textContent = 'Loading logs...';

    // Fetch job details
    try {
      const res = await fetch('/api/jobs/' + jobName);
      const job = await res.json();

      const badge = document.getElementById('modal-status-badge');
      badge.textContent = job.status;
      badge.className = 'badge ' + (STATUS_BADGE_CLASS[job.status] || 'badge-default');

      document.getElementById('modal-phase').textContent = SKILL_MAP[job.phase] || job.phase || '-';
      document.getElementById('modal-issue').textContent = (job.issue || '-').toUpperCase();
      document.getElementById('modal-model').textContent = job.model || '-';
      document.getElementById('modal-runner').textContent = job.runner || 'cli';
      document.getElementById('modal-created').textContent = job.created ? new Date(job.created).toLocaleString() : '-';
      document.getElementById('modal-started').textContent = job.started ? new Date(job.started).toLocaleString() : '-';

      if (job.completed && job.started) {
        const dur = ((new Date(job.completed) - new Date(job.started)) / 1000).toFixed(1);
        document.getElementById('modal-duration').textContent = dur + 's';
      } else {
        document.getElementById('modal-duration').textContent = '-';
      }

      document.getElementById('modal-result').textContent =
        (job.succeeded ? job.succeeded + ' succeeded' : '') +
        (job.failed ? (job.succeeded ? ', ' : '') + job.failed + ' failed' : '') ||
        '-';

      document.getElementById('modal-strace').innerHTML = job.strace
        ? '<span class="text-green-600 dark:text-green-400">Enabled</span>'
        : '<span class="text-gray-400">Off</span>';
      document.getElementById('modal-mlflow').innerHTML = job.mlflow
        ? '<span class="text-green-600 dark:text-green-400">Enabled</span>'
        : '<span class="text-gray-400">Off</span>';

      // Action buttons
      const actionsEl = document.getElementById('modal-actions');
      let btns = '';
      btns += `<button class="btn-rerun" onclick="modalRerun('${job.phase}','${job.issue}','${job.model}','${job.runner || 'cli'}')">Re-run</button>`;
      if (job.status === 'running' || job.status === 'pending') {
        btns += `<button class="btn-stop" onclick="modalStop('${jobName}')">Stop</button>`;
      }
      btns += `<button class="btn-delete" onclick="modalDelete('${jobName}')">Delete</button>`;
      actionsEl.innerHTML = btns;

    } catch (err) {
      document.getElementById('modal-phase').textContent = '-';
      document.getElementById('modal-issue').textContent = '-';
    }

    // Fetch logs
    await fetchModalLogs(jobName);

    modal.showModal();

    // Poll logs every 2s for running/pending jobs
    startLogPolling(jobName);
  }

  async function fetchModalLogs(jobName) {
    try {
      const res = await fetch('/api/jobs/' + jobName + '/logs');
      const logs = await res.text();
      const logEl = document.getElementById('modal-log-content');
      const wasAtBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
      logEl.textContent = logs || '(no logs available)';
      if (wasAtBottom) logEl.scrollTop = logEl.scrollHeight;
    } catch (err) {
      document.getElementById('modal-log-content').textContent = 'Error loading logs: ' + err.message;
    }
  }

  function startLogPolling(jobName) {
    stopLogPolling();
    logPollInterval = setInterval(async () => {
      // Check if job is still running
      try {
        const res = await fetch('/api/jobs/' + jobName);
        const job = await res.json();

        // Update status badge
        const badge = document.getElementById('modal-status-badge');
        badge.textContent = job.status;
        badge.className = 'badge ' + (STATUS_BADGE_CLASS[job.status] || 'badge-default');

        if (job.completed && job.started) {
          const dur = ((new Date(job.completed) - new Date(job.started)) / 1000).toFixed(1);
          document.getElementById('modal-duration').textContent = dur + 's';
        }

        if (job.status !== 'running' && job.status !== 'pending') {
          // Update actions (remove Stop button)
          const actionsEl = document.getElementById('modal-actions');
          let btns = '';
          btns += `<button class="btn-rerun" onclick="modalRerun('${job.phase}','${job.issue}','${job.model}','${job.runner || 'cli'}')">Re-run</button>`;
          btns += `<button class="btn-delete" onclick="modalDelete('${jobName}')">Delete</button>`;
          actionsEl.innerHTML = btns;

          document.getElementById('modal-result').textContent =
            (job.succeeded ? job.succeeded + ' succeeded' : '') +
            (job.failed ? (job.succeeded ? ', ' : '') + job.failed + ' failed' : '') ||
            '-';

          stopLogPolling();
        }
      } catch (e) {}

      await fetchModalLogs(jobName);
    }, 2000);
  }

  function stopLogPolling() {
    if (logPollInterval) {
      clearInterval(logPollInterval);
      logPollInterval = null;
    }
  }

  function closeJobModal() {
    stopLogPolling();
    currentModalJob = null;
    document.getElementById('job-modal').close();
  }

  // Close on backdrop click
  document.getElementById('job-modal').addEventListener('click', function(e) {
    if (e.target === this) closeJobModal();
  });

  // Modal action handlers
  async function modalStop(jobName) {
    if (!confirm('Stop job "' + jobName + '"?')) return;
    try {
      await fetch('/api/jobs/' + jobName + '/stop', { method: 'POST' });
      refreshJobs();
    } catch (err) {
      alert('Error stopping job: ' + err.message);
    }
  }

  async function modalDelete(jobName) {
    if (!confirm('Delete job "' + jobName + '"?')) return;
    try {
      const res = await fetch('/api/jobs/' + jobName, { method: 'DELETE' });
      if (res.ok) {
        closeJobModal();
        refreshJobs();
      } else {
        const data = await res.json();
        alert('Error deleting job: ' + (data.error || 'Unknown error'));
      }
    } catch (err) {
      alert('Error deleting job: ' + err.message);
    }
  }

  async function modalRerun(phase, issue, model, runner) {
    const args = { model, runner };
    if (issue && issue !== 'all') args.issue = issue.toUpperCase();

    try {
      const res = await fetch('/api/jobs/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: phase, args })
      });

      const data = await res.json();
      if (res.ok) {
        closeJobModal();
        refreshJobs();
      } else {
        alert('Error re-running job: ' + (data.error || 'Unknown error'));
      }
    } catch (err) {
      alert('Error re-running job: ' + err.message);
    }
  }

  // Make functions global
  window.openJobModal = openJobModal;
  window.closeJobModal = closeJobModal;
  window.modalStop = modalStop;
  window.modalDelete = modalDelete;
  window.modalRerun = modalRerun;

  // Auto-refresh every 3 seconds
  refreshJobs();
  setInterval(refreshJobs, 3000);
}
