import { useState, useRef, useEffect } from "react";
import { Calendar as CalendarIcon, ChevronDown, Check, Store } from "lucide-react";
import Calendar from "./Calendar";
import { fmtRange as formatRange } from "../lib/format";

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
  // noms des magasins qui n'ont encore envoyé aucun événement : signalés dans la
  // liste pour qu'un dashboard vide se lise comme « pas de flux », pas « bug »
  storesSansDonnees,
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
                    {storesSansDonnees?.has(s) && <span className="store-flag">aucun flux</span>}
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
