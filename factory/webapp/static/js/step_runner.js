/**
 * step_runner.js -- Interactive step runner WebSocket client.
 *
 * Handles WebSocket communication with the step runner backend,
 * renders interactive controls, and manages step state in the sidebar.
 */

// State
let ws = null;
let steps = window.STATION_STEPS || [];
let stationId = window.STATION_ID;
let boxName = window.BOX_NAME;
let runId = null;
let eventLog = [];
let runState = 'idle'; // idle | starting | running | done
let completedSteps = new Set();
let startTime = null;
let timerInterval = null;

// DOM refs
const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const stepList = document.getElementById('step-list');
const activeStepCard = document.getElementById('active-step');
const stepTitle = document.getElementById('step-title');
const stepDescription = document.getElementById('step-description');
const stepControls = document.getElementById('step-controls');
const stepHeading = document.getElementById('step-heading');
const stepImageContainer = document.getElementById('step-image-container');
const stepImage = document.getElementById('step-image');
const stdoutConsole = document.getElementById('stdout-console');
const stderrConsole = document.getElementById('stderr-console');
const runStatus = document.getElementById('run-status');
const calloutBanner = document.getElementById('callout-banner');
const calloutText = document.getElementById('callout-text');


// ---- Core functions ----

function startRun() {
  if (runState !== 'idle') return;
  setRunState('starting');

  // Clear previous state
  eventLog = [];
  completedSteps.clear();
  stdoutConsole.textContent = '';
  stderrConsole.textContent = '';
  clearControls();
  dismissCallout();
  resetStepList();

  fetch('/api/station-run/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({station_id: stationId, box_id: boxName}),
  })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        appendLog('stderr', 'Error: ' + data.error);
        setRunState('idle');
        return;
      }
      runId = data.run_id;
      if (data.steps && data.steps.length > 0) {
        steps = data.steps;
      }
      connectWebSocket(runId);
    })
    .catch(err => {
      appendLog('stderr', 'Failed to start run: ' + err);
      setRunState('idle');
    });
}


function stopRun() {
  if (ws) {
    ws.close();
    ws = null;
  }

  // Save run data
  if (runId) {
    const duration = startTime ? (Date.now() - startTime) / 1000 : 0;
    let successCount = 0;
    let failureCount = 0;
    let failedStep = '';

    eventLog.forEach(e => {
      if (e.type === 'done') {
        if (e.data === true) successCount++;
        else {
          failureCount++;
          if (!failedStep) failedStep = e.class || '';
        }
      }
    });

    fetch('/api/station-run/' + runId + '/stop', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        box_id: boxName,
        status: 'cancelled',
        event_log: eventLog,
        stdout: stdoutConsole.textContent,
        stderr: stderrConsole.textContent,
        success: successCount,
        failure: failureCount,
        failed_step: failedStep,
        duration: Math.round(duration * 10) / 10,
      }),
    }).catch(() => {});
  }

  setRunState('idle');
}


function connectWebSocket(id) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = protocol + '//' + window.location.host + '/ws/run/' + id;
  ws = new WebSocket(url);

  ws.onopen = function() {
    setRunState('running');
    startTime = Date.now();
    startTimer();
  };

  ws.onmessage = function(evt) {
    try {
      const event = JSON.parse(evt.data);
      handleEvent(event);
    } catch (e) {
      appendLog('stderr', 'Failed to parse event: ' + evt.data);
    }
  };

  ws.onerror = function() {
    appendLog('stderr', 'WebSocket error');
  };

  ws.onclose = function() {
    if (runState === 'running') {
      setRunState('done');
      stopTimer();
    }
  };
}


function handleEvent(event) {
  if (event.type === 'keepalive') return;

  // Track all non-log events in the event log
  if (event.type !== 'lager-log') {
    eventLog.push(event);
  }

  switch (event.type) {
    case 'start':
      handleStepStart(event);
      break;
    case 'done':
      handleStepDone(event);
      break;
    case 'error':
      handleStepError(event);
      break;
    case 'present_buttons':
      renderButtons(event);
      break;
    case 'present_text_input':
      renderTextInput(event);
      break;
    case 'present_radios':
      renderRadios(event);
      break;
    case 'present_checkboxes':
      renderCheckboxes(event);
      break;
    case 'present_select':
      renderSelect(event);
      break;
    case 'update_heading':
      if (event.data && event.data.text) {
        stepHeading.textContent = event.data.text;
      }
      break;
    case 'present_link':
      if (event.data) {
        const a = document.createElement('a');
        a.href = event.data.url;
        a.textContent = event.data.text || event.data.url;
        a.target = '_blank';
        a.className = 'text-info';
        stepHeading.innerHTML = '';
        stepHeading.appendChild(a);
      }
      break;
    case 'present_image':
      if (event.data && event.data.filename) {
        stepImage.src = event.data.filename;
        stepImageContainer.classList.remove('d-none');
      }
      break;
    case 'lager-log':
      handleLog(event);
      break;
    case 'lager-factory-complete':
      handleComplete(event);
      break;
  }
}


// ---- Step event handlers ----

function handleStepStart(event) {
  const cls = event.class;
  setStepStatus(cls, 'active');
  renderActiveStep(event);
}


function handleStepDone(event) {
  const cls = event.class;
  const passed = event.data === true;
  completedSteps.add(cls);
  setStepStatus(cls, passed ? 'pass' : 'fail');
  clearControls();

  if (!passed && event.stop_on_fail !== false) {
    // This step failed and stops execution
  }
}


function handleStepError(event) {
  const cls = event.class;
  setStepStatus(cls, 'fail');
  if (event.data && event.data.message) {
    appendLog('stderr', event.data.message);
  }
}


function handleLog(event) {
  const file = event.file || 'stdout';
  const content = event.content || '';
  appendLog(file, content);
}


function handleComplete(event) {
  // Suppress WebSocket error from server-side close (expected after completion)
  if (ws) ws.onerror = null;

  const success = event.result === true;
  setRunState('done');
  stopTimer();
  showCallout(success);

  // Save run data
  if (runId) {
    const duration = startTime ? (Date.now() - startTime) / 1000 : 0;
    fetch('/api/station-run/' + runId + '/stop', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        box_id: boxName,
        status: success ? 'completed' : 'failed',
        event_log: eventLog,
        stdout: stdoutConsole.textContent,
        stderr: stderrConsole.textContent,
        success: event.success || 0,
        failure: event.failure || 0,
        failed_step: event.failed_step || '',
        duration: Math.round(duration * 10) / 10,
      }),
    }).catch(() => {});
  }

  if (ws) {
    ws.close();
    ws = null;
  }
}


// ---- Sidebar management ----

function resetStepList() {
  document.querySelectorAll('.step-item').forEach(el => {
    el.className = 'list-group-item list-group-item-action step-item';
    const badge = el.querySelector('.step-badge');
    if (badge) {
      badge.className = 'badge bg-secondary float-end step-badge';
      badge.textContent = 'pending';
    }
  });
}


function setStepStatus(cls, status) {
  const el = document.getElementById('step-item-' + cls);
  if (!el) return;

  const badge = el.querySelector('.step-badge');

  // Remove variant classes
  el.classList.remove(
    'list-group-item-primary', 'list-group-item-success',
    'list-group-item-danger'
  );

  switch (status) {
    case 'active':
      el.classList.add('list-group-item-primary');
      if (badge) {
        badge.className = 'badge bg-primary float-end step-badge';
        badge.textContent = 'running';
      }
      break;
    case 'pass':
      el.classList.add('list-group-item-success');
      if (badge) {
        badge.className = 'badge bg-success float-end step-badge';
        badge.textContent = 'passed';
      }
      break;
    case 'fail':
      el.classList.add('list-group-item-danger');
      if (badge) {
        badge.className = 'badge bg-danger float-end step-badge';
        badge.textContent = 'failed';
      }
      break;
  }
}


// ---- Main area rendering ----

function renderActiveStep(event) {
  const cls = event.class;
  const step = steps.find(s => s.class === cls);

  activeStepCard.classList.remove('d-none');
  stepTitle.textContent = (step && step.name) ? step.name : cls;
  stepDescription.textContent = (step && step.description) ? step.description : '';
  stepHeading.textContent = '';
  stepImageContainer.classList.add('d-none');

  if (step && step.image) {
    stepImage.src = step.image;
    stepImageContainer.classList.remove('d-none');
  }

  if (step && step.link) {
    const linkEl = document.createElement('a');
    linkEl.href = step.link;
    linkEl.textContent = step.link;
    linkEl.target = '_blank';
    linkEl.className = 'text-info d-block mt-2';
    stepHeading.appendChild(linkEl);
  }

  clearControls();
}


function renderButtons(event) {
  clearControls();
  const buttons = event.data || [];
  const container = document.createElement('div');
  container.className = 'd-grid gap-2';

  buttons.forEach(function(pair) {
    const label = pair[0];
    const value = pair[1];
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = label;

    if (value === true) {
      btn.className = 'btn btn-success btn-lg';
    } else if (value === false) {
      btn.className = 'btn btn-danger btn-lg';
    } else {
      btn.className = 'btn btn-outline-secondary btn-lg';
    }

    btn.addEventListener('click', function() {
      sendResponse(value);
      clearControls();
    });
    container.appendChild(btn);
  });

  stepControls.appendChild(container);
}


function renderTextInput(event) {
  clearControls();
  const data = event.data || {};
  const container = document.createElement('div');

  if (data.prompt) {
    const label = document.createElement('label');
    label.className = 'form-label';
    label.textContent = data.prompt;
    container.appendChild(label);
  }

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'form-control mb-2';
  if (data.size) input.size = data.size;
  input.autofocus = true;
  container.appendChild(input);

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn btn-primary';
  btn.textContent = 'Next Step';
  btn.addEventListener('click', function() {
    sendResponse(input.value);
    clearControls();
  });
  container.appendChild(btn);

  // Submit on Enter
  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
      sendResponse(input.value);
      clearControls();
    }
  });

  stepControls.appendChild(container);
  input.focus();
}


function renderRadios(event) {
  clearControls();
  const data = event.data || {};
  const container = document.createElement('div');

  if (data.label) {
    const heading = document.createElement('label');
    heading.className = 'form-label fw-bold';
    heading.textContent = data.label;
    container.appendChild(heading);
  }

  const choices = data.choices || [];
  choices.forEach(function(choice, idx) {
    const label = choice[0];
    const value = choice[1];
    const wrapper = document.createElement('div');
    wrapper.className = 'form-check';

    const radio = document.createElement('input');
    radio.type = 'radio';
    radio.className = 'form-check-input';
    radio.name = 'step-radio';
    radio.id = 'radio-' + idx;
    radio.value = JSON.stringify(value);
    if (idx === 0) radio.checked = true;
    wrapper.appendChild(radio);

    const radioLabel = document.createElement('label');
    radioLabel.className = 'form-check-label';
    radioLabel.htmlFor = 'radio-' + idx;
    radioLabel.textContent = label;
    wrapper.appendChild(radioLabel);

    container.appendChild(wrapper);
  });

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn btn-primary mt-2';
  btn.textContent = 'Next Step';
  btn.addEventListener('click', function() {
    const selected = container.querySelector('input[name="step-radio"]:checked');
    if (selected) {
      sendResponse(JSON.parse(selected.value));
    }
    clearControls();
  });
  container.appendChild(btn);

  stepControls.appendChild(container);
}


function renderCheckboxes(event) {
  clearControls();
  const data = event.data || {};
  const container = document.createElement('div');

  if (data.label) {
    const heading = document.createElement('label');
    heading.className = 'form-label fw-bold';
    heading.textContent = data.label;
    container.appendChild(heading);
  }

  const choices = data.choices || [];
  choices.forEach(function(choice, idx) {
    const label = choice[0];
    const value = choice[1];
    const wrapper = document.createElement('div');
    wrapper.className = 'form-check';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'form-check-input';
    checkbox.id = 'check-' + idx;
    checkbox.value = JSON.stringify(value);
    wrapper.appendChild(checkbox);

    const checkLabel = document.createElement('label');
    checkLabel.className = 'form-check-label';
    checkLabel.htmlFor = 'check-' + idx;
    checkLabel.textContent = label;
    wrapper.appendChild(checkLabel);

    container.appendChild(wrapper);
  });

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn btn-primary mt-2';
  btn.textContent = 'Next Step';
  btn.addEventListener('click', function() {
    const checked = container.querySelectorAll('input[type="checkbox"]:checked');
    const values = Array.from(checked).map(c => JSON.parse(c.value));
    sendResponse(values);
    clearControls();
  });
  container.appendChild(btn);

  stepControls.appendChild(container);
}


function renderSelect(event) {
  clearControls();
  const data = event.data || {};
  const container = document.createElement('div');

  if (data.label) {
    const heading = document.createElement('label');
    heading.className = 'form-label fw-bold';
    heading.textContent = data.label;
    container.appendChild(heading);
  }

  const select = document.createElement('select');
  select.className = 'form-select mb-2';
  if (data.allow_multiple) select.multiple = true;

  const choices = data.choices || [];
  choices.forEach(function(choice) {
    const opt = document.createElement('option');
    opt.value = JSON.stringify(choice[1]);
    opt.textContent = choice[0];
    select.appendChild(opt);
  });
  container.appendChild(select);

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn btn-primary';
  btn.textContent = 'Next Step';
  btn.addEventListener('click', function() {
    if (data.allow_multiple) {
      const selected = Array.from(select.selectedOptions)
        .map(o => JSON.parse(o.value));
      sendResponse(selected);
    } else {
      const val = select.value ? JSON.parse(select.value) : null;
      sendResponse(val);
    }
    clearControls();
  });
  container.appendChild(btn);

  stepControls.appendChild(container);
}


function clearControls() {
  stepControls.innerHTML = '';
}


// ---- Communication ----

function sendResponse(value) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({value: value}));
  }
}


// ---- Output ----

function appendLog(type, text) {
  const target = type === 'stderr' ? stderrConsole : stdoutConsole;
  const span = document.createElement('span');
  span.textContent = text + '\n';
  if (type === 'stderr') span.className = 'text-danger';
  target.appendChild(span);
  target.scrollTop = target.scrollHeight;
}


function showCallout(success) {
  calloutBanner.classList.remove('d-none', 'alert-success', 'alert-danger');
  calloutBanner.classList.add('show');
  if (success) {
    calloutBanner.classList.add('alert-success');
    calloutText.textContent = 'Test Succeeded!';
  } else {
    calloutBanner.classList.add('alert-danger');
    calloutText.textContent = 'Test Failed';
  }
}


function dismissCallout() {
  calloutBanner.classList.add('d-none');
  calloutBanner.classList.remove('show', 'alert-success', 'alert-danger');
}


// ---- UI State ----

function setRunState(state) {
  runState = state;
  switch (state) {
    case 'idle':
      btnStart.classList.remove('d-none');
      btnStop.classList.add('d-none');
      btnStart.disabled = false;
      runStatus.className = 'badge bg-secondary';
      runStatus.textContent = 'idle';
      break;
    case 'starting':
      btnStart.disabled = true;
      btnStart.textContent = 'Starting...';
      runStatus.className = 'badge bg-warning';
      runStatus.textContent = 'starting';
      break;
    case 'running':
      btnStart.classList.add('d-none');
      btnStart.textContent = 'START';
      btnStop.classList.remove('d-none');
      runStatus.className = 'badge bg-primary';
      runStatus.textContent = 'running';
      break;
    case 'done':
      btnStart.classList.remove('d-none');
      btnStart.disabled = false;
      btnStart.textContent = 'START';
      btnStop.classList.add('d-none');
      runStatus.className = 'badge bg-info';
      runStatus.textContent = 'done';
      break;
  }
}


function startTimer() {
  stopTimer();
  timerInterval = setInterval(function() {
    if (startTime) {
      const elapsed = Math.round((Date.now() - startTime) / 1000);
      runStatus.textContent = 'running ' + elapsed + 's';
    }
  }, 1000);
}


function stopTimer() {
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
}
