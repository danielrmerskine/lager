/* ---- State ---- */
let scripts = [];
let currentSuiteId = null;
let eventSource = null;
let startTime = null;
let timerInterval = null;

/* ---- Script management ---- */

function loadScripts() {
  fetch('/api/scripts')
    .then(r => r.json())
    .then(data => {
      scripts = data;
      renderScriptList();
    });
}

function uploadFiles(fileList) {
  if (!fileList || fileList.length === 0) return;

  const form = new FormData();
  for (const file of fileList) {
    form.append('files', file);
  }

  fetch('/api/scripts/upload', { method: 'POST', body: form })
    .then(r => r.json())
    .then(data => {
      if (data.errors && data.errors.length > 0) {
        alert('Some files failed: ' + data.errors.map(e => e.file + ': ' + e.error).join(', '));
      }
      loadScripts();
    })
    .catch(err => alert('Upload failed: ' + err));
}

function removeScript(name) {
  fetch('/api/scripts/' + encodeURIComponent(name), { method: 'DELETE' })
    .then(() => loadScripts());
}

function moveScript(index, direction) {
  const newIndex = index + direction;
  if (newIndex < 0 || newIndex >= scripts.length) return;

  const names = scripts.map(s => s.name);
  const tmp = names[index];
  names[index] = names[newIndex];
  names[newIndex] = tmp;

  fetch('/api/scripts/reorder', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ order: names }),
  }).then(() => loadScripts());
}

function clearAllScripts() {
  if (!confirm('Remove all uploaded scripts?')) return;

  const names = scripts.map(s => s.name);
  Promise.all(names.map(n =>
    fetch('/api/scripts/' + encodeURIComponent(n), { method: 'DELETE' })
  )).then(() => loadScripts());
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  return (bytes / 1024).toFixed(1) + ' KB';
}

function renderScriptList() {
  const container = document.getElementById('script-list');
  const clearBtn = document.getElementById('clear-all-btn');

  if (scripts.length === 0) {
    container.innerHTML = '<div class="text-body-secondary text-center py-2">No scripts uploaded</div>';
    clearBtn.style.display = 'none';
    return;
  }

  clearBtn.style.display = '';
  let html = '';
  scripts.forEach((s, i) => {
    html += `
      <div class="script-list-item" id="script-item-${i}">
        <span class="script-index">${i + 1}</span>
        <span class="script-name" title="${s.name}">${s.name}</span>
        <span class="script-size">${formatSize(s.size_bytes)}</span>
        <span class="badge bg-secondary script-badge" id="badge-${i}"></span>
        <div class="btn-group btn-group-sm">
          <button class="btn btn-outline-secondary" onclick="moveScript(${i}, -1)"
                  ${i === 0 ? 'disabled' : ''} title="Move up">&#9650;</button>
          <button class="btn btn-outline-secondary" onclick="moveScript(${i}, 1)"
                  ${i === scripts.length - 1 ? 'disabled' : ''} title="Move down">&#9660;</button>
          <button class="btn btn-outline-danger" onclick="removeScript('${s.name}')"
                  title="Remove">&#10005;</button>
        </div>
      </div>`;
  });
  container.innerHTML = html;

  // Hide all badges initially (they show during runs)
  scripts.forEach((_, i) => {
    document.getElementById('badge-' + i).style.display = 'none';
  });
}

/* ---- Suite execution ---- */

function startSuiteRun() {
  const boxId = document.getElementById('box-select').value;
  if (!boxId) {
    alert('Please select a box.');
    return;
  }
  if (scripts.length === 0) {
    alert('Please upload at least one script.');
    return;
  }

  // Clear output
  const outputEl = document.getElementById('output-console');
  outputEl.innerHTML = '';
  document.getElementById('status-bar').textContent = '';

  // Reset badges
  scripts.forEach((_, i) => {
    const badge = document.getElementById('badge-' + i);
    if (badge) {
      badge.textContent = '';
      badge.className = 'badge bg-secondary script-badge';
      badge.style.display = 'none';
    }
  });

  // Disable run, enable cancel
  document.getElementById('run-btn').disabled = true;
  document.getElementById('cancel-btn').disabled = false;

  // Start timer
  startTime = Date.now();
  updateTimer();
  timerInterval = setInterval(updateTimer, 1000);

  fetch('/api/run-suite', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ box_id: boxId }),
  })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        appendText('stderr', data.error);
        finishSuite();
        return;
      }
      currentSuiteId = data.suite_id;
      connectSuiteSSE(data.suite_id);
    })
    .catch(err => {
      appendText('stderr', 'Failed to start suite: ' + err);
      finishSuite();
    });
}

function connectSuiteSSE(suiteId) {
  eventSource = new EventSource('/api/stream-suite/' + suiteId);

  eventSource.onmessage = function(event) {
    const msg = JSON.parse(event.data);
    const evt = msg.event;
    const d = msg.data;

    if (evt === 'script_start') {
      setScriptStatus(d.index, 'running');
      appendScriptHeader(d.index, d.name);
    } else if (evt === 'script_output') {
      const output = d.output;
      appendText(output.type, output.line);
    } else if (evt === 'script_end') {
      appendScriptResult(d.index, d.name, d.status, d.exit_code);
      if (d.status === 'completed') {
        setScriptStatus(d.index, 'passed');
      } else {
        setScriptStatus(d.index, 'failed');
      }
    } else if (evt === 'suite_done') {
      showSuiteSummary(d);
      finishSuite();
    }
  };

  eventSource.onerror = function() {
    finishSuite();
  };
}

function cancelSuite() {
  if (!currentSuiteId) return;

  fetch('/api/suite/' + currentSuiteId + '/cancel', { method: 'POST' })
    .then(r => r.json())
    .then(() => {
      appendText('stderr', 'Cancelling...');
    })
    .catch(err => {
      appendText('stderr', 'Cancel failed: ' + err);
    });
}

function finishSuite() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
  document.getElementById('run-btn').disabled = false;
  document.getElementById('cancel-btn').disabled = true;
  currentSuiteId = null;
}

/* ---- UI helpers ---- */

function setScriptStatus(index, status) {
  const badge = document.getElementById('badge-' + index);
  if (!badge) return;
  badge.style.display = '';

  if (status === 'running') {
    badge.textContent = 'running';
    badge.className = 'badge bg-primary script-badge';
  } else if (status === 'passed') {
    badge.textContent = 'passed';
    badge.className = 'badge bg-success script-badge';
  } else if (status === 'failed') {
    badge.textContent = 'failed';
    badge.className = 'badge bg-danger script-badge';
  }
}

function appendScriptHeader(index, name) {
  const outputEl = document.getElementById('output-console');
  const div = document.createElement('div');
  div.className = 'script-header';
  div.textContent = '--- [' + (index + 1) + '] ' + name + ' ---';
  outputEl.appendChild(div);
  outputEl.scrollTop = outputEl.scrollHeight;
}

function appendScriptResult(index, name, status, exitCode) {
  const outputEl = document.getElementById('output-console');
  const div = document.createElement('div');
  if (status === 'completed') {
    div.className = 'script-result-pass';
    div.textContent = '--- [' + (index + 1) + '] ' + name + ' PASSED (exit 0) ---';
  } else {
    div.className = 'script-result-fail';
    div.textContent = '--- [' + (index + 1) + '] ' + name + ' FAILED (exit ' + exitCode + ') ---';
  }
  outputEl.appendChild(div);
  outputEl.scrollTop = outputEl.scrollHeight;
}

function appendText(type, text) {
  const outputEl = document.getElementById('output-console');
  const span = document.createElement('span');
  span.textContent = text + '\n';
  if (type === 'stderr') {
    span.className = 'text-danger';
  }
  outputEl.appendChild(span);
  outputEl.scrollTop = outputEl.scrollHeight;
}

function showSuiteSummary(data) {
  const results = data.results || [];
  const passed = results.filter(r => r.status === 'completed').length;
  const total = results.length;
  const statusBar = document.getElementById('status-bar');

  if (data.status === 'completed') {
    statusBar.innerHTML = '<span class="text-success">' + passed + '/' + total + ' passed - ALL PASSED</span>';
  } else if (data.status === 'cancelled') {
    statusBar.innerHTML = '<span class="text-warning">' + passed + '/' + total + ' passed - CANCELLED</span>';
  } else {
    statusBar.innerHTML = '<span class="text-danger">' + passed + '/' + total + ' passed - FAILED</span>';
  }
}

function updateTimer() {
  if (!startTime) return;
  const elapsed = ((Date.now() - startTime) / 1000).toFixed(0);
  const statusBar = document.getElementById('status-bar');
  // Only update if no final status shown yet
  if (!statusBar.textContent.includes('passed')) {
    statusBar.textContent = 'Running... ' + elapsed + 's';
  }
}

/* ---- Drag & drop ---- */

document.addEventListener('DOMContentLoaded', function() {
  loadScripts();

  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');

  dropZone.addEventListener('dragover', function(e) {
    e.preventDefault();
    dropZone.classList.add('dragover');
  });

  dropZone.addEventListener('dragleave', function() {
    dropZone.classList.remove('dragover');
  });

  dropZone.addEventListener('drop', function(e) {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    uploadFiles(e.dataTransfer.files);
  });

  dropZone.addEventListener('click', function() {
    fileInput.click();
  });

  fileInput.addEventListener('change', function() {
    uploadFiles(this.files);
    this.value = '';  // allow re-uploading same file
  });
});
