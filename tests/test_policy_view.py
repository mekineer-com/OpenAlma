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
