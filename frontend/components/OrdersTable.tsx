"use client";

import { money, date } from "@/lib/format";

export type Order = {
  id: string;
  ebay_order_id: string | null;
  buyer_name: string | null;
  sale_price: number | null;
  amazon_cost: number | null;
  profit: number | null;
  status: string;
  tracking_number: string | null;
  created_at: string | null;
  product?: { title: string | null } | null;
};

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-yellow-500/15 text-yellow-300",
  fulfilled: "bg-blue-500/15 text-blue-300",
  shipped: "bg-purple-500/15 text-purple-300",
  delivered: "bg-accent/15 text-accent",
  cancelled: "bg-red-500/15 text-red-400",
  fulfillment_failed: "bg-red-500/15 text-red-400",
};

export default function OrdersTable({ orders }: { orders: Order[] }) {
  if (!orders.length) {
    return <div className="card text-center text-muted">No orders yet.</div>;
  }

  return (
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
              <td className="td">
                <div className="line-clamp-1 max-w-xs">{o.product?.title || "—"}</div>
              </td>
              <td className="td">{money(o.sale_price)}</td>
              <td className="td">{money(o.amazon_cost)}</td>
              <td className="td text-accent">{money(o.profit)}</td>
              <td className="td">
                <span className={`badge ${STATUS_STYLES[o.status] || "bg-zinc-500/20"}`}>
                  {o.status}
                </span>
              </td>
              <td className="td font-mono text-xs">{o.tracking_number || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
