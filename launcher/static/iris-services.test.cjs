const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');

const source = fs.readFileSync(__dirname + '/iris-services.js', 'utf8');
const installation = {
  device_session_id: 'disposable-phone', display_name: 'Test Phone', metadata_known: true,
  host_package: 'com.mentra.mentra.openalma', state: 'ready', status_label: 'Host ready',
  action_kind: 'start', action_label: 'Install', startable: true,
};
const ready = {
  running: false, installations: [installation], available_package: 'test-iris', available_version: '0.1.0',
  setup: {enabled: true, ready: true, rows: []},
};

test('Services preserves rows and Rename drafts through outages, then restores current actions', async () => {
  const name = {disabled: false, setAttribute() {}};
  const save = {disabled: false};
  const input = {value: 'Unsaved name'};
  const status = {};
  const detail = {};
  let install, forget;
  const actions = {
    set innerHTML(value) {
      this.html = value;
      install = /type="submit"/.test(value) ? {disabled: /type="submit" disabled/.test(value)} : null;
      forget = /data-forget/.test(value) ? {disabled: /data-forget[^>]* disabled/.test(value)} : null;
    },
    get innerHTML() { return this.html; },
    querySelector: () => forget,
  };
  const elements = new Map([
    ['.iris-name-view button', name], ['.iris-name', name], ['input', input],
    ['button[type="submit"]', save], ['form', {hidden: false}],
    ['.iris-status', status], ['.iris-detail', detail], ['.iris-soul', {}], ['.iris-actions', actions],
  ]);
  const row = {
    dataset: {irisInstallation: installation.device_session_id},
    querySelector: selector => elements.get(selector),
    querySelectorAll: () => [name, save, install, forget].filter(Boolean),
    remove() { this.removed = true; },
  };
  const parent = {parentNode: {querySelectorAll: () => [row]}};
  let polls = 0, rejectRequest;
  const context = vm.createContext({
    document: {querySelector: () => parent}, esc: String, confirm: () => true, alert() {},
    pollStatus: () => { polls++; }, fetch: () => new Promise((_resolve, reject) => { rejectRequest = reject; }),
  });
  vm.runInContext(source, context);
  context.renderIrisInstallations(ready);
  assert.equal(install.disabled, false);
  assert.equal(forget.disabled, false);
  const pendingForget = forget.onclick();
  context.renderIrisInstallations({detail: 'MCP unavailable'});
  assert.equal(row.removed, undefined);
  assert.equal(input.value, 'Unsaved name');
  assert.equal(status.textContent, 'Status unavailable');
  assert.equal(detail.textContent, 'MCP unavailable');
  for (const button of [name, save, install, forget]) assert.equal(button.disabled, true);
  rejectRequest(new Error('MCP unavailable'));
  await pendingForget;
  assert.equal(forget.disabled, true);
  assert.equal(polls, 1);
  context.renderIrisInstallations(ready);
  for (const button of [name, save, install, forget]) assert.equal(button.disabled, false);
  assert.equal(input.value, 'Unsaved name');
  assert.equal(status.textContent, 'Host ready');
  context.renderIrisInstallations({...ready, blocked: true});
  assert.equal(install.disabled, true);
  assert.equal(context.irisInstallDisabled({}), true);
  for (const patch of [{ready: false}, {starting: true}, {state: 'stopping'},
                       {setup: {enabled: false, ready: true}}, {setup: {enabled: true, ready: false}}]) {
    assert.equal(context.irisInstallDisabled({...ready, ...patch}), true);
  }
  context.renderIrisInstallations({...ready, installations: [{...installation, action_label: 'Update',
    repair_available: true, update_available: true}]});
  assert.match(actions.innerHTML, />Update<\/button>/);
  assert.equal(install.disabled, false);
  context.renderIrisInstallations({...ready, blocked: true, installations: [{...installation, action_label: 'Update',
    repair_available: true, update_available: true}]});
  assert.equal(install.disabled, true);
  context.renderIrisInstallations({...ready, installations: [{...installation, action_label: 'Repair',
    repair_available: true, installed_version: '0.2.0'}]});
  assert.equal(install, null);
  assert.match(actions.innerHTML, /Setup<\/a>/);
  context.renderIrisInstallations({...ready, installations: []});
  assert.equal(row.removed, true);
});

test('Setup poll applies blocks and outages even with Rename open, without disabling installer cancellation', async () => {
  const stock = {}, install = {}, rename = {}, forget = {}, cancel = {disabled: false};
  const address = {disabled: false}, busyHint = {hidden: true}, installerStatus = {};
  const progress = {hidden: false}, cancelControls = {hidden: false};
  const actionError = {textContent: 'Invalid address'};
  const elements = new Map([
    ['iris-action-error', actionError], ['iris-installer-status', installerStatus], ['iris-address-busy', busyHint],
    ['iris-installer-progress', progress], ['iris-cancel-controls', cancelControls],
  ]);
  const selectors = new Map([
    ['form[action="/iris/install"] button', install], ['.iris-rename button', rename],
    ['form[data-forget] button', forget], ['[data-status]', {}],
  ]);
  const item = {dataset: {deviceSessionId: installation.device_session_id}, querySelector: s => selectors.get(s),
    querySelectorAll: s => s === 'form[action="/iris/install"] button' ? [install] : []};
  let poll, next = ready, responseOK = true, open = true, reloads = 0;
  const context = vm.createContext({
    document: {
      getElementById: id => elements.get(id),
      querySelectorAll: s => {
        if (s === 'form[action="/iris/install"] button') return [stock, install];
        if (s === '#iris-installations form button') return [install, rename, forget];
        if (s === 'form[action^="/iris/"]') return [];
        assert.equal(s, '[data-device-session-id]');
        return [item];
      },
      querySelector: s => s === '.iris-address button' ? address : s === '.iris-repair' ? null : open,
    },
    setInterval: callback => { poll = callback; },
    fetch: async () => {
      if (next instanceof Error) throw next;
      return {ok: responseOK, json: async () => next};
    },
    location: {reload: () => { reloads++; }},
  });
  const template = fs.readFileSync(__dirname + '/../templates/iris.html', 'utf8');
  const inlineStart = template.indexOf('const initialStatus = ');
  const included = template.slice(0, inlineStart).match(/<script src="\/static\/iris-services\.js"><\/script>/);
  assert.ok(included, 'Setup must load the real shared guard before its inline script');
  vm.runInContext(fs.readFileSync(__dirname + '/iris-services.js', 'utf8'), context);
  assert.equal(typeof context.irisInstallDisabled, 'function');
  const boot = template.slice(inlineStart, template.indexOf('{% if show_installer and iris.running', inlineStart))
    .replace('{{ iris|tojson }}', JSON.stringify(ready))
    .replace("{{ (selected_installation.device_session_id if selected_installation else '')|tojson }}", JSON.stringify(installation.device_session_id));
  vm.runInContext(boot, context);
  const signature = context.statusSignature(ready);
  assert.notEqual(context.statusSignature({...ready, blocked: true}), signature);
  assert.notEqual(context.statusSignature({...ready, available_package: 'changed'}), signature);
  await poll();
  assert.equal(progress.hidden, true);
  assert.equal(cancelControls.hidden, true);
  for (const button of [stock, install, rename, forget]) assert.equal(Boolean(button.disabled), false);
  for (const block of [{blocked: true, detail: 'Free installer port 6789'},
                       {setup: {enabled: true, ready: false, reason: 'Restart memU Server'}}]) {
    next = {...ready, ...block};
    await poll();
    assert.equal(stock.disabled, true);
    assert.equal(install.disabled, true);
    assert.equal(installerStatus.textContent, block.detail || block.setup.reason);
    assert.equal(address.disabled, false);
    assert.equal(reloads, 0);
  }
  for (const outage of [{detail: 'MCP unavailable'}, new Error('Offline')]) {
    cancelControls.hidden = false;
    next = outage;
    await poll();
    for (const button of [stock, install, rename, forget]) assert.equal(button.disabled, true);
    assert.equal(cancel.disabled, false);
    assert.equal(cancelControls.hidden, false);
  }
  next = ready;
  responseOK = false;
  await poll();
  assert.equal(install.disabled, true);
  responseOK = true;
  await poll();
  for (const button of [stock, install, rename, forget]) assert.equal(Boolean(button.disabled), false);
  for (const busy of [{running: true}, {starting: true}, {stuck: true}, {orphaned: true}]) {
    next = {...ready, ...busy};
    await poll();
    assert.equal(address.disabled, true);
    assert.equal(busyHint.hidden, false);
    assert.equal(install.disabled, true);
  }
  next = new Error('Offline');
  await poll();
  assert.equal(address.disabled, true);
  next = {...ready, blocked: true};
  await poll();
  assert.equal(address.disabled, false);
  assert.equal(busyHint.hidden, true);
  next = {...ready, installations: [{...installation, host_reporting: true}]};
  await poll();
  assert.equal(forget.disabled, true);
  next = {...ready, installations: []};
  await poll();
  for (const button of [install, rename, forget]) assert.equal(button.disabled, true);
  next = ready;
  open = false;
  await poll();
  assert.equal(reloads, 0);
  next = {...ready, blocked: true};
  await poll();
  assert.equal(reloads, 1);
  assert.equal(actionError.textContent, 'Invalid address');
});
