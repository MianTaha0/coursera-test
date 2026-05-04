"use client";

import { useEffect, useState } from "react";
import { ShoppingCart } from "lucide-react";
import { api, Order } from "@/lib/api";
import { money, date } from "@/lib/format";

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<Order[]>("/api/orders")
      .then(setOrders)
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Orders</h1>
        <p className="text-sm text-muted">eBay orders synced through your seller account.</p>
      </div>

      {err && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{err}</div>
      )}

      {loading ? (
        <div className="card text-muted">Loading…</div>
      ) : orders.length === 0 ? (
        <div className="card text-center text-muted">
          <ShoppingCart className="mx-auto mb-3 opacity-50" size={32} />
          <div className="font-medium text-white">No orders yet</div>
          <div className="mt-1 text-sm">
            Connect your eBay store on the <a href="/settings" className="text-accent hover:underline">Settings</a> page
            to start syncing orders. (eBay integration is staged for the next milestone.)
          </div>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="w-full text-sm">
            <thead className="bg-panel2">
              <tr>
                <th className="th">Date</th>
                <th className="th">Buyer</th>
                <th className="th">Product</th>
                <th className="th">Sale</th>
                <th className="th">Cost</th>
                <th className="th">Profit</th>
                <th className="th">Status</th>
                <th className="th">Tracking</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id} className="border-t border-border">
                  <td className="td">{date(o.created_at)}</td>
                  <td className="td">{o.buyer_name || "—"}</td>
                  <td className="td font-mono text-xs">{o.product_asin}</td>
                  <td className="td">{money(o.sale_price)}</td>
                  <td className="td">{money(o.amazon_cost)}</td>
                  <td className="td text-accent">{money(o.profit)}</td>
                  <td className="td"><span className="badge bg-blue-500/15 text-blue-300">{o.status}</span></td>
                  <td className="td font-mono text-xs">{o.tracking_number || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
