let currentPath = '';
let currentEntries = [];

function formatSize(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function formatDate(isoString) {
  if (!isoString) return 'N/A';
  const d = new Date(isoString);
  return d.toLocaleString();
}

async function navigateTo(path) {
  // Normalize path: remove trailing slash (except for root)
  currentPath = path === '/' ? path : path.replace(/\/+$/, '');

  try {
    const response = await fetch('/api/files/list?path=' + encodeURIComponent(path));
    const data = await response.json();

    if (!response.ok) {
      showError('Error loading directory: ' + (data.error || 'Unknown error'));
      return;
    }

    currentEntries = data.entries || [];
    renderBreadcrumb(path);
    renderDirectoryList(currentEntries);

    // Clear file viewer
    document.getElementById('file-display').innerHTML = '<div class="empty-state">Select a file to view its contents</div>';
  } catch (err) {
    showError('Error loading directory: ' + err.message);
  }
}

function renderBreadcrumb(path) {
  const parts = path.split('/').filter(p => p);
  const breadcrumb = document.getElementById('breadcrumb');

  let html = `<a href="#" onclick="navigateTo('/'); return false;">/</a>`;
  let accumulated = '';

  for (let i = 0; i < parts.length; i++) {
    accumulated += '/' + parts[i];
    if (i < parts.length - 1) {
      html += `<span>/</span><a href="#" onclick="navigateTo('${accumulated}'); return false;">${parts[i]}</a>`;
    } else {
      html += '<span>/</span><strong>' + parts[i] + '</strong>';
    }
  }

  breadcrumb.innerHTML = html;
}

function renderDirectoryList(entries) {
  const dirList = document.getElementById('dir-list');

  if (entries.length === 0) {
    dirList.innerHTML = '<li class="empty-state">Empty directory</li>';
    return;
  }

  // Sort: directories first, then files, alphabetically
  const sorted = [...entries].sort((a, b) => {
    if (a.type !== b.type) {
      return a.type === 'directory' ? -1 : 1;
    }
    return a.name.localeCompare(b.name);
  });

  let html = '';

  // Add parent directory link if not at root
  if (currentPath && currentPath !== '/') {
    const parentPath = currentPath.substring(0, currentPath.lastIndexOf('/')) || '/';
    html += `<li><div class="dir-entry" onclick="navigateTo('${parentPath}')"><span class="icon-dir"></span>.. (parent)</div></li>`;
  }

  for (const entry of sorted) {
    const basePath = currentPath.endsWith('/') ? currentPath.slice(0, -1) : currentPath;
    const fullPath = basePath + '/' + entry.name;
    const iconClass = entry.type === 'directory' ? 'icon-dir' : 'icon-file';
    const onclick = entry.type === 'directory'
      ? `navigateTo('${fullPath}')`
      : `viewFile('${fullPath}', '${entry.name}')`;

    html += `<li><div class="dir-entry" onclick="${onclick}"><span class="${iconClass}"></span>${entry.name}</div></li>`;
  }

  dirList.innerHTML = html;
}

async function viewFile(path, name) {
  const display = document.getElementById('file-display');
  display.innerHTML = '<div class="empty-state">Loading...</div>';

  try {
    const response = await fetch('/api/files/read?path=' + encodeURIComponent(path));
    const data = await response.json();

    if (!response.ok) {
      showError('Error reading file: ' + (data.error || 'Unknown error'));
      return;
    }

    let html = '';

    // File info header
    html += '<div class="file-info">';
    html += '<div><strong>' + name + '</strong></div>';
    html += '<div>';
    if (data.size !== undefined) {
      html += 'Size: ' + formatSize(data.size) + ' | ';
    }
    if (data.modified) {
      html += 'Modified: ' + formatDate(data.modified);
    }
    html += '</div>';
    html += '</div>';

    if (data.binary) {
      html += '<div class="empty-state">Binary file (' + formatSize(data.size) + ')<br>Cannot display</div>';
    } else if (data.content !== undefined) {
      html += '<div class="file-content">' + escapeHtml(data.content) + '</div>';
    } else if (data.error) {
      html += '<div class="error-state">' + data.error + '</div>';
    }

    display.innerHTML = html;
  } catch (err) {
    showError('Error reading file: ' + err.message);
  }
}

function showError(message) {
  document.getElementById('file-display').innerHTML = '<div class="error-state">' + message + '</div>';
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Make functions global
window.navigateTo = navigateTo;
window.viewFile = viewFile;
