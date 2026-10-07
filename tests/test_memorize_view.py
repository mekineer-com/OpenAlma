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
        editable_configs=[],
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
    })
    assert "Memorize: 2,000 / 8,000 (25%)" in html
    assert 'style="width: 25%"' in html
    assert "waiting for sleep-gap" not in html
    assert 'title="Back to Services"' not in html


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
        if row["name"] == "iris-server":
            assert "Stock Install" not in initial + dynamic
            assert 'action="/iris/install"' not in initial + dynamic
    assert labels(polled[2]) == ["Setup"]
    assert 'href="/hermes?pair=1"' in polled[-1]


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
        iris_setup={"enabled": True, "ready": True, "rows": []},
        iris_connection={"base_url": "http://fixture.invalid"},
    )
    html = env.get_template("iris.html").render(**context, selected_installation=installations[0])
    confirmed = html.split('data-device-session-id="confirmed-app"', 1)[1].split("</li>", 1)[0]
    assert '<details class="iris-rename">' in confirmed
    assert 'aria-label="Rename Test Phone">Test Phone</summary>' in confirmed
    assert 'action="/iris/installations/confirmed-app/rename"' in confirmed
    assert 'action="/iris/install"' in confirmed
    assert '<summary>Rename</summary>' not in html
    assert '>Stock Install</button>' not in html
    assert 'data-device-session-id="forgotten-app"' not in html
    html = env.get_template("iris.html").render(**context, selected_installation=installations[1])
    live = html.split('data-device-session-id="forgotten-app"', 1)[1].split("</li>", 1)[0]
    assert 'data-device-session-id="confirmed-app"' not in html
    assert 'title="App details unavailable version unknown, Iris not yet reported">Unreported app</strong>' in live
    assert "<details" not in live
    assert "<form" not in live


def test_iris_status_signature_ignores_json_key_order():
    template = (Path(__file__).resolve().parents[1] / "launcher/templates/iris.html").read_text()
    function = template.split("function statusSignature(status) {", 1)[1].split("const initialSignature", 1)[0]
    script = "const selectedDevice = ''; function statusSignature(status) {" + function + r"""
const assert = require('assert');
const status = {setup: {enabled: true, ready: true, reason: 'Ready', step: 'ready',
  rows: [{label: 'Server', state: 'ready', detail: 'Ready'}]}, installations: []};
const sorted = JSON.parse(JSON.stringify(status, ['setup', 'installations', 'detail', 'enabled', 'label', 'ready', 'reason', 'rows', 'state', 'step']));
assert.equal(statusSignature(status), statusSignature(sorted));
sorted.setup.rows[0].state = 'failure';
assert.notEqual(statusSignature(status), statusSignature(sorted));
"""
    subprocess.run(["node", "-e", script], check=True, timeout=10)


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
    html = _render({
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
    })

    assert "Paused: Consolidation failed" in html
    assert "RuntimeError: reflection failed" in html
    assert ">Retry</button>" in html


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
const box = {innerHTML: ''};
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
const base = {threshold: 8000, pending_consolidation_segments: 2, computed_at: '2026-09-26T10:00:00Z'};
context.renderMemorize({souls: [{...base, paused: true, retry_operation: 'consolidation', pause_reason: '<bad>', soul_id: 'First Soul'}]});
assert.match(box.innerHTML, /Retry<\/button>/);
assert.match(box.innerHTML, /&lt;bad&gt;/);
assert.doesNotMatch(box.innerHTML, /<bad>/);
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


def test_multi_soul_meters_are_named_and_retry_stays_paused():
    base = {"summed_unmemorized_tokens": 10, "threshold": 6000, "pct": 0, "computed_at": "2026-10-02T00:00:00Z"}
    html = _render([
        {**base, "soul_id": "First Soul", "paused": True, "retry_operation": "memorize", "pause_reason": "Failed", "memorize_running": True, "progress": {"phase": "extracting", "current": 1, "total": 2}},
        {**base, "soul_id": "Other Soul"},
    ])
    assert "<h3>First Soul</h3>" in html and "<h3>Other Soul</h3>" in html
    assert "Paused: Memorize failed" in html
    assert "disabled>Retrying..." in html
    assert html.count('class="meter"') == 2
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


def test_not_installed_services_are_collapsed_below_services():
    html = _render({}, [{"name": "atomic", "label": "Atomic Mind Map"}])

    assert '<details class="not-installed">' in html
    assert "Not installed (1)" in html
    assert "Atomic Mind Map" in html


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
