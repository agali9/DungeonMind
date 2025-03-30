import { useEffect, useState } from "react";

export default function HomeScreen({ onNewGame, onResume, onHowToPlay }) {
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    fetch("/api/me", { credentials: "same-origin" })
      .then((response) => {
        if (response.ok) setAuthed(true);
        else window.location.replace("/auth/login");
      })
      .catch(() => {
        window.location.replace("/auth/login");
      });
  }, []);

  if (!authed) return null;

  const embers = Array.from({ length: 14 }, (_, index) => ({
    id: index,
    left: `${8 + ((index * 6.7) % 84)}%`,
    bottom: `${6 + ((index * 5.2) % 54)}%`,
    rise: `-${80 + ((index * 17) % 121)}px`,
    drift: `${-20 + ((index * 13) % 41)}px`,
    duration: `${3 + ((index * 0.77) % 4)}s`,
    delay: `${(index * 0.31) % 2.2}s`,
    opacity: `${0.35 + ((index * 0.08) % 0.5)}`,
  }));

  return (
    <main className="relative m-0 h-screen min-h-screen w-screen overflow-hidden bg-[#0a0600] p-0">
      <svg width="0" height="0" style={{ position: "absolute" }}>
        <defs>
          <filter id="metallic">
            <feFlood floodColor="#c8860a" result="base" />
            <feBlend in="SourceGraphic" in2="base" mode="multiply" />
            <feComposite in2="SourceAlpha" operator="in" />
          </filter>
        </defs>
      </svg>
      <img
        alt=""
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 object-cover"
        style={{
          objectPosition: "center center",
          width: "100vw",
          height: "100vh",
          imageRendering: "auto",
        }}
        src="/title/dragon-title-bg.png"
      />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_20%,#0a0600_80%)]" />

      <div className="pointer-events-none absolute inset-0">
        {embers.map((ember) => (
          <span
            key={ember.id}
            className="ember-particle"
            style={{
              left: ember.left,
              bottom: ember.bottom,
              animationDuration: ember.duration,
              animationDelay: ember.delay,
              "--rise-y": ember.rise,
              "--drift-x": ember.drift,
              "--start-opacity": ember.opacity,
            }}
          />
        ))}
      </div>

      <section className="relative z-10 h-full w-full">
        <div
          className="absolute left-1/2 top-[66%] flex -translate-x-1/2 flex-col items-center"
          style={{ fontFamily: "Cinzel, var(--ev-font)", gap: "clamp(6px, 1.5vh, 14px)" }}
        >
          <button
            className="home-menu-btn inline-flex h-[52px] w-[320px] items-center justify-center border border-[#8a6a10] bg-[rgba(5,3,0,0.75)] px-6 text-center text-[13px] tracking-[0.2em] text-[#c9a84c] transition duration-200 ease-out hover:border-[#c9a84c] hover:bg-[rgba(35,24,4,0.78)] hover:text-[#f0d060] active:scale-[0.98]"
            style={{ width: "clamp(260px, 25vw, 380px)", fontSize: "clamp(11px, 1vw, 14px)" }}
            onClick={onNewGame}
            type="button"
          >
            <span className="home-menu-corner home-menu-corner-tl" />
            <span className="home-menu-corner home-menu-corner-tr" />
            <span className="home-menu-corner home-menu-corner-bl" />
            <span className="home-menu-corner home-menu-corner-br" />
            <span>NEW GAME</span>
          </button>
          <span className="text-[#7b6435]">◆</span>
          <button
            className="home-menu-btn inline-flex h-[52px] w-[320px] items-center justify-center border border-[#8a6a10] bg-[rgba(5,3,0,0.75)] px-6 text-center text-[13px] tracking-[0.2em] text-[#c9a84c] transition duration-200 ease-out hover:border-[#c9a84c] hover:bg-[rgba(35,24,4,0.78)] hover:text-[#f0d060] active:scale-[0.98]"
            style={{ width: "clamp(260px, 25vw, 380px)", fontSize: "clamp(11px, 1vw, 14px)" }}
            onClick={onResume}
            type="button"
          >
            <span className="home-menu-corner home-menu-corner-tl" />
            <span className="home-menu-corner home-menu-corner-tr" />
            <span className="home-menu-corner home-menu-corner-bl" />
            <span className="home-menu-corner home-menu-corner-br" />
            <span>RESUME</span>
          </button>
          <span className="text-[#7b6435]">◆</span>
          <button
            className="home-menu-btn inline-flex h-[52px] w-[320px] items-center justify-center border border-[#8a6a10] bg-[rgba(5,3,0,0.75)] px-6 text-center text-[13px] tracking-[0.2em] text-[#c9a84c] transition duration-200 ease-out hover:border-[#c9a84c] hover:bg-[rgba(35,24,4,0.78)] hover:text-[#f0d060] active:scale-[0.98]"
            onClick={onHowToPlay}
            style={{ width: "clamp(260px, 25vw, 380px)", fontSize: "clamp(11px, 1vw, 14px)" }}
            type="button"
          >
            <span className="home-menu-corner home-menu-corner-tl" />
            <span className="home-menu-corner home-menu-corner-tr" />
            <span className="home-menu-corner home-menu-corner-bl" />
            <span className="home-menu-corner home-menu-corner-br" />
            <span>HOW TO PLAY</span>
          </button>
        </div>
      </section>
      <a
        href="/auth/logout"
        className="btn-ghost"
        style={{ position: "fixed", bottom: "24px", right: "24px", zIndex: 50 }}
      >
        Log out
      </a>
    </main>
  );
}
