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

function fmtSnapshot(value) {
  var date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value || '') : date.toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'});
}

function infoHtml(text, key) {
  return '<span class="context-info" data-info="' + esc(key) + '"><button type="button" popovertarget="info:' + esc(key) +
    '" aria-label="' + esc(text) + '" onpointerenter="if (event.pointerType === \'mouse\') this.nextElementSibling.showPopover()">i</button>' +
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
  html = '<div class="memorize-row"><div class="memorize-pressure">' + html + '</div>' +
    '<div class="context-load"><p>Context load ' + infoHtml(contextHelp, 'context:' + data.soul_id) + '</p><p>' +
    (data.context_load_tokens == null ? 'unknown' : '&asymp; ' + fmt(data.context_load_tokens) + ' tokens' +
      (data.context_load_has_chat ? '' : ' (memory only)')) + '</p></div></div>';
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
  html += '<p class="muted">Memorize-eligible at ' + fmt(threshold) + ' tokens; a sleep-gap releases it. Snapshot ' + esc(fmtSnapshot(data.computed_at)) + '.</p>';
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
    return (rows.length > 1 ? '<h3>' + esc(row.soul_id) + '</h3>' : '') + memorizeHtml(row);
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
