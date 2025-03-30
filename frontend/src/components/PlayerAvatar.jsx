import { PORTRAIT_BY_PLAYER_ID } from "../data/portraits";

export default function PlayerAvatar({ player, sizeClass = "h-12 w-12", className = "" }) {
  const src = player?.portraitUrl || PORTRAIT_BY_PLAYER_ID[player?.id];

  return (
    <div
      className={`relative shrink-0 overflow-hidden rounded-full border border-[#c9a84c] bg-[#1a1308] ${sizeClass} ${className}`}
      title={player?.name}
    >
      {src ? (
        <img alt="" className="h-full w-full object-cover" src={src} />
      ) : (
        <div className="grid h-full w-full place-items-center bg-[#2a2010] text-sm text-[#d4c4a0]">
          {(player?.name || "?").charAt(0)}
        </div>
      )}
    </div>
  );
}
