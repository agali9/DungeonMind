const BASE = "";

async function apiFetch(path, options = {}) {
  const response = await fetch(BASE + path, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-Requested-With": "Embervale",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (response.status === 401) {
    window.location.href = "/auth/login";
    return null;
  }

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(errorBody.error || response.statusText);
  }

  return response.json();
}

export const api = {
  me: () => apiFetch("/api/me"),
  listCampaigns: () => apiFetch("/api/campaigns"),
  createCampaign: (name) =>
    apiFetch("/api/campaigns", { method: "POST", body: JSON.stringify({ name }) }),
  joinCampaign: (code) =>
    apiFetch("/api/campaigns/join", { method: "POST", body: JSON.stringify({ code }) }),
  createCharacter: (campaignId, data) =>
    apiFetch(`/api/campaigns/${campaignId}/characters`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getState: (campaignId) => apiFetch(`/api/campaigns/${campaignId}/state`),
  getShop: (campaignId, shopKey) => apiFetch(`/api/campaigns/${campaignId}/shops/${shopKey}`),
  buyItem: (shopId, itemId) =>
    apiFetch(`/api/shops/${shopId}/buy`, {
      method: "POST",
      body: JSON.stringify({ item_id: itemId }),
    }),
  battleAction: (battleId, action, targetId) =>
    apiFetch(`/api/battles/${battleId}/action`, {
      method: "POST",
      body: JSON.stringify({ action, target_id: targetId }),
    }),
  metrics: () => apiFetch("/api/metrics"),
  transcript: (campaignId) => apiFetch(`/api/campaigns/${campaignId}/transcript.md`),
};
