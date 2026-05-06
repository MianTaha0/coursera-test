"use client";

import { useEffect, useState } from "react";
import { X, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { api, PriceSnapshot, Product } from "@/lib/api";
import { money } from "@/lib/format";

export default function PriceHistoryModal({
  product,
  onClose,
}: {
  product: Product;
  onClose: () => void;
}) {
  const [history, setHistory] = useState<PriceSnapshot[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<PriceSnapshot[]>(`/api/products/${encodeURIComponent(product.asin)}/history`)
      .then(setHistory)
      .catch((e) => setErr(e.message));
  }, [product.asin]);

  const data = (history || []).map((s) => ({
    t: new Date(s.checked_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    price: s.price,
    stock: s.stock_status,
  }));

  const first = history?.[0]?.price ?? null;
  const last = history?.[history.length - 1]?.price ?? null;
  const delta = first !== null && last !== null ? last - first : null;
  const trend =
    delta === null ? null : delta > 0 ? "up" : delta < 0 ? "down" : "flat";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-2xl rounded-xl border border-border bg-panel p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 rounded p-1 text-muted hover:bg-panel2 hover:text-white"
        >
          <X size={18} />
        </button>

        <div className="flex items-start gap-4">
          {product.images?.[0] && (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={product.images[0]}
              alt=""
              className="h-16 w-16 rounded border border-border bg-white object-contain"
              referrerPolicy="no-referrer"
            />
          )}
          <div className="min-w-0 flex-1">
            <h2 className="line-clamp-2 text-lg font-semibold">
              {product.title || product.asin}
            </h2>
            <div className="font-mono text-xs text-muted">{product.asin}</div>
            <div className="mt-2 flex items-center gap-3 text-sm">
              <span className="text-muted">Current:</span>
              <span className="font-medium">{money(product.price, product.currency)}</span>
              {trend && delta !== null && (
                <span
                  className={`flex items-center gap-1 text-xs ${
                    trend === "down"
                      ? "text-accent"
                      : trend === "up"
                      ? "text-red-400"
                      : "text-muted"
                  }`}
                >
                  {trend === "up" && <TrendingUp size={12} />}
                  {trend === "down" && <TrendingDown size={12} />}
                  {trend === "flat" && <Minus size={12} />}
                  {delta > 0 ? "+" : ""}
                  {money(delta, product.currency)} since first save
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="mt-6">
          <h3 className="text-sm font-semibold text-muted">Price history</h3>
          {err ? (
            <div className="mt-3 text-sm text-red-400">{err}</div>
          ) : history === null ? (
            <div className="mt-3 text-sm text-muted">Loading…</div>
          ) : data.length < 2 ? (
            <div className="mt-3 rounded-lg border border-border bg-panel2 p-4 text-sm text-muted">
              Only {data.length} snapshot so far. Visit the Amazon page again (with the
              extension installed) to record a new datapoint — Droply tracks history every
              time the price or stock status changes.
            </div>
          ) : (
            <div className="mt-3 h-56 w-full">
              <ResponsiveContainer>
                <LineChart data={data}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="t" tick={{ fontSize: 11, fill: "#9ca3af" }} />
                  <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} domain={["auto", "auto"]} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#0f172a",
                      border: "1px solid #1f2937",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                  <Line type="monotone" dataKey="price" stroke="#10b981" strokeWidth={2} dot />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {history && history.length > 0 && (
          <div className="mt-6">
            <h3 className="text-sm font-semibold text-muted">Snapshots</h3>
            <div className="mt-2 max-h-48 overflow-auto rounded-lg border border-border">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-panel2">
                  <tr>
                    <th className="px-3 py-2 text-left">When</th>
                    <th className="px-3 py-2 text-left">Price</th>
                    <th className="px-3 py-2 text-left">Stock</th>
                  </tr>
                </thead>
                <tbody>
                  {[...history].reverse().map((s, i) => (
                    <tr key={i} className="border-t border-border">
                      <td className="px-3 py-2">{new Date(s.checked_at).toLocaleString()}</td>
                      <td className="px-3 py-2 font-medium">{money(s.price, s.currency)}</td>
                      <td className="px-3 py-2">
                        <span
                          className={`badge ${
                            s.stock_status === "in_stock"
                              ? "bg-accent/15 text-accent"
                              : "bg-red-500/15 text-red-400"
                          }`}
                        >
                          {s.stock_status === "in_stock" ? "In stock" : "Out"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
