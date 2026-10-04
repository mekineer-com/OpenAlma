const soulChoice = document.getElementById('echo-soul');
const labelInput = document.getElementById('echo-label');
const chatMenu = document.getElementById('echo-chat-options');
const chatReady = document.getElementById('echo-chat-ready');
const chatNew = document.getElementById('echo-chat-new');
const fileInput = document.getElementById('echo-file');
const allHistory = document.getElementById('echo-all-history');
const gap = document.getElementById('echo-history-count');
const continuous = document.getElementById('echo-continuous');
let knownChats = new Set(), pendingNewChat = '', selection = null, preview = null;
let accepted = null, lastStatus = null, timer = null, busy = false;
let selectedSoul = '';

async function echoRequest(url, options) {
  const response = await fetch(url, {cache: 'no-store', ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Import request failed');
  return data;
}
function showError(error) {
  const box = document.getElementById('echo-error');
  box.textContent = error.message;
  box.hidden = false;
}
function lockForm(locked) {
  busy = locked;
  document.getElementById('echo-picker').disabled = locked;
  document.getElementById('echo-soul-picker').disabled = locked;
  document.getElementById('echo-upload').disabled = locked || !selection;
  document.getElementById('echo-process').disabled = locked || !lastStatus?.registered || lastStatus.running || lastStatus.import_state.error || lastStatus.import_state.stage === 'complete';
  document.getElementById('echo-retry').disabled = locked || lastStatus?.running;
  document.getElementById('echo-register').disabled = locked;
}
function closeChatMenu() {
  chatMenu.hidden = true;
  labelInput.setAttribute('aria-expanded', 'false');
}
function openChatMenu() {
  chatMenu.hidden = knownChats.size === 0;
  labelInput.setAttribute('aria-expanded', String(!chatMenu.hidden));
}
function invalidatePreview() {
  preview = null;
  document.getElementById('echo-confirm').disabled = true;
  document.getElementById('echo-preview').hidden = true;
}
function resetSelection() {
  selection = null;
  lastStatus = null;
  chatReady.hidden = true;
  chatNew.hidden = true;
  pendingNewChat = '';
  invalidatePreview();
  clearTimeout(timer);
  document.getElementById('echo-results').replaceChildren();
  document.getElementById('echo-status').textContent = 'Choose a Soul and chat app.';
  document.getElementById('echo-register').hidden = true;
  document.getElementById('echo-retry').hidden = true;
  document.getElementById('echo-show-results').disabled = true;
  document.getElementById('memorize-meter').textContent = "Choose a chat to see its Soul's progress.";
  lockForm(false);
}
async function loadChats() {
  resetSelection();
  const sid = selectedSoul;
  knownChats = new Set();
  chatMenu.replaceChildren();
  if (!sid) return;
  const data = await echoRequest('/echo/chats?' + new URLSearchParams({soul_id: sid}));
  if (sid !== selectedSoul) return;
  knownChats = new Set(data.chats.map(chat => chat.label));
  knownChats.forEach(addChatOption);
}
function addChatOption(name) {
    const option = document.createElement('button');
    option.type = 'button'; option.role = 'option'; option.textContent = name;
    option.addEventListener('mousedown', event => event.preventDefault());
    option.addEventListener('click', () => {labelInput.value = name; resetSelection(); closeChatMenu();});
    chatMenu.appendChild(option);
}
labelInput.addEventListener('focus', openChatMenu);
labelInput.addEventListener('click', openChatMenu);
labelInput.addEventListener('blur', closeChatMenu);
labelInput.addEventListener('input', () => {resetSelection(); openChatMenu();});
document.getElementById('echo-chat-form').addEventListener('submit', event => {
  event.preventDefault();
  const label = labelInput.value.trim();
  if (!selectedSoul || !label || label.split(/\s+/).length !== 1) {
    showError(new Error('Select a Soul and a one-word chat-app label.')); return;
  }
  if (!knownChats.has(label) && pendingNewChat !== label) {
    pendingNewChat = label; chatNew.hidden = false; return;
  }
  selection = {soul_id: selectedSoul, label, confirmed_new: !knownChats.has(label)};
  chatNew.hidden = true; chatReady.hidden = false; closeChatMenu();
  lockForm(false);
  refreshStatus();
});
function uploadForm() {
  const form = new FormData();
  Object.entries(selection).forEach(([key, value]) => form.append(key, value));
  form.append('file', fileInput.files[0]);
  form.append('all_history', allHistory.checked);
  form.append('history_count', gap.value);
  return form;
}
function showPreview(data) {
  preview = data;
  gap.max = data.total_messages;
  if (allHistory.checked) gap.value = data.total_messages;
  document.getElementById('echo-gap-count').textContent = gap.value;
  document.getElementById('echo-preview').hidden = false;
  document.getElementById('echo-counts').textContent = `${data.total_messages} text messages; ${data.duplicates} already stored; ${data.stats.skipped_non_text} non-text and ${data.stats.skipped_empty} empty items skipped.`;
  const range = group => `${group.count} messages${group.count ? ` (${group.start} to ${group.end})` : ''}`;
  document.getElementById('echo-ranges').textContent = `New history: ${range(data.history)}. New current context: ${range(data.current)}.`;
  const guide = data.guidance;
  document.getElementById('echo-guidance').textContent = (guide.pending_start_day ? `This chat's pending context starts ${guide.pending_start_day}. ` : 'No stored pending context for this chat. ') + (guide.processed_start_day ? `Previously processed dates: ${guide.processed_start_day} to ${guide.processed_end_day}.` : 'No processed dates recorded for this chat.');
  document.getElementById('echo-overlap').hidden = !data.possible_overlap;
  document.getElementById('echo-before').textContent = data.before_gap || '(none)';
  document.getElementById('echo-after').textContent = data.after_gap || '(none)';
  document.getElementById('echo-confirm').disabled = data.saved;
}
fileInput.addEventListener('change', () => {
  invalidatePreview(); allHistory.checked = true; gap.max = 0; gap.value = 0;
  document.getElementById('echo-gap').hidden = true;
});
gap.addEventListener('input', () => {invalidatePreview(); document.getElementById('echo-gap-count').textContent = gap.value;});
allHistory.addEventListener('change', () => {invalidatePreview(); document.getElementById('echo-gap').hidden = allHistory.checked;});
async function upload(save) {
  if (!selection || !fileInput.files.length || busy || (save && !preview)) return;
  const body = uploadForm();
  document.getElementById('echo-error').hidden = true;
  lockForm(true);
  try {
    const data = await echoRequest('/echo/' + (save ? 'confirm' : 'preview'), {method: 'POST', body});
    showPreview(data);
    if (save) {
      if (!knownChats.has(selection.label)) addChatOption(selection.label);
      knownChats.add(selection.label);
      document.getElementById('echo-status').textContent = 'Source stored and registered. Historical processing is a separate action.';
    }
  } catch (error) {showError(error); invalidatePreview();}
  finally {lockForm(false); await refreshStatus();}
}
document.getElementById('echo-upload-form').addEventListener('submit', event => {event.preventDefault(); upload(false);});
document.getElementById('echo-confirm').addEventListener('click', () => upload(true));

function checkpointAdvanced(before, after) {
  return after.stage === 'complete' || after.memorize_cursor > before.memorize_cursor ||
    before.pending_segment_ids.some(id => !after.pending_segment_ids.includes(id));
}
async function readStatus() {
  const selected = selection;
  const data = await echoRequest('/echo/status?' + new URLSearchParams({soul_id: selected.soul_id, label: selected.label}));
  return selected === selection ? data : null;
}
async function refreshStatus() {
  clearTimeout(timer);
  if (!selection) return;
  if (busy && !accepted) {timer = setTimeout(refreshStatus, 3000); return;}
  let nextBatch = false;
  try {
    const data = await readStatus();
    if (!data) return;
    lastStatus = data;
    document.getElementById('echo-register').hidden = !data.stored || data.registered;
    document.getElementById('echo-retry').hidden = !data.registered || !data.import_state.error;
    document.getElementById('echo-show-results').disabled = !data.registered;
    const state = data.import_state;
    document.getElementById('echo-status').textContent = !data.stored ? 'No source stored yet.' : !data.registered ? 'Source stored; register it to process.' : state.error ? `Import failed: ${state.error}` : data.running ? `Soul memory work: ${data.progress.phase || 'running'}` : state.stage === 'complete' ? 'Historical processing complete. Current rows remain ordinary chat context.' : `History checkpoint ${state.memorize_cursor + 1} / ${state.history_end_index}; ${state.pending_segment_ids.length} segments awaiting consolidation.`;
    if (data.meter) renderMemorize({souls: [{...data.meter, soul_id: selection.soul_id}]});
    if (accepted && data.registered && !data.running) {
      const before = accepted;
      accepted = null;
      if (state.error) throw new Error(state.error);
      if (!checkpointAdvanced(before, state)) throw new Error('Completion is uncertain. Inspect status before starting again.');
      await loadResults();
      lockForm(false);
      nextBatch = continuous.checked && state.stage !== 'complete';
    }
    if (!accepted) lockForm(busy);
  } catch (error) {
    accepted = null; continuous.checked = false; lockForm(false); showError(error);
  } finally {
    if (selection) timer = setTimeout(nextBatch ? () => startWork('process') : refreshStatus, nextBatch ? 0 : 3000);
  }
}
async function startWork(action) {
  if (!selection || busy || accepted) return;
  lockForm(true);
  document.getElementById('echo-error').hidden = true;
  try {
    const before = await readStatus();
    if (!before?.registered || before.running || (action === 'process' && before.import_state.stage === 'complete')) throw new Error('No import batch is ready to start.');
    const form = new FormData();
    form.append('soul_id', selection.soul_id); form.append('label', selection.label);
    const reply = await echoRequest('/echo/' + action, {method: 'POST', body: form});
    if (reply.status !== 'accepted' || reply.conversation_id !== before.conversation_id) throw new Error('Start acknowledgement is uncertain. Inspect status; do not repeat payment.');
    accepted = before.import_state;
  } catch (error) {
    accepted = null; continuous.checked = false; lockForm(false); showError(error);
  }
  await refreshStatus();
}
document.getElementById('echo-process').addEventListener('click', () => startWork('process'));
document.getElementById('echo-retry').addEventListener('click', () => startWork('retry'));
document.getElementById('echo-register').addEventListener('click', async () => {
  lockForm(true);
  try {
    const form = new FormData();
    form.append('soul_id', selection.soul_id); form.append('label', selection.label);
    await echoRequest('/echo/register', {method: 'POST', body: form});
  } catch (error) {showError(error);}
  finally {lockForm(false); refreshStatus();}
});
async function loadResults() {
  const selected = selection;
  const data = await echoRequest('/echo/results?' + new URLSearchParams({soul_id: selected.soul_id}));
  if (selected !== selection) return;
  const box = document.getElementById('echo-results');
  box.replaceChildren();
  [...data.categories, ...data.soul_summaries].forEach(row => {
    const details = document.createElement('details'), title = document.createElement('summary'), prose = document.createElement('div');
    title.textContent = row.name || row.label || row.title || row.kind;
    prose.className = 'echo-prose'; prose.textContent = row.summary || row.content || '';
    details.append(title, prose); box.appendChild(details);
  });
  if (!box.childElementCount) box.textContent = 'No dossier prose yet.';
}
document.getElementById('echo-show-results').addEventListener('click', () => loadResults().catch(showError));
function pollMemorize() {return refreshStatus();}
(async () => {
  const data = await echoRequest('/souls');
  bindSoulCombobox(document.getElementById('echo-soul-form'), data.souls, name => {
    selectedSoul = name; soulChoice.value = name; loadChats().catch(showError);
  }, () => {selectedSoul = ''; resetSelection();});
})().catch(showError);
