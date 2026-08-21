if (K8S_AVAILABLE) {
  // Skill / FQN / Prompt mode toggle
  let inputMode = 'skill'; // 'skill' | 'fqn' | 'prompt'
  const toggleBtn = document.getElementById('toggle-fqn');
  const togglePromptBtn = document.getElementById('toggle-prompt');
  const skillSelect = document.getElementById('skill');
  const fqnInput = document.getElementById('skill-fqn');
  const promptInput = document.getElementById('skill-prompt');
  const pluginFields = document.getElementById('plugin-fields');

  const togglePluginsBtn = document.getElementById('toggle-plugins');
  let pluginsVisible = false;

  function setInputMode(mode) {
    inputMode = mode;
    skillSelect.style.visibility = mode === 'skill' ? '' : 'hidden';
    if (mode !== 'skill') skillSelect.value = '';
    fqnInput.style.display = mode === 'fqn' ? '' : 'none';
    if (mode !== 'fqn') fqnInput.value = '';
    promptInput.style.display = mode === 'prompt' ? '' : 'none';
    if (mode !== 'prompt') promptInput.value = '';
    toggleBtn.style.display = mode === 'fqn' ? 'none' : '';
    togglePromptBtn.style.display = mode === 'prompt' ? 'none' : '';
    if (mode === 'skill') {
      toggleBtn.textContent = 'or enter FQN...';
      togglePromptBtn.textContent = 'or enter prompt...';
    } else if (mode === 'fqn') {
      togglePromptBtn.textContent = 'or enter prompt...';
    } else if (mode === 'prompt') {
      toggleBtn.textContent = 'or enter FQN...';
    }
  }

  function setPluginsVisible(show) {
    pluginsVisible = show;
    pluginFields.style.display = show ? '' : 'none';
    togglePluginsBtn.textContent = show ? '- registries/plugins' : '+ registries/plugins';
  }

  togglePluginsBtn.addEventListener('click', () => {
    setPluginsVisible(!pluginsVisible);
  });

  // Harness-dependent model options
  const HARNESS_MODELS = {
    'claude-code': [
      { value: 'haiku', label: 'haiku' },
      { value: 'sonnet', label: 'sonnet' },
      { value: 'opus', label: 'opus', selected: true },
    ],
    'opencode': [
      { value: 'google-vertex-anthropic/claude-haiku-4-5@20251001', label: 'claude-haiku-4-5' },
      { value: 'google-vertex-anthropic/claude-sonnet-4-6@default', label: 'claude-sonnet-4-6' },
      { value: 'google-vertex-anthropic/claude-opus-4-6@default', label: 'claude-opus-4-6', selected: true },
    ],
  };

  // Harness-dependent runner options
  const HARNESS_RUNNERS = {
    'claude-code': [
      { value: 'cli', label: 'CLI', selected: true },
      { value: 'sdk', label: 'SDK' },
      { value: 'agentic-ci', label: 'agentic-ci' },
    ],
    'opencode': [
      { value: 'cli', label: 'CLI' },
      { value: 'sdk', label: 'SDK', selected: true },
      { value: 'agentic-ci', label: 'agentic-ci' },
    ],
  };

  document.getElementById('harness').addEventListener('change', function() {
    const modelSelect = document.getElementById('model');
    const models = HARNESS_MODELS[this.value] || HARNESS_MODELS['claude-code'];
    modelSelect.innerHTML = models.map(m =>
      `<option value="${m.value}"${m.selected ? ' selected' : ''}>${m.label}</option>`
    ).join('');

    const runnerSelect = document.getElementById('runner');
    const runners = HARNESS_RUNNERS[this.value] || HARNESS_RUNNERS['claude-code'];
    runnerSelect.innerHTML = runners.map(r =>
      `<option value="${r.value}"${r.selected ? ' selected' : ''}>${r.label}</option>`
    ).join('');
  });

  toggleBtn.addEventListener('click', () => {
    if (inputMode === 'skill') {
      setInputMode('fqn');
      fqnInput.focus();
    } else {
      setInputMode('skill');
    }
  });

  togglePromptBtn.addEventListener('click', () => {
    if (inputMode !== 'prompt') {
      setInputMode('prompt');
      promptInput.focus();
    } else {
      setInputMode('skill');
    }
  });

  // Submit job form
  document.getElementById('submit-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const skill = document.getElementById('skill').value;
    const fqn = document.getElementById('skill-fqn').value.trim();
    const prompt = document.getElementById('skill-prompt').value.trim();
    const issueRaw = document.getElementById('issue').value.trim();
    const issue = issueRaw ? issueRaw.toUpperCase() : '';
    const model = document.getElementById('model').value;
    const runner = document.getElementById('runner').value;
    const harness = document.getElementById('harness').value;
    const execution = document.getElementById('execution').value;
    const statusDiv = document.getElementById('submit-status');

    if (!skill && !fqn && !prompt) {
      statusDiv.innerHTML = '<strong style="color: #e74c3c;">✗ Error:</strong> Select a skill, enter an FQN, or enter a prompt';
      return;
    }

    statusDiv.innerHTML = '<em style="color: #3498db;">Submitting job...</em>';

    try {
      const args = { model, runner, harness };
      if (issue) args.issue = issue;
      const extraKwargs = document.getElementById('extra-kwargs').value.trim();
      if (extraKwargs) args.extra_kwargs = extraKwargs;
      const extraEnvStr = document.getElementById('extra-env').value.trim();
      if (extraEnvStr) {
        args.extra_env = {};
        extraEnvStr.split(/\s+/).forEach(kv => {
          const eq = kv.indexOf('=');
          if (eq > 0) args.extra_env[kv.slice(0, eq)] = kv.slice(eq + 1);
        });
      }
      if (document.getElementById('enable-force').checked) args.force = true;
      if (document.getElementById('enable-strace').checked) args.strace = true;
      if (!document.getElementById('enable-mlflow').checked) args.mlflow = false;
      if (!document.getElementById('enable-otel').checked) args.otel = false;
      if (!document.getElementById('enable-api-dump').checked) args.api_dump = false;

      const registriesVal = document.getElementById('registries').value.trim();
      if (registriesVal) {
        args.registries = registriesVal.split(/\n+/).map(s => s.trim()).filter(Boolean);
      }
      const pluginsVal = document.getElementById('plugins').value.trim();
      if (pluginsVal) {
        args.plugins = pluginsVal.split(/\n+/).map(s => s.trim()).filter(Boolean);
      }
      if (prompt) args.prompt = prompt;

      let body;
      if (prompt) {
        body = { args, execution };
      } else if (fqn) {
        body = { fqn, args, execution };
      } else {
        body = { command: skill, args, execution };
      }
      const response = await fetch('/api/jobs/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      const data = await response.json();

      if (response.ok) {
        statusDiv.innerHTML = '<strong style="color: #27ae60;">✓ Job submitted:</strong> ' + data.job_name;
        document.getElementById('submit-form').reset();
        setInputMode('skill');
        setPluginsVisible(false);
        document.getElementById('harness').value = 'claude-code';
        document.getElementById('harness').dispatchEvent(new Event('change'));
        document.getElementById('execution').value = 'kubernetes';
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
        tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: #95a5a6;">No jobs found</td></tr>';
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
            <td class="px-4 py-3">${job.fqn || SKILL_MAP[job.phase] || job.phase}</td>
            <td class="px-4 py-3">${job.issue.toUpperCase()}</td>
            <td class="px-4 py-3">${job.model}</td>
            <td class="px-4 py-3">${runner}</td>
            <td class="px-4 py-3">${job.harness || 'claude-code'}</td>
            <td class="px-4 py-3">${job.execution || 'kubernetes'}</td>
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

      document.getElementById('modal-phase').textContent = job.fqn || SKILL_MAP[job.phase] || job.phase || '-';
      document.getElementById('modal-issue').textContent = (job.issue || '-').toUpperCase();
      document.getElementById('modal-model').textContent = job.model || '-';
      document.getElementById('modal-runner').textContent = job.runner || 'cli';
      document.getElementById('modal-harness').textContent = job.harness || 'claude-code';
      document.getElementById('modal-execution').textContent = job.execution || 'kubernetes';
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

      document.getElementById('modal-force').innerHTML = job.force
        ? '<span class="text-green-600 dark:text-green-400">Enabled</span>'
        : '<span class="text-gray-400">Off</span>';
      document.getElementById('modal-strace').innerHTML = job.strace
        ? '<span class="text-green-600 dark:text-green-400">Enabled</span>'
        : '<span class="text-gray-400">Off</span>';
      document.getElementById('modal-mlflow').innerHTML = job.mlflow
        ? '<span class="text-green-600 dark:text-green-400">Enabled</span>'
        : '<span class="text-gray-400">Off</span>';
      document.getElementById('modal-otel').innerHTML = job.otel !== false
        ? '<span class="text-green-600 dark:text-green-400">Enabled</span>'
        : '<span class="text-gray-400">Off</span>';
      document.getElementById('modal-api-dump').innerHTML = job.api_dump !== false
        ? '<span class="text-green-600 dark:text-green-400">Enabled</span>'
        : '<span class="text-gray-400">Off</span>';

      const ekRow = document.getElementById('modal-extra-kwargs-row');
      if (job.extra_kwargs) {
        document.getElementById('modal-extra-kwargs').textContent = job.extra_kwargs;
        ekRow.style.display = '';
      } else {
        ekRow.style.display = 'none';
      }

      const eeRow = document.getElementById('modal-extra-env-row');
      if (eeRow) {
        const envObj = job.extra_env || {};
        const envStr = Object.entries(envObj).map(([k,v]) => `${k}=${v}`).join(' ');
        if (envStr) {
          document.getElementById('modal-extra-env').textContent = envStr;
          eeRow.style.display = '';
        } else {
          eeRow.style.display = 'none';
        }
      }

      const promptRow = document.getElementById('modal-prompt-row');
      if (job.prompt) {
        document.getElementById('modal-prompt').textContent = job.prompt;
        promptRow.style.display = '';
      } else {
        promptRow.style.display = 'none';
      }

      const regsRow = document.getElementById('modal-registries-row');
      const regs = job.registries ? (typeof job.registries === 'string' ? JSON.parse(job.registries) : job.registries) : [];
      if (regs.length) {
        document.getElementById('modal-registries').textContent = regs.join(', ');
        regsRow.style.display = '';
      } else {
        regsRow.style.display = 'none';
      }

      const plugsRow = document.getElementById('modal-plugins-row');
      const plugs = job.plugins ? (typeof job.plugins === 'string' ? JSON.parse(job.plugins) : job.plugins) : [];
      if (plugs.length) {
        document.getElementById('modal-plugins').textContent = plugs.join(', ');
        plugsRow.style.display = '';
      } else {
        plugsRow.style.display = 'none';
      }

      // Store job opts for re-run
      window._rerunOpts = {
        phase: job.phase,
        fqn: job.fqn || '',
        prompt: job.prompt || '',
        registries: regs,
        plugins: plugs,
        issue: job.issue,
        model: job.model,
        runner: job.runner || 'cli',
        harness: job.harness || 'claude-code',
        execution: job.execution || 'kubernetes',
        extra_kwargs: job.extra_kwargs || '',
        extra_env: job.extra_env || {},
        force: !!job.force,
        strace: !!job.strace,
        mlflow: job.mlflow !== false,
        otel: job.otel !== false,
        api_dump: job.api_dump !== false,
      };

      // Action buttons
      const actionsEl = document.getElementById('modal-actions');
      let btns = '';
      btns += `<button class="btn-rerun" onclick="modalRerun(window._rerunOpts)">Re-run</button>`;
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
          btns += `<button class="btn-rerun" onclick="modalRerun(window._rerunOpts)">Re-run</button>`;
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

  async function modalRerun(opts) {
    opts = opts || {};
    const args = { model: opts.model, runner: opts.runner, harness: opts.harness || 'claude-code' };
    if (opts.issue && opts.issue !== 'all') args.issue = opts.issue.toUpperCase();
    if (opts.extra_kwargs) args.extra_kwargs = opts.extra_kwargs;
    if (opts.extra_env && Object.keys(opts.extra_env).length) args.extra_env = opts.extra_env;
    if (opts.force) args.force = true;
    if (opts.strace) args.strace = true;
    if (opts.mlflow === false) args.mlflow = false;
    if (opts.otel === false) args.otel = false;
    if (opts.api_dump === false) args.api_dump = false;
    if (opts.registries && opts.registries.length) args.registries = opts.registries;
    if (opts.plugins && opts.plugins.length) args.plugins = opts.plugins;
    if (opts.prompt) args.prompt = opts.prompt;

    let body;
    if (opts.prompt) {
      body = { args, execution: opts.execution || 'kubernetes' };
    } else if (opts.fqn) {
      body = { fqn: opts.fqn, args, execution: opts.execution || 'kubernetes' };
    } else {
      body = { command: opts.phase, args, execution: opts.execution || 'kubernetes' };
    }

    try {
      const res = await fetch('/api/jobs/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
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
