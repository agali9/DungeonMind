import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { AuthGuard } from "./AuthGuard";
import { api } from "./api";
import { joinCampaignRoom, leaveCampaignRoom, socket, submitAction } from "./socket";
import ActionComposer from "./components/ActionComposer";
import HomeScreen from "./components/HomeScreen";
import MapPanel from "./components/MapPanel";
import PartyPanel from "./components/PartyPanel";
import QuestPanel from "./components/QuestPanel";
import StoryPanel from "./components/StoryPanel";
import TopNavBar from "./components/TopNavBar";
import { PORTRAIT_BY_PLAYER_ID } from "./data/portraits";
import { locations } from "./data/locations";

const ANTHROPIC_API_KEY = import.meta.env.VITE_ANTHROPIC_API_KEY;
const CURRENT_PLAYER_ID = "player-1";
const SUGGESTION_MODEL = "claude-sonnet-4-20250514";
const SUGGESTION_SYSTEM_PROMPT = `You are a D&D assistant. Based on the story context provided, suggest exactly 3 short player actions. Each must be under 6 words. Return ONLY a JSON array of 3 strings, no preamble, no markdown. Example: ["Approach the weathered man", "Scan for other patrons", "Order an ale and listen"]`;
const LOCATION_KEYWORDS = {
  tavern: ["silverbark tavern", "silverbar tavern", "tavern", "silverbar"],
  village_square: ["hollow's end", "hollows end", "the village", "village square"],
  smithy: ["thorne's forge", "blacksmith", "smithy", "forge"],
  apothecary: ["maerla's cottage", "apothecary", "hedge witch", "maerla"],
  forest: ["whisperwood", "the wood", "the forest"],
  ruins: ["sunken ruins", "the ruins"],
  cave: ["gloam cavern", "the cavern", "the cave"],
  road: ["eastern road", "the road"],
  ironkeep: ["ironkeep", "the keep", "the fortress"],
  mossmarket: ["mossmarket", "the market"],
  witchciell: ["witchciell", "the tower"],
};

const initialPlayState = {
  campaign: null,
  locations: [],
  characters: {},
  myCharacterId: null,
  battle: null,
  activeShop: null,
  log: [],
  narrationBuffer: "",
  dmThinking: false,
  ttsEnabled: true,
  zoomLevel: 1,
};

function toMapById(items = []) {
  return items.reduce((acc, item) => {
    acc[item.id] = item;
    return acc;
  }, {});
}

function playReducer(state, action) {
  switch (action.type) {
    case "HYDRATE":
      return {
        ...state,
        campaign: action.payload.campaign,
        locations: action.payload.locations || [],
        characters: toMapById(action.payload.characters || []),
        myCharacterId: action.payload.my_character_id ?? null,
        battle: action.payload.battle ?? null,
      };
    case "JOINED":
      return { ...state, myCharacterId: action.payload.character?.id ?? state.myCharacterId };
    case "TURN_STARTED":
      return { ...state, dmThinking: true, narrationBuffer: "" };
    case "NARRATION_DELTA":
      return { ...state, narrationBuffer: `${state.narrationBuffer}${action.text || ""}` };
    case "MUTATION":
      if (action.payload?.name === "open_shop" && action.payload?.result?.shop_key) {
        return { ...state, activeShop: { key: action.payload.result.shop_key } };
      }
      return state;
    case "STATE_UPDATE":
      return {
        ...state,
        campaign: { ...(state.campaign || {}), ...action.payload },
        characters: toMapById(action.payload.characters || []),
        battle: action.payload.battle ?? null,
      };
    case "TURN_COMPLETE":
      return { ...state, dmThinking: false, narrationBuffer: "" };
    case "DM_ERROR":
      return { ...state, dmThinking: false, narrationBuffer: "" };
    case "SHOP_UPDATE":
      return { ...state, activeShop: action.payload.shop || state.activeShop };
    case "OPEN_SHOP":
      return { ...state, activeShop: action.payload || state.activeShop };
    case "CLOSE_SHOP":
      return { ...state, activeShop: null };
    default:
      return state;
  }
}

const initialPlayers = [
  {
    id: "player-1",
    name: "Lyra Dawnveil",
    className: "Ranger",
    race: "Human",
    level: 3,
    hp: 32,
    maxHp: 36,
    online: true,
    portraitUrl: PORTRAIT_BY_PLAYER_ID["player-1"],
    x: 35,
    y: 65,
  },
  {
    id: "player-2",
    name: "Borin Emberforge",
    className: "Fighter",
    race: "Dwarf",
    level: 3,
    hp: 45,
    maxHp: 50,
    online: true,
    portraitUrl: PORTRAIT_BY_PLAYER_ID["player-2"],
    x: 47,
    y: 58,
  },
  {
    id: "player-3",
    name: "Mira Thistlebloom",
    className: "Druid",
    race: "Elf",
    level: 3,
    hp: 26,
    maxHp: 30,
    online: false,
    portraitUrl: PORTRAIT_BY_PLAYER_ID["player-3"],
    x: 56,
    y: 40,
  },
];

const initialMessages = [];

const RACE_BONUSES = {
  Human: { str: 1, dex: 1, con: 1, int: 1, wis: 1, cha: 1 },
  Elf: { dex: 2, int: 1 },
  Dwarf: { con: 2, wis: 1 },
  Halfling: { dex: 2, cha: 1 },
  "Half-Orc": { str: 2, con: 1 },
  Tiefling: { int: 2, cha: 1 },
};

const RACE_BONUS_LABELS = {
  Human: "+1 to all stats",
  Elf: "+2 DEX, +1 INT",
  Dwarf: "+2 CON, +1 WIS",
  Halfling: "+2 DEX, +1 CHA",
  "Half-Orc": "+2 STR, +1 CON",
  Tiefling: "+2 INT, +1 CHA",
};

const CLASS_INFO = {
  fighter: { label: "Fighter", hp: 14, ac: 14, desc: "Martial master. Highest HP and AC." },
  rogue: { label: "Rogue", hp: 10, ac: 13, desc: "Swift and cunning. Bonus to DEX and CHA." },
  cleric: { label: "Cleric", hp: 12, ac: 13, desc: "Divine healer. Bonus to WIS and CHA." },
  wizard: { label: "Wizard", hp: 8, ac: 11, desc: "Arcane scholar. Bonus to INT and WIS." },
  ranger: { label: "Ranger", hp: 11, ac: 13, desc: "Wilderness tracker. Bonus to DEX and WIS." },
  paladin: { label: "Paladin", hp: 13, ac: 15, desc: "Holy warrior. Bonus to STR, CON, and CHA." },
};

const CLASS_BONUSES = {
  fighter: { str: +2, con: +1, dex: -1, int: -1, wis: 0, cha: 0 },
  rogue: { dex: +2, cha: +1, str: -1, con: -1, int: 0, wis: 0 },
  cleric: { wis: +2, cha: +1, str: -1, dex: -1, con: 0, int: 0 },
  wizard: { int: +2, wis: +1, str: -2, con: -1, dex: 0, cha: 0 },
  ranger: { dex: +2, wis: +1, cha: -1, int: -1, str: 0, con: 0 },
  paladin: { str: +1, con: +1, cha: +1, int: -1, dex: -1, wis: 0 },
};

const STAT_KEYS = ["str", "dex", "con", "int", "wis", "cha"];
const STAT_LABELS = { str: "STR", dex: "DEX", con: "CON", int: "INT", wis: "WIS", cha: "CHA" };

function mod(score) {
  const value = Math.floor((score - 10) / 2);
  return `${value >= 0 ? "+" : ""}${value}`;
}

function getFinalStats(rolled, race, charClass) {
  const raceMod = RACE_BONUSES[race] || {};
  const classMod = CLASS_BONUSES[charClass] || {};
  return {
    str: (rolled?.str || 10) + (raceMod.str || 0) + (classMod.str || 0),
    dex: (rolled?.dex || 10) + (raceMod.dex || 0) + (classMod.dex || 0),
    con: (rolled?.con || 10) + (raceMod.con || 0) + (classMod.con || 0),
    int: (rolled?.int || 10) + (raceMod.int || 0) + (classMod.int || 0),
    wis: (rolled?.wis || 10) + (raceMod.wis || 0) + (classMod.wis || 0),
    cha: (rolled?.cha || 10) + (raceMod.cha || 0) + (classMod.cha || 0),
  };
}

const CLASS_SKILLS = {
  fighter: {
    passive: [
      { name: "Second Wind", desc: "Regain 1d10 + Fighter level HP as a bonus action. Once per short rest.", type: "recovery", cooldown: "Short rest" },
      { name: "Fighting Style", desc: "Chosen combat specialization. +2 to attack rolls with chosen weapon type.", type: "passive" },
      { name: "Action Surge", desc: "Take one additional action on your turn. Once per short rest.", type: "active", cooldown: "Short rest" },
    ],
    spells: [],
  },
  rogue: {
    passive: [
      { name: "Sneak Attack", desc: "Deal extra 1d6 damage when you have advantage or an ally is adjacent to your target.", type: "passive", damage: "+1d6" },
      { name: "Cunning Action", desc: "Dash, Disengage, or Hide as a bonus action each turn.", type: "passive" },
      { name: "Thieves' Cant", desc: "Secret language of rogues. Can hide messages in normal conversation.", type: "passive" },
      { name: "Expertise", desc: "Double proficiency bonus on two chosen skills.", type: "passive" },
    ],
    spells: [],
  },
  cleric: {
    passive: [
      { name: "Divine Domain", desc: "Channel the power of your deity. Domain spells always prepared.", type: "passive" },
      { name: "Channel Divinity", desc: "Use divine power for special effects. Once per short rest.", type: "active", cooldown: "Short rest" },
      { name: "Turn Undead", desc: "Undead within 30ft must make WIS save or flee for 1 minute.", type: "active", cooldown: "Channel Divinity" },
    ],
    spells: [
      { name: "Cure Wounds", desc: "Touch to restore 1d8 + WIS modifier HP.", type: "spell", slot: "1st", heal: "1d8+WIS" },
      { name: "Sacred Flame", desc: "Target must DEX save or take 1d8 radiant damage.", type: "spell", slot: "Cantrip", damage: "1d8 radiant" },
      { name: "Bless", desc: "3 targets add 1d4 to attack rolls and saving throws for 1 minute.", type: "spell", slot: "1st" },
      { name: "Guiding Bolt", desc: "Ranged spell attack for 4d6 radiant damage. Next attack has advantage.", type: "spell", slot: "1st", damage: "4d6 radiant" },
    ],
  },
  wizard: {
    passive: [
      { name: "Arcane Recovery", desc: "Recover spell slots during a short rest once per day. Total levels ≤ half wizard level.", type: "recovery", cooldown: "Long rest" },
      { name: "Spellcasting", desc: "INT is your spellcasting ability. Spell save DC = 8 + INT mod + proficiency.", type: "passive" },
      { name: "Ritual Casting", desc: "Cast ritual spells without expending a spell slot (takes 10 extra minutes).", type: "passive" },
    ],
    spells: [
      { name: "Magic Missile", desc: "3 darts that automatically hit. Each deals 1d4+1 force damage.", type: "spell", slot: "1st", damage: "3x(1d4+1) force" },
      { name: "Shield", desc: "Reaction: +5 AC until start of next turn, negates Magic Missile.", type: "spell", slot: "1st" },
      { name: "Fire Bolt", desc: "Ranged attack for 1d10 fire damage. Ignites flammable objects.", type: "spell", slot: "Cantrip", damage: "1d10 fire" },
      { name: "Mage Hand", desc: "Spectral hand can manipulate objects up to 30ft away.", type: "spell", slot: "Cantrip" },
    ],
  },
  ranger: {
    passive: [
      { name: "Favored Enemy", desc: "Advantage on survival/tracking checks vs chosen enemy type.", type: "passive" },
      { name: "Natural Explorer", desc: "Difficult terrain doesn't slow group in favored terrain. Extra benefits in the wild.", type: "passive" },
      { name: "Primeval Awareness", desc: "Expend a spell slot to sense nearby enemy types for 1 min/slot level.", type: "active" },
    ],
    spells: [
      { name: "Hunter's Mark", desc: "Mark a target. Deal extra 1d6 damage to it, advantage on tracking.", type: "spell", slot: "1st", damage: "+1d6" },
      { name: "Speak with Animals", desc: "Communicate with beasts for 10 minutes.", type: "spell", slot: "1st" },
      { name: "Ensnaring Strike", desc: "On next hit, target must STR save or be restrained. 1d6 piercing/turn.", type: "spell", slot: "1st", damage: "1d6 piercing/turn" },
    ],
  },
  paladin: {
    passive: [
      { name: "Divine Sense", desc: "Detect celestials, fiends, undead within 60ft. Uses = 1 + CHA mod per long rest.", type: "active", cooldown: "Long rest" },
      { name: "Lay on Hands", desc: "Healing pool of 5 x paladin level HP. Restore any amount with a touch.", type: "active", heal: "Pool: 5xlevel" },
      { name: "Aura of Protection", desc: "You and allies within 10ft add CHA modifier to saving throws.", type: "passive" },
    ],
    spells: [
      { name: "Divine Smite", desc: "Expend a spell slot on a hit: +2d8 radiant per slot level (max 5d8). +1d8 vs undead.", type: "spell", slot: "1st+", damage: "2d8+ radiant" },
      { name: "Bless", desc: "3 targets add 1d4 to attack rolls and saving throws.", type: "spell", slot: "1st" },
      { name: "Thunderous Smite", desc: "Next hit deals extra 2d6 thunder damage and pushes target 10ft.", type: "spell", slot: "1st", damage: "+2d6 thunder" },
      { name: "Cure Wounds", desc: "Touch to restore 1d8 + CHA modifier HP.", type: "spell", slot: "1st", heal: "1d8+CHA" },
    ],
  },
};

const SHOP_THEMES = {
  thorne_smithy: {
    title: "Thorne's Forge",
    icon: "⚒",
    bgColor: "#1a1008",
    accentColor: "#c44a3c",
    keeper: "Ira Thorne",
    greeting: "\"What'll it be? Got blades, got armor, got tools. Don't got time.\"",
    categories: ["weapon", "armor", "tool"],
  },
  maerla_apothecary: {
    title: "Maerla's Cottage",
    icon: "🌿",
    bgColor: "#0a1408",
    accentColor: "#6a8a40",
    keeper: "Maerla",
    greeting: "\"Come in, come in. Mind the dried herbs. What ails you, traveler?\"",
    categories: ["potion", "scroll", "misc"],
  },
};

const DEFAULT_SHOP_THEME = {
  icon: "🏪",
  bgColor: "#14100c",
  accentColor: "#d98a3a",
  greeting: "\"Welcome, traveler. Browse as you like.\"",
  categories: ["weapon", "armor", "potion", "scroll", "tool", "misc"],
};

function Modal({ title, onClose, children, wide = false }) {
  useEffect(() => {
    const handler = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return createPortal(
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <section className={`modal-box ${wide ? "modal-wide" : ""}`} onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">{title}</h2>
          <button className="modal-close" onClick={onClose} type="button">✕</button>
        </div>
        <div className="modal-content">{children}</div>
      </section>
    </div>,
    document.body,
  );
}

function InventoryPanel({ character, onClose }) {
  const items = Array.isArray(character?.inventory) ? character.inventory : [];
  const gold = character?.gold || 0;
  const ITEM_MASTER = {
    "Longbow": { type: "weapon", icon: "🏹", desc: "Range 150ft. Fires arrows with lethal precision.", damage: "1d8 piercing", weight: 2 },
    "Short Sword": { type: "weapon", icon: "⚔️", desc: "A reliable double-edged blade. Good for close quarters.", damage: "1d6 piercing", weight: 2 },
    "Hand Axe": { type: "weapon", icon: "🪓", desc: "Light and throwable up to 20ft.", damage: "1d6 slashing", weight: 2 },
    "Dagger": { type: "weapon", icon: "🗡️", desc: "Concealable. Can be thrown 20ft.", damage: "1d4 piercing", weight: 0.5 },
    "Wooden Mace": { type: "weapon", icon: "⚔️", desc: "A blessed weapon of solid oak and iron.", damage: "1d6 bludgeoning", weight: 4 },
    "Quarterstaff": { type: "weapon", icon: "🪄", desc: "A gnarled wizard's staff. Also a decent weapon.", damage: "1d6 bludgeoning", weight: 4 },
    "Longsword": { type: "weapon", icon: "⚔️", desc: "A holy blade, balanced for both offense and defense.", damage: "1d8 slashing", weight: 3 },
    "Iron Torch": { type: "misc", icon: "🔦", desc: "Burns for 8 hours. Illuminates 20ft radius.", weight: 1 },
    "Chain Shirt": { type: "armor", icon: "🛡️", desc: "Sturdy linked steel armor. Quiet enough for travel.", weight: 20 },
    "Shield": { type: "armor", icon: "🛡️", desc: "Wooden shield with iron rim. +2 to AC.", weight: 6 },
    "Dark Cloak": { type: "armor", icon: "🧥", desc: "Shadows cling to it. +1 to stealth checks.", weight: 1 },
    "Healing Potion": { type: "potion", icon: "⚗️", desc: "A bitter root-red liquid. Drink to restore health.", heal: "2d4+2 HP", weight: 0.5 },
    "Healing Draught": { type: "potion", icon: "⚗️", desc: "A stronger healing brew.", heal: "2d4+2 HP", weight: 0.5 },
    "Spellbook": { type: "focus", icon: "📖", desc: "Contains your known spells. Required for wizard spell prep.", weight: 3 },
    "Arcane Focus": { type: "focus", icon: "🔮", desc: "A crystal orb that channels arcane energy.", weight: 1 },
    "Holy Symbol": { type: "focus", icon: "✝️", desc: "A divine focus for cleric and paladin spellcasting.", weight: 0.5 },
    "Prayer Beads": { type: "misc", icon: "📿", desc: "+1 to WIS saving throws when held.", weight: 0.1 },
    "Lockpicks": { type: "tool", icon: "🔑", desc: "A fine set of steel picks. Required for lock-picking attempts.", weight: 0.5 },
    "Herbalism Kit": { type: "tool", icon: "🌿", desc: "Craft healing poultices and antitoxins in the wild.", weight: 3 },
    "Quiver": { type: "misc", icon: "🏹", desc: "Holds up to 20 arrows.", weight: 0.5 },
    "Arrows": { type: "ammo", icon: "🏹", desc: "Standard fletched arrows. 20 per quiver.", weight: 0.05 },
    "Rations": { type: "misc", icon: "🍖", desc: "Dried meat and hardtack. One day's food.", weight: 0.5 },
    "Scroll of Magic Missile": { type: "scroll", icon: "📜", desc: "Single-use. Deals 3×(1d4+1) force damage. Never misses.", damage: "3×1d4+1 force", weight: 0.1 },
    "Lucky Coin": { type: "misc", icon: "🪙", desc: "A human heirloom. +1 to one ability check per day.", weight: 0.1 },
    "Elven Waybread": { type: "misc", icon: "🍞", desc: "Nourishing elvish bread. Keeps you alert in the wild.", weight: 0.2 },
    "Dwarven Ale": { type: "misc", icon: "🍺", desc: "Stout enough to grant resistance to poison. One use.", weight: 0.5 },
    "Halfling Pipe": { type: "misc", icon: "🪈", desc: "Calming smoke. +1 to CHA checks when relaxed.", weight: 0.2 },
    "Bone Talisman": { type: "misc", icon: "🦴", desc: "Ancestral ward. Once per day: avoid being downed (drop to 1 HP instead).", weight: 0.1 },
    "Infernal Charm": { type: "misc", icon: "😈", desc: "Radiates subtle menace. Advantage on Intimidation checks.", weight: 0.1 },
  };

  const enrichItem = (item) => {
    const master = ITEM_MASTER[item.name] || {};
    return {
      ...master,
      ...item,
      type: item.type || master.type || "misc",
      icon: master.icon || "📦",
      desc: item.desc || item.description || master.desc || "",
      damage: item.damage || master.damage || null,
      heal: item.heal || master.heal || null,
      weight: item.weight || master.weight || 1,
    };
  };

  const enrichedItems = items.map(enrichItem);
  const totalWeight = enrichedItems.reduce((sum, item) => {
    return sum + ((item.weight || 1) * (item.qty || 1));
  }, 0);
  const carryCapacity = (character?.stats?.str || 10) * 15;
  const isEncumbered = totalWeight > carryCapacity * 0.67;
  const isOverloaded = totalWeight > carryCapacity;

  return (
    <Modal onClose={onClose} title="INVENTORY">
      <div className="inv-summary-bar">
        <div className="inv-gold">
          <span>💰</span>
          <strong>{gold}</strong>
          <span>gold pieces</span>
        </div>
        <div className="inv-weight">
          <span>⚖️</span>
          <span>{totalWeight.toFixed(1)} / {carryCapacity} lbs</span>
        </div>
      </div>
      <div className="inv-weight-bar-wrap">
        <div
          className="inv-weight-bar-fill"
          style={{
            width: `${Math.min(100, (totalWeight / carryCapacity) * 100)}%`,
            background: isOverloaded ? "#c44a3c" : isEncumbered ? "#d98a3a" : "#6ae0a9",
          }}
        />
      </div>
      <span className={`inv-weight-text ${isOverloaded ? "overloaded" : isEncumbered ? "encumbered" : ""}`}>
        {isOverloaded ? "⚠ Overloaded" : isEncumbered ? "Encumbered" : ""} {totalWeight.toFixed(1)} / {carryCapacity} lbs
      </span>
      {items.length === 0 ? (
        <p className="inv-empty">Your pack is empty.</p>
      ) : (
        <ul className="inv-list">
          {enrichedItems.map((item, idx) => {
            return (
            <li className="inv-item" key={`${item.name}-${idx}`}>
              <div className="inv-icon-col">
                <span className="inv-type-icon">{item.icon}</span>
                <span className="inv-type-badge" data-type={item.type}>
                  {item.type?.toUpperCase()}
                </span>
              </div>
              <div className="inv-item-body">
                <div className="inv-name-row">
                  <span className="inv-name">{item.name}</span>
                  {item.qty > 1 ? <span className="inv-qty">x{item.qty}</span> : null}
                </div>
                <div className="inv-desc">{item.desc || item.description || ""}</div>
                <div className="inv-tags">
                  {item.damage ? <span className="inv-tag inv-tag-damage">⚔ {item.damage}</span> : null}
                  {item.heal ? <span className="inv-tag inv-tag-heal">💚 {item.heal}</span> : null}
                  {item.weight ? <span className="inv-tag inv-tag-weight">⚖ {(item.weight * (item.qty || 1)).toFixed(1)} lbs</span> : null}
                  {item.type === "armor" ? <span className="inv-tag inv-tag-armor">🛡 Armor</span> : null}
                  {item.type === "focus" ? <span className="inv-tag inv-tag-focus">🔮 Spellcasting Focus</span> : null}
                </div>
              </div>
            </li>
            );
          })}
        </ul>
      )}
    </Modal>
  );
}

function ProfilePanel({ character, onClose }) {
  if (!character) return null;
  const stats = [
    { key: "str", label: "Strength", value: character?.stats?.str || 10 },
    { key: "dex", label: "Dexterity", value: character?.stats?.dex || 10 },
    { key: "con", label: "Constitution", value: character?.stats?.con || 10 },
    { key: "int", label: "Intelligence", value: character?.stats?.int || 10 },
    { key: "wis", label: "Wisdom", value: character?.stats?.wis || 10 },
    { key: "cha", label: "Charisma", value: character?.stats?.cha || 10 },
  ];

  return (
    <Modal onClose={onClose} title="PROFILE">
      <div className="mb-4 flex items-start gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-full text-[#0a0908]" style={{ backgroundColor: character?.pin_color || "#d98a3a" }}>
          {(character?.name || "?").slice(0, 1).toUpperCase()}
        </div>
        <div>
          <div className="text-lg">{character?.name}</div>
          <div className="text-sm text-[#b8a688]">{character?.race} {character?.class} · Level {character?.level}</div>
          <div className="text-sm text-[#b8a688]">HP {character?.hp}/{character?.max_hp} · AC {character?.ac} · {character?.gold}g</div>
        </div>
      </div>
      <div className="stat-grid">
        {stats.map((stat) => (
          <div className="stat-cell" key={stat.key}>
            <div className="stat-label">{stat.label}</div>
            <div className="stat-value">{stat.value}</div>
            <div className="stat-mod" style={{ color: stat.value >= 10 ? "#d98a3a" : "#c44a3c" }}>{mod(stat.value)}</div>
          </div>
        ))}
      </div>
      <div className="profile-derived">
        <div><span>Initiative</span><span>{mod(character?.stats?.dex || 10)}</span></div>
        <div><span>Passive Perception</span><span>{10 + Math.floor(((character?.stats?.wis || 10) - 10) / 2)}</span></div>
        <div><span>Carrying Capacity</span><span>{(character?.stats?.str || 10) * 15} lbs</span></div>
        <div><span>Spell Save DC</span><span>{8 + Math.floor(((character?.stats?.int || 10) - 10) / 2)}</span></div>
      </div>
    </Modal>
  );
}

function SkillsPanel({ character, onClose }) {
  const charClass = character?.class?.toLowerCase() || "fighter";
  const skillData = CLASS_SKILLS[charClass] || { passive: [], spells: [] };
  const [tab, setTab] = useState("abilities");
  const typeColors = { passive: "#8a7859", active: "#d98a3a", recovery: "#6ae0a9", spell: "#9a6eb8" };
  const typeLabels = { passive: "Passive", active: "Active", recovery: "Recovery", spell: "Spell" };

  return (
    <Modal onClose={onClose} title="SKILLS & ABILITIES">
      <div className="skills-char-line">{character?.name} · {character?.race} {character?.class}</div>
      <div className="skills-tabs">
        <button className={tab === "abilities" ? "active" : ""} onClick={() => setTab("abilities")} type="button">Class Abilities</button>
        {skillData.spells.length > 0 ? (
          <button className={tab === "spells" ? "active" : ""} onClick={() => setTab("spells")} type="button">Spells</button>
        ) : null}
      </div>
      {tab === "abilities" ? (
        <ul className="skill-list">
          {skillData.passive.map((skill) => (
            <li className="skill-item" key={skill.name}>
              <div className="skill-header">
                <span className="skill-name">{skill.name}</span>
                <span className="skill-type" style={{ color: typeColors[skill.type] }}>{typeLabels[skill.type]}</span>
              </div>
              <p className="skill-desc">{skill.desc}</p>
              <div className="skill-tags">
                {skill.damage ? <span className="skill-tag damage">⚔ {skill.damage}</span> : null}
                {skill.heal ? <span className="skill-tag heal">💚 {skill.heal}</span> : null}
                {skill.cooldown ? <span className="skill-tag cooldown">⏱ {skill.cooldown}</span> : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      {tab === "spells" && skillData.spells.length > 0 ? (
        <ul className="skill-list">
          {skillData.spells.map((spell) => (
            <li className="skill-item spell-item" key={spell.name}>
              <div className="skill-header">
                <span className="skill-name">{spell.name}</span>
                <span className={`spell-slot-badge ${spell.slot === "Cantrip" ? "cantrip" : ""}`}>{spell.slot}</span>
              </div>
              <p className="skill-desc">{spell.desc}</p>
              <div className="skill-tags">
                {spell.damage ? <span className="skill-tag damage">⚔ {spell.damage}</span> : null}
                {spell.heal ? <span className="skill-tag heal">💚 {spell.heal}</span> : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      {tab === "spells" && skillData.spells.length === 0 ? (
        <p className="skills-empty">
          {charClass === "fighter" ? "Fighters master martial combat, not arcane arts." : "No spells available."}
        </p>
      ) : null}
    </Modal>
  );
}

function JournalPanel({ campaignId, turnIndex, quest, onClose }) {
  const [sceneText, setSceneText] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!campaignId) return;
    setLoading(true);
    api.getState(campaignId)
      .then((payload) => setSceneText(payload?.campaign?.scene || ""))
      .finally(() => setLoading(false));
  }, [campaignId, turnIndex]);

  return (
    <Modal onClose={onClose} title="JOURNAL">
      {loading ? <p>Loading...</p> : (
        <>
          <div className="journal-label">CURRENT SCENE</div>
          <p>{sceneText || "No scene text available."}</p>
          <div className="journal-label">ACTIVE QUEST</div>
          <p className="journal-quest-name">{quest?.title}</p>
          <p>{quest?.description}</p>
          <p className="journal-objective">◆ Explore and gather leads</p>
          <div className="journal-label">SESSION NOTES</div>
          <p className="text-[#8a7859]">
            {turnIndex > 0 ? `${turnIndex} turn${turnIndex !== 1 ? "s" : ""} taken this session.` : "Your story has not yet begun. Take your first action."}
          </p>
        </>
      )}
    </Modal>
  );
}

function ShopPanel({ campaignId, myCharacter, shopData, onClose }) {
  const key = shopData?.key;
  const theme = { ...DEFAULT_SHOP_THEME, ...(SHOP_THEMES[key] || {}) };
  const items = Array.isArray(shopData?.items) ? shopData.items : [];
  const filtered = [...items].sort((a, b) => (a.price || 0) - (b.price || 0));

  return (
    <Modal onClose={onClose} title={`${theme.icon} ${theme.title || shopData?.name || "Shop"}`} wide>
      <div className="mb-3 rounded-lg border p-3" style={{ backgroundColor: theme.bgColor, borderColor: theme.accentColor }}>
        <p className="text-sm text-[#e8d9b8]">{theme.keeper || shopData?.shopkeeper || "Shopkeeper"}</p>
        <p className="text-sm italic text-[#b8a688]">{theme.greeting}</p>
      </div>
      <div className="space-y-2">
        {filtered.map((item) => {
          const tooLow = (myCharacter?.level || 1) < (item.min_level || 1);
          return (
            <div className="rounded-lg border border-[rgba(232,217,184,0.1)] bg-[rgba(255,255,255,0.03)] p-3" key={item.id || item.name}>
              <div className="flex items-center justify-between">
                <p>{item.name}</p>
                <p>{item.price || 0}g</p>
              </div>
              <p className="text-xs text-[#8a7859]">{item.description || item.desc || ""}</p>
              {item.damage ? <p className="text-xs text-[#d98a3a]">Damage: {item.damage}</p> : null}
              {tooLow ? <p className="text-xs text-[#c44a3c]">Requires Level {item.min_level}</p> : null}
            </div>
          );
        })}
        {!filtered.length ? <p className="text-sm text-[#8a7859]">No items available in this shop.</p> : null}
      </div>
      <div className="mt-3 text-right">
        <button className="min-h-11 rounded border border-[#8a6a10] px-4 py-2 text-sm text-[#c9a84c]" onClick={onClose} type="button">Close Shop</button>
      </div>
    </Modal>
  );
}

function PlayScreen() {
  const { id: campaignId } = useParams();
  const navigate = useNavigate();
  const [state, dispatch] = useReducer(playReducer, initialPlayState);
  const [messages, setMessages] = useState(initialMessages);
  const [composerDraft, setComposerDraft] = useState("");
  const [contextualSuggestions, setContextualSuggestions] = useState([]);
  const [isSuggestionsLoading, setIsSuggestionsLoading] = useState(false);
  const [currentLocation, setCurrentLocation] = useState("tavern");
  const [visitedLocations, setVisitedLocations] = useState(
    () => new Set(["tavern"]),
  );
  const [pulseState, setPulseState] = useState({ locationId: "tavern", seq: 0 });
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [voiceSupported, setVoiceSupported] = useState(true);
  const [activePanel, setActivePanel] = useState("");
  const [showPlayers, setShowPlayers] = useState(true);
  const ttsBufferRef = useRef("");
  const recognitionRef = useRef(null);
  const [quest] = useState({
    title: "Echoes in Whisperwood",
    description:
      "Find the missing ranger north of Hollow's End and uncover the source of the strange lights in the pines.",
  });

  const locationMap = useMemo(
    () => Object.fromEntries(locations.map((loc) => [loc.id, loc])),
    [],
  );

  const players = useMemo(() => {
    const dynamic = Object.values(state.characters || {}).map((c, index) => ({
      id: `char-${c.id}`,
      name: c.name,
      className: c.class,
      race: c.race,
      level: c.level,
      hp: c.hp,
      maxHp: c.max_hp,
      online: c.is_online,
      portraitUrl: PORTRAIT_BY_PLAYER_ID[`player-${index + 1}`],
      x: c.map?.x ?? 500,
      y: c.map?.y ?? 500,
    }));
    return dynamic.length ? dynamic : initialPlayers;
  }, [state.characters]);

  const chatPlayer = useMemo(() => {
    const mine = state.myCharacterId ? state.characters[state.myCharacterId] : null;
    if (mine) {
      return {
        id: `char-${mine.id}`,
        name: mine.name,
        className: mine.class,
        race: mine.race,
        level: mine.level,
        hp: mine.hp,
        maxHp: mine.max_hp,
        online: mine.is_online,
      };
    }
    return players.find((p) => p.id === CURRENT_PLAYER_ID) || players[0];
  }, [players, state.characters, state.myCharacterId]);
  const dmSuggestionContext = useMemo(
    () =>
      messages
        .filter((message) => message.role === "dm")
        .slice(-3)
        .map((message) => message.text.trim())
        .filter(Boolean)
        .join("\n\n"),
    [messages],
  );

  const detectLocationFromDmText = (text) => {
    const haystack = String(text || "").toLowerCase();
    for (const [locId, keywords] of Object.entries(LOCATION_KEYWORDS)) {
      if (keywords.some((keyword) => haystack.includes(keyword))) {
        return locId;
      }
    }
    return null;
  };

  const applyDetectedLocation = (locId) => {
    if (!locId || !locationMap[locId]) return;
    setCurrentLocation((prev) => {
      if (prev === locId) return prev;
      setPulseState((pulsePrev) => ({ locationId: locId, seq: pulsePrev.seq + 1 }));
      return locId;
    });
  };

  const tryFlushTTS = useCallback(
    (newText) => {
      if (!ttsEnabled || !window.speechSynthesis) return;
      ttsBufferRef.current += newText;
      const lastEnd = Math.max(
        ttsBufferRef.current.lastIndexOf("."),
        ttsBufferRef.current.lastIndexOf("!"),
        ttsBufferRef.current.lastIndexOf("?"),
      );
      if (lastEnd < 0) return;
      const chunk = ttsBufferRef.current.slice(0, lastEnd + 1);
      ttsBufferRef.current = ttsBufferRef.current.slice(lastEnd + 1);
      const utter = new SpeechSynthesisUtterance(chunk);
      utter.rate = 0.98;
      utter.pitch = 0.92;
      window.speechSynthesis.speak(utter);
    },
    [ttsEnabled],
  );

  useEffect(() => {
    setVisitedLocations((prev) => {
      const next = new Set(prev);
      next.add(currentLocation);
      return next;
    });
  }, [currentLocation]);

  const handleSendAction = useCallback((text) => {
    setMessages((prev) => [
      ...prev,
      {
        id: `p-${Date.now()}`,
        role: "player",
        author: "You",
        text,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      },
    ]);
    if (campaignId) submitAction(campaignId, text);
    setComposerDraft("");
  }, [campaignId]);

  useEffect(() => {
    if (!ANTHROPIC_API_KEY || !dmSuggestionContext) {
      setContextualSuggestions([]);
      setIsSuggestionsLoading(false);
      return undefined;
    }

    const controller = new AbortController();
    let alive = true;

    const fetchSuggestions = async () => {
      setIsSuggestionsLoading(true);
      try {
        const response = await fetch("https://api.anthropic.com/v1/messages", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
          },
          body: JSON.stringify({
            model: SUGGESTION_MODEL,
            max_tokens: 100,
            system: SUGGESTION_SYSTEM_PROMPT,
            messages: [{ role: "user", content: dmSuggestionContext }],
          }),
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`Claude suggestion request failed: ${response.status}`);
        }

        const data = await response.json();
        const rawText = data?.content?.find((item) => item?.type === "text")?.text?.trim();
        if (!rawText) throw new Error("No text content returned from Claude");

        const parsed = JSON.parse(rawText);
        if (!Array.isArray(parsed) || parsed.length < 3) {
          throw new Error("Claude suggestions payload was not a 3-item array");
        }

        const next = parsed
          .slice(0, 3)
          .map((item) => String(item).trim())
          .filter(Boolean);

        if (alive && next.length === 3) {
          setContextualSuggestions(next);
        } else if (alive) {
          setContextualSuggestions([]);
        }
      } catch {
        if (alive) {
          setContextualSuggestions([]);
        }
      } finally {
        if (alive) {
          setIsSuggestionsLoading(false);
        }
      }
    };

    fetchSuggestions();

    return () => {
      alive = false;
      controller.abort();
    };
  }, [dmSuggestionContext]);

  useEffect(() => {
    const Recog = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recog) {
      setVoiceSupported(false);
      return;
    }
    const rec = new Recog();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = (event) => {
      const transcript = event?.results?.[0]?.[0]?.transcript;
      if (transcript) setComposerDraft(transcript);
    };
    recognitionRef.current = rec;
  }, []);

  useEffect(() => {
    let mounted = true;
    if (!campaignId) return undefined;
    setMessages([]);
    setComposerDraft("");
    setContextualSuggestions([]);
    setCurrentLocation("tavern");
    setVisitedLocations(new Set(["tavern"]));
    setPulseState({ locationId: "tavern", seq: 0 });
    setActivePanel("");

    api.me().catch(() => {
      window.location.href = "/auth/login";
    });

    socket.connect();
    socket.on("connect", () => joinCampaignRoom(campaignId));

    api.getState(campaignId)
      .then((payload) => {
        if (mounted && payload) dispatch({ type: "HYDRATE", payload });
      })
      .catch(() => {});

    socket.on("joined_campaign", (d) => dispatch({ type: "JOINED", payload: d }));
    socket.on("turn_started", (d) => dispatch({ type: "TURN_STARTED", payload: d }));
    socket.on("narration_delta", (d) => {
      const text = d?.text || "";
      dispatch({ type: "NARRATION_DELTA", text });
      tryFlushTTS(text);
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last?.role === "dm" && last?.streaming) {
          const next = [...prev];
          next[next.length - 1] = { ...last, text: `${last.text}${text}` };
          return next;
        }
        return [
          ...prev,
          {
            id: `dm-${Date.now()}`,
            role: "dm",
            author: "DM",
            text,
            streaming: true,
            timestamp: new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }),
          },
        ];
      });
      applyDetectedLocation(detectLocationFromDmText(text));
    });
    socket.on("mutation", async (d) => {
      if (d?.name === "open_shop" && d?.result?.shop_key && campaignId) {
        try {
          const shopData = await api.getShop(campaignId, d.result.shop_key);
          dispatch({ type: "OPEN_SHOP", payload: shopData });
          return;
        } catch {
          // fallback to existing mutation path
        }
      }
      dispatch({ type: "MUTATION", payload: d });
    });
    socket.on("state_update", (d) => dispatch({ type: "STATE_UPDATE", payload: d }));
    socket.on("turn_complete", () => {
      dispatch({ type: "TURN_COMPLETE" });
      setMessages((prev) =>
        prev.map((m, idx) => (idx === prev.length - 1 && m.role === "dm" ? { ...m, streaming: false } : m)),
      );
    });
    socket.on("dm_error", (d) => dispatch({ type: "DM_ERROR", message: d?.message || "DM error" }));
    socket.on("shop_update", (d) => dispatch({ type: "SHOP_UPDATE", payload: d }));
    socket.on("character_joined", (d) => dispatch({ type: "CHARACTER_JOINED", payload: d }));
    socket.on("presence_update", (d) => dispatch({ type: "PRESENCE_UPDATE", payload: d }));
    socket.on("auth_error", () => {
      window.location.href = "/auth/login";
    });

    return () => {
      mounted = false;
      leaveCampaignRoom(campaignId);
      socket.off();
      socket.disconnect();
    };
  }, [campaignId, tryFlushTTS]);

  useEffect(() => {
    if (!state.campaign?.scene || state.campaign.scene.length === 0) return;
    if (messages.length !== 0) return;
    setMessages([{
      id: "opening",
      role: "dm",
      type: "dm",
      author: "Dungeon Master",
      text: state.campaign.scene,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    }]);
  }, [state.campaign?.scene]);

  useEffect(() => {
    if (!import.meta.env.DEV) return;
    if (!state.campaign) return;
    // Dev verification: ensure API state has campaign.scene available for opening message.
    // eslint-disable-next-line no-console
    console.log("campaign state loaded", state.campaign);
  }, [state.campaign]);

  const handleVoiceInput = useCallback(() => {
    if (!voiceSupported || !recognitionRef.current) return;
    recognitionRef.current.start();
  }, [voiceSupported]);

  const myCharacter = state.myCharacterId ? state.characters[state.myCharacterId] : null;
  const turnIndex = state.campaign?.turn_index || 0;
  const turnLabel = turnIndex > 0 ? `Turn ${turnIndex}` : "Begin your adventure";

  useEffect(() => {
    if (!state.activeShop?.key || !campaignId) return;
    if (state.activeShop?.items) return;
    api.getShop(campaignId, state.activeShop.key)
      .then((shop) => dispatch({ type: "SHOP_UPDATE", payload: { shop } }))
      .catch(() => {});
  }, [campaignId, state.activeShop?.key, state.activeShop?.items, dispatch]);

  return (
    <main className="relative grid h-dvh grid-rows-[auto_1fr] overflow-hidden bg-[#0d0900] p-3 font-serif text-[#d4c4a0]">
      <TopNavBar
        campaignTitle="EMBERVALE"
        locationLabel={locationMap[currentLocation]?.name || state.campaign?.scene || "Unknown Location"}
        onExit={() => navigate("/")}
        onOpenHelp={() => setActivePanel("help")}
        onToggleTts={() => {
          setTtsEnabled((prev) => !prev);
          if (window.speechSynthesis) window.speechSynthesis.cancel();
        }}
        ttsEnabled={ttsEnabled}
      />

      <div className="mt-2 grid min-h-0 grid-cols-1 gap-0 overflow-hidden lg:grid-cols-[32%_43%_25%]">
        <div className="min-h-0 pr-2 lg:border-r lg:border-[#2a1e0e]">
          <MapPanel
            activeLocationId={currentLocation}
            backendLocations={state.locations}
            locations={locations}
            onTogglePlayers={() => setShowPlayers((prev) => !prev)}
            playerMarkers={Object.values(state.characters || {})}
            showPlayers={showPlayers}
            visitedLocations={visitedLocations}
          />
        </div>

        <div className="flex min-h-0 flex-col gap-3 px-2 lg:border-r lg:border-[#2a1e0e]">
          <StoryPanel
            chatPlayer={chatPlayer}
            messages={messages}
            turnLabel={turnLabel}
          />
          <ActionComposer
            dmThinking={state.dmThinking}
            onChange={setComposerDraft}
            onSendAction={handleSendAction}
            onVoiceInput={handleVoiceInput}
            suggestions={contextualSuggestions}
            suggestionsLoading={isSuggestionsLoading}
            value={composerDraft}
            voiceSupported={voiceSupported}
          />
          {!voiceSupported ? (
            <p className="px-1 text-xs text-[#6b5a3a]">Voice input is unavailable in this browser.</p>
          ) : null}
        </div>

        <div className="flex min-h-0 min-w-0 flex-col overflow-hidden pl-2">
          <div className="min-h-0 flex-1">
            <PartyPanel players={players} />
          </div>
          <div className="mt-3 min-h-0">
            <QuestPanel quest={quest} />
          </div>
          <div className="grid w-full grid-cols-2 gap-3 pb-3 pt-3">
            {["Inventory", "Skills", "Journal", "Profile"].map((label) => (
              <button
                key={label}
                className="min-h-11 w-full rounded-lg border border-[#3a2a14] bg-[#1a1308] px-3 py-2 text-center font-serif text-xs text-[#8a7a5a] transition hover:bg-[#1e1610]"
                onClick={() => {
                  if (label === "Inventory") {
                    setActivePanel("inventory");
                  } else if (label === "Skills") {
                    setActivePanel("skills");
                  } else if (label === "Journal") {
                    setActivePanel("journal");
                  } else if (label === "Profile") {
                    setActivePanel("profile");
                  }
                }}
                type="button"
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {state.activeShop ? (
        <ShopPanel
          campaignId={campaignId}
          myCharacter={myCharacter}
          onClose={() => dispatch({ type: "CLOSE_SHOP" })}
          shopData={state.activeShop}
        />
      ) : null}

      {activePanel === "help" ? (
        <Modal onClose={() => setActivePanel("")} title="How to Play">
          <p className="text-sm text-[#b59f77]">Type actions and press Enter or the send button. The DM streams responses into the story panel.</p>
        </Modal>
      ) : null}
      {activePanel === "inventory" ? <InventoryPanel character={myCharacter} onClose={() => setActivePanel("")} /> : null}
      {activePanel === "profile" ? <ProfilePanel character={myCharacter} onClose={() => setActivePanel("")} /> : null}
      {activePanel === "skills" ? <SkillsPanel character={myCharacter} onClose={() => setActivePanel("")} /> : null}
      {activePanel === "journal" ? <JournalPanel campaignId={campaignId} onClose={() => setActivePanel("")} quest={quest} turnIndex={turnIndex} /> : null}
    </main>
  );
}

function PlayRoute() {
  const { id } = useParams();
  return <PlayScreen key={id} />;
}

function HomeRoute() {
  const navigate = useNavigate();
  return (
    <HomeScreen
      onHowToPlay={() => navigate("/how-to-play")}
      onNewGame={() => navigate("/campaigns/new")}
      onResume={() => navigate("/campaigns/resume")}
    />
  );
}

function HowToPlayPage() {
  const navigate = useNavigate();
  return (
    <main className="grid min-h-screen place-items-center bg-[#0d0900] p-6 text-[#d4c4a0]">
      <section className="max-w-2xl rounded-xl border border-[#2a1e0e] bg-[#12100a] p-6">
        <h1 className="mb-4 text-2xl">How To Play</h1>
        <p className="mb-4 text-sm text-[#b59f77]">
          Create a campaign, build your character, then play through scenes by sending actions.
          The DM narrates outcomes and updates the world state.
        </p>
        <button
          className="rounded border border-[#8a6a10] bg-[rgba(5,3,0,0.75)] px-4 py-2 text-sm text-[#c9a84c]"
          onClick={() => navigate("/")}
          type="button"
        >
          Back
        </button>
      </section>
    </main>
  );
}

function NewCampaignPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const createCampaign = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const result = await api.createCampaign(name.trim());
      if (!result?.campaign?.id) throw new Error("Campaign creation failed");
      navigate(`/campaigns/${result.campaign.id}/character/new`);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="grid min-h-screen place-items-center bg-[#0d0900] p-6 text-[#d4c4a0]">
      <form className="w-full max-w-md rounded-xl border border-[#2a1e0e] bg-[#12100a] p-6" onSubmit={createCampaign}>
        <h1 className="mb-4 text-xl">New Campaign</h1>
        <input
          className="mb-3 w-full rounded border border-[#3a2a14] bg-[#1a1308] px-3 py-2 outline-none"
          onChange={(e) => setName(e.target.value)}
          placeholder="Campaign name"
          value={name}
        />
        {error ? <p className="mb-3 text-xs text-red-300">{error}</p> : null}
        <button
          className="w-full rounded border border-[#8a6a10] bg-[rgba(5,3,0,0.75)] px-4 py-2 text-sm text-[#c9a84c] disabled:opacity-60"
          disabled={saving || !name.trim()}
          type="submit"
        >
          {saving ? "Creating..." : "Create Campaign"}
        </button>
      </form>
    </main>
  );
}

function ResumeCampaignsPage() {
  const navigate = useNavigate();
  const [campaigns, setCampaigns] = useState([]);
  const [joinCode, setJoinCode] = useState("");
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");

  useEffect(() => {
    api.listCampaigns().then((list) => setCampaigns(list || [])).catch((e) => setError(e.message));
  }, []);

  const joinByCode = async () => {
    setError("");
    try {
      const result = await api.joinCampaign(joinCode.trim());
      if (!result?.campaign?.id) throw new Error("Join failed");
      navigate(result.has_character ? `/campaigns/${result.campaign.id}/play` : `/campaigns/${result.campaign.id}/character/new`);
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <main className="grid min-h-screen place-items-center bg-[#0d0900] p-6 text-[#d4c4a0]">
      <section className="w-full max-w-2xl rounded-xl border border-[#2a1e0e] bg-[#12100a] p-6">
        <h1 className="mb-4 text-xl">Resume Campaign</h1>
        <div className="mb-5 flex gap-2">
          <input
            className="flex-1 rounded border border-[#3a2a14] bg-[#1a1308] px-3 py-2 outline-none"
            onChange={(e) => setJoinCode(e.target.value)}
            placeholder="Join code"
            value={joinCode}
          />
          <button
            className="rounded border border-[#8a6a10] bg-[rgba(5,3,0,0.75)] px-4 py-2 text-sm text-[#c9a84c]"
            onClick={joinByCode}
            type="button"
          >
            Join
          </button>
        </div>
        {error ? <p className="mb-3 text-xs text-red-300">{error}</p> : null}
        <div className="space-y-2">
          {campaigns.map((campaign) => (
            <div key={campaign.id} className="flex items-center justify-between rounded border border-[#2a1e0e] bg-[#151108] p-3">
              <div>
                <p className="text-sm">{campaign.name}</p>
                <p className="text-xs text-[#b59f77]">Code: {campaign.join_code}</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  className="rounded border border-[#3a2a14] bg-[#1a1308] px-3 py-1.5 text-xs text-[#d4c4a0]"
                  onClick={async () => {
                    await navigator.clipboard.writeText(campaign.join_code);
                    setToast("Join code copied");
                    window.setTimeout(() => setToast(""), 1300);
                  }}
                  type="button"
                >
                  Copy Code
                </button>
                <button
                  className="rounded border border-[#8a6a10] bg-[rgba(5,3,0,0.75)] px-3 py-1.5 text-xs text-[#c9a84c]"
                  onClick={() => navigate(campaign.character ? `/campaigns/${campaign.id}/play` : `/campaigns/${campaign.id}/character/new`)}
                  type="button"
                >
                  {campaign.character ? "Play" : "Create Character"}
                </button>
              </div>
            </div>
          ))}
        </div>
        {toast ? <p className="mt-3 text-xs text-[#8fbf9f]">{toast}</p> : null}
      </section>
    </main>
  );
}

function CharacterCreationPage() {
  const { id: campaignId } = useParams();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [race, setRace] = useState("Human");
  const [charClass, setCharClass] = useState("fighter");
  const [rolledStats, setRolledStats] = useState(null);
  const [rollsLeft, setRollsLeft] = useState(3);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const rollStats = () => {
    if (rollsLeft <= 0) return;
    const roll4d6 = () => {
      const dice = Array.from({ length: 4 }, () => Math.floor(Math.random() * 6) + 1);
      dice.sort((a, b) => a - b);
      return dice.slice(1).reduce((a, b) => a + b, 0);
    };
    setRolledStats({
      str: roll4d6(),
      dex: roll4d6(),
      con: roll4d6(),
      int: roll4d6(),
      wis: roll4d6(),
      cha: roll4d6(),
    });
    setRollsLeft((r) => r - 1);
  };

  const finalStats = useMemo(() => getFinalStats(rolledStats, race, charClass), [charClass, race, rolledStats]);
  const raceMods = useMemo(() => RACE_BONUSES[race] || {}, [race]);
  const classMods = useMemo(() => CLASS_BONUSES[charClass] || {}, [charClass]);
  const selectedClass = CLASS_INFO[charClass];

  const submit = async (event) => {
    event.preventDefault();
    if (!campaignId) return;
    setLoading(true);
    setError("");
    try {
      await api.createCharacter(campaignId, {
        name,
        race,
        class: charClass,
        strength: finalStats.str,
        dexterity: finalStats.dex,
        constitution: finalStats.con,
        intelligence: finalStats.int,
        wisdom: finalStats.wis,
        charisma: finalStats.cha,
        max_hp: selectedClass.hp,
        armor_class: selectedClass.ac,
      });
      navigate(`/campaigns/${campaignId}/play`);
    } catch (e) {
      setError(e.message);
      setLoading(false);
    }
  };

  return (
    <main className="grid min-h-screen place-items-center bg-[#0a0908] p-6 text-[#e8d9b8]">
      <form className="w-full max-w-4xl rounded-2xl border border-[rgba(232,217,184,0.12)] bg-[#14100c] p-6 shadow-[0_12px_40px_rgba(0,0,0,0.55)] md:p-8" onSubmit={submit}>
        <h1 className="mb-6 text-center text-3xl tracking-[0.06em] md:text-4xl" style={{ fontFamily: "Cinzel, serif" }}>
          Create Character
        </h1>
        <div className="grid gap-4">
          <label className="grid gap-1.5">
            <span className="text-xs uppercase tracking-[0.15em] text-[#b8a688]" style={{ fontFamily: "Cinzel, serif" }}>Name</span>
            <input
              className="min-h-11 rounded border border-[rgba(232,217,184,0.22)] bg-[#1d1812] px-3 py-2 text-base text-[#e8d9b8] outline-none focus:border-[#d98a3a]"
              onChange={(e) => setName(e.target.value)}
              placeholder="Name"
              value={name}
            />
          </label>

          <label className="grid gap-1.5">
            <span className="text-xs uppercase tracking-[0.15em] text-[#b8a688]" style={{ fontFamily: "Cinzel, serif" }}>Race</span>
            <select
              className="min-h-11 rounded border border-[rgba(232,217,184,0.22)] bg-[#1d1812] px-3 py-2 text-base text-[#e8d9b8] outline-none focus:border-[#d98a3a]"
              onChange={(e) => setRace(e.target.value)}
              value={race}
            >
              {Object.keys(RACE_BONUSES).map((raceName) => (
                <option key={raceName} value={raceName}>{raceName}</option>
              ))}
            </select>
          </label>

          <p className="text-sm italic text-[#d98a3a]">{RACE_BONUS_LABELS[race]}</p>

          <div>
            <p className="mb-2 text-xs uppercase tracking-[0.15em] text-[#b8a688]" style={{ fontFamily: "Cinzel, serif" }}>Class</p>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              {Object.entries(CLASS_INFO).map(([key, klass]) => {
                const selected = key === charClass;
                return (
                  <button
                    className={`min-h-11 rounded-lg border px-4 py-3 text-left transition ${
                      selected
                        ? "border-[#d98a3a] bg-[rgba(217,138,58,0.09)] shadow-[0_0_14px_rgba(217,138,58,0.5)]"
                        : "border-[rgba(232,217,184,0.18)] bg-[#1d1812] hover:border-[#d98a3a]"
                    }`}
                    key={key}
                    onClick={() => setCharClass(key)}
                    type="button"
                  >
                    <p className="text-lg uppercase tracking-[0.05em]" style={{ fontFamily: "Cinzel, serif" }}>{klass.label}</p>
                    <p className="text-xs text-[#b8a688]">HP {klass.hp} · AC {klass.ac}</p>
                    <p className="mt-1 text-xs">
                      {Object.entries(CLASS_BONUSES[key])
                        .filter(([, val]) => val !== 0)
                        .map(([stat, val]) => (
                          <span
                            key={stat}
                            style={{ color: val > 0 ? "#d98a3a" : "#c44a3c", marginRight: "8px" }}
                          >
                            {val > 0 ? "+" : ""}
                            {val} {stat.toUpperCase()}
                          </span>
                        ))}
                    </p>
                    <p className="mt-2 text-sm text-[#b8a688]">{klass.desc}</p>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="rounded-lg border border-[rgba(232,217,184,0.14)] bg-[#1a140f] p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs uppercase tracking-[0.15em] text-[#b8a688]" style={{ fontFamily: "Cinzel, serif" }}>Final Stats</p>
              {rolledStats ? <p className="text-xs text-[#d98a3a]">Using rolled stats</p> : <p className="text-xs text-[#8a7859]">Roll your stats to begin</p>}
            </div>
            {!rolledStats ? (
              <p className="text-sm italic text-[#8a7859]">- Roll your stats above to see final values -</p>
            ) : (
              <div className="space-y-2 text-sm">
                <div className="grid grid-cols-7 gap-2 rounded border border-[rgba(232,217,184,0.12)] bg-[#14100c] p-2">
                  <p className="text-[#8a7859]">Rolled</p>
                  {STAT_KEYS.map((key) => <p key={`rolled-${key}`} className="text-[#8a7859]">{STAT_LABELS[key]} {rolledStats[key]}</p>)}
                </div>
                <div className="grid grid-cols-7 gap-2 rounded border border-[rgba(232,217,184,0.12)] bg-[#14100c] p-2">
                  <p className="text-[#8a7859]">Race</p>
                  {STAT_KEYS.map((key) => {
                    const val = raceMods[key] || 0;
                    const color = val > 0 ? "#d98a3a" : val < 0 ? "#c44a3c" : "#8a7859";
                    return <p key={`race-${key}`} style={{ color }}>{val >= 0 ? "+" : ""}{val}</p>;
                  })}
                </div>
                <div className="grid grid-cols-7 gap-2 rounded border border-[rgba(232,217,184,0.12)] bg-[#14100c] p-2">
                  <p className="text-[#8a7859]">Class</p>
                  {STAT_KEYS.map((key) => {
                    const val = classMods[key] || 0;
                    const color = val > 0 ? "#d98a3a" : val < 0 ? "#c44a3c" : "#8a7859";
                    return <p key={`class-${key}`} style={{ color }}>{val >= 0 ? "+" : ""}{val}</p>;
                  })}
                </div>
                <div className="grid grid-cols-7 gap-2 rounded border border-[rgba(232,217,184,0.12)] bg-[#14100c] p-2">
                  <p className="text-[#e8d9b8]">Final</p>
                  {STAT_KEYS.map((key) => (
                    <div key={`final-${key}`}>
                      <p className="text-[#e8d9b8]" style={{ fontFamily: "JetBrains Mono, monospace" }}>{STAT_LABELS[key]} {finalStats[key]}</p>
                      <p style={{ color: mod(finalStats[key]).startsWith("+") ? "#d98a3a" : mod(finalStats[key]) === "+0" ? "#8a7859" : "#c44a3c" }}>
                        ({mod(finalStats[key])})
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              className="min-h-11 rounded border border-[#8a6a10] px-4 py-2 text-sm disabled:opacity-60"
              disabled={rollsLeft <= 0}
              onClick={rollStats}
              type="button"
            >
              {rollsLeft > 0 ? "Roll Stats" : "No rolls remaining"}
            </button>
            <span className="text-sm text-[#b8a688]">Rolls remaining: {rollsLeft}</span>
          </div>

          {error ? <p className="text-xs text-red-300">{error}</p> : null}
          <button className="min-h-11 rounded border border-[#8a6a10] bg-[rgba(5,3,0,0.75)] px-4 py-2 text-sm text-[#c9a84c] disabled:opacity-60" disabled={loading || !name.trim() || !rolledStats} title={!rolledStats ? "Roll your stats first" : ""} type="submit">
            {loading ? "Creating..." : "Enter the Story"}
          </button>
        </div>
      </form>
    </main>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<HomeRoute />} path="/" />
      <Route element={<HowToPlayPage />} path="/how-to-play" />
      <Route
        element={(
          <AuthGuard>
            <NewCampaignPage />
          </AuthGuard>
        )}
        path="/campaigns/new"
      />
      <Route
        element={(
          <AuthGuard>
            <ResumeCampaignsPage />
          </AuthGuard>
        )}
        path="/campaigns/resume"
      />
      <Route
        element={(
          <AuthGuard>
            <CharacterCreationPage />
          </AuthGuard>
        )}
        path="/campaigns/:id/character/new"
      />
      <Route
        element={(
          <AuthGuard>
            <PlayRoute />
          </AuthGuard>
        )}
        path="/campaigns/:id/play"
      />
      <Route element={<Navigate replace to="/" />} path="*" />
    </Routes>
  );
}
