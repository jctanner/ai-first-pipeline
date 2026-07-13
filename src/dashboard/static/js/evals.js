if (K8S_AVAILABLE) {

  // --- Select/custom toggle for Eval Harness, Dataset FQN, Context Repo ---

  function setupToggle(selectId, customId, toggleId, selectLabel, customLabel) {
    const select = document.getElementById(selectId);
    const custom = document.getElementById(customId);
    const toggle = document.getElementById(toggleId);
    let customMode = false;

    toggle.addEventListener('click', () => {
      customMode = !customMode;
      if (customMode) {
        select.style.visibility = 'hidden';
        custom.style.display = '';
        custom.focus();
        toggle.textContent = selectLabel;
      } else {
        custom.style.display = 'none';
        custom.value = '';
        select.style.visibility = '';
        toggle.textContent = customLabel;
      }
    });

    return {
      getValue: () => customMode ? custom.value.trim() : select.value,
      isCustom: () => customMode,
      setValue: (val) => {
        const option = Array.from(select.options).find(o => o.value === val);
        if (option) {
          if (customMode) toggle.click();
          select.value = val;
        } else if (val) {
          if (!customMode) toggle.click();
          custom.value = val;
        }
      },
      reset: () => {
        if (customMode) toggle.click();
        select.selectedIndex = 0;
      },
    };
  }

  const harnessToggle = setupToggle(
    'eval-harness', 'eval-harness-custom', 'toggle-harness',
    'or select preset...', 'or enter URL...'
  );
  const datasetToggle = setupToggle(
    'dataset-fqn', 'dataset-fqn-custom', 'toggle-dataset',
    'or select preset...', 'or enter FQN...'
  );
  const contextRepoToggle = setupToggle(
    'context-repo', 'context-repo-custom', 'toggle-context-repo',
    'or select preset...', 'or enter URL...'
  );

  // Submit eval form
  document.getElementById('eval-submit-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const datasetFqn = datasetToggle.getValue();
    const model = document.getElementById('eval-model').value;
    const contextRepo = contextRepoToggle.getValue();
    const contextRef = document.getElementById('context-ref').value.trim() || 'main';
    const contextMode = document.getElementById('context-mode').value;
    const evalHarness = harnessToggle.getValue();
    const baseline = document.getElementById('baseline').value.trim();
    const statusDiv = document.getElementById('eval-submit-status');

    if (!datasetFqn) {
      statusDiv.innerHTML = '<strong style="color: #e74c3c;">Error:</strong> Dataset FQN is required';
      return;
    }

    statusDiv.innerHTML = '<em style="color: #3498db;">Submitting eval...</em>';

    try {
      const body = {
        dataset_fqn: datasetFqn,
        model: model,
        context_repo: contextRepo,
        context_ref: contextRef,
        context_mode: contextMode,
        eval_harness: evalHarness,
      };
      if (baseline) body.baseline = baseline;
      if (document.getElementById('eval-strace').checked) body.strace = true;
      if (!document.getElementById('eval-mlflow').checked) body.mlflow = false;
      if (!document.getElementById('eval-otel').checked) body.otel = false;
      if (!document.getElementById('eval-api-dump').checked) body.api_dump = false;

      const response = await fetch('/api/evals/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const data = await response.json();

      if (response.ok) {
        statusDiv.innerHTML = '<strong style="color: #27ae60;">Eval submitted:</strong> ' + data.job_name;
        harnessToggle.reset();
        datasetToggle.reset();
        contextRepoToggle.reset();
        document.getElementById('context-ref').value = '';
        document.getElementById('baseline').value = '';
        await refreshEvals();
        openEvalModal(data.job_name);
      } else {
        statusDiv.innerHTML = '<strong style="color: #e74c3c;">Error:</strong> ' + (data.error || 'Unknown error');
      }
    } catch (err) {
      statusDiv.innerHTML = '<strong style="color: #e74c3c;">Error:</strong> ' + err.message;
    }
  });

  // Refresh evals table
  async function refreshEvals() {
    try {
      const response = await fetch('/api/evals');
      const evals = await response.json();

      evals.sort((a, b) => new Date(b.created) - new Date(a.created));

      document.getElementById('eval-count').textContent = '(' + evals.length + ')';

      const tbody = document.getElementById('evals-tbody');

      if (evals.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #95a5a6;">No eval runs found</td></tr>';
        return;
      }

      tbody.innerHTML = evals.map(ev => {
        const statusClass = 'status-' + ev.status;
        const duration = ev.duration ? ev.duration.toFixed(1) : '-';
        const created = new Date(ev.created).toLocaleString();
        const contextLabel = ev.context_mode + (ev.context_ref && ev.context_ref !== 'main' ? ' @' + ev.context_ref : '');

        return `
          <tr onclick="openEvalModal('${ev.name}')" class="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50">
            <td class="px-4 py-3 font-mono text-xs">${ev.name}</td>
            <td class="px-4 py-3">${ev.dataset_fqn}</td>
            <td class="px-4 py-3">${ev.model}</td>
            <td class="px-4 py-3">${contextLabel}</td>
            <td class="px-4 py-3 ${statusClass}">${ev.status}</td>
            <td class="px-4 py-3">${created}</td>
            <td class="px-4 py-3">${duration}</td>
          </tr>
        `;
      }).join('');
    } catch (err) {
      console.error('Failed to refresh evals:', err);
    }
  }

  // --- Eval Detail Modal ---

  let evalLogPollInterval = null;
  let currentEvalModal = null;

  const EVAL_STATUS_BADGE_CLASS = {
    pending: 'badge-val-skip',
    running: 'badge-fix-ai-fixable',
    completed: 'badge-val-pass',
    failed: 'badge-val-fail',
  };

  async function openEvalModal(jobName) {
    currentEvalModal = jobName;
    const modal = document.getElementById('eval-modal');
    const logEl = document.getElementById('eval-modal-log-content');

    document.getElementById('eval-modal-name').textContent = jobName;
    logEl.textContent = 'Loading logs...';

    try {
      const res = await fetch('/api/jobs/' + jobName);
      const job = await res.json();

      const badge = document.getElementById('eval-modal-status-badge');
      badge.textContent = job.status;
      badge.className = 'badge ' + (EVAL_STATUS_BADGE_CLASS[job.status] || 'badge-default');

      document.getElementById('eval-modal-dataset').textContent = job.dataset_fqn || '-';
      document.getElementById('eval-modal-model').textContent = job.model || '-';
      document.getElementById('eval-modal-context-repo').textContent = job.context_repo || '-';
      document.getElementById('eval-modal-context-ref').textContent = job.context_ref || 'main';
      document.getElementById('eval-modal-context-mode').textContent = job.context_mode || 'files';
      document.getElementById('eval-modal-harness').textContent = job.eval_harness || '-';
      document.getElementById('eval-modal-run-id').textContent = job.run_id || '-';
      document.getElementById('eval-modal-baseline').textContent = job.baseline || '-';
      document.getElementById('eval-modal-created').textContent = job.created ? new Date(job.created).toLocaleString() : '-';
      document.getElementById('eval-modal-started').textContent = job.started ? new Date(job.started).toLocaleString() : '-';

      if (job.completed && job.started) {
        const dur = ((new Date(job.completed) - new Date(job.started)) / 1000).toFixed(1);
        document.getElementById('eval-modal-duration').textContent = dur + 's';
      } else {
        document.getElementById('eval-modal-duration').textContent = '-';
      }

      document.getElementById('eval-modal-result').textContent =
        (job.succeeded ? job.succeeded + ' succeeded' : '') +
        (job.failed ? (job.succeeded ? ', ' : '') + job.failed + ' failed' : '') ||
        '-';

      document.getElementById('eval-modal-strace').innerHTML = job.strace
        ? '<span class="text-green-600 dark:text-green-400">Enabled</span>'
        : '<span class="text-gray-400">Off</span>';
      document.getElementById('eval-modal-mlflow').innerHTML = job.mlflow
        ? '<span class="text-green-600 dark:text-green-400">Enabled</span>'
        : '<span class="text-gray-400">Off</span>';
      document.getElementById('eval-modal-otel').innerHTML = job.otel !== false
        ? '<span class="text-green-600 dark:text-green-400">Enabled</span>'
        : '<span class="text-gray-400">Off</span>';
      document.getElementById('eval-modal-api-dump').innerHTML = job.api_dump !== false
        ? '<span class="text-green-600 dark:text-green-400">Enabled</span>'
        : '<span class="text-gray-400">Off</span>';

      window._evalRerunOpts = {
        dataset_fqn: job.dataset_fqn || '',
        model: job.model || 'opus',
        context_repo: job.context_repo || 'https://github.local/opendatahub-io/architecture-context',
        context_ref: job.context_ref || 'main',
        context_mode: job.context_mode || 'files',
        eval_harness: job.eval_harness || 'https://github.local/opendatahub-io/agent-eval-harness',
        baseline: job.baseline || '',
        strace: !!job.strace,
        mlflow: job.mlflow !== false,
        otel: job.otel !== false,
        api_dump: job.api_dump !== false,
      };

      const actionsEl = document.getElementById('eval-modal-actions');
      let btns = '';
      btns += '<button class="btn-rerun" onclick="evalModalRerun()">Re-run</button>';
      if (job.status === 'running' || job.status === 'pending') {
        btns += `<button class="btn-stop" onclick="evalModalStop('${jobName}')">Stop</button>`;
      }
      btns += `<button class="btn-delete" onclick="evalModalDelete('${jobName}')">Delete</button>`;
      actionsEl.innerHTML = btns;

    } catch (err) {
      document.getElementById('eval-modal-dataset').textContent = '-';
      document.getElementById('eval-modal-model').textContent = '-';
    }

    await fetchEvalModalLogs(jobName);
    modal.showModal();
    startEvalLogPolling(jobName);
  }

  async function fetchEvalModalLogs(jobName) {
    try {
      const res = await fetch('/api/jobs/' + jobName + '/logs');
      const logs = await res.text();
      const logEl = document.getElementById('eval-modal-log-content');
      const wasAtBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
      logEl.textContent = logs || '(no logs available)';
      if (wasAtBottom) logEl.scrollTop = logEl.scrollHeight;
    } catch (err) {
      document.getElementById('eval-modal-log-content').textContent = 'Error loading logs: ' + err.message;
    }
  }

  function startEvalLogPolling(jobName) {
    stopEvalLogPolling();
    evalLogPollInterval = setInterval(async () => {
      try {
        const res = await fetch('/api/jobs/' + jobName);
        const job = await res.json();

        const badge = document.getElementById('eval-modal-status-badge');
        badge.textContent = job.status;
        badge.className = 'badge ' + (EVAL_STATUS_BADGE_CLASS[job.status] || 'badge-default');

        if (job.completed && job.started) {
          const dur = ((new Date(job.completed) - new Date(job.started)) / 1000).toFixed(1);
          document.getElementById('eval-modal-duration').textContent = dur + 's';
        }

        if (job.status !== 'running' && job.status !== 'pending') {
          const actionsEl = document.getElementById('eval-modal-actions');
          let btns = '';
          btns += '<button class="btn-rerun" onclick="evalModalRerun()">Re-run</button>';
          btns += `<button class="btn-delete" onclick="evalModalDelete('${jobName}')">Delete</button>`;
          actionsEl.innerHTML = btns;

          document.getElementById('eval-modal-result').textContent =
            (job.succeeded ? job.succeeded + ' succeeded' : '') +
            (job.failed ? (job.succeeded ? ', ' : '') + job.failed + ' failed' : '') ||
            '-';

          stopEvalLogPolling();
        }
      } catch (e) {}

      await fetchEvalModalLogs(jobName);
    }, 2000);
  }

  function stopEvalLogPolling() {
    if (evalLogPollInterval) {
      clearInterval(evalLogPollInterval);
      evalLogPollInterval = null;
    }
  }

  function closeEvalModal() {
    stopEvalLogPolling();
    currentEvalModal = null;
    document.getElementById('eval-modal').close();
  }

  document.getElementById('eval-modal').addEventListener('click', function(e) {
    if (e.target === this) closeEvalModal();
  });

  async function evalModalStop(jobName) {
    if (!confirm('Stop eval "' + jobName + '"?')) return;
    try {
      await fetch('/api/jobs/' + jobName + '/stop', { method: 'POST' });
      refreshEvals();
    } catch (err) {
      alert('Error stopping eval: ' + err.message);
    }
  }

  async function evalModalDelete(jobName) {
    if (!confirm('Delete eval "' + jobName + '"?')) return;
    try {
      const res = await fetch('/api/jobs/' + jobName, { method: 'DELETE' });
      if (res.ok) {
        closeEvalModal();
        refreshEvals();
      } else {
        const data = await res.json();
        alert('Error deleting eval: ' + (data.error || 'Unknown error'));
      }
    } catch (err) {
      alert('Error deleting eval: ' + err.message);
    }
  }

  async function evalModalRerun() {
    const opts = window._evalRerunOpts;
    if (!opts) return;

    // Pre-fill the form with the job's values
    harnessToggle.setValue(opts.eval_harness);
    datasetToggle.setValue(opts.dataset_fqn);
    contextRepoToggle.setValue(opts.context_repo);
    document.getElementById('context-ref').value = opts.context_ref || '';
    document.getElementById('context-mode').value = opts.context_mode || 'files';
    document.getElementById('eval-model').value = opts.model || 'opus';
    document.getElementById('baseline').value = opts.baseline || '';
    document.getElementById('eval-strace').checked = !!opts.strace;
    document.getElementById('eval-mlflow').checked = opts.mlflow !== false;
    document.getElementById('eval-otel').checked = opts.otel !== false;
    document.getElementById('eval-api-dump').checked = opts.api_dump !== false;

    closeEvalModal();
    document.getElementById('eval-submit-form').scrollIntoView({ behavior: 'smooth' });
  }

  // Make functions global
  window.openEvalModal = openEvalModal;
  window.closeEvalModal = closeEvalModal;
  window.evalModalStop = evalModalStop;
  window.evalModalDelete = evalModalDelete;
  window.evalModalRerun = evalModalRerun;

  // Auto-refresh every 3 seconds
  refreshEvals();
  setInterval(refreshEvals, 3000);
}
