from __future__ import annotations

from app.extensions import db, socketio
from app.models import Campaign, CampaignMembership, User
from app.seed import clone_template_campaign


def _register(client, email):
    client.post("/auth/register", data={"email": email, "display_name": email.split("@")[0], "password": "password123"})


def test_create_campaign_generates_join_code(app, client):
    _register(client, "owner@example.com")
    res = client.post("/api/campaigns", json={"name": "Test Campaign"}, headers={"X-Requested-With": "Embervale"})
    assert res.status_code == 201
    code = res.get_json()["campaign"]["join_code"]
    assert isinstance(code, str) and len(code) >= 6


def test_join_code_no_collisions():
    from app.models import _gen_join_code

    codes = {_gen_join_code() for _ in range(1000)}
    assert len(codes) == 1000


def test_join_campaign_valid_code_creates_membership(app, client):
    _register(client, "owner2@example.com")
    created = client.post("/api/campaigns", json={"name": "Owners"}, headers={"X-Requested-With": "Embervale"}).get_json()["campaign"]
    client.post("/auth/logout")
    _register(client, "player@example.com")
    joined = client.post("/api/campaigns/join", json={"code": created["join_code"]}, headers={"X-Requested-With": "Embervale"})
    assert joined.status_code == 200
    with app.app_context():
        assert CampaignMembership.query.filter_by(campaign_id=created["id"]).count() == 2


def test_join_campaign_unknown_code_returns_404(client):
    _register(client, "owner3@example.com")
    res = client.post("/api/campaigns/join", json={"code": "XXXXXX"}, headers={"X-Requested-With": "Embervale"})
    assert res.status_code == 404


def test_join_campaign_idempotent(app, client):
    _register(client, "owner4@example.com")
    created = client.post("/api/campaigns", json={"name": "Owners"}, headers={"X-Requested-With": "Embervale"}).get_json()["campaign"]
    client.post("/auth/logout")
    _register(client, "player2@example.com")
    assert client.post("/api/campaigns/join", json={"code": created["join_code"]}, headers={"X-Requested-With": "Embervale"}).status_code == 200
    assert client.post("/api/campaigns/join", json={"code": created["join_code"]}, headers={"X-Requested-With": "Embervale"}).status_code == 200
    with app.app_context():
        assert CampaignMembership.query.filter_by(campaign_id=created["id"]).count() == 2


def test_non_member_state_forbidden_then_allowed_after_join(app):
    owner = app.test_client()
    _register(owner, "owner5@example.com")
    created = owner.post("/api/campaigns", json={"name": "Private"}, headers={"X-Requested-With": "Embervale"}).get_json()["campaign"]

    other = app.test_client()
    _register(other, "other@example.com")
    assert other.get(f"/api/campaigns/{created['id']}/state").status_code == 403
    assert other.post("/api/campaigns/join", json={"code": created["join_code"]}, headers={"X-Requested-With": "Embervale"}).status_code == 200
    assert other.get(f"/api/campaigns/{created['id']}/state").status_code == 200


def test_demo_campaign_accessible_without_membership(app):
    c = app.test_client()
    _register(c, "demoaccess@example.com")
    with app.app_context():
        demo = Campaign.query.filter_by(is_demo=True).first()
        assert demo is not None
        demo_id = demo.id
    assert c.get(f"/api/campaigns/{demo_id}/state").status_code == 200


def test_clone_template_campaign_independent_state(app, client):
    _register(client, "owner6@example.com")
    with app.app_context():
        owner = User.query.filter_by(email="owner6@example.com").first()
        cloned = clone_template_campaign(owner, "Independent")
        demo = Campaign.query.filter_by(is_demo=True).first()
        cloned.current_scene = "Changed"
        db.session.commit()
        assert demo.current_scene != cloned.current_scene


def test_socket_join_non_member_rejected(app):
    owner = app.test_client()
    _register(owner, "owner7@example.com")
    created = owner.post("/api/campaigns", json={"name": "Private"}, headers={"X-Requested-With": "Embervale"}).get_json()["campaign"]

    outsider = app.test_client()
    _register(outsider, "outsider@example.com")
    sio = socketio.test_client(app, flask_test_client=outsider)
    sio.emit("join_campaign", {"campaign_id": created["id"]})
    events = [e["name"] for e in sio.get_received()]
    assert "joined_campaign" not in events
