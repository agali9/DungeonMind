(function () {
  const form = document.getElementById("create-char-form");
  if (!form) return;

  const campaignId = form.dataset.campaignId;
  const errorEl = document.getElementById("create-error");
  const rollBtn = document.getElementById("roll-stats-btn");
  const rollCounter = document.getElementById("roll-counter");
  const statsEl = document.getElementById("rolled-stats");
  const statKeys = ["str", "dex", "con", "int", "wis", "cha"];
  const MAX_ROLLS = parseInt(form.dataset.maxRolls || "3", 10);
  let rollsUsed = 0;
  let rolled = null;

  function roll4d6DropLowest() {
    const rolls = [1, 2, 3, 4].map(() => 1 + Math.floor(Math.random() * 6)).sort((a, b) => a - b);
    return rolls[1] + rolls[2] + rolls[3];
  }

  function renderStats() {
    if (!rolled) {
      statsEl.textContent = "No roll yet.";
      return;
    }
    statsEl.textContent = `STR ${rolled.str} · DEX ${rolled.dex} · CON ${rolled.con} · INT ${rolled.int} · WIS ${rolled.wis} · CHA ${rolled.cha}`;
  }

  function updateRollCounter() {
    const remaining = Math.max(0, MAX_ROLLS - rollsUsed);
    if (rollCounter) {
      rollCounter.textContent = `Rolls remaining: ${remaining}`;
    }
    if (rollBtn) {
      rollBtn.disabled = rollsUsed >= MAX_ROLLS;
    }
  }

  rollBtn?.addEventListener("click", () => {
    if (rollsUsed >= MAX_ROLLS) return;
    rolled = {};
    statKeys.forEach((k) => {
      rolled[k] = roll4d6DropLowest();
    });
    rollsUsed += 1;
    renderStats();
    updateRollCounter();
  });
  updateRollCounter();

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.hidden = true;
    const fd = new FormData(form);
    const payload = {
      name: fd.get("name"),
      race: fd.get("race"),
      class: fd.get("class"),
      rolled_stats: rolled,
    };
    const res = await fetch(`/api/campaigns/${campaignId}/characters`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "Embervale" },
      body: JSON.stringify(payload),
      credentials: "same-origin",
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      errorEl.textContent = body.error || "Could not create character.";
      errorEl.hidden = false;
      return;
    }
    window.location.href = `/play/${campaignId}`;
  });
})();
