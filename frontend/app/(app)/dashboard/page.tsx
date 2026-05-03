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
import { DollarSign, Package, ShoppingCart, Activity } from "lucide-react";
import StatsCard from "@/components/StatsCard";
import OrdersTable, { Order } from "@/components/OrdersTable";
import ProductsTable, { Product } from "@/components/ProductsTable";
import { supabase } from "@/lib/supabase";
import { money } from "@/lib/format";

type Stats = {
  total_products: number;
  active_orders: number;
  monthly_profit: number;
  active_monitors: number;
};

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [recentOrders, setRecentOrders] = useState<Order[]>([]);
  const [recentImports, setRecentImports] = useState<Product[]>([]);
  const [chart, setChart] = useState<{ day: string; profit: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    try {
      setLoading(true);
      const sb = supabase();
      const monthStart = new Date();
      monthStart.setDate(1);
      monthStart.setHours(0, 0, 0, 0);

      const [productsCount, activeOrdersCount, monitorsCount, profitRows, ordersRes, importsRes, profitChart] =
        await Promise.all([
          sb.from("products").select("id", { count: "exact", head: true }),
          sb.from("orders").select("id", { count: "exact", head: true }).in("status", ["pending", "fulfilled", "shipped"]),
          sb.from("products").select("id", { count: "exact", head: true }).eq("monitor_status", "active"),
          sb.from("orders").select("profit, created_at").gte("created_at", monthStart.toISOString()),
          sb
            .from("orders")
            .select("id, ebay_order_id, buyer_name, sale_price, amazon_cost, profit, status, tracking_number, created_at, product:products(title)")
            .order("created_at", { ascending: false })
            .limit(8),
          sb
            .from("products")
            .select("id, asin, title, images, amazon_price, ebay_price, profit_margin, stock_status, monitor_status, ebay_listing_url")
            .order("imported_at", { ascending: false })
            .limit(6),
          sb
            .from("orders")
            .select("profit, created_at")
            .gte("created_at", new Date(Date.now() - 30 * 86400_000).toISOString()),
        ]);

      const monthlyProfit = (profitRows.data || []).reduce(
        (s: number, r: any) => s + (Number(r.profit) || 0),
        0,
      );

      setStats({
        total_products: productsCount.count || 0,
        active_orders: activeOrdersCount.count || 0,
        monthly_profit: monthlyProfit,
        active_monitors: monitorsCount.count || 0,
      });
      setRecentOrders(((ordersRes.data || []) as any[]).map((o) => ({ ...o, product: Array.isArray(o.product) ? o.product[0] : o.product })));
      setRecentImports((importsRes.data || []) as Product[]);

      // Aggregate by day
      const days: Record<string, number> = {};
      for (let i = 13; i >= 0; i--) {
        const d = new Date(Date.now() - i * 86400_000);
        days[d.toISOString().slice(0, 10)] = 0;
      }
      (profitChart.data || []).forEach((r: any) => {
        const k = (r.created_at || "").slice(0, 10);
        if (k in days) days[k] += Number(r.profit) || 0;
      });
      setChart(
        Object.entries(days).map(([day, profit]) => ({
          day: day.slice(5),
          profit: Number(profit.toFixed(2)),
        })),
      );
    } catch (e: any) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const sb = supabase();
    const ch = sb
      .channel("dashboard")
      .on("postgres_changes", { event: "*", schema: "public", table: "orders" }, () => load())
      .on("postgres_changes", { event: "*", schema: "public", table: "products" }, () => load())
      .subscribe();
    return () => {
      sb.removeChannel(ch);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dashboard</h1>
      </div>

      {err && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {err}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatsCard label="Total Products" value={loading ? "…" : stats?.total_products ?? 0} icon={Package} />
        <StatsCard label="Active Orders" value={loading ? "…" : stats?.active_orders ?? 0} icon={ShoppingCart} />
        <StatsCard label="Profit This Month" value={loading ? "…" : money(stats?.monthly_profit)} icon={DollarSign} />
        <StatsCard label="Active Monitors" value={loading ? "…" : stats?.active_monitors ?? 0} icon={Activity} />
      </div>

      <div className="card">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">Profit — last 14 days</h2>
            <p className="text-xs text-muted">From orders created in this period.</p>
          </div>
        </div>
        <div className="h-64 w-full">
          <ResponsiveContainer>
            <BarChart data={chart}>
              <CartesianGrid stroke="#222632" vertical={false} />
              <XAxis dataKey="day" stroke="#8b93a7" fontSize={11} tickLine={false} axisLine={false} />
              <YAxis stroke="#8b93a7" fontSize={11} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{ background: "#12151c", border: "1px solid #222632", borderRadius: 8 }}
                labelStyle={{ color: "#e6e8ee" }}
                cursor={{ fill: "rgba(34,197,94,.08)" }}
              />
              <Bar dataKey="profit" fill="#22c55e" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <h2 className="mb-3 text-lg font-semibold">Recent orders</h2>
          {loading ? (
            <div className="card text-muted">Loading…</div>
          ) : (
            <OrdersTable orders={recentOrders} />
          )}
        </div>
        <div>
          <h2 className="mb-3 text-lg font-semibold">Recent imports</h2>
          {loading ? (
            <div className="card text-muted">Loading…</div>
          ) : (
            <ProductsTable products={recentImports} compact onChange={load} />
          )}
        </div>
      </div>
    </div>
  );
}
