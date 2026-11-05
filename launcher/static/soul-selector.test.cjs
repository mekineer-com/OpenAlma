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
  for (const edited of [false, true]) {
    const calls = [];
    const consent = {value: 'false'};
    const form = {action: '/soul', soul: 'Original Soul', querySelector: () => consent};
    const context = sharedContext({
      FormData: class extends Map {
        constructor(form) { super([['soul_id', form.soul], ['use_existing', consent.value]]); }
      },
      fetch: async (_url, options) => {
        calls.push(Object.fromEntries(options.body));
        if (calls.length === 1) {
          if (edited) form.soul = 'Different Soul';
          return new Response('{"detail":{"reason":"existing_exact","message":"Use it?"}}', {status: 409});
        }
        return {ok: true, url: '/done'};
      },
      confirm: () => true,
      showLauncherMessage: () => assert.fail('confirmation should retry instead of showing an error'),
      alert: () => assert.fail('No browser alerts'),
      location: {href: '/original'},
    });
    vm.runInContext(fs.readFileSync(__dirname + '/soul-selector.js', 'utf8'), context);
    await context.submitSoulForm(form);
    assert.deepEqual(calls, edited ? [
      {soul_id: 'Original Soul', use_existing: 'false'},
    ] : [
      {soul_id: 'Original Soul', use_existing: 'false'},
      {soul_id: 'Original Soul', use_existing: 'true'},
    ]);
    assert.equal(consent.value, edited ? 'false' : 'true');
    assert.equal(context.location.href, edited ? '/original' : '/done');
  }
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

function settingsHarness(active = 'Lumen', names = ['Lumen', 'Fable']) {
  function node() {
    return {value: '', hidden: true, disabled: false, inert: false, checked: false, events: {}, children: [],
      addEventListener(event, callback) { this.events[event] = callback; },
      setAttribute() {}, appendChild(child) { this.children.push(child); }};
  }
  const input = node(), ready = node(), checkbox = node(), menu = node();
  input.value = active;
  ready.hidden = !names.includes(active);
  checkbox.disabled = true;
  const fields = {'[name=soul_id]': input, '.soul-ready': ready, '.soul-options': menu,
    '.soul-new': node(), '[name=use_existing]': node()};
  const form = {...node(), action: '/soul', querySelector: selector => fields[selector.replaceAll('"', '')]};
  const messages = [], requests = [], windowEvents = {}, documentEvents = {};
  const document = {hidden: false, createElement: node, getElementById: () => checkbox,
    addEventListener(event, callback) { documentEvents[event] = callback; }};
  const context = sharedContext({document,
    window: {addEventListener(event, callback) { windowEvents[event] = callback; }},
    FormData: class extends Map {
      constructor() { super([['soul_id', input.value], ['use_existing', fields['[name=use_existing]'].value]]); }
    },
    fetch: (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject})),
    showLauncherMessage: message => messages.push(message), clearLauncherMessage() {},
    alert: () => assert.fail('Soul settings errors must remain inline'),
  });
  vm.runInContext(fs.readFileSync(__dirname + '/soul-selector.js', 'utf8'), context);
  context.bindHermesSoulSettings(form, names);
  return {context, form, input, ready, checkbox, menu, messages, requests, windowEvents, documentEvents, document,
    reply(index, settings) { requests[index].resolve(Response.json({settings})); },
    draft(name) { if (!form.inert) { input.value = name; input.events.input(); } },
    submit() { form.events.submit({preventDefault() {}}); },
    async select(name) {
      this.draft(name);
      this.submit();
      assert.equal(checkbox.disabled, true, 'pending Soul selection must disable settings');
      const request = requests.at(-1);
      assert.equal(request.url, '/soul');
      request.resolve({ok: true, url: '/hermes'});
      await settle();
    },
    toggle(value) { checkbox.checked = value; return checkbox.events.change(); },
  };
}

const settle = () => new Promise(setImmediate);

test('Soul selection is single-flight and preserves FormData until the save settles', async () => {
  const h = settingsHarness();
  h.reply(0, {});
  await settle();
  let configuredSoul = 'Lumen';
  for (const name of ['Fable', 'Lumen']) {
    h.draft(name);
    const index = h.requests.length;
    h.submit();
    assert.equal(h.form.inert, true);
    assert.equal(h.input.disabled, false, 'Inert must not disable FormData controls');
    assert.equal(h.form.querySelector('[name=use_existing]').disabled, false);
    assert.deepEqual(Object.fromEntries(h.requests[index].options.body), {soul_id: name, use_existing: 'true'});
    h.submit(); // Programmatic submit events bypass native inert handling.
    h.draft(name === 'Fable' ? 'Lumen' : 'Fable');
    assert.equal(h.input.value, name);
    assert.equal(h.requests.length, index + 1, 'A second selection POST must not be dispatched');
    configuredSoul = h.requests[index].options.body.get('soul_id');
    h.requests[index].resolve({ok: true, url: '/hermes'});
    await settle();
    assert.equal(h.form.inert, false);
    h.reply(index + 1, {});
    await settle();
    assert.equal(h.ready.hidden, false);
    assert.equal(h.input.value, configuredSoul);
    assert.equal(h.checkbox.disabled, false);
  }
});

test('Soul selection unlocks after refusal or network failure and permits retry', async () => {
  for (const networkFailure of [false, true]) {
    const h = settingsHarness();
    h.reply(0, {});
    await settle();
    h.draft('Fable');
    h.submit();
    assert.equal(h.form.inert, true);
    if (networkFailure) h.requests[1].reject(new Error('Fictional outage'));
    else h.requests[1].resolve(Response.json({detail: 'Fictional refusal'}, {status: 503}));
    await settle();
    assert.equal(h.form.inert, false);
    assert.equal(h.input.value, 'Fable');
    assert.equal(h.ready.hidden, true);
    assert.equal(h.checkbox.disabled, true);
    assert.match(h.messages.at(-1), /Fictional (outage|refusal)/);
    h.submit();
    assert.equal(h.form.inert, true);
    assert.equal(h.requests[2].options.body.get('soul_id'), 'Fable');
    h.requests[2].resolve({ok: true, url: '/hermes'});
    await settle();
    h.reply(3, {});
    await settle();
    assert.equal(h.form.inert, false);
    assert.equal(h.ready.hidden, false);
  }
});

test('New-Soul confirmation and existing-Soul retry hold the same selection lock', async () => {
  for (const accept of [false, true]) {
    const h = settingsHarness('');
    h.context.confirm = () => {
      assert.equal(h.form.inert, true);
      h.submit();
      return accept;
    };
    h.draft('NewSoul');
    h.submit();
    assert.equal(h.form.inert, false);
    assert.equal(h.requests.length, 0, 'First arrow still only confirms creation');
    h.submit();
    assert.equal(h.form.inert, true);
    assert.deepEqual(Object.fromEntries(h.requests[0].options.body), {soul_id: 'NewSoul', use_existing: 'false'});
    h.requests[0].resolve(Response.json({detail: {reason: 'existing_exact', message: 'Use it?'}}, {status: 409}));
    await settle();
    if (accept) {
      assert.equal(h.form.inert, true, 'The confirmation retry must retain the lock');
      assert.deepEqual(Object.fromEntries(h.requests[1].options.body), {soul_id: 'NewSoul', use_existing: 'true'});
      h.submit();
      assert.equal(h.requests.length, 2);
      assert.equal(h.form.querySelector('[name=use_existing]').value, 'true', 'Ignored submits must not reset confirmed consent');
      h.requests[1].resolve({ok: true, url: '/hermes'});
      await settle();
      h.reply(2, {});
      await settle();
      assert.equal(h.ready.hidden, false);
    } else {
      assert.equal(h.requests.length, 1);
      assert.equal(h.ready.hidden, true);
      assert.deepEqual(h.messages, ['Use it?']);
    }
    assert.equal(h.input.value, 'NewSoul');
    assert.equal(h.form.inert, false);
  }
});

test('Selection locking does not retarget an outstanding Mental Health PATCH', async () => {
  const h = settingsHarness();
  h.reply(0, {});
  await settle();
  const save = h.toggle(true);
  h.draft('Fable');
  h.submit();
  assert.equal(h.form.inert, true);
  h.submit();
  assert.equal(h.requests.length, 3);
  assert.equal(h.requests[1].url, '/souls/Lumen/settings');
  h.reply(1, {mental_health_addon: true});
  await save;
  assert.equal(h.checkbox.disabled, true);
  assert.equal(h.form.inert, true);
  h.requests[2].resolve({ok: true, url: '/hermes'});
  await settle();
  assert.equal(h.requests[3].url, '/souls/Fable/settings');
  h.reply(3, {mental_health_addon: false});
  await settle();
  assert.equal(h.form.inert, false);
  assert.equal(h.checkbox.checked, false);
  assert.equal(h.checkbox.disabled, false);
  assert.equal(h.requests.filter(request => request.options.method === 'PATCH').length, 1);
});

test('MH loads sparse settings without saving defaults; absent/unknown Soul stays disabled', async () => {
  for (const active of ['', 'MissingSoul']) {
    const h = settingsHarness(active);
    h.windowEvents.focus();
    assert.equal(h.checkbox.disabled, true);
    assert.equal(h.requests.length, 0);
  }
  for (const settings of [{}, {mental_health_addon: false}, {mental_health_addon: true}]) {
    const h = settingsHarness();
    assert.equal(h.checkbox.disabled, true);
    assert.equal(h.requests[0].url, '/souls/Lumen/settings');
    assert.equal(h.requests[0].options.method, 'GET');
    assert.equal(h.requests[0].options.cache, 'no-store');
    assert.equal(h.requests[0].options.body, undefined);
    h.reply(0, settings);
    await settle();
    assert.equal(h.checkbox.disabled, false);
    assert.equal(h.checkbox.checked, settings.mental_health_addon === true);
    assert.equal(h.requests.length, 1);
  }
});

test('MH PATCH captures the Soul, sends only its Boolean and uses winning sparse settings', async () => {
  for (const winning of [{}, {mental_health_addon: false}, {mental_health_addon: true}]) {
    const h = settingsHarness('Test Soul%?#', ['Test Soul%?#']);
    h.reply(0, {mental_health_addon: true});
    await settle();
    const save = h.toggle(false);
    const request = h.requests[1];
    assert.equal(h.checkbox.disabled, true);
    assert.equal(request.url, '/souls/Test%20Soul%25%3F%23/settings');
    assert.equal(request.options.method, 'PATCH');
    assert.equal(request.options.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(request.options.body), {mental_health_addon: false});
    h.reply(1, winning);
    await save;
    assert.equal(h.checkbox.checked, winning.mental_health_addon === true);
    assert.equal(h.checkbox.disabled, false);
  }
});

test('MH keeps different saved choices when switching Souls and never writes during loads', async () => {
  const h = settingsHarness();
  h.reply(0, {});
  await settle();
  const save = h.toggle(true);
  h.reply(1, {mental_health_addon: true});
  await save;
  // Choosing a menu option is still a draft until its arrow is submitted.
  h.menu.children[1].events.click();
  assert.equal(h.checkbox.disabled, true);
  assert.equal(h.input.value, 'Fable');
  h.submit();
  h.requests[2].resolve({ok: true, url: '/hermes'});
  await settle();
  h.reply(3, {mental_health_addon: false});
  await settle();
  assert.equal(h.checkbox.checked, false);
  await h.select('Lumen');
  h.reply(5, {mental_health_addon: true});
  await settle();
  assert.equal(h.checkbox.checked, true);
  assert.equal(h.requests.filter(request => request.options.method === 'PATCH').length, 1);
});

test('MH loads newly created Souls only after confirmed selector save', async () => {
  for (const active of ['', 'MissingSoul']) {
    const h = settingsHarness(active);
    if (!active) h.draft('NewSoul');
    h.submit();
    assert.equal(h.requests.length, 0, 'first arrow only confirms creation');
    assert.equal(h.checkbox.disabled, true);
    h.submit();
    assert.equal(h.requests[0].url, '/soul');
    assert.equal(h.checkbox.disabled, true);
    h.requests[0].resolve({ok: true, url: '/hermes'});
    await settle();
    assert.equal(h.requests[1].url, '/souls/' + (active || 'NewSoul') + '/settings');
    h.reply(1, {});
    await settle();
    assert.equal(h.checkbox.checked, false);
    assert.equal(h.checkbox.disabled, false);
    assert.equal(h.requests.some(request => request.options.method === 'PATCH'), false);
  }
});

test('MH ignores stale GET success/failure including an A-to-B-to-A switch', async () => {
  for (const fails of [false, true]) {
    const h = settingsHarness();
    await h.select('Fable');
    await h.select('Lumen');
    h.reply(4, {mental_health_addon: true});
    await settle();
    h.reply(2, {mental_health_addon: false});
    if (fails) h.requests[0].reject(new Error('Old outage'));
    else h.reply(0, {});
    await settle();
    assert.equal(h.checkbox.checked, true);
    assert.equal(h.checkbox.disabled, false);
    assert.deepEqual(h.messages, []);
  }
});

test('MH focus/visibility refresh saved values but never replace a pending typed Soul draft', async () => {
  const h = settingsHarness();
  h.reply(0, {});
  await settle();
  h.windowEvents.focus();
  assert.equal(h.checkbox.disabled, true);
  h.reply(1, {mental_health_addon: true});
  await settle();
  assert.equal(h.checkbox.checked, true);
  h.document.hidden = true;
  h.documentEvents.visibilitychange();
  assert.equal(h.requests.length, 2);
  h.document.hidden = false;
  h.documentEvents.visibilitychange();
  h.draft('Unsaved Soul draft');
  h.reply(2, {mental_health_addon: false});
  await settle();
  h.windowEvents.focus();
  h.documentEvents.visibilitychange();
  assert.equal(h.input.value, 'Unsaved Soul draft');
  assert.equal(h.checkbox.disabled, true);
  assert.equal(h.requests.length, 3);
  assert.equal(h.requests.every(request => request.options.method === 'GET'), true);
});

test('MH blocks a switched Soul load until PATCH settles and ignores stale save outcomes', async () => {
  for (const fails of [false, true]) {
    const h = settingsHarness();
    h.reply(0, {mental_health_addon: false});
    await settle();
    const save = h.toggle(true);
    await h.select('Fable');
    assert.equal(h.requests.length, 3, 'do not read settings ahead of the pending write');
    if (fails) h.requests[1].reject(new Error('Old save failed'));
    else h.reply(1, {mental_health_addon: true});
    await save;
    await settle();
    assert.equal(h.requests[3].url, '/souls/Fable/settings');
    h.reply(3, {});
    await settle();
    assert.equal(h.checkbox.checked, false);
    assert.equal(h.checkbox.disabled, false);
    assert.deepEqual(h.messages, []);
  }
});

test('MH switch back or focus during PATCH reads the server only after its write', async () => {
  for (const switchBack of [false, true]) {
    const h = settingsHarness();
    h.reply(0, {});
    await settle();
    const save = h.toggle(true);
    if (switchBack) {
      await h.select('Fable');
      await h.select('Lumen');
    } else h.windowEvents.focus();
    const count = h.requests.length;
    h.reply(1, {mental_health_addon: true});
    await save;
    await settle();
    assert.equal(h.requests.length, count + 1);
    assert.equal(h.requests.at(-1).url, '/souls/Lumen/settings');
    h.reply(count, {mental_health_addon: true});
    await settle();
    assert.equal(h.checkbox.checked, true);
    assert.equal(h.checkbox.disabled, false);
  }
});

test('MH focus during a failed PATCH preserves its error and refreshes the saved value', async () => {
  const h = settingsHarness();
  h.reply(0, {});
  await settle();
  const save = h.toggle(true);
  h.windowEvents.focus();
  h.windowEvents.focus();
  assert.equal(h.requests.length, 2);
  h.requests[1].resolve(Response.json({detail: 'Fictional save refusal'}, {status: 422}));
  await save;
  await settle();
  assert.equal(h.requests.length, 3);
  h.reply(2, {mental_health_addon: false});
  await settle();
  assert.equal(h.checkbox.checked, false);
  assert.equal(h.checkbox.disabled, false);
  assert.deepEqual(h.messages, ['Fictional save refusal']);
});

test('MH load/save errors stay inline and disabled until a successful refresh', async () => {
  for (const failure of ['load', 'save', 'malformed']) {
    const h = settingsHarness();
    if (failure === 'malformed') h.reply(0, {mental_health_addon: 'false'});
    else h.requests[0].resolve(Response.json({detail: 'Fictional outage'}, {status: 503}));
    await settle();
    assert.equal(h.checkbox.disabled, true);
    assert.equal(h.messages.length, 1);
    assert.match(h.messages[0], failure === 'malformed' ? /invalid Soul settings/ : /Fictional outage/);
    h.windowEvents.focus();
    h.reply(1, {mental_health_addon: true});
    await settle();
    assert.equal(h.checkbox.disabled, false);
    assert.equal(h.checkbox.checked, true);
    if (failure === 'save') {
      const save = h.toggle(false);
      h.requests[2].resolve(Response.json({detail: 'Fictional save refusal'}, {status: 422}));
      await save;
      assert.equal(h.checkbox.checked, true, 'restore the last confirmed value');
      assert.equal(h.checkbox.disabled, true);
      assert.equal(h.messages.at(-1), 'Fictional save refusal');
    }
  }
});
