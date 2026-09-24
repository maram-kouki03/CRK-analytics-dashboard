import { useEffect, useState } from "react";
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import {
  Users, Handshake, AlertTriangle, Banknote, Receipt,
  CalendarRange, ArrowUp, ArrowDown,
} from "lucide-react";
import Topbar from "../components/Topbar";
import { ErrorBlock, NoDataBlock, PageLoader } from "../components/States";
import {
  CaptureHourlyCard, ConversionHourlyCard, FunnelCard, GapHourlyCard,
  ObjectifPicker, PotentialHourlyCard, SectionHead, SimulationBanner,
} from "../components/SalesPotential";
import { fetchRange, fetchSeries } from "../api/client";
import { useApi, useStores } from "../api/useApi";
import {
  computeDelta, fmtDT, fmtInt, fmtNum, fmtPct, fmtRange, MISSING,
} from "../lib/format";

// Ce que le boîtier mesure. Chaque entrée lit une clé de `kpis` (GET /api/range).
// Le taux PEC n'est plus une carte : il figure dans l'entonnoir, sous le niveau
// « Pris en charge » qu'il produit, où il se lit avec les deux volumes qu'il relie.
const KPI_DEFS = [
  { key: "clients_entres", label: "Clients entrés", icon: Users, format: fmtInt },
  { key: "clients_par_jour", label: "Clients / jour (moy.)", icon: CalendarRange, format: (v) => fmtNum(v) },
  { key: "pec_count", label: "Nombre de PEC", icon: Handshake, format: fmtInt },
];

// Cartes de caisse : même présentation, mais lues dans `ventes` et marquées
// « simulé » tant que l'API caisse n'est pas branchée.
const KPI_VENTES = [
  { key: "revenue", label: "Chiffre d'affaires", icon: Banknote, format: (v) => fmtDT(v) },
  { key: "tickets", label: "Tickets", icon: Receipt, format: fmtInt },
];

const PERIODES = [
  { value: "jour", label: "Par jour" },
  { value: "semaine", label: "Par semaine" },
  { value: "mois", label: "Par mois" },
];

// couleur heatmap : vert → jaune → orange → rouge, sur la part du maximum
function heatColor(ratio) {
  if (ratio <= 0) return "#f4efe9";
  if (ratio < 0.25) return "#cde7c8";
  if (ratio < 0.45) return "#f5e08a";
  if (ratio < 0.65) return "#f2c063";
  if (ratio < 0.85) return "#ec8f4a";
  return "#d64533";
}

const tooltipStyle = {
  background: "#fff",
  border: "1px solid #f0e6df",
  borderRadius: 10,
  fontSize: 12,
};

const fmtTooltip = (v) => (v === null || v === undefined ? MISSING : v.toLocaleString("fr-FR"));

// L'axe affiche « 11h » faute de place, mais la valeur couvre 11h00–11h59.
// L'infobulle écrit la tranche en entier : « 11h » seul se lit comme un instant.
const trancheHoraire = (label) => {
  const debut = parseInt(label, 10);
  return Number.isNaN(debut) ? label : `${label} – ${String(debut + 1).padStart(2, "0")}h`;
};

export default function Dashboard({ rangeStart, rangeEnd, onRangeChange }) {
  const { stores, sansDonnees, defaut, error: storesError } = useStores();
  const [selectedStore, setSelectedStore] = useState(null);
  const [periodeClients, setPeriodeClients] = useState("jour");
  const [periodeTaux, setPeriodeTaux] = useState("jour");
  // Objectif de conversion visé, en %. C'est une hypothèse de travail que la
  // direction déplace pour voir bouger le potentiel de vente — pas une mesure.
  // 20 % est le repère fourni par CRK (défaut de CRK_CR_TARGET_PCT côté API).
  const [objectif, setObjectif] = useState(20);

  // Ouvrir sur le magasin le plus récemment actif (cf. useStores) : une page
  // vide au premier chargement se lirait comme un dashboard cassé.
  useEffect(() => {
    if (selectedStore || !defaut) return;
    setSelectedStore(defaut);
  }, [defaut, selectedStore]);

  const range = useApi(
    () =>
      selectedStore
        ? fetchRange(selectedStore, rangeStart, rangeEnd, objectif)
        : Promise.resolve(null),
    [selectedStore, rangeStart, rangeEnd, objectif]
  );
  const serieClients = useApi(
    () => (selectedStore ? fetchSeries(selectedStore, periodeClients, rangeEnd) : Promise.resolve(null)),
    [selectedStore, periodeClients, rangeEnd]
  );
  const serieTaux = useApi(
    () => (selectedStore ? fetchSeries(selectedStore, periodeTaux, rangeEnd) : Promise.resolve(null)),
    [selectedStore, periodeTaux, rangeEnd]
  );

  if (storesError) return <ErrorBlock error={storesError} onRetry={() => window.location.reload()} />;
  if (!selectedStore) return <PageLoader label="Chargement des magasins…" />;

  const data = range.data;
  const periodLabel = fmtRange(rangeStart, rangeEnd);

  // Les cartes du haut cumulent toute la periode ; les graphes horaires, eux,
  // detaillent tranche par tranche. Le libelle dit laquelle des deux on lit.
  const finAujourdhui = rangeEnd.toDateString() === new Date().toDateString();
  const heureOuverture = data?.heureDePointe?.[0]?.h ?? "10h";
  const cumulLabel = finAujourdhui
    ? `cumul de ${heureOuverture} à maintenant`
    : `cumul sur la période (${periodLabel})`;

  return (
    <div>
      <Topbar
        title="Tableau de bord"
        stores={stores}
        storesSansDonnees={sansDonnees}
        selectedStore={selectedStore}
        onStoreChange={setSelectedStore}
        rangeStart={rangeStart}
        rangeEnd={rangeEnd}
        onRangeChange={onRangeChange}
      />

      {range.error && <ErrorBlock error={range.error} />}
      {!data && range.loading && <PageLoader />}

      {data && (
        <>
          {data.kpis.evenements === 0 && (
            <NoDataBlock>
              Aucun événement reçu de {selectedStore} entre le {periodLabel}. Les
              indicateurs ci-dessous sont donc vides — choisis une autre période ou
              vérifie que le boîtier de la boutique émet bien.
            </NoDataBlock>
          )}

          {/* ---- Section 1 : ce que le boitier mesure ---- */}
          <SectionHead
            title="Fréquentation & prise en charge"
            sub="Mesuré par le boîtier caméra de la boutique"
          />
          <div className="kpi-row">
            {KPI_DEFS.map((def) => (
              <KpiCard
                key={def.key}
                def={def}
                value={data.kpis[def.key]}
                previous={data.kpisPrecedent?.[def.key]}
              />
            ))}
          </div>

          {/* ---- Section 2 : ventes & potentiel (croise caisse + boitier) ---- */}
          {data.ventes && (
            <>
              <SectionHead
                title="Ventes & potentiel"
                sub="Croisement des visiteurs mesurés avec les données de caisse"
                action={
                  <ObjectifPicker value={objectif} onChange={setObjectif} />
                }
              />
              <SimulationBanner ventes={data.ventes} />
              {/* Ces deux cartes additionnent toute la periode, contrairement aux
                  graphes horaires plus bas : on le dit explicitement. */}
              <div className="cumul-note">{cumulLabel}</div>
              <div className="kpi-row kpi-row-2">
                {KPI_VENTES.map((def) => (
                  <KpiCard
                    key={def.key}
                    def={def}
                    value={data.ventes[def.key]}
                    previous={data.ventesPrecedent?.[def.key]}
                    simule={data.ventes.simule}
                  />
                ))}
              </div>
              {/* Entonnoir cumule, puis les indicateurs de potentiel : chacun
                  porte son total de periode ET sa ventilation horaire, c'est la
                  que se voit A QUELLE HEURE le potentiel n'est pas converti.
                  Captation et conversion sont cote a cote : la premiere mesure
                  l'ecart a l'objectif, la seconde ce qui s'est reellement
                  passe, et les lire ensemble evite de confondre les deux. */}
              <div className="grid-charts">
                <FunnelCard ventes={data.ventes} cumulLabel={cumulLabel} />
                <PotentialHourlyCard ventes={data.ventes} cumulLabel={cumulLabel} />
                <GapHourlyCard ventes={data.ventes} cumulLabel={cumulLabel} />
                <CaptureHourlyCard ventes={data.ventes} cumulLabel={cumulLabel} />
                <ConversionHourlyCard ventes={data.ventes} cumulLabel={cumulLabel} />
              </div>
            </>
          )}

          {/* ---- Section 3 : detail horaire ---- */}
          <SectionHead
            title="Détail par heure et par jour"
            sub="Répartition de la fréquentation sur la période"
          />

          {/* ---- Charts ---- */}
          <div className="grid-charts">
            <ChartCard
              title="Heure de pointe"
              sub={`Clients entrés par tranche horaire — total sur la période (${data.periode.nbJours} j)`}
            >
              {/* Des barres, pas une courbe : ce sont 12 comptages par tranche
                  d'une heure, pas un signal continu. Une aire interpolerait entre
                  10h et 11h et laisserait croire à une arrivée progressive, alors
                  que les clients sont arrivés dans la tranche 11h–12h. */}
              <BarChart data={data.heureDePointe} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
                <XAxis dataKey="h" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip
                  contentStyle={tooltipStyle}
                  labelFormatter={trancheHoraire}
                  formatter={(v) => [fmtTooltip(v), "Clients"]}
                />
                <Bar dataKey="clients" name="Clients" fill="#96402e" radius={[4, 4, 0, 0]} barSize={18} />
              </BarChart>
            </ChartCard>

            <ChartCard title="PEC par heure" sub="Prises en charge par tranche horaire — total sur la période">
              <BarChart data={data.pecParHeure} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
                <XAxis dataKey="h" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip
                  contentStyle={tooltipStyle}
                  labelFormatter={trancheHoraire}
                  formatter={(v) => [fmtTooltip(v), "PEC"]}
                />
                <Bar dataKey="pec" name="PEC" fill="#96402e" radius={[4, 4, 0, 0]} barSize={18} />
              </BarChart>
            </ChartCard>

            <ChartCard title="Taux PEC par heure" sub="PEC / clients entrés, par tranche horaire">
              <LineChart data={data.tauxParHeure} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
                <XAxis dataKey="h" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
                {/* Pas de plafond à 100 % : le taux mesuré dépasse réellement 100 %
                    sur ces données, borner l'axe masquerait l'anomalie. */}
                <YAxis unit="%" domain={[0, "auto"]} tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={tooltipStyle}
                  labelFormatter={trancheHoraire}
                  formatter={(v) => [fmtPct(v), "Taux PEC"]}
                />
                <Line
                  type="monotone" dataKey="taux" name="Taux PEC"
                  stroke="#c0392b" strokeWidth={2}
                  dot={{ r: 3, fill: "#c0392b" }}
                  activeDot={{ r: 5 }}
                  connectNulls={false}
                />
              </LineChart>
            </ChartCard>

            <SeriesCard
              title="Clients entrés dans le temps"
              sub="Comptage caméra agrégé"
              state={serieClients}
              periode={periodeClients}
              onPeriodeChange={setPeriodeClients}
            >
              {(points) => (
                <BarChart data={points} margin={{ top: 5, right: 5, left: -12, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip contentStyle={tooltipStyle} formatter={(v) => [fmtTooltip(v), "Clients"]} />
                  <Bar dataKey="clients" name="Clients" fill="#96402e" radius={[4, 4, 0, 0]} barSize={22} />
                </BarChart>
              )}
            </SeriesCard>

            <SeriesCard
              title="Taux PEC dans le temps"
              sub="PEC / clients entrés"
              state={serieTaux}
              periode={periodeTaux}
              onPeriodeChange={setPeriodeTaux}
            >
              {(points) => (
                <LineChart data={points} margin={{ top: 5, right: 5, left: -12, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
                  <YAxis unit="%" domain={[0, "auto"]} tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={tooltipStyle} formatter={(v) => [fmtPct(v), "Taux PEC"]} />
                  <Line
                    type="monotone" dataKey="taux" name="Taux PEC"
                    stroke="#1e9e5a" strokeWidth={2}
                    dot={{ r: 3, fill: "#1e9e5a" }}
                    activeDot={{ r: 5 }}
                    connectNulls={false}
                  />
                </LineChart>
              )}
            </SeriesCard>
          </div>

          {/* ---- Heatmap ---- */}
          <div className="card" style={{ marginTop: 16 }}>
            <div className="card-head">
              <div>
                <div className="card-title">Heatmap de présence clients</div>
                <div className="card-sub">
                  Clients entrés par heure et par jour de semaine, cumulés sur la période
                </div>
              </div>
            </div>
            <Heatmap heatmap={data.heatmap} />
          </div>
        </>
      )}
    </div>
  );
}

function KpiCard({ def, value, previous, simule = false }) {
  const Icon = def.icon;
  const delta = computeDelta(value, previous, def.delta ?? "pct");
  const missing = value === null || value === undefined;
  const warning = missing ? null : def.warn?.(value);

  return (
    <div className="kpi-card">
      <div className="kpi-icon"><Icon size={20} /></div>
      <div className="kpi-body">
        <div className="kpi-label">
          {def.label}
          {simule && <span className="funnel-sim">simulé</span>}
        </div>
        <div className={`kpi-value${missing ? " missing" : ""}`}>{def.format(value)}</div>
        {missing && def.hint ? (
          <span className="kpi-note">{def.hint}</span>
        ) : delta ? (
          <span className={`kpi-delta ${def.neutral ? "neutral" : delta.up ? "up" : "down"}`}>
            {delta.up ? <ArrowUp size={11} /> : <ArrowDown size={11} />}
            {delta.text} <span className="vs">vs période préc.</span>
          </span>
        ) : (
          <span className="kpi-note">pas de période précédente comparable</span>
        )}
        {warning && (
          <div className="kpi-warn">
            <AlertTriangle size={11} /> {warning}
          </div>
        )}
      </div>
    </div>
  );
}

function ChartCard({ title, sub, action, children }) {
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">{title}</div>
          {sub && <div className="card-sub">{sub}</div>}
        </div>
        {action}
      </div>
      <ResponsiveContainer width="100%" height={310}>
        {children}
      </ResponsiveContainer>
    </div>
  );
}

/** Carte de série temporelle avec son propre sélecteur jour / semaine / mois. */
function SeriesCard({ title, sub, state, periode, onPeriodeChange, children }) {
  const select = (
    <select
      className="mini-select"
      value={periode}
      onChange={(e) => onPeriodeChange(e.target.value)}
    >
      {PERIODES.map((p) => (
        <option key={p.value} value={p.value}>{p.label}</option>
      ))}
    </select>
  );

  if (state.error) {
    return (
      <div className="card">
        <div className="card-head">
          <div><div className="card-title">{title}</div></div>
          {select}
        </div>
        <ErrorBlock error={state.error} />
      </div>
    );
  }

  if (!state.data) {
    return (
      <div className="card">
        <div className="card-head">
          <div><div className="card-title">{title}</div></div>
          {select}
        </div>
        <PageLoader label="Chargement de la série…" />
      </div>
    );
  }

  return (
    <ChartCard title={title} sub={sub} action={select}>
      {children(state.data.points)}
    </ChartCard>
  );
}

function Heatmap({ heatmap }) {
  const { heures, jours, data, max } = heatmap;
  return (
    <>
      <div className="heatmap">
        <div />
        {jours.map((j) => (
          <div key={j} className="hm-day">{j}</div>
        ))}
        {data.map((row, i) => (
          <HeatRow key={heures[i]} heure={heures[i]} row={row} jours={jours} max={max} />
        ))}
      </div>
      <div className="hm-legend">
        Faible <div className="bar" /> Élevé
        <span className="hm-max">
          {max > 0 ? `max ${fmtInt(max)} clients / case` : "aucun client compté"}
        </span>
      </div>
    </>
  );
}

function HeatRow({ heure, row, jours, max }) {
  return (
    <>
      <div className="hm-label">{heure}</div>
      {row.map((v, i) => (
        <div
          key={jours[i]}
          className="hm-cell"
          style={{ background: heatColor(max ? v / max : 0) }}
          title={`${jours[i]} ${heure} — ${fmtInt(v)} client${v === 1 ? "" : "s"}`}
        />
      ))}
    </>
  );
}
