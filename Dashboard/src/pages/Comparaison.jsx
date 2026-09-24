import {
  BarChart, Bar, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { Trophy, Handshake, Globe, Radio } from "lucide-react";
import Topbar from "../components/Topbar";
import { ErrorBlock, NoDataBlock, PageLoader } from "../components/States";
import { fetchComparison } from "../api/client";
import { useApi } from "../api/useApi";
import { fmtInt, fmtNum, fmtPct, fmtRange, MISSING } from "../lib/format";
import { storeColor } from "../data/storeColors";

const bestIcons = { trophy: Trophy, handshake: Handshake, globe: Globe, radio: Radio };

const tooltipStyle = {
  background: "#fff",
  border: "1px solid #f0e6df",
  borderRadius: 10,
  fontSize: 12,
};

/** Magasin qui maximise `key`, en ignorant ceux sans mesure. */
function bestBy(magasins, key) {
  const candidats = magasins.filter((m) => m[key] !== null && m[key] !== undefined);
  if (candidats.length === 0) return null;
  return candidats.reduce((a, b) => (b[key] > a[key] ? b : a));
}

export default function Comparaison({ rangeStart, rangeEnd }) {
  const { data, error, loading } = useApi(
    () => fetchComparison(rangeStart, rangeEnd),
    [rangeStart, rangeEnd]
  );

  if (error) return <ErrorBlock error={error} onRetry={() => window.location.reload()} />;
  if (!data) return loading ? <PageLoader /> : null;

  const { magasins, evolutionJours } = data;
  const actifs = magasins.filter((m) => m.aDonnees);
  // Un magasin peut avoir des événements sans une seule entrée comptée : son taux
  // PEC est alors null. Les classements sur le taux doivent l'ignorer.
  const avecTaux = actifs.filter((m) => m.taux_pec !== null);

  // Classement sur les clients entrés, magasins sans flux relégués à la fin.
  const classement = [...magasins]
    .sort((a, b) => Number(b.aDonnees) - Number(a.aDonnees) || b.clients_entres - a.clients_entres)
    .map((m, i) => ({ ...m, rang: m.aDonnees ? i + 1 : null }));

  const bTaux = bestBy(actifs, "taux_pec");
  const bPec = bestBy(actifs, "pec_count");
  const bClients = bestBy(actifs, "clients_entres");

  const bestCards = [
    bTaux && { label: "Meilleur taux PEC", store: bTaux.nom, value: fmtPct(bTaux.taux_pec), icon: "trophy" },
    bPec && { label: "Plus de PEC", store: bPec.nom, value: fmtInt(bPec.pec_count), icon: "handshake" },
    bClients && { label: "Plus de clients entrés", store: bClients.nom, value: fmtInt(bClients.clients_entres), icon: "globe" },
    {
      label: "Magasins connectés",
      store: `${actifs.length} sur ${magasins.length}`,
      value: actifs.length === magasins.length ? "complet" : "partiel",
      icon: "radio",
    },
  ].filter(Boolean);

  // Une courbe par magasin ayant des données : tracer les 8 rendrait la légende
  // illisible pour des lignes vides.
  const courbes = actifs.map((m, i) => ({ nom: m.nom, color: storeColor(m.nom, i) }));

  return (
    <div>
      <Topbar
        title={`Comparaison des ${magasins.length} magasins`}
        storeLabel="Tous les magasins"
        rangeStart={rangeStart}
        rangeEnd={rangeEnd}
      />

      {actifs.length === 0 && (
        <NoDataBlock>
          Aucun des {magasins.length} magasins n'a envoyé d'événement sur cette période.
        </NoDataBlock>
      )}

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
            <div>
              <div className="card-title">Performances par magasin</div>
              <div className="card-sub">
                {fmtRange(rangeStart, rangeEnd)} · {data.periode.nbJours} jour
                {data.periode.nbJours > 1 ? "s" : ""}
              </div>
            </div>
          </div>
          <table className="perf">
            <thead>
              <tr>
                <th>#</th><th>Magasin</th><th>Clients entrés</th><th>Nombre de PEC</th>
                <th>Taux PEC</th>
              </tr>
            </thead>
            <tbody>
              {classement.map((m) => (
                <tr key={m.nom} className={m.aDonnees ? undefined : "row-muted"}>
                  <td>{m.rang ?? MISSING}</td>
                  <td>
                    {m.nom}
                    {/* `aDonnees` est ici relatif à la période affichée, alors que le
                        « aucun flux » du sélecteur de magasin porte sur tout l'historique. */}
                    {!m.aDonnees && <span className="store-flag">sans données</span>}
                  </td>
                  <td>{m.aDonnees ? fmtInt(m.clients_entres) : MISSING}</td>
                  <td>{m.aDonnees ? fmtInt(m.pec_count) : MISSING}</td>
                  <td>
                    {m.taux_pec === null ? MISSING : (
                      // Au-delà de 100 % il y a plus de PEC comptées que de clients
                      // entrés : c'est une anomalie de mesure, surtout pas un score vert.
                      <span
                        className={`rate-badge ${
                          m.taux_pec > 100 ? "anomaly" : m.taux_pec >= 78 ? "good" : "bad"
                        }`}
                        title={m.taux_pec > 100 ? "Plus de PEC que de clients entrés — mesure à vérifier" : undefined}
                      >
                        {fmtPct(m.taux_pec)}
                      </span>
                    )}
                  </td>
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
            <BarChart
              data={[...avecTaux].sort((a, b) => b.taux_pec - a.taux_pec)}
              margin={{ top: 5, right: 5, left: -12, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
              <XAxis dataKey="nom" tick={{ fontSize: 9 }} tickLine={false} axisLine={false} interval={0} angle={-25} textAnchor="end" height={50} />
              <YAxis unit="%" domain={[0, "auto"]} tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmtPct(v)} />
              <Bar dataKey="taux_pec" name="Taux PEC" fill="#96402e" radius={[4, 4, 0, 0]} barSize={22} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <div className="card-head">
            <div className="card-title">Clients entrés par magasin</div>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart
              data={[...actifs].sort((a, b) => b.clients_entres - a.clients_entres)}
              margin={{ top: 5, right: 5, left: -12, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
              <XAxis dataKey="nom" tick={{ fontSize: 9 }} tickLine={false} axisLine={false} interval={0} angle={-25} textAnchor="end" height={50} />
              <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmtInt(v)} />
              <Bar dataKey="clients_entres" name="Clients entrés" fill="#96402e" radius={[4, 4, 0, 0]} barSize={22} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* ---- Rangée 2 : multi-lignes + conclusion ---- */}
      <div className="compare-grid-2">
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Évolution du taux PEC sur la période</div>
              <div className="card-sub">Une courbe par magasin connecté</div>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={evolutionJours} margin={{ top: 5, right: 5, left: -12, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0e6df" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis unit="%" domain={[0, "auto"]} tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmtPct(v)} />
              <Legend wrapperStyle={{ fontSize: 10.5 }} />
              {courbes.map(({ nom, color }) => (
                <Line
                  key={nom} type="monotone" dataKey={nom}
                  stroke={color} strokeWidth={1.6}
                  dot={{ r: 2.5 }} activeDot={{ r: 4 }}
                  connectNulls={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <div className="card-head">
            <div className="card-title">Conclusion</div>
          </div>
          {actifs.length === 0 ? (
            <p className="empty-hint">Rien à conclure : aucun magasin n'a de données sur la période.</p>
          ) : (
            <>
              {bTaux && (
                <Conclusion icon={Trophy} label="Meilleur taux PEC" detail={`${bTaux.nom} (${fmtPct(bTaux.taux_pec)})`} />
              )}
              <Conclusion icon={Handshake} label="Plus de PEC" detail={`${bPec.nom} (${fmtInt(bPec.pec_count)})`} />
              <Conclusion icon={Globe} label="Plus de clients entrés" detail={`${bClients.nom} (${fmtInt(bClients.clients_entres)})`} />
              <Conclusion
                icon={Radio}
                label="Couverture des mesures"
                detail={
                  actifs.length === magasins.length
                    ? `Les ${magasins.length} magasins remontent des événements.`
                    : `${magasins.length - actifs.length} magasin(s) sans données sur la période : ` +
                      `${magasins.filter((m) => !m.aDonnees).map((m) => m.nom).join(", ")}. ` +
                      "Le classement ne porte donc que sur " +
                      `${actifs.length} magasin${actifs.length > 1 ? "s" : ""}.`
                }
              />
              <Conclusion
                icon={Trophy}
                label="Clients / jour (moy.)"
                detail={actifs
                  .map((m) => `${m.nom} : ${fmtNum(m.clients_par_jour)}`)
                  .join(" · ")}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Conclusion({ icon: Icon, label, detail }) {
  return (
    <div className="conclusion-item">
      <Icon size={17} className="ci-icon" />
      <div><b>{label}</b><span>{detail}</span></div>
    </div>
  );
}
