import { useState, useMemo } from "react";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import {
  Users, Handshake, Percent, UserRound,
  ShoppingBag, Banknote, ArrowUp, ArrowDown,
} from "lucide-react";
import Topbar from "../components/Topbar";
import ShopMap from "../components/ShopMap";
import {
  storeNames, getKpiSeries, heatmapHeures, heatmapJours,
} from "../data/mockData";
import { getRangeData, getZoneStatsRange } from "../data/rangeData";
import shopMaps from "../data/shopMaps";

const MOIS_COURT = ["Jan","Fév","Mars","Avr","Mai","Juin","Juil","Août","Sept","Oct","Nov","Déc"];
const fmtPeriodDate = (d) => `${String(d.getDate()).padStart(2, "0")} ${MOIS_COURT[d.getMonth()]} ${d.getFullYear()}`;

const PERIODES = [
  { value: "jour", label: "Par jour" },
  { value: "semaine", label: "Par semaine" },
  { value: "mois", label: "Par mois" },
];

// format compact pour les grands montants (axes du potentiel)
const fmtCompact = (v) =>
  v >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M` :
  v >= 1_000 ? `${Math.round(v / 1_000)}k` : v;

const kpiIcons = {
  clients: Users,
  pec: Handshake,
  taux: Percent,
  vendeurs: UserRound,
  transformation: ShoppingBag,
  potentiel: Banknote,
};

// couleur heatmap : vert → jaune → orange → rouge
function heatColor(v) {
  if (v < 0.25) return "#cde7c8";
  if (v < 0.45) return "#f5e08a";
  if (v < 0.65) return "#f2c063";
  if (v < 0.85) return "#ec8f4a";
  return "#d64533";
}

const tooltipStyle = {
  background: "#fff",
  border: "1px solid #f0e6df",
  borderRadius: 10,
  fontSize: 12,
};

export default function Dashboard({ rangeStart, rangeEnd, onRangeChange }) {
  const [selectedStore, setSelectedStore] = useState("Tunisia Mall");
  const [periodeTransfo, setPeriodeTransfo] = useState("jour");
  const [periodePotentiel, setPeriodePotentiel] = useState("jour");

  // Données recalculées à chaque changement de magasin ou de date.
  // 💡 Quand l'API sera branchée, remplacer cet appel par un fetch :
  //    fetch(`/api/dashboard?magasin=${selectedStore}&date=${selectedDate.toISOString()}`)
  // 💡 Quand l'API sera branchée :
  //    fetch(`/api/dashboard?magasin=${selectedStore}&du=${rangeStart}&au=${rangeEnd}`)
  const { kpis, heureDePointe, tauxParHeure, evolutionJours, heatmapData, nbJours } =
    useMemo(() => getRangeData(selectedStore, rangeStart, rangeEnd), [selectedStore, rangeStart, rangeEnd]);

  const serieTransfo = useMemo(
    () => getKpiSeries(selectedStore, "transformation", periodeTransfo, rangeEnd),
    [selectedStore, periodeTransfo, rangeEnd]
  );
  const seriePotentiel = useMemo(
    () => getKpiSeries(selectedStore, "potentiel", periodePotentiel, rangeEnd),
    [selectedStore, periodePotentiel, rangeEnd]
  );

  const zoneStats = useMemo(
    () => getZoneStatsRange(selectedStore, rangeStart, rangeEnd),
    [selectedStore, rangeStart, rangeEnd]
  );
  const mapConfig = shopMaps[selectedStore];
  const periodLabel = `${fmtPeriodDate(rangeStart)} – ${fmtPeriodDate(rangeEnd)}`;

  return (
    <div>
      <Topbar
        title="Tableau de bord"
        stores={storeNames}
        selectedStore={selectedStore}
        onStoreChange={setSelectedStore}
        rangeStart={rangeStart}
        rangeEnd={rangeEnd}
        onRangeChange={onRangeChange}
      />

      {/* ---- KPI cards ---- */}
      <div className="kpi-row">
        {kpis.map((k) => {
          const Icon = kpiIcons[k.id];
          return (
            <div className="kpi-card" key={k.id}>
              <div className="kpi-icon"><Icon size={20} /></div>
              <div className="kpi-body">
                <div className="kpi-label">{k.label}</div>
                <div className="kpi-value">{k.value}</div>
                <span className={`kpi-delta ${k.up ? "up" : "down"}`}>
                  {k.up ? <ArrowUp size={11} /> : <ArrowDown size={11} />}
                  {k.delta} <span className="vs">vs période préc.</span>
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* ---- Charts ---- */}
      <div className="grid-charts">
        {/* Heure de pointe */}
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Heure de pointe</div>
              <div className="card-sub">Moyenne par heure sur la période</div>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={310}>
            <AreaChart data={heureDePointe} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="gradClients" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#96402e" stopOpacity={0.25} />
                  <stop offset="100%" stopColor="#96402e" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
              <XAxis dataKey="h" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} />
              <Area
                type="monotone" dataKey="clients" name="Clients"
                stroke="#96402e" strokeWidth={2}
                fill="url(#gradClients)"
                dot={{ r: 3, fill: "#96402e" }}
                activeDot={{ r: 5 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Taux PEC par heure */}
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Taux PEC par heure</div>
              <div className="card-sub">Moyenne par heure sur la période</div>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={310}>
            <LineChart data={tauxParHeure} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
              <XAxis dataKey="h" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => `${v}%`} />
              <Line
                type="monotone" dataKey="taux" name="Taux PEC"
                stroke="#c0392b" strokeWidth={2}
                dot={{ r: 3, fill: "#c0392b" }}
                activeDot={{ r: 5 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Évolution du taux PEC sur la période */}
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Évolution du taux PEC</div>
              <div className="card-sub">Jour par jour sur la période ({nbJours} jour{nbJours > 1 ? "s" : ""})</div>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={310}>
            <BarChart data={evolutionJours} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis domain={[50, 100]} unit="%" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${v}%`, "Taux PEC"]} />
              <Bar dataKey="taux" name="Taux PEC" fill="#96402e" radius={[4, 4, 0, 0]} barSize={18} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Heatmap */}
        <div className="card">
          <div className="card-head">
            <div className="card-title">Heatmap de présence clients</div>
          </div>
          <div className="card-sub" style={{ marginBottom: 10 }}>(par heure et jour)</div>
          <div className="heatmap">
            <div />
            {heatmapJours.map((j) => (
              <div key={j} className="hm-day">{j}</div>
            ))}
            {heatmapData.map((row, i) => (
              <HeatRow key={heatmapHeures[i]} heure={heatmapHeures[i]} row={row} />
            ))}
          </div>
          <div className="hm-legend">
            Faible <div className="bar" /> Élevé
          </div>
        </div>
        {/* Taux de transformation */}
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Taux de transformation</div>
              <div className="card-sub">Tickets caisse / visiteurs entrés (%)</div>
            </div>
            <select
              className="mini-select"
              value={periodeTransfo}
              onChange={(e) => setPeriodeTransfo(e.target.value)}
            >
              {PERIODES.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </div>
          <ResponsiveContainer width="100%" height={310}>
            <LineChart data={serieTransfo} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis unit="%" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} domain={[0, "auto"]} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${v}%`, "Taux de transformation"]} />
              <Line
                type="monotone" dataKey="value" name="Taux de transformation"
                stroke="#1e9e5a" strokeWidth={2}
                dot={{ r: 3, fill: "#1e9e5a" }}
                activeDot={{ r: 5 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Potentiel de revenu */}
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Potentiel de revenu</div>
              <div className="card-sub">Panier moyen × visiteurs (DT)</div>
            </div>
            <select
              className="mini-select"
              value={periodePotentiel}
              onChange={(e) => setPeriodePotentiel(e.target.value)}
            >
              {PERIODES.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </div>
          <ResponsiveContainer width="100%" height={310}>
            <BarChart data={seriePotentiel} margin={{ top: 5, right: 5, left: -8, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={fmtCompact} />
              <Tooltip
                contentStyle={tooltipStyle}
                formatter={(v) => [`${v.toLocaleString("fr-FR")} DT`, "Potentiel"]}
              />
              <Bar dataKey="value" name="Potentiel" fill="#96402e" radius={[4, 4, 0, 0]} barSize={22} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* ---- Carte de la boutique ---- */}
      <div className="card shop-map-card">
        <div className="card-head">
          <div>
            <div className="card-title">Carte de la boutique — zones d'affluence</div>
            <div className="card-sub">Comptage caméra par zone : pic de clients simultanés et prises en charge</div>
          </div>
        </div>
        {mapConfig ? (
          <ShopMap config={mapConfig} zoneStats={zoneStats} periodLabel={periodLabel} />
        ) : (
          <p className="empty-hint">Plan de la boutique bientôt disponible pour {selectedStore}.</p>
        )}
      </div>
    </div>
  );
}

function HeatRow({ heure, row }) {
  return (
    <>
      <div className="hm-label">{heure}</div>
      {row.map((v, i) => (
        <div key={i} className="hm-cell" style={{ background: heatColor(v) }} title={`${Math.round(v * 100)}%`} />
      ))}
    </>
  );
}
