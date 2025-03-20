from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Campaign, Character, User, _gen_join_code


def test_password_round_trip(app):
    with app.app_context():
        user = User(email="pw@example.com", display_name="pw")
        user.set_password("password123")
        assert user.check_password("password123")


def test_password_wrong_returns_false(app):
    with app.app_context():
        user = User(email="pw2@example.com", display_name="pw")
        user.set_password("password123")
        assert not user.check_password("wrong")


def test_character_public_dict_has_expected_keys(app):
    with app.app_context():
        campaign = Campaign.query.first()
        user = User(email="pub@example.com", display_name="pub")
        user.set_password("password123")
        db.session.add(user)
        db.session.flush()
        character = Character(
            user_id=user.id,
            campaign_id=campaign.id,
            name="Arya",
            race="Human",
            char_class="Fighter",
            inventory={"items": []},
        )
        db.session.add(character)
        db.session.commit()
        pub = character.to_public_dict()
        assert {"id", "name", "race", "class", "stats", "inventory", "is_online"} <= set(pub)
        assert "email" not in pub


def test_character_unique_constraint_per_user_campaign(app):
    with app.app_context():
        campaign = Campaign.query.first()
        user = User(email="uq@example.com", display_name="u")
        user.set_password("password123")
        db.session.add(user)
        db.session.flush()
        db.session.add(Character(user_id=user.id, campaign_id=campaign.id, name="A", race="H", char_class="F", inventory={"items": []}))
        db.session.commit()
        db.session.add(Character(user_id=user.id, campaign_id=campaign.id, name="B", race="H", char_class="F", inventory={"items": []}))
        try:
            db.session.commit()
            assert False, "expected unique constraint"
        except IntegrityError:
            db.session.rollback()


def test_gen_join_code_unique():
    codes = {_gen_join_code() for _ in range(1000)}
    assert len(codes) == 1000


def test_campaign_character_relationship_loads(app):
    with app.app_context():
        campaign = Campaign.query.first()
        assert isinstance(campaign.characters, list)
