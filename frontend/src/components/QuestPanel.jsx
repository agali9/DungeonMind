function IconCompassMini({ className }) {
  return (
    <svg aria-hidden className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="12" cy="12" r="8" />
      <path d="M12 4v2M12 18v2M4 12h2M18 12h2" />
      <path d="m13.5 10-3 4-1.5-2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function QuestPanel({ quest }) {
  return (
    <section className="rounded-2xl bg-[#12100a] p-3">
      <h2 className="mb-2.5 text-[13px] font-normal uppercase tracking-[0.15em] text-[#a08040]">Active Quest</h2>
      <article className="relative rounded-lg border border-[#2a1e0e] bg-[#161208] p-3">
        <div className="mb-2 flex items-start gap-2">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[#3a2810] text-[#c9a84c]">
            <IconCompassMini className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="font-serif text-[13px] font-medium leading-snug text-[#c9a84c]">{quest.title}</p>
            <p className="mt-1 font-serif text-[12px] leading-[1.6] text-[#8a7a5a]">{quest.description}</p>
            <ul className="mt-2 space-y-1 font-serif text-[12px] text-[#7a6a4a]">
              <li>
                <span className="text-[#c9a84c]">◆</span> Explore and gather leads
              </li>
            </ul>
          </div>
        </div>
      </article>
    </section>
  );
}
