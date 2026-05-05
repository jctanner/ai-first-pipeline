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
        refreshJobs();
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

      document.getElementById('job-count').textContent = '(' + jobs.length + ')';

      const tbody = document.getElementById('jobs-tbody');

      if (jobs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: #95a5a6;">No jobs found</td></tr>';
        return;
      }

      tbody.innerHTML = jobs.map(job => {
        const statusClass = 'status-' + job.status;
        const duration = job.duration ? job.duration.toFixed(1) : '-';
        const created = new Date(job.created).toLocaleString();
        const runner = job.runner || 'cli';

        return `
          <tr>
            <td style="font-family: monospace; font-size: 0.85em;">${job.name}</td>
            <td>${SKILL_MAP[job.phase] || job.phase}</td>
            <td>${job.issue.toUpperCase()}</td>
            <td>${job.model}</td>
            <td>${runner}</td>
            <td class="${statusClass}">${job.status}</td>
            <td>${created}</td>
            <td>${duration}</td>
            <td>
              <button class="btn-logs" onclick="viewLogs('${job.name}')">Logs</button>
              <button class="btn-rerun" onclick="rerunJob('${job.phase}', '${job.issue}', '${job.model}', '${job.runner || 'cli'}')">Re-run</button>
              ${(job.status === 'running' || job.status === 'pending') ? `<button class="btn-stop" onclick="stopJob('${job.name}')">Stop</button>` : ''}
              <button class="btn-delete" onclick="deleteJob('${job.name}')">Delete</button>
            </td>
          </tr>
        `;
      }).join('');
    } catch (err) {
      console.error('Failed to refresh jobs:', err);
    }
  }

  // View job logs
  async function viewLogs(jobName) {
    const logViewer = document.getElementById('log-viewer');
    const logContent = document.getElementById('log-content');
    const logJobName = document.getElementById('log-job-name');

    logJobName.textContent = 'Logs: ' + jobName;
    logContent.textContent = 'Loading logs...';
    logViewer.classList.add('active');

    try {
      const response = await fetch('/api/jobs/' + jobName + '/logs');
      const logs = await response.text();
      logContent.textContent = logs || '(no logs available)';
    } catch (err) {
      logContent.textContent = 'Error loading logs: ' + err.message;
    }
  }

  // Close log viewer
  function closeLogs() {
    document.getElementById('log-viewer').classList.remove('active');
  }

  // Stop job
  async function stopJob(jobName) {
    if (!confirm('Stop job "' + jobName + '"?')) return;

    try {
      const response = await fetch('/api/jobs/' + jobName + '/stop', {
        method: 'POST'
      });

      if (response.ok) {
        refreshJobs();
      } else {
        const data = await response.json();
        alert('Error stopping job: ' + (data.error || 'Unknown error'));
      }
    } catch (err) {
      alert('Error stopping job: ' + err.message);
    }
  }

  // Delete job
  async function deleteJob(jobName) {
    if (!confirm('Delete job "' + jobName + '"?')) return;

    try {
      const response = await fetch('/api/jobs/' + jobName, {
        method: 'DELETE'
      });

      if (response.ok) {
        refreshJobs();
      } else {
        const data = await response.json();
        alert('Error deleting job: ' + (data.error || 'Unknown error'));
      }
    } catch (err) {
      alert('Error deleting job: ' + err.message);
    }
  }

  // Re-run job with same parameters
  async function rerunJob(phase, issue, model, runner) {
    const args = { model, runner };
    if (issue && issue !== 'all') args.issue = issue.toUpperCase();

    try {
      const response = await fetch('/api/jobs/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: phase, args })
      });

      const data = await response.json();
      if (response.ok) {
        refreshJobs();
      } else {
        alert('Error re-running job: ' + (data.error || 'Unknown error'));
      }
    } catch (err) {
      alert('Error re-running job: ' + err.message);
    }
  }

  // Make functions global
  window.viewLogs = viewLogs;
  window.closeLogs = closeLogs;
  window.stopJob = stopJob;
  window.deleteJob = deleteJob;
  window.rerunJob = rerunJob;

  // Auto-refresh every 3 seconds
  refreshJobs();
  setInterval(refreshJobs, 3000);
}
