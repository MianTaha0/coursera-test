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
import { DollarSign, Package, ShoppingCart, Activity, AlertCircle, Bell, TrendingUp, TrendingDown, Wallet } from "lucide-react";
import StatsCard from "@/components/StatsCard";
import ProductsTable from "@/components/ProductsTable";
import { api, Alert, AppSettings, Product, Stats, computeNet } from "@/lib/api";
import { money } from "@/lib/format";

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [recent, setRecent] = useState<Product[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [allProducts, setAllProducts] = useState<Product[]>([]);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    try {
      setErr(null);
      const [s, p, a, all, cfg] = await Promise.all([
        api<Stats>("/api/stats"),
        api<Product[]>("/api/products?limit=8"),
        api<Alert[]>("/api/alerts?days=30&limit=8"),
        api<Product[]>("/api/products?limit=500"),
        api<AppSettings>("/api/settings"),
      ]);
      setStats(s);
      setRecent(p);
      setAlerts(a);
      setAllProducts(all);
      setSettings(cfg);
    } catch (e: any) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  // Sum of projected net profit across the whole library at current markup
  const projectedProfit = (() => {
    if (!settings) return null;
    let total = 0;
    let count = 0;
    for (const p of allProducts) {
      const sale = (p.price ?? 0) * (1 + settings.markup_percent / 100);
      const r = computeNet(p.price ?? null, sale, settings);
      if (r.net !== null) {
        total += r.net;
        count += 1;
      }
    }
    return { total: +total.toFixed(2), count };
  })();

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

      {projectedProfit && projectedProfit.count > 0 && (
        <div className="card">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <Wallet size={20} className="text-accent" />
              <div>
                <h2 className="text-lg font-semibold">Projected net profit</h2>
                <p className="text-xs text-muted">
                  If every product sells at +{settings?.markup_percent ?? 30}% markup,
                  after eBay fees ({settings?.ebay_fvf_percent ?? 13.25}% FVF + ${(settings?.ebay_per_order_fee ?? 0.30).toFixed(2)} per order
                  {(settings?.ebay_ad_rate_percent ?? 0) > 0 && ` + ${settings?.ebay_ad_rate_percent}% promoted`}).
                </p>
              </div>
            </div>
            <div className="text-right">
              <div className={`text-2xl font-bold ${projectedProfit.total >= 0 ? "text-accent" : "text-red-400"}`}>
                {money(projectedProfit.total)}
              </div>
              <div className="text-xs text-muted">across {projectedProfit.count} products</div>
            </div>
          </div>
        </div>
      )}

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

      <div className="card">
        <div className="mb-3 flex items-center gap-2">
          <Bell size={18} className="text-muted" />
          <h2 className="text-lg font-semibold">Recent alerts</h2>
          <span className="text-xs text-muted">last 30 days</span>
        </div>
        {alerts.length === 0 ? (
          <div className="text-sm text-muted">
            No price or stock changes detected yet. Re-save a product on Amazon to record a new snapshot.
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {alerts.map((a, i) => (
              <li key={`${a.asin}-${i}`} className="flex items-center gap-3 py-2 text-sm">
                {a.image && (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img
                    src={a.image}
                    alt=""
                    referrerPolicy="no-referrer"
                    className="h-9 w-9 rounded border border-border bg-white object-contain"
                  />
                )}
                <div className="min-w-0 flex-1">
                  <div className="line-clamp-1 font-medium">{a.title || a.asin}</div>
                  <div className="text-xs text-muted">{new Date(a.checked_at).toLocaleString()}</div>
                </div>
                {a.price_delta !== null && a.price_delta !== 0 && (
                  <span
                    className={`flex items-center gap-1 text-xs font-medium ${
                      a.price_delta < 0 ? "text-accent" : "text-red-400"
                    }`}
                  >
                    {a.price_delta < 0 ? <TrendingDown size={12} /> : <TrendingUp size={12} />}
                    {a.price_delta > 0 ? "+" : ""}
                    {money(a.price_delta, a.currency)} → {money(a.price, a.currency)}
                  </span>
                )}
                {a.stock_delta && (
                  <span
                    className={`badge ${
                      a.stock_status === "in_stock"
                        ? "bg-accent/15 text-accent"
                        : "bg-red-500/15 text-red-400"
                    }`}
                  >
                    {a.stock_delta}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
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
