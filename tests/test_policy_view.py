from pathlib import Path

import pytest


jinja2 = pytest.importorskip("jinja2")


def test_excluded_whatsapp_chats_are_collapsed():
    template_dir = Path(__file__).resolve().parents[1] / "launcher" / "templates"
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir),
        autoescape=True,
    )
    html = env.get_template("index.html").render(
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
    html = env.get_template("index.html").render(
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


def test_virgin_setup_hides_both_channels_sections():
    template_dir = Path(__file__).resolve().parents[1] / "launcher" / "templates"
    html = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir), autoescape=True,
    ).get_template("index.html").render(
        services=[], chats=[], visible_chats=[], excluded_chats=[],
        channels_configured=False, needs_setup=True, soul_ids=[],
    )

    assert "Hermes Channels Soul selector" not in html
    assert "WhatsApp channel policy" not in html
