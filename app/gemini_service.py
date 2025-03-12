"""Gemini service.

The flow for a player action:

1. Build prompt from (world_brief + concatenated memoirs + last N turns + current action).
2. Check cache using (state_hash, action) key — on hit, stream cached narration.
3. First call: Gemini with tools enabled, automatic_function_calling disabled,
   mode='ANY' to strongly encourage tool use. We execute any returned function
   calls against SQL, collect results.
4. Second call: feed the tool results back, stream the narration token-by-token.
   Frontend speaks sentences as they arrive.
5. Persist Turn with metrics (tokens, latency, cache_hit).
6. Every TURNS_BEFORE_COMPACTION turns, enqueue a compaction job that
   summarises old turns into a Memoir row using the Pro model.

Every external call is wrapped in structured error recovery: if Gemini fails
or returns malformed output, we fall back to a terse deterministic narration
so the game never deadlocks.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Iterable

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from tenacity import RetryError, Retrying, retry_if_exception, stop_after_attempt, wait_chain, wait_fixed

from .cache import cache
from .config import config
from .extensions import db
from .game import TOOL_DECLARATIONS, execute_tool
from .models import Battle, Campaign, Character, Memoir, Shop, Turn

log = logging.getLogger(__name__)


_SYSTEM_INSTRUCTION = """You are the Dungeon Master for Embervale, a dark fantasy tabletop RPG.

════════════════════════════════════════
CORE RULES — FOLLOW THESE WITHOUT EXCEPTION
════════════════════════════════════════

TOOL USE IS MANDATORY:
- NEVER describe damage, healing, item changes, movement, or combat without calling the appropriate tool first.
- Call tools BEFORE writing narration. Your narration must match the tool results exactly.
- If a tool call fails, narrate the failure — do not invent a different outcome.

STAT CHECKS:
- For any non-trivial action, roll dice and use the character's relevant stat modifier.
- STR for lifting, breaking, melee attacks. DEX for stealth, ranged, acrobatics.
- INT for knowledge, puzzles, arcane. WIS for perception, survival, healing. CHA for persuasion, deception.
- Low stats mean likely failure. A STR 8 character cannot break down a reinforced door on a bad roll.

COMBAT:
- Use apply_damage for ALL damage. Never describe wounds without calling apply_damage first.
- Enemies fight intelligently — they target the weakest party member, use cover, retreat when losing.
- When a character reaches 0 HP: they are DOWNED. Narrate it dramatically. They may die.

DEATH IS REAL:
- If a character reaches 0 HP in combat, they are downed.
- If no ally stabilizes them within 3 rounds (or if they take further damage), they DIE.
- Death is permanent. Narrate it with weight — honor their story.
- A dead character's items remain on their body and can be looted.
- Do NOT soften death. Do NOT "knock unconscious and wake up later" unless the player specifically chose Cleric or has magic that prevents it.

MAP BOUNDARIES:
- The world has exactly these locations: {location_keys}
- Characters may ONLY move between these locations using move_character.
- If a player tries to go somewhere that doesn't exist ("I fly to the moon", "I teleport to Paris"), respond in-world: the world has limits, powerful magic might not work here, or it simply isn't possible.
- If a player tries to leave the map entirely, describe the valley's natural boundaries: the impassable peaks of Mount Cindermaw to the north, the endless Ashwood to the east, treacherous marshlands to the south, and sheer cliffs to the west. They cannot leave.
- You may describe journeys between locations with flavor, but always use move_character to update their actual position.

INVENTORY RULES:
- Characters can only use items they actually have in their inventory.
- If a player tries to use an item they don't have ("I throw a fireball" when they have no scroll), deny it: "You reach for the spell and find nothing — you don't have that."
- When items are consumed (potions drunk, scrolls cast, arrows fired), call update_inventory with delta=-1.
- Characters cannot buy things they can't afford. Gold is tracked — enforce it.

SHOPS:
- Only open a shop when the character is physically at that location AND interacts with it.
- Call open_shop with the exact shop key. The shop inventory is fixed — don't invent items.
- Shopkeepers have personalities. Ira Thorne is blunt and businesslike. Maerla is mystical and cryptic.
- Haggling is possible with a high CHA check (DC 14). On success, 10% discount. On failure, no discount.

ABSURD REQUESTS:
- "I fly" — unless the character has a magical item or spell that grants flight, they cannot fly. "Your boots are firmly on the ground."
- "I kill the sun" / "I destroy the world" — gently break the fourth wall: "The threads of fate resist such ambitions. The world endures."
- "I instantly win" / "I use cheat codes" — in-world response: "The old stories don't yield to shortcuts."
- "I seduce the dragon" — roll CHA. On a nat 20 something interesting happens. Otherwise the dragon is amused and unimpressed.
- Ridiculous but internally consistent actions (jumping off a cliff, attacking an ally) — let them happen with real consequences. Players own their choices.
- Never refuse outright unless something is physically impossible in the world. Instead, adjudicate with dice and consequences.

TONE:
- Narration is vivid, second-person, 2-4 sentences. No bullet lists. No headers.
- React to the ACTUAL dice results. A failed stealth roll means they were heard. Don't soften it.
- Track emotional continuity — if a character just watched an ally die, NPCs react to their grief.
- The world is dangerous and morally complex. Not every quest has a clean ending.

FORMAT:
- Narrate in plain prose only after all tool calls are complete.
- Address the acting character by name.
- Never break character to explain rules. Handle everything in-world.
"""

SHOP_TRIGGERS = """
SHOP RULES:
- "Thorne's Forge", "the blacksmith", "buy weapons/armor/tools" -> move_character to "smithy", then open_shop("thorne_smithy")
- "Maerla's Cottage", "the apothecary", "buy potions/herbs/scrolls" -> move_character to "apothecary", then open_shop("maerla_apothecary")
- "Mossmarket", "the market", "the traders" -> move_character to "mossmarket" (no shop key yet - describe the market verbally)
- ALWAYS call move_character BEFORE open_shop so the character's position updates on the map.
- NEVER open a shop the character isn't physically at.
"""


class GeminiError(RuntimeError):
    pass


class GeminiService:
    def __init__(self) -> None:
        self.gemini_ok = False
        if not config.GEMINI_API_KEY:
            log.warning("GEMINI_API_KEY is not set — service will return stub narration")
            self.client: genai.Client | None = None
        else:
            self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self._tool = {"function_declarations": [self._normalize_declaration(d) for d in TOOL_DECLARATIONS]}
        self.gemini_ok = self.client is not None

    @staticmethod
    def _normalize_declaration(decl: dict[str, Any]) -> dict[str, Any]:
        out = dict(decl)
        out["parameters"] = GeminiService._normalize_schema(dict(decl.get("parameters", {})))
        return out

    @staticmethod
    def _normalize_schema(schema: dict[str, Any]) -> dict[str, Any]:
        t = schema.get("type")
        if isinstance(t, str):
            schema["type"] = t.upper()
        props = schema.get("properties")
        if isinstance(props, dict):
            for key, value in props.items():
                if isinstance(value, dict):
                    props[key] = GeminiService._normalize_schema(dict(value))
        items = schema.get("items")
        if isinstance(items, dict):
            schema["items"] = GeminiService._normalize_schema(dict(items))
        return schema

    def check_connectivity(self) -> bool:
        """Verify the Gemini API key works. Called once at startup."""
        if self.client is None:
            return False
        try:
            # models.list() is only supported on Vertex AI, not the Developer API.
            # Do a trivial generate instead — ~1 token, ~$0 cost.
            resp = self.client.models.generate_content(
                model=config.GEMINI_NARRATION_MODEL,
                contents="ping",
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=1,
                    temperature=0,
                ),
            )
            ok = resp is not None
            log.info("Gemini connectivity check: %s", "ok" if ok else "no response")
            return ok
        except Exception as e:
            log.error("Gemini connectivity check failed: %s", e)
            return False

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        retry_statuses = {500, 502, 503, 504}
        status = getattr(exc, "status_code", None)
        if status in retry_statuses:
            return True
        return isinstance(exc, (genai_errors.ServerError, genai_errors.APIError)) and status in retry_statuses

    @staticmethod
    def _retry_wait():
        # 0.5s, 1.5s, 4.0s plus tiny jitter per attempt.
        return wait_chain(wait_fixed(0.5), wait_fixed(1.5), wait_fixed(4.0))

    def _phase1_config(self, system_instruction: str) -> genai_types.GenerateContentConfig:
        cfg = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[self._tool],
            temperature=0.85,
            tool_config=genai_types.ToolConfig(
                function_calling_config=genai_types.FunctionCallingConfig(mode="AUTO"),
            ),
            automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(disable=True),
        )
        # Defensive check: we always require manual tool execution.
        assert cfg.automatic_function_calling and cfg.automatic_function_calling.disable is True
        return cfg

    def _phase1_with_retry(self, context: str, system_instruction: str):
        if self.client is None:
            raise GeminiError("Gemini client unavailable")
        retrying = Retrying(
            stop=stop_after_attempt(3),
            wait=self._retry_wait(),
            retry=retry_if_exception(self._is_retryable_error),
            reraise=True,
        )
        for attempt in retrying:
            with attempt:
                if attempt.retry_state.attempt_number > 1:
                    time.sleep(random.uniform(0.01, 0.15))
                return self.client.models.generate_content(
                    model=config.GEMINI_NARRATION_MODEL,
                    contents=context,
                    config=self._phase1_config(system_instruction),
                )
        raise GeminiError("phase-1 retries exhausted")

    def _phase2_stream_with_retry(self, followup_contents: list[Any], system_instruction: str):
        if self.client is None:
            raise GeminiError("Gemini client unavailable")
        retrying = Retrying(
            stop=stop_after_attempt(3),
            wait=self._retry_wait(),
            retry=retry_if_exception(self._is_retryable_error),
            reraise=True,
        )
        for attempt in retrying:
            with attempt:
                if attempt.retry_state.attempt_number > 1:
                    time.sleep(random.uniform(0.01, 0.15))
                return self.client.models.generate_content_stream(
                    model=config.GEMINI_NARRATION_MODEL,
                    contents=followup_contents,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.9,
                    ),
                )
        raise GeminiError("phase-2 retries exhausted")

    @staticmethod
    def _extract_function_calls(resp1: Any) -> list[Any]:
        # Version-safe: prefer convenience property when present.
        try:
            return list(resp1.function_calls or [])
        except AttributeError:
            function_calls: list[Any] = []
            candidates = getattr(resp1, "candidates", None) or []
            if candidates and getattr(candidates[0], "content", None) and getattr(candidates[0].content, "parts", None):
                for part in candidates[0].content.parts:
                    fn = getattr(part, "function_call", None)
                    if fn:
                        function_calls.append(fn)
            return function_calls

    # --- Prompt assembly ---------------------------------------------------

    @staticmethod
    def _render_character(ch: Character) -> str:
        def mod(score: int) -> int:
            return (score - 10) // 2

        def mod_str(score: int) -> str:
            m = mod(score)
            return f"+{m}" if m >= 0 else str(m)

        stats = (
            f"STR {ch.strength}({mod_str(ch.strength)}) "
            f"DEX {ch.dexterity}({mod_str(ch.dexterity)}) "
            f"CON {ch.constitution}({mod_str(ch.constitution)}) "
            f"INT {ch.intelligence}({mod_str(ch.intelligence)}) "
            f"WIS {ch.wisdom}({mod_str(ch.wisdom)}) "
            f"CHA {ch.charisma}({mod_str(ch.charisma)})"
        )
        inv_items = ch.inventory.get("items", []) if ch.inventory else []
        inv = ", ".join(
            f"{i.get('name', 'item')}×{i.get('qty', 1)}[{i.get('type', 'misc')}]"
            for i in inv_items
        ) if inv_items else "nothing"
        loc = ch.location.display_name if ch.location else "unknown location"
        status = (
            "DOWNED (0 HP)" if ch.hp <= 0 else
            "CRITICAL" if ch.hp <= ch.max_hp * 0.25 else
            "BLOODIED" if ch.hp <= ch.max_hp * 0.5 else
            "healthy"
        )
        effects = getattr(ch, "status_effects", None) or []
        effects_text = ", ".join(str(e) for e in effects) if effects else "none"
        return (
            f"- {ch.name} (id={ch.id}) | {ch.race} {ch.char_class} Level {ch.level} | "
            f"HP {ch.hp}/{ch.max_hp} [{status}] | AC {ch.armor_class} | Gold {ch.gold}g\n"
            f"  Stats: {stats}\n"
            f"  Location: {loc} | Inventory: {inv}\n"
            f"  Status Effects: {effects_text}\n"
            f"  Online: {ch.is_online} | Is downed: {ch.hp <= 0}"
        )

    def _get_system_instruction(self, campaign: Campaign) -> str:
        location_keys = ", ".join(l.key for l in campaign.locations)
        base = _SYSTEM_INSTRUCTION.replace("{location_keys}", location_keys or "none")
        return f"{base}\n\n{SHOP_TRIGGERS}"

    @staticmethod
    def _render_recent_turns(turns: Iterable[Turn]) -> str:
        lines: list[str] = []
        for t in turns:
            who = t.character.name if t.character else "Party"
            if t.player_action:
                lines.append(f"[Turn {t.index}] {who}: {t.player_action}")
            if t.dm_narration:
                lines.append(f"[Turn {t.index}] DM: {t.dm_narration}")
        return "\n".join(lines)

    def _build_context(self, campaign: Campaign, actor: Character, action: str) -> str:
        memoir_text = "\n\n".join(
            f"# Memoir {m.index} (turns {m.covers_turn_from}-{m.covers_turn_to}):\n{m.summary}"
            for m in sorted(campaign.memoirs, key=lambda x: x.index)
        ) or "(none yet)"

        # Verbatim tail — anything not covered by a memoir.
        last_covered = max((m.covers_turn_to for m in campaign.memoirs), default=-1)
        recent = [t for t in campaign.turns if t.index > last_covered][-config.TURNS_BEFORE_COMPACTION:]

        chars_block = "\n".join(self._render_character(c) for c in campaign.characters) or "(no characters)"
        location_danger = {
            "tavern": "safe",
            "smithy": "safe",
            "apothecary": "safe",
            "village_square": "safe",
            "road": "low",
            "forest": "moderate",
            "ruins": "moderate",
            "cave": "moderate",
            "ironkeep": "high",
            "mossmarket": "low",
            "witchciell": "extreme — level 5+ only",
        }
        locations_block = "\n".join(
            f"  - {l.key}: {l.display_name} — {l.description} [danger: {location_danger.get(l.key, 'unknown')}]"
            for l in campaign.locations
        ) or "  - (none)"

        active_battle = Battle.query.filter_by(campaign_id=campaign.id, state="active").first()
        if active_battle:
            battle_lines = []
            for participant in sorted(active_battle.participants, key=lambda x: -x.initiative):
                hp_pct = (participant.hp / participant.max_hp) if participant.max_hp else 0
                state_str = "DOWNED" if participant.hp <= 0 else ("BLOODIED" if hp_pct <= 0.5 else "healthy")
                battle_lines.append(
                    f"  - {participant.display_name} | HP {participant.hp}/{participant.max_hp} [{state_str}] | "
                    f"AC {participant.ac} | Initiative {participant.initiative}"
                    + (" [ENEMY]" if participant.is_enemy else " [ALLY]")
                )
            battle_block = "ACTIVE COMBAT:\n" + "\n".join(battle_lines)
        else:
            battle_block = "No active combat."

        shops_here = Shop.query.filter_by(campaign_id=campaign.id, location_id=actor.current_location_id).all()
        if shops_here:
            shop_block = "SHOPS AT THIS LOCATION:\n" + "\n".join(
                f"  - {s.key}: {s.name} (run by {s.shopkeeper})"
                for s in shops_here
            )
        else:
            shop_block = "SHOPS AT THIS LOCATION:\n  - none"

        return f"""=== EMBERVALE CAMPAIGN: {campaign.name} ===

WORLD LORE:
{campaign.world_brief}

CURRENT SCENE:
{campaign.current_scene}

GAME MODE: {campaign.mode.upper()}
TURN: {campaign.turn_index}

=== PARTY ===
{chars_block}

=== MAP — VALID LOCATIONS ===
{locations_block}

{shop_block}

=== COMBAT STATE ===
{battle_block}

=== PAST EVENTS (COMPACTED) ===
{memoir_text}

=== RECENT HISTORY ===
{self._render_recent_turns(recent)}

=== ACTING NOW ===
Character: {actor.name} (id={actor.id}) — {actor.race} {actor.char_class}
HP: {actor.hp}/{actor.max_hp}
Action: {action}
"""

    # --- State hash for cache key -----------------------------------------

    @staticmethod
    def _state_hash_parts(campaign: Campaign, actor: Character) -> dict[str, Any]:
        return {
            "campaign_id": campaign.id,
            "turn_index": campaign.turn_index,
            "mode": campaign.mode,
            "scene": campaign.current_scene[:200],
            "actor": {
                "id": actor.id,
                "hp": actor.hp,
                "loc": actor.current_location_id,
                "inv": [(i["name"], i["qty"]) for i in actor.inventory.get("items", [])],
            },
        }

    # --- Main entry point --------------------------------------------------

    def run_turn(self, campaign: Campaign, actor: Character, action: str):
        """Yield (event_type, payload) tuples as the turn unfolds.

        Events:
            ("mutation", {...})        — a tool call was executed
            ("narration_delta", str)    — streaming text chunk
            ("turn_complete", {...})    — final turn record
            ("error", str)              — something failed, game continues
        """
        started = time.monotonic()

        cache_key = cache.make_key(
            "turn",
            {"state": self._state_hash_parts(campaign, actor), "action": action.strip().lower()},
        )
        hit = cache.get(cache_key)
        if hit:
            # Cached turns only replay narration; mutations would be re-applied
            # which is unsafe. So we only cache *exploration-mode* narrations
            # that had no mutations.
            yield ("narration_delta", hit["narration"])
            yield ("turn_complete", {
                "narration": hit["narration"],
                "mutations": [],
                "tokens_in": 0, "tokens_out": 0,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "cache_hit": True,
            })
            return

        context = self._build_context(campaign, actor, action)
        system_instruction = self._get_system_instruction(campaign)

        if self.client is None:
            yield from self._stub_turn(action, started)
            return

        mutations: list[dict[str, Any]] = []
        tokens_in = tokens_out = 0

        # ---- Phase 1: ask for any tool calls (non-streaming, fast) ----
        try:
            resp1 = self._phase1_with_retry(context, system_instruction)
        except Exception:
            log.exception("Gemini phase-1 error")
            yield from self._fallback_narration(context, action, started)
            return

        if resp1.usage_metadata:
            tokens_in += resp1.usage_metadata.prompt_token_count or 0
            tokens_out += resp1.usage_metadata.candidates_token_count or 0

        function_calls = self._extract_function_calls(resp1)
        tool_result_parts: list[genai_types.Part] = []

        # Execute each tool call and collect the responses.
        for fc in function_calls:
            args = dict(fc.args or {})
            # Normalize scalar args to expected runtime-friendly types.
            for k, v in list(args.items()):
                if isinstance(v, float) and v.is_integer():
                    args[k] = int(v)
            result = execute_tool(campaign, fc.name, args)
            mutations.append({"name": fc.name, "args": args, "result": result})
            yield ("mutation", {"name": fc.name, "args": args, "result": result})
            tool_result_parts.append(
                genai_types.Part.from_function_response(name=fc.name, response={"result": result})
            )

        # ---- Phase 2: stream the narration ----
        assistant_content = None
        candidates = getattr(resp1, "candidates", None) or []
        if candidates:
            assistant_content = getattr(candidates[0], "content", None)

        if function_calls and assistant_content is not None:
            # Feed back tool results and let the model produce final narration.
            followup_contents: list[Any] = [
                context,
                assistant_content,
                genai_types.Content(role="user", parts=tool_result_parts),
            ]
        else:
            # Model answered directly with no tools. Re-issue as a streaming
            # call so the user still gets incremental text.
            followup_contents = [context]

        narration_parts: list[str] = []
        try:
            stream = self._phase2_stream_with_retry(followup_contents, system_instruction)
            for chunk in stream:
                if chunk.text:
                    narration_parts.append(chunk.text)
                    yield ("narration_delta", chunk.text)
                if chunk.usage_metadata:
                    tokens_in = max(tokens_in, chunk.usage_metadata.prompt_token_count or 0)
                    tokens_out = (chunk.usage_metadata.candidates_token_count or 0) + tokens_out
        except Exception:
            log.exception("Gemini phase-2 streaming error")
            if not narration_parts:
                fallback = "The DM pauses, choosing their words carefully..."
                narration_parts = [fallback]
                yield ("narration_delta", fallback)

        if not narration_parts:
            fallback = "The DM pauses, choosing their words carefully..."
            narration_parts = [fallback]
            yield ("narration_delta", fallback)

        narration = "".join(narration_parts).strip() or "(The DM pauses.)"
        latency_ms = int((time.monotonic() - started) * 1000)

        # Cache ONLY if no mutations occurred — replaying mutations on a cache
        # hit would double-apply them.
        if not mutations:
            cache.set(cache_key, {"narration": narration})

        yield ("turn_complete", {
            "narration": narration,
            "mutations": mutations,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": latency_ms,
            "cache_hit": False,
        })

    # --- Fallbacks ---------------------------------------------------------

    def _stub_turn(self, action: str, started: float):
        """No API key — return a canned response so the app still runs end-to-end."""
        text = (
            f"[DEMO MODE — no GEMINI_API_KEY set] You attempt: '{action}'. "
            "The world waits for a real Dungeon Master to answer. Set your API key in .env."
        )
        yield ("narration_delta", text)
        yield ("turn_complete", {
            "narration": text, "mutations": [],
            "tokens_in": 0, "tokens_out": 0,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "cache_hit": False,
        })

    def _fallback_narration(self, context: str, action: str, started: float):
        text = (
            f"A sudden mist clouds the scene. You try to {action}, but the "
            "unseen forces intervene. (The DM is temporarily unreachable.)"
        )
        yield ("narration_delta", text)
        yield ("turn_complete", {
            "narration": text, "mutations": [],
            "tokens_in": 0, "tokens_out": 0,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "cache_hit": False,
        })

    # --- Compaction --------------------------------------------------------

    def compact_if_needed(self, campaign: Campaign) -> Memoir | None:
        """If we have more than TURNS_BEFORE_COMPACTION uncovered turns, summarise
        them into a Memoir row using the Pro model."""
        covered_to = max((m.covers_turn_to for m in campaign.memoirs), default=-1)
        uncovered = [t for t in campaign.turns if t.index > covered_to]
        if len(uncovered) < config.TURNS_BEFORE_COMPACTION * 2:
            return None

        batch = uncovered[: config.TURNS_BEFORE_COMPACTION]
        transcript = self._render_recent_turns(batch)

        prompt = (
            "Summarise the following RPG session transcript into a TIGHT "
            f"third-person memoir of about {config.MEMOIR_TARGET_CHARS} characters. "
            "Preserve named NPCs, locations visited, items acquired/lost, injuries, "
            "bargains made, and any promises or outstanding threads. Omit banter and dice specifics. "
            "Write in narrative past tense.\n\n"
            f"TRANSCRIPT:\n{transcript}"
        )

        if self.client is None:
            summary = f"(Stub memoir of turns {batch[0].index}-{batch[-1].index}.)"
        else:
            try:
                resp = self.client.models.generate_content(
                    model=config.GEMINI_REASONING_MODEL,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(temperature=0.5),
                )
                summary = (resp.text or "").strip() or "(Memoir unavailable.)"
            except genai_errors.APIError:
                log.exception("compaction failed")
                return None

        next_index = (campaign.memoirs[-1].index + 1) if campaign.memoirs else 0
        memoir = Memoir(
            campaign_id=campaign.id,
            index=next_index,
            covers_turn_from=batch[0].index,
            covers_turn_to=batch[-1].index,
            summary=summary,
        )
        db.session.add(memoir)
        db.session.commit()
        return memoir


gemini_service = GeminiService()
