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
