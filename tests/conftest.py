from __future__ import annotations

import tempfile
import sys
from pathlib import Path
from unittest.mock import Mock

import fakeredis
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.config import config as app_config
from app.extensions import db, socketio
from app.models import Campaign, Character, User
from app.seed import seed_database


@pytest.fixture
def app():
    original_uri = app_config.SQLALCHEMY_DATABASE_URI
    db_file = Path(tempfile.gettempdir()) / f"embervale-test-{next(tempfile._get_candidate_names())}.db"
    object.__setattr__(app_config, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{db_file}")
    try:
        flask_app = create_app()
        flask_app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            LOGIN_DISABLED=False,
        )
        with flask_app.app_context():
            db.drop_all()
            db.create_all()
            seed_database()
        yield flask_app
    finally:
        object.__setattr__(app_config, "SQLALCHEMY_DATABASE_URI", original_uri)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def fake_redis(monkeypatch):
    from app.cache import cache

    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(cache, "_redis", fake)
    monkeypatch.setattr(cache, "_redis_ok", True)
    return fake


@pytest.fixture
def fake_gemini(monkeypatch):
    from app.gemini_service import gemini_service

    fake_client = Mock()
    monkeypatch.setattr(gemini_service, "client", fake_client)
    monkeypatch.setattr(gemini_service, "gemini_ok", True)
    return fake_client


@pytest.fixture
def logged_in_user(app, client):
    payload = {
        "email": "player@example.com",
        "display_name": "Player One",
        "password": "password123",
    }
    client.post("/auth/register", data=payload, follow_redirects=False)
    with app.app_context():
        user = User.query.filter_by(email=payload["email"]).first()
    return {"id": user.id, "email": user.email}


@pytest.fixture
def seeded_campaign(app):
    with app.app_context():
        return Campaign.query.first()


@pytest.fixture
def character_factory(app):
    def _create(user: User, campaign: Campaign, name: str = "Arya"):
        character = Character(
            user_id=user.id,
            campaign_id=campaign.id,
            name=name,
            race="Human",
            char_class="Fighter",
            max_hp=14,
            hp=14,
            armor_class=14,
            gold=25,
            inventory={"items": []},
            strength=14,
            dexterity=11,
            constitution=13,
            intelligence=10,
            wisdom=10,
            charisma=10,
        )
        db.session.add(character)
        db.session.commit()
        return character

    return _create


@pytest.fixture
def socketio_client(app, client, logged_in_user):
    sio = socketio.test_client(app, flask_test_client=client, auth={})
    yield sio
    sio.disconnect()
