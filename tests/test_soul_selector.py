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
function comboField() {
  return {...field(), hidden:true, children:[], setAttribute(){}, appendChild(node){this.children.push(node);}};
}
global.document = {createElement: comboField};
const nodes = Object.fromEntries(['[name=soul_id]', '.soul-options', '.soul-ready', '.soul-new', '[name=use_existing]'].map(key=>[key,comboField()]));
const form = {...field(), querySelector:key=>nodes[key]};
let saved=[], changed=0;
global.submitSoulForm = (_form, done)=>done();
nodes['[name=soul_id]'].value='MissingSoul'; nodes['.soul-ready'].hidden=false;
bindSoulCombobox(form, ['KnownSoul'], name=>saved.push(name), ()=>changed++);
form.events.submit({preventDefault(){}});
assert.equal(nodes['.soul-new'].hidden,false);
form.events.submit({preventDefault(){}});
assert.equal(nodes['.soul-new'].hidden,true);
assert.equal(nodes['.soul-ready'].hidden,false);
assert.deepEqual(nodes['.soul-options'].children.map(node=>node.textContent),['KnownSoul','MissingSoul']);
assert.deepEqual(saved,[]); assert.equal(changed,0);
form.events.submit({preventDefault(){}});
assert.equal(nodes['[name=use_existing]'].value,'true');
assert.equal(nodes['.soul-new'].hidden,true); assert.deepEqual(saved,[]);
nodes['[name=soul_id]'].value='NewSoul'; nodes['[name=soul_id]'].events.input();
form.events.submit({preventDefault(){}});
assert.deepEqual(saved, []); assert.equal(nodes['.soul-new'].hidden,false);
form.events.submit({preventDefault(){}});
assert.deepEqual(saved,['NewSoul']); assert.equal(nodes['.soul-ready'].hidden,false);
nodes['.soul-options'].children[0].events.click();
assert.equal(nodes['[name=soul_id]'].value,'KnownSoul'); assert.equal(changed,2);
form.events.submit({preventDefault(){}});
assert.deepEqual(saved,['NewSoul','KnownSoul']);
const replies=[];
global.submitSoulForm = (_form, done)=>replies.push(done);
nodes['[name=soul_id]'].value='LateSoul'; nodes['[name=soul_id]'].events.input();
form.events.submit({preventDefault(){}}); form.events.submit({preventDefault(){}});
nodes['[name=soul_id]'].value='CurrentSoul'; nodes['[name=soul_id]'].events.input();
form.events.submit({preventDefault(){}}); form.events.submit({preventDefault(){}});
replies[1](); replies[0]();
assert.deepEqual(saved,['NewSoul','KnownSoul','CurrentSoul']);
assert.equal(nodes['[name=soul_id]'].value,'CurrentSoul');
assert.equal(nodes['.soul-ready'].hidden,false);
nodes['[name=soul_id]'].events.input();
form.events.submit({preventDefault(){}}); form.events.submit({preventDefault(){}});
replies[3](); replies[2]();
assert.deepEqual(saved,['NewSoul','KnownSoul','CurrentSoul','CurrentSoul']);
assert.equal(nodes['.soul-ready'].hidden,false);
''', str(script)], check=True)
