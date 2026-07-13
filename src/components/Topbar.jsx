import { useState, useRef, useEffect } from "react";
import { Calendar as CalendarIcon, ChevronDown, Check, Store } from "lucide-react";
import Calendar from "./Calendar";

const MOIS_COURT = [
  "Jan", "Fév", "Mars", "Avr", "Mai", "Juin",
  "Juil", "Août", "Sept", "Oct", "Nov", "Déc",
];

function formatDate(d) {
  const today = new Date();
  const isToday =
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate();
  const label = `${d.getDate()} ${MOIS_COURT[d.getMonth()]} ${d.getFullYear()}`;
  return isToday ? `Aujourd'hui · ${label}` : label;
}

// hook : ferme le popover quand on clique en dehors
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
  // mode interactif (dashboard)
  stores,
  selectedStore,
  onStoreChange,
  selectedDate,
  onDateChange,
  // mode statique (comparaison)
  dateLabel,
  storeLabel,
}) {
  const interactive = Boolean(stores);

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
        {interactive && (
          <>
            {" "}- <span className="store-name">{selectedStore}</span>
          </>
        )}
      </h1>

      <div className="topbar-right">
        {/* ---- Sélecteur de date ---- */}
        <div className="popover-wrap" ref={dateRef}>
          <button
            className={`select-pill${dateOpen ? " open" : ""}`}
            onClick={() => { setDateOpen(!dateOpen); setStoreOpen(false); }}
          >
            <CalendarIcon size={15} />
            {interactive ? formatDate(selectedDate) : dateLabel}
            <ChevronDown size={14} />
          </button>
          {interactive && dateOpen && (
            <div className="popover">
              <Calendar
                selected={selectedDate}
                onSelect={(d) => { onDateChange(d); setDateOpen(false); }}
              />
            </div>
          )}
        </div>

        {/* ---- Sélecteur de magasin ---- */}
        <div className="popover-wrap" ref={storeRef}>
          <button
            className={`select-pill${storeOpen ? " open" : ""}`}
            onClick={() => { setStoreOpen(!storeOpen); setDateOpen(false); }}
          >
            {interactive ? selectedStore : storeLabel}
            <ChevronDown size={14} />
          </button>
          {interactive && storeOpen && (
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

        <div className="avatar">CRK</div>
      </div>
    </header>
  );
}
