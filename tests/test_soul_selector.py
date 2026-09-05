import subprocess
from pathlib import Path


def test_native_selection_and_typed_consent():
    script = Path(__file__).resolve().parents[1] / "launcher/static/soul-selector.js"
    subprocess.run(["node", "-e", r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
global.Option = function(text, value) { return {text, value}; };
function field() {
  return {value: '', events: {}, addEventListener(k, fn) { this.events[k] = fn; },
    replaceChildren(...options) { this.options = options; }};
}
const input = field(), select = field(), consent = field();
const picker = createSoulSelector(input, select, consent);
let prompts = 0, accepted = false;
global.confirm = () => { prompts++; return accepted; };
picker.setSouls(['Codexia', 'Echo']);
select.value = 'Codexia'; select.events.change();
assert.equal(input.value, 'Codexia');
assert.equal(picker.prepareSubmit(), true);
assert.equal(consent.value, 'true');
assert.equal(prompts, 0);
input.events.input();
assert.equal(picker.prepareSubmit(), false);
assert.equal(consent.value, 'false');
accepted = true;
assert.equal(picker.prepareSubmit(), true);
input.value = 'New Soul'; input.events.input();
assert.equal(picker.prepareSubmit(), true);
assert.equal(consent.value, 'false');
assert.equal(prompts, 2);
select.value = 'Echo'; select.events.change();
picker.setSouls([]);
assert.equal(input.value, 'Echo');
assert.equal(consent.value, 'false');
''', str(script)], check=True)
