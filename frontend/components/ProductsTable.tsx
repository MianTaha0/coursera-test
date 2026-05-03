"use client";

import { useState } from "react";
import { supabase } from "@/lib/supabase";
import { money } from "@/lib/format";

export type Product = {
  id: string;
  asin: string | null;
  title: string | null;
  images: string[] | null;
  amazon_price: number | null;
  ebay_price: number | null;
  profit_margin: number | null;
  stock_status: string;
  monitor_status: string;
  ebay_listing_url: string | null;
};

export default function ProductsTable({
  products,
  onChange,
  compact = false,
}: {
  products: Product[];
  onChange?: () => void;
  compact?: boolean;
}) {
  const [busy, setBusy] = useState<string | null>(null);

  async function toggleMonitor(p: Product) {
    setBusy(p.id);
    const next = p.monitor_status === "active" ? "paused" : "active";
    await supabase().from("products").update({ monitor_status: next }).eq("id", p.id);
    setBusy(null);
    onChange?.();
  }

  async function remove(p: Product) {
    if (!confirm(`Remove "${p.title}" from your store?`)) return;
    setBusy(p.id);
    await supabase().from("products").delete().eq("id", p.id);
    setBusy(null);
    onChange?.();
  }

  if (!products.length) {
    return (
      <div className="card text-center text-muted">
        No products yet. Use the Chrome extension on an Amazon product page to import one.
      </div>
    );
  }

  return (
    <div className="table-wrap">
      <table className="w-full text-sm">
        <thead className="bg-panel2">
          <tr>
            <th className="th">Product</th>
            <th className="th">Amazon</th>
            <th className="th">eBay</th>
            <th className="th">Profit</th>
            <th className="th">Stock</th>
            {!compact && <th className="th">Monitor</th>}
            {!compact && <th className="th text-right">Actions</th>}
          </tr>
        </thead>
        <tbody>
          {products.map((p) => (
            <tr key={p.id} className="border-t border-border">
              <td className="td">
                <div className="flex items-center gap-3">
                  {p.images?.[0] && (
                    /* eslint-disable-next-line @next/next/no-img-element */
                    <img
                      src={p.images[0]}
                      alt=""
                      className="h-10 w-10 rounded border border-border bg-white object-contain"
                    />
                  )}
                  <div className="min-w-0">
                    <div className="line-clamp-1 max-w-xs font-medium">
                      {p.title || p.asin}
                    </div>
                    {p.ebay_listing_url ? (
                      <a
                        href={p.ebay_listing_url}
                        target="_blank"
                        className="text-xs text-accent hover:underline"
                      >
                        View on eBay
                      </a>
                    ) : (
                      <div className="text-xs text-muted">Not listed</div>
                    )}
                  </div>
                </div>
              </td>
              <td className="td">{money(p.amazon_price)}</td>
              <td className="td">{money(p.ebay_price)}</td>
              <td className="td text-accent">{money(p.profit_margin)}</td>
              <td className="td">
                <span
                  className={`badge ${
                    p.stock_status === "in_stock"
                      ? "bg-accent/15 text-accent"
                      : "bg-red-500/15 text-red-400"
                  }`}
                >
                  {p.stock_status === "in_stock" ? "In stock" : "Out"}
                </span>
              </td>
              {!compact && (
                <td className="td">
                  <span
                    className={`badge ${
                      p.monitor_status === "active"
                        ? "bg-blue-500/15 text-blue-300"
                        : "bg-zinc-500/20 text-zinc-300"
                    }`}
                  >
                    {p.monitor_status}
                  </span>
                </td>
              )}
              {!compact && (
                <td className="td text-right">
                  <div className="flex justify-end gap-2">
                    <button
                      disabled={busy === p.id}
                      onClick={() => toggleMonitor(p)}
                      className="btn-secondary text-xs"
                    >
                      {p.monitor_status === "active" ? "Pause" : "Resume"}
                    </button>
                    <button
                      disabled={busy === p.id}
                      onClick={() => remove(p)}
                      className="btn-danger text-xs"
                    >
                      Remove
                    </button>
                  </div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
