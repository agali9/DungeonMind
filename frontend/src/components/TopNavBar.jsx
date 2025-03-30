function NavIcon({ children, label, onClick }) {
  return (
    <button
      className="grid h-9 w-9 place-items-center text-[#6b5a3a] transition hover:text-[#a09070]"
      onClick={onClick}
      title={label}
      type="button"
    >
      <span className="h-5 w-5 [&>svg]:h-full [&>svg]:w-full">{children}</span>
    </button>
  );
}

export default function TopNavBar({
  campaignTitle,
  locationLabel,
  ttsEnabled,
  onToggleTts,
  onOpenHelp,
  onExit,
}) {
  return (
    <header
      className="flex items-center justify-between rounded-2xl px-4 py-2.5"
      style={{ backgroundColor: "#0d0900", borderBottom: "1px solid #2a1e0e" }}
    >
      <div className="min-w-0">
        <p className="truncate font-serif text-[14px] leading-snug">
          <span className="uppercase tracking-[0.12em] text-[#c9a84c]" style={{ fontVariant: "small-caps" }}>
            {campaignTitle}
          </span>
          <span className="mx-2 text-[#6b5a3a]">›</span>
          <span className="font-normal tracking-normal text-[#d4c4a0]">{locationLabel}</span>
        </p>
      </div>
      <div className="ml-3 flex items-center gap-1 sm:gap-2">
        <NavIcon label={ttsEnabled ? "Mute narrator" : "Enable narrator"} onClick={onToggleTts}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
            <path d="M11 5 6 9H3v6h3l5 4V5z" />
            {ttsEnabled ? <path d="M16 9a5 5 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11" /> : <path d="m16 8 4 8M20 8l-4 8" />}
          </svg>
        </NavIcon>
        <NavIcon label="Help" onClick={onOpenHelp}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
            <circle cx="12" cy="12" r="9" />
            <path d="M9 9a3 3 0 1 1 4 2.8c0 1-.8 1.5-1.3 2" strokeLinecap="round" />
            <circle cx="12" cy="17" r="0.5" fill="currentColor" />
          </svg>
        </NavIcon>
        <NavIcon label="Exit to Lobby" onClick={onExit}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
            <path d="M14 4h5v16h-5" />
            <path d="M10 12h9" />
            <path d="m7 9 3 3-3 3" />
          </svg>
        </NavIcon>
      </div>
    </header>
  );
}
