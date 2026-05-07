"use client";

import { ExternalLink, Tag, Trash2, Loader2, CheckCircle2, LineChart as LineChartIcon, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, AppSettings, EbayListing, Product, VeroMatch, computeNet } from "@/lib/api";
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
  // ASIN → listing record (persisted server-side)
  const [listings, setListings] = useState<Record<string, EbayListing>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  async function loadListings() {
    try {
      const arr = await api<EbayListing[]>("/api/listings");
      const map: Record<string, EbayListing> = {};
      for (const l of arr) map[l.asin] = l;
      setListings(map);
    } catch {
      /* ignore */
    }
  }

  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [veroMap, setVeroMap] = useState<Record<string, VeroMatch[]>>({});
  const markupPercent = settings?.markup_percent ?? DEFAULT_MARKUP_PERCENT;

  async function loadVero() {
    try {
      const res = await api<Record<string, VeroMatch[]>>("/api/vero/scan");
      setVeroMap(res || {});
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    api<{ connected: boolean }>("/auth/ebay/status")
      .then((s) => setEbayConnected(s.connected))
      .catch(() => {});
    loadListings();
    loadVero();
    api<AppSettings>("/api/settings").then(setSettings).catch(() => {});
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

  async function listOnEbayApi(p: Product, overrideVero = false) {
    // Pre-flight VeRO check
    const vero = veroMap[p.asin] || [];
    const blocking = vero.filter((m) => m.level === "block");
    if (blocking.length && !overrideVero) {
      const kws = blocking.map((m) => m.keyword).join(", ");
      const reasons = blocking.map((m) => `• ${m.keyword}: ${m.reason || ""}`).join("\n");
      const proceed = confirm(
        `⚠️ VeRO watchlist match: ${kws}\n\n${reasons}\n\nListing branded items can get your eBay account suspended. Override and publish anyway?`,
      );
      if (!proceed) return;
      overrideVero = true;
    }
    setBusy(p.asin);
    try {
      const result = await api<{ ok: boolean; listing_url: string; listing_price: number }>(
        `/api/products/${encodeURIComponent(p.asin)}/list-ebay`,
        { method: "POST", body: JSON.stringify({ override_vero: overrideVero }) }
      );
      flash(`Listed on eBay at ${money(result.listing_price, p.currency)} — opening listing…`, "ok");
      await loadListings();
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

  function toggleSelect(asin: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(asin)) next.delete(asin);
      else next.add(asin);
      return next;
    });
  }

  function selectAllUnpublished() {
    const next = new Set<string>();
    for (const p of products) {
      if (!listings[p.asin]?.listing_url) next.add(p.asin);
    }
    setSelected(next);
  }

  async function bulkPublish() {
    if (!selected.size) return;
    const asins = Array.from(selected);
    // Warn if any are VeRO-blocked
    const blocked = asins.filter((a) =>
      (veroMap[a] || []).some((m) => m.level === "block"),
    );
    let overrideVero = false;
    if (blocked.length) {
      const proceed = confirm(
        `${blocked.length} of ${asins.length} selected products match the VeRO watchlist. Override and publish anyway?`,
      );
      if (!proceed) return;
      overrideVero = true;
    }
    setBulkBusy(true);
    try {
      const result = await api<{ total: number; success: number; failed: number }>(
        "/api/products/list-ebay-bulk",
        {
          method: "POST",
          body: JSON.stringify({ asins, override_vero: overrideVero }),
        },
      );
      flash(
        `Bulk publish: ${result.success}/${result.total} succeeded${
          result.failed ? ` · ${result.failed} failed` : ""
        }`,
        result.failed ? "err" : "ok",
      );
      setSelected(new Set());
      await loadListings();
    } catch (e: any) {
      flash(e.message || "Bulk publish failed.", "err");
    } finally {
      setBulkBusy(false);
    }
  }

  if (!products.length) {
    return (
      <div className="card text-center text-muted">
        No products yet. Visit any Amazon product page and click <b>Save product (Droply)</b> in the Chrome extension.
      </div>
    );
  }

  const allSelectable = products.filter((p) => !listings[p.asin]?.listing_url);
  const allSelected =
    allSelectable.length > 0 && allSelectable.every((p) => selected.has(p.asin));

  return (
    <>
      {!compact && selected.size > 0 && (
        <div className="sticky top-0 z-10 -mt-2 mb-3 flex items-center justify-between gap-3 rounded-lg border border-accent/40 bg-accent/15 px-4 py-2 text-sm">
          <div>
            <b>{selected.size}</b> selected
            <button
              onClick={() => setSelected(new Set())}
              className="ml-3 text-xs text-muted hover:text-white"
            >
              Clear
            </button>
          </div>
          <div className="flex gap-2">
            <button
              onClick={selectAllUnpublished}
              className="btn-secondary text-xs"
            >
              Select all unpublished ({allSelectable.length})
            </button>
            <button
              onClick={bulkPublish}
              disabled={bulkBusy || !ebayConnected}
              className="btn-primary text-xs"
              title={ebayConnected ? "Publish selected products to eBay" : "Connect eBay first"}
            >
              {bulkBusy ? <Loader2 size={12} className="animate-spin" /> : <Tag size={12} />}
              Publish {selected.size} to eBay
            </button>
          </div>
        </div>
      )}

      <div className="table-wrap">
        <table className="w-full text-sm">
          <thead className="bg-panel2">
            <tr>
              {!compact && (
                <th className="th w-8">
                  <input
                    type="checkbox"
                    aria-label="Select all unpublished"
                    checked={allSelected}
                    onChange={(e) => {
                      if (e.target.checked) selectAllUnpublished();
                      else setSelected(new Set());
                    }}
                    className="h-4 w-4 accent-accent"
                  />
                </th>
              )}
              <th className="th">Product</th>
              <th className="th">Brand</th>
              <th className="th">Amazon</th>
              {!compact && <th className="th">List @ +{markupPercent}%</th>}
              {!compact && <th className="th">Net</th>}
              <th className="th">Stock</th>
              {!compact && <th className="th">Saved</th>}
              <th className="th text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {products.map((p) => {
              const lp = ebayPrice(p.price, markupPercent);
              const listing = listings[p.asin];
              const isBusy = busy === p.asin;
              // Use the actual listed price if available; otherwise the suggested price
              const salePrice = listing?.last_price ?? lp;
              const profit = computeNet(p.price, salePrice, settings);
              return (
                <tr key={p.asin} className="border-t border-border">
                  {!compact && (
                    <td className="td">
                      <input
                        type="checkbox"
                        aria-label={`Select ${p.asin}`}
                        checked={selected.has(p.asin)}
                        disabled={!!listing?.listing_url}
                        onChange={() => toggleSelect(p.asin)}
                        className="h-4 w-4 accent-accent disabled:opacity-30"
                      />
                    </td>
                  )}
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
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs text-muted">{p.asin}</span>
                          {(veroMap[p.asin]?.length ?? 0) > 0 && (() => {
                            const matches = veroMap[p.asin];
                            const blocking = matches.some((m) => m.level === "block");
                            const kws = matches.map((m) => m.keyword).join(", ");
                            const tooltip = matches
                              .map((m) => `${m.keyword} (${m.level}): ${m.reason || ""}`)
                              .join("\n");
                            return (
                              <span
                                title={tooltip}
                                className={`badge inline-flex items-center gap-1 ${
                                  blocking
                                    ? "bg-red-500/15 text-red-300"
                                    : "bg-yellow-500/15 text-yellow-300"
                                }`}
                              >
                                <ShieldAlert size={11} />
                                VeRO · {kws}
                              </span>
                            );
                          })()}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="td">{p.brand || "—"}</td>
                  <td className="td font-medium">{money(p.price, p.currency)}</td>
                  {!compact && <td className="td text-accent">{money(lp, p.currency)}</td>}
                  {!compact && (
                    <td
                      className={`td font-medium ${
                        profit.net === null
                          ? "text-muted"
                          : profit.net >= 0
                          ? "text-accent"
                          : "text-red-400"
                      }`}
                      title={
                        profit.net === null
                          ? "Set Amazon price to compute net profit"
                          : `Sale ${money(profit.breakdown.sale, p.currency)} − FVF ${money(profit.breakdown.fvf, p.currency)} − Promoted ${money(profit.breakdown.ad, p.currency)} − Per-order ${money(profit.breakdown.per_order_fee, p.currency)} − Cost ${money(profit.breakdown.amazon_price, p.currency)} − Ship ${money(profit.breakdown.amazon_shipping, p.currency)}`
                      }
                    >
                      {profit.net === null ? "—" : (
                        <>
                          {money(profit.net, p.currency)}
                          {profit.netMargin !== null && (
                            <span className="ml-1 text-xs text-muted">({profit.netMargin}%)</span>
                          )}
                        </>
                      )}
                    </td>
                  )}
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
                      {listing?.listing_url ? (
                        <a
                          href={listing.listing_url}
                          target="_blank"
                          rel="noopener"
                          className="btn-primary text-xs"
                          title={`Listed on eBay at ${money(listing.last_price, listing.currency || p.currency)}`}
                        >
                          <CheckCircle2 size={14} />
                          Listed @ {money(listing.last_price, listing.currency || p.currency)}
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
