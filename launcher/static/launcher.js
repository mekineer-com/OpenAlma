async function quitLauncher(button) {
  button.disabled = true;
  try {
    var response = await fetch('/launcher/quit', {method: 'POST'});
    if (!response.ok) throw new Error('Exit failed');
    document.body.innerHTML = '<main><h1>OpenAlma Launcher has exited.</h1><p>You may close this tab.</p></main>';
  } catch (error) {
    button.disabled = false;
    alert(error.message);
  }
}

function esc(text) {
  return String(text || '').replace(/[&<>"']/g, function(ch) {
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch];
  });
}

function fmt(n) {
  return Number(n || 0).toLocaleString();
}

function installProgressHtml(progress) {
  var attributes = progress && progress.total_steps ? ' max="' + esc(progress.total_steps) + '" value="' + esc(progress.step_number - 1) + '"' : '';
  var html = '<progress class="install-progress" aria-label="Installation steps completed"' + attributes + '></progress>';
  if (progress) {
    var seconds = progress.elapsed_seconds;
    html += '<div class="svc-detail">' + (progress.total_steps ? 'Step ' + esc(progress.step_number) + ' of ' + esc(progress.total_steps) + ' · ' : '') +
      Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0') + ' elapsed</div>';
  }
  return html;
}

var serviceRows = [];

function updateDownloadNotice() {
  var download = document.getElementById('update-download');
  if (!download) return;
  var active = !!document.querySelector('tr[data-update-active="true"]');
  download.hidden = active;
  document.getElementById('update-stop-notice').hidden = !active;
}

async function launcherUpdateRequest(path, method) {
  var response = await fetch(path, {method: method || 'GET', cache: 'no-store'});
  var data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Launcher update failed');
  return data;
}

function renderLauncherUpdate(data) {
  var form = document.getElementById('launcher-update-form');
  var button = form.querySelector('button');
  var progress = document.getElementById('launcher-update-progress');
  var busy = data.state === 'running' || data.state === 'ready';
  button.disabled = busy;
  button.textContent = busy ? 'Updating…' : data.state === 'error' ? 'Retry' : data.state === 'opened' ? 'Open installer again' : 'Update';
  document.getElementById('launcher-update-status').textContent =
    (data.step || '') + (data.detail ? ': ' + data.detail : '');
  progress.hidden = !busy;
  if (data.progress && data.progress.total_bytes) {
    progress.max = data.progress.total_bytes;
    progress.value = data.progress.downloaded_bytes;
  } else {
    progress.removeAttribute('value');
  }
}

async function pollLauncherUpdate(start) {
  var form = document.getElementById('launcher-update-form');
  if (!form || form.dataset.polling || (!start && form.dataset.paused)) return;
  form.dataset.polling = 'true';
  delete form.dataset.paused;
  if (start) renderLauncherUpdate({state: 'running', step: 'Preparing update'});
  try {
    var data = await launcherUpdateRequest(start ? '/launcher/update' : '/launcher/update/status', start ? 'POST' : 'GET');
    renderLauncherUpdate(data);
    if (data.state === 'ready') {
      data = await launcherUpdateRequest('/launcher/update/open', 'POST');
      renderLauncherUpdate(data);
    }
    if (data.state === 'opened' || data.state === 'error') form.dataset.paused = 'true';
  } catch (error) {
    form.dataset.paused = 'true';
    renderLauncherUpdate({state: 'error', step: error.message});
  } finally {
    delete form.dataset.polling;
  }
}

function startLauncherUpdate() {
  return pollLauncherUpdate(true);
}

function initServiceVisibility() {
  serviceRows = Array.from(document.querySelectorAll('tr[data-service], #echo-row'));
  try {
    document.getElementById('hide-not-installed').checked = localStorage.getItem('hide-not-installed') === 'true';
  } catch (_error) {}
  groupServiceRows();
}

function setServiceVisibility(hide) {
  try { localStorage.setItem('hide-not-installed', String(hide)); } catch (_error) {}
  groupServiceRows();
}

function groupServiceRows() {
  if (!serviceRows.length) return;
  var visible = document.getElementById('visible-services');
  var hidden = document.getElementById('hidden-services');
  var hide = document.getElementById('hide-not-installed').checked;
  var last = new Map([[visible, null], [hidden, null]]);
  var focused = document.activeElement;
  serviceRows.forEach(function(row) {
    var target = hide && row.dataset.installed !== 'true' ? hidden : visible;
    var children = [];
    for (var child = row.nextElementSibling; child && child.dataset.irisInstallation; child = child.nextElementSibling) children.push(child);
    [row].concat(children).forEach(function(node) {
      var before = last.get(target) ? last.get(target).nextElementSibling : target.firstElementChild;
      if (node !== before) target.insertBefore(node, before);
      last.set(target, node);
    });
  });
  var section = document.getElementById('hidden-services-section');
  section.hidden = !serviceRows.some(function(row) { return row.dataset.installed !== 'true'; });
  if (!hide || section.hidden) section.open = false;
  if (focused && document.activeElement !== focused) focused.focus();
}

function infoHtml(text, key, label) {
  return '<span class="context-info" data-info="' + esc(key) + '"><button type="button" popovertarget="info:' + esc(key) +
    '" aria-label="' + esc(text) + '" onpointerenter="if (event.pointerType === \'mouse\') this.nextElementSibling.showPopover()" onpointerleave="if (event.pointerType === \'mouse\') this.nextElementSibling.hidePopover()">' + esc(label) + '<span class="info-icon">i</span></button>' +
    '<span class="info-text" popover id="info:' + esc(key) + '">' + esc(text) + '</span></span>';
}

function memorizeHtml(data) {
  if (data && data.error) {
    return '<p class="error" role="alert">' + esc(data.error) + '</p>';
  }
  if (!data || data.threshold == null) {
    return '<p class="muted">Memory status unavailable</p>';
  }
  var threshold = Number(data.threshold || 0);
  var html;
  if (data.source_warning) {
    html = '<p role="alert">Memorize: error ' + infoHtml(data.source_warning, 'source:' + data.soul_id) + '</p>';
  } else if (data.summed_unmemorized_tokens == null) {
    html = '<p>Memorize: unknown</p>';
  } else {
    var tokens = Number(data.summed_unmemorized_tokens);
    var pct = Number(data.pct || 0);
    html = '<p>Memorize: ' + fmt(tokens) + ' / ' + fmt(threshold) + ' (' + pct + '%)';
    if (tokens >= threshold) {
      html += ' <span class="badge">' + esc(data.sleep_gap_ready ? 'sleep-gap detected' : 'waiting for sleep-gap') + '</span>';
    }
    html += '</p>';
    html += '<div class="meter"><div class="meter-fill" style="width: ' + Math.min(pct, 100) + '%"></div></div>';
  }
  var contextHelp = 'Forecast at the Memorize threshold using current chat density and supporting memory. With no chat sample, only supporting memory and instructions are shown. Generated episode/background summaries and speaker details are excluded; supporting context varies, and waiting for a sleep gap can produce a larger actual batch. Actual prepared prompts are checked separately.';
  html += '<p class="muted">Memorize-eligible at ' + fmt(threshold) + ' tokens; a sleep-gap releases it.</p>';
  html = '<div class="memorize-row"><div class="memorize-pressure">' + html + '</div>' +
    '<div class="context-load"><p>' + infoHtml(contextHelp, 'context:' + data.soul_id, 'Context load') + '</p><p>' +
    (data.context_load_tokens == null ? 'unknown' : '&asymp; ' + fmt(data.context_load_tokens) + ' tokens' +
      (data.context_load_has_chat ? '' : '<br>(memory only)')) + '</p></div></div>';
  if (data.paused) {
    var running = data.memorize_running || data.consolidation_running;
    html += '<p class="consolidation-warning" role="alert">Paused: ' +
      (data.retry_operation === 'import' ? (data.pause_reason === 'Import failed. Retry in Echo.' ? 'Import failed.' : 'waiting for import.') :
       data.pause_reason === 'Waiting for Memorize after import.' ? 'waiting for Memorize.' :
       (data.retry_operation === 'memorize' ? 'Memorize' : 'Consolidation') + ' failed.') +
      ' <span title="' + esc(data.pause_reason) + '">!</span> ';
    html += data.retry_operation === 'import' ? '<a class="btn" href="/echo">Echo</a></p>' :
      '<button type="button" class="btn" data-soul="' + esc(data.soul_id) + '" onclick="retryConsolidation(this)"' + (running ? ' disabled' : '') + '>' + (running ? 'Retrying...' : 'Retry') + '</button></p>';
  } else if (data.consolidation_state === 'overdue') {
    var overdueSegments = Number(data.pending_consolidation_segments || 0);
    html += '<p class="consolidation-warning" role="status">Weekly reflection will occur after the coming Memorize. ' + fmt(overdueSegments) + ' memorized ' + (overdueSegments === 1 ? 'segment' : 'segments') + ' already in queue.</p>';
  } else if (data.consolidation_state === 'running') {
    html += '<p class="muted" role="status">Memory consolidation is running.</p>';
  }
  if (data.memorize_running && data.progress) {
    html += '<p class="muted" role="status">' + esc(data.progress.phase || 'Running') + (data.progress.total ? ': ' + fmt(data.progress.current) + ' / ' + fmt(data.progress.total) : '') + '</p>';
  }
  return html;
}

function renderMemorize(data) {
  var box = document.getElementById('memorize-meter');
  if (!box) return;
  if (data.error) { box.innerHTML = '<p class="error" role="alert">' + esc(data.error) + '</p>'; return; }
  var openKey = box.querySelector('.info-text:popover-open')?.parentElement.dataset.info;
  var focusKey = document.activeElement?.closest('.context-info')?.dataset.info;
  var rows = data.souls || [];
  box.innerHTML = rows.map(function(row) {
    return '<h3>' + esc(row.soul_id) + '</h3>' + memorizeHtml(row);
  }).join('') || '<p class="muted">No Souls available</p>';
  box.querySelectorAll('.context-info').forEach(function(info) {
    if (info.dataset.info === openKey) {
      info.querySelector('.info-text').showPopover();
    }
    if (info.dataset.info === focusKey) info.querySelector('button').focus();
  });
}

function retryConsolidation(button) {
  button.disabled = true;
  button.textContent = 'Retrying...';
  fetch('/memorize/retry?soul_id=' + encodeURIComponent(button.dataset.soul), { method: 'POST' })
    .then(function(response) {
      if (response.ok) return response.json();
      return response.json().then(function(data) {
        throw new Error(data.detail || 'Retry failed');
      });
    })
    .then(pollMemorize)
    .catch(function(error) {
      button.disabled = false;
      button.textContent = 'Retry';
      window.alert(error.message);
    });
}
