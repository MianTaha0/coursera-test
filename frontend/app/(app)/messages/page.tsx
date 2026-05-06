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
} from "lucide-react";
import { api, MessageTemplate } from "@/lib/api";

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
        <div>
          <h1 className="text-2xl font-bold">Messages</h1>
          <p className="text-sm text-muted">
            Templates for buyer communication. Fill variables on the right to
            preview, then copy into eBay's message center.
          </p>
        </div>
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
