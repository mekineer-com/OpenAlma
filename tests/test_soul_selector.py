import subprocess
from pathlib import Path


def test_soul_selector_node_regressions():
    script = Path(__file__).resolve().parents[1] / "launcher/static/soul-selector.test.cjs"
    subprocess.run(["node", "--test", str(script)], check=True, timeout=30)


def test_combobox_selection_preserves_pending_and_current_souls():
    script = Path(__file__).resolve().parents[1] / "launcher/static/soul-selector.js"
    subprocess.run(["node", "-e", r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
function field() {
  return {value: '', events: {}, addEventListener(k, fn) { this.events[k] = fn; },
    replaceChildren(...options) { this.options = options; }};
}
function comboField() {
  return {...field(), hidden:true, children:[], setAttribute(){}, reportValidity(){this.invalid=true;}, appendChild(node){this.children.push(node);}};
}
global.document = {createElement: comboField};
(async () => {
const settle = () => new Promise(setImmediate);
const nodes = Object.fromEntries(['[name=soul_id]', '.soul-options', '.soul-ready', '.soul-new', '[name=use_existing]'].map(key=>[key,comboField()]));
const form = {...field(), querySelector:key=>nodes[key]};
let saved=[], changed=0;
global.submitSoulForm = async (_form, done)=>done();
nodes['[name=soul_id]'].value='MissingSoul'; nodes['.soul-ready'].hidden=false;
bindSoulCombobox(form, ['KnownSoul'], name=>saved.push(name), ()=>changed++);
form.events.submit({preventDefault(){}});
assert.equal(nodes['.soul-new'].hidden,false);
form.events.submit({preventDefault(){}});
await settle();
assert.equal(nodes['.soul-new'].hidden,true);
assert.equal(nodes['.soul-ready'].hidden,false);
assert.deepEqual(nodes['.soul-options'].children.map(node=>node.textContent),['KnownSoul','MissingSoul']);
assert.deepEqual(saved,[]); assert.equal(changed,0);
form.events.submit({preventDefault(){}});
await settle();
assert.equal(nodes['[name=use_existing]'].value,'true');
assert.equal(nodes['.soul-new'].hidden,true); assert.deepEqual(saved,[]);
nodes['[name=soul_id]'].value='NewSoul'; nodes['[name=soul_id]'].events.input();
form.events.submit({preventDefault(){}});
assert.deepEqual(saved, []); assert.equal(nodes['.soul-new'].hidden,false);
form.events.submit({preventDefault(){}});
await settle();
assert.deepEqual(saved,['NewSoul']); assert.equal(nodes['.soul-ready'].hidden,false);
nodes['.soul-options'].children[0].events.click();
assert.equal(nodes['[name=soul_id]'].value,'KnownSoul'); assert.equal(changed,2);
form.events.submit({preventDefault(){}});
await settle();
assert.deepEqual(saved,['NewSoul','KnownSoul']);
const replies=[];
global.submitSoulForm = (_form, done)=>new Promise(resolve=>replies.push(()=>{done(); resolve();}));
nodes['[name=soul_id]'].value='LateSoul'; nodes['[name=soul_id]'].events.input();
form.events.submit({preventDefault(){}}); form.events.submit({preventDefault(){}});
assert.equal(form.inert,true);
form.events.submit({preventDefault(){}});
assert.equal(replies.length,1);
replies[0](); await settle();
assert.equal(form.inert,false);
assert.deepEqual(saved,['NewSoul','KnownSoul','LateSoul']);
nodes['[name=soul_id]'].value='CurrentSoul'; nodes['[name=soul_id]'].events.input();
form.events.submit({preventDefault(){}}); form.events.submit({preventDefault(){}});
form.events.submit({preventDefault(){}});
assert.equal(replies.length,2);
assert.equal(form.inert,true);
replies[1](); await settle();
assert.equal(form.inert,false);
assert.deepEqual(saved,['NewSoul','KnownSoul','LateSoul','CurrentSoul']);
assert.equal(nodes['[name=soul_id]'].value,'CurrentSoul');
assert.equal(nodes['.soul-ready'].hidden,false);
})().catch(error=>{console.error(error); process.exitCode=1;});
''', str(script)], check=True)
