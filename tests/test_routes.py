from __future__ import annotations

import threading

from app.extensions import db
from app.models import Campaign, Character, Shop, ShopItem, User


def _register_and_login(client, email):
    client.post("/auth/register", data={"email": email, "display_name": email.split("@")[0], "password": "password123"})


def test_index_redirects_when_unauthenticated(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b'id="root"' in res.data


def test_lobby_redirects(client):
    res = client.get("/lobby")
    assert res.status_code == 301


def test_api_me_unauthenticated(client):
    res = client.get("/api/me")
    assert res.status_code == 401


def test_api_me_authenticated(client):
    _register_and_login(client, "me@example.com")
    res = client.get("/api/me")
    body = res.get_json()
    assert res.status_code == 200
    assert "id" in body and "display_name" in body


def test_api_campaigns_requires_auth(client):
    res = client.get("/api/campaigns")
    assert res.status_code in (302, 401)


def test_api_campaigns_authenticated(client):
    _register_and_login(client, "list@example.com")
    res = client.get("/api/campaigns")
    assert res.status_code == 200
    assert isinstance(res.get_json(), list)


def test_home_authenticated(client):
    _register_and_login(client, "lobby@example.com")
    res = client.get("/")
    assert res.status_code == 200
    assert b'id="root"' in res.data


def test_play_requires_character(app, client):
    _register_and_login(client, "play@example.com")
    with app.app_context():
        campaign = Campaign.query.first()
    res = client.get(f"/play/{campaign.id}")
    assert res.status_code == 302
    assert "/lobby" in res.location


def test_create_character_valid(app, client):
    _register_and_login(client, "char@example.com")
    with app.app_context():
        campaign = Campaign.query.first()
    res = client.post(
        f"/api/campaigns/{campaign.id}/characters",
        json={"name": "Arya", "race": "Human", "class": "fighter"},
        headers={"X-Requested-With": "Embervale"},
    )
    assert res.status_code == 201


def test_create_character_duplicate(app, client):
    _register_and_login(client, "char2@example.com")
    with app.app_context():
        campaign = Campaign.query.first()
    url = f"/api/campaigns/{campaign.id}/characters"
    headers = {"X-Requested-With": "Embervale"}
    assert client.post(url, json={"name": "A", "race": "Human", "class": "fighter"}, headers=headers).status_code == 201
    assert client.post(url, json={"name": "B", "race": "Human", "class": "fighter"}, headers=headers).status_code == 400


def test_create_character_unknown_class(app, client):
    _register_and_login(client, "char3@example.com")
    with app.app_context():
        campaign = Campaign.query.first()
    res = client.post(
        f"/api/campaigns/{campaign.id}/characters",
        json={"name": "Arya", "race": "Human", "class": "invalid"},
        headers={"X-Requested-With": "Embervale"},
    )
    assert res.status_code == 400


def test_create_character_ranger_and_paladin_valid(app, client):
    _register_and_login(client, "char-classes@example.com")
    with app.app_context():
        campaign = Campaign.query.first()

    ranger = client.post(
        f"/api/campaigns/{campaign.id}/characters",
        json={"name": "Vale", "race": "Elf", "class": "ranger"},
        headers={"X-Requested-With": "Embervale"},
    )
    assert ranger.status_code == 201

    second_client = app.test_client()
    _register_and_login(second_client, "paladin@example.com")
    paladin = second_client.post(
        f"/api/campaigns/{campaign.id}/characters",
        json={"name": "Aster", "race": "Human", "class": "paladin"},
        headers={"X-Requested-With": "Embervale"},
    )
    assert paladin.status_code == 201


def test_create_character_stat_overrides_are_applied(app, client):
    _register_and_login(client, "char-stats@example.com")
    with app.app_context():
        campaign = Campaign.query.first()

    res = client.post(
        f"/api/campaigns/{campaign.id}/characters",
        json={
            "name": "Mira",
            "race": "Tiefling",
            "class": "wizard",
            "strength": 9,
            "dexterity": 12,
            "constitution": 11,
            "intelligence": 18,
            "wisdom": 14,
            "charisma": 16,
        },
        headers={"X-Requested-With": "Embervale"},
    )
    assert res.status_code == 201
    with app.app_context():
        character = Character.query.filter_by(campaign_id=campaign.id, name="Mira").first()
        assert character is not None
        assert character.strength == 9
        assert character.dexterity == 12
        assert character.constitution == 11
        assert character.intelligence == 18
        assert character.wisdom == 14
        assert character.charisma == 16


def test_state_shape(app, client):
    _register_and_login(client, "state@example.com")
    with app.app_context():
        campaign = Campaign.query.first()
    client.post(
        f"/api/campaigns/{campaign.id}/characters",
        json={"name": "Arya", "race": "Human", "class": "fighter"},
        headers={"X-Requested-With": "Embervale"},
    )
    res = client.get(f"/api/campaigns/{campaign.id}/state")
    body = res.get_json()
    assert {"campaign", "locations", "characters", "battle", "my_character_id"} <= set(body)


def test_get_shop(app, client):
    _register_and_login(client, "shop@example.com")
    with app.app_context():
        campaign = Campaign.query.first()
    res = client.get(f"/api/campaigns/{campaign.id}/shops/thorne_smithy")
    assert res.status_code == 200
    assert res.get_json()["items"]


def test_concurrent_shop_purchase(client, app):
    with app.app_context():
        campaign = Campaign.query.first()
        campaign_id = campaign.id
        shop = Shop.query.filter_by(campaign_id=campaign.id, key="thorne_smithy").first()
        shop_id = shop.id
        item = ShopItem.query.filter_by(shop_id=shop.id).first()
        item_id = item.id
        item.stock = 1
        db.session.commit()

    c1 = app.test_client()
    c2 = app.test_client()
    _register_and_login(c1, "buyer1@example.com")
    _register_and_login(c2, "buyer2@example.com")
    for c in (c1, c2):
        c.post(
            f"/api/campaigns/{campaign_id}/characters",
            json={"name": "Buyer", "race": "Human", "class": "fighter"},
            headers={"X-Requested-With": "Embervale"},
        )

    results = []

    def buy(c):
        r = c.post(
            f"/api/shops/{shop_id}/buy",
            json={"item_id": item_id},
            headers={"X-Requested-With": "Embervale"},
        )
        results.append(r.status_code)

    t1 = threading.Thread(target=buy, args=(c1,))
    t2 = threading.Thread(target=buy, args=(c2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sorted(results) in ([200, 409], [200, 400])
    with app.app_context():
        assert ShopItem.query.get(item_id).stock == 0


def test_buy_insufficient_gold(client, app):
    _register_and_login(client, "gold@example.com")
    with app.app_context():
        campaign = Campaign.query.first()
    client.post(f"/api/campaigns/{campaign.id}/characters", json={"name": "A", "race": "H", "class": "fighter"}, headers={"X-Requested-With": "Embervale"})
    with app.app_context():
        ch = Character.query.filter_by(campaign_id=campaign.id).order_by(Character.id.desc()).first()
        ch.gold = 0
        shop = Shop.query.filter_by(campaign_id=campaign.id, key="thorne_smithy").first()
        item = ShopItem.query.filter_by(shop_id=shop.id).first()
        db.session.commit()
        shop_id = shop.id
        item_id = item.id
    res = client.post(f"/api/shops/{shop_id}/buy", json={"item_id": item_id}, headers={"X-Requested-With": "Embervale"})
    assert res.status_code == 402


def test_metrics_and_healthz(client):
    _register_and_login(client, "metrics@example.com")
    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert {"cache", "turns"} <= set(metrics.get_json())
    healthz = client.get("/healthz")
    assert healthz.status_code in (200, 503)


def test_transcript_markdown_contains_turns(app, client, monkeypatch):
    _register_and_login(client, "transcript@example.com")
    with app.app_context():
        campaign = Campaign.query.first()
    client.post(
        f"/api/campaigns/{campaign.id}/characters",
        json={"name": "Arya", "race": "Human", "class": "fighter"},
        headers={"X-Requested-With": "Embervale"},
    )
    from app.gemini_service import gemini_service
    from app.routes import _run_turn_and_broadcast

    def fake_run_turn(_campaign, _actor, _action):
        yield ("narration_delta", "Test narration.")
        yield ("turn_complete", {"tokens_in": 1, "tokens_out": 1, "latency_ms": 1, "cache_hit": False})

    monkeypatch.setattr(gemini_service, "run_turn", fake_run_turn)
    with app.app_context():
        actor = Character.query.filter_by(campaign_id=campaign.id).first()
        _run_turn_and_broadcast(campaign.id, actor.id, "hello")
    res = client.get(f"/api/campaigns/{campaign.id}/transcript.md")
    text = res.get_data(as_text=True)
    assert res.status_code == 200
    assert "### Turn 1" in text
    assert "Test narration." in text
