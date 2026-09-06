const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');

test('server refusal preserves the page and typed soul', async () => {
  const form = {action: '/soul', soul: 'Fictional Soul'};
  const messages = [];
  const context = vm.createContext({
    FormData: class {},
    fetch: async () => ({ok: false, json: async () => ({detail: 'Choose a different name'})}),
    alert: message => messages.push(message),
    location: {href: '/original'},
  });
  vm.runInContext(fs.readFileSync(__dirname + '/soul-selector.js', 'utf8'), context);
  await context.submitSoulForm(form);
  assert.deepEqual(messages, ['Choose a different name']);
  assert.equal(context.location.href, '/original');
  assert.equal(form.soul, 'Fictional Soul');
});

test('late existing-soul conflict can be confirmed and retried', async () => {
  let calls = 0;
  const consent = {value: 'false'};
  const context = vm.createContext({
    FormData: class {},
    fetch: async () => ++calls === 1
      ? {ok: false, status: 409, json: async () => ({detail: {reason: 'existing_exact', message: 'Use it?'}})}
      : {ok: true, url: '/done'},
    confirm: () => true,
    alert: () => assert.fail('confirmation should retry instead of alerting'),
    location: {href: '/original'},
  });
  vm.runInContext(fs.readFileSync(__dirname + '/soul-selector.js', 'utf8'), context);
  await context.submitSoulForm({action: '/soul', querySelector: () => consent});
  assert.equal(calls, 2);
  assert.equal(consent.value, 'true');
  assert.equal(context.location.href, '/done');
});
