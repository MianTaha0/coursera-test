"use client";

import {
  LayoutDashboard,
  Package,
  ShoppingCart,
  Settings,
  LogOut,
  Menu,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/products", label: "Products", icon: Package },
  { href: "/orders", label: "Orders", icon: ShoppingCart },
  { href: "/settings", label: "Settings", icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState<string>("");

  useEffect(() => {
    supabase()
      .auth.getUser()
      .then(({ data }) => setEmail(data.user?.email ?? ""));
  }, []);

  async function logout() {
    await supabase().auth.signOut();
    router.replace("/login");
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="fixed left-3 top-3 z-30 rounded-md border border-border bg-panel p-2 md:hidden"
        aria-label="Open menu"
      >
        <Menu size={18} />
      </button>

      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/60 md:hidden"
          onClick={() => setOpen(false)}
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 w-64 transform border-r border-border bg-panel transition-transform md:static md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <Link href="/dashboard" className="flex items-center gap-2 text-lg font-bold">
              <span className="inline-block h-3 w-3 rounded-full bg-accent shadow-[0_0_10px_rgba(34,197,94,.6)]" />
              Droply
            </Link>
            <button
              onClick={() => setOpen(false)}
              className="md:hidden"
              aria-label="Close menu"
            >
              <X size={18} />
            </button>
          </div>

          <nav className="flex-1 space-y-1 p-3">
            {NAV.map((item) => {
              const Icon = item.icon;
              const active = pathname === item.href || pathname?.startsWith(item.href + "/");
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setOpen(false)}
                  className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
                    active
                      ? "bg-accent/15 text-accent"
                      : "text-white/80 hover:bg-panel2 hover:text-white"
                  }`}
                >
                  <Icon size={18} />
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="border-t border-border p-3">
            <div className="mb-2 flex items-center gap-3 rounded-lg bg-panel2 px-3 py-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-sm font-bold text-black">
                {(email || "?").slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{email || "Not signed in"}</div>
                <div className="text-xs text-muted">Trial plan</div>
              </div>
            </div>
            <button
              onClick={logout}
              className="flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm text-muted hover:bg-panel2 hover:text-white"
            >
              <LogOut size={16} /> Log out
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
