import { NavLink } from "react-router-dom";
import { LayoutDashboard, GitCompareArrows, FileText, ChevronLeft, ChevronRight } from "lucide-react";

// 👉 EMPLACEMENT DU LOGO : src/assets/logo-crk.png
import logo from "../assets/logo-crk.png";

const navItems = [
  { to: "/", label: "Vue d'ensemble", icon: LayoutDashboard },
  { to: "/comparaison", label: "Comparaison", icon: GitCompareArrows },
  { to: "/rapports", label: "Rapports", icon: FileText },
];

export default function Sidebar({ collapsed, onToggle }) {
  return (
    <aside className={`sidebar${collapsed ? " collapsed" : ""}`}>
      {/* Bouton pour réduire / agrandir */}
      <button
        className="sidebar-toggle"
        onClick={onToggle}
        aria-label={collapsed ? "Agrandir le menu" : "Réduire le menu"}
      >
        {collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
      </button>

      <div className="sidebar-logo">
        <img src={logo} alt="CRK Maroquinier depuis 1986" />
      </div>

      <nav className="sidebar-nav">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            title={collapsed ? label : undefined}
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
          >
            <Icon size={17} strokeWidth={2} />
            <span className="nav-label">{label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
