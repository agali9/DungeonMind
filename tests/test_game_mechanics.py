from __future__ import annotations

import pytest

from app.extensions import db
from app.game import (
    _advance_scene,
    _apply_damage,
    _end_combat,
    _heal,
    _move_character,
    _open_shop,
    _roll_dice,
    _start_combat,
    _update_inventory,
    execute_tool,
)
from app.models import Campaign, Character, User


@pytest.fixture
def campaign_and_char(app):
    with app.app_context():
        campaign = Campaign.query.first()
        user = User(email="gm@example.com", display_name="gm")
        user.set_password("password123")
        db.session.add(user)
        db.session.flush()
        char = Character(
            user_id=user.id,
            campaign_id=campaign.id,
            name="Arya",
            race="Human",
            char_class="Fighter",
            max_hp=14,
            hp=14,
            armor_class=14,
            dexterity=12,
            inventory={"items": []},
        )
        db.session.add(char)
        db.session.commit()
        yield campaign, char


def test_roll_dice_bounds():
    for _ in range(100):
        t = _roll_dice(20)["total"]
        assert 1 <= t <= 20


def test_roll_dice_count_modifier_bounds():
    t = _roll_dice(20, 3, 5)["total"]
    assert 8 <= t <= 65


def test_roll_dice_invalid_sides_raises():
    with pytest.raises(ValueError):
        _roll_dice(1)


def test_roll_dice_clamps_count():
    r = _roll_dice(20, 100)
    assert len(r["rolls"]) == 20


def test_apply_damage_clamps_and_downed(campaign_and_char):
    campaign, char = campaign_and_char
    res = _apply_damage(campaign, char.id, "character", 50)
    assert res["hp_after"] == 0 and res["downed"]


def test_apply_damage_negative_raises(campaign_and_char):
    campaign, char = campaign_and_char
    with pytest.raises(ValueError):
        _apply_damage(campaign, char.id, "character", -1)


def test_apply_damage_wrong_campaign_raises(app, campaign_and_char):
    campaign, char = campaign_and_char
    with app.app_context():
        other = Campaign(name="Other", world_brief="x", current_scene="y")
        db.session.add(other)
        db.session.commit()
        with pytest.raises(ValueError):
            _apply_damage(other, char.id, "character", 1)


def test_heal_does_not_exceed_max(campaign_and_char):
    campaign, char = campaign_and_char
    char.hp = 10
    out = _heal(campaign, char.id, "character", 50)
    assert out["hp_after"] == char.max_hp


def test_update_inventory_add_new_item(campaign_and_char):
    campaign, char = campaign_and_char
    out = _update_inventory(campaign, char.id, "Rope", 2)
    assert any(i["name"] == "Rope" and i["qty"] == 2 for i in out["inventory"])


def test_update_inventory_add_existing(campaign_and_char):
    campaign, char = campaign_and_char
    _update_inventory(campaign, char.id, "Rope", 1)
    out = _update_inventory(campaign, char.id, "Rope", 2)
    assert any(i["name"] == "Rope" and i["qty"] == 3 for i in out["inventory"])


def test_update_inventory_remove_to_zero_removes_item(campaign_and_char):
    campaign, char = campaign_and_char
    _update_inventory(campaign, char.id, "Rope", 1)
    out = _update_inventory(campaign, char.id, "Rope", -1)
    assert not any(i["name"].lower() == "rope" for i in out["inventory"])


def test_update_inventory_remove_missing_raises(campaign_and_char):
    campaign, char = campaign_and_char
    with pytest.raises(ValueError):
        _update_inventory(campaign, char.id, "Missing", -1)


def test_move_character_updates_fields(campaign_and_char):
    campaign, char = campaign_and_char
    out = _move_character(campaign, char.id, "tavern")
    assert char.current_location_id is not None
    assert char.map_x == out["x"]


def test_move_character_unknown_location_raises(campaign_and_char):
    campaign, char = campaign_and_char
    with pytest.raises(ValueError):
        _move_character(campaign, char.id, "not-real")


def test_open_shop_sets_mode(campaign_and_char):
    campaign, _ = campaign_and_char
    out = _open_shop(campaign, "thorne_smithy")
    assert campaign.mode == "shop"
    assert out["items"]


def test_start_combat_creates_battle(campaign_and_char):
    campaign, _ = campaign_and_char
    out = _start_combat(campaign, [{"name": "Goblin", "hp": 5, "ac": 12}])
    assert "battle_id" in out
    assert campaign.mode == "combat"
    assert out["order"]


def test_start_combat_idempotent(campaign_and_char):
    campaign, _ = campaign_and_char
    _start_combat(campaign, [{"name": "Goblin", "hp": 5, "ac": 12}])
    out = _start_combat(campaign, [{"name": "Goblin", "hp": 5, "ac": 12}])
    assert out["already_active"] is True


def test_end_combat_resets_mode(campaign_and_char):
    campaign, _ = campaign_and_char
    _start_combat(campaign, [{"name": "Goblin", "hp": 5, "ac": 12}])
    out = _end_combat(campaign, "won")
    assert out["outcome"] == "won"
    assert campaign.mode == "exploration"


def test_advance_scene_truncates(campaign_and_char):
    campaign, _ = campaign_and_char
    out = _advance_scene(campaign, "x" * 1000)
    assert len(out["scene"]) == 600


def test_execute_tool_catches_value_error(campaign_and_char):
    campaign, _ = campaign_and_char
    out = execute_tool(campaign, "move_character", {"character_id": 9999, "location_key": "tavern"})
    assert "error" in out


def test_apply_damage_participant_path(campaign_and_char):
    campaign, _ = campaign_and_char
    start = _start_combat(campaign, [{"name": "Goblin", "hp": 8, "ac": 12}])
    participant_id = start["order"][0]["id"]
    out = _apply_damage(campaign, participant_id, "participant", 2)
    assert "hp_after" in out


def test_heal_participant_path(campaign_and_char):
    campaign, _ = campaign_and_char
    start = _start_combat(campaign, [{"name": "Goblin", "hp": 8, "ac": 12}])
    participant_id = start["order"][0]["id"]
    _apply_damage(campaign, participant_id, "participant", 1)
    out = _heal(campaign, participant_id, "participant", 1)
    assert "hp_after" in out


def test_update_inventory_delta_zero_raises(campaign_and_char):
    campaign, char = campaign_and_char
    with pytest.raises(ValueError):
        _update_inventory(campaign, char.id, "Rope", 0)


def test_open_shop_unknown_raises(campaign_and_char):
    campaign, _ = campaign_and_char
    with pytest.raises(ValueError):
        _open_shop(campaign, "missing")


def test_start_combat_requires_enemies(campaign_and_char):
    campaign, _ = campaign_and_char
    with pytest.raises(ValueError):
        _start_combat(campaign, [])


def test_end_combat_no_active_battle(campaign_and_char):
    campaign, _ = campaign_and_char
    out = _end_combat(campaign, "won")
    assert out["no_active_battle"] is True


def test_execute_tool_unknown_returns_error(campaign_and_char):
    campaign, _ = campaign_and_char
    out = execute_tool(campaign, "not_a_tool", {})
    assert "error" in out
