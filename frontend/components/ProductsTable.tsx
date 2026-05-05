"use client";

import { ExternalLink, Tag, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, Product } from "@/lib/api";
import { money, date } from "@/lib/format";

const DEFAULT_MARKUP_PERCENT = 30;

function ebayPrice(amazon: number | null | undefined, markup = DEFAULT_MARKUP_PERCENT) {
  if (amazon === null || amazon === undefined || isNaN(Number(amazon))) return null;
  return Math.round(Number(amazon) * (1 + markup / 100) * 100) / 100;
}

function buildClipboardBlock(p: Product, listingPrice: number | null) {
  const lines = [
    `Title: ${p.title || ""}`,
    `Brand: ${p.brand || ""}`,
    `ASIN: ${p.asin}`,
    `Amazon price: ${p.price ?? ""} ${p.currency || ""}`.trim(),
  ];
  if (listingPrice !== null) lines.push(`Suggested list price: ${listingPrice} ${p.currency || "USD"} (Amazon + ${DEFAULT_MARKUP_PERCENT}%)`);
  if (p.amazon_url) lines.push(`Amazon URL: ${p.amazon_url}`);
  if (p.images?.length) lines.push("", "Image URLs:", ...p.images);
  if (p.description) lines.push("", "Description:", p.description);
  return lines.join("\n");
}

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
  const [toast, setToast] = useState<string | null>(null);

  function flash(msg: string) {
    setToast(msg);
    window.clearTimeout((flash as any)._t);
    (flash as any)._t = window.setTimeout(() => setToast(null), 2200);
  }

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

  async function listOnEbay(p: Product) {
    const lp = ebayPrice(p.price);
    const block = buildClipboardBlock(p, lp);
    try {
      await navigator.clipboard.writeText(block);
      flash("Details copied. Find a similar item → 'Sell one like this'.");
    } catch {
      flash("Could not copy automatically — open the product page to copy.");
    }
    // eBay's catalog search. Pick any matching listing and click 'Sell one
    // like this' on the right rail — eBay prefills 90% of the listing form.
    const q = encodeURIComponent((p.title || p.asin || "").slice(0, 80));
    const url = `https://www.ebay.com/sch/i.html?_nkw=${q}&_sacat=0`;
    window.open(url, "_blank", "noopener");
  }

  if (!products.length) {
    return (
      <div className="card text-center text-muted">
        No products yet. Visit any Amazon product page and click <b>Save product (Droply)</b> in the Chrome extension.
      </div>
    );
  }

  return (
    <>
      <div className="table-wrap">
        <table className="w-full text-sm">
          <thead className="bg-panel2">
            <tr>
              <th className="th">Product</th>
              <th className="th">Brand</th>
              <th className="th">Amazon</th>
              {!compact && <th className="th">List @ +{DEFAULT_MARKUP_PERCENT}%</th>}
              <th className="th">Stock</th>
              {!compact && <th className="th">Saved</th>}
              <th className="th text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {products.map((p) => {
              const lp = ebayPrice(p.price);
              return (
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
                  {!compact && <td className="td text-accent">{money(lp, p.currency)}</td>}
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
                      <button
                        onClick={() => listOnEbay(p)}
                        className="btn-primary text-xs"
                        title="Copy details and open eBay listing flow"
                      >
                        <Tag size={14} /> List on eBay
                      </button>
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
              );
            })}
          </tbody>
        </table>
      </div>

      {toast && (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-lg border border-accent/30 bg-panel px-4 py-2 text-sm text-accent shadow-lg">
          {toast}
        </div>
      )}
    </>
  );
}
