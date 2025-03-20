from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from app.cache import cache
from app.extensions import db
from app.gemini_service import GeminiService
from app.models import Campaign, Character, Memoir, Turn, User


def _campaign_with_actor():
    campaign = Campaign.query.first()
    user = User(email="svc@example.com", display_name="svc")
    user.set_password("password123")
    db.session.add(user)
    db.session.flush()
    actor = Character(
        user_id=user.id,
        campaign_id=campaign.id,
        name="Arya",
        race="Human",
        char_class="Fighter",
        inventory={"items": []},
    )
    db.session.add(actor)
    db.session.commit()
    return campaign, actor


def _resp(function_calls=None, text=""):
    return SimpleNamespace(
        function_calls=function_calls or [],
        usage_metadata=SimpleNamespace(prompt_token_count=5, candidates_token_count=7),
        candidates=[SimpleNamespace(content="assistant content")],
        text=text,
    )


def test_phase1_no_tools_still_streams(app, fake_gemini, monkeypatch):
    with app.app_context():
        campaign, actor = _campaign_with_actor()
        svc = GeminiService()
        svc.client = fake_gemini
        fake_gemini.models.generate_content.return_value = _resp([])
        fake_gemini.models.generate_content_stream.return_value = [SimpleNamespace(text="Hello ", usage_metadata=None), SimpleNamespace(text="world", usage_metadata=None)]
        events = list(svc.run_turn(campaign, actor, "look around"))
        assert any(e[0] == "narration_delta" for e in events)


def test_roll_dice_mutation_and_narration(app, fake_gemini):
    with app.app_context():
        campaign, actor = _campaign_with_actor()
        svc = GeminiService()
        svc.client = fake_gemini
        fake_gemini.models.generate_content.return_value = _resp([SimpleNamespace(name="roll_dice", args={"sides": 20})])
        fake_gemini.models.generate_content_stream.return_value = [SimpleNamespace(text="Result narrated.", usage_metadata=None)]
        events = list(svc.run_turn(campaign, actor, "roll"))
        assert any(e[0] == "mutation" and e[1]["name"] == "roll_dice" for e in events)
        assert any(e[0] == "narration_delta" for e in events)


def test_cache_hit_skips_gemini_calls(app):
    with app.app_context():
        campaign, actor = _campaign_with_actor()
        svc = GeminiService()
        svc.client = Mock()
        key = cache.make_key("turn", {"state": svc._state_hash_parts(campaign, actor), "action": "look"})
        cache.set(key, {"narration": "cached"})
        events = list(svc.run_turn(campaign, actor, "look"))
        assert any(e[0] == "narration_delta" for e in events)
        assert svc.client.models.generate_content.call_count == 0


def test_mutation_turn_not_cached(app, fake_gemini, monkeypatch):
    with app.app_context():
        campaign, actor = _campaign_with_actor()
        svc = GeminiService()
        svc.client = fake_gemini
        fake_gemini.models.generate_content.return_value = _resp([SimpleNamespace(name="roll_dice", args={"sides": 20})])
        fake_gemini.models.generate_content_stream.return_value = [SimpleNamespace(text="x", usage_metadata=None)]
        set_spy = Mock(wraps=cache.set)
        monkeypatch.setattr(cache, "set", set_spy)
        list(svc.run_turn(campaign, actor, "roll"))
        assert set_spy.call_count == 0


def test_no_mutation_turn_cached(app, fake_gemini, monkeypatch):
    with app.app_context():
        campaign, actor = _campaign_with_actor()
        svc = GeminiService()
        svc.client = fake_gemini
        fake_gemini.models.generate_content.return_value = _resp([])
        fake_gemini.models.generate_content_stream.return_value = [SimpleNamespace(text="plain narration", usage_metadata=None)]
        set_spy = Mock(wraps=cache.set)
        monkeypatch.setattr(cache, "set", set_spy)
        monkeypatch.setattr(cache, "get", lambda _k: None)
        list(svc.run_turn(campaign, actor, "look uncached"))
        assert set_spy.call_count == 1


def test_stub_turn_fallback_when_no_client(app):
    with app.app_context():
        campaign, actor = _campaign_with_actor()
        svc = GeminiService()
        svc.client = None
        events = list(svc.run_turn(campaign, actor, "look"))
        assert any(e[0] == "narration_delta" for e in events)


def test_build_context_contains_expected_sections(app):
    with app.app_context():
        campaign, actor = _campaign_with_actor()
        svc = GeminiService()
        txt = svc._build_context(campaign, actor, "act")
        assert "=== PARTY ===" in txt
        assert "VALID LOCATIONS" in txt
        assert "RECENT HISTORY" in txt


def test_build_context_contains_hp_status_stats_inventory_and_locations(app):
    with app.app_context():
        campaign, actor = _campaign_with_actor()
        actor.hp = max(1, actor.max_hp // 2)
        actor.strength = 15
        actor.dexterity = 12
        actor.constitution = 14
        actor.intelligence = 10
        actor.wisdom = 8
        actor.charisma = 13
        actor.inventory = {"items": [{"name": "Short Sword", "qty": 1, "type": "weapon"}]}
        db.session.commit()

        svc = GeminiService()
        txt = svc._build_context(campaign, actor, "act")
        assert "BLOODIED" in txt or "healthy" in txt or "CRITICAL" in txt or "DOWNED" in txt
        assert "STR " in txt and "DEX " in txt and "CON " in txt and "INT " in txt and "WIS " in txt and "CHA " in txt
        assert "Short Sword×1[weapon]" in txt
        assert "VALID LOCATIONS" in txt
        assert "ACTING NOW" in txt


def test_system_instruction_contains_death_and_boundaries(app):
    with app.app_context():
        campaign, _ = _campaign_with_actor()
        svc = GeminiService()
        system_text = svc._get_system_instruction(campaign)
        assert "DEATH" in system_text
        assert ("MAP BOUNDARIES" in system_text) or ("Mount Cindermaw" in system_text)


def test_compact_if_needed_threshold(app):
    with app.app_context():
        campaign, _ = _campaign_with_actor()
        svc = GeminiService()
        assert svc.compact_if_needed(campaign) is None


def test_compact_if_needed_creates_memoir(app):
    with app.app_context():
        campaign, actor = _campaign_with_actor()
        svc = GeminiService()
        svc.client = None
        for i in range(30):
            db.session.add(Turn(campaign_id=campaign.id, character_id=actor.id, index=i + 1, player_action="a", dm_narration="b"))
        db.session.commit()
        memoir = svc.compact_if_needed(campaign)
        assert memoir is not None
        assert Memoir.query.count() >= 1


class _RetryableGeminiError(Exception):
    def __init__(self, status_code=503):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def test_phase1_retries_then_succeeds(app, fake_gemini, monkeypatch):
    with app.app_context():
        campaign, actor = _campaign_with_actor()
        svc = GeminiService()
        svc.client = fake_gemini
        calls = {"n": 0}

        def flaky_generate(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise _RetryableGeminiError(503)
            return _resp([])

        fake_gemini.models.generate_content.side_effect = flaky_generate
        fake_gemini.models.generate_content_stream.return_value = [SimpleNamespace(text="Recovered narration.", usage_metadata=None)]
        monkeypatch.setattr("app.gemini_service.time.sleep", lambda _x: None)
        monkeypatch.setattr(cache, "get", lambda _k: None)
        events = list(svc.run_turn(campaign, actor, "retry look"))
        assert calls["n"] == 3
        assert any(e[0] == "turn_complete" for e in events)


def test_phase1_retries_exhaust_then_fallback(app, fake_gemini, monkeypatch):
    with app.app_context():
        campaign, actor = _campaign_with_actor()
        svc = GeminiService()
        svc.client = fake_gemini
        fake_gemini.models.generate_content.side_effect = _RetryableGeminiError(503)
        monkeypatch.setattr("app.gemini_service.time.sleep", lambda _x: None)
        monkeypatch.setattr(cache, "get", lambda _k: None)
        events = list(svc.run_turn(campaign, actor, "retry fail look"))
        assert any(e[0] == "narration_delta" and "temporarily unreachable" in e[1] for e in events)
        assert any(e[0] == "turn_complete" for e in events)


def test_empty_phase2_stream_emits_placeholder(app, fake_gemini):
    with app.app_context():
        campaign, actor = _campaign_with_actor()
        svc = GeminiService()
        svc.client = fake_gemini
        fake_gemini.models.generate_content.return_value = _resp([])
        fake_gemini.models.generate_content_stream.return_value = []
        events = list(svc.run_turn(campaign, actor, "wait"))
        assert any(e[0] == "narration_delta" and "pauses, choosing their words" in e[1] for e in events)


def test_parts_based_function_calls_without_property(app, fake_gemini):
    with app.app_context():
        campaign, actor = _campaign_with_actor()
        svc = GeminiService()
        svc.client = fake_gemini

        class Resp:
            def __init__(self):
                self.usage_metadata = SimpleNamespace(prompt_token_count=1, candidates_token_count=1)
                fn = SimpleNamespace(name="roll_dice", args={"sides": 20})
                part = SimpleNamespace(function_call=fn)
                content = SimpleNamespace(parts=[part])
                self.candidates = [SimpleNamespace(content=content)]

        fake_gemini.models.generate_content.return_value = Resp()
        fake_gemini.models.generate_content_stream.return_value = [SimpleNamespace(text="ok", usage_metadata=None)]
        events = list(svc.run_turn(campaign, actor, "roll now"))
        assert any(e[0] == "mutation" for e in events)
        assert any(e[0] == "turn_complete" for e in events)
