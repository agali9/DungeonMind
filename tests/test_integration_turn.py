from __future__ import annotations

from unittest.mock import Mock

from app.gemini_service import gemini_service
from app.routes import _run_turn_and_broadcast
from app.models import Campaign, Turn


def test_full_turn_pipeline(app, client, monkeypatch):
    client.post("/auth/register", data={"email": "int@example.com", "display_name": "int", "password": "password123"})
    with app.app_context():
        campaign = Campaign.query.first()
    client.post(
        f"/api/campaigns/{campaign.id}/characters",
        json={"name": "Arya", "race": "Human", "class": "fighter"},
        headers={"X-Requested-With": "Embervale"},
    )
    def fake_run_turn(_campaign, _actor, _action):
        yield ("narration_delta", "One.")
        yield ("narration_delta", " Two.")
        yield ("narration_delta", " Three.")
        yield ("turn_complete", {"tokens_in": 10, "tokens_out": 20, "latency_ms": 10, "cache_hit": False})

    monkeypatch.setattr(gemini_service, "run_turn", fake_run_turn)
    with app.app_context():
        actor_id = (
            Campaign.query.get(campaign.id)
            .characters[0]
            .id
        )
        _run_turn_and_broadcast(campaign.id, actor_id, "I greet the tavernkeeper")
    with app.app_context():
        turn = Turn.query.order_by(Turn.id.desc()).first()
        assert turn.index == 1
        assert turn.tokens_out > 0
