from __future__ import annotations

from app.seed import seed_database


def test_seed_idempotent(app):
    with app.app_context():
        first = seed_database()
        second = seed_database()
        assert first.id == second.id


def test_seed_counts(app):
    with app.app_context():
        campaign = seed_database()
        assert len(campaign.locations) == 9
        assert len(campaign.shops) == 2
        item_counts = sorted(len(s.items) for s in campaign.shops)
        assert item_counts == [4, 5]
