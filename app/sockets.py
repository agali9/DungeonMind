"""WebSocket handlers.

Events from client:
    join_campaign   — {campaign_id}  -> joins the room for that campaign
    leave_campaign  — {campaign_id}
    submit_action   — {campaign_id, action}  -> triggers a turn (narration streams back)
    typing          — {campaign_id, is_typing}  -> typing indicator broadcast

Events to client (see narration_delta / mutation / turn_started / turn_complete /
state_update / dm_error / character_joined / shop_update in routes.py):
    all broadcast to room `campaign-<id>`.

Authentication: Flask-Login cookies are forwarded with the socket handshake,
so current_user is available. Unauthenticated sockets are rejected.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from flask import request
from flask_login import current_user
from flask_socketio import disconnect, emit, join_room, leave_room

from .extensions import db, socketio
from .models import Campaign, CampaignMembership, Character
from .routes import _process_action_sync

log = logging.getLogger(__name__)
_ACTION_RATE_WINDOW_SECONDS = 60
_ACTION_RATE_LIMIT = 30
_action_windows: dict[int, deque[float]] = defaultdict(deque)


def _room(campaign_id: int) -> str:
    return f"campaign-{campaign_id}"


def _require_auth() -> bool:
    if not current_user.is_authenticated:
        emit("auth_error", {"message": "not authenticated"})
        disconnect()
        return False
    return True


@socketio.on("connect")
def on_connect():
    if not current_user.is_authenticated:
        log.info("rejecting anonymous socket from %s", request.sid)
        return False  # reject handshake
    log.info("socket %s connected as user %d", request.sid, current_user.id)
    emit("connected", {"user_id": current_user.id})
    return None


@socketio.on("disconnect")
def on_disconnect():
    log.info("socket %s disconnected", request.sid)


@socketio.on("join_campaign")
def on_join(data):
    if not _require_auth():
        return
    campaign_id = int(data.get("campaign_id", 0))
    campaign = db.session.get(Campaign, campaign_id)
    if campaign is None:
        emit("error", {"message": "campaign not found"})
        return
    if not campaign.is_demo and CampaignMembership.query.filter_by(user_id=current_user.id, campaign_id=campaign_id).first() is None:
        emit("error", {"message": "you are not a member of this campaign"})
        return

    ch = Character.query.filter_by(user_id=current_user.id, campaign_id=campaign_id).first()
    if ch is None:
        emit("error", {"message": "no character in this campaign — create one first"})
        return

    join_room(_room(campaign_id))
    ch.is_online = True
    db.session.commit()

    emit("presence_update", {
        "character_id": ch.id,
        "name": ch.name,
        "is_online": True,
    }, to=_room(campaign_id))

    emit("joined_campaign", {
        "campaign_id": campaign_id,
        "character": ch.to_public_dict(),
    })


@socketio.on("leave_campaign")
def on_leave(data):
    if not _require_auth():
        return
    campaign_id = int(data.get("campaign_id", 0))
    leave_room(_room(campaign_id))

    ch = Character.query.filter_by(user_id=current_user.id, campaign_id=campaign_id).first()
    if ch is not None:
        ch.is_online = False
        db.session.commit()
        emit("presence_update", {
            "character_id": ch.id,
            "name": ch.name,
            "is_online": False,
        }, to=_room(campaign_id))


@socketio.on("submit_action")
def on_submit_action(data):
    """Primary multiplayer entry point. Streams narration back to the whole room."""
    if not _require_auth():
        return
    campaign_id = int(data.get("campaign_id", 0))
    campaign = db.session.get(Campaign, campaign_id)
    if campaign is None:
        emit("error", {"message": "campaign not found"})
        return
    if not campaign.is_demo and CampaignMembership.query.filter_by(user_id=current_user.id, campaign_id=campaign_id).first() is None:
        emit("error", {"message": "forbidden"})
        return
    action = (data.get("action") or "").strip()
    if not action:
        emit("error", {"message": "empty action"})
        return
    if len(action) > 800:
        emit("error", {"message": "action too long (800 char max)"})
        return

    ch = Character.query.filter_by(user_id=current_user.id, campaign_id=campaign_id).first()
    if ch is None:
        emit("error", {"message": "no character"})
        return
    if ch.hp <= 0:
        emit("dm_narration", {
            "text": f"{ch.name} lies downed on the ground, vision fading. They cannot act — an ally must stabilize them, or death will follow.",
        })
        return

    now = time.time()
    window = _action_windows[current_user.id]
    while window and now - window[0] > _ACTION_RATE_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= _ACTION_RATE_LIMIT:
        emit("rate_limit_exceeded", {"message": "Too many actions. Please wait a moment."})
        return
    window.append(now)

    queued_at_turn = (campaign.turn_index + 1) if campaign else None

    # Kick off the turn in a background task so the socket event returns quickly.
    socketio.start_background_task(_process_action_sync, campaign_id, ch.id, action)
    emit("player_acting", {"character_name": ch.name, "queued_at_turn": queued_at_turn}, to=_room(campaign_id), include_self=False)
    emit("action_accepted", {"queued_at_turn": queued_at_turn, "character_name": ch.name})


@socketio.on("typing")
def on_typing(data):
    if not _require_auth():
        return
    campaign_id = int(data.get("campaign_id", 0))
    emit("peer_typing", {
        "user_id": current_user.id,
        "is_typing": bool(data.get("is_typing")),
    }, to=_room(campaign_id), include_self=False)
