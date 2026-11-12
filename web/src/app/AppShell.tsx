import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { tokenStore } from "../auth/tokenStore";
import { Button } from "../components/ui/Button";
import { BrandMark } from "./BrandMark";
import { NAV_ITEMS } from "./routes";

export function AppShell() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const [lastPath, setLastPath] = useState(location.pathname);
  if (location.pathname !== lastPath) {
    // Close the phone menu after navigating.
    setLastPath(location.pathname);
    setOpen(false);
  }

  return (
    <div className="shell">
      <header className="sidebar" data-open={open}>
        <div className="brand">
          <BrandMark />
          <span>LocalRithmicLLM</span>
        </div>
        <Button
          variant="ghost"
          size="small"
          className="menu-button"
          aria-expanded={open}
          aria-controls="primary-nav"
          onClick={() => setOpen((value) => !value)}
        >
          Menu
        </Button>
        <nav id="primary-nav" className="nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <Button size="small" variant="ghost" onClick={() => tokenStore.clear()}>
            Sign out
          </Button>
        </div>
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
