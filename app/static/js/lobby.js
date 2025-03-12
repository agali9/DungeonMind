(function () {
  const form = document.getElementById("create-char-form");
  const joinForm = document.getElementById("join-campaign-form");
  const newCampaignForm = document.getElementById("new-campaign-form");
  if (!form && !joinForm && !newCampaignForm) return;

  let campaignId = form ? form.dataset.campaignId : null;
  const errorEl = document.getElementById("create-error");
  const selectedEl = document.getElementById("selected-campaign-id");
  const copyFeedback = document.getElementById("copy-feedback");

  document.querySelectorAll(".campaign-select-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      campaignId = btn.dataset.campaignId;
      if (form) form.dataset.campaignId = campaignId;
      if (selectedEl) selectedEl.textContent = campaignId;
      document.getElementById("create-char-form")?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });

  document.querySelectorAll(".copy-code-btn, .copy-code-icon").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(btn.dataset.joinCode || "");
        if (copyFeedback) copyFeedback.textContent = `Copied invite code ${btn.dataset.joinCode}`;
        btn.dataset.copied = "true";
        setTimeout(() => { btn.dataset.copied = "false"; }, 1200);
      } catch (_e) {
        if (copyFeedback) copyFeedback.textContent = "Could not copy code.";
      }
    });
  });

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      errorEl.hidden = true;

      const data = new FormData(form);
      const payload = {
        name: data.get("name"),
        race: data.get("race"),
        class: data.get("class"),
      };

      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      btn.textContent = "Forging…";

      try {
        const res = await fetch(`/api/campaigns/${campaignId}/characters`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Requested-With": "Embervale" },
          body: JSON.stringify(payload),
          credentials: "same-origin",
        });
        if (!res.ok) {
          const j = await res.json().catch(() => ({ error: "unknown error" }));
          errorEl.textContent = j.error || "Could not create character.";
          errorEl.hidden = false;
          btn.disabled = false;
          btn.textContent = "Enter Embervale";
          return;
        }
        window.location.href = `/play/${campaignId}`;
      } catch (err) {
        errorEl.textContent = "Network error.";
        errorEl.hidden = false;
        btn.disabled = false;
        btn.textContent = "Enter Embervale";
      }
    });
  }

  if (joinForm) {
    const joinError = document.getElementById("join-error");
    joinForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      joinError.hidden = true;
      const fd = new FormData(joinForm);
      const code = (fd.get("code") || "").toString().trim().toUpperCase();
      const res = await fetch("/api/campaigns/join", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "Embervale" },
        body: JSON.stringify({ code }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        joinError.textContent = body.error || "Join failed";
        joinError.hidden = false;
        return;
      }
      if (body.has_character) {
        window.location.href = `/play/${body.campaign.id}`;
        return;
      }
      campaignId = String(body.campaign.id);
      if (form) form.dataset.campaignId = campaignId;
      if (selectedEl) selectedEl.textContent = campaignId;
      document.getElementById("create-char-form")?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  if (newCampaignForm) {
    const newErr = document.getElementById("new-campaign-error");
    newCampaignForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      newErr.hidden = true;
      const fd = new FormData(newCampaignForm);
      const name = (fd.get("name") || "").toString().trim();
      const res = await fetch("/api/campaigns", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "Embervale" },
        body: JSON.stringify({ name }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        newErr.textContent = body.error || "Could not create campaign.";
        newErr.hidden = false;
        return;
      }
      campaignId = String(body.campaign.id);
      if (form) form.dataset.campaignId = campaignId;
      if (selectedEl) selectedEl.textContent = campaignId;
      if (copyFeedback) copyFeedback.textContent = `Created campaign. Invite code: ${body.campaign.join_code}`;
      document.getElementById("create-char-form")?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }
})();
