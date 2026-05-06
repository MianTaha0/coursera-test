"use client";

import {
  LayoutDashboard,
  Package,
  ShoppingCart,
  Settings,
  MessageSquare,
  Menu,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/products", label: "Products", icon: Package },
  { href: "/orders", label: "Orders", icon: ShoppingCart },
  { href: "/messages", label: "Messages", icon: MessageSquare },
  { href: "/settings", label: "Settings", icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

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
              const active =
                pathname === item.href || pathname?.startsWith(item.href + "/");
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

          <div className="border-t border-border p-3 text-xs text-muted">
            <div className="mb-1 font-medium text-white/80">eBay Dropshipping</div>
            <div>Self-hosted · v2.0</div>
          </div>
        </div>
      </aside>
    </>
  );
}
