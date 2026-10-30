const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup(contextValue = '') {
  const listeners = {};
  const button = { disabled: false, addEventListener: (_event, fn) => { listeners.lookup = fn; } };
  const submit = { disabled: false };
  const status = { textContent: '' };
  const fields = {
    context_window_tokens: { value: contextValue },
    base_url: { value: 'https://openrouter.ai/api/v1' },
    chat_model: { value: 'fictional/model' },
    chat_api_key: { value: '' },
  };
  const keyless = { checked: false };
  const form = {
    action: '/settings/ai',
    addEventListener: (event, fn) => { listeners[event] = fn; },
    querySelector: selector => {
      if (selector === '[data-ai-status]') return status;
      if (selector === '[data-ai-autofill]') return button;
      if (selector === 'button[type="submit"]') return submit;
      if (selector === '[name="keyless"]') return keyless;
      const name = selector.match(/(?:data-ai-field|name)="([^"]+)"/)?.[1];
      return fields[name];
    },
  };
  let resolve;
  const requests = [];
  let reloads = 0;
  class FormData {
    constructor() { this.values = {}; }
    set(name, value) { this.values[name] = value; }
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'ai-settings.js'), 'utf8'), {
    document: { querySelectorAll: () => [form] }, FormData,
    window: { location: { reload: () => { reloads += 1; } } },
    fetch: (url, options) => {
      requests.push({ url, options });
      return new Promise(done => { resolve = result => done({ ok: true, json: async () => result }); });
    },
  });
  return { listeners, status, fields, keyless, requests, button, submit,
    resolve: result => resolve(result), reloads: () => reloads };
}

test('auto-fill changes only the unsaved input, not a populated value', async () => {
  const view = setup();
  const pending = view.listeners.lookup();
  assert.equal(view.button.disabled, true);
  assert.equal(view.requests[0].url, '/settings/ai/context');
  view.resolve({ context_window_tokens: 64000 });
  await pending;
  assert.equal(view.fields.context_window_tokens.value, 64000);
  assert.equal(view.requests.length, 1);
  assert.equal(view.reloads(), 0);
  assert.match(view.status.textContent, /Review it/);
  await view.listeners.lookup();
  assert.equal(view.requests.length, 1);
});

test('any edit, including edit-away-and-back or keyless, invalidates a lookup', async () => {
  for (const name of ['chat_model', 'base_url', 'chat_api_key', 'context_window_tokens', 'keyless']) {
    const view = setup();
    const pending = view.listeners.lookup();
    view.listeners.input();
    view.listeners.input();
    view.resolve({ context_window_tokens: 64000 });
    await pending;
    assert.equal(view.fields.context_window_tokens.value, '', name);
    assert.match(view.status.textContent, /Settings changed/);
    assert.equal(view.button.disabled, false);
  }
});

test('save is the only persistence action and reloads after success', async () => {
  const view = setup('64000');
  let prevented = false;
  const pending = view.listeners.submit({ preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(view.requests[0].url, '/settings/ai');
  assert.equal(view.submit.disabled, true);
  view.resolve({ ok: true });
  await pending;
  assert.equal(view.reloads(), 1);
  assert.equal(view.submit.disabled, false);
});
