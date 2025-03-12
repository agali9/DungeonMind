/* =====================================================================
   Embervale play-screen client.

   Responsibilities:
     - Socket.IO lifecycle (connect, join room, resume)
     - SVG map rendering & live player-pin updates
     - Streaming narration with sentence-chunked Web Speech TTS
     - Push-to-hold Web Speech STT on the mic button
     - Shop modal (opens when DM calls open_shop)
     - Battle modal (opens when DM calls start_combat)
     - Periodic metrics refresh

   Designed to be resilient: if any browser feature is unsupported (no STT
   in Firefox, no dialog element on very old mobile), the app still works
   in text-only mode.
   ===================================================================== */

(function () {
  "use strict";

  const root = document.getElementById("game-root");
  if (!root) return;

  const CAMPAIGN_ID = parseInt(root.dataset.campaignId, 10);
  const MY_CHAR_ID = parseInt(root.dataset.myCharacterId, 10);
  const IS_OWNER = root.dataset.isOwner === "true";
  const JOIN_CODE = root.dataset.joinCode || "";

  // ------------------------------------------------------------------
  // State
  // ------------------------------------------------------------------
  const state = {
    characters: new Map(),       // id -> character dict
    locations: new Map(),        // id -> location dict
    locationsByKey: new Map(),
    mode: "exploration",
    scene: "",
    turnIndex: 0,
    ttsEnabled: true,
    battle: null,
    activeShop: null,
    battleTargetId: null,
    currentDmParagraph: "",      // accumulated narration so far this turn
    lastSpokenIdx: 0,            // char index up to which TTS has been kicked off
    reconnectEntry: null,
    actionHistory: [],
    actingEntry: null,
    mapZoom: 1,
    mapPinEls: new Map(),
    activeProfileCharacterId: null,
    exploreMode: false,
    tempLocations: [],
    explorerPos: null,
    explorerTokenEl: null,
  };

  // ------------------------------------------------------------------
  // Small DOM helpers
  // ------------------------------------------------------------------
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const bind = (name) => $$(`[data-bind="${name}"]`);
  const setText = (name, value) => bind(name).forEach((el) => (el.textContent = value));

  function esc(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  // ------------------------------------------------------------------
  // Log entries
  // ------------------------------------------------------------------
  const logEl = $("#log");

  function appendLog(html, cls) {
    const div = document.createElement("article");
    div.className = "story-card " + (cls || "");
    div.innerHTML = html;
    logEl.appendChild(div);
    logEl.scrollTo({ top: logEl.scrollHeight, behavior: "smooth" });
    return div;
  }

  function mutationLabel(mut) {
    const a = mut.args || {};
    const r = mut.result || {};
    switch (mut.name) {
      case "roll_dice":
        return `<strong>Rolled ${esc(r.expression || "")}</strong>${
          r.reason ? ` for ${esc(r.reason)}` : ""
        } → <strong>${esc(r.total)}</strong>${
          r.rolls ? ` <span style="opacity:0.6">[${r.rolls.join(", ")}]</span>` : ""
        }`;
      case "apply_damage":
        return `<strong>${esc(r.name || "?")}</strong> takes ${esc(a.amount)} damage → HP ${esc(r.hp_after)}/${esc(r.max_hp)}${r.downed ? " <strong>(downed)</strong>" : ""}`;
      case "heal":
        return `<strong>${esc(r.name || "?")}</strong> healed for ${esc(a.amount)} → HP ${esc(r.hp_after)}/${esc(r.max_hp)}`;
      case "update_inventory":
        return `${esc(r.character || "?")} ${a.delta > 0 ? "gains" : "loses"} <strong>${esc(a.item_name)}</strong>`;
      case "move_character":
        return `${esc(r.character || "?")} moves to <strong>${esc(r.location || a.location_key)}</strong>`;
      case "open_shop":
        return `Entered <strong>${esc(r.name || a.shop_key)}</strong>`;
      case "start_combat":
        return `<strong>Combat begins.</strong>`;
      case "end_combat":
        return `<strong>Combat ends</strong> (${esc(a.outcome)})`;
      case "advance_scene":
        return `<em>${esc(r.scene || "")}</em>`;
      default:
        return `<strong>${esc(mut.name)}</strong> ${esc(JSON.stringify(a))}`;
    }
  }

  function rollDiceMarkup(mut) {
    const r = mut.result || {};
    return `
      <span class="dice-roll-wrap">
        <svg class="dice-roll-icon" viewBox="0 0 100 100" aria-hidden="true" focusable="false">
          <polygon points="50,8 86,28 86,72 50,92 14,72 14,28" />
          <text x="50" y="58" text-anchor="middle">${esc(r.total ?? "?")}</text>
        </svg>
      </span>
      <span>${mutationLabel(mut)}</span>
    `;
  }

  // ------------------------------------------------------------------
  // Party rail
  // ------------------------------------------------------------------
  const partyEl = $("#party-list");

  function renderParty() {
    partyEl.innerHTML = "";
    const chars = [...state.characters.values()].sort((a, b) => {
      if (a.id === MY_CHAR_ID) return -1;
      if (b.id === MY_CHAR_ID) return 1;
      return a.id - b.id;
    });
    chars.forEach((c) => {
      const pct = c.max_hp > 0 ? Math.max(0, Math.min(100, (c.hp / c.max_hp) * 100)) : 0;
      const hpCls = pct < 25 ? "critical" : pct < 55 ? "low" : "";
      const li = document.createElement("li");
      li.className =
        "party-card" +
        (c.id === MY_CHAR_ID ? " is-self" : "") +
        (c.hp <= 0 ? " is-downed" : "");
      li.innerHTML = `
        <div class="party-card-head">
          <span class="char-pin" style="--pin: ${esc(c.pin_color)}"></span>
          <div style="flex:1">
            <div class="party-card-name">${esc(c.name)}</div>
            <div class="party-card-meta">${esc(c.race)} ${esc(c["class"] || c.char_class || "")} · L${esc(c.level)} · AC ${esc(c.ac)} · ${esc(c.gold)}g</div>
          </div>
          <span class="party-dot ${c.is_online ? "online" : ""}"></span>
        </div>
        <div class="hp-bar"><div class="hp-bar-fill ${hpCls}" style="width:${pct}%"></div></div>
        <div class="hp-text"><span>HP</span><span>${esc(c.hp)}/${esc(c.max_hp)}</span></div>
        <button class="btn-ghost profile-open-btn" data-character-id="${c.id}">👤 Profile</button>
      `;
      partyEl.appendChild(li);
    });
  }

  // ------------------------------------------------------------------
  // SVG map
  // ------------------------------------------------------------------
  const mapLocationsEl = document.getElementById("map-locations");
  const mapRoutesEl = document.getElementById("map-routes");
  const mapPinsEl = document.getElementById("map-pins");
  const mapZoomGroup = document.getElementById("map-zoom-group");
  const mapSvg = document.getElementById("world-map");
  const SVG = "http://www.w3.org/2000/svg";
  const MAX_TEMP_LOCATIONS = 8;
  const TEMP_LOCATION_TTL_MS = 90000;
  const NODE_SNAP_DISTANCE = 42;
  const LOCATION_ICON_PATHS = {
    tavern: "/static/icons/tavern.svg",
    village_square: "/static/icons/city.svg",
    forest: "/static/icons/forest.svg",
    cave: "/static/icons/cave.svg",
    ruins: "/static/icons/ruins.svg",
    smithy: "/static/icons/castle.svg",
    apothecary: "/static/icons/city.svg",
    road: "/static/icons/city.svg",
    river: "/static/icons/forest.svg",
  };
  const MAJOR_ROUTE_KEYS = [
    ["village_square", "tavern"],
    ["tavern", "smithy"],
    ["village_square", "forest"],
    ["forest", "ruins"],
    ["ruins", "cave"],
    ["village_square", "apothecary"],
  ];

  function renderMapRoutes() {
    if (!mapRoutesEl) return;
    mapRoutesEl.innerHTML = "";
    MAJOR_ROUTE_KEYS.forEach(([fromKey, toKey]) => {
      const from = state.locationsByKey.get(fromKey);
      const to = state.locationsByKey.get(toKey);
      if (!from || !to) return;
      const path = document.createElementNS(SVG, "path");
      path.classList.add("map-major-route");
      const cx = (from.x + to.x) / 2;
      const cy = (from.y + to.y) / 2 - 24;
      path.setAttribute("d", `M ${from.x} ${from.y} Q ${cx} ${cy} ${to.x} ${to.y}`);
      mapRoutesEl.appendChild(path);
    });
  }

  function renderMapLocations() {
    mapLocationsEl.innerHTML = "";
    state.locations.forEach((loc) => {
      const g = document.createElementNS(SVG, "g");
      g.classList.add("map-location");
      g.setAttribute("aria-label", loc.name);
      g.setAttribute("transform", `translate(${loc.x}, ${loc.y})`);
      const iconHref = LOCATION_ICON_PATHS[loc.key] || "/static/icons/city.svg";
      const icon = document.createElementNS(SVG, "image");
      icon.setAttribute("href", iconHref);
      icon.setAttribute("x", "-18");
      icon.setAttribute("y", "-28");
      icon.setAttribute("width", "36");
      icon.setAttribute("height", "36");
      icon.setAttribute("preserveAspectRatio", "xMidYMid meet");
      icon.classList.add("map-location-icon");
      g.appendChild(icon);

      const labelY = loc.y + 36;
      const clampedX = Math.max(80, Math.min(920, loc.x));

      const connector = document.createElementNS(SVG, "path");
      connector.classList.add("map-waypoint-path");
      connector.setAttribute("d", `M ${loc.x} ${loc.y + 10} Q ${loc.x + 8} ${labelY - 8} ${clampedX} ${labelY - 10}`);
      mapLocationsEl.appendChild(connector);

      const banner = document.createElementNS(SVG, "rect");
      banner.classList.add("map-location-banner");
      const bannerWidth = Math.max(74, loc.name.length * 7.4);
      banner.setAttribute("x", clampedX - bannerWidth / 2);
      banner.setAttribute("y", labelY - 14);
      banner.setAttribute("width", bannerWidth);
      banner.setAttribute("height", 18);
      banner.setAttribute("rx", "9");
      mapLocationsEl.appendChild(banner);

      const label = document.createElementNS(SVG, "text");
      label.classList.add("map-location-label");
      label.setAttribute("x", clampedX);
      label.setAttribute("y", labelY);
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("fill", "#3d1f08");
      label.setAttribute("stroke", "#dfc078");
      label.setAttribute("stroke-width", "3");
      label.setAttribute("paint-order", "stroke");
      label.setAttribute("font-size", "11");
      label.setAttribute("font-family", "Cinzel, serif");
      label.setAttribute("font-weight", "600");
      label.textContent = loc.name;
      mapLocationsEl.appendChild(g);
      mapLocationsEl.appendChild(label);

      const title = document.createElementNS(SVG, "title");
      title.textContent = `${loc.name} — ${loc.description}`;
      g.appendChild(title);
      g.dataset.name = loc.name;
      g.dataset.description = loc.description || "";
      g.dataset.locId = String(loc.id);
    });

    state.tempLocations.forEach((loc) => {
      const g = document.createElementNS(SVG, "g");
      g.classList.add("map-location", "map-location-temp");
      g.setAttribute("aria-label", loc.name);
      g.setAttribute("transform", `translate(${loc.x}, ${loc.y})`);
      g.dataset.name = loc.name;
      g.dataset.description = loc.description || "Uncharted territory";
      g.dataset.temporary = "true";
      g.dataset.locId = String(loc.id);

      const ring = document.createElementNS(SVG, "circle");
      ring.setAttribute("cx", "0");
      ring.setAttribute("cy", "0");
      ring.setAttribute("r", "11");
      ring.classList.add("map-temp-ring");
      g.appendChild(ring);

      const core = document.createElementNS(SVG, "circle");
      core.setAttribute("cx", "0");
      core.setAttribute("cy", "0");
      core.setAttribute("r", "4");
      core.classList.add("map-temp-core");
      g.appendChild(core);

      const title = document.createElementNS(SVG, "title");
      title.textContent = loc.name;
      g.appendChild(title);

      mapLocationsEl.appendChild(g);
    });
  }

  function svgPointFromClient(clientX, clientY) {
    if (!mapSvg || typeof mapSvg.createSVGPoint !== "function") return null;
    const point = mapSvg.createSVGPoint();
    point.x = clientX;
    point.y = clientY;
    const ctm = mapSvg.getScreenCTM();
    if (!ctm) return null;
    const p = point.matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
  }

  function nearestLocation(x, y) {
    let best = null;
    let bestDist = Infinity;
    state.locations.forEach((loc) => {
      const dx = loc.x - x;
      const dy = loc.y - y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < bestDist) {
        bestDist = dist;
        best = loc;
      }
    });
    return { loc: best, dist: bestDist };
  }

  function pruneTempLocations() {
    const now = Date.now();
    state.tempLocations = state.tempLocations.filter((loc) => (now - loc.createdAt) < TEMP_LOCATION_TTL_MS);
    if (state.tempLocations.length > MAX_TEMP_LOCATIONS) {
      state.tempLocations = state.tempLocations.slice(state.tempLocations.length - MAX_TEMP_LOCATIONS);
    }
  }

  function addTempLocation(x, y) {
    const tempLoc = {
      id: `temp_${Math.random().toString(36).slice(2, 9)}`,
      key: "wild",
      name: "Unknown Area",
      description: "The path ahead is unwritten.",
      type: "wild",
      x,
      y,
      temporary: true,
      createdAt: Date.now(),
    };
    state.tempLocations.push(tempLoc);
    pruneTempLocations();
    renderMapLocations();
    renderMapRoutes();
    return tempLoc;
  }

  function drawTrail(fromX, fromY, toX, toY) {
    const path = document.createElementNS(SVG, "path");
    path.classList.add("map-travel-trail");
    path.setAttribute("d", `M ${fromX} ${fromY} Q ${(fromX + toX) / 2} ${(fromY + toY) / 2 - 14} ${toX} ${toY}`);
    mapPinsEl.appendChild(path);
    setTimeout(() => path.remove(), 1600);
  }

  function ensureExplorerToken() {
    if (state.explorerTokenEl) return state.explorerTokenEl;
    const token = document.createElementNS(SVG, "g");
    token.classList.add("map-explorer-token");

    const outer = document.createElementNS(SVG, "circle");
    outer.setAttribute("cx", "0");
    outer.setAttribute("cy", "0");
    outer.setAttribute("r", "12");
    outer.classList.add("map-explorer-glow");
    token.appendChild(outer);

    const disc = document.createElementNS(SVG, "circle");
    disc.setAttribute("cx", "0");
    disc.setAttribute("cy", "0");
    disc.setAttribute("r", "8");
    disc.classList.add("map-explorer-disc");
    token.appendChild(disc);

    mapPinsEl.appendChild(token);
    state.explorerTokenEl = token;
    return token;
  }

  function animateExplorerTo(x, y) {
    const me = state.characters.get(MY_CHAR_ID);
    const from = state.explorerPos || (me && me.map ? { x: me.map.x, y: me.map.y } : { x, y });
    state.explorerPos = { x: from.x, y: from.y };
    drawTrail(from.x, from.y, x, y);

    const token = ensureExplorerToken();
    const start = performance.now();
    const duration = 650;
    const ease = (t) => 1 - Math.pow(1 - t, 3);
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const e = ease(t);
      const nx = from.x + (x - from.x) * e;
      const ny = from.y + (y - from.y) * e;
      token.setAttribute("transform", `translate(${nx} ${ny})`);
      if (t < 1) {
        requestAnimationFrame(step);
      } else {
        state.explorerPos = { x, y };
      }
    };
    requestAnimationFrame(step);
  }

  function applyDestination(loc, snapped) {
    animateExplorerTo(loc.x, loc.y);
    if (snapped) {
      actionInput.value = `I travel to ${loc.name} and carefully observe the area.`;
    } else {
      actionInput.value = `I explore this unknown area carefully and report what I find.`;
    }
    actionInput.focus();
  }

  function renderPins() {
    const nextIds = new Set();
    // Jitter pins slightly if many chars are co-located, so they don't overlap.
    const byCoord = new Map();
    state.characters.forEach((c) => {
      if (!c.map) return;
      const key = `${Math.round(c.map.x)}:${Math.round(c.map.y)}`;
      const list = byCoord.get(key) || [];
      list.push(c);
      byCoord.set(key, list);
    });

    byCoord.forEach((chars) => {
      chars.forEach((c, i) => {
        nextIds.add(c.id);
        const angle = (i / Math.max(1, chars.length)) * Math.PI * 2;
        const jitter = chars.length > 1 ? 14 : 0;
        const px = c.map.x + Math.cos(angle) * jitter;
        const py = c.map.y + Math.sin(angle) * jitter;

        let g = state.mapPinEls.get(c.id);
        if (!g) {
          g = document.createElementNS(SVG, "g");
          g.classList.add("map-pin");
          if (window.innerWidth >= 1600) g.classList.add("map-pin-lg");
          g.setAttribute("data-char-id", String(c.id));

          const pin = document.createElementNS(SVG, "path");
          pin.classList.add("map-pin-shape");
          pin.setAttribute("d", "M 0 -22 C -9 -22 -11 -10 0 0 C 11 -10 9 -22 0 -22 Z");
          pin.setAttribute("fill", c.pin_color || "#e0b46a");
          pin.setAttribute("stroke", "#3d1f08");
          pin.setAttribute("stroke-width", "2");
          g.appendChild(pin);

          const glow = document.createElementNS(SVG, "circle");
          glow.classList.add("map-pin-glow");
          glow.setAttribute("cx", "0");
          glow.setAttribute("cy", "-14");
          glow.setAttribute("r", "8");
          g.appendChild(glow);

          const inner = document.createElementNS(SVG, "circle");
          inner.setAttribute("cx", "0");
          inner.setAttribute("cy", "-14");
          inner.setAttribute("r", "3.5");
          inner.setAttribute("fill", "#0a0908");
          g.appendChild(inner);

          const label = document.createElementNS(SVG, "text");
          label.classList.add("map-pin-label");
          label.setAttribute("x", "0");
          label.setAttribute("y", "16");
          label.setAttribute("text-anchor", "middle");
          label.textContent = c.name;
          g.appendChild(label);

          const title = document.createElementNS(SVG, "title");
          g.appendChild(title);
          state.mapPinEls.set(c.id, g);
          mapPinsEl.appendChild(g);
        }

        g.style.transition = "transform 280ms cubic-bezier(0.16,1,0.3,1)";
        g.setAttribute("transform", `translate(${px} ${py})`);
        g.querySelector(".map-pin-shape")?.setAttribute("fill", c.pin_color || "#e0b46a");
        g.querySelector(".map-pin-label").textContent = c.name;
        const title = g.querySelector("title");
        if (title) title.textContent = `${c.name} · HP ${c.hp}/${c.max_hp}`;
      });
    });

    state.mapPinEls.forEach((el, id) => {
      if (nextIds.has(id)) return;
      el.remove();
      state.mapPinEls.delete(id);
    });
  }

  // ------------------------------------------------------------------
  // Shop modal
  // ------------------------------------------------------------------
  const shopModal = $("#shop-modal");

  async function openShop(shopKey) {
    if (!shopModal) return;
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/shops/${encodeURIComponent(shopKey)}`);
    if (!res.ok) return;
    const shop = await res.json();
    state.activeShop = shop;
    renderShop();
    if (typeof shopModal.showModal === "function") shopModal.showModal();
  }

  function renderShop() {
    if (!state.activeShop) return;
    const shop = state.activeShop;
    $("#shop-title").textContent = shop.name;
    setText("shop-keeper", shop.shopkeeper);

    const me = state.characters.get(MY_CHAR_ID);
    setText("player-gold", me ? me.gold : "—");

    const list = $("#shop-items");
    list.innerHTML = "";
    shop.items.forEach((item) => {
      const canAfford = me && me.gold >= item.price;
      const inStock = item.stock > 0;
      const li = document.createElement("li");
      li.className = "shop-item";
      li.innerHTML = `
        <div>
          <div class="shop-item-name">${esc(item.name)}</div>
          <div class="shop-item-desc">${esc(item.description || "")}</div>
          <div class="shop-item-meta">
            <span class="shop-item-price">${esc(item.price)}g</span>
            · ${esc(item.kind)} · stock: ${esc(item.stock)}
          </div>
        </div>
        <button class="btn shop-buy-btn" ${(!canAfford || !inStock) ? "disabled" : ""} data-item-id="${esc(item.id)}">
          ${!inStock ? "Sold out" : !canAfford ? "Too costly" : "Buy"}
        </button>
      `;
      list.appendChild(li);
    });

    list.onclick = async (e) => {
      const btn = e.target.closest(".shop-buy-btn");
      if (!btn || btn.disabled) return;
      const itemId = parseInt(btn.dataset.itemId, 10);
      btn.disabled = true;
      btn.textContent = "Buying…";
      const res = await fetch(`/api/shops/${shop.id}/buy`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "Embervale" },
        body: JSON.stringify({ item_id: itemId }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) {
        btn.textContent = j.error || "Failed";
        setTimeout(() => (btn.textContent = "Buy"), 1500);
        btn.disabled = false;
        return;
      }
      // local optimistic update; state_update event will sync authoritatively
      if (j.character) {
        state.characters.set(j.character.id, j.character);
        renderParty();
      }
      if (state.activeShop) {
        const it = state.activeShop.items.find((i) => i.id === itemId);
        if (it) it.stock = j.new_stock;
      }
      renderShop();
    };
  }

  // Close handlers for any modal
  document.addEventListener("click", (e) => {
    if (e.target.matches("[data-close-modal]")) {
      const dlg = e.target.closest("dialog");
      if (dlg && typeof dlg.close === "function") dlg.close();
    }
  });

  // ------------------------------------------------------------------
  // Battle modal
  // ------------------------------------------------------------------
  const battleModal = $("#battle-modal");

  function renderBattle() {
    if (!state.battle) {
      if (battleModal && battleModal.open) battleModal.close();
      return;
    }
    if (battleModal && !battleModal.open && typeof battleModal.showModal === "function") {
      battleModal.showModal();
    }
    setText("battle-round", state.battle.round || 1);

    const allies = $("#battle-allies");
    const enemies = $("#battle-enemies");
    allies.innerHTML = "";
    enemies.innerHTML = "";

    state.battle.participants.forEach((p) => {
      const li = document.createElement("li");
      li.className = "battle-participant"
        + (p.id === state.battle.active_participant_id ? " active" : "")
        + (p.id === state.battleTargetId ? " targeted" : "")
        + (p.hp <= 0 ? " downed" : "");
      const pct = p.max_hp ? Math.max(0, Math.min(100, (p.hp / p.max_hp) * 100)) : 0;
      li.innerHTML = `
        <div class="bp-head">
          <span>${esc(p.name)}</span>
          <span class="bp-init">init ${esc(p.initiative)}</span>
        </div>
        <div class="hp-bar"><div class="hp-bar-fill ${pct < 30 ? "critical" : pct < 60 ? "low" : ""}" style="width:${pct}%"></div></div>
        <div class="hp-text"><span>HP</span><span>${esc(p.hp)}/${esc(p.max_hp)}</span></div>
      `;
      if (p.hp > 0 && p.is_enemy) {
        li.addEventListener("click", () => {
          state.battleTargetId = (state.battleTargetId === p.id) ? null : p.id;
          renderBattle();
        });
      }
      (p.is_enemy ? enemies : allies).appendChild(li);
    });

    const hint = $("#battle-target-hint");
    if (state.battleTargetId) {
      const t = state.battle.participants.find((x) => x.id === state.battleTargetId);
      hint.textContent = `Target: ${t ? t.name : "—"}`;
    } else {
      hint.textContent = "Click an enemy to target.";
    }
  }

  // Battle verb buttons pre-fill the action
  $$(".battle-btns [data-battle-verb]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = $("#battle-action-input");
      input.value = btn.dataset.battleVerb + (input.value ? " " + input.value : "");
      input.focus();
    });
  });

  $("#battle-submit").addEventListener("click", async () => {
    if (!state.battle) return;
    const input = $("#battle-action-input");
    const text = input.value.trim();
    if (!text) return;
    const body = { action: text };
    if (state.battleTargetId) body.target_id = state.battleTargetId;
    const submit = $("#battle-submit");
    submit.disabled = true;
    try {
      await fetch(`/api/battles/${state.battle.id}/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "Embervale" },
        body: JSON.stringify(body),
      });
      input.value = "";
      state.battleTargetId = null;
    } finally {
      submit.disabled = false;
    }
  });

  // ------------------------------------------------------------------
  // Web Speech: TTS output
  // ------------------------------------------------------------------
  const synth = window.speechSynthesis;
  let voice = null;
  function pickVoice() {
    if (!synth) return;
    const voices = synth.getVoices();
    // Prefer English voices that sound distinct. Fall back to default.
    voice =
      voices.find((v) => /Daniel|Google UK English Male|Microsoft Ryan/.test(v.name)) ||
      voices.find((v) => v.lang && v.lang.startsWith("en")) ||
      voices[0] || null;
  }
  if (synth) {
    pickVoice();
    synth.onvoiceschanged = pickVoice;
  }

  function speakChunk(text) {
    if (!state.ttsEnabled || !synth || !text.trim()) return;
    const u = new SpeechSynthesisUtterance(text);
    if (voice) u.voice = voice;
    u.rate = 0.98;
    u.pitch = 0.92;
    synth.speak(u);
  }

  function tryFlushTTS() {
    // Speak any complete sentence(s) added since last flush.
    const full = state.currentDmParagraph;
    const tail = full.slice(state.lastSpokenIdx);
    const lastEnd = Math.max(tail.lastIndexOf("."), tail.lastIndexOf("!"), tail.lastIndexOf("?"));
    if (lastEnd < 0) return;
    const chunk = tail.slice(0, lastEnd + 1);
    state.lastSpokenIdx += chunk.length;
    speakChunk(chunk);
  }

  const ttsBtn = $("#tts-toggle");
  ttsBtn.addEventListener("click", () => {
    state.ttsEnabled = !state.ttsEnabled;
    ttsBtn.setAttribute("aria-pressed", state.ttsEnabled ? "true" : "false");
    ttsBtn.title = state.ttsEnabled ? "DM voice: on" : "DM voice: off";
    ttsBtn.firstElementChild.textContent = state.ttsEnabled ? "🔊" : "🔇";
    if (!state.ttsEnabled && synth) synth.cancel();
  });

  // ------------------------------------------------------------------
  // Web Speech: STT input (mic)
  // ------------------------------------------------------------------
  const Recog = window.SpeechRecognition || window.webkitSpeechRecognition;
  const micBtn = $("#mic-btn");
  const micStatus = $("#mic-status");
  const actionInput = $("#action-input");

  if (!Recog) {
    micBtn.disabled = true;
    micBtn.title = "Voice not supported in this browser";
    micStatus.textContent = "Voice input isn't supported in this browser; use text.";
  } else {
    let recog = null;
    let listening = false;

    micBtn.addEventListener("click", () => {
      if (listening) {
        recog && recog.stop();
        return;
      }
      recog = new Recog();
      recog.continuous = false;
      recog.interimResults = true;
      recog.lang = "en-US";
      recog.onstart = () => {
        listening = true;
        micBtn.setAttribute("aria-pressed", "true");
        micStatus.textContent = "Listening…";
      };
      recog.onresult = (ev) => {
        let interim = "";
        let final = "";
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const res = ev.results[i];
          if (res.isFinal) final += res[0].transcript;
          else interim += res[0].transcript;
        }
        actionInput.value = (final + interim).trim();
      };
      recog.onerror = (ev) => {
        micStatus.textContent = "Mic error: " + ev.error;
      };
      recog.onend = () => {
        listening = false;
        micBtn.setAttribute("aria-pressed", "false");
        micStatus.textContent = "";
      };
      recog.start();
    });
  }

  // ------------------------------------------------------------------
  // Socket wiring
  // ------------------------------------------------------------------
  const socket = io({ transports: ["websocket", "polling"] });
  const dmStatus = $("#dm-status");

  socket.on("connect", () => {
    dmStatus.textContent = "Connected.";
    if (state.reconnectEntry) {
      state.reconnectEntry.remove();
      state.reconnectEntry = null;
    }
    socket.emit("join_campaign", { campaign_id: CAMPAIGN_ID });
  });
  socket.on("disconnect", () => {
    dmStatus.textContent = "Reconnecting…";
    if (!state.reconnectEntry) {
      state.reconnectEntry = appendLog("<p><em>Reconnecting...</em></p>", "entry-scene");
    }
  });
  socket.on("auth_error", () => { window.location.href = "/auth/login"; });

  socket.on("joined_campaign", () => {
    hydrateState();
  });

  socket.on("character_joined", (data) => {
    state.characters.set(data.character.id, data.character);
    renderParty();
    renderPins();
    appendLog(`<p class="log-author">—</p><p><em>${esc(data.character.name)} joins the party.</em></p>`, "entry-scene");
  });

  socket.on("presence_update", (d) => {
    const c = state.characters.get(d.character_id);
    if (c) { c.is_online = d.is_online; renderParty(); }
  });

  socket.on("turn_started", (d) => {
    state.currentDmParagraph = "";
    state.lastSpokenIdx = 0;
    appendLog(
      `<span class="log-author">${esc(d.character_name)}</span><p>${esc(d.action)}</p>`,
      "entry-player"
    );
    state._dmEntryEl = appendLog(`<p class="dm-text"></p>`, "entry-dm");
    dmStatus.textContent = "The DM considers…";
  });

  socket.on("narration_delta", (d) => {
    if (!state._dmEntryEl) state._dmEntryEl = appendLog(`<p class="dm-text"></p>`, "entry-dm");
    state.currentDmParagraph += d.text;
    const p = state._dmEntryEl.querySelector(".dm-text");
    p.textContent = state.currentDmParagraph;
    logEl.scrollTo({ top: logEl.scrollHeight, behavior: "smooth" });
    tryFlushTTS();
  });

  socket.on("mutation", (mut) => {
    const html = mut.name === "roll_dice" ? rollDiceMarkup(mut) : mutationLabel(mut);
    appendLog(html, "entry-mutation");
    // open_shop mutation opens modal
    if (mut.name === "open_shop" && mut.result && mut.result.shop_key) {
      openShop(mut.result.shop_key);
    }
  });

  socket.on("dm_error", (d) => {
    appendLog(`<p>${esc(d.message)}</p>`, "entry-error");
  });

  socket.on("state_update", (s) => {
    state.mode = s.mode;
    state.scene = s.scene;
    state.turnIndex = s.turn_index;
    setText("mode", s.mode);
    setText("turn-counter", `turn ${s.turn_index}`);
    state.characters = new Map(s.characters.map((c) => [c.id, c]));
    state.battle = s.battle || null;
    renderParty();
    renderPins();
    renderBattle();
    if (profileModal && profileModal.open) {
      renderProfile(state.activeProfileCharacterId || MY_CHAR_ID);
    }
    // Speak any trailing portion of the DM paragraph not yet spoken.
    tryFlushTTS();
    state._dmEntryEl = null;  // next turn gets a fresh entry
  });

  socket.on("turn_complete", (d) => {
    dmStatus.textContent = `Turn ${d.turn_index} · ${d.latency_ms}ms${d.cache_hit ? " · cached" : ""}`;
    if (state.actingEntry) {
      state.actingEntry.classList.add("is-fading");
      setTimeout(() => state.actingEntry && state.actingEntry.remove(), 350);
      state.actingEntry = null;
    }
    refreshMetrics();
  });

  socket.on("action_accepted", (d) => {
    if (d && d.queued_at_turn) {
      dmStatus.textContent = `Queued for turn ${d.queued_at_turn}`;
    }
  });

  socket.on("player_acting", (d) => {
    const entry = appendLog(`<p><em>${esc(d.character_name)} is acting...</em></p>`, "entry-scene");
    if (state.actingEntry) {
      state.actingEntry.remove();
    }
    state.actingEntry = entry;
  });

  socket.on("shop_update", (d) => {
    if (state.activeShop && state.activeShop.id === d.shop_id) {
      const it = state.activeShop.items.find((i) => i.id === d.item_id);
      if (it) it.stock = d.new_stock;
      renderShop();
    }
    if (d.buyer) {
      state.characters.set(d.buyer.id, d.buyer);
      renderParty();
    }
  });

  // ------------------------------------------------------------------
  // Hydrate initial state
  // ------------------------------------------------------------------
  async function hydrateState() {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/state`);
    if (!res.ok) return;
    const s = await res.json();
    state.mode = s.campaign.mode;
    state.scene = s.campaign.scene;
    state.turnIndex = s.campaign.turn_index;
    setText("mode", s.campaign.mode);
    setText("turn-counter", `turn ${s.campaign.turn_index}`);
    setText("scene-hint", s.campaign.name);

    state.locations = new Map(s.locations.map((l) => [l.id, l]));
    state.locationsByKey = new Map(s.locations.map((l) => [l.key, l]));
    state.characters = new Map(s.characters.map((c) => [c.id, c]));
    state.battle = s.battle || null;

    renderMapLocations();
    renderMapRoutes();
    renderPins();
    renderParty();
    renderBattle();
  }

  function applyMapZoom() {
    if (!mapZoomGroup) return;
    mapZoomGroup.style.transformOrigin = "center center";
    mapZoomGroup.style.transform = `scale(${state.mapZoom})`;
  }

  // ------------------------------------------------------------------
  // Submit action
  // ------------------------------------------------------------------
  const sendBtn = $("#send-btn");
  function submitAction() {
    const text = actionInput.value.trim();
    if (!text) return;
    if (!state.actionHistory.length || state.actionHistory[state.actionHistory.length - 1] !== text) {
      state.actionHistory.push(text);
      if (state.actionHistory.length > 20) {
        state.actionHistory.shift();
      }
    }
    socket.emit("submit_action", { campaign_id: CAMPAIGN_ID, action: text });
    actionInput.value = "";
    actionInput.focus();
  }
  sendBtn.addEventListener("click", submitAction);
  actionInput.addEventListener("keydown", (e) => {
    if (e.key === "ArrowUp" && !e.shiftKey && !e.ctrlKey && !e.altKey && actionInput.value === "") {
      const last = state.actionHistory[state.actionHistory.length - 1];
      if (last) {
        e.preventDefault();
        actionInput.value = last;
      }
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitAction();
    }
  });

  const centerBtn = $("#map-center-btn");
  const zoomInBtn = $("#map-zoom-in-btn");
  const zoomOutBtn = $("#map-zoom-out-btn");
  const ZOOM_STEP = 0.25;
  const ZOOM_MIN = 0.75;
  const ZOOM_MAX = 3.0;
  if (centerBtn && zoomInBtn && zoomOutBtn) {
    centerBtn.addEventListener("click", () => {
      state.mapZoom = 1;
      applyMapZoom();
    });
    zoomInBtn.addEventListener("click", () => {
      state.mapZoom = Math.min(ZOOM_MAX, +(state.mapZoom + ZOOM_STEP).toFixed(2));
      applyMapZoom();
    });
    zoomOutBtn.addEventListener("click", () => {
      state.mapZoom = Math.max(ZOOM_MIN, +(state.mapZoom - ZOOM_STEP).toFixed(2));
      applyMapZoom();
    });
  }

  const mapExpandBtn = $("#expand-btn");
  const mapPanel = $(".panel-map");
  if (mapExpandBtn && mapPanel) {
    const closeExpanded = () => {
      mapPanel.classList.remove("map-expanded");
      mapExpandBtn.textContent = "⛶";
      mapExpandBtn.title = "Expand map";
    };
    mapExpandBtn.addEventListener("click", () => {
      const nowExpanded = !mapPanel.classList.contains("map-expanded");
      mapPanel.classList.toggle("map-expanded", nowExpanded);
      mapExpandBtn.textContent = nowExpanded ? "✕" : "⛶";
      mapExpandBtn.title = nowExpanded ? "Close expanded map" : "Expand map";
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeExpanded();
    });
    mapPanel.addEventListener("click", (e) => {
      if (mapPanel.classList.contains("map-expanded") && e.target === mapPanel) closeExpanded();
    });
  }

  const partyToggleBtn = $("#party-toggle");
  if (partyToggleBtn) {
    partyToggleBtn.addEventListener("click", () => {
      document.body.classList.toggle("party-open");
    });
  }
  const partyCollapseBtn = $("#party-collapse-btn");
  if (partyCollapseBtn) {
    partyCollapseBtn.addEventListener("click", () => {
      document.body.classList.toggle("party-collapsed");
      const collapsed = document.body.classList.contains("party-collapsed");
      partyCollapseBtn.textContent = collapsed ? "⟩" : "⟨";
      partyCollapseBtn.title = collapsed ? "Expand party rail" : "Collapse party rail";
    });
  }

  $$(".quick-action-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      actionInput.value = btn.dataset.quickAction || "";
      actionInput.focus();
    });
  });

  const mapTooltip = $("#map-tooltip");
  if (mapTooltip && mapLocationsEl) {
    mapLocationsEl.addEventListener("pointermove", (e) => {
      const locationNode = e.target.closest(".map-location");
      if (!locationNode) {
        mapTooltip.hidden = true;
        return;
      }
      mapTooltip.hidden = false;
      mapTooltip.textContent = `${locationNode.dataset.name || "Location"}${locationNode.dataset.description ? " - " + locationNode.dataset.description : ""}`;
      mapTooltip.style.left = `${e.clientX + 12}px`;
      mapTooltip.style.top = `${e.clientY + 12}px`;
    });
    mapLocationsEl.addEventListener("pointerleave", () => {
      mapTooltip.hidden = true;
    });
    mapLocationsEl.addEventListener("click", (e) => {
      const locationNode = e.target.closest(".map-location");
      if (!locationNode) return;
      const isTemp = locationNode.dataset.temporary === "true";
      const locId = locationNode.dataset.locId || "";
      const tempLoc = state.tempLocations.find((loc) => String(loc.id) === locId && isTemp);
      const staticLoc = state.locations.get(parseInt(locId, 10));
      const loc = tempLoc || staticLoc;
      if (!loc) return;
      applyDestination(loc, !isTemp);
    });
  }

  const exploreModeBtn = $("#explore-mode-btn");
  if (exploreModeBtn) {
    const syncExploreBtn = () => {
      exploreModeBtn.setAttribute("aria-pressed", state.exploreMode ? "true" : "false");
      exploreModeBtn.title = state.exploreMode ? "Explore mode: on" : "Explore mode: off";
      mapPanel.classList.toggle("is-explore-mode", state.exploreMode);
    };
    exploreModeBtn.addEventListener("click", () => {
      state.exploreMode = !state.exploreMode;
      syncExploreBtn();
    });
    syncExploreBtn();
  }

  if (mapSvg) {
    mapSvg.addEventListener("click", (e) => {
      if (!state.exploreMode) return;
      if (e.target.closest(".map-location")) return;
      const p = svgPointFromClient(e.clientX, e.clientY);
      if (!p) return;
      const near = nearestLocation(p.x, p.y);
      if (near.loc && near.dist <= NODE_SNAP_DISTANCE) {
        applyDestination(near.loc, true);
        return;
      }
      const temp = addTempLocation(p.x, p.y);
      applyDestination(temp, false);
    });
  }

  setInterval(() => {
    const before = state.tempLocations.length;
    pruneTempLocations();
    if (state.tempLocations.length !== before) {
      renderMapLocations();
    }
  }, 15000);

  if (IS_OWNER) {
    const shareBtn = $("#share-code-btn");
    const shareModal = $("#share-code-modal");
    const copyBtn = $("#copy-share-code-btn");
    if (shareBtn && shareModal) {
      shareBtn.addEventListener("click", () => {
        if (typeof shareModal.showModal === "function") shareModal.showModal();
      });
    }
    if (copyBtn) {
      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(JOIN_CODE);
          copyBtn.textContent = "Copied";
          setTimeout(() => (copyBtn.textContent = "Copy"), 1200);
        } catch (_e) {
          copyBtn.textContent = "Copy failed";
          setTimeout(() => (copyBtn.textContent = "Copy"), 1200);
        }
      });
    }
  }

  const profileModal = $("#profile-modal");
  function mod(score) { return Math.floor((score - 10) / 2); }
  function modStr(score) { const m = mod(score); return (m >= 0 ? "+" : "") + m; }
  function statSegments(score) { return Math.min(5, Math.floor(score / 4)); }
  function renderProfile(characterId) {
    const char = state.characters.get(characterId || MY_CHAR_ID);
    if (!char || !profileModal) return;
    $("#profile-title").textContent = char.name;
    const charClass = char["class"] || char.char_class || "";
    $("#profile-subtitle").textContent = `${char.race} ${charClass} · Level ${char.level}`;
    const stats = char.stats || {};
    const rows = [["STR", stats.str], ["DEX", stats.dex], ["CON", stats.con], ["INT", stats.int], ["WIS", stats.wis], ["CHA", stats.cha]];
    $("#tab-stats").innerHTML = rows.map(([k, v]) => `<div class="profile-stat-row"><span>${k}</span><strong>${v}</strong><span>${modStr(v)}</span><div class="stat-bar">${Array.from({ length: 5 }).map((_, i) => `<span class="stat-seg ${i < statSegments(v) ? "filled" : ""}"></span>`).join("")}</div></div>`).join("") + `<div class="profile-meta">HP ${char.hp}/${char.max_hp} · AC ${char.ac} · Gold ${char.gold} · Level ${char.level} · XP 0</div>`;
    const inv = Array.isArray(char.inventory?.items) ? char.inventory.items : (Array.isArray(char.inventory) ? char.inventory : []);
    $("#tab-inventory").innerHTML = inv.length ? inv.map((i) => `<div class="profile-item-row"><span>${esc(i.name)}</span><span>x${esc(i.qty)}</span></div>`).join("") : "<p>Your pack is empty.</p>";
    const dex = stats.dex || 10;
    const wis = stats.wis || 10;
    const str = stats.str || 10;
    $("#tab-skills").innerHTML = `
      <div class="profile-item-row"><span>Attack Bonus</span><span>${modStr(dex)}</span></div>
      <div class="profile-item-row"><span>Save DC</span><span>${8 + 2 + mod(wis)}</span></div>
      <div class="profile-item-row"><span>Initiative</span><span>${modStr(dex)}</span></div>
      <div class="profile-item-row"><span>Passive Perception</span><span>${10 + mod(wis)}</span></div>
      <div class="profile-item-row"><span>Carrying Capacity</span><span>${str * 15}</span></div>
      <p>Special abilities will appear here as you level up.</p>
    `;
  }
  partyEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".profile-open-btn");
    if (btn && profileModal && typeof profileModal.showModal === "function") {
      const characterId = parseInt(btn.dataset.characterId, 10);
      state.activeProfileCharacterId = characterId;
      renderProfile(characterId);
      profileModal.showModal();
    }
  });
  const tabButtons = $$(".modal-tabs [role='tab']");
  tabButtons.forEach((btn, idx) => {
    btn.addEventListener("click", () => {
      tabButtons.forEach((b) => b.setAttribute("aria-selected", b === btn ? "true" : "false"));
      ["stats", "inventory", "skills"].forEach((name) => {
        const panel = $(`#tab-${name}`);
        if (panel) panel.hidden = name !== btn.dataset.tab;
      });
    });
    btn.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const n = (idx + (e.key === "ArrowRight" ? 1 : -1) + tabButtons.length) % tabButtons.length;
      tabButtons[n].focus();
      tabButtons[n].click();
    });
  });

  // ------------------------------------------------------------------
  // Metrics
  // ------------------------------------------------------------------
  const metricsToggle = $("#metrics-toggle");
  const metricsPanel = $("#metrics-panel");
  let metricsInterval = null;

  metricsToggle.addEventListener("click", () => {
    metricsPanel.hidden = !metricsPanel.hidden;
    if (!metricsPanel.hidden) {
      refreshMetrics();
      metricsInterval = setInterval(refreshMetrics, 5000);
    } else if (metricsInterval) {
      clearInterval(metricsInterval);
      metricsInterval = null;
    }
  });

  async function refreshMetrics() {
    if (metricsPanel.hidden) return;
    try {
      const r = await fetch("/api/metrics");
      if (!r.ok) return;
      const m = await r.json();
      setText("metric-hitrate", `${(m.cache.hit_rate * 100).toFixed(1)}% · ${m.cache.backend}`);
      setText("metric-latency", `${m.turns.avg_latency_ms}ms`);
      setText("metric-p95", `${m.turns.p95_latency_ms}ms`);
      setText("metric-tokens", `${m.turns.tokens_in_sum} / ${m.turns.tokens_out_sum}`);
    } catch (e) { /* silent */ }
  }
})();
