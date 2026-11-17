"use client";

import { usePathname } from "next/navigation";
import Sidebar from "./Sidebar";

const AUTH_ROUTES = ["/login", "/signup"];
const FULL_BLEED_ROUTES = ["/landing"];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAuth = AUTH_ROUTES.some((r) => pathname.startsWith(r));
  const isFullBleed = FULL_BLEED_ROUTES.some((r) => pathname.startsWith(r));

  if (isAuth || isFullBleed) return <>{children}</>;

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">{children}</main>
    </div>
  );
}
