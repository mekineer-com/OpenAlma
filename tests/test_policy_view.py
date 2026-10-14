from pathlib import Path
import json
import re
import subprocess

import pytest


jinja2 = pytest.importorskip("jinja2")


@pytest.mark.parametrize("configured", [True, False])
def test_hermes_recovery_preserves_policy_dom_and_binds_soul_once(configured):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(
        Path(__file__).resolve().parents[1] / "launcher/templates"), autoescape=True)
    args = dict(services=[], chats=[], visible_chats=[], excluded_chats=[],
                policies=("full", "listen_only", "excluded"), active_soul="TestSoul",
                channels_configured=configured, soul_ids=[], editable_configs=[],
                apps_root="", needs_setup=False)
    offline = env.get_template("hermes.html").render(**args, soul_error="Fictional outage")
    ready = env.get_template("hermes.html").render(**{**args, "soul_ids": ["TestSoul"]})
    script = next(code for code in re.findall(r"<script>(.*?)</script>", offline, re.S)
                  if "function syncMemorize" in code)
    subprocess.run(["node", "-e", r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {script, readyHtml, configured} = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
let tick, cleared = 0, reloads = 0, liveForm = null, replacements = 0, phase = 'offline', lateSouls, pageRequests = 0;
const policy = {routing:'listen_only', memorize:false, defaultPolicy:'full'};
const policyBefore = {...policy};
const bindings = [], deferred = [];
const region = {replaceWith(node) { liveForm=node.form; replacements++; }};
const element = {hidden:true, addEventListener(){}};
const document = {getElementById(id) {
  if(id === 'channels-soul-form') return liveForm;
  if(id === 'channels-soul-selector') return region;
  if(id === 'policy-form') return policy;
  return element;
}};
class DOMParser {
  parseFromString(html, type) {
    assert.equal(type, 'text/html');
    const form = html.includes('id="channels-soul-form"') ? {value:'TestSoul'} : null;
    return {getElementById() {return {form, querySelector(){return form;}};}};
  }
}
const context = {
 document, DOMParser, URLSearchParams, console,
 window:{location:{search:''}}, location:{href:'/hermes', reload(){reloads++; Object.assign(policy,{routing:'excluded',memorize:true});}},
 bindSoulCombobox(form,names,saved){bindings.push({form,names,saved});},
 setInterval(fn){tick=fn;return 41;}, clearInterval(id){assert.equal(id,41);cleared++;},
 fetch: async(url) => {
   if(url === '/souls') {
     if(phase === 'late-souls') return new Promise(resolve=>{lateSouls=resolve;});
     return {ok:phase !== 'offline', json:async()=>({souls:['TestSoul']})};
   }
   assert.equal(url,'/hermes');
   pageRequests++;
   if(phase === 'late') return new Promise(resolve=>deferred.push(resolve));
   return {ok:phase !== 'bad-http', text:async()=>phase === 'bad-page' ? '<div>Configuration unavailable</div>' : readyHtml};
 },
};
vm.runInNewContext(script, context);
const poll = async()=>{await tick();await new Promise(setImmediate);};
(async()=>{
 await poll(); assert.equal(bindings.length,0); assert.equal(cleared,0);
 phase='bad-http'; await poll(); assert.equal(bindings.length,0); assert.equal(reloads,0); assert.deepEqual(policy,policyBefore);
 phase='bad-page'; await poll(); assert.equal(bindings.length,0); assert.equal(cleared,0);
 phase='late-souls'; const delayed=poll(); await new Promise(setImmediate);
 phase='late'; const first=poll(); const second=poll(); await new Promise(setImmediate);
 assert.equal(deferred.length,2);
 deferred[0]({ok:true,text:async()=>readyHtml}); await first;
 assert.equal(reloads,0); assert.deepEqual(policy,policyBefore);
 assert.equal(bindings.length,1); assert.equal(replacements,1); assert.equal(cleared,1);
 assert.equal(bindings[0].names.join(','),'TestSoul');
 liveForm.value='UnsavedSoul';
 deferred[1]({ok:true,text:async()=>readyHtml}); await second;
 assert.equal(liveForm.value,'UnsavedSoul'); assert.equal(bindings.length,1); assert.equal(replacements,1);
 const pagesBefore=pageRequests; phase='ready';
 lateSouls({ok:true,json:async()=>({souls:['TestSoul']})}); await delayed;
 assert.equal(pageRequests,pagesBefore); assert.equal(liveForm.value,'UnsavedSoul');
 if(configured) assert.equal(bindings[0].saved,undefined);
 else {assert.equal(typeof bindings[0].saved,'function'); bindings[0].saved(); assert.equal(context.location.href,'/hermes');}
 assert.deepEqual(policy,policyBefore);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''], input=json.dumps({"script": script, "readyHtml": ready, "configured": configured}),
        text=True, encoding="utf-8", check=True, timeout=15)
    for html in (offline, ready):
        section = html.split('<div id="channels-soul-selector">', 1)[1].split('</div>', 1)[0]
        assert 'action="/policy"' not in section and 'id="pair-whatsapp"' not in section


def test_excluded_whatsapp_chats_are_collapsed():
    template_dir = Path(__file__).resolve().parents[1] / "launcher" / "templates"
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir),
        autoescape=True,
    )
    html = env.get_template("hermes.html").render(
        services=[],
        chats=[
            {"id": "visible@g.us", "name": "Visible", "type": "group", "policy": "full", "memorize": True},
            {
                "id": "excluded@g.us",
                "name": "Hidden",
                "type": "group",
                "policy": "excluded",
                "memorize": False,
            },
        ],
        visible_chats=[
            {"id": "visible@g.us", "name": "Visible", "type": "group", "policy": "full", "memorize": True},
        ],
        excluded_chats=[
            {
                "id": "excluded@g.us",
                "name": "Hidden",
                "type": "group",
                "policy": "excluded",
                "memorize": False,
            },
        ],
        policies=("full", "listen_only", "excluded"),
            active_soul="Siri",
            channels_configured=True,
        soul_ids=["Siri"],
        editable_configs=[],
        apps_root="",
        needs_setup=False,
    )

    main_table = html.split('<details class="excluded-chats">', 1)[0]
    excluded_section = html.split('<details class="excluded-chats">', 1)[1]
    assert "Visible" in main_table
    assert "Hidden" not in main_table
    assert "<summary>Excluded (1)</summary>" in excluded_section
    assert "Hidden" in excluded_section
    assert "New rows default to" in html
    assert '<option value="excluded" selected>excluded</option>' in html


def test_empty_policy_view_shows_actual_channel_directory_path():
    template_dir = Path(__file__).resolve().parents[1] / "launcher" / "templates"
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir),
        autoescape=True,
    )
    html = env.get_template("hermes.html").render(
        services=[],
        chats=[],
        visible_chats=[],
        excluded_chats=[],
        channel_directory_path="/tmp/hermes-channels/channel_directory.json",
        policies=("full", "listen_only", "excluded"),
            active_soul="Siri",
            channels_configured=True,
        soul_ids=["Siri"],
        editable_configs=[],
        apps_root="",
        needs_setup=False,
    )

    assert "No WhatsApp chats in" in html
    assert "/tmp/hermes-channels/channel_directory.json" in html
    assert "New rows default to" in html
