import PlayerAvatar from "./PlayerAvatar";

function PartyCard({ player }) {
  const hpPct = Math.max(0, Math.min(100, (player.hp / player.maxHp) * 100));
  return (
    <article className="rounded-lg bg-transparent px-1 py-2">
      <div className="mb-2 flex items-start gap-3">
        <div className="relative shrink-0">
          <PlayerAvatar player={player} sizeClass="h-12 w-12" />
          <span
            className={`absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border border-[#12100a] ${player.online ? "bg-[#4ade80]" : "bg-[#4a3a28]"}`}
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <p className="truncate overflow-hidden whitespace-nowrap font-serif text-[14px] font-medium leading-tight text-[#d4c4a0]">{player.name}</p>
            <p className="shrink-0 pt-0.5 text-right font-serif text-[12px] text-[#6b5a3a]">
              {player.hp}/{player.maxHp}
            </p>
          </div>
          <p className="mt-0.5 font-serif text-[12px] leading-snug text-[#7a6a4a]">
            {player.race} {player.className} · Level {player.level}
          </p>
        </div>
      </div>
      <div className="h-[3px] w-full overflow-hidden rounded-full bg-[#2a2014]">
        <div className="h-full rounded-full bg-[#4ade80] transition-all duration-500" style={{ width: `${hpPct}%` }} />
      </div>
    </article>
  );
}

export default function PartyPanel({ players }) {
  return (
    <section className="h-full min-h-0 overflow-y-auto rounded-2xl bg-[#12100a]">
      <header className="flex items-center border-b border-[#2a1e0e] px-4 py-2.5">
        <h2 className="text-[13px] font-normal uppercase tracking-[0.15em] text-[#a08040]">Party</h2>
      </header>
      <div className="space-y-1 px-2.5 py-2">
        {players.map((player) => (
          <PartyCard key={player.id} player={player} />
        ))}
      </div>
    </section>
  );
}
