"use client";

import { ExternalLink, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, Product } from "@/lib/api";
import { money, date } from "@/lib/format";

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

  async function remove(p: Product) {
    if (!confirm(`Remove "${p.title || p.asin}" from the dashboard?`)) return;
    setBusy(p.asin);
    try {
      await api(`/api/products/${encodeURIComponent(p.asin)}`, { method: "DELETE" });
      onChange?.();
    } finally {
      setBusy(null);
    }
  }

  if (!products.length) {
    return (
      <div className="card text-center text-muted">
        No products yet. Visit any Amazon product page and click <b>Save product (Droply)</b> in the Chrome extension.
      </div>
    );
  }

  return (
    <div className="table-wrap">
      <table className="w-full text-sm">
        <thead className="bg-panel2">
          <tr>
            <th className="th">Product</th>
            <th className="th">Brand</th>
            <th className="th">Price</th>
            <th className="th">Stock</th>
            {!compact && <th className="th">Saved</th>}
            <th className="th text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {products.map((p) => (
            <tr key={p.asin} className="border-t border-border">
              <td className="td">
                <div className="flex items-center gap-3">
                  {p.images?.[0] && (
                    /* eslint-disable-next-line @next/next/no-img-element */
                    <img
                      src={p.images[0]}
                      alt=""
                      referrerPolicy="no-referrer"
                      className="h-12 w-12 rounded border border-border bg-white object-contain"
                    />
                  )}
                  <div className="min-w-0">
                    <div className="line-clamp-1 max-w-md font-medium">
                      {p.title || p.asin}
                    </div>
                    <div className="font-mono text-xs text-muted">{p.asin}</div>
                  </div>
                </div>
              </td>
              <td className="td">{p.brand || "—"}</td>
              <td className="td font-medium">{money(p.price, p.currency)}</td>
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
              {!compact && <td className="td text-muted">{date(p.saved_at)}</td>}
              <td className="td text-right">
                <div className="flex justify-end gap-2">
                  {p.amazon_url && (
                    <a
                      href={p.amazon_url}
                      target="_blank"
                      rel="noopener"
                      className="btn-secondary text-xs"
                      title="View on Amazon"
                    >
                      <ExternalLink size={14} />
                    </a>
                  )}
                  <button
                    disabled={busy === p.asin}
                    onClick={() => remove(p)}
                    className="btn-danger text-xs"
                    title="Remove"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
