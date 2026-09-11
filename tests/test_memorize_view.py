from pathlib import Path

import pytest


jinja2 = pytest.importorskip("jinja2")


def _render(
    memorize: dict,
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
        memorize=memorize,
        owner_id="Fictional User",
        owner_error="",
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


def test_memorize_gauge_empty_state():
    html = _render({})
    assert "No pending-memorize data" in html
    assert '<div class="meter">' not in html


def test_memorize_owner_error_is_visible():
    assert "OpenAlma owner mismatch" in _render({"error": "OpenAlma owner mismatch"})


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

    template = (Path(__file__).resolve().parents[1] / "launcher" / "templates" / "index.html").read_text()
    action_html = template.split("function actionHtml", 1)[1]
    assert action_html.index("if (data.force_stoppable)") < action_html.index("if (data.action_kind")
