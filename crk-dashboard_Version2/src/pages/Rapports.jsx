import { useState, useRef, useEffect } from "react";
import {
  Calendar as CalendarIcon, ChevronDown, Check, Store,
  FileText, Download, CheckCircle2, X, Loader2,
} from "lucide-react";
import Calendar from "../components/Calendar";
import { storeNames } from "../data/mockData";
import {
  buildReportPayload, generateReport, reportHtmlDocument,
} from "../report/generateReport";

const MOIS_COURT = [
  "Jan", "Fév", "Mars", "Avr", "Mai", "Juin",
  "Juil", "Août", "Sept", "Oct", "Nov", "Déc",
];

const fmtDate = (d) => `${String(d.getDate()).padStart(2, "0")} ${MOIS_COURT[d.getMonth()]} ${d.getFullYear()}`;
const fmtDateTime = (d) =>
  `${fmtDate(d)} à ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

const STORAGE_KEY = "crk-rapports";

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || [];
  } catch {
    return [];
  }
}

function useClickOutside(ref, onClose) {
  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [ref, onClose]);
}

// génère et télécharge le PDF depuis le markdown stocké
async function downloadPdf(rapport) {
  const html2pdf = (await import("html2pdf.js")).default;

  // html2pdf clone le nœud passé à .from() tel quel (styles inline inclus) et le
  // réinsère dans son propre conteneur à hauteur automatique : si ce nœud est lui-même
  // en position absolute/fixed, il sort du flux et la hauteur du conteneur s'effondre
  // à 0 → PDF blanc. On garde donc `el` en position statique et on masque ce contenu
  // à l'écran via un wrapper externe (non cloné par html2pdf, qui ne clone que `el`).
  const wrapper = document.createElement("div");
  wrapper.style.position = "fixed";
  wrapper.style.top = "0";
  wrapper.style.left = "-10000px";
  wrapper.style.zIndex = "-1";

  const el = document.createElement("div");
  el.style.width = "690px";
  el.style.background = "#fff";
  el.innerHTML = reportHtmlDocument(rapport.markdown, rapport.magasin, rapport.periodeLabel);
  wrapper.appendChild(el);
  document.body.appendChild(wrapper);
  try {
    // laisse le navigateur peindre le contenu injecté avant la capture
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

    if (el.offsetHeight === 0) {
      throw new Error("Le conteneur du rapport a une hauteur nulle, la capture PDF serait vide.");
    }

    await html2pdf()
      .set({
        margin: [12, 12, 14, 12],
        filename: rapport.fichier,
        image: { type: "jpeg", quality: 0.95 },
        html2canvas: { scale: 2, useCORS: true },
        jsPDF: { unit: "mm", format: "a4", orientation: "portrait" },
        pagebreak: { mode: ["css", "legacy"] },
      })
      .from(el)
      .save();
  } finally {
    document.body.removeChild(wrapper);
  }
}

export default function Rapports() {
  // sélection
  const [start, setStart] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 6); return d;
  });
  const [end, setEnd] = useState(new Date());
  const [store, setStore] = useState(storeNames[0]);

  // popovers
  const [dateOpen, setDateOpen] = useState(false);
  const [storeOpen, setStoreOpen] = useState(false);
  const dateRef = useRef(null);
  const storeRef = useRef(null);
  useClickOutside(dateRef, () => setDateOpen(false));
  useClickOutside(storeRef, () => setStoreOpen(false));

  // génération + historique + notification
  const [generating, setGenerating] = useState(false);
  const [history, setHistory] = useState(loadHistory);
  const [toast, setToast] = useState(null); // { type: "ok"|"err", title, message }

  const saveHistory = (list) => {
    setHistory(list);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(list)); } catch { /* plein : tant pis */ }
  };

  const showToast = (t) => {
    setToast(t);
    setTimeout(() => setToast(null), 7000);
  };

  const periodeLabel = `${fmtDate(start)} – ${fmtDate(end)}`;

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const payload = buildReportPayload(store, start, end);
      const markdown = await generateReport(payload);

      const slug = store.toLowerCase().replace(/\s+/g, "-");
      const rapport = {
        id: Date.now(),
        nom: "Rapport d'analyse",
        description: "Analyse KPI et recommandations",
        magasin: store,
        periodeLabel,
        dateGen: new Date().toISOString(),
        statut: "Terminé",
        fichier: `Rapport_${slug}_${payload.periode.du}_${payload.periode.au}.pdf`,
        markdown,
      };

      saveHistory([rapport, ...history]);
      await downloadPdf(rapport);

      showToast({
        type: "ok",
        title: "Rapport généré avec succès",
        message: `Le rapport « ${store} — ${periodeLabel} » a été téléchargé en PDF sur votre poste.`,
      });
    } catch (e) {
      showToast({ type: "err", title: "Échec de la génération", message: e.message });
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div>
      <header className="topbar">
        <div>
          <h1>Rapports</h1>
          <p className="page-sub">Générez et téléchargez des rapports personnalisés</p>
        </div>
        <div className="topbar-right">
          <div className="avatar">CRK</div>
        </div>
      </header>

      {/* ---- Générer un rapport ---- */}
      <div className="card report-form">
        <div className="card-title" style={{ marginBottom: 14 }}>Générer un rapport</div>
        <div className="report-form-row">
          <div className="report-field">
            <label>Période</label>
            <div className="popover-wrap" ref={dateRef}>
              <button
                className={`select-pill wide${dateOpen ? " open" : ""}`}
                onClick={() => { setDateOpen(!dateOpen); setStoreOpen(false); }}
              >
                <CalendarIcon size={15} />
                {fmtDate(start)} <span className="arrow">→</span> {fmtDate(end)}
                <ChevronDown size={14} />
              </button>
              {dateOpen && (
                <div className="popover left">
                  <Calendar
                    initialStart={start}
                    initialEnd={end}
                    onApply={(s, e) => { setStart(s); setEnd(e); setDateOpen(false); }}
                  />
                </div>
              )}
            </div>
          </div>

          <div className="report-field">
            <label>Magasin</label>
            <div className="popover-wrap" ref={storeRef}>
              <button
                className={`select-pill wide${storeOpen ? " open" : ""}`}
                onClick={() => { setStoreOpen(!storeOpen); setDateOpen(false); }}
              >
                {store}
                <ChevronDown size={14} />
              </button>
              {storeOpen && (
                <div className="popover store-list left">
                  {storeNames.map((s) => (
                    <button
                      key={s}
                      className={`store-option${s === store ? " selected" : ""}`}
                      onClick={() => { setStore(s); setStoreOpen(false); }}
                    >
                      <Store size={14} />
                      {s}
                      {s === store && <Check size={14} className="check" />}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          <button className="btn-generate" onClick={handleGenerate} disabled={generating}>
            {generating
              ? <><Loader2 size={16} className="spin" /> Génération en cours…</>
              : <><FileText size={16} /> Générer le rapport</>}
          </button>
        </div>
      </div>

      {/* ---- Rapports générés ---- */}
      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title" style={{ marginBottom: 12 }}>Rapports générés</div>
        {history.length === 0 ? (
          <p className="empty-hint">Aucun rapport pour l'instant — sélectionne une période et un magasin, puis clique sur « Générer le rapport ».</p>
        ) : (
          <table className="perf reports-table">
            <thead>
              <tr>
                <th>Nom du rapport</th><th>Période</th><th>Magasin</th>
                <th>Date de génération</th><th>Statut</th><th>Téléchargement</th>
              </tr>
            </thead>
            <tbody>
              {history.map((r) => (
                <tr key={r.id}>
                  <td>
                    <div className="report-name">{r.nom}</div>
                    <div className="report-desc">{r.description}</div>
                  </td>
                  <td>{r.periodeLabel}</td>
                  <td>{r.magasin}</td>
                  <td>{fmtDateTime(new Date(r.dateGen))}</td>
                  <td><span className="rate-badge good">{r.statut}</span></td>
                  <td>
                    <button className="btn-download" onClick={() => downloadPdf(r)}>
                      <Download size={14} /> Télécharger PDF
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ---- Notification ---- */}
      {toast && (
        <div className={`toast ${toast.type}`}>
          <CheckCircle2 size={22} className="toast-icon" />
          <div className="toast-body">
            <div className="toast-title">{toast.title}</div>
            <div className="toast-msg">{toast.message}</div>
            <div className="toast-time">il y a quelques secondes</div>
          </div>
          <button className="toast-close" onClick={() => setToast(null)}><X size={15} /></button>
        </div>
      )}
    </div>
  );
}
