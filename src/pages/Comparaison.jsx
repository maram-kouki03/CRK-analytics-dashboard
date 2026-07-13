import {
  BarChart, Bar, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import {
  Trophy, Handshake, Globe, Users, Clock,
} from "lucide-react";
import Topbar from "../components/Topbar";
import {
  bestCards, magasins, evolutionMultiMagasins, lineColors, conclusions,
} from "../data/mockData";

const bestIcons = { trophy: Trophy, handshake: Handshake, globe: Globe, users: Users, clock: Clock };

const tooltipStyle = {
  background: "#fff",
  border: "1px solid #f0e6df",
  borderRadius: 10,
  fontSize: 12,
};

// données triées pour les bar charts
const parTaux = [...magasins].sort((a, b) => b.taux - a.taux);
const parClients = [...magasins].sort((a, b) => b.clients - a.clients);
const parTemps = [...magasins].sort((a, b) => a.temps - b.temps);

export default function Comparaison() {
  return (
    <div>
      <Topbar
        title="Comparaison des 8 magasins"
        dateLabel="7 derniers jours"
        storeLabel="Tous les magasins"
      />

      {/* ---- Meilleurs magasins ---- */}
      <div className="best-row">
        {bestCards.map((b) => {
          const Icon = bestIcons[b.icon];
          return (
            <div className="best-card" key={b.label}>
              <Icon size={22} className="best-icon" />
              <div>
                <div className="best-label">{b.label}</div>
                <div className="best-store">{b.store}</div>
                <div className="best-value">{b.value}</div>
              </div>
            </div>
          );
        })}
      </div>

      {/* ---- Rangée 1 : tableau + 2 bar charts ---- */}
      <div className="compare-grid">
        <div className="card">
          <div className="card-head">
            <div className="card-title">Performances par magasin</div>
          </div>
          <table className="perf">
            <thead>
              <tr>
                <th>#</th><th>Magasin</th><th>Clients entrés</th><th>Nombre de PEC</th>
                <th>Taux PEC</th><th>Vendeurs actifs</th><th>Temps moyen avant PEC</th>
              </tr>
            </thead>
            <tbody>
              {magasins.map((m) => (
                <tr key={m.nom}>
                  <td>{m.rang}</td>
                  <td>{m.nom}</td>
                  <td>{m.clients.toLocaleString("fr-FR")}</td>
                  <td>{m.pec.toLocaleString("fr-FR")}</td>
                  <td>
                    <span className={`rate-badge ${m.taux >= 78 ? "good" : "bad"}`}>
                      {m.taux.toFixed(1).replace(".", ",")}%
                    </span>
                  </td>
                  <td>{m.vendeurs}</td>
                  <td>{m.temps} s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <div className="card-head">
            <div className="card-title">Taux PEC par magasin (%)</div>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={parTaux} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
              <XAxis dataKey="nom" tick={{ fontSize: 9 }} tickLine={false} axisLine={false} interval={0} angle={-25} textAnchor="end" height={50} />
              <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => `${v}%`} />
              <Bar dataKey="taux" name="Taux PEC" fill="#96402e" radius={[4, 4, 0, 0]} barSize={22} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <div className="card-head">
            <div className="card-title">Clients entrés par magasin</div>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={parClients} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
              <XAxis dataKey="nom" tick={{ fontSize: 9 }} tickLine={false} axisLine={false} interval={0} angle={-25} textAnchor="end" height={50} />
              <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar dataKey="clients" name="Clients entrés" fill="#96402e" radius={[4, 4, 0, 0]} barSize={22} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* ---- Rangée 2 : multi-lignes + temps moyen + conclusion ---- */}
      <div className="compare-grid-2">
        <div className="card">
          <div className="card-head">
            <div className="card-title">Évolution du taux PEC (hebdomadaire)</div>
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={evolutionMultiMagasins} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
              <XAxis dataKey="jour" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis domain={[50, 100]} unit="%" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => `${v}%`} />
              <Legend wrapperStyle={{ fontSize: 10.5 }} />
              {Object.entries(lineColors).map(([nom, color]) => (
                <Line
                  key={nom} type="monotone" dataKey={nom}
                  stroke={color} strokeWidth={1.6}
                  dot={{ r: 2.5 }} activeDot={{ r: 4 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <div className="card-head">
            <div className="card-title">Temps moyen avant PEC par magasin (s)</div>
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={parTemps} layout="vertical" margin={{ top: 5, right: 30, left: 10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" horizontal={false} />
              <XAxis type="number" domain={[0, 30]} tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="nom" width={70} tick={{ fontSize: 10.5 }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => `${v} s`} />
              <Bar dataKey="temps" name="Temps moyen (s)" fill="#96402e" radius={[0, 4, 4, 0]} barSize={13} label={{ position: "right", fontSize: 10, formatter: (v) => `${v} s` }} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <div className="card-head">
            <div className="card-title">Conclusion</div>
          </div>
          {conclusions.map((c) => {
            const Icon = bestIcons[c.icon];
            return (
              <div className="conclusion-item" key={c.label}>
                <Icon size={17} className="ci-icon" />
                <div><b>{c.label}</b><span>{c.detail}</span></div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
