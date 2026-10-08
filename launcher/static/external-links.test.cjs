const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');

test('miniapp links navigate on the viewing device; web links use the desktop opener', async () => {
  const opened = [];
  const context = vm.createContext({
    URL, URLSearchParams,
    location: {origin: 'http://launcher.example'},
    document: {addEventListener() {}},
    fetch: async (_path, options) => { opened.push(options.body.get('url')); return {ok: true}; },
    alert: () => assert.fail('link opening should succeed'),
  });
  vm.runInContext(fs.readFileSync(__dirname + '/external-links.js', 'utf8'), context);
  for (const type of ['click', 'auxclick']) {
    for (const href of ['miniapp://release?url=https%3A%2F%2Fprivate.example', 'http://launcher.example/iris', 'https://example.org/guide']) {
      let prevented = false;
      await context.openExternalLink({
        type, button: type === 'auxclick' ? 1 : 0,
        target: {closest: () => ({href})},
        preventDefault: () => { prevented = true; },
      });
      assert.equal(prevented, href === 'https://example.org/guide');
    }
  }
  assert.deepEqual(opened, ['https://example.org/guide', 'https://example.org/guide']);
});
