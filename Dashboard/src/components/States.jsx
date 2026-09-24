import { AlertTriangle, Loader2, Inbox } from "lucide-react";

/** Chargement d'une page entière (première requête). */
export function PageLoader({ label = "Chargement des données…" }) {
  return (
    <div className="state-block">
      <Loader2 size={22} className="spin" />
      <span>{label}</span>
    </div>
  );
}

/** Échec d'une requête backend : on montre le message réel, pas un « oups ». */
export function ErrorBlock({ error, onRetry }) {
  return (
    <div className="state-block error">
      <AlertTriangle size={22} />
      <div>
        <div className="state-title">Impossible de charger les données</div>
        <div className="state-msg">{error?.message ?? String(error)}</div>
      </div>
      {onRetry && (
        <button className="cal-apply" onClick={onRetry}>
          Réessayer
        </button>
      )}
    </div>
  );
}

/** Requête réussie mais aucun événement sur la période. */
export function NoDataBlock({ children }) {
  return (
    <div className="state-block">
      <Inbox size={22} />
      <div>
        <div className="state-title">Aucune donnée sur cette période</div>
        <div className="state-msg">{children}</div>
      </div>
    </div>
  );
}
