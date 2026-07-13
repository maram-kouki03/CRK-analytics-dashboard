import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

const MOIS = [
  "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
  "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
];
const JOURS = ["Lu", "Ma", "Me", "Je", "Ve", "Sa", "Di"];

export default function Calendar({ selected, onSelect }) {
  const [viewYear, setViewYear] = useState(selected.getFullYear());
  const [viewMonth, setViewMonth] = useState(selected.getMonth());

  const today = new Date();

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(viewYear - 1); }
    else setViewMonth(viewMonth - 1);
  };
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(viewYear + 1); }
    else setViewMonth(viewMonth + 1);
  };

  // on ne peut pas naviguer au-delà du mois en cours
  const atCurrentMonth =
    viewYear === today.getFullYear() && viewMonth === today.getMonth();

  const firstDay = new Date(viewYear, viewMonth, 1);
  // getDay() : 0 = dimanche → on veut lundi en premier
  const offset = (firstDay.getDay() + 6) % 7;
  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();

  const isSameDay = (d1, y, m, day) =>
    d1.getFullYear() === y && d1.getMonth() === m && d1.getDate() === day;

  // une date est future si elle est après aujourd'hui (jour entier)
  const isFuture = (y, m, day) => {
    const endOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate(), 23, 59, 59);
    return new Date(y, m, day) > endOfToday;
  };

  const cells = [];
  for (let i = 0; i < offset; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  return (
    <div className="calendar">
      <div className="cal-head">
        <button className="cal-nav" onClick={prevMonth} aria-label="Mois précédent">
          <ChevronLeft size={15} />
        </button>
        <span className="cal-month">{MOIS[viewMonth]} {viewYear}</span>
        <button
          className="cal-nav"
          onClick={nextMonth}
          disabled={atCurrentMonth}
          aria-label="Mois suivant"
        >
          <ChevronRight size={15} />
        </button>
      </div>

      <div className="cal-grid">
        {JOURS.map((j) => (
          <div key={j} className="cal-dayname">{j}</div>
        ))}
        {cells.map((d, i) =>
          d === null ? (
            <div key={`e${i}`} />
          ) : (
            <button
              key={d}
              disabled={isFuture(viewYear, viewMonth, d)}
              className={
                "cal-day" +
                (isSameDay(selected, viewYear, viewMonth, d) ? " selected" : "") +
                (isSameDay(today, viewYear, viewMonth, d) ? " today" : "")
              }
              onClick={() => onSelect(new Date(viewYear, viewMonth, d))}
            >
              {d}
            </button>
          )
        )}
      </div>
    </div>
  );
}
