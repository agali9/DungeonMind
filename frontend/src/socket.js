import { io } from "socket.io-client";

export const socket = io({
  transports: ["websocket", "polling"],
  autoConnect: false,
  withCredentials: true,
});

export function joinCampaignRoom(campaignId) {
  socket.emit("join_campaign", { campaign_id: campaignId });
}

export function submitAction(campaignId, action) {
  socket.emit("submit_action", { campaign_id: campaignId, action });
}

export function sendTyping(campaignId, isTyping) {
  socket.emit("typing", { campaign_id: campaignId, is_typing: isTyping });
}

export function leaveCampaignRoom(campaignId) {
  socket.emit("leave_campaign", { campaign_id: campaignId });
}
