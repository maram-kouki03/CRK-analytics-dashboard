import { useRef, useState } from "react";

// Carte de la boutique : image + polygones de zones superposés en SVG.
// L'opacité de chaque zone est proportionnelle à son nombre de clients
// rapporté au max des 3 zones (mini-heatmap).
export default function ShopMap({ config, zoneStats, periodLabel }) {
  const wrapRef = useRef(null);
  const [imgSize, setImgSize] = useState(null); // { w, h } = dimensions naturelles de l'image
  const [hover, setHover] = useState(null); // { zone, x, y }

  const statsById = Object.fromEntries((zoneStats || []).map((z) => [z.id, z]));
  const maxClients = Math.max(1, ...(zoneStats || []).map((z) => z.clients));

  const handleLoad = (e) => {
    setImgSize({ w: e.target.naturalWidth, h: e.target.naturalHeight });
  };

  const handleMove = (e, zone) => {
    const rect = wrapRef.current.getBoundingClientRect();
    setHover({ zone, x: e.clientX - rect.left, y: e.clientY - rect.top });
  };

  const hoverStat = hover ? statsById[hover.zone.id] : null;

  return (
    <div className="shop-map">
      <div className="shop-map-wrap" ref={wrapRef}>
        <img
          src={config.image}
          alt="Plan de la boutique"
          className="shop-map-img"
          onLoad={handleLoad}
        />
        {imgSize && (
          <svg
            className="shop-map-svg"
            viewBox={`0 0 ${imgSize.w} ${imgSize.h}`}
            preserveAspectRatio="none"
          >
            {config.zones.map((zone) => {
              const stat = statsById[zone.id] || { clients: 0, pec: 0 };
              const intensity = Math.max(0.1, stat.clients / maxClients);
              const isHover = hover?.zone.id === zone.id;
              const points = zone.points
                .map((p) => `${(p.x / 100) * imgSize.w},${(p.y / 100) * imgSize.h}`)
                .join(" ");
              return (
                <polygon
                  key={zone.id}
                  points={points}
                  fill="#96402e"
                  fillOpacity={isHover ? Math.min(0.85, intensity * 0.55 + 0.3) : intensity * 0.55}
                  stroke="#96402e"
                  strokeWidth={Math.max(1, imgSize.w * 0.0025)}
                  strokeOpacity={isHover ? 0.9 : 0.55}
                  style={{ cursor: "pointer", transition: "fill-opacity 0.15s ease" }}
                  onMouseMove={(e) => handleMove(e, zone)}
                  onMouseLeave={() => setHover(null)}
                />
              );
            })}
          </svg>
        )}
        {hover && (
          <div className="shop-map-tooltip" style={{ left: hover.x + 14, top: hover.y + 14 }}>
            <div className="smt-title">{hover.zone.nom}</div>
            <div>Nombre de clients : {(hoverStat?.clients ?? 0).toLocaleString("fr-FR")}</div>
            <div>Prises en charge : {(hoverStat?.pec ?? 0).toLocaleString("fr-FR")}</div>
          </div>
        )}
      </div>
      <div className="shop-map-legend">
        Intensité = affluence de la zone · Période : {periodLabel}
      </div>
    </div>
  );
}
