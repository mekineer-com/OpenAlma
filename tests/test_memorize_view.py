import subprocess
import json
import re
from pathlib import Path

import pytest


jinja2 = pytest.importorskip("jinja2")


def _render(
    memorize: dict | list,
    not_installed_services: list[dict] | None = None,
    services: list[dict] | None = None,
    template_name: str = "index.html",
    editable_configs: list[dict] | None = None,
) -> str:
    template_dir = Path(__file__).resolve().parents[1] / "launcher" / "templates"
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir),
        autoescape=True,
    )
    return env.get_template(template_name).render(
        services=services or [],
        not_installed_services=not_installed_services or [],
        chats=[],
        visible_chats=[],
        excluded_chats=[],
        policies=("full", "listen_only", "excluded"),
        active_soul="Fictional Soul",
        soul_ids=["Fictional Soul"],
        editable_configs=editable_configs or [],
        host_prerequisites={"rows": []},
        apps_root="",
        needs_setup=False,
        memorize=memorize if isinstance(memorize, list) else ([{"soul_id": "Fictional Soul", **memorize}] if memorize else []),
        owner_id="Fictional User",
        owner_error="",
        channels_configured=True,
        channels_error="",
        soul_error="",
    ).split('<script>', 1)[0]


def test_memorize_gauge_under_threshold():
    html = _render({
        "summed_unmemorized_tokens": 2000,
        "threshold": 8000,
        "pct": 25,
        "sleep_gap_ready": False,
        "computed_at": "2026-06-11T10:00:00+00:00",
        "context_load_tokens": 43567,
        "context_load_has_chat": True,
    })
    assert "Memorize: 2,000 / 8,000 (25%)" in html
    assert 'style="width: 25%"' in html
    assert "waiting for sleep-gap" not in html
    assert 'title="Back to Services"' not in html
    assert 'class="memorize-row"' in html and 'class="context-load"' in html
    assert "&asymp; 43,567 tokens" in html
    assert 'popovertarget="info:context:Fictional Soul"' in html
    assert 'class="info-text" popover' in html
    assert 'onpointerleave="if (event.pointerType === \'mouse\') this.nextElementSibling.hidePopover()"' in html
    assert 'width: 1.375em; height: 1.375em' in html
    assert 'Context load<span class="info-icon">i</span></button>' in html
    pressure = html.split('<div class="memorize-pressure">', 1)[1].split('<div class="context-load">', 1)[0]
    assert 'Memorize-eligible at' in pressure
    assert "Actual prepared prompts are checked separately." in html
    assert "@media (max-width: 40rem)" in html
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html
    assert "Conservative forecast" not in html
    assert "memory only" not in html.split('class="context-load"', 1)[1].split("</div>", 1)[0]
    empty = _render({"threshold": 8000, "summed_unmemorized_tokens": 0, "pct": 0,
                     "context_load_tokens": 12000, "context_load_has_chat": False})
    assert "Memorize: 0 / 8,000" in empty and "tokens<br>(memory only)" in empty
    assert 'Snapshot' not in empty
    settings = html.split('<summary>Context window settings</summary>', 1)[1].split('</details>', 1)[0]
    assert 'llm.context_window_tokens' in settings and 'claude_code_context_window_tokens' in settings
    assert "Memorize: error" not in empty


def test_initial_and_polled_setup_actions_match():
    cases = [
        {"name": "iris-server", "action_kind": "install", "action_label": "Install"},
        {"name": "iris-server", "action_kind": "install", "action_label": "Update"},
        {"name": "iris-server", "action_kind": "start", "action_label": "Update"},
        {"name": "iris-server", "action_kind": "stop", "action_label": "Cancel"},
        {"name": "iris-server", "install_enabled": False},
        {"name": "iris-server", "install_running": True, "force_stoppable": True},
        {"name": "iris-server", "state": "stopping"},
        {"name": "channels-daemon", "startable": True},
        {"name": "channels-daemon", "action_kind": "install", "action_label": "Install"},
        {"name": "channels-daemon", "action_kind": "settings", "startable": False},
        {"name": "memu-server", "action_kind": "recover"},
        {"name": "channels-daemon", "running": True, "stoppable": True, "pairing_required": True},
    ]
    script = r"""
const fs=require('fs'),vm=require('vm'); const text=fs.readFileSync(process.argv[1],'utf8');
vm.runInThisContext(fs.readFileSync(require('path').join(require('path').dirname(process.argv[1]), '../static/launcher.js'), 'utf8'));
vm.runInThisContext(fs.readFileSync(require('path').join(require('path').dirname(process.argv[1]), '../static/iris-services.js'), 'utf8'));
vm.runInThisContext(text.slice(text.indexOf('function actionHtml'),text.indexOf('async function openService')));
console.log(JSON.stringify(JSON.parse(process.argv[2]).map(row=>actionHtml(row.name,row))));
"""
    path = Path(__file__).resolve().parents[1] / "launcher/templates/index.html"
    polled = json.loads(subprocess.check_output(["node", "-e", script, str(path), json.dumps(cases)], text=True))
    labels = lambda html: re.findall(r">([^<>]+)</(?:button|a)>" , html)
    for row, dynamic in zip(cases, polled):
        initial = _render({}, services=[row]).split('<td class="svc-actions">', 1)[1].split("</td>", 1)[0]
        assert labels(initial) == labels(dynamic)
        if row.get("action_kind") in {"install", "recover"} and row["name"] != "iris-server":
            assert '<form class="inline"' in initial and '<form class="inline"' in dynamic
        if row["name"] == "iris-server":
            assert "Stock Install" not in initial + dynamic
            assert 'action="/iris/install"' not in initial + dynamic
    assert labels(polled[2]) == ["QR", "Setup"]
    assert 'href="/hermes?pair=1"' in polled[-1]


def test_install_meter_is_in_status_and_matches_polled_rendering():
    progress = {"step_number": 2, "total_steps": 5, "elapsed_seconds": 65}
    html = _render({}, services=[{
        "name": "channels-daemon", "install_running": True, "install_setup": True,
        "install_progress": progress, "detail": "Installing dependencies",
    }])
    status = html.split('<td class="svc-status">', 1)[1].split('</td>', 1)[0]
    actions = html.split('<td class="svc-actions">', 1)[1].split('</td>', 1)[0]
    assert '<progress class="install-progress"' in status
    assert 'max="5" value="1"' in status
    assert 'Step 2 of 5' in status and '1:05 elapsed' in status
    assert 'Installing dependencies' in status
    assert 'id="info:service:channels-daemon"' in status
    assert '<div class="svc-detail">Installing dependencies</div>' not in status
    assert 'spinner' not in actions and '>Setup</a>' in actions
    path = Path(__file__).resolve().parents[1] / "launcher/static/launcher.js"
    script = "const fs=require('fs'),vm=require('vm');vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));console.log(installProgressHtml(JSON.parse(process.argv[2])));"
    polled = subprocess.check_output(["node", "-e", script, str(path), json.dumps(progress)], text=True)
    assert 'max="5" value="1"' in polled and 'Step 2 of 5' in polled and '1:05 elapsed' in polled
    template = path.parent.parent / "templates/index.html"
    polling = r"""
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const text=fs.readFileSync(process.argv[2],'utf8'), start=text.indexOf('function pollStatus');
vm.runInThisContext(text.slice(start,text.indexOf('\n{% for s',start)));
const cells={'.svc-status':{querySelector:()=>null},'.svc-actions':{}}, row={dataset:{runtime:'false',installing:'true'},querySelector:key=>cells[key]};
global.document={querySelector:()=>row};global.pendingStarts={};global.pendingStops={};global.actionHtml=()=>'';
let reloads=0,ok=true,url,payload={install_running:true,install_setup:true,detail:'Installing dependencies',install_progress:{step_number:2,total_steps:5,elapsed_seconds:65}};
global.location={reload:()=>reloads++};global.fetch=async value=>{url=value;return {ok,json:async()=>payload};};
async function poll(){pollStatus('atomic');await new Promise(setImmediate);}
(async()=>{
  await poll();assert.equal(url,'/install/atomic/status');assert.equal(reloads,0);
  assert.ok(cells['.svc-status'].innerHTML.includes('Step 2 of 5'));
  assert.ok(cells['.svc-status'].innerHTML.includes('info:service:atomic'));
  const shown=cells['.svc-status'].innerHTML;
  cells['.svc-status'].querySelector=()=>({});
  payload.detail='Changed while reading';await poll();
  assert.equal(cells['.svc-status'].innerHTML,shown);
  cells['.svc-status'].querySelector=()=>null;
  ok=false;await poll();assert.equal(reloads,0);
  ok=true;payload={install_running:false};await poll();assert.equal(reloads,1);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    subprocess.run(["node", "-e", polling, str(path), str(template)], check=True)


def test_memorize_gauge_over_threshold_shows_sleep_gap_badge():
    html = _render({
        "summed_unmemorized_tokens": 12900,
        "threshold": 8000,
        "pct": 161,
        "sleep_gap_ready": False,
        "computed_at": "2026-06-11T10:00:00+00:00",
    })
    assert "Memorize: 12,900 / 8,000 (161%)" in html
    assert 'style="width: 100%"' in html
    assert "waiting for sleep-gap" in html


def test_iris_setup_names_open_existing_rename_and_live_fallback_is_readonly():
    template_dir = Path(__file__).resolve().parents[1] / "launcher/templates"
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir), autoescape=True)
    installations = [
        {"device_session_id": "confirmed-app", "display_name": "Test Phone",
         "host_package": "com.mentra.mentra.openalma", "host_version": "3.2.1",
         "package_name": "com.openalma.mentra", "action_kind": "start",
         "action_label": "Install", "startable": True},
        {"device_session_id": "forgotten-app", "display_name": "Unreported app",
         "metadata_known": False, "active": True, "status_label": "Connected"},
    ]
    context = dict(
        iris={"installations": installations},
        iris_setup={"ready": True, "rows": []},
        iris_connection={"base_url": "http://fixture.invalid"},
    )
    html = env.get_template("iris.html").render(**context, selected_installation=installations[0])
    confirmed = html.split('data-device-session-id="confirmed-app"', 1)[1].split("</li>", 1)[0]
    assert '<details class="iris-rename">' in confirmed
    assert 'aria-label="Rename Test Phone">Test Phone</summary>' in confirmed
    assert 'action="/iris/installations/confirmed-app/rename"' in confirmed
    assert 'action="/iris/install"' in confirmed
    assert '<summary>Rename</summary>' not in html
    assert '>Install Iris in Stock Mentra</button>' not in html
    assert 'id="iris-stock-installation"' not in html
    assert 'data-device-session-id="forgotten-app"' not in html
    html = env.get_template("iris.html").render(**context, selected_installation=installations[1])
    live = html.split('data-device-session-id="forgotten-app"', 1)[1].split("</li>", 1)[0]
    assert 'data-device-session-id="confirmed-app"' not in html
    assert 'title="App details unavailable (version unknown), Iris not yet reported">Unreported app</strong>' in live
    assert "<details" not in live
    assert "<form" not in live


def test_iris_status_signature_ignores_json_key_order():
    template = (Path(__file__).resolve().parents[1] / "launcher/templates/iris.html").read_text()
    function = template.split("function statusSignature(status) {", 1)[1].split("const initialSignature", 1)[0]
    script = "const selectedDevice = ''; function statusSignature(status) {" + function + r"""
const assert = require('assert');
const status = {setup: {ready: true, reason: 'Ready', step: 'ready',
  rows: [{label: 'Server', state: 'ready', detail: 'Ready'}]}, installations: []};
const sorted = JSON.parse(JSON.stringify(status, ['setup', 'installations', 'detail', 'enabled', 'label', 'ready', 'reason', 'rows', 'state', 'step']));
assert.equal(statusSignature(status), statusSignature(sorted));
sorted.setup.rows[0].state = 'failure';
assert.notEqual(statusSignature(status), statusSignature(sorted));
"""
    subprocess.run(["node", "-e", script], check=True, timeout=10)
    check = Path(__file__).resolve().parents[1] / "launcher/static/iris-services.test.cjs"
    subprocess.run(["node", str(check)], check=True, timeout=10)


def test_polled_iris_subrows_link_setup_to_their_own_app():
    path = Path(__file__).resolve().parents[1] / "launcher/static/iris-services.js"
    subprocess.run(["node", "-e", r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const installations = [
  {device_session_id: 'stock-test', display_name: 'Stock test', host_package: 'com.mentra.mentra'},
  {device_session_id: 'fork-test', display_name: 'Fork test', host_package: 'com.mentra.mentra.openalma',
   action_kind: 'start', action_label: 'Install', startable: true}
];
const rows = installations.map(installation => {
  const elements = new Map();
  return {dataset: {irisInstallation: installation.device_session_id},
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, {
        setAttribute() {}, querySelector() { return null; }
      });
      return elements.get(selector);
    }
  };
});
const parent = {parentNode: {querySelectorAll: () => rows}};
global.document = {querySelector: () => parent};
global.esc = value => String(value).replace(/&/g, '&amp;');
global.irisInstallDisabled = () => false;
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
renderIrisInstallations({installations});
for (let i = 0; i < rows.length; i++) {
  const html = rows[i].querySelector('.iris-actions').innerHTML;
  assert.ok(html.includes('href="/iris?device_session_id=' + encodeURIComponent(installations[i].device_session_id) + '">Setup</a>'));
  assert.ok(!html.includes('href="/iris">Setup</a>'));
  assert.ok(!html.includes('Stock Install'));
}
assert.match(rows[1].querySelector('.iris-actions').innerHTML, />Install<\/button>/);
assert.match(rows[1].querySelector('.iris-actions').innerHTML, /name="device_session_id" value="fork-test"/);
installations[1].action_label = 'Update';
renderIrisInstallations({installations, ready: false});
assert.match(rows[1].querySelector('.iris-actions').innerHTML, /disabled>Update<\/button>/);
renderIrisInstallations({installations, ready: true});
assert.match(rows[1].querySelector('.iris-actions').innerHTML, /type="submit">Update<\/button>/);
installations[1].action_label = 'Repair';
for (const ready of [false, true]) {
  renderIrisInstallations({installations, ready});
  const html = rows[1].querySelector('.iris-actions').innerHTML;
  assert.doesNotMatch(html, /<form|>Repair</);
  assert.match(html, /href="\/iris\?device_session_id=fork-test">Setup<\/a>/);
}
assert.ok(!rows[0].querySelector('.iris-actions').innerHTML.includes('>Repair<'));
""", str(path)], check=True, timeout=10)


def test_memorize_gauge_over_threshold_with_gap_detected():
    html = _render({
        "summed_unmemorized_tokens": 12900,
        "threshold": 8000,
        "pct": 161,
        "sleep_gap_ready": True,
        "computed_at": "2026-06-11T10:00:00+00:00",
    })
    assert "sleep-gap detected" in html
    assert "waiting for sleep-gap" not in html


def test_memorize_gauge_shows_failed_consolidation_retry():
    state = {
        "summed_unmemorized_tokens": 2000,
        "threshold": 8000,
        "pct": 25,
        "sleep_gap_ready": False,
        "pending_consolidation_segments": 2,
        "consolidation_state": "error",
        "paused": True, "retry_operation": "consolidation",
        "pause_reason": "RuntimeError: reflection failed",
        "consolidation_age_days": 103.5,
        "last_consolidation_error": "RuntimeError: reflection failed",
        "computed_at": "2026-09-26T10:00:00+00:00",
    }
    html = _render(state)

    assert "Paused: Consolidation failed" in html
    assert "RuntimeError: reflection failed" in html
    assert ">Retry</button>" in html
    unknown = {**state, "summed_unmemorized_tokens": None, "pct": None, "sleep_gap_ready": None,
               "source_warning": 'Cannot read <snapshot> & "source"', "context_load_tokens": 12000,
               "context_load_has_chat": False}
    html = _render(unknown)
    assert "Memorize: error" in html
    assert "Cannot read &lt;snapshot&gt; &amp; &#34;source&#34;" in html
    assert 'popovertarget="info:source:Fictional Soul"' in html
    assert 'aria-label="Cannot read &lt;snapshot&gt; &amp; &#34;source&#34;"' in html
    assert "<snapshot>" not in html
    assert "Memorize: 0" not in html and "Memorize: 2,000" not in html
    assert 'class="meter"' not in html and 'class="badge"' not in html
    assert "Paused: Consolidation failed" in html and ">Retry</button>" in html
    assert "&asymp; 12,000 tokens" in html
    assert "tokens<br>(memory only)" in html
    html = _render({**unknown, "memorize_running": True,
                    "progress": {"phase": "extracting", "current": 1, "total": 2}})
    assert "disabled>Retrying..." in html and "extracting: 1 / 2" in html
    html = _render({**unknown, "retry_operation": "import", "pause_reason": "Waiting for import before Memorize."})
    assert 'href="/echo"' in html and ">Retry</button>" not in html


def test_memorize_gauge_distinguishes_overdue_and_running():
    base = {
        "summed_unmemorized_tokens": 2000,
        "threshold": 8000,
        "pct": 25,
        "pending_consolidation_segments": 2,
        "computed_at": "2026-09-26T10:00:00+00:00",
    }

    overdue = _render({**base, "consolidation_state": "overdue"})
    running = _render({**base, "consolidation_state": "running"})

    assert "Weekly reflection will occur after the coming Memorize" in overdue
    assert ">Retry</button>" not in overdue
    assert "Memory consolidation is running" in running
    assert ">Retry</button>" not in running


def test_memorize_poll_renderer_executes_all_consolidation_states():
    template = Path(__file__).resolve().parents[1] / "launcher" / "templates" / "index.html"
    subprocess.run(
        [
            "node",
            "-e",
            r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const text = fs.readFileSync(process.argv[1], 'utf8');
const script = fs.readFileSync(require('path').join(require('path').dirname(process.argv[1]), '../static/launcher.js'), 'utf8');
const box = {innerHTML: '', querySelector: () => null, querySelectorAll: () => []};
const fetches = []; let polls = 0;
const context = {
  console, Date, Number, Math,
  document: {getElementById: () => box},
  window: {alert: () => {}},
  fetch: async (url, options) => { fetches.push({url, options}); return {ok: true, json: async () => ({})}; },
  pollMemorize: () => { polls++; },
};
vm.createContext(context);
vm.runInContext(script, context);
(async () => {
const base = {summed_unmemorized_tokens: 2000, pct: 25, sleep_gap_ready: false, context_load_tokens: 43567, context_load_has_chat: true,
  threshold: 8000, pending_consolidation_segments: 2, computed_at: '2026-09-26T10:00:00Z'};
context.renderMemorize({souls: [{...base, paused: true, retry_operation: 'consolidation', pause_reason: '<bad>', soul_id: 'First Soul'}]});
assert.match(box.innerHTML, /Retry<\/button>/);
assert.match(box.innerHTML, /&lt;bad&gt;/);
assert.doesNotMatch(box.innerHTML, /<bad>/);
assert.match(box.innerHTML, /Memorize: 2,000 \/ 8,000 \(25%\)/);
assert.match(box.innerHTML, /style="width: 25%"/);
assert.match(box.innerHTML, /&asymp; 43,567 tokens/);
assert.match(box.innerHTML, /class="memorize-row"/);
assert.match(box.innerHTML, /popovertarget="info:context:/);
assert.match(box.innerHTML, /class="info-text" popover/);
const tooltip = box.innerHTML.match(/class="info-text"[^>]*>([^<]+)</)[1];
assert.ok(text.includes(tooltip));
for (const missing of [{}, {context_load_tokens: null}]) {
  context.renderMemorize({souls: [{...base, context_load_tokens: undefined, ...missing}]});
  assert.match(box.innerHTML, /class="context-load"[\s\S]*<p>unknown<\/p>/);
  assert.doesNotMatch(box.innerHTML, /&asymp; 0 tokens/);
}
context.renderMemorize({souls: [{...base, context_load_tokens: 0}]});
assert.match(box.innerHTML, /&asymp; 0 tokens/);
context.renderMemorize({souls: [
  {...base, soul_id: 'First Soul', context_load_tokens: 12000},
  {...base, soul_id: 'Other Soul', context_load_tokens: 34000},
]});
const firstSoul = box.innerHTML.split('<h3>First Soul</h3>')[1].split('<h3>Other Soul</h3>')[0];
assert.match(firstSoul, /&asymp; 12,000 tokens/);
assert.doesNotMatch(firstSoul, /&asymp; 34,000 tokens/);
assert.match(box.innerHTML.split('<h3>Other Soul</h3>')[1], /&asymp; 34,000 tokens/);
const unknown = {...base, summed_unmemorized_tokens: null, pct: null, sleep_gap_ready: null,
  source_warning: 'Cannot read <snapshot> & "source"', context_load_has_chat: false, paused: true,
  retry_operation: 'consolidation', soul_id: 'First Soul'};
context.renderMemorize({souls: [unknown]});
assert.match(box.innerHTML, /Memorize: error/);
assert.match(box.innerHTML, /Cannot read &lt;snapshot&gt; &amp; &quot;source&quot;/);
assert.match(box.innerHTML, /popovertarget="info:source:First Soul"/);
assert.match(box.innerHTML, /aria-label="Cannot read &lt;snapshot&gt; &amp; &quot;source&quot;"/);
assert.match(box.innerHTML, /tokens<br>\(memory only\)/);
assert.doesNotMatch(box.innerHTML, /<snapshot>|Memorize: (0|2,000)|class="meter"|class="badge"/);
assert.match(box.innerHTML, /Paused: Consolidation failed/);
assert.match(box.innerHTML, /Retry<\/button>/);
assert.match(box.innerHTML, /&asymp; 43,567 tokens/);
context.renderMemorize({souls: [{...base, summed_unmemorized_tokens: 0, pct: 0, context_load_has_chat: false}]});
assert.match(box.innerHTML, /Memorize: 0 \/ 8,000/);
assert.match(box.innerHTML, /tokens<br>\(memory only\)/);
assert.doesNotMatch(box.innerHTML, /Snapshot/);
assert.doesNotMatch(box.innerHTML, /Memorize: error/);
let shown = 0, focused = 0;
const info = {dataset: {info: 'context:First Soul'}, querySelector: selector => selector === '.info-text'
  ? {showPopover: () => { shown++; }} : {focus: () => { focused++; }}};
box.querySelector = () => ({parentElement: info});
box.querySelectorAll = () => [info];
context.document.activeElement = {closest: () => info};
context.renderMemorize({souls: [{...base, soul_id: 'First Soul'}]});
assert.equal(shown, 1);
assert.equal(focused, 1);
box.querySelector = () => null;
box.querySelectorAll = () => [];
delete context.document.activeElement;
context.renderMemorize({souls: [{...unknown, memorize_running: true,
  progress: {phase: 'extracting', current: 1, total: 2}}]});
assert.match(box.innerHTML, / disabled>Retrying\.\.\./);
assert.match(box.innerHTML, /extracting: 1 \/ 2/);
context.renderMemorize({souls: [{...unknown, retry_operation: 'import', pause_reason: 'Waiting for import before Memorize.'}]});
assert.match(box.innerHTML, /href="\/echo"/);
assert.doesNotMatch(box.innerHTML, /Retry<\/button>/);
context.renderMemorize({souls: [{...base, paused: true, retry_operation: 'import', pause_reason: 'Waiting for import before Memorize.'}]});
assert.match(box.innerHTML, /href="\/echo"/);
assert.doesNotMatch(box.innerHTML, /Consolidation failed|Retry<\/button>/);
context.renderMemorize({souls: [{...base, paused: true, retry_operation: 'memorize', pause_reason: 'Waiting for Memorize after import.'}]});
assert.match(box.innerHTML, /waiting for Memorize/);
context.renderMemorize({souls: [{...base, threshold: 0, paused: true, retry_operation: 'memorize', soul_id: 'First Soul'}]});
assert.match(box.innerHTML, /Paused: Memorize failed/);
assert.match(box.innerHTML, /Retry<\/button>/);
context.renderMemorize({souls: [{...base, consolidation_state: 'overdue'}]});
assert.match(box.innerHTML, /Weekly reflection will occur after the coming Memorize/);
assert.match(box.innerHTML, /2 memorized segments already in queue/);
assert.doesNotMatch(box.innerHTML, /Retry<\/button>/);
context.renderMemorize({souls: [{...base, consolidation_state: 'running'}]});
assert.match(box.innerHTML, /is running/);
assert.doesNotMatch(box.innerHTML, /Retry<\/button>/);
const button = {disabled: false, textContent: 'Retry', dataset: {soul: 'First Soul & Next'}};
context.retryConsolidation(button);
await new Promise(resolve => setImmediate(resolve));
assert.equal(button.disabled, true);
assert.equal(button.textContent, 'Retrying...');
assert.deepEqual(fetches, [{url: '/memorize/retry?soul_id=First%20Soul%20%26%20Next', options: {method: 'POST'}}]);
assert.equal(polls, 1);
})().catch(error => { console.error(error); process.exitCode = 1; });
""",
            str(template),
        ],
        check=True,
    )


def test_memorize_gauge_empty_state():
    html = _render({})
    assert "No pending-memorize data" in html
    assert '<div class="meter">' not in html


@pytest.mark.parametrize("forecast", [{}, {"context_load_tokens": None}, {"context_load_tokens": 0}])
def test_context_load_missing_is_unknown_without_hiding_recovery(forecast):
    html = _render({"threshold": 6000, "summed_unmemorized_tokens": 0, "pct": 0,
                    "paused": True, "retry_operation": "memorize", **forecast})
    context = html.split('<div class="context-load">', 1)[1].split("</div>", 1)[0]
    if forecast.get("context_load_tokens") == 0:
        assert "&asymp; 0 tokens" in context
    else:
        assert "unknown" in context and "&asymp; 0 tokens" not in context
    assert "Paused: Memorize failed" in html and ">Retry</button>" in html


def test_context_load_guidance_uses_existing_private_config_opener(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app

    html = _render({"threshold": 6000, "summed_unmemorized_tokens": 0, "pct": 0})
    paragraph = "Configure your AI model’s published context-window size. The estimated <strong>context load</strong> of the conversation and supporting memory must fit within the context-window. Reduce min_chunk_tokens in config.json if the context load is too high."
    assert paragraph in html
    forms = re.findall(r'<form class="inline" method="post" action="/edit/memu-server-config">(.*?)</form>', html, re.S)
    assert len(forms) == 2
    for form, key in zip(forms, ("llm.context_window_tokens", "claude_code_context_window_tokens")):
        assert f"<code>{key}</code>" in form
        assert 'class="config-link" type="submit"' in form
        assert html.index(form) < html.index('id="memorize-meter"')
    assert html.index(paragraph) < html.index(forms[0])
    assert 'href="/edit/' not in html
    target = tmp_path / "mcp-memu-server" / "config.json"
    target.parent.mkdir()
    target.write_text('{"llm":{"api_key":"fictional-private-key"}}', encoding="utf-8")
    original = target.read_bytes()
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    opened = []
    monkeypatch.setattr(app.webbrowser, "open", opened.append)
    client = TestClient(app.app, base_url="http://127.0.0.1")
    for _form in forms:
        response = client.post("/edit/memu-server-config", follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/"
        assert "fictional-private-key" not in response.text
    assert opened == [target.resolve().as_uri()] * 2
    assert client.get("/edit/memu-server-config").status_code == 405
    assert target.read_bytes() == original
    settings_html = _render({}, template_name="settings.html",
                            editable_configs=[{"key": "memu-server-config", "label": "memU Server config.json"}])
    assert "Edit configs" in settings_html and 'method="post" action="/edit/memu-server-config"' in settings_html
    assert "memU Server config.json" in settings_html
    assert "Memory reflection requires this setting" not in settings_html


def test_multi_soul_meters_are_named_and_retry_stays_paused():
    base = {"summed_unmemorized_tokens": 10, "threshold": 6000, "pct": 0, "computed_at": "2026-10-02T00:00:00Z"}
    html = _render([
        {**base, "soul_id": "First Soul", "context_load_tokens": 12000, "paused": True, "retry_operation": "memorize", "pause_reason": "Failed", "memorize_running": True, "progress": {"phase": "extracting", "current": 1, "total": 2}},
        {**base, "soul_id": "Other Soul", "context_load_tokens": 34000},
    ])
    assert "<h3>First Soul</h3>" in html and "<h3>Other Soul</h3>" in html
    assert "Paused: Memorize failed" in html
    assert "disabled>Retrying..." in html
    assert html.count('class="meter"') == 2
    first = html.split("<h3>First Soul</h3>", 1)[1].split("<h3>Other Soul</h3>", 1)[0]
    assert "&asymp; 12,000 tokens" in first and "&asymp; 34,000 tokens" not in first
    assert "&asymp; 34,000 tokens" in html.split("<h3>Other Soul</h3>", 1)[1]
    assert "<h3>" not in _render(base)
    zero = _render({**base, "threshold": 0, "paused": True, "retry_operation": "memorize"})
    assert "Paused: Memorize failed" in zero and ">Retry</button>" in zero


def test_memorize_owner_error_is_visible():
    assert "OpenAlma owner mismatch" in _render({"error": "OpenAlma owner mismatch"})


def test_import_wait_uses_echo_not_consolidation_retry():
    html = _render({"threshold": 6000, "summed_unmemorized_tokens": 0, "pct": 0,
                    "paused": True, "retry_operation": "import", "pause_reason": "Waiting for import before Memorize."})
    assert 'href="/echo"' in html and "waiting for import" in html
    assert "Consolidation failed" not in html and "retryConsolidation(this)" not in html


def test_channels_soul_selector_is_one_combobox():
    html = _render({}, template_name="hermes.html")

    assert 'id="channels-soul-form"' in html
    assert 'id="channels-soul-options"' in html
    assert 'id="soul-existing"' not in html
    assert "New soul will be created" in html
    assert ".soul-options[hidden] { display: none; }" in html


def test_not_installed_services_use_regular_rows_and_opt_in_hiding():
    html = _render({}, [{"name": "atomic", "label": "Atomic Mind Map"}])

    assert 'id="hide-not-installed" type="checkbox"' in html
    assert 'type="checkbox" checked' not in html
    assert 'id="hidden-services-section" class="not-installed" hidden' in html
    assert html.index('id="visible-services"') < html.index('Hide not installed')
    assert '<summary><label onclick="event.stopPropagation()">Hide not installed' in html
    assert 'data-service="atomic" data-installed="false"' in html
    assert '<tbody id="hidden-services"></tbody>' in html
    assert '<tr id="echo-row" data-installed="false">' in html
    assert 'action="/echo/enable"' in html
    assert "Atomic Mind Map" in html


def test_service_visibility_moves_existing_rows_and_preserves_preferences():
    path = Path(__file__).resolve().parents[1] / "launcher/static/launcher.js"
    subprocess.run(["node", "-e", r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function body() {
  return {children: [], get firstElementChild() { return this.children[0] || null; },
    insertBefore(node, before) {
      if (node.parentNode) node.parentNode.children.splice(node.parentNode.children.indexOf(node), 1);
      this.children.splice(before ? this.children.indexOf(before) : this.children.length, 0, node);
      node.parentNode = this;
    }};
}
function row(id, installed) {
  return {id, dataset: {installed: String(installed)},
    get nextElementSibling() { return this.parentNode.children[this.parentNode.children.indexOf(this) + 1] || null; }};
}
const visible = body(), hidden = body(), checkbox = {checked: false}, section = {hidden: true, open: false};
const core = row('core', false), atomic = row('atomic', true), iris = row('iris', false), echo = row('echo-row', false);
const rows = [core, atomic, iris, echo];
rows.forEach(node => visible.insertBefore(node, null));
const elements = new Map([['visible-services', visible], ['hidden-services', hidden],
  ['hide-not-installed', checkbox], ['hidden-services-section', section], ['echo-row', echo]]);
const saved = new Map();
global.document = {querySelectorAll: () => rows, getElementById: id => elements.get(id)};
global.localStorage = {getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value)};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
initServiceVisibility();
assert.deepEqual(visible.children, rows);
assert.equal(section.hidden, false);
checkbox.checked = true;
setServiceVisibility(true);
assert.deepEqual(visible.children, [atomic]);
assert.deepEqual(hidden.children, [core, iris, echo]);
assert.equal(section.hidden, false);
assert.equal(section.open, false);
echo.dataset.installed = 'true'; // The server renders the enabled state after Install.
groupServiceRows();
assert.deepEqual(visible.children, [atomic, echo]);
const phone = row('phone', true);
phone.dataset.irisInstallation = 'fictional-phone';
phone.draft = 'Unsaved name';
hidden.insertBefore(phone, iris.nextElementSibling);
iris.dataset.installed = 'true';
groupServiceRows();
assert.deepEqual(visible.children, [atomic, iris, phone, echo]);
assert.equal(phone.draft, 'Unsaved name');
assert.equal(visible.children.filter(node => node === phone).length, 1);
initServiceVisibility();
assert.equal(checkbox.checked, true);
assert.equal(echo.dataset.installed, 'true');
checkbox.checked = false;
setServiceVisibility(false);
assert.deepEqual(visible.children, [core, atomic, iris, phone, echo]);
assert.equal(section.hidden, false);
rows.forEach(node => { node.dataset.installed = 'true'; });
groupServiceRows();
assert.equal(section.hidden, true);
assert.equal(section.open, false);
global.localStorage = {getItem() { throw Error('Blocked'); }, setItem() { throw Error('Blocked'); }};
assert.doesNotThrow(() => initServiceVisibility());
assert.doesNotThrow(() => setServiceVisibility(false));
""", str(path)], check=True, timeout=10)


def test_force_stop_only_renders_with_failure_evidence():
    service = {"name": "memu-server", "label": "memU", "state": "stopping"}

    assert "Force Stop" not in _render({}, services=[{**service, "force_stoppable": False}])
    assert _render({}, services=[{**service, "force_stoppable": True}]).count("Force Stop") == 1
    specialized = {**service, "state": "running", "force_stoppable": True, "action_kind": "settings"}
    assert "Force Stop" in _render({}, services=[specialized])

    template = (
        Path(__file__).resolve().parents[1] / "launcher" / "templates" / "index.html"
    ).read_text(encoding="utf-8")
    action_html = template.split("function actionHtml", 1)[1]
    assert action_html.index("if (data.force_stoppable)") < action_html.index("if (data.action_kind")


def test_retry_reports_unavailable_server_at_each_read(monkeypatch):
    from fastapi.testclient import TestClient
    import app
    for method in ("read_owner", "list_souls", "memorize_pending"):
        with monkeypatch.context() as patch:
            patch.setattr(app.services, "read_owner", lambda: "TestOwner")
            patch.setattr(app.services, "list_souls", lambda: ["TestSoul"])
            patch.setattr(app.services, "memorize_pending", lambda *_args: {})
            def unavailable(*_args):
                raise app.services.OwnerServiceUnavailable("Owner service unavailable")
            patch.setattr(app.services, method, unavailable)
            response = TestClient(app.app, base_url="http://127.0.0.1").post("/memorize/retry?soul_id=TestSoul")
            assert response.status_code == 503
            assert response.json()["detail"] == "Owner service unavailable"
