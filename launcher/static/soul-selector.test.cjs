const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');

function sharedContext(properties) {
  const context = vm.createContext({document: {getElementById: () => ({hidden: true})}, ...properties});
  vm.runInContext(fs.readFileSync(__dirname + '/launcher.js', 'utf8'), context);
  Object.assign(context, properties);
  return context;
}

test('server refusal preserves the page and typed soul', async () => {
  const form = {action: '/soul', soul: 'Fictional Soul', querySelector: () => null};
  const messages = [];
  const context = sharedContext({
    FormData: class {},
    fetch: async () => new Response('{"detail":"Choose a different name"}', {status: 400}),
    showLauncherMessage: message => messages.push(message),
    alert: () => assert.fail('Soul errors must remain inline'),
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
  const context = sharedContext({
    FormData: class {},
    fetch: async () => ++calls === 1
      ? new Response('{"detail":{"reason":"existing_exact","message":"Use it?"}}', {status: 409})
      : {ok: true, url: '/done'},
    confirm: () => true,
    showLauncherMessage: () => assert.fail('confirmation should retry instead of showing an error'),
    alert: () => assert.fail('No browser alerts'),
    location: {href: '/original'},
  });
  vm.runInContext(fs.readFileSync(__dirname + '/soul-selector.js', 'utf8'), context);
  await context.submitSoulForm({action: '/soul', querySelector: () => consent});
  assert.equal(calls, 2);
  assert.equal(consent.value, 'true');
  assert.equal(context.location.href, '/done');
});

test('success callback avoids a page redirect', async () => {
  let succeeded = false;
  const context = sharedContext({
    FormData: class {},
    fetch: async () => ({ok: true, url: '/done'}),
    alert: () => assert.fail('success should not alert'),
    location: {href: '/original'},
  });
  vm.runInContext(fs.readFileSync(__dirname + '/soul-selector.js', 'utf8'), context);
  await context.submitSoulForm({action: '/soul'}, () => { succeeded = true; });
  assert.equal(succeeded, true);
  assert.equal(context.location.href, '/original');
});

test('first-run conflicts stay inline without offering unsupported adoption', async () => {
  const messages = [];
  const context = sharedContext({
    FormData: class {},
    fetch: async () => new Response('{"detail":{"reason":"existing_exact","message":"Already exists"}}', {status: 409}),
    confirm: () => assert.fail('First-run routes cannot adopt an existing Soul'),
    showLauncherMessage: message => messages.push(message),
    location: {href: '/original'},
  });
  vm.runInContext(fs.readFileSync(__dirname + '/soul-selector.js', 'utf8'), context);
  for (const action of ['/owner', '/first-soul']) {
    await context.submitSoulForm({action, querySelector: () => null});
    assert.equal(context.location.href, '/original');
  }
  assert.deepEqual(messages, ['Already exists', 'Already exists']);
});
