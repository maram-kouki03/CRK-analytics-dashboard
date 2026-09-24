import {
  BarChart, Bar, LineChart, Line, ReferenceLine,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { AlertTriangle } from "lucide-react";
import { fmtDT, fmtInt, fmtPct } from "../lib/format";

// L'axe affiche « 11h » faute de place, mais la valeur couvre 11h00-11h59.
// L'infobulle ecrit la tranche en entier : « 11h » seul se lit comme un instant.
const trancheHoraire = (label) => {
  const debut = parseInt(label, 10);
  return Number.isNaN(debut) ? label : `${label} – ${String(debut + 1).padStart(2, "0")}h`;
};

// Axe en dinars : « 1,2k » plutot que « 1200 », sinon l'axe mange la moitie du
// graphe des que les montants depassent le millier.
const fmtCompactDT = (v) =>
  v >= 1000 ? `${(v / 1000).toFixed(1).replace(".", ",")}k` : Math.round(v);

const tooltipHoraire = {
  background: "#fff",
  border: "1px solid #f0e6df",
  borderRadius: 10,
  fontSize: 12,
};

// ============================================================
// Bloc « Ventes & potentiel » — spec CRK_Dashboard_Sales_Potential_KPIs.pdf
// ============================================================

/**
 * Provenance des chiffres de caisse. Deux avertissements possibles, jamais les
 * deux à la fois :
 *   · simulation en cours (API Joolan pas encore branchée) ;
 *   · Joolan branché mais des journées manquantes — le CA est alors sous-évalué,
 *     et sans ce message rien ne l'expliquerait à l'écran.
 */
export function SimulationBanner({ ventes }) {
  if (!ventes) return null;

  if (ventes.simule) {
    return (
      <div className="sim-banner">
        <AlertTriangle size={18} />
        <div>
          <b>Données caisse simulées</b>
          <span>
            L'API de la caisse n'est pas encore branchée : les <b>tickets</b> et le{" "}
            <b>chiffre d'affaires</b> ci-dessous sont des valeurs de démonstration.
            Les <b>visiteurs</b> et les <b>prises en charge</b>, eux, sont bien mesurés
            par le boîtier.
          </span>
        </div>
      </div>
    );
  }

  const manquants = ventes.joursManquants ?? [];
  if (manquants.length === 0) return null;

  return (
    <div className="sim-banner">
      <AlertTriangle size={18} />
      <div>
        <b>
          Caisse indisponible sur {manquants.length} jour
          {manquants.length > 1 ? "s" : ""}
        </b>
        <span>
          Joolan n'a pas répondu pour : <b>{manquants.join(", ")}</b>. Les tickets
          et le chiffre d'affaires de ces journées manquent, donc le CA, le panier
          moyen et le taux de captation sont <b>sous-évalués</b>. Les visiteurs et
          les prises en charge ne sont pas concernés.
        </span>
      </div>
    </div>
  );
}

/**
 * Entonnoir : Visiteurs → Pris en charge → Tickets → Chiffre d'affaires.
 *
 * Chaque taux est placé SOUS le niveau qu'il produit : « taux de prise en charge »
 * sous Pris en charge, « taux de conversion » sous Tickets. Le premier niveau
 * (Visiteurs) et le dernier (CA) n'ont donc rien en dessous.
 */
export function FunnelCard({ ventes, cumulLabel }) {
  const {
    visiteurs, pris_en_charge, tickets, revenue,
    pec_rate, conversion_rate, average_basket, simule,
  } = ventes;

  // Échelle commune aux seuls VOLUMES (personnes / tickets). Le chiffre d'affaires
  // est en dinars : lui donner une barre sur la même échelle comparerait des
  // dinars à des personnes, ce qui ne veut rien dire. Il est donc présenté comme
  // une ligne de total, sans barre.
  const maxVolume = Math.max(visiteurs, pris_en_charge, tickets, 1);
  const largeur = (v) => `${Math.max(2, (v / maxVolume) * 100)}%`;

  const niveaux = [
    { cle: "V", label: "Visiteurs", valeur: visiteurs, couleur: "#96402e" },
    {
      cle: "A", label: "Pris en charge", valeur: pris_en_charge, couleur: "#c0673f",
      taux: pec_rate, tauxLabel: "taux de prise en charge",
    },
    {
      cle: "T", label: "Tickets", valeur: tickets, couleur: "#1e9e5a", simule,
      taux: conversion_rate, tauxLabel: "taux de conversion",
    },
  ];

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">Entonnoir de conversion</div>
          <div className="card-sub">
            Du visiteur au chiffre d'affaires — <b>{cumulLabel}</b>
          </div>
        </div>
      </div>

      <div className="funnel">
        {niveaux.map((n) => (
          <div key={n.cle} className="funnel-level">
            <div className="funnel-row">
              <span className="funnel-label">
                {n.label}
                {n.simule && <span className="funnel-sim">simulé</span>}
              </span>
              <span className="funnel-value">{fmtInt(n.valeur)}</span>
            </div>
            <div className="funnel-bar-track">
              <div className="funnel-bar" style={{ width: largeur(n.valeur), background: n.couleur }} />
            </div>
            {n.taux !== undefined && (
              <div className="funnel-step">
                <b>{fmtPct(n.taux)}</b>
                <span>{n.tauxLabel}</span>
              </div>
            )}
          </div>
        ))}

        {/* Dernier niveau : montant, donc pas de barre et rien en dessous. */}
        <div className="funnel-level funnel-total">
          <div className="funnel-row">
            <span className="funnel-label">
              Chiffre d'affaires
              {simule && <span className="funnel-sim">simulé</span>}
            </span>
            <span className="funnel-value">{fmtDT(revenue)}</span>
          </div>
        </div>
      </div>

      <div className="funnel-foot">
        <span className="ff-label">Panier moyen</span>
        <span className="ff-value">{fmtDT(average_basket, 2)}</span>
        <code>CA / tickets</code>
      </div>
    </div>
  );
}

/** Titre de section, pour séparer ce qui est mesuré de ce qui vient de la caisse. */
export function SectionHead({ title, sub, action }) {
  return (
    <div className="section-head">
      <h2>{title}</h2>
      {sub && <span>{sub}</span>}
      {action && <div className="section-head-action">{action}</div>}
    </div>
  );
}

// Objectif de conversion : de 0 à 100 % par pas de 5.
const OBJECTIFS = Array.from({ length: 21 }, (_, i) => i * 5);

/**
 * Sélecteur de l'objectif de conversion visé.
 *
 * C'est le CR_target de la spec : une HYPOTHÈSE, pas une mesure. Le déplacer
 * recalcule le potentiel de vente, le manque à gagner et le taux de captation —
 * et rien d'autre. Les visiteurs, les prises en charge, les tickets et le CA ne
 * bougent pas d'un point : ils sont mesurés.
 */
export function ObjectifPicker({ value, onChange }) {
  return (
    <label className="objectif-picker">
      <span>Objectif de conversion</span>
      <select
        className="mini-select"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      >
        {OBJECTIFS.map((o) => (
          <option key={o} value={o}>{o} %</option>
        ))}
      </select>
    </label>
  );
}

// ============================================================
// Les mêmes indicateurs, tranche horaire par tranche horaire.
//
// Le potentiel d'une heure suit la formule de la spec appliquée aux visiteurs
// de CETTE heure : V(h) x objectif x panier de référence. La somme des heures
// est donc exactement le potentiel de la période — aucune approximation.
// ============================================================

const axeStyle = { fontSize: 10 };
const grille = { strokeDasharray: "3 3", stroke: "#f0e6df", vertical: false };

/**
 * Enveloppe commune des graphes horaires.
 *
 * Chaque graphe porte SON total de periode juste au-dessus de sa ventilation :
 * le chiffre cumule et le detail heure par heure se lisent au meme endroit,
 * sans carte separee. La somme des barres est exactement ce total.
 */
function HourlyCard({ title, sub, total, totalLabel, cumulLabel, detail, formule, data, children }) {
  const vide = !data || data.length === 0;
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">{title}</div>
          <div className="card-sub">{sub}</div>
        </div>
        {formule && <code className="hour-formula">{formule}</code>}
      </div>

      {total !== undefined && (
        <div className="pot-hero">
          <div className="pot-hero-value">{total}</div>
          <div className="pot-hero-label">
            {totalLabel}{cumulLabel ? ` — ${cumulLabel}` : ""}
          </div>
          {/* Le calcul juste sous le nombre : un total qu'on ne peut pas
              reconstituer n'est ni verifiable ni exploitable. */}
          {detail && <div className="pot-hero-formula">{detail}</div>}
        </div>
      )}

      {vide ? (
        <p className="empty-hint">Aucune donnée sur cette période.</p>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          {children}
        </ResponsiveContainer>
      )}
    </div>
  );
}

/** Potentiel de vente par heure, avec le CA réalisé en regard. */
export function PotentialHourlyCard({ ventes, cumulLabel }) {
  const data = ventes?.parHeure ?? [];
  const visiteurs = ventes?.visiteurs;
  return (
    <HourlyCard
      title="Potentiel de vente"
      sub="Ce que chaque tranche aurait pu générer, face au CA réellement encaissé"
      total={fmtDT(ventes?.sales_potential)}
      totalLabel="potentiel estimé"
      cumulLabel={cumulLabel}
      detail={
        visiteurs
          ? `${fmtInt(visiteurs)} visiteurs × ${fmtPct(ventes?.cr_target_pct, 0)} (objectif) × ${fmtDT(ventes?.ab_reference)} (panier de référence)`
          : null
      }
      data={data}
    >
      <BarChart data={data} margin={{ top: 5, right: 5, left: -8, bottom: 0 }}>
        <CartesianGrid {...grille} />
        <XAxis dataKey="h" tick={axeStyle} tickLine={false} axisLine={false} />
        <YAxis tick={axeStyle} tickLine={false} axisLine={false} tickFormatter={fmtCompactDT} />
        <Tooltip
          contentStyle={tooltipHoraire}
          labelFormatter={trancheHoraire}
          formatter={(v, n) => [fmtDT(v), n]}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {/* Le potentiel en fond clair, le réalisé par-dessus : l'écart entre les
            deux barres EST le manque à gagner, sans avoir à le calculer. */}
        <Bar dataKey="potentiel" name="Potentiel" fill="#e0cdc2" radius={[4, 4, 0, 0]} />
        <Bar dataKey="revenue" name="CA réalisé" fill="#1e9e5a" radius={[4, 4, 0, 0]} />
      </BarChart>
    </HourlyCard>
  );
}

/** Manque à gagner par heure : là où l'écart se creuse. */
export function GapHourlyCard({ ventes, cumulLabel }) {
  const data = ventes?.parHeure ?? [];
  return (
    <HourlyCard
      title="Manque à gagner"
      sub="Potentiel non converti — une heure excédentaire ne compense pas les autres"
      total={fmtDT(ventes?.opportunity_gap)}
      totalLabel="manque à gagner"
      cumulLabel={cumulLabel}
      formule="max(potentiel − CA, 0)"
      data={data}
    >
      <BarChart data={data} margin={{ top: 5, right: 5, left: -8, bottom: 0 }}>
        <CartesianGrid {...grille} />
        <XAxis dataKey="h" tick={axeStyle} tickLine={false} axisLine={false} />
        <YAxis tick={axeStyle} tickLine={false} axisLine={false} tickFormatter={fmtCompactDT} />
        <Tooltip
          contentStyle={tooltipHoraire}
          labelFormatter={trancheHoraire}
          formatter={(v) => [fmtDT(v), "Manque à gagner"]}
        />
        <Bar dataKey="manque" name="Manque à gagner" fill="#c0673f" radius={[4, 4, 0, 0]} />
      </BarChart>
    </HourlyCard>
  );
}

/** Taux de captation (efficacité) par heure, avec le repère des 100 %. */
export function CaptureHourlyCard({ ventes, cumulLabel }) {
  const data = ventes?.parHeure ?? [];
  return (
    <HourlyCard
      title="Taux de captation"
      sub="Part du potentiel réellement encaissée — l'efficacité de la boutique"
      total={fmtPct(ventes?.opportunity_capture_rate)}
      totalLabel="taux de captation"
      cumulLabel={cumulLabel}
      formule="CA / potentiel"
      data={data}
    >
      <LineChart data={data} margin={{ top: 5, right: 5, left: -12, bottom: 0 }}>
        <CartesianGrid {...grille} />
        <XAxis dataKey="h" tick={axeStyle} tickLine={false} axisLine={false} />
        <YAxis unit="%" domain={[0, "auto"]} tick={axeStyle} tickLine={false} axisLine={false} />
        <Tooltip
          contentStyle={tooltipHoraire}
          labelFormatter={trancheHoraire}
          formatter={(v) => [fmtPct(v), "Taux de captation"]}
        />
        {/* 100 % = l'objectif atteint. Au-dessus, l'heure a fait mieux que visé. */}
        <ReferenceLine y={100} stroke="#96402e" strokeDasharray="4 4"
          label={{ value: "objectif", position: "insideTopRight", fontSize: 10, fill: "#96402e" }} />
        <Line
          type="monotone" dataKey="captation" name="Taux de captation"
          stroke="#96402e" strokeWidth={2}
          dot={{ r: 3, fill: "#96402e" }} activeDot={{ r: 5 }}
          connectNulls={false}
        />
      </LineChart>
    </HourlyCard>
  );
}

/**
 * Taux de conversion par heure : tickets / visiteurs de la tranche.
 *
 * À lire à côté de la captation, pas à sa place. La captation compare le CA à
 * un objectif que l'on a choisi ; la conversion, elle, ne compare rien — c'est
 * la part brute des visiteurs qui sont repartis avec un ticket. Une heure peut
 * très bien mal capter tout en convertissant normalement, si l'objectif est
 * simplement placé haut.
 *
 * Les deux chiffres viennent de sources différentes — tickets de la caisse,
 * visiteurs du boîtier — donc une heure peut afficher des ventes sans visiteur
 * ou l'inverse. On ne corrige rien : c'est précisément ce qu'il faut voir.
 */
export function ConversionHourlyCard({ ventes, cumulLabel }) {
  const data = ventes?.parHeure ?? [];
  const objectif = ventes?.cr_target_pct;
  return (
    <HourlyCard
      title="Taux de conversion par heure"
      sub="Part des visiteurs repartis avec un ticket, tranche par tranche"
      total={fmtPct(ventes?.conversion_rate)}
      totalLabel="taux de conversion"
      cumulLabel={cumulLabel}
      detail={`${fmtInt(ventes?.tickets)} tickets / ${fmtInt(ventes?.visiteurs)} visiteurs`}
      formule="tickets / visiteurs"
      data={data}
    >
      <LineChart data={data} margin={{ top: 5, right: 5, left: -12, bottom: 0 }}>
        <CartesianGrid {...grille} />
        <XAxis dataKey="h" tick={axeStyle} tickLine={false} axisLine={false} />
        <YAxis unit="%" domain={[0, "auto"]} tick={axeStyle} tickLine={false} axisLine={false} />
        <Tooltip
          contentStyle={tooltipHoraire}
          labelFormatter={trancheHoraire}
          formatter={(v) => [fmtPct(v), "Taux de conversion"]}
        />
        {/* L'objectif choisi, en repère : l'écart vertical à cette ligne est
            exactement ce que mesure le taux de captation. */}
        {objectif > 0 && (
          <ReferenceLine
            y={objectif} stroke="#96402e" strokeDasharray="4 4"
            label={{
              value: `objectif ${objectif} %`,
              position: "insideTopRight", fontSize: 10, fill: "#96402e",
            }}
          />
        )}
        <Line
          type="monotone" dataKey="conversion" name="Taux de conversion"
          stroke="#2f6d5b" strokeWidth={2}
          dot={{ r: 3, fill: "#2f6d5b" }} activeDot={{ r: 5 }}
          connectNulls={false}
        />
      </LineChart>
    </HourlyCard>
  );
}
