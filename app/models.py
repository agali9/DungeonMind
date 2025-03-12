"""SQLAlchemy models.

Design notes for interviewers:

* Game state lives in SQL. The LLM *proposes* mutations via function calls;
  the server validates and commits them in a single transaction before the
  narration is streamed back. This keeps the LLM from hallucinating HP,
  duping items, or rewriting history.

* `Turn` is append-only. Every player action + DM narration is one row, with
  token counts and latency recorded for observability.

* `Memoir` holds compacted summaries of old turns. The prompt builder reads
  memoirs + the last N verbatim turns, so per-turn prompt size stays bounded
  no matter how long the campaign runs.

* Character.inventory is JSON rather than its own table on purpose — it is
  read/written atomically with every action, and a join would add latency
  without enabling any query we actually run. If inventory queries become a
  feature (e.g. "who has the amulet"), promote to a table.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Any

import bcrypt
from flask_login import UserMixin
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db


def _now() -> datetime:
    return datetime.utcnow()


def _gen_join_code() -> str:
    # 6 char URL-safe — plenty of entropy for demo-scale campaigns.
    return secrets.token_urlsafe(5)[:6].upper()


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    characters: Mapped[list["Character"]] = relationship(back_populates="user")
    campaign_memberships: Mapped[list["CampaignMembership"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), self.password_hash)


class Campaign(db.Model):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    join_code: Mapped[str] = mapped_column(String(12), unique=True, default=_gen_join_code, nullable=False)
    world_brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    current_scene: Mapped[str] = mapped_column(Text, nullable=False, default="")
    turn_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_turn_character_id: Mapped[int | None] = mapped_column(ForeignKey("characters.id"), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # "exploration" | "combat" | "shop" — controls which UI surfaces show
    mode: Mapped[str] = mapped_column(String(16), default="exploration", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    characters: Mapped[list["Character"]] = relationship(
        back_populates="campaign",
        foreign_keys="Character.campaign_id",
    )
    turns: Mapped[list["Turn"]] = relationship(back_populates="campaign", order_by="Turn.index")
    memoirs: Mapped[list["Memoir"]] = relationship(back_populates="campaign", order_by="Memoir.index")
    locations: Mapped[list["Location"]] = relationship(back_populates="campaign")
    shops: Mapped[list["Shop"]] = relationship(back_populates="campaign")
    battles: Mapped[list["Battle"]] = relationship(back_populates="campaign", order_by="Battle.id")
    memberships: Mapped[list["CampaignMembership"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")


class Character(db.Model):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    race: Mapped[str] = mapped_column(String(32), nullable=False)
    char_class: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Core stats (D&D 5e-ish; kept simple)
    max_hp: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    hp: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    armor_class: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    gold: Mapped[int] = mapped_column(Integer, default=25, nullable=False)

    strength: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    dexterity: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    constitution: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    intelligence: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    wisdom: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    charisma: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    # Position on the SVG world map (0-1000 coordinate space).
    map_x: Mapped[float] = mapped_column(Float, default=500.0, nullable=False)
    map_y: Mapped[float] = mapped_column(Float, default=500.0, nullable=False)
    current_location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)

    # {"items": [{"name": "Short Sword", "qty": 1, "damage": "1d6"}, ...]}
    inventory: Mapped[dict[str, Any]] = mapped_column(JSON, default=lambda: {"items": []}, nullable=False)

    # Display colour for their map pin; assigned at join.
    pin_color: Mapped[str] = mapped_column(String(9), default="#e0b46a", nullable=False)

    is_online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped["User"] = relationship(back_populates="characters")
    campaign: Mapped["Campaign"] = relationship(back_populates="characters", foreign_keys=[campaign_id])
    location: Mapped["Location | None"] = relationship(foreign_keys=[current_location_id])

    __table_args__ = (UniqueConstraint("user_id", "campaign_id", name="uq_user_campaign"),)

    def to_public_dict(self) -> dict[str, Any]:
        """Dict sent to clients; never includes private user info."""
        return {
            "id": self.id,
            "name": self.name,
            "race": self.race,
            "class": self.char_class,
            "level": self.level,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "ac": self.armor_class,
            "gold": self.gold,
            "stats": {
                "str": self.strength, "dex": self.dexterity, "con": self.constitution,
                "int": self.intelligence, "wis": self.wisdom, "cha": self.charisma,
            },
            "map": {"x": self.map_x, "y": self.map_y, "location_id": self.current_location_id},
            "inventory": self.inventory.get("items", []),
            "pin_color": self.pin_color,
            "is_online": self.is_online,
        }


class Location(db.Model):
    """Named region on the world map. Powers fast-travel labels and the
    `describe where you are` workflow."""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. "tavern", "ruins"
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(16), default="📍")  # used in SVG tooltip only
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    discovered: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    campaign: Mapped["Campaign"] = relationship(back_populates="locations")

    __table_args__ = (UniqueConstraint("campaign_id", "key", name="uq_campaign_location_key"),)


class Turn(db.Model):
    """Append-only log of player actions + DM responses."""

    __tablename__ = "turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    character_id: Mapped[int | None] = mapped_column(ForeignKey("characters.id"), nullable=True)
    index: Mapped[int] = mapped_column(Integer, nullable=False)

    player_action: Mapped[str] = mapped_column(Text, default="")
    dm_narration: Mapped[str] = mapped_column(Text, default="")
    # Function calls that were executed, for audit: [{"name":..., "args":...}]
    mutations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # Observability
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    campaign: Mapped["Campaign"] = relationship(back_populates="turns")
    character: Mapped["Character | None"] = relationship()


class Memoir(db.Model):
    """Compacted summary of a window of past turns.

    The prompt builder concatenates all memoirs (chronological) + the last
    N verbatim turns. Each memoir replaces TURNS_BEFORE_COMPACTION turns,
    so prompt growth is O(log N * memoir_size) in practice."""

    __tablename__ = "memoirs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    covers_turn_from: Mapped[int] = mapped_column(Integer, nullable=False)
    covers_turn_to: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    campaign: Mapped["Campaign"] = relationship(back_populates="memoirs")


# --- Commerce ---------------------------------------------------------------

class Shop(db.Model):
    __tablename__ = "shops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    shopkeeper: Mapped[str] = mapped_column(String(64), default="")
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)

    campaign: Mapped["Campaign"] = relationship(back_populates="shops")
    items: Mapped[list["ShopItem"]] = relationship(back_populates="shop", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("campaign_id", "key", name="uq_campaign_shop_key"),)


class ShopItem(db.Model):
    __tablename__ = "shop_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # "weapon" | "armor" | "potion" | "misc" — affects icon choice client-side
    kind: Mapped[str] = mapped_column(String(16), default="misc", nullable=False)
    # JSON blob for weapon damage, potion effect, etc.
    effect: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    shop: Mapped["Shop"] = relationship(back_populates="items")


# --- Combat -----------------------------------------------------------------

class Battle(db.Model):
    __tablename__ = "battles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(16), default="active", nullable=False)  # active|won|lost|fled
    round_num: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    active_participant_id: Mapped[int | None] = mapped_column(ForeignKey("battle_participants.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    campaign: Mapped["Campaign"] = relationship(back_populates="battles")
    participants: Mapped[list["BattleParticipant"]] = relationship(
        back_populates="battle",
        foreign_keys="BattleParticipant.battle_id",
        cascade="all, delete-orphan",
        order_by="BattleParticipant.initiative.desc()",
    )


class BattleParticipant(db.Model):
    """A character or NPC/enemy in a battle. Enemies don't have a Character row."""

    __tablename__ = "battle_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    battle_id: Mapped[int] = mapped_column(ForeignKey("battles.id"), nullable=False, index=True)
    character_id: Mapped[int | None] = mapped_column(ForeignKey("characters.id"), nullable=True)
    enemy_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_enemy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    hp: Mapped[int] = mapped_column(Integer, nullable=False)
    max_hp: Mapped[int] = mapped_column(Integer, nullable=False)
    ac: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    initiative: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    has_acted_this_round: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    battle: Mapped["Battle"] = relationship(back_populates="participants", foreign_keys=[battle_id])
    character: Mapped["Character | None"] = relationship()

    @property
    def display_name(self) -> str:
        return self.enemy_name or (self.character.name if self.character else "Unknown")


# --- Cache ------------------------------------------------------------------

class CacheFallback(db.Model):
    """SQL fallback if Redis is unavailable; primarily a dev-mode safety net."""

    __tablename__ = "cache_fallback"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class CampaignMembership(db.Model):
    __tablename__ = "campaign_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), default="player", nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped["User"] = relationship(back_populates="campaign_memberships")
    campaign: Mapped["Campaign"] = relationship(back_populates="memberships")

    __table_args__ = (UniqueConstraint("user_id", "campaign_id", name="uq_campaign_membership"),)
