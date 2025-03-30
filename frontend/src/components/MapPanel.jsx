import { useMemo, useRef, useState } from "react";
import { LOCATION_COORDS } from "../data/locations";

const MAJOR_LOCATIONS = new Set([
  "tavern",
  "village_square",
  "forest",
  "ruins",
  "cave",
  "witchciell",
  "ironkeep",
  "mossmarket",
]);

const HIDDEN_FROM_MAP = new Set(["smithy", "apothecary", "road"]);

export default function MapPanel({
  locations,
  backendLocations = [],
  playerMarkers = [],
  showPlayers = true,
  visitedLocations,
  activeLocationId = null,
  onTogglePlayers,
}) {
  const mapRef = useRef(null);
  const [hoveredLocationId, setHoveredLocationId] = useState(null);
  const visibleLocations = useMemo(
    () => locations.filter((loc) => !HIDDEN_FROM_MAP.has(loc.id)),
    [locations],
  );
  const locationMap = useMemo(
    () => Object.fromEntries(visibleLocations.map((loc) => [loc.id, loc])),
    [visibleLocations],
  );
  const [devCoords, setDevCoords] = useState(null);
  const isDev = import.meta.env.DEV;

  const routeSegments = useMemo(() => {
    const seen = new Set();
    const segments = [];
    visibleLocations.forEach((loc) => {
      loc.connections.forEach((nextId) => {
        const key = [loc.id, nextId].sort().join("::");
        if (seen.has(key) || !locationMap[nextId]) return;
        seen.add(key);
        segments.push([loc, locationMap[nextId]]);
      });
    });
    return segments;
  }, [visibleLocations, locationMap]);

  const hoveredLocation = hoveredLocationId ? locationMap[hoveredLocationId] : null;
  const getLocationStyle = (locationId) => {
    const coords = LOCATION_COORDS[locationId];
    if (!coords) return { left: "50%", top: "50%", transform: "translate(-50%, -50%)" };
    return {
      position: "absolute",
      left: coords.x,
      top: coords.y,
      transform: "translate(-50%, -50%)",
    };
  };
  const toMapPercent = (value, max) => {
    if (typeof value !== "number") return "50%";
    if (value <= 100) return `${value}%`;
    return `${Math.max(0, Math.min(100, (value / max) * 100))}%`;
  };

  const getTooltipStyle = (loc) => {
    const x = Number.parseFloat(loc.x);
    const y = Number.parseFloat(loc.y);
    const rect = mapRef.current?.getBoundingClientRect();
    const mapWidth = rect?.width || 1;
    const mapHeight = rect?.height || 1;

    const tooltipWidth = 220;
    const tooltipHeight = 78;
    const pad = 10;
    const markerOffset = 18;

    const anchorX = (x / 100) * mapWidth;
    const anchorY = (y / 100) * mapHeight;

    const flipDown = y < 15;
    const flipRight = x < 15;
    const flipLeft = x > 85;

    let left = anchorX - tooltipWidth / 2;
    if (flipRight) left = anchorX - 12;
    if (flipLeft) left = anchorX - tooltipWidth + 12;
    left = Math.max(pad, Math.min(left, mapWidth - tooltipWidth - pad));

    let top = flipDown ? anchorY + markerOffset : anchorY - tooltipHeight - markerOffset;
    top = Math.max(pad, Math.min(top, mapHeight - tooltipHeight - pad));

    return {
      left: `${left}px`,
      top: `${top}px`,
      width: `${tooltipWidth}px`,
    };
  };

  return (
    <section className="panel-surface relative flex h-full min-h-0 flex-col overflow-hidden rounded-2xl bg-[#15100d]/85">
      <header className="flex items-center justify-between border-b border-amber-500/20 px-4 py-2.5">
        <h2 className="panel-header-glow text-sm font-semibold uppercase tracking-[0.18em] text-amber-100/90">
          Embervale Atlas
        </h2>
      </header>

      <div
        className="relative flex-1 overflow-hidden border-y border-amber-500/20 shadow-[inset_0_0_20px_rgba(0,0,0,0.5)]"
        onMouseMove={isDev ? (event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const x = (((event.clientX - rect.left) / rect.width) * 100).toFixed(1);
          const y = (((event.clientY - rect.top) / rect.height) * 100).toFixed(1);
          setDevCoords({ x, y });
        } : undefined}
        ref={mapRef}
        style={{ height: "100%" }}
      >
        <div className="absolute inset-0">
          <img
            alt="Illustrated world map"
            className="pointer-events-none h-full w-full object-cover object-top-left opacity-95"
            src="/map/embervale-final-map.png"
          />

          <svg className="pointer-events-none absolute inset-0 h-full w-full">
            {routeSegments.map(([from, to]) => (
              <path
                key={`${from.id}-${to.id}`}
                d={`M ${from.x}% ${from.y}% Q ${(from.x + to.x) / 2}% ${((from.y + to.y) / 2) - 3}% ${to.x}% ${to.y}%`}
                className="stroke-amber-100/45"
                fill="none"
                strokeDasharray="5 8"
                strokeWidth="1.4"
              />
            ))}
          </svg>
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_46%,transparent_52%,rgba(0,0,0,0.52)_100%)]" />

          {visibleLocations.map((loc) => (
            <div
              key={loc.id}
              className={`group absolute ${loc.id === activeLocationId ? "map-location-active" : ""}`}
              onMouseEnter={() => setHoveredLocationId(loc.id)}
              onMouseLeave={() => setHoveredLocationId(null)}
              style={getLocationStyle(loc.id)}
            >
              {MAJOR_LOCATIONS.has(loc.id) ? (
                <div className="location-icon relative h-7 w-7">
                  <img
                    alt={loc.name}
                    className="h-7 w-7 rounded-full border border-amber-100/25 bg-black/55 p-[2px] shadow-[0_4px_10px_rgba(0,0,0,0.45)] transition duration-300 group-hover:scale-110 group-hover:border-amber-100/50 group-hover:shadow-[0_0_20px_rgba(255,180,80,0.3)]"
                    src={loc.icon}
                  />
                  {!visitedLocations?.has(loc.id) && (
                    <div className="absolute inset-0 rounded-full bg-black/45" />
                  )}
                </div>
              ) : null}
              <span className="mt-1 block rounded bg-black/70 px-2 py-0.5 text-[10px] tracking-wide text-amber-50/90">
                {loc.name}
              </span>
            </div>
          ))}

          {hoveredLocation && (
            <div
              className="pointer-events-none absolute z-30 rounded-xl bg-[rgba(10,6,2,0.85)] px-3 py-2 text-[12px] text-amber-100/90"
              style={getTooltipStyle(hoveredLocation)}
            >
              <p className="font-semibold">{hoveredLocation.name}</p>
              {visitedLocations?.has(hoveredLocation.id) ? (
                <p className="text-amber-100/80">{hoveredLocation.description}</p>
              ) : (
                <p className="text-amber-100/70">Undiscovered</p>
              )}
              <p className="mt-1 text-amber-100/75">
                Danger: {(hoveredLocation.danger || 0) > 0 ? "☠".repeat(hoveredLocation.danger) : "None"}
              </p>
            </div>
          )}

          {showPlayers ? playerMarkers.map((character) => (
            <div
              className="map-player-bubble"
              key={`marker-${character.id}`}
              style={(() => {
                const numericLocationId = Number(character?.map?.location_id);
                const backendLoc = backendLocations.find((entry) => Number(entry.id) === numericLocationId);
                const currentLocKey = backendLoc?.key || character?.current_location_key || "tavern";
                const coords = LOCATION_COORDS[currentLocKey] || LOCATION_COORDS.tavern;
                if (coords) {
                  return {
                    position: "absolute",
                    left: coords.x,
                    top: coords.y,
                    backgroundColor: character?.pin_color || "#d98a3a",
                    transform: "translate(-50%, -50%)",
                  };
                }
                return {
                  position: "absolute",
                  left: "50%",
                  top: "50%",
                  backgroundColor: character?.pin_color || "#d98a3a",
                  transform: "translate(-50%, -50%)",
                };
              })()}
              title={`${character?.name || "Unknown"} - HP ${character?.hp ?? 0}/${character?.max_hp ?? 0}`}
            >
              {(character?.name || "?").slice(0, 1).toUpperCase()}
              <span className={`player-dot ${character?.is_online ? "online" : "offline"}`} />
            </div>
          )) : null}
        </div>
        {isDev && devCoords ? (
          <div className="absolute bottom-2 left-2 z-[100] rounded bg-black/80 px-2 py-1 font-mono text-xs text-[#6ae0a9] pointer-events-none">
            x: {devCoords.x}% y: {devCoords.y}%
          </div>
        ) : null}
        <button
          className="absolute bottom-3 left-1/2 z-20 -translate-x-1/2 rounded-xl border border-amber-500/25 bg-[#16110c]/90 px-3 py-1.5 text-[11px] uppercase tracking-[0.14em] text-amber-100/85 transition hover:scale-105 hover:border-amber-400/40"
          onClick={onTogglePlayers}
          type="button"
        >
          {showPlayers ? "Hide Players" : "Show Players"}
        </button>

      </div>

    </section>
  );
}
