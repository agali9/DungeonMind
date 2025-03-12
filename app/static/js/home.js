(function () {
  const root = document.getElementById("home-root");
  if (!root) return;

  const menu = document.querySelector(".scroll-body");
  const resumePanel = document.getElementById("resume-panel");
  const howPanel = document.getElementById("howtoplay-panel");
  const newModal = document.getElementById("new-game-dialog");
  const newBtn = document.getElementById("btn-new-game");
  const resumeBtn = document.getElementById("btn-resume");
  const howBtn = document.getElementById("btn-how-to-play");
  const joinForm = document.getElementById("join-campaign-form");
  const newForm = document.getElementById("new-campaign-form");
  const newErr = document.getElementById("new-campaign-error");
  const joinErr = document.getElementById("join-error");

  function showMenu() {
    resumePanel.hidden = true;
    howPanel.hidden = true;
  }
  function showResume() {
    resumePanel.hidden = false;
    howPanel.hidden = true;
  }
  function showHow() {
    resumePanel.hidden = true;
    howPanel.hidden = false;
  }

  newBtn?.addEventListener("click", () => {
    if (typeof newModal?.showModal === "function") newModal.showModal();
  });
  resumeBtn?.addEventListener("click", showResume);
  howBtn?.addEventListener("click", showHow);
  document.querySelectorAll("[data-back-menu]").forEach((b) => b.addEventListener("click", showMenu));

  document.addEventListener("click", (e) => {
    if (e.target.matches("[data-close-modal]")) {
      const dlg = e.target.closest("dialog");
      if (dlg && typeof dlg.close === "function") dlg.close();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && newModal?.open) newModal.close();
  });

  newForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (newErr) newErr.hidden = true;
    const fd = new FormData(newForm);
    const name = (fd.get("name") || "").toString().trim();
    const res = await fetch("/api/campaigns", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "Embervale" },
      body: JSON.stringify({ name }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (newErr) {
        newErr.textContent = body.error || "Could not create campaign.";
        newErr.hidden = false;
      }
      return;
    }
    window.location.href = `/campaigns/${body.campaign.id}/character/new`;
  });

  joinForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (joinErr) joinErr.hidden = true;
    const fd = new FormData(joinForm);
    const code = (fd.get("code") || "").toString().trim().toUpperCase();
    const res = await fetch("/api/campaigns/join", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "Embervale" },
      body: JSON.stringify({ code }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (joinErr) {
        joinErr.textContent = body.error || "Join failed";
        joinErr.hidden = false;
      }
      return;
    }
    if (body.has_character) window.location.href = `/play/${body.campaign.id}`;
    else window.location.href = `/campaigns/${body.campaign.id}/character/new`;
  });
})();
