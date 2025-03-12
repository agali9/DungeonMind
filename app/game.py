"""Deterministic game mechanics.

The LLM can *request* any of these via function calling, but every call
goes through these handlers which:

1. Validate the payload (e.g. damage must be positive, character must exist
   in this campaign).
2. Mutate SQL inside a transaction. If anything raises, the whole turn is
   rolled back and the player gets an error — never a half-applied mutation.
3. Return a compact dict describing what actually happened, which is fed
   back to the LLM so its narration matches reality.

Everything here is pure-Python side-effects-on-SQL; no LLM logic lives here.
"""

from __future__ import annotations

import logging
import random
from typing import Any

from sqlalchemy.orm import Session

from .extensions import db
from .models import (
    Battle,
    BattleParticipant,
    Campaign,
    Character,
    Location,
    Shop,
    ShopItem,
)

log = logging.getLogger(__name__)


# --- Tool declarations sent to Gemini --------------------------------------
# These are the OpenAPI-style schemas. Keep descriptions TIGHT — every token
# of schema is billed and shown to the model on every call.

TOOL_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "roll_dice",
        "description": "Roll dice. Use for skill checks, attacks, saves.",
        "parameters": {
            "type": "object",
            "properties": {
                "sides": {"type": "integer", "description": "Die size, e.g. 20 for d20"},
                "count": {"type": "integer", "description": "Number of dice, default 1"},
                "modifier": {"type": "integer", "description": "Flat bonus or penalty, default 0"},
                "reason": {"type": "string", "description": "What this roll represents (e.g. 'stealth check')"},
            },
            "required": ["sides"],
        },
    },
    {
        "name": "apply_damage",
        "description": "Deal damage to a character or battle participant. Amount must be positive.",
        "parameters": {
            "type": "object",
            "properties": {
                "target_id": {"type": "integer", "description": "Character id OR battle_participant id"},
                "target_kind": {"type": "string", "enum": ["character", "participant"]},
                "amount": {"type": "integer"},
                "source": {"type": "string", "description": "What caused the damage, for the log"},
            },
            "required": ["target_id", "target_kind", "amount"],
        },
    },
    {
        "name": "heal",
        "description": "Restore HP to a character or participant. Capped at max_hp.",
        "parameters": {
            "type": "object",
            "properties": {
                "target_id": {"type": "integer"},
                "target_kind": {"type": "string", "enum": ["character", "participant"]},
                "amount": {"type": "integer"},
            },
            "required": ["target_id", "target_kind", "amount"],
        },
    },
    {
        "name": "update_inventory",
        "description": "Add or remove an item from a character's inventory.",
        "parameters": {
            "type": "object",
            "properties": {
                "character_id": {"type": "integer"},
                "item_name": {"type": "string"},
                "delta": {"type": "integer", "description": "+1 to add, -1 to remove one"},
            },
            "required": ["character_id", "item_name", "delta"],
        },
    },
    {
        "name": "move_character",
        "description": "Move a character to a named location (see location keys in game state).",
        "parameters": {
            "type": "object",
            "properties": {
                "character_id": {"type": "integer"},
                "location_key": {"type": "string"},
            },
            "required": ["character_id", "location_key"],
        },
    },
    {
        "name": "open_shop",
        "description": "Signal that the party is entering a shop. Opens shop UI for all players.",
        "parameters": {
            "type": "object",
            "properties": {"shop_key": {"type": "string"}},
            "required": ["shop_key"],
        },
    },
    {
        "name": "start_combat",
        "description": "Begin combat with one or more enemies. Rolls initiative and opens battle UI.",
        "parameters": {
            "type": "object",
            "properties": {
                "enemies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "hp": {"type": "integer"},
                            "ac": {"type": "integer"},
                        },
                        "required": ["name", "hp"],
                    },
                },
            },
            "required": ["enemies"],
        },
    },
    {
        "name": "end_combat",
        "description": "End the current battle. outcome: 'won' | 'lost' | 'fled'.",
        "parameters": {
            "type": "object",
            "properties": {"outcome": {"type": "string", "enum": ["won", "lost", "fled"]}},
            "required": ["outcome"],
        },
    },
    {
        "name": "advance_scene",
        "description": "Update the campaign's current scene description (short, 1-2 sentences).",
        "parameters": {
            "type": "object",
            "properties": {"scene": {"type": "string"}},
            "required": ["scene"],
        },
    },
]


# --- Handlers ---------------------------------------------------------------

def _get_character(campaign: Campaign, character_id: int) -> Character:
    ch = Character.query.filter_by(id=character_id, campaign_id=campaign.id).first()
    if ch is None:
        raise ValueError(f"Character {character_id} not in this campaign")
    return ch


def _get_participant(campaign: Campaign, participant_id: int) -> BattleParticipant:
    bp = (
        db.session.query(BattleParticipant)
        .join(Battle, BattleParticipant.battle_id == Battle.id)
        .filter(BattleParticipant.id == participant_id, Battle.campaign_id == campaign.id)
        .first()
    )
    if bp is None:
        raise ValueError(f"Battle participant {participant_id} not found")
    return bp


def _roll_dice(sides: int, count: int = 1, modifier: int = 0, reason: str = "") -> dict[str, Any]:
    if sides < 2 or sides > 100:
        raise ValueError("sides must be 2..100")
    count = max(1, min(count, 20))
    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier
    return {"rolls": rolls, "modifier": modifier, "total": total, "reason": reason, "expression": f"{count}d{sides}{modifier:+d}"}


def _apply_damage(campaign: Campaign, target_id: int, target_kind: str, amount: int, source: str = "") -> dict[str, Any]:
    if amount < 0:
        raise ValueError("amount must be non-negative; use heal for restoration")
    if target_kind == "character":
        ch = _get_character(campaign, target_id)
        before = ch.hp
        ch.hp = max(0, ch.hp - amount)
        result = {"name": ch.name, "hp_before": before, "hp_after": ch.hp, "max_hp": ch.max_hp, "downed": ch.hp == 0, "source": source}
        if ch.hp <= 0:
            result["downed"] = True
            result["death_message"] = f"{ch.name} has fallen and lies dying."
        return result
    elif target_kind == "participant":
        bp = _get_participant(campaign, target_id)
        before = bp.hp
        bp.hp = max(0, bp.hp - amount)
        return {"name": bp.display_name, "hp_before": before, "hp_after": bp.hp, "max_hp": bp.max_hp, "downed": bp.hp == 0, "is_enemy": bp.is_enemy, "source": source}
    raise ValueError(f"unknown target_kind {target_kind}")


def _heal(campaign: Campaign, target_id: int, target_kind: str, amount: int) -> dict[str, Any]:
    if amount < 0:
        raise ValueError("amount must be non-negative")
    if target_kind == "character":
        ch = _get_character(campaign, target_id)
        before = ch.hp
        ch.hp = min(ch.max_hp, ch.hp + amount)
        return {"name": ch.name, "hp_before": before, "hp_after": ch.hp, "max_hp": ch.max_hp}
    bp = _get_participant(campaign, target_id)
    before = bp.hp
    bp.hp = min(bp.max_hp, bp.hp + amount)
    return {"name": bp.display_name, "hp_before": before, "hp_after": bp.hp, "max_hp": bp.max_hp}


def _update_inventory(campaign: Campaign, character_id: int, item_name: str, delta: int) -> dict[str, Any]:
    if delta == 0:
        raise ValueError("delta must be non-zero")
    ch = _get_character(campaign, character_id)
    # Work on a copy, reassign at end — SQLAlchemy won't notice mutations to
    # existing dicts on a JSON column without flag_modified, so we rebuild.
    inv = dict(ch.inventory or {"items": []})
    items: list[dict[str, Any]] = list(inv.get("items", []))
    found = next((i for i in items if i["name"].lower() == item_name.lower()), None)
    if found is None:
        if delta < 0:
            raise ValueError(f"{ch.name} does not have {item_name}")
        items.append({"name": item_name, "qty": delta})
    else:
        found["qty"] += delta
        if found["qty"] <= 0:
            target_name = item_name.lower()
            items = [i for i in items if str(i.get("name", "")).lower() != target_name]
    inv["items"] = items
    ch.inventory = inv
    return {"character": ch.name, "item": item_name, "delta": delta, "inventory": items}


def _move_character(campaign: Campaign, character_id: int, location_key: str) -> dict[str, Any]:
    ch = _get_character(campaign, character_id)
    loc = Location.query.filter_by(campaign_id=campaign.id, key=location_key).first()
    if loc is None:
        raise ValueError(f"location '{location_key}' does not exist")
    ch.current_location_id = loc.id
    ch.map_x = loc.x
    ch.map_y = loc.y
    return {"character": ch.name, "location": loc.display_name, "x": loc.x, "y": loc.y}


def _open_shop(campaign: Campaign, shop_key: str) -> dict[str, Any]:
    shop = Shop.query.filter_by(campaign_id=campaign.id, key=shop_key).first()
    if shop is None:
        raise ValueError(f"shop '{shop_key}' does not exist")
    campaign.mode = "shop"
    return {
        "shop_id": shop.id,
        "shop_key": shop.key,
        "name": shop.name,
        "shopkeeper": shop.shopkeeper,
        "items": [
            {"id": i.id, "name": i.name, "description": i.description, "price": i.price,
             "stock": i.stock, "kind": i.kind, "effect": i.effect}
            for i in shop.items
        ],
    }


def _start_combat(campaign: Campaign, enemies: list[dict[str, Any]]) -> dict[str, Any]:
    if not enemies:
        raise ValueError("at least one enemy required")
    if campaign.mode == "combat":
        # idempotent: return current battle rather than starting another
        active = Battle.query.filter_by(campaign_id=campaign.id, state="active").first()
        if active:
            return {"battle_id": active.id, "already_active": True}

    battle = Battle(campaign_id=campaign.id, state="active", round_num=1)
    db.session.add(battle)
    db.session.flush()

    # Players roll initiative d20 + dex_mod (simplified)
    for ch in campaign.characters:
        if ch.hp <= 0:
            continue
        init = random.randint(1, 20) + (ch.dexterity - 10) // 2
        db.session.add(BattleParticipant(
            battle_id=battle.id, character_id=ch.id, is_enemy=False,
            hp=ch.hp, max_hp=ch.max_hp, ac=ch.armor_class, initiative=init,
        ))

    for e in enemies:
        init = random.randint(1, 20)
        db.session.add(BattleParticipant(
            battle_id=battle.id, is_enemy=True, enemy_name=e["name"],
            hp=int(e["hp"]), max_hp=int(e["hp"]), ac=int(e.get("ac", 12)), initiative=init,
        ))

    campaign.mode = "combat"
    db.session.flush()

    # First participant by initiative goes first
    first = sorted(battle.participants, key=lambda p: -p.initiative)[0]
    battle.active_participant_id = first.id
    return {"battle_id": battle.id, "round": 1, "order": [
        {"id": p.id, "name": p.display_name, "is_enemy": p.is_enemy, "initiative": p.initiative}
        for p in sorted(battle.participants, key=lambda p: -p.initiative)
    ]}


def _end_combat(campaign: Campaign, outcome: str) -> dict[str, Any]:
    battle = Battle.query.filter_by(campaign_id=campaign.id, state="active").first()
    if battle is None:
        return {"no_active_battle": True}
    battle.state = outcome
    campaign.mode = "exploration"
    # Sync surviving character HP back to Character rows (combat is source of
    # truth during a battle; Characters resume being SoT after).
    for p in battle.participants:
        if not p.is_enemy and p.character is not None:
            p.character.hp = p.hp
    return {"outcome": outcome, "battle_id": battle.id}


def _advance_scene(campaign: Campaign, scene: str) -> dict[str, Any]:
    campaign.current_scene = scene[:600]
    return {"scene": campaign.current_scene}


# --- Dispatcher -------------------------------------------------------------

def execute_tool(campaign: Campaign, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call from the LLM to its handler.

    Returns a dict with either the result or {"error": ...}. Caller decides
    whether to commit the transaction or roll back.
    """
    try:
        if name == "roll_dice":
            return _roll_dice(int(args["sides"]), int(args.get("count", 1)),
                              int(args.get("modifier", 0)), str(args.get("reason", "")))
        if name == "apply_damage":
            return _apply_damage(campaign, int(args["target_id"]), str(args["target_kind"]),
                                 int(args["amount"]), str(args.get("source", "")))
        if name == "heal":
            return _heal(campaign, int(args["target_id"]), str(args["target_kind"]), int(args["amount"]))
        if name == "update_inventory":
            return _update_inventory(campaign, int(args["character_id"]),
                                     str(args["item_name"]), int(args["delta"]))
        if name == "move_character":
            return _move_character(campaign, int(args["character_id"]), str(args["location_key"]))
        if name == "open_shop":
            return _open_shop(campaign, str(args["shop_key"]))
        if name == "start_combat":
            return _start_combat(campaign, list(args["enemies"]))
        if name == "end_combat":
            return _end_combat(campaign, str(args["outcome"]))
        if name == "advance_scene":
            return _advance_scene(campaign, str(args["scene"]))
        return {"error": f"unknown tool {name}"}
    except (KeyError, ValueError, TypeError) as e:
        log.warning("tool %s failed: %s", name, e)
        return {"error": str(e)}
