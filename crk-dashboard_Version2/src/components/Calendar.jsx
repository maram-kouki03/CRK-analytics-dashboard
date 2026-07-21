import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

const MOIS = [
  "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
  "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
];
const JOURS = ["Lu", "Ma", "Me", "Je", "Ve", "Sa", "Di"];

// Calendrier en mode PÉRIODE (type Airbnb) :
// 1er clic = date de début, 2e clic = date de fin,
// puis bouton "Voir les résultats" pour appliquer.
export default function Calendar({ initialStart, initialEnd, onApply }) {
  const [start, setStart] = useState(initialStart);
  const [end, setEnd] = useState(initialEnd);
  const [viewYear, setViewYear] = useState(initialEnd.getFullYear());
  const [viewMonth, setViewMonth] = useState(initialEnd.getMonth());

  const today = new Date();

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(viewYear - 1); }
    else setViewMonth(viewMonth - 1);
  };
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(viewYear + 1); }
    else setViewMonth(viewMonth + 1);
  };

  const atCurrentMonth =
    viewYear === today.getFullYear() && viewMonth === today.getMonth();

  const firstDay = new Date(viewYear, viewMonth, 1);
  const offset = (firstDay.getDay() + 6) % 7; // lundi en premier
  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();

  const sameDay = (d1, d2) =>
    d1 && d2 &&
    d1.getFullYear() === d2.getFullYear() &&
    d1.getMonth() === d2.getMonth() &&
    d1.getDate() === d2.getDate();

  const isFuture = (y, m, day) => {
    const endOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate(), 23, 59, 59);
    return new Date(y, m, day) > endOfToday;
  };

  const handleDayClick = (d) => {
    const clicked = new Date(viewYear, viewMonth, d);
    if (!start || (start && end)) {
      // nouveau départ de sélection
      setStart(clicked);
      setEnd(null);
    } else {
      // deuxième clic : fixe la fin (inversion automatique si besoin)
      if (clicked < start) { setEnd(start); setStart(clicked); }
      else setEnd(clicked);
    }
  };

  const inRange = (date) => start && end && date > start && date < end;

  const cells = [];
  for (let i = 0; i < offset; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  const canApply = Boolean(start); // fin absente = période d'un seul jour

  return (
    <div className="calendar">
      <div className="cal-head">
        <button className="cal-nav" onClick={prevMonth} aria-label="Mois précédent">
          <ChevronLeft size={15} />
        </button>
        <span className="cal-month">{MOIS[viewMonth]} {viewYear}</span>
        <button className="cal-nav" onClick={nextMonth} disabled={atCurrentMonth} aria-label="Mois suivant">
          <ChevronRight size={15} />
        </button>
      </div>

      <div className="cal-grid">
        {JOURS.map((j) => (
          <div key={j} className="cal-dayname">{j}</div>
        ))}
        {cells.map((d, i) => {
          if (d === null) return <div key={`e${i}`} />;
          const date = new Date(viewYear, viewMonth, d);
          const isStart = sameDay(date, start);
          const isEnd = sameDay(date, end);
          return (
            <button
              key={d}
              disabled={isFuture(viewYear, viewMonth, d)}
              className={
                "cal-day" +
                (isStart || isEnd ? " range-edge" : "") +
                (inRange(date) ? " in-range" : "") +
                (sameDay(date, today) ? " today" : "")
              }
              onClick={() => handleDayClick(d)}
            >
              {d}
            </button>
          );
        })}
      </div>

      <div className="cal-footer">
        <span className="cal-hint">
          {!start
            ? "Choisis la date de début"
            : !end
            ? "Choisis la date de fin"
            : `${start.getDate()}/${start.getMonth() + 1} → ${end.getDate()}/${end.getMonth() + 1}`}
        </span>
        <button
          className="cal-apply"
          disabled={!canApply}
          onClick={() => onApply(start, end ?? start)}
        >
          Voir les résultats
        </button>
      </div>
    </div>
  );
}
