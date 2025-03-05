"""Cache layer.

Interview talking points:

* Keys are `sha1(campaign_state_hash + normalized_action)`, so identical
  actions against identical state return cached narrations. The state hash
  includes active character HP, location, turn_index, and mode — so a cache
  hit is genuinely safe, not just textually similar.

* `CACHE_TTL_SECONDS` provides a belt-and-suspenders second layer: even if
  the state hash collides (it won't in practice — SHA1 of the full JSON),
  stale entries age out.

* Observability: every call increments hit/miss counters exposed at
  GET /api/metrics.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Any

import redis as redis_lib

from .config import config
from .extensions import db
from .models import CacheFallback

log = logging.getLogger(__name__)


class Cache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self._redis: redis_lib.Redis | None = None
        self._redis_ok = False
        self._try_connect()

    def _try_connect(self) -> None:
        try:
            client = redis_lib.from_url(config.REDIS_URL, socket_connect_timeout=1)
            client.ping()
            self._redis = client
            self._redis_ok = True
            log.info("Redis connected at %s", config.REDIS_URL)
        except Exception as e:  # noqa: BLE001
            log.warning("Redis unavailable (%s); falling back to SQL cache", e)
            self._redis_ok = False

    # ---- key building ----

    @staticmethod
    def make_key(namespace: str, parts: dict[str, Any]) -> str:
        """Build a deterministic cache key from a dict of parts.

        JSON dump is sorted so {"a":1,"b":2} and {"b":2,"a":1} collide."""
        canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:24]
        return f"{namespace}:{digest}"

    # ---- read/write ----

    def get(self, key: str) -> Any | None:
        raw = self._get_raw(key)
        with self._lock:
            if raw is None:
                self.misses += 1
                return None
            self.hits += 1
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.exception("Corrupt cache value for %s", key)
            return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = ttl or config.CACHE_TTL_SECONDS
        raw = json.dumps(value, separators=(",", ":"))
        self._set_raw(key, raw, ttl)

    # ---- private: dual-backend IO ----

    def _get_raw(self, key: str) -> str | None:
        if self._redis_ok and self._redis is not None:
            try:
                v = self._redis.get(key)
                return v.decode("utf-8") if v else None
            except Exception:  # noqa: BLE001
                log.exception("Redis GET failed; falling back")
                self._redis_ok = False

        # SQL fallback — only used during Redis outages / dev without Redis.
        row = CacheFallback.query.filter_by(key=key).first()
        if row is None:
            return None
        if row.expires_at < datetime.utcnow():
            db.session.delete(row)
            db.session.commit()
            return None
        return row.value

    def _set_raw(self, key: str, raw: str, ttl: int) -> None:
        if self._redis_ok and self._redis is not None:
            try:
                self._redis.setex(key, ttl, raw)
                return
            except Exception:  # noqa: BLE001
                log.exception("Redis SET failed; falling back")
                self._redis_ok = False

        expires = datetime.utcnow() + timedelta(seconds=ttl)
        row = CacheFallback.query.filter_by(key=key).first()
        if row is None:
            db.session.add(CacheFallback(key=key, value=raw, expires_at=expires))
        else:
            row.value = raw
            row.expires_at = expires
        db.session.commit()

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        hit_rate = self.hits / total if total else 0.0
        return {
            "backend": "redis" if self._redis_ok else "sql_fallback",
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(hit_rate, 3),
        }


cache = Cache()
