from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import Mock

from app.cache import cache
from app.extensions import db
from app.models import CacheFallback


def test_make_key_deterministic():
    parts = {"a": 1, "b": 2}
    assert cache.make_key("turn", parts) == cache.make_key("turn", parts)


def test_make_key_order_independent():
    assert cache.make_key("turn", {"a": 1, "b": 2}) == cache.make_key("turn", {"b": 2, "a": 1})


def test_hit_miss_increment(app):
    with app.app_context():
        cache.hits = 0
        cache.misses = 0
        cache.get("missing-key")
        assert cache.misses == 1
        cache.set("present-key", {"ok": 1}, ttl=60)
        cache.get("present-key")
        assert cache.hits == 1


def test_redis_set_get(fake_redis):
    cache.set("redis-key", {"x": 1})
    assert cache.get("redis-key") == {"x": 1}


def test_sql_fallback_set_get_delete(app):
    with app.app_context():
        cache._redis_ok = False
        cache.set("sql-key", {"x": 2}, ttl=10)
        assert cache.get("sql-key") == {"x": 2}
        row = CacheFallback.query.filter_by(key="sql-key").first()
        db.session.delete(row)
        db.session.commit()
        assert cache.get("sql-key") is None


def test_expired_sql_entry_removed_on_get(app):
    with app.app_context():
        cache._redis_ok = False
        db.session.add(CacheFallback(key="expired-key", value='{"a":1}', expires_at=datetime.utcnow() - timedelta(seconds=1)))
        db.session.commit()
        assert cache.get("expired-key") is None
        assert CacheFallback.query.filter_by(key="expired-key").first() is None


def test_stats_shape():
    s = cache.stats()
    assert {"backend", "hits", "misses", "hit_rate"} <= set(s)


def test_get_handles_corrupt_json(app):
    with app.app_context():
        cache._redis_ok = False
        db.session.add(CacheFallback(key="corrupt", value="{bad", expires_at=datetime.utcnow() + timedelta(seconds=10)))
        db.session.commit()
        assert cache.get("corrupt") is None


def test_redis_get_failure_falls_back(app):
    with app.app_context():
        bad = Mock()
        bad.get.side_effect = RuntimeError("redis down")
        cache._redis = bad
        cache._redis_ok = True
        db.session.add(CacheFallback(key="fallback-key", value='{"ok":1}', expires_at=datetime.utcnow() + timedelta(seconds=10)))
        db.session.commit()
        assert cache.get("fallback-key") == {"ok": 1}


def test_redis_set_failure_falls_back_sql(app):
    with app.app_context():
        bad = Mock()
        bad.setex.side_effect = RuntimeError("redis down")
        cache._redis = bad
        cache._redis_ok = True
        cache.set("fallback-set", {"ok": 2}, ttl=10)
        row = CacheFallback.query.filter_by(key="fallback-set").first()
        assert row is not None
