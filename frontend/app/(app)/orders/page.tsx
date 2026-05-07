"use client";

import { useEffect, useState } from "react";
import {
  ShoppingCart,
  RefreshCw,
  Loader2,
  Truck,
  ExternalLink,
  Copy,
  CheckCircle2,
  AlertCircle,
  Bot,
  Mail,
  Trash2,
} from "lucide-react";
import { api, Order, OutboundMessage } from "@/lib/api";
import { money, date } from "@/lib/format";

const CARRIERS = ["USPS", "FEDEX", "UPS", "DHL"];

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [flashMsg, setFlashMsg] = useState<string | null>(null);
  const [openOrderId, setOpenOrderId] = useState<string | null>(null);
  const [trackingDraft, setTrackingDraft] = useState<{
    tracking_number: string;
    carrier: string;
  }>({ tracking_number: "", carrier: "USPS" });
  const [submitting, setSubmitting] = useState(false);
  const [fulfilling, setFulfilling] = useState<string | null>(null);

  async function load() {
    try {
      setErr(null);
      const data = await api<Order[]>("/api/orders");
      setOrders(data);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function syncFromEbay() {
    setSyncing(true);
    setErr(null);
    try {
      const res = await api<{ ok: boolean; synced: number }>("/api/orders/sync", {
        method: "POST",
        body: JSON.stringify({}),
      });
      flash(`Synced ${res.synced} orders from eBay`);
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSyncing(false);
    }
  }

  function flash(m: string) {
    setFlashMsg(m);
    setTimeout(() => setFlashMsg(null), 2500);
  }

  async function copyAddress(o: Order) {
    const lines = [
      o.ship_to_name,
      o.ship_to_line1,
      o.ship_to_line2,
      [o.ship_to_city, o.ship_to_state, o.ship_to_postal].filter(Boolean).join(", "),
      o.ship_to_country,
    ].filter(Boolean);
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      flash("Address copied");
    } catch {
      flash("Could not copy");
    }
  }

  async function fulfillOnAmazon(o: Order, dryRun: boolean) {
    setFulfilling(o.ebay_order_id);
    try {
      const res = await api<{
        ok: boolean;
        status: string;
        amazon_order_id: string | null;
        error: string | null;
        screenshot_path: string | null;
      }>(`/api/orders/${encodeURIComponent(o.ebay_order_id)}/fulfill`, {
        method: "POST",
        body: JSON.stringify({ dry_run: dryRun }),
      });
      if (res.ok) {
        flash(
          res.status === "dry_run"
            ? `Dry-run reached review page${res.screenshot_path ? " — screenshot saved" : ""}`
            : `Placed Amazon order ${res.amazon_order_id || ""}`.trim(),
        );
      } else {
        flash(`Fulfill failed: ${res.error || "unknown error"}`);
      }
      await load();
    } catch (e: any) {
      flash(`Failed: ${e.message}`);
    } finally {
      setFulfilling(null);
    }
  }

  async function submitTracking(o: Order) {
    if (!trackingDraft.tracking_number) {
      flash("Enter a tracking number");
      return;
    }
    setSubmitting(true);
    try {
      await api(`/api/orders/${encodeURIComponent(o.ebay_order_id)}/tracking`, {
        method: "POST",
        body: JSON.stringify(trackingDraft),
      });
      flash("Tracking pushed to eBay");
      setOpenOrderId(null);
      setTrackingDraft({ tracking_number: "", carrier: "USPS" });
      await load();
    } catch (e: any) {
      flash(`Failed: ${e.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Orders</h1>
          <p className="text-sm text-muted">
            eBay orders pulled from your seller account. Click an order to fulfill on
            Amazon and push tracking back to eBay.
          </p>
        </div>
        <button onClick={syncFromEbay} disabled={syncing} className="btn-primary">
          {syncing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          Sync from eBay
        </button>
      </div>

      {flashMsg && (
        <div className="flex items-center gap-2 rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-sm text-accent">
          <CheckCircle2 size={14} /> {flashMsg}
        </div>
      )}
      {err && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          <AlertCircle size={14} className="mt-0.5" /> {err}
        </div>
      )}

      {loading ? (
        <div className="card text-muted">Loading…</div>
      ) : orders.length === 0 ? (
        <div className="card text-center text-muted">
          <ShoppingCart className="mx-auto mb-3 opacity-50" size={32} />
          <div className="font-medium text-white">No orders yet</div>
          <div className="mt-1 text-sm">
            Click <b>Sync from eBay</b> to pull recent orders. Sandbox orders appear once
            eBay's sandbox tooling generates a test sale on a published listing.
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {orders.map((o) => {
            const expanded = openOrderId === o.ebay_order_id;
            return (
              <div key={o.ebay_order_id} className="card !p-0 overflow-hidden">
                <button
                  onClick={() => setOpenOrderId(expanded ? null : o.ebay_order_id)}
                  className="flex w-full items-center gap-4 px-4 py-3 text-left hover:bg-panel2"
                >
                  <ShoppingCart size={18} className="text-muted" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs text-muted">{o.ebay_order_id}</span>
                      <span
                        className={`badge ${
                          o.tracking_number
                            ? "bg-accent/15 text-accent"
                            : o.status === "shipped"
                            ? "bg-accent/15 text-accent"
                            : "bg-blue-500/15 text-blue-300"
                        }`}
                      >
                        {o.tracking_number ? "shipped" : o.status}
                      </span>
                    </div>
                    <div className="mt-0.5 text-sm font-medium">
                      {o.ship_to_name || o.buyer_username || "—"} ·{" "}
                      <span className="text-muted">{o.product_asin || o.sku}</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-6 text-right text-xs">
                    <div>
                      <div className="text-muted">Sale</div>
                      <div className="font-medium">{money(o.sale_price, o.currency)}</div>
                    </div>
                    <div>
                      <div className="text-muted">Cost</div>
                      <div className="font-medium">{money(o.amazon_cost, o.currency)}</div>
                    </div>
                    <div>
                      <div className="text-muted">Profit</div>
                      <div className={`font-medium ${(o.profit || 0) >= 0 ? "text-accent" : "text-red-400"}`}>
                        {money(o.profit, o.currency)}
                      </div>
                    </div>
                  </div>
                </button>

                {expanded && (
                  <div className="border-t border-border bg-panel2 p-4">
                    <div className="grid gap-4 md:grid-cols-2">
                      <div>
                        <h4 className="text-xs uppercase text-muted">Ship to</h4>
                        <div className="mt-1 text-sm">
                          <div className="font-medium">{o.ship_to_name || "—"}</div>
                          <div>{o.ship_to_line1}</div>
                          {o.ship_to_line2 && <div>{o.ship_to_line2}</div>}
                          <div>
                            {[o.ship_to_city, o.ship_to_state, o.ship_to_postal]
                              .filter(Boolean)
                              .join(", ")}
                          </div>
                          <div>{o.ship_to_country}</div>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          <button onClick={() => copyAddress(o)} className="btn-secondary text-xs">
                            <Copy size={12} /> Copy address
                          </button>
                          {o.product_asin && (
                            <a
                              href={`https://www.amazon.com/dp/${o.product_asin}`}
                              target="_blank"
                              rel="noopener"
                              className="btn-secondary text-xs"
                            >
                              <ExternalLink size={12} /> Open on Amazon
                            </a>
                          )}
                          <button
                            onClick={() => fulfillOnAmazon(o, true)}
                            disabled={fulfilling === o.ebay_order_id}
                            className="btn-secondary text-xs"
                            title="Drives Amazon checkout up to the review page; never places the order."
                          >
                            {fulfilling === o.ebay_order_id ? (
                              <Loader2 size={12} className="animate-spin" />
                            ) : (
                              <Bot size={12} />
                            )}
                            Fulfill (dry-run)
                          </button>
                          <button
                            onClick={() => {
                              if (!confirm("Place a REAL Amazon order for this item? This will charge your card.")) return;
                              fulfillOnAmazon(o, false);
                            }}
                            disabled={fulfilling === o.ebay_order_id}
                            className="btn-primary text-xs"
                          >
                            <Bot size={12} /> Fulfill (live)
                          </button>
                        </div>
                      </div>

                      <div>
                        <h4 className="text-xs uppercase text-muted">Tracking</h4>
                        {o.tracking_number ? (
                          <div className="mt-1 text-sm">
                            <div className="font-mono">{o.tracking_number}</div>
                            <div className="text-xs text-muted">
                              {o.tracking_carrier} · submitted{" "}
                              {o.tracking_submitted_at ? date(o.tracking_submitted_at) : ""}
                            </div>
                          </div>
                        ) : (
                          <div className="mt-1 space-y-2">
                            <div className="flex gap-2">
                              <select
                                value={trackingDraft.carrier}
                                onChange={(e) =>
                                  setTrackingDraft({
                                    ...trackingDraft,
                                    carrier: e.target.value,
                                  })
                                }
                                className="input text-sm"
                              >
                                {CARRIERS.map((c) => (
                                  <option key={c} value={c}>
                                    {c}
                                  </option>
                                ))}
                              </select>
                              <input
                                placeholder="Tracking number"
                                value={trackingDraft.tracking_number}
                                onChange={(e) =>
                                  setTrackingDraft({
                                    ...trackingDraft,
                                    tracking_number: e.target.value,
                                  })
                                }
                                className="input flex-1 text-sm"
                              />
                            </div>
                            <button
                              onClick={() => submitTracking(o)}
                              disabled={submitting}
                              className="btn-primary text-sm"
                            >
                              {submitting ? (
                                <Loader2 size={14} className="animate-spin" />
                              ) : (
                                <Truck size={14} />
                              )}
                              Submit tracking to eBay
                            </button>
                          </div>
                        )}
                      </div>
                    </div>

                    <OrderMessages
                      orderId={o.ebay_order_id}
                      onFlash={flash}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

const ADDITIONAL_TEMPLATES = [
  { slug: "delivered", label: "Delivered check-in" },
  { slug: "feedback_request", label: "Feedback request" },
];

function OrderMessages({
  orderId,
  onFlash,
}: {
  orderId: string;
  onFlash: (msg: string) => void;
}) {
  const [messages, setMessages] = useState<OutboundMessage[]>([]);
  const [busy, setBusy] = useState<number | null>(null);
  const [queueing, setQueueing] = useState(false);

  async function load() {
    try {
      const res = await api<OutboundMessage[]>(
        `/api/messages/outbound?order_id=${encodeURIComponent(orderId)}`,
      );
      setMessages(res);
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    load();
  }, [orderId]);

  async function copyAndMarkSent(m: OutboundMessage) {
    setBusy(m.id);
    try {
      await navigator.clipboard.writeText(`Subject: ${m.subject}\n\n${m.body}`);
      onFlash("Copied — pasting into eBay messages…");
      window.open("https://www.ebay.com/mesg/", "_blank", "noopener");
      await api(`/api/messages/outbound/${m.id}/mark-sent`, { method: "POST" });
      await load();
    } catch (e: any) {
      onFlash(`Failed: ${e.message}`);
    } finally {
      setBusy(null);
    }
  }

  async function discard(m: OutboundMessage) {
    if (!confirm("Discard this queued message?")) return;
    setBusy(m.id);
    try {
      await api(`/api/messages/outbound/${m.id}`, { method: "DELETE" });
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function queueAdditional(slug: string) {
    setQueueing(true);
    try {
      await api(`/api/orders/${encodeURIComponent(orderId)}/messages`, {
        method: "POST",
        body: JSON.stringify({ template_slug: slug, trigger_event: "manual" }),
      });
      onFlash(`Queued ${slug.replace("_", " ")} message`);
      await load();
    } catch (e: any) {
      onFlash(`Failed: ${e.message}`);
    } finally {
      setQueueing(false);
    }
  }

  // Hide templates already queued for this order so we don't double-queue
  const queuedSlugs = new Set(messages.map((m) => m.template_slug));
  const remaining = ADDITIONAL_TEMPLATES.filter((t) => !queuedSlugs.has(t.slug));

  return (
    <div className="mt-4 border-t border-border pt-4">
      <div className="flex items-center justify-between gap-2">
        <h4 className="flex items-center gap-2 text-xs uppercase text-muted">
          <Mail size={14} /> Buyer messages
        </h4>
        {remaining.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {remaining.map((t) => (
              <button
                key={t.slug}
                onClick={() => queueAdditional(t.slug)}
                disabled={queueing}
                className="btn-secondary text-xs"
              >
                + {t.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {messages.length === 0 ? (
        <div className="mt-2 text-xs text-muted">
          No queued messages. <code>order_confirmed</code> is auto-queued on order sync; <code>shipped</code> is auto-queued when tracking is submitted.
        </div>
      ) : (
        <ul className="mt-2 space-y-2">
          {messages.map((m) => (
            <li key={m.id} className="rounded-lg border border-border bg-panel p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm">{m.subject}</span>
                    <span
                      className={`badge text-[10px] ${
                        m.status === "sent"
                          ? "bg-accent/15 text-accent"
                          : "bg-blue-500/15 text-blue-300"
                      }`}
                    >
                      {m.status}
                    </span>
                    <span className="text-[10px] text-muted">
                      {m.template_slug} · {m.trigger_event}
                    </span>
                  </div>
                  <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words font-sans text-xs text-white/70">
                    {m.body}
                  </pre>
                </div>
                <div className="flex shrink-0 flex-col gap-1">
                  {m.status === "queued" ? (
                    <button
                      onClick={() => copyAndMarkSent(m)}
                      disabled={busy === m.id}
                      className="btn-primary text-xs"
                      title="Copy to clipboard, open eBay messages, mark as sent"
                    >
                      {busy === m.id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <Copy size={12} />
                      )}
                      Copy &amp; send
                    </button>
                  ) : (
                    <span className="text-[10px] text-muted">
                      Sent {m.sent_at ? new Date(m.sent_at).toLocaleString() : ""}
                    </span>
                  )}
                  <button
                    onClick={() => discard(m)}
                    disabled={busy === m.id}
                    className="btn-danger text-xs"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
