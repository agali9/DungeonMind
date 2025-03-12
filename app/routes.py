"""Game REST endpoints.

WebSocket events are in app/sockets.py. These HTTP routes handle:
- The lobby/game HTML pages
- Character creation
- Shop transactions (must be HTTP for guaranteed ACID; we don't want
  a dropped socket mid-purchase to leave state indeterminate)
- Battle player actions
- State snapshots for reconnecting clients
- Observability metrics

Auth: everything except the page routes that Flask-Login will redirect
is @login_required.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required
from sqlalchemy import select, text

from .cache import cache
from .config import config as app_config
from .extensions import db, limiter, socketio
from .gemini_service import gemini_service
from .models import (
    Battle,
    BattleParticipant,
    Campaign,
    CampaignMembership,
    Character,
    Location,
    Shop,
    Turn,
    User,
)
from .seed import clone_template_campaign

bp = Blueprint("game", __name__)
log = logging.getLogger(__name__)


_PIN_COLORS = ["#e0b46a", "#6aa9e0", "#b46ae0", "#e06a6a", "#6ae0a9", "#e0d66a"]

_STARTER_CLASSES = {
    "fighter": {"hp": 14, "ac": 14, "inv": [
        {"name": "Short Sword", "qty": 1, "desc": "A reliable steel blade.", "type": "weapon", "damage": "1d6"},
        {"name": "Chain Shirt", "qty": 1, "desc": "Sturdy linked armor.", "type": "armor"},
        {"name": "Iron Torch", "qty": 2, "desc": "Burns for 8 hours.", "type": "misc"},
        {"name": "Rations", "qty": 3, "desc": "Dried meat and hardtack.", "type": "misc"},
        {"name": "Healing Potion", "qty": 1, "desc": "Restores 2d4+2 HP.", "type": "potion", "heal": "2d4+2"},
    ]},
    "rogue": {"hp": 10, "ac": 13, "inv": [
        {"name": "Hand Axe", "qty": 1, "desc": "Light and throwable.", "type": "weapon", "damage": "1d6"},
        {"name": "Lockpicks", "qty": 1, "desc": "A set of fine steel picks.", "type": "tool"},
        {"name": "Dagger", "qty": 2, "desc": "Concealable blade.", "type": "weapon", "damage": "1d4"},
        {"name": "Dark Cloak", "qty": 1, "desc": "+1 to stealth checks.", "type": "armor"},
        {"name": "Rations", "qty": 3, "desc": "Dried meat and hardtack.", "type": "misc"},
    ]},
    "cleric": {"hp": 12, "ac": 13, "inv": [
        {"name": "Wooden Mace", "qty": 1, "desc": "A blessed weapon.", "type": "weapon", "damage": "1d6"},
        {"name": "Holy Symbol", "qty": 1, "desc": "Focus for divine spells.", "type": "focus"},
        {"name": "Healing Potion", "qty": 2, "desc": "Restores 2d4+2 HP.", "type": "potion", "heal": "2d4+2"},
        {"name": "Prayer Beads", "qty": 1, "desc": "+1 to WIS saving throws.", "type": "misc"},
        {"name": "Rations", "qty": 3, "desc": "Dried meat and hardtack.", "type": "misc"},
    ]},
    "wizard": {"hp": 8, "ac": 11, "inv": [
        {"name": "Quarterstaff", "qty": 1, "desc": "A gnarled wooden staff.", "type": "weapon", "damage": "1d6"},
        {"name": "Spellbook", "qty": 1, "desc": "Contains your known spells.", "type": "focus"},
        {"name": "Arcane Focus", "qty": 1, "desc": "A crystal orb for spell casting.", "type": "focus"},
        {"name": "Scroll of Magic Missile", "qty": 2, "desc": "Deals 3x1d4+1 force damage.", "type": "scroll"},
        {"name": "Rations", "qty": 2, "desc": "Dried meat and hardtack.", "type": "misc"},
    ]},
    "ranger": {"hp": 11, "ac": 13, "inv": [
        {"name": "Longbow", "qty": 1, "desc": "Range 150ft, 1d8 damage.", "type": "weapon", "damage": "1d8"},
        {"name": "Quiver", "qty": 1, "desc": "Holds 20 arrows.", "type": "misc"},
        {"name": "Arrows", "qty": 20, "desc": "Standard fletched arrows.", "type": "ammo"},
        {"name": "Short Sword", "qty": 1, "desc": "Backup melee weapon.", "type": "weapon", "damage": "1d6"},
        {"name": "Herbalism Kit", "qty": 1, "desc": "Craft healing poultices.", "type": "tool"},
        {"name": "Rations", "qty": 3, "desc": "Dried meat and hardtack.", "type": "misc"},
    ]},
    "paladin": {"hp": 13, "ac": 15, "inv": [
        {"name": "Longsword", "qty": 1, "desc": "A blessed blade, 1d8 damage.", "type": "weapon", "damage": "1d8"},
        {"name": "Shield", "qty": 1, "desc": "+2 to AC.", "type": "armor"},
        {"name": "Holy Symbol", "qty": 1, "desc": "Focus for divine spells.", "type": "focus"},
        {"name": "Healing Potion", "qty": 2, "desc": "Restores 2d4+2 HP.", "type": "potion", "heal": "2d4+2"},
        {"name": "Rations", "qty": 3, "desc": "Dried meat and hardtack.", "type": "misc"},
    ]},
}

_RACE_BONUS_ITEMS = {
    "Human": {"name": "Lucky Coin", "qty": 1, "desc": "Humans are resourceful. +1 to one check per day.", "type": "misc"},
    "Elf": {"name": "Elven Waybread", "qty": 2, "desc": "Nourishing and light. Keeps you alert.", "type": "misc"},
    "Dwarf": {"name": "Dwarven Ale", "qty": 1, "desc": "Stout enough to resist poison.", "type": "misc"},
    "Halfling": {"name": "Halfling Pipe", "qty": 1, "desc": "Calming. +1 to CHA checks when relaxed.", "type": "misc"},
    "Half-Orc": {"name": "Bone Talisman", "qty": 1, "desc": "Ancestral ward. Once per day avoid being downed.", "type": "misc"},
    "Tiefling": {"name": "Infernal Charm", "qty": 1, "desc": "Radiates subtle menace. Advantage on intimidation.", "type": "misc"},
}


def _react_build_dir() -> Path:
    return Path(current_app.static_folder) / "react"


def _serve_react_index() -> Response:
    return send_from_directory(_react_build_dir(), "index.html")


def _has_react_build() -> bool:
    return (_react_build_dir() / "index.html").exists()


def _has_membership(user_id: int, campaign_id: int) -> bool:
    return CampaignMembership.query.filter_by(user_id=user_id, campaign_id=campaign_id).first() is not None


def _require_membership(campaign_id: int) -> Campaign:
    campaign = db.session.get(Campaign, campaign_id) or abort(404)
    if campaign.is_demo:
        return campaign
    if not _has_membership(current_user.id, campaign_id):
        abort(403)
    return campaign


# --- Pages -----------------------------------------------------------------

@bp.route("/")
def index():
    if _has_react_build():
        return _serve_react_index()
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    memberships = CampaignMembership.query.filter_by(user_id=current_user.id).all()
    member_campaign_ids = [m.campaign_id for m in memberships]
    campaigns = (
        Campaign.query
        .filter(Campaign.id.in_(member_campaign_ids), Campaign.is_demo.is_(False))
        .order_by(Campaign.id.desc())
        .all()
        if member_campaign_ids
        else []
    )
    my_chars = {
        c.campaign_id: c
        for c in Character.query.filter(
            Character.user_id == current_user.id,
            Character.campaign_id.in_(member_campaign_ids),
        ).all()
    }
    return render_template(
        "home.html",
        campaigns=campaigns,
        memberships={m.campaign_id: m for m in memberships},
        my_chars=my_chars,
        classes=_STARTER_CLASSES,
    )


@bp.route("/lobby")
def lobby():
    return redirect("/", code=301)


@bp.get("/campaigns/<int:campaign_id>/character/new")
@login_required
def character_new(campaign_id: int):
    campaign = _require_membership(campaign_id)
    existing = Character.query.filter_by(user_id=current_user.id, campaign_id=campaign_id).first()
    if existing is not None:
        return redirect(f"/campaigns/{campaign_id}/play")
    if _has_react_build():
        return redirect(f"/campaigns/{campaign_id}/character/new")
    return render_template(
        "character_new.html",
        campaign=campaign,
        classes=_STARTER_CLASSES,
    )




@bp.route("/play/<int:campaign_id>")
@login_required
def play(campaign_id: int):
    campaign = _require_membership(campaign_id)
    my_char = Character.query.filter_by(user_id=current_user.id, campaign_id=campaign_id).first()
    if my_char is None:
        flash("Create a character first to join this campaign.", "warning")
        return redirect(url_for("game.lobby"))
    if _has_react_build():
        return redirect(f"/campaigns/{campaign_id}/play")
    is_owner = campaign.owner_id == current_user.id
    return render_template("play.html", campaign=campaign, my_char=my_char, is_owner=is_owner)


# --- Character creation ----------------------------------------------------

@bp.get("/api/me")
def me():
    if current_user.is_authenticated:
        return jsonify({"id": current_user.id, "display_name": current_user.display_name})
    return jsonify({"error": "not authenticated"}), 401


@bp.get("/api/campaigns")
@login_required
def list_campaigns():
    memberships = CampaignMembership.query.filter_by(user_id=current_user.id).all()
    result = []
    for membership in memberships:
        campaign = membership.campaign
        my_character = Character.query.filter_by(
            user_id=current_user.id,
            campaign_id=campaign.id,
        ).first()
        result.append({
            "id": campaign.id,
            "name": campaign.name,
            "join_code": campaign.join_code,
            "turn_index": campaign.turn_index,
            "mode": campaign.mode,
            "role": membership.role,
            "character": my_character.to_public_dict() if my_character else None,
        })
    return jsonify(result)

@bp.post("/api/campaigns")
@login_required
def create_campaign():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "campaign name required"}), 400
    owner = db.session.get(User, current_user.id)
    campaign = clone_template_campaign(owner, name)
    return jsonify({
        "campaign": {
            "id": campaign.id,
            "name": campaign.name,
            "join_code": campaign.join_code,
        }
    }), 201


@bp.post("/api/campaigns/join")
@login_required
def join_campaign():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    if len(code) < 3:
        return jsonify({"error": "join code required"}), 400
    campaign = Campaign.query.filter_by(join_code=code).first()
    if campaign is None:
        return jsonify({"error": "campaign not found"}), 404
    membership = CampaignMembership.query.filter_by(user_id=current_user.id, campaign_id=campaign.id).first()
    if membership is None and not campaign.is_demo:
        db.session.add(CampaignMembership(user_id=current_user.id, campaign_id=campaign.id, role="player"))
        db.session.commit()
    my_char = Character.query.filter_by(user_id=current_user.id, campaign_id=campaign.id).first()
    return jsonify({
        "campaign": {"id": campaign.id, "name": campaign.name, "join_code": campaign.join_code},
        "has_character": my_char is not None,
    })

@bp.post("/api/campaigns/<int:campaign_id>/characters")
@login_required
def create_character(campaign_id: int):
    campaign = _require_membership(campaign_id)
    if Character.query.filter_by(user_id=current_user.id, campaign_id=campaign_id).first():
        return jsonify({"error": "You already have a character in this campaign."}), 400

    data = request.get_json(silent=True) or request.form
    name = (data.get("name") or "").strip()
    race = (data.get("race") or "Human").strip()
    klass = (data.get("class") or "fighter").strip().lower()
    if klass not in _STARTER_CLASSES:
        return jsonify({"error": f"Unknown class {klass}"}), 400
    if not name or len(name) > 64:
        return jsonify({"error": "Name required (1–64 chars)"}), 400

    klass_info = dict(_STARTER_CLASSES[klass])

    def _parse_stat(key: str) -> int:
        raw = data.get(key, 10)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 10
        return max(3, min(25, value))

    strength = _parse_stat("strength")
    dexterity = _parse_stat("dexterity")
    constitution = _parse_stat("constitution")
    intelligence = _parse_stat("intelligence")
    wisdom = _parse_stat("wisdom")
    charisma = _parse_stat("charisma")

    max_hp = klass_info["hp"]
    armor_class = klass_info["ac"]
    try:
        incoming_hp = int(data.get("max_hp", max_hp))
        if incoming_hp > 0:
            max_hp = incoming_hp
    except (TypeError, ValueError):
        pass
    try:
        incoming_ac = int(data.get("armor_class", armor_class))
        if incoming_ac > 0:
            armor_class = incoming_ac
    except (TypeError, ValueError):
        pass
    existing_count = Character.query.filter_by(campaign_id=campaign_id).count()
    pin = _PIN_COLORS[existing_count % len(_PIN_COLORS)]

    # Starting location: tavern if it exists.
    tavern = Location.query.filter_by(campaign_id=campaign_id, key="tavern").first()

    items = list(klass_info["inv"])
    bonus_item = _RACE_BONUS_ITEMS.get(race)
    if bonus_item:
        items.append(dict(bonus_item))

    ch = Character(
        user_id=current_user.id,
        campaign_id=campaign_id,
        name=name,
        race=race,
        char_class=klass.capitalize(),
        max_hp=max_hp, hp=max_hp, armor_class=armor_class,
        strength=strength, dexterity=dexterity, constitution=constitution,
        intelligence=intelligence, wisdom=wisdom, charisma=charisma,
        inventory={"items": items},
        pin_color=pin,
        map_x=tavern.x if tavern else 500.0,
        map_y=tavern.y if tavern else 500.0,
        current_location_id=tavern.id if tavern else None,
    )
    db.session.add(ch)
    db.session.commit()

    socketio.emit("character_joined", {"character": ch.to_public_dict()}, to=f"campaign-{campaign_id}")
    return jsonify({"character": ch.to_public_dict()}), 201


# --- State snapshot --------------------------------------------------------

def _battle_to_dict(battle: Battle | None) -> dict[str, Any] | None:
    if battle is None:
        return None
    return {
        "id": battle.id,
        "state": battle.state,
        "round": battle.round_num,
        "active_participant_id": battle.active_participant_id,
        "participants": [
            {
                "id": p.id,
                "name": p.display_name,
                "is_enemy": p.is_enemy,
                "hp": p.hp, "max_hp": p.max_hp, "ac": p.ac,
                "initiative": p.initiative,
                "has_acted": p.has_acted_this_round,
                "character_id": p.character_id,
            }
            for p in sorted(battle.participants, key=lambda x: -x.initiative)
        ],
    }


@bp.get("/api/campaigns/<int:campaign_id>/state")
@login_required
def state(campaign_id: int):
    campaign = _require_membership(campaign_id)
    active_battle = Battle.query.filter_by(campaign_id=campaign_id, state="active").first()

    return jsonify({
        "campaign": {
            "id": campaign.id, "name": campaign.name,
            "scene": campaign.current_scene, "mode": campaign.mode,
            "turn_index": campaign.turn_index,
        },
        "locations": [
            {"id": l.id, "key": l.key, "name": l.display_name, "description": l.description,
             "x": l.x, "y": l.y, "icon": l.icon, "discovered": l.discovered}
            for l in campaign.locations
        ],
        "characters": [c.to_public_dict() for c in campaign.characters],
        "battle": _battle_to_dict(active_battle),
        "my_character_id": (Character.query
                            .filter_by(user_id=current_user.id, campaign_id=campaign_id)
                            .with_entities(Character.id).scalar()),
    })


# --- Shop ------------------------------------------------------------------

@bp.get("/api/campaigns/<int:campaign_id>/shops/<shop_key>")
@login_required
def get_shop(campaign_id: int, shop_key: str):
    _require_membership(campaign_id)
    shop = Shop.query.filter_by(campaign_id=campaign_id, key=shop_key).first() or abort(404)
    return jsonify({
        "id": shop.id, "key": shop.key, "name": shop.name, "shopkeeper": shop.shopkeeper,
        "items": [
            {"id": i.id, "name": i.name, "description": i.description,
             "price": i.price, "stock": i.stock, "kind": i.kind}
            for i in shop.items
        ],
    })


@bp.post("/api/shops/<int:shop_id>/buy")
@login_required
@limiter.limit("10/minute", key_func=lambda: str(current_user.id))
def buy_item(shop_id: int):
    data = request.get_json(silent=True) or {}
    item_id = int(data.get("item_id") or 0)

    # Lock the character and shop_item rows for the duration of the
    # transaction so two concurrent buyers can't drain the last item.
    with db.session.begin_nested():
        shop = db.session.get(Shop, shop_id) or abort(404)
        if not (shop.campaign.is_demo or _has_membership(current_user.id, shop.campaign_id)):
            return jsonify({"error": "forbidden"}), 403
        item = next((i for i in shop.items if i.id == item_id), None)
        if item is None:
            return jsonify({"error": "item not found"}), 404

        ch = Character.query.filter_by(user_id=current_user.id, campaign_id=shop.campaign_id).first()
        if ch is None:
            return jsonify({"error": "no character in this campaign"}), 400
        if item.stock <= 0:
            return jsonify({"error": "out of stock"}), 409
        if ch.gold < item.price:
            return jsonify({"error": "insufficient gold"}), 402

        item.stock -= 1
        ch.gold -= item.price
        inv = dict(ch.inventory or {"items": []})
        items = list(inv.get("items", []))
        found = next((i for i in items if i["name"].lower() == item.name.lower()), None)
        if found:
            found["qty"] += 1
        else:
            items.append({"name": item.name, "qty": 1})
        inv["items"] = items
        ch.inventory = inv
    db.session.commit()

    socketio.emit("shop_update", {
        "shop_id": shop.id,
        "item_id": item.id,
        "new_stock": item.stock,
        "buyer": ch.to_public_dict(),
    }, to=f"campaign-{shop.campaign_id}")

    return jsonify({"character": ch.to_public_dict(), "new_stock": item.stock})


# --- Battle actions --------------------------------------------------------

@bp.post("/api/battles/<int:battle_id>/action")
@login_required
def battle_action(battle_id: int):
    """A player's combat action. Narrated by Gemini via the same turn pipeline."""
    battle = db.session.get(Battle, battle_id) or abort(404)
    if not (battle.campaign.is_demo or _has_membership(current_user.id, battle.campaign_id)):
        return jsonify({"error": "forbidden"}), 403
    if battle.state != "active":
        return jsonify({"error": "battle is not active"}), 409

    data = request.get_json(silent=True) or {}
    action_text = (data.get("action") or "").strip()
    target_id = data.get("target_id")
    if not action_text:
        return jsonify({"error": "action text required"}), 400

    ch = Character.query.filter_by(user_id=current_user.id, campaign_id=battle.campaign_id).first()
    if ch is None:
        return jsonify({"error": "no character in this campaign"}), 400

    # Actions are funnelled through the same WebSocket pipeline so both REST
    # and WS callers get identical state. Emit it via socketio here to trigger
    # the handler.
    phrasing = action_text
    if target_id:
        target = db.session.get(BattleParticipant, int(target_id))
        if target and target.battle_id == battle.id:
            phrasing = f"{action_text} targeting {target.display_name} (participant id {target.id})"

    socketio.start_background_task(
        _process_action_sync, battle.campaign_id, ch.id, phrasing,
    )
    return jsonify({"status": "queued"}), 202


# --- Observability ---------------------------------------------------------

@bp.get("/api/metrics")
@login_required
def metrics():
    last_50 = Turn.query.order_by(Turn.id.desc()).limit(50).all()
    if last_50:
        avg_latency = sum(t.latency_ms for t in last_50) / len(last_50)
        p95_latency = sorted(t.latency_ms for t in last_50)[int(len(last_50) * 0.95) - 1]
        total_tokens_in = sum(t.tokens_in for t in last_50)
        total_tokens_out = sum(t.tokens_out for t in last_50)
    else:
        avg_latency = p95_latency = total_tokens_in = total_tokens_out = 0

    return jsonify({
        "cache": cache.stats(),
        "gemini_ok": gemini_service.gemini_ok,
        "turns": {
            "sample_size": len(last_50),
            "avg_latency_ms": round(avg_latency, 1),
            "p95_latency_ms": p95_latency,
            "tokens_in_sum": total_tokens_in,
            "tokens_out_sum": total_tokens_out,
        },
    })


@bp.get("/healthz")
def healthz():
    db_ok = True
    redis_ok = bool(cache._redis_ok)
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False

    if cache._redis is not None:
        try:
            cache._redis.ping()
            redis_ok = True
        except Exception:  # noqa: BLE001
            redis_ok = False

    payload = {
        "status": "ok" if all([gemini_service.gemini_ok, redis_ok, db_ok]) else "degraded",
        "gemini_ok": gemini_service.gemini_ok,
        "redis_ok": redis_ok,
        "db_ok": db_ok,
    }
    return jsonify(payload), (200 if payload["status"] == "ok" else 503)


@bp.get("/api/campaigns/<int:campaign_id>/transcript.md")
@login_required
def campaign_transcript(campaign_id: int):
    campaign = _require_membership(campaign_id)

    lines = [
        f"# {campaign.name} transcript",
        "",
        f"Mode: {campaign.mode}",
        f"Current scene: {campaign.current_scene}",
        "",
        "## Memoirs",
    ]
    for memoir in sorted(campaign.memoirs, key=lambda x: x.index):
        lines.extend([
            f"### Memoir {memoir.index} (turns {memoir.covers_turn_from}-{memoir.covers_turn_to})",
            memoir.summary,
            "",
        ])
    lines.append("## Turn log")
    for turn in sorted(campaign.turns, key=lambda t: t.index):
        actor = turn.character.name if turn.character else "Party"
        lines.extend([
            f"### Turn {turn.index}",
            f"**{actor}**: {turn.player_action}",
            "",
            turn.dm_narration,
            "",
        ])
        for mutation in turn.mutations or []:
            lines.append(f"- Mutation `{mutation.get('name')}`: `{mutation.get('result')}`")
        lines.append("")

    transcript = "\n".join(lines).encode("utf-8")
    return Response(
        transcript,
        mimetype="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="campaign-{campaign_id}-transcript.md"',
        },
    )


# --- Shared turn processor -------------------------------------------------

def _process_action_sync(campaign_id: int, character_id: int, action: str) -> None:
    """Run a full turn in a background task so the HTTP request returns fast.
    This function is called from both REST and WebSocket paths.

    NOTE: We import the Flask app from the current app context via socketio's
    background task machinery. Because we set `app.app_context()` in the
    socketio handler, `db.session` is valid here.
    """
    from .app_context import get_app  # lazy import to avoid circular
    app = get_app()
    with app.app_context():
        _run_turn_and_broadcast(campaign_id, character_id, action)


def _run_turn_and_broadcast(campaign_id: int, character_id: int, action: str) -> None:
    campaign = db.session.get(Campaign, campaign_id)
    actor = db.session.get(Character, character_id)
    if not campaign or not actor:
        return

    room = f"campaign-{campaign_id}"
    log.info("turn started", extra={"campaign_id": campaign_id, "user_id": actor.user_id})
    narration_accum: list[str] = []
    mutations: list[dict[str, Any]] = []
    tokens_in = tokens_out = latency_ms = 0
    cache_hit = False

    # Announce to everyone that a turn has started.
    socketio.emit("turn_started", {
        "character_id": actor.id,
        "character_name": actor.name,
        "action": action,
    }, to=room)

    try:
        for event, payload in gemini_service.run_turn(campaign, actor, action):
            if event == "narration_delta":
                narration_accum.append(payload)
                socketio.emit("narration_delta", {"text": payload}, to=room)
            elif event == "mutation":
                mutations.append(payload)
                socketio.emit("mutation", payload, to=room)
            elif event == "error":
                socketio.emit("dm_error", {"message": payload}, to=room)
            elif event == "turn_complete":
                tokens_in = payload["tokens_in"]
                tokens_out = payload["tokens_out"]
                latency_ms = payload["latency_ms"]
                cache_hit = payload["cache_hit"]
    except Exception as exc:  # noqa: BLE001
        log.exception(
            "turn processing failed campaign_id=%s character_id=%s action=%r",
            campaign_id,
            character_id,
            action,
        )
        message = str(exc) if app_config.FLASK_ENV == "development" else "Turn failed — please retry."
        socketio.emit("dm_error", {"message": message}, to=room)
        db.session.rollback()
        return

    # Persist the turn atomically.
    campaign.turn_index += 1
    turn = Turn(
        campaign_id=campaign.id,
        character_id=actor.id,
        index=campaign.turn_index,
        player_action=action,
        dm_narration="".join(narration_accum),
        mutations=mutations,
        tokens_in=tokens_in, tokens_out=tokens_out,
        latency_ms=latency_ms, cache_hit=cache_hit,
    )
    db.session.add(turn)
    db.session.commit()

    # Broadcast the authoritative post-turn state so all clients converge.
    socketio.emit("state_update", {
        "turn_index": campaign.turn_index,
        "mode": campaign.mode,
        "scene": campaign.current_scene,
        "characters": [c.to_public_dict() for c in campaign.characters],
        "battle": _battle_to_dict(
            Battle.query.filter_by(campaign_id=campaign.id, state="active").first()
        ),
    }, to=room)

    socketio.emit("turn_complete", {
        "turn_index": campaign.turn_index,
        "latency_ms": latency_ms,
        "cache_hit": cache_hit,
    }, to=room)
    log.info("turn complete", extra={"campaign_id": campaign_id, "user_id": actor.user_id})

    # Background: check if we need to compact history.
    socketio.start_background_task(_compact_safely, campaign.id)


def _compact_safely(campaign_id: int) -> None:
    from .app_context import get_app
    app = get_app()
    with app.app_context():
        campaign = db.session.get(Campaign, campaign_id)
        if campaign is None:
            return
        try:
            m = gemini_service.compact_if_needed(campaign)
            if m:
                log.info("compacted memoir %d for campaign %d", m.index, campaign_id)
        except Exception:  # noqa: BLE001
            log.exception("compaction error")
