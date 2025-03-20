from __future__ import annotations

from app.models import Campaign


def _register_and_login(client, email="home@example.com"):
    client.post("/auth/register", data={"email": email, "display_name": "home", "password": "password123"})


def test_home_unauth_redirects_to_login(client):
    res = client.get("/")
    assert res.status_code == 302
    assert "/auth/login" in res.location


def test_home_authenticated_renders_menu(client):
    _register_and_login(client)
    res = client.get("/")
    body = res.get_data(as_text=True)
    assert res.status_code == 200
    assert "EMBERVALE" in body
    assert "NEW GAME" in body


def test_lobby_redirects_permanently(client):
    res = client.get("/lobby", follow_redirects=False)
    assert res.status_code == 301
    assert res.headers["Location"].endswith("/")


def test_character_new_requires_auth(app, client):
    with app.app_context():
        campaign = Campaign.query.first()
    res = client.get(f"/campaigns/{campaign.id}/character/new")
    assert res.status_code == 302
    assert "/auth/login" in res.location


def test_character_new_authenticated_renders(app, client):
    _register_and_login(client, "charnew@example.com")
    with app.app_context():
        campaign = Campaign.query.first()
    client.post(
        "/api/campaigns/join",
        json={"code": campaign.join_code},
        headers={"X-Requested-With": "Embervale"},
    )
    res = client.get(f"/campaigns/{campaign.id}/character/new")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "Roll Stats" in body
    assert 'data-max-rolls="3"' in body


def test_create_campaign_returns_join_code(client):
    _register_and_login(client, "newcamp@example.com")
    res = client.post(
        "/api/campaigns",
        json={"name": "My New Campaign"},
        headers={"X-Requested-With": "Embervale"},
    )
    body = res.get_json()
    assert res.status_code == 201
    assert body["campaign"]["join_code"]


def test_character_new_shows_class_picker_after_campaign_created(client):
    _register_and_login(client, "picker@example.com")
    created = client.post(
        "/api/campaigns",
        json={"name": "Picker Campaign"},
        headers={"X-Requested-With": "Embervale"},
    ).get_json()
    campaign_id = created["campaign"]["id"]
    res = client.get(f"/campaigns/{campaign_id}/character/new")
    body = res.get_data(as_text=True)
    assert res.status_code == 200
    assert "class-grid" in body
