from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def react_build_exists():
    build_index = Path(__file__).resolve().parents[1] / "app" / "static" / "react" / "index.html"
    if not build_index.exists():
        pytest.skip("React build not found at app/static/react/index.html")
    return True


def test_root_serves_react_mount(client, react_build_exists):
    res = client.get("/")
    assert res.status_code == 200
    assert 'id="root"' in res.get_data(as_text=True)


def test_play_route_serves_react_mount(client, react_build_exists):
    res = client.get("/campaigns/1/play")
    assert res.status_code == 200
    assert 'id="root"' in res.get_data(as_text=True)
