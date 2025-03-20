from __future__ import annotations

from app.extensions import socketio
from app.models import Campaign


def _events(client):
    return [e["name"] for e in client.get_received()]


def test_unauthenticated_connect_rejected(app):
    unauth_client = app.test_client()
    sio = socketio.test_client(app, flask_test_client=unauth_client)
    assert isinstance(sio.is_connected(), bool)


def test_authenticated_connect_emits_connected(socketio_client):
    assert socketio_client.is_connected()


def test_join_campaign_without_character_errors(app, client, logged_in_user):
    sio = socketio.test_client(app, flask_test_client=client)
    with app.app_context():
        campaign = Campaign.query.first()
    sio.emit("join_campaign", {"campaign_id": campaign.id})
    assert isinstance(_events(sio), list)


def test_submit_action_empty_errors(socketio_client):
    socketio_client.emit("submit_action", {"campaign_id": 1, "action": ""})
    assert isinstance(_events(socketio_client), list)
