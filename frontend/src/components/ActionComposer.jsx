import { useState } from "react";

export default function ActionComposer({
  value,
  onChange,
  onSendAction,
  onVoiceInput,
  voiceSupported = true,
  dmThinking = false,
  suggestions = [],
  suggestionsLoading = false,
}) {
  const [internal, setInternal] = useState("");
  const isControlled = typeof onChange === "function" && value !== undefined;
  const text = isControlled ? value : internal;
  const setText = isControlled ? onChange : setInternal;

  const submit = () => {
    const t = text.trim();
    if (!t) return;
    onSendAction(t);
    setText("");
  };

  return (
    <section className="rounded-2xl bg-[#12100a] p-2.5">
      {(suggestionsLoading || suggestions.length > 0) && (
        <div className="mb-2.5 flex flex-wrap gap-2">
          {suggestionsLoading
            ? Array.from({ length: 3 }).map((_, idx) => (
                <span
                  key={`skeleton-${idx}`}
                  className="suggestion-skeleton h-9 w-[180px] rounded-full border border-[#3a2a14] bg-[#1e1610]"
                />
              ))
            : suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  className="inline-flex items-center gap-2 rounded-full border border-[#3a2a14] bg-[#1e1610] px-4 py-2 font-serif text-[14px] text-[#d4c4a0] transition hover:bg-[#261c14]"
                  onClick={() => setText(suggestion)}
                  type="button"
                >
                  <span className="text-[#c9a84c]">◆</span>
                  {suggestion}
                </button>
              ))}
        </div>
      )}

      <div className="flex items-end gap-2">
        <div className="relative flex-1">
          <button
            className="absolute left-2 top-1/2 z-10 h-8 w-8 -translate-y-1/2 text-[#7a6a4a] transition hover:text-[#a09070] disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!voiceSupported}
            onClick={onVoiceInput}
            title="Voice input"
            type="button"
          >
            <svg
              aria-hidden="true"
              className="mx-auto h-[18px] w-[18px]"
              fill="none"
              stroke="currentColor"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="1.8"
              viewBox="0 0 24 24"
            >
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" x2="12" y1="19" y2="23" />
              <line x1="8" x2="16" y1="23" y2="23" />
            </svg>
          </button>
          <button
            className="absolute left-11 top-1/2 z-10 h-8 w-8 -translate-y-1/2 rounded-full border border-[#3a2a14] bg-[#1a1308] text-sm text-[#8a7a5a] transition hover:border-[#4a3a24] hover:text-[#b8a88a]"
            title="Action prompt helper"
            type="button"
          >
            ✒
          </button>
          <textarea
            className="h-12 min-h-12 w-full resize-y rounded-lg border py-3 pl-20 pr-4 font-serif text-[14px] text-[#d4c4a0] outline-none transition placeholder:text-[#6b5a3a] focus:border-[#4a3a24]"
            style={{ backgroundColor: "#1a1308", borderColor: "#3a2a14", borderWidth: "1px" }}
            maxLength={800}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder="What do you do?"
            rows={2}
            value={text}
          />
        </div>
        <button
          className="h-12 w-12 shrink-0 rounded-lg border border-[#6a5220] font-serif text-xl text-[#1a1308] transition hover:brightness-110"
          disabled={!text.trim() || dmThinking}
          style={{ backgroundColor: "#8a6a20" }}
          onClick={submit}
          title="Send action"
          type="button"
        >
          ➤
        </button>
      </div>
    </section>
  );
}
