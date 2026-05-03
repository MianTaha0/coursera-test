"use client";

import { useEffect, useMemo, useState } from "react";
import OrdersTable, { Order } from "@/components/OrdersTable";
import { supabase } from "@/lib/supabase";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "pending", label: "Pending" },
  { key: "fulfilled", label: "Fulfilled" },
  { key: "shipped", label: "Shipped" },
  { key: "delivered", label: "Delivered" },
];

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");

  async function load() {
    try {
      setLoading(true);
      const { data, error } = await supabase()
        .from("orders")
        .select(
          "id, ebay_order_id, buyer_name, sale_price, amazon_cost, profit, status, tracking_number, created_at, product:products(title)",
        )
        .order("created_at", { ascending: false });
      if (error) throw error;
      setOrders(((data || []) as any[]).map((o) => ({ ...o, product: Array.isArray(o.product) ? o.product[0] : o.product })));
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
      .channel("orders-page")
      .on("postgres_changes", { event: "*", schema: "public", table: "orders" }, () => load())
      .subscribe();
    return () => {
      sb.removeChannel(ch);
    };
  }, []);

  const filtered = useMemo(
    () => (filter === "all" ? orders : orders.filter((o) => o.status === filter)),
    [orders, filter],
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Orders</h1>
      </div>
      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`rounded-lg border px-3 py-1.5 text-sm transition ${
              filter === f.key
                ? "border-accent bg-accent/15 text-accent"
                : "border-border bg-panel2 text-muted hover:text-white"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>
      {err && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {err}
        </div>
      )}
      {loading ? <div className="card text-muted">Loading orders…</div> : <OrdersTable orders={filtered} />}
    </div>
  );
}
