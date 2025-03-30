import { useEffect, useRef } from "react";
import { DM_PORTRAIT_SRC } from "../data/portraits";
import PlayerAvatar from "./PlayerAvatar";

export default function StoryPanel({ messages, turnLabel = "Begin your adventure", chatPlayer }) {
  const scrollRef = useRef(null);

  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages]);

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl bg-[#12100a]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#2a1e0e] px-4 py-2.5">
        <h2 className="text-[13px] font-normal uppercase tracking-[0.15em] text-[#a08040]">STORY</h2>
        <div className="flex items-center gap-3 text-[11px] text-[#7a6a4a]">
          <span>{turnLabel}</span>
        </div>
      </header>

      <div className="story-scroll min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4" ref={scrollRef}>
        {messages.map((message) => (
          <article
            key={message.id}
            className={`animate-fade-in group flex gap-3 rounded-lg px-4 py-4 ${
              message.role === "dm"
                ? "message-dm max-w-[94%] bg-[#1e1610]"
                : "message-player ml-auto max-w-[80%] flex-row-reverse bg-[#1a2820]"
            }`}
          >
            {message.role === "dm" ? (
              <div className="mt-0.5 h-10 w-10 shrink-0 overflow-hidden rounded-full border-[2px] border-[#4a3568] bg-[#120a14]">
                <img alt="Dungeon Master" className="h-full w-full object-cover" src={DM_PORTRAIT_SRC} />
              </div>
            ) : (
              <div className="mt-0.5 shrink-0">
                {chatPlayer ? <PlayerAvatar player={chatPlayer} sizeClass="h-10 w-10" /> : null}
              </div>
            )}
            <div className="min-w-0 flex-1">
              <div className="mb-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-0">
                {message.role === "dm" ? (
                  <span
                    className="text-[12px] font-normal leading-none text-[#a08040]"
                    style={{ fontVariant: "small-caps" }}
                  >
                    Dungeon Master
                  </span>
                ) : (
                  <span
                    className="text-[12px] font-normal leading-none text-[#4a9070]"
                    style={{ fontVariant: "small-caps" }}
                  >
                    You
                  </span>
                )}
                <span className="text-[11px] text-[#6b5a3a]">{message.timestamp}</span>
                {message.role === "dm" ? null : (
                  <span className="ml-auto text-[11px] text-[#4a9070]/80">✓✓</span>
                )}
              </div>
              <p
                className="font-serif leading-[1.7] text-[14px]"
                style={{ color: "#c8b48a" }}
              >
                {message.text}
              </p>
            </div>
          </article>
        ))}
      </div>

    </section>
  );
}
