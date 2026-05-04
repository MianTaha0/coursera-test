"use client";

import { useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { DollarSign, Package, ShoppingCart, Activity, AlertCircle } from "lucide-react";
import StatsCard from "@/components/StatsCard";
import ProductsTable from "@/components/ProductsTable";
import { api, Product, Stats } from "@/lib/api";
import { money } from "@/lib/format";

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [recent, setRecent] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    try {
      setErr(null);
      const [s, p] = await Promise.all([
        api<Stats>("/api/stats"),
        api<Product[]>("/api/products?limit=8"),
      ]);
      setStats(s);
      setRecent(p);
    } catch (e: any) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-sm text-muted">
            Live view of products synced from your Droply Chrome extension.
          </p>
        </div>
      </div>

      {err && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          <AlertCircle size={16} className="mt-0.5" />
          <div>
            Couldn't reach the API. Make sure the backend is running at <code>{process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}</code>.
            <div className="text-xs opacity-70">{err}</div>
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatsCard label="Total Products" value={loading ? "…" : stats?.total ?? 0} icon={Package} />
        <StatsCard label="Saved Today" value={loading ? "…" : stats?.saved_today ?? 0} icon={Activity} />
        <StatsCard
          label="Avg Price"
          value={loading ? "…" : money(stats?.avg_price)}
          icon={DollarSign}
          hint={stats ? `Range ${money(stats.min_price)} – ${money(stats.max_price)}` : undefined}
        />
        <StatsCard
          label="In Stock"
          value={loading ? "…" : `${stats?.in_stock ?? 0} / ${stats?.total ?? 0}`}
          icon={ShoppingCart}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="card lg:col-span-2">
          <div className="mb-3">
            <h2 className="text-lg font-semibold">Imports — last 14 days</h2>
            <p className="text-xs text-muted">Number of products saved per day.</p>
          </div>
          <div className="h-64 w-full">
            <ResponsiveContainer>
              <BarChart data={stats?.series || []}>
                <CartesianGrid stroke="#222632" vertical={false} />
                <XAxis dataKey="day" stroke="#8b93a7" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="#8b93a7" fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ background: "#12151c", border: "1px solid #222632", borderRadius: 8 }}
                  labelStyle={{ color: "#e6e8ee" }}
                  cursor={{ fill: "rgba(34,197,94,.08)" }}
                />
                <Bar dataKey="count" fill="#22c55e" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <h2 className="mb-3 text-lg font-semibold">Top brands</h2>
          {!stats?.top_brands?.length ? (
            <div className="text-sm text-muted">No data yet.</div>
          ) : (
            <ul className="space-y-2">
              {stats.top_brands.map((b) => (
                <li key={b.brand} className="flex items-center justify-between rounded-lg bg-panel2 px-3 py-2">
                  <span className="truncate font-medium">{b.brand}</span>
                  <span className="text-sm text-muted">{b.count}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div>
        <h2 className="mb-3 text-lg font-semibold">Recent imports</h2>
        {loading ? (
          <div className="card text-muted">Loading…</div>
        ) : (
          <ProductsTable products={recent} compact onChange={load} />
        )}
      </div>
    </div>
  );
}
