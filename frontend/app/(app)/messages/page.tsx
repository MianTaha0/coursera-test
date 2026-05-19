"use client";

import { useEffect, useMemo, useState } from "react";
import {
  MessageSquare,
  Plus,
  Save,
  Trash2,
  Copy,
  CheckCircle2,
  Loader2,
  Inbox,
  RefreshCw,
  Bot,
} from "lucide-react";
import { api, InboundMessage, InboundRule, MessageTemplate, OutboundMessage } from "@/lib/api";

const TEMPLATE_VARIABLES = [
  "buyer_name",
  "item_title",
  "order_id",
  "tracking_number",
  "carrier",
  "est_delivery_date",
  "seller_name",
];

const SAMPLE_VARS: Record<string, string> = {
  buyer_name: "Alex",
  item_title: "Lightning Charger Cable 6ft",
  order_id: "12-34567-89012",
  tracking_number: "9400111899223344556677",
  carrier: "USPS",
  est_delivery_date: "Thursday, May 14",
  seller_name: "Taha",
};

function fillTemplate(text: string, vars: Record<string, string>): string {
  let out = text;
  for (const [k, v] of Object.entries(vars)) {
    out = out.replaceAll(`{${k}}`, v);
  }
  return out;
}

export default function MessagesPage() {
  const [tab, setTab] = useState<"inbox" | "templates" | "rules">("inbox");
  const [unread, setUnread] = useState<number>(0);

  // Poll the unread count so the tab badge stays current.
  useEffect(() => {
    let alive = true;
    async function tick() {
      try {
        const rows = await api<InboundMessage[]>("/api/messages/inbound?needs_reply=true");
        if (alive) setUnread(rows.length);
      } catch {
        /* ignore — backend may be down */
      }
    }
    tick();
    const t = setInterval(tick, 30_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Messages</h1>
        <div className="flex rounded-lg border border-border bg-panel2 p-1">
          <button
            onClick={() => setTab("inbox")}
            className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-sm ${
              tab === "inbox" ? "bg-accent/15 text-accent" : "text-muted hover:text-white"
            }`}
          >
            <Inbox size={14} /> Inbox
            {unread > 0 && (
              <span className="rounded-full bg-red-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                {unread}
              </span>
            )}
          </button>
          <button
            onClick={() => setTab("templates")}
            className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-sm ${
              tab === "templates" ? "bg-accent/15 text-accent" : "text-muted hover:text-white"
            }`}
          >
            <MessageSquare size={14} /> Templates
          </button>
          <button
            onClick={() => setTab("rules")}
            className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-sm ${
              tab === "rules" ? "bg-accent/15 text-accent" : "text-muted hover:text-white"
            }`}
          >
            <Bot size={14} /> Auto-reply rules
          </button>
        </div>
      </div>

      {tab === "inbox" && <InboxView onUnreadChange={setUnread} />}
      {tab === "templates" && <TemplatesView />}
      {tab === "rules" && <RulesView />}
    </div>
  );
}

function TemplatesView() {
  const [templates, setTemplates] = useState<MessageTemplate[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Partial<MessageTemplate>>({});
  const [vars, setVars] = useState<Record<string, string>>(SAMPLE_VARS);
  const [busy, setBusy] = useState(false);
  const [flashMsg, setFlashMsg] = useState<string | null>(null);

  async function load(selectId?: number) {
    const res = await api<MessageTemplate[]>("/api/message-templates");
    setTemplates(res);
    if (selectId !== undefined) {
      setSelectedId(selectId);
    } else if (selectedId === null && res.length) {
      setSelectedId(res[0].id);
    }
  }

  useEffect(() => {
    load().catch((e) => setFlashMsg(e.message));
  }, []);

  const selected = useMemo(
    () => templates?.find((t) => t.id === selectedId) || null,
    [templates, selectedId],
  );

  useEffect(() => {
    if (selected) {
      setDraft({
        name: selected.name,
        kind: selected.kind,
        subject: selected.subject,
        body: selected.body,
      });
    }
  }, [selected]);

  function flash(msg: string) {
    setFlashMsg(msg);
    setTimeout(() => setFlashMsg(null), 2500);
  }

  async function saveDraft() {
    if (!selected) return;
    setBusy(true);
    try {
      await api(`/api/message-templates/${selected.id}`, {
        method: "PUT",
        body: JSON.stringify({
          name: draft.name,
          kind: draft.kind || "custom",
          subject: draft.subject,
          body: draft.body,
        }),
      });
      await load(selected.id);
      flash("Saved");
    } catch (e: any) {
      flash(e.message || "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function createNew() {
    setBusy(true);
    try {
      const res = await api<MessageTemplate>("/api/message-templates", {
        method: "POST",
        body: JSON.stringify({
          name: "New template",
          kind: "custom",
          subject: "Subject — {item_title}",
          body: "Hi {buyer_name},\n\n…\n\nThanks,\n{seller_name}",
        }),
      });
      await load(res.id);
      flash("Template created");
    } finally {
      setBusy(false);
    }
  }

  async function removeTemplate() {
    if (!selected) return;
    if (!confirm(`Delete template "${selected.name}"?`)) return;
    setBusy(true);
    try {
      await api(`/api/message-templates/${selected.id}`, { method: "DELETE" });
      setSelectedId(null);
      await load();
      flash("Deleted");
    } finally {
      setBusy(false);
    }
  }

  async function copyPreview() {
    const text = `Subject: ${fillTemplate(draft.subject || "", vars)}\n\n${fillTemplate(draft.body || "", vars)}`;
    try {
      await navigator.clipboard.writeText(text);
      flash("Copied to clipboard");
    } catch {
      flash("Could not copy");
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted">
          Templates for buyer communication. Fill variables on the right to
          preview, then copy into eBay's message center.
        </p>
        <button onClick={createNew} className="btn-primary" disabled={busy}>
          <Plus size={16} /> New template
        </button>
      </div>

      {flashMsg && (
        <div className="flex items-center gap-2 rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-sm text-accent">
          <CheckCircle2 size={14} /> {flashMsg}
        </div>
      )}

      {templates === null ? (
        <div className="card text-muted">Loading…</div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[220px_1fr_320px]">
          {/* Template list */}
          <div className="card !p-2">
            <ul className="space-y-1">
              {templates.map((t) => (
                <li key={t.id}>
                  <button
                    onClick={() => setSelectedId(t.id)}
                    className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm ${
                      t.id === selectedId
                        ? "bg-accent/15 text-accent"
                        : "text-white/85 hover:bg-panel2"
                    }`}
                  >
                    <MessageSquare size={14} />
                    <div className="min-w-0 flex-1">
                      <div className="line-clamp-1 font-medium">{t.name}</div>
                      <div className="text-xs text-muted">{t.kind}</div>
                    </div>
                  </button>
                </li>
              ))}
              {!templates.length && (
                <li className="px-3 py-3 text-sm text-muted">
                  No templates yet. Click "New template" to start.
                </li>
              )}
            </ul>
          </div>

          {/* Editor */}
          {selected ? (
            <div className="card space-y-3">
              <div>
                <label className="text-xs uppercase text-muted">Name</label>
                <input
                  className="input mt-1 w-full"
                  value={draft.name || ""}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                />
              </div>
              <div>
                <label className="text-xs uppercase text-muted">Subject</label>
                <input
                  className="input mt-1 w-full"
                  value={draft.subject || ""}
                  onChange={(e) => setDraft({ ...draft, subject: e.target.value })}
                />
              </div>
              <div>
                <label className="text-xs uppercase text-muted">Body</label>
                <textarea
                  className="input mt-1 w-full font-mono text-sm"
                  rows={14}
                  value={draft.body || ""}
                  onChange={(e) => setDraft({ ...draft, body: e.target.value })}
                />
              </div>

              <div className="flex flex-wrap gap-2">
                <button onClick={saveDraft} className="btn-primary text-sm" disabled={busy}>
                  {busy ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                  Save
                </button>
                <button onClick={removeTemplate} className="btn-danger text-sm" disabled={busy}>
                  <Trash2 size={14} /> Delete
                </button>
              </div>

              <div className="rounded-lg border border-border bg-panel2 p-3 text-xs text-muted">
                <div className="mb-1 font-medium text-white/70">Available variables</div>
                <div className="flex flex-wrap gap-1.5">
                  {TEMPLATE_VARIABLES.map((v) => (
                    <code
                      key={v}
                      className="cursor-pointer rounded bg-panel px-1.5 py-0.5 hover:bg-accent/20 hover:text-accent"
                      onClick={() => {
                        const insert = `{${v}}`;
                        setDraft({ ...draft, body: (draft.body || "") + insert });
                      }}
                    >
                      {`{${v}}`}
                    </code>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="card text-muted">Pick a template to edit.</div>
          )}

          {/* Preview / variables */}
          <div className="card space-y-3">
            <div>
              <h3 className="text-sm font-semibold">Variables</h3>
              <p className="text-xs text-muted">Fill these to preview the rendered message.</p>
            </div>
            <div className="space-y-2">
              {TEMPLATE_VARIABLES.map((v) => (
                <div key={v}>
                  <label className="text-xs text-muted">{v}</label>
                  <input
                    className="input mt-0.5 w-full text-sm"
                    value={vars[v] || ""}
                    onChange={(e) => setVars({ ...vars, [v]: e.target.value })}
                  />
                </div>
              ))}
            </div>

            <div className="border-t border-border pt-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">Preview</h3>
                <button onClick={copyPreview} className="btn-secondary text-xs">
                  <Copy size={12} /> Copy
                </button>
              </div>
              <div className="mt-2 rounded-lg border border-border bg-panel2 p-3 text-xs">
                <div className="mb-2 font-semibold text-white/80">
                  {fillTemplate(draft.subject || "", vars)}
                </div>
                <pre className="whitespace-pre-wrap font-sans text-white/80">
                  {fillTemplate(draft.body || "", vars)}
                </pre>
              </div>
              <p className="mt-2 text-xs text-muted">
                Open eBay's <a href="https://www.ebay.com/mesg/" target="_blank" rel="noopener" className="text-accent hover:underline">message center</a> and paste.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ===========================================================================
// Inbox (Phase 4.2) — threaded buyer ↔ seller conversations
// ===========================================================================

type Thread = {
  key: string;                 // group key (order or buyer)
  ebay_order_id: string | null;
  sender_username: string;
  ebay_item_id: string | null;
  inbound: InboundMessage[];
  outbound: OutboundMessage[];
  needs_reply_count: number;
  last_received_at: string;
};

function groupThreads(
  inbound: InboundMessage[],
  outbound: OutboundMessage[],
): Thread[] {
  const map = new Map<string, Thread>();
  function keyFor(m: { ebay_order_id: string | null; sender_username?: string | null }) {
    return m.ebay_order_id || `buyer:${m.sender_username || "unknown"}`;
  }
  for (const m of inbound) {
    const key = keyFor(m);
    if (!map.has(key)) {
      map.set(key, {
        key,
        ebay_order_id: m.ebay_order_id,
        sender_username: m.sender_username || "(unknown buyer)",
        ebay_item_id: m.ebay_item_id,
        inbound: [],
        outbound: [],
        needs_reply_count: 0,
        last_received_at: m.received_at,
      });
    }
    const t = map.get(key)!;
    t.inbound.push(m);
    if (m.needs_reply) t.needs_reply_count++;
    if (m.received_at > t.last_received_at) t.last_received_at = m.received_at;
  }
  for (const m of outbound) {
    // outbound rows only have ebay_order_id, no sender — they belong to an
    // order thread if one exists.
    const key = m.ebay_order_id || "";
    if (!key || !map.has(key)) continue;
    map.get(key)!.outbound.push(m);
  }
  return Array.from(map.values()).sort((a, b) =>
    b.last_received_at.localeCompare(a.last_received_at),
  );
}

function InboxView({ onUnreadChange }: { onUnreadChange?: (n: number) => void }) {
  const [inbound, setInbound] = useState<InboundMessage[] | null>(null);
  const [outbound, setOutbound] = useState<OutboundMessage[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const [inb, outb] = await Promise.all([
        api<InboundMessage[]>("/api/messages/inbound?limit=500"),
        api<OutboundMessage[]>("/api/messages/outbound?limit=500"),
      ]);
      setInbound(inb);
      setOutbound(outb);
      onUnreadChange?.(inb.filter((m) => m.needs_reply).length);
    } catch (e: any) {
      setError(e.message || "Failed to load");
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const threads = useMemo(() => groupThreads(inbound || [], outbound), [inbound, outbound]);
  const selected = threads.find((t) => t.key === selectedKey) || null;

  async function pollNow() {
    setBusy(true);
    try {
      await api("/api/messages/inbound/poll-now", { method: "POST" });
      await load();
    } catch (e: any) {
      setError(e.message || "Poll failed");
    } finally {
      setBusy(false);
    }
  }

  async function markReplied(id: number) {
    setBusy(true);
    try {
      await api(`/api/messages/inbound/${id}/mark-replied`, { method: "POST" });
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function markRead(id: number) {
    try {
      await api(`/api/messages/inbound/${id}/mark-read`, { method: "POST" });
      await load();
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted">
          Buyer messages pulled from eBay every 5 min. Click a thread to read,
          then reply via the existing message-template flow.
        </p>
        <button onClick={pollNow} disabled={busy} className="btn-secondary text-xs">
          {busy ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          Poll now
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {inbound === null ? (
        <div className="card text-muted">Loading…</div>
      ) : threads.length === 0 ? (
        <div className="card text-center text-muted">
          No buyer messages yet. eBay will surface them here once buyers reach out.
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[320px,1fr]">
          {/* Thread list */}
          <div className="space-y-1 lg:max-h-[70vh] lg:overflow-y-auto">
            {threads.map((t) => (
              <button
                key={t.key}
                onClick={() => {
                  setSelectedKey(t.key);
                  // mark every unread message in this thread as read
                  for (const m of t.inbound) {
                    if (!m.read_at) markRead(m.id);
                  }
                }}
                className={`block w-full rounded-lg border p-3 text-left ${
                  selectedKey === t.key
                    ? "border-accent/40 bg-accent/5"
                    : "border-border bg-panel2 hover:border-accent/20"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="truncate font-medium">{t.sender_username}</div>
                  {t.needs_reply_count > 0 && (
                    <span className="rounded-full bg-red-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                      {t.needs_reply_count}
                    </span>
                  )}
                </div>
                <div className="mt-1 text-xs text-muted">
                  {t.ebay_order_id ? (
                    <span className="font-mono">Order {t.ebay_order_id}</span>
                  ) : (
                    <span>No order link</span>
                  )}
                </div>
                <div className="mt-1 truncate text-xs text-white/70">
                  {t.inbound[t.inbound.length - 1]?.subject || "(no subject)"}
                </div>
              </button>
            ))}
          </div>

          {/* Thread view */}
          {selected ? (
            <ThreadView thread={selected} onMarkReplied={markReplied} />
          ) : (
            <div className="card text-center text-muted">Select a thread to read.</div>
          )}
        </div>
      )}
    </div>
  );
}

function ThreadView({
  thread,
  onMarkReplied,
}: {
  thread: Thread;
  onMarkReplied: (id: number) => void;
}) {
  // Interleave inbound and outbound by timestamp.
  const items = useMemo(() => {
    type Item =
      | { type: "in"; at: string; msg: InboundMessage }
      | { type: "out"; at: string; msg: OutboundMessage };
    const arr: Item[] = [
      ...thread.inbound.map((m): Item => ({ type: "in", at: m.received_at, msg: m })),
      ...thread.outbound.map((m): Item => ({ type: "out", at: m.sent_at || m.created_at, msg: m })),
    ];
    return arr.sort((a, b) => a.at.localeCompare(b.at));
  }, [thread]);

  return (
    <div className="card space-y-3">
      <div className="flex flex-wrap items-center gap-2 border-b border-border pb-3">
        <div className="text-sm">
          <span className="font-semibold">{thread.sender_username}</span>
          {thread.ebay_order_id && (
            <span className="ml-2 font-mono text-xs text-muted">Order {thread.ebay_order_id}</span>
          )}
        </div>
        <a
          href="https://www.ebay.com/mesg/"
          target="_blank"
          rel="noopener"
          className="btn-secondary ml-auto text-xs"
        >
          Reply on eBay
        </a>
      </div>

      <div className="space-y-3">
        {items.map((it, i) =>
          it.type === "in" ? (
            <div key={`in-${it.msg.id}`} className="rounded-lg border border-border bg-panel2 p-3">
              <div className="flex items-center gap-2 text-xs text-muted">
                <Inbox size={12} className="text-blue-300" />
                <b className="text-white/90">{it.msg.sender_username}</b>
                <span>· {new Date(it.msg.received_at).toLocaleString()}</span>
                {it.msg.auto_replied ? (
                  <span className="ml-auto inline-flex items-center gap-1 text-accent">
                    <Bot size={11} /> auto-replied
                  </span>
                ) : it.msg.needs_reply ? (
                  <button
                    onClick={() => onMarkReplied(it.msg.id)}
                    className="ml-auto btn-secondary text-[10px] py-0.5 px-2"
                    title="Hide the 'needs reply' badge"
                  >
                    Mark replied
                  </button>
                ) : null}
              </div>
              {it.msg.subject && (
                <div className="mt-1 text-sm font-medium">{it.msg.subject}</div>
              )}
              <div className="mt-1 whitespace-pre-wrap text-sm text-white/90">
                {it.msg.body || "(no body)"}
              </div>
            </div>
          ) : (
            <div
              key={`out-${it.msg.id}`}
              className="ml-8 rounded-lg border border-accent/20 bg-accent/5 p-3"
            >
              <div className="flex items-center gap-2 text-xs text-muted">
                <MessageSquare size={12} className="text-accent" />
                <b className="text-accent">You (Droply)</b>
                <span>· {new Date(it.at).toLocaleString()}</span>
                <span
                  className={`ml-auto badge ${
                    it.msg.status === "sent"
                      ? "bg-accent/15 text-accent"
                      : it.msg.status === "failed"
                      ? "bg-red-500/15 text-red-300"
                      : "bg-yellow-500/15 text-yellow-300"
                  }`}
                >
                  {it.msg.status}
                </span>
              </div>
              {it.msg.subject && (
                <div className="mt-1 text-sm font-medium">{it.msg.subject}</div>
              )}
              <div className="mt-1 whitespace-pre-wrap text-sm text-white/90">
                {it.msg.body}
              </div>
              {it.msg.error && (
                <div className="mt-1 text-xs text-red-300">⚠ {it.msg.error}</div>
              )}
            </div>
          ),
        )}
      </div>
    </div>
  );
}

// ===========================================================================
// Auto-reply rules (Phase 4.3) — pattern → reply template ladder
// ===========================================================================

function RulesView() {
  const [rules, setRules] = useState<InboundRule[] | null>(null);
  const [templates, setTemplates] = useState<MessageTemplate[]>([]);
  const [busy, setBusy] = useState<number | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [testSubject, setTestSubject] = useState("");
  const [testBody, setTestBody] = useState("Hi, where is my order? Has it shipped yet?");
  const [testResult, setTestResult] = useState<{
    matched: boolean;
    rule: InboundRule | null;
  } | null>(null);

  async function load() {
    setError(null);
    try {
      const [rs, ts] = await Promise.all([
        api<InboundRule[]>("/api/inbound-rules"),
        api<MessageTemplate[]>("/api/message-templates"),
      ]);
      setRules(rs);
      setTemplates(ts);
    } catch (e: any) {
      setError(e.message || "Failed to load rules");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function patch(r: InboundRule, update: Partial<InboundRule>) {
    setBusy(r.id);
    try {
      const next: any = {
        name: r.name,
        pattern: r.pattern,
        is_regex: !!r.is_regex,
        reply_template_slug: r.reply_template_slug,
        enabled: !!r.enabled,
        priority: r.priority,
        ...update,
      };
      await api(`/api/inbound-rules/${r.id}`, {
        method: "PUT",
        body: JSON.stringify(next),
      });
      await load();
    } catch (e: any) {
      setError(e.message || "Save failed");
    } finally {
      setBusy(null);
    }
  }

  async function create() {
    setBusy("new");
    try {
      await api("/api/inbound-rules", {
        method: "POST",
        body: JSON.stringify({
          name: "New rule",
          pattern: "",
          is_regex: false,
          reply_template_slug: "",
          enabled: true,
          priority: 100,
        }),
      });
      await load();
    } catch (e: any) {
      setError(e.message || "Create failed");
    } finally {
      setBusy(null);
    }
  }

  async function remove(r: InboundRule) {
    if (!confirm(`Delete rule "${r.name}"?`)) return;
    setBusy(r.id);
    try {
      await api(`/api/inbound-rules/${r.id}`, { method: "DELETE" });
      await load();
    } catch (e: any) {
      setError(e.message || "Delete failed");
    } finally {
      setBusy(null);
    }
  }

  async function runTest() {
    try {
      const r = await api<{ matched: boolean; rule: InboundRule | null }>(
        "/api/inbound-rules/test",
        { method: "POST", body: JSON.stringify({ subject: testSubject, body: testBody }) },
      );
      setTestResult(r);
    } catch (e: any) {
      setError(e.message || "Test failed");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted">
          Rules are checked in priority order (lower = higher priority). The
          first match wins. A rule with a reply template will auto-send when
          matched on a message tied to an eBay order; a rule with no template
          just flags the message for human attention.
        </p>
        <button onClick={create} disabled={busy === "new"} className="btn-primary text-xs">
          {busy === "new" ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
          New rule
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Test playground */}
      <div className="card">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Bot size={14} className="text-accent" /> Test the classifier
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <label className="text-xs uppercase text-muted">Subject</label>
            <input
              value={testSubject}
              onChange={(e) => setTestSubject(e.target.value)}
              className="input mt-1 w-full"
              placeholder="(optional)"
            />
          </div>
          <div>
            <label className="text-xs uppercase text-muted">Body</label>
            <input
              value={testBody}
              onChange={(e) => setTestBody(e.target.value)}
              className="input mt-1 w-full"
            />
          </div>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <button onClick={runTest} className="btn-secondary text-xs">
            Run match
          </button>
          {testResult && (
            <div className="text-xs">
              {testResult.matched && testResult.rule ? (
                <span className="text-accent">
                  ✓ Matched: <b>{testResult.rule.name}</b>{" "}
                  {testResult.rule.reply_template_slug ? (
                    <>
                      → auto-reply with <code>{testResult.rule.reply_template_slug}</code>
                    </>
                  ) : (
                    <>→ flag only (needs human)</>
                  )}
                </span>
              ) : (
                <span className="text-muted">No rule matched.</span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Rule rows */}
      {rules === null ? (
        <div className="card text-muted">Loading…</div>
      ) : (
        <div className="card space-y-2 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-muted">
              <tr>
                <th className="text-left py-2 px-2">Prio</th>
                <th className="text-left py-2 px-2">Name</th>
                <th className="text-left py-2 px-2">Pattern</th>
                <th className="text-left py-2 px-2">Regex?</th>
                <th className="text-left py-2 px-2">Reply with</th>
                <th className="text-left py-2 px-2">Enabled</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id} className="border-t border-border">
                  <td className="px-2 py-2 w-16">
                    <input
                      type="number"
                      value={r.priority}
                      onChange={(e) => patch(r, { priority: Number(e.target.value) })}
                      className="input w-14 text-xs"
                      disabled={busy === r.id}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <input
                      type="text"
                      value={r.name}
                      onChange={(e) => patch(r, { name: e.target.value })}
                      className="input w-full text-xs"
                      disabled={busy === r.id}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <input
                      type="text"
                      value={r.pattern}
                      onChange={(e) => patch(r, { pattern: e.target.value })}
                      className="input w-full font-mono text-xs"
                      disabled={busy === r.id}
                    />
                  </td>
                  <td className="px-2 py-2 text-center">
                    <input
                      type="checkbox"
                      checked={!!r.is_regex}
                      onChange={(e) => patch(r, { is_regex: e.target.checked ? 1 : 0 })}
                      disabled={busy === r.id}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <select
                      value={r.reply_template_slug}
                      onChange={(e) => patch(r, { reply_template_slug: e.target.value })}
                      className="input w-full text-xs"
                      disabled={busy === r.id}
                    >
                      <option value="">— flag only —</option>
                      {templates.map((t) => (
                        <option key={t.slug} value={t.slug}>
                          {t.slug}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-2 py-2 text-center">
                    <input
                      type="checkbox"
                      checked={!!r.enabled}
                      onChange={(e) => patch(r, { enabled: e.target.checked ? 1 : 0 })}
                      disabled={busy === r.id}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <button
                      onClick={() => remove(r)}
                      disabled={busy === r.id}
                      className="btn-danger text-xs"
                      title="Delete rule"
                    >
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
