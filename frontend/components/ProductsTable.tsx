"use client";

import { ExternalLink, Tag, Trash2, Loader2, CheckCircle2, LineChart as LineChartIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { api, Product } from "@/lib/api";
import { money, date } from "@/lib/format";
import PriceHistoryModal from "./PriceHistoryModal";

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
  const [toast, setToast] = useState<{ msg: string; type: "ok" | "err" } | null>(null);
  const [ebayConnected, setEbayConnected] = useState(false);
  const [historyProduct, setHistoryProduct] = useState<Product | null>(null);
  // track which ASINs have been listed this session
  const [listed, setListed] = useState<Record<string, string>>({});

  useEffect(() => {
    api<{ connected: boolean }>("/auth/ebay/status")
      .then((s) => setEbayConnected(s.connected))
      .catch(() => {});
  }, []);

  function flash(msg: string, type: "ok" | "err" = "ok") {
    setToast({ msg, type });
    window.clearTimeout((flash as any)._t);
    (flash as any)._t = window.setTimeout(() => setToast(null), 3500);
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

  async function listOnEbayApi(p: Product) {
    setBusy(p.asin);
    try {
      const result = await api<{ ok: boolean; listing_url: string; listing_price: number }>(
        `/api/products/${encodeURIComponent(p.asin)}/list-ebay`,
        { method: "POST", body: JSON.stringify({}) }
      );
      setListed((prev) => ({ ...prev, [p.asin]: result.listing_url }));
      flash(`Listed on eBay at $${result.listing_price} — opening listing…`, "ok");
      window.open(result.listing_url, "_blank", "noopener");
    } catch (e: any) {
      flash(e.message || "eBay listing failed.", "err");
    } finally {
      setBusy(null);
    }
  }

  async function listOnEbayManual(p: Product) {
    const lp = ebayPrice(p.price);
    const block = buildClipboardBlock(p, lp);
    try {
      await navigator.clipboard.writeText(block);
      flash("Details copied. Find a similar item → 'Sell one like this'.", "ok");
    } catch {
      flash("Could not copy automatically — open the product page to copy.", "err");
    }
    const q = encodeURIComponent((p.title || p.asin || "").slice(0, 80));
    window.open(`https://www.ebay.com/sch/i.html?_nkw=${q}&_sacat=0`, "_blank", "noopener");
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
              const listingUrl = listed[p.asin];
              const isBusy = busy === p.asin;
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
                      {listingUrl ? (
                        <a
                          href={listingUrl}
                          target="_blank"
                          rel="noopener"
                          className="btn-primary text-xs"
                          title="View eBay listing"
                        >
                          <CheckCircle2 size={14} /> Listed
                        </a>
                      ) : (
                        <button
                          onClick={() =>
                            ebayConnected ? listOnEbayApi(p) : listOnEbayManual(p)
                          }
                          disabled={isBusy}
                          className="btn-primary text-xs"
                          title={
                            ebayConnected
                              ? "Publish to eBay via API"
                              : "Copy details and open eBay listing flow"
                          }
                        >
                          {isBusy ? (
                            <Loader2 size={14} className="animate-spin" />
                          ) : (
                            <Tag size={14} />
                          )}
                          {ebayConnected ? "Publish to eBay" : "List on eBay"}
                        </button>
                      )}
                      <button
                        onClick={() => setHistoryProduct(p)}
                        className="btn-secondary text-xs"
                        title="Price history"
                      >
                        <LineChartIcon size={14} />
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
                        disabled={isBusy}
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
        <div
          className={`fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-lg border px-4 py-2 text-sm shadow-lg ${
            toast.type === "ok"
              ? "border-accent/30 bg-panel text-accent"
              : "border-red-500/30 bg-panel text-red-400"
          }`}
        >
          {toast.msg}
        </div>
      )}

      {historyProduct && (
        <PriceHistoryModal
          product={historyProduct}
          onClose={() => setHistoryProduct(null)}
        />
      )}
    </>
  );
}
