"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LayoutDashboard, FileText, FlaskConical, LogOut, Stethoscope, Music, Activity } from "lucide-react";
import { Button } from "../components/ui";
import { ICON_SIZE, ICON_STROKE } from "../lib/icons";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/evals", label: "Run Eval", icon: FlaskConical },
  { href: "/pulse", label: "Pulse", icon: Activity },
  { href: "/library", label: "Library", icon: Music },
  { href: "/reports", label: "Reports", icon: FileText },
];

type User = { email: string; name: string };

function loadUser(): User | null {
  if (typeof window === "undefined") return null;
  try { return JSON.parse(localStorage.getItem("evalra_user") || "null"); }
  catch { return null; }
}

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => { setUser(loadUser()); }, []);

  function logout() {
    localStorage.removeItem("evalra_token");
    localStorage.removeItem("evalra_user");
    document.cookie = "evalra_token=; path=/; max-age=0";
    router.push("/login");
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <Stethoscope size={ICON_SIZE} strokeWidth={ICON_STROKE} />
        <span>Voice Doctor</span>
      </div>

      <nav className="sidebar-nav">
        <p className="sidebar-section-label">Menu</p>
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={`sidebar-item ${active ? "sidebar-item-active" : ""}`}
            >
              <Icon size={15} strokeWidth={ICON_STROKE} />
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="sidebar-user">
        {user && (
          <div className="sidebar-user__divider">
            <div className="sidebar-user__row">
              <div className="sidebar-avatar">
                {user.name.charAt(0).toUpperCase()}
              </div>
              <div style={{ minWidth: 0 }}>
                <div className="sidebar-user__name">{user.name}</div>
                <div className="sidebar-user__email">{user.email}</div>
              </div>
            </div>
            <Button variant="secondary" size="sm" fullWidth onClick={logout}>
              <LogOut size={13} strokeWidth={ICON_STROKE} />
              Sign out
            </Button>
          </div>
        )}
      </div>
    </aside>
  );
}
