function IconShop() {
  return (
    <svg viewBox="0 0 32 32" className="h-[28px] w-[28px]" fill="none" stroke="#a08040" strokeWidth="1.2">
      <path d="M6 10h20l-1 14H7L6 10z" fill="#1e1610" strokeLinejoin="round" />
      <path d="M9 10V8a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v2" />
      <path d="M6 14h20" opacity="0.5" />
    </svg>
  );
}

function IconBattle() {
  return (
    <svg viewBox="0 0 32 32" className="h-[28px] w-[28px]" fill="none" stroke="#a08040" strokeWidth="1.2">
      <path d="M8 26 14 6l4 4 4-4 6 20" strokeLinejoin="round" fill="#1e1610" />
      <path d="m10 22 4-4M18 18l4 4" />
    </svg>
  );
}

function IconMap() {
  return (
    <svg viewBox="0 0 32 32" className="h-[28px] w-[28px]" fill="none" stroke="#a08040" strokeWidth="1.2">
      <path d="M4 24V8l6-2 8 2 8-2v16l-6 2-8-2-6 2z" fill="#1e1610" strokeLinejoin="round" />
      <path d="M10 6v16M18 10v14" opacity="0.6" />
    </svg>
  );
}

function IconVoice() {
  return (
    <svg viewBox="0 0 32 32" className="h-[28px] w-[28px]" fill="none" stroke="#a08040" strokeWidth="1.2">
      <path d="M12 10v12M8 14h8v4H8z" fill="#1e1610" />
      <path d="M20 12c2 2 2 8 0 10M23 9c3 4 3 12 0 16" />
    </svg>
  );
}

const dockActions = [
  { id: "shop", icon: IconShop, label: "Shop" },
  { id: "battle", icon: IconBattle, label: "Battle" },
  { id: "map", icon: IconMap, label: "Map" },
  { id: "voice", icon: IconVoice, label: "Voice" },
];

export default function ActionDock() {
  return (
    <div className="border-t border-[#2a1e0e] px-2 py-4">
      <div className="flex items-start justify-between gap-2">
        {dockActions.map(({ id, icon: Icon, label }) => (
          <button key={id} className="flex flex-1 flex-col items-center gap-1.5 text-[#7a6a4a] transition hover:text-[#9a8a6a]" type="button">
            <span className="flex h-[28px] w-[28px] items-center justify-center text-[#c9a84c]">
              <Icon />
            </span>
            <span className="font-serif text-[10px] uppercase tracking-[0.14em]" style={{ fontVariant: "small-caps" }}>
              {label}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
