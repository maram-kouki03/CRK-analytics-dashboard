import { useState, useRef, useEffect } from "react";
import { Calendar as CalendarIcon, ChevronDown, Check, Store } from "lucide-react";
import Calendar from "./Calendar";

const MOIS_COURT = [
  "Jan", "Fév", "Mars", "Avr", "Mai", "Juin",
  "Juil", "Août", "Sept", "Oct", "Nov", "Déc",
];

// Libellé de la période, style Airbnb :
// "12 – 18 Juil 2026", "28 Juin – 4 Juil 2026", ou "12 Juil 2026" (1 jour)
function formatRange(start, end) {
  const d1 = start.getDate(), m1 = start.getMonth(), y1 = start.getFullYear();
  const d2 = end.getDate(), m2 = end.getMonth(), y2 = end.getFullYear();
  if (d1 === d2 && m1 === m2 && y1 === y2) return `${d2} ${MOIS_COURT[m2]} ${y2}`;
  if (m1 === m2 && y1 === y2) return `${d1} – ${d2} ${MOIS_COURT[m2]} ${y2}`;
  if (y1 === y2) return `${d1} ${MOIS_COURT[m1]} – ${d2} ${MOIS_COURT[m2]} ${y2}`;
  return `${d1} ${MOIS_COURT[m1]} ${y1} – ${d2} ${MOIS_COURT[m2]} ${y2}`;
}

function useClickOutside(ref, onClose) {
  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [ref, onClose]);
}

export default function Topbar({
  title,
  // sélecteur de magasin (mode interactif si stores est fourni)
  stores,
  selectedStore,
  onStoreChange,
  // libellé de magasin statique (si stores n'est pas fourni)
  storeLabel,
  // période : toujours affichée ; éditable si onRangeChange est fourni
  rangeStart,
  rangeEnd,
  onRangeChange,
}) {
  const storeInteractive = Boolean(stores);
  const dateInteractive = Boolean(onRangeChange);

  const [dateOpen, setDateOpen] = useState(false);
  const [storeOpen, setStoreOpen] = useState(false);
  const dateRef = useRef(null);
  const storeRef = useRef(null);
  useClickOutside(dateRef, () => setDateOpen(false));
  useClickOutside(storeRef, () => setStoreOpen(false));

  return (
    <header className="topbar">
      <h1>
        {title}
        {storeInteractive && (
          <>
            {" "}- <span className="store-name">{selectedStore}</span>
          </>
        )}
      </h1>

      <div className="topbar-right">
        {/* ---- Période ---- */}
        {dateInteractive ? (
          <div className="popover-wrap" ref={dateRef}>
            <button
              className={`select-pill${dateOpen ? " open" : ""}`}
              onClick={() => { setDateOpen(!dateOpen); setStoreOpen(false); }}
            >
              <CalendarIcon size={15} />
              {formatRange(rangeStart, rangeEnd)}
              <ChevronDown size={14} />
            </button>
            {dateOpen && (
              <div className="popover">
                <Calendar
                  initialStart={rangeStart}
                  initialEnd={rangeEnd}
                  onApply={(s, e) => { onRangeChange(s, e); setDateOpen(false); }}
                />
              </div>
            )}
          </div>
        ) : (
          <span className="select-pill static">
            <CalendarIcon size={15} />
            {formatRange(rangeStart, rangeEnd)}
          </span>
        )}

        {/* ---- Sélecteur de magasin ---- */}
        {storeInteractive ? (
          <div className="popover-wrap" ref={storeRef}>
            <button
              className={`select-pill${storeOpen ? " open" : ""}`}
              onClick={() => { setStoreOpen(!storeOpen); setDateOpen(false); }}
            >
              {selectedStore}
              <ChevronDown size={14} />
            </button>
            {storeOpen && (
              <div className="popover store-list">
                {stores.map((s) => (
                  <button
                    key={s}
                    className={`store-option${s === selectedStore ? " selected" : ""}`}
                    onClick={() => { onStoreChange(s); setStoreOpen(false); }}
                  >
                    <Store size={14} />
                    {s}
                    {s === selectedStore && <Check size={14} className="check" />}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <span className="select-pill static">{storeLabel}</span>
        )}

        <div className="avatar">CRK</div>
      </div>
    </header>
  );
}
