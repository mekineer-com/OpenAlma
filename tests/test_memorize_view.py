import subprocess
from pathlib import Path

import pytest


jinja2 = pytest.importorskip("jinja2")


def _render(
    memorize: dict | list,
    not_installed_services: list[dict] | None = None,
    services: list[dict] | None = None,
) -> str:
    template_dir = Path(__file__).resolve().parents[1] / "launcher" / "templates"
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir),
        autoescape=True,
    )
    return env.get_template("index.html").render(
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


def test_launcher_heading_uses_accessible_spiral_mark():
    html = _render({})

    assert '<h1 aria-label="OpenAlma"><svg class="brand-mark"' in html
    assert 'aria-hidden="true"' in html
    assert "</svg>penAlma</h1>" in html


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


def test_memorize_poll_renderer_supports_consolidation_states_and_retry():
    template = (
        Path(__file__).resolve().parents[1] / "launcher" / "templates" / "index.html"
    ).read_text(encoding="utf-8")

    assert "if (data.paused)" in template
    assert "data.consolidation_state === 'overdue'" in template
    assert "data.consolidation_state === 'running'" in template
    assert "data.pending_consolidation_segments" in template
    assert "data.pause_reason" in template
    assert "encodeURIComponent(button.dataset.soul)" in template


def test_memorize_poll_renderer_executes_all_consolidation_states():
    template = Path(__file__).resolve().parents[1] / "launcher" / "templates" / "index.html"
    subprocess.run(
        [
            "node",
            "-e",
            r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const text = fs.readFileSync(process.argv[1], 'utf8');
const script = text.slice(text.indexOf('function esc(text)'), text.indexOf('function syncMemorize'))
  + text.slice(text.indexOf('function fmt(n)'), text.indexOf("document.querySelectorAll('.snapshot-time')"));
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
context.renderMemorize({souls: [{...base, threshold: 0, paused: true, retry_operation: 'memorize', soul_id: 'First Soul'}]});
assert.match(box.innerHTML, /Paused: Memorize failed/);
assert.match(box.innerHTML, /Retry<\/button>/);
context.renderMemorize({souls: [{...base, consolidation_state: 'overdue'}]});
assert.match(box.innerHTML, /Weekly reflection will occur after the coming Memorize/);
assert.doesNotMatch(box.innerHTML, /Retry<\/button>/);
context.renderMemorize({souls: [{...base, consolidation_state: 'running'}]});
assert.match(box.innerHTML, /is running/);
assert.doesNotMatch(box.innerHTML, /Retry<\/button>/);
const button = {disabled: false, textContent: 'Retry', dataset: {soul: 'First Soul'}};
context.retryConsolidation(button);
await new Promise(resolve => setImmediate(resolve));
assert.equal(button.disabled, true);
assert.equal(button.textContent, 'Retrying...');
assert.deepEqual(fetches, [{url: '/memorize/retry?soul_id=First%20Soul', options: {method: 'POST'}}]);
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


def test_channels_soul_selector_is_one_combobox():
    html = _render({})

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
            response = TestClient(app.app).post("/memorize/retry?soul_id=TestSoul")
            assert response.status_code == 503
            assert response.json()["detail"] == "Owner service unavailable"
