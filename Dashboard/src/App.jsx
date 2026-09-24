import { useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Dashboard from "./pages/Dashboard";
import Comparaison from "./pages/Comparaison";
import Rapports from "./pages/Rapports";

export default function App() {
  const [collapsed, setCollapsed] = useState(false);

  // période partagée entre Vue d'ensemble et Comparaison
  // période par défaut : les 7 derniers jours
  const [rangeStart, setRangeStart] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 6); return d;
  });
  const [rangeEnd, setRangeEnd] = useState(new Date());
  const onRangeChange = (s, e) => { setRangeStart(s); setRangeEnd(e); };

  return (
    <BrowserRouter>
      <div className={`app-layout${collapsed ? " collapsed" : ""}`}>
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
        <main className="main">
          <Routes>
            <Route
              path="/"
              element={
                <Dashboard
                  rangeStart={rangeStart}
                  rangeEnd={rangeEnd}
                  onRangeChange={onRangeChange}
                />
              }
            />
            <Route
              path="/comparaison"
              element={<Comparaison rangeStart={rangeStart} rangeEnd={rangeEnd} />}
            />
            <Route path="/rapports" element={<Rapports />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
