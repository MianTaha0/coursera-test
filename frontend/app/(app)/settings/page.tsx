"use client";

import { useEffect, useState } from "react";
import { Chrome, Server, CheckCircle2, XCircle, Download, Store, LogOut, Loader2, AlertTriangle, RefreshCw, Calculator, Truck, FileText, Eye, Plus, Trash2 } from "lucide-react";
import { api, API_URL, AppSettings, DescriptionTemplate, computeNet } from "@/lib/api";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

type EbayAccount = {
  id: number;
  label: string;
  sandbox: boolean;
  is_active: boolean;
  connected: boolean;
  token_valid: boolean;
  refresh_valid: boolean;
  token_connected_at: string | null;
  expires_at: number | null;
  created_at: string;
};

function EbaySection() {
  const params = useSearchParams();
  const [accounts, setAccounts] = useState<EbayAccount[] | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [flashMsg, setFlashMsg] = useState<string | null>(null);
  const [newLabel, setNewLabel] = useState("");

  async function load() {
    try {
      const a = await api<EbayAccount[]>("/api/ebay/accounts");
      setAccounts(a);
    } catch {
      setAccounts([]);
    }
  }

  useEffect(() => {
    load();
    if (params.get("ebay") === "connected") {
      setFlashMsg("eBay account connected successfully!");
      window.history.replaceState({}, "", "/settings");
    }
  }, [params]);

  async function activate(id: number) {
    setBusy(id);
    try {
      await api(`/api/ebay/accounts/${id}/activate`, { method: "POST" });
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function rename(id: number, current: string) {
    const label = prompt("Rename store", current);
    if (!label || label === current) return;
    setBusy(id);
    try {
      await api(`/api/ebay/accounts/${id}`, {
        method: "PUT",
        body: JSON.stringify({ label }),
      });
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function remove(id: number, label: string) {
    if (!confirm(`Delete "${label}"? Tokens for this account will be discarded.`)) return;
    setBusy(id);
    try {
      await api(`/api/ebay/accounts/${id}`, { method: "DELETE" });
      await load();
    } finally {
      setBusy(null);
    }
  }

  const addUrl = newLabel.trim()
    ? `${API_URL}/auth/ebay?label=${encodeURIComponent(newLabel.trim())}`
    : `${API_URL}/auth/ebay`;

  return (
    <div className="card">
      <div className="flex items-center gap-3">
        <Store size={20} className="text-muted" />
        <h2 className="text-lg font-semibold">eBay Accounts</h2>
        <span className="badge bg-yellow-500/15 text-yellow-400">Sandbox</span>
        <span className="ml-auto text-xs text-muted">
          {accounts?.length ?? 0} connected
        </span>
      </div>

      {flashMsg && (
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-sm text-accent">
          <CheckCircle2 size={16} /> {flashMsg}
        </div>
      )}

      <p className="mt-2 text-sm text-muted">
        Connect multiple eBay seller accounts. Operations like Publish, Sync,
        and List use the <b>active</b> account. Switch the active store any time.
      </p>

      {accounts === null ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-muted">
          <Loader2 size={16} className="animate-spin" /> Loading accounts…
        </div>
      ) : accounts.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed border-border bg-panel2 p-6 text-center text-sm text-muted">
          No eBay accounts connected yet.
        </div>
      ) : (
        <ul className="mt-4 space-y-2">
          {accounts.map((a) => (
            <li
              key={a.id}
              className={`rounded-lg border p-3 ${
                a.is_active
                  ? "border-accent/40 bg-accent/5"
                  : "border-border bg-panel2"
              }`}
            >
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <span className="font-medium truncate">{a.label}</span>
                  {a.is_active && (
                    <span className="badge bg-accent/15 text-accent">Active</span>
                  )}
                  {a.sandbox && (
                    <span className="badge bg-yellow-500/15 text-yellow-400">Sandbox</span>
                  )}
                  {!a.connected ? (
                    <span className="badge bg-red-500/15 text-red-300">Not connected</span>
                  ) : a.token_valid ? (
                    <span className="badge bg-blue-500/15 text-blue-300">Connected</span>
                  ) : (
                    <span className="badge bg-yellow-500/15 text-yellow-300">
                      <AlertTriangle size={11} /> Token expired
                    </span>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  {!a.is_active && a.connected && (
                    <button
                      onClick={() => activate(a.id)}
                      disabled={busy === a.id}
                      className="btn-secondary text-xs"
                    >
                      {busy === a.id ? <Loader2 size={12} className="animate-spin" /> : null}
                      Make active
                    </button>
                  )}
                  <a
                    href={`${API_URL}/auth/ebay?account_id=${a.id}`}
                    className="btn-secondary text-xs"
                  >
                    {a.connected ? "Reconnect" : "Connect"}
                  </a>
                  <button
                    onClick={() => rename(a.id, a.label)}
                    disabled={busy === a.id}
                    className="btn-secondary text-xs"
                  >
                    Rename
                  </button>
                  <button
                    onClick={() => remove(a.id, a.label)}
                    disabled={busy === a.id}
                    className="btn-danger text-xs"
                  >
                    <LogOut size={12} />
                  </button>
                </div>
              </div>
              {a.token_connected_at && (
                <div className="mt-1 text-xs text-muted">
                  Connected {new Date(a.token_connected_at).toLocaleString()}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 rounded-lg border border-border bg-panel2 p-3">
        <div className="text-xs uppercase text-muted">Add another store</div>
        <div className="mt-2 flex flex-wrap gap-2">
          <input
            type="text"
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            placeholder="Store label (e.g. 'Main UK store')"
            className="input flex-1 text-sm"
          />
          <a href={addUrl} className="btn-primary text-sm">
            <Store size={14} /> Connect new eBay account
          </a>
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-border bg-panel2 p-3 text-xs text-muted space-y-1">
        <p className="font-medium text-white/60">Setup required</p>
        <p>1. In the <a href="https://developer.ebay.com/my/keys" target="_blank" rel="noopener" className="text-accent hover:underline">eBay Developer Portal</a>, copy your <b>App ID</b> and <b>Cert ID</b>.</p>
        <p>2. Set <code>EBAY_CLIENT_ID</code>, <code>EBAY_CLIENT_SECRET</code>, and <code>EBAY_RU_NAME</code> in your backend environment.</p>
        <p>3. Update the <b>Auth accepted URL</b> in your eBay app to <code>{API_URL}/auth/ebay/callback</code>.</p>
        <p>4. Use the form above to add stores. Each store goes through its own OAuth consent.</p>
      </div>
    </div>
  );
}

function FeeStructureSection() {
  const [s, setS] = useState<AppSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api<AppSettings>("/api/settings").then(setS).catch(() => {});
  }, []);

  async function patch(update: Partial<AppSettings>) {
    setBusy(true);
    try {
      const fresh = await api<AppSettings>("/api/settings", {
        method: "PUT",
        body: JSON.stringify(update),
      });
      setS(fresh);
      setSavedAt(Date.now());
    } finally {
      setBusy(false);
    }
  }

  // Worked example so the user can sanity-check the math
  const example = computeNet(20, 20 * (1 + (s?.markup_percent ?? 30) / 100), s);

  return (
    <div className="card">
      <div className="flex items-center gap-3">
        <Calculator size={20} className="text-muted" />
        <h2 className="text-lg font-semibold">Fee structure</h2>
        {busy && <Loader2 size={14} className="animate-spin text-muted" />}
        {!busy && savedAt && Date.now() - savedAt < 3000 && (
          <span className="text-xs text-accent">Saved</span>
        )}
      </div>
      <p className="mt-1 text-xs text-muted">
        Used to compute net profit on the Products and Dashboard pages.
        Defaults are typical for US managed-payments sellers — adjust to match your account.
      </p>

      {!s ? (
        <div className="mt-3 text-sm text-muted">Loading…</div>
      ) : (
        <>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <FeeField
              label="eBay Final Value Fee"
              suffix="%"
              value={s.ebay_fvf_percent}
              onCommit={(v) => patch({ ebay_fvf_percent: v })}
              hint="Applied to (item price × FVF%). 13.25% is the default for most US categories."
            />
            <FeeField
              label="Per-order fee"
              prefix="$"
              value={s.ebay_per_order_fee}
              onCommit={(v) => patch({ ebay_per_order_fee: v })}
              hint="Flat fee charged on each completed sale."
            />
            <FeeField
              label="Promoted Listings ad rate"
              suffix="%"
              value={s.ebay_ad_rate_percent}
              onCommit={(v) => patch({ ebay_ad_rate_percent: v })}
              hint="Set to 0 if you don't run promoted listings."
            />
            <FeeField
              label="Amazon shipping cost"
              prefix="$"
              value={s.amazon_shipping_cost}
              onCommit={(v) => patch({ amazon_shipping_cost: v })}
              hint="If buying from Amazon adds shipping (no Prime), set it here."
            />
          </div>

          <div className="mt-4 rounded-lg border border-border bg-panel2 p-3 text-xs">
            <div className="font-semibold text-white/80">Worked example</div>
            <div className="mt-1 text-muted">
              Buy at $20.00 on Amazon, list at +{s.markup_percent}% (${(20 * (1 + s.markup_percent / 100)).toFixed(2)}) on eBay:
            </div>
            <ul className="mt-2 space-y-0.5 font-mono">
              <li>+ Sale price: ${example.breakdown.sale?.toFixed(2)}</li>
              <li>− eBay FVF ({s.ebay_fvf_percent}%): ${example.breakdown.fvf?.toFixed(2)}</li>
              <li>− Promoted Listings ({s.ebay_ad_rate_percent}%): ${example.breakdown.ad?.toFixed(2)}</li>
              <li>− Per-order fee: ${example.breakdown.per_order_fee?.toFixed(2)}</li>
              <li>− Amazon cost: ${example.breakdown.amazon_price?.toFixed(2)}</li>
              <li>− Amazon shipping: ${example.breakdown.amazon_shipping?.toFixed(2)}</li>
              <li className={`pt-1 font-bold ${(example.net ?? 0) >= 0 ? "text-accent" : "text-red-400"}`}>
                = Net: ${example.net?.toFixed(2)} ({example.netMargin}% margin)
              </li>
            </ul>
          </div>
        </>
      )}
    </div>
  );
}

function FeeField({
  label, value, onCommit, prefix, suffix, hint,
}: {
  label: string;
  value: number;
  onCommit: (v: number) => void;
  prefix?: string;
  suffix?: string;
  hint?: string;
}) {
  const [v, setV] = useState(String(value));
  useEffect(() => setV(String(value)), [value]);
  return (
    <div>
      <label className="text-xs uppercase text-muted">{label}</label>
      <div className="mt-1 flex items-center gap-1">
        {prefix && <span className="text-muted">{prefix}</span>}
        <input
          type="number"
          step="0.01"
          value={v}
          onChange={(e) => setV(e.target.value)}
          onBlur={() => {
            const n = Number(v);
            if (!isNaN(n) && n !== value) onCommit(n);
          }}
          className="input w-full text-sm"
        />
        {suffix && <span className="text-muted">{suffix}</span>}
      </div>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

function AutoRepriceSection() {
  const [s, setS] = useState<AppSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api<AppSettings>("/api/settings").then(setS).catch(() => {});
  }, []);

  async function patch(update: Partial<AppSettings>) {
    if (!s) return;
    const next = { ...s, ...update };
    setS(next);
    setSaving(true);
    try {
      const fresh = await api<AppSettings>("/api/settings", {
        method: "PUT",
        body: JSON.stringify(update),
      });
      setS(fresh);
      setSavedAt(Date.now());
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <div className="flex items-center gap-3">
        <RefreshCw size={20} className="text-muted" />
        <h2 className="text-lg font-semibold">Auto-reprice eBay listings</h2>
        {saving && <Loader2 size={14} className="animate-spin text-muted" />}
        {!saving && savedAt && Date.now() - savedAt < 3000 && (
          <span className="text-xs text-accent">Saved</span>
        )}
      </div>

      {!s ? (
        <div className="mt-3 text-sm text-muted">Loading…</div>
      ) : (
        <div className="mt-4 space-y-4">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={s.auto_reprice_enabled}
              onChange={(e) => patch({ auto_reprice_enabled: e.target.checked })}
              className="mt-1 h-4 w-4 accent-accent"
            />
            <div>
              <div className="font-medium">Enable auto-reprice</div>
              <p className="text-xs text-muted">
                When the extension reports a new Amazon price, Droply pushes a new
                price (Amazon × markup) to the matching eBay listing automatically.
              </p>
            </div>
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="text-xs uppercase text-muted">Flat markup %</label>
              <input
                type="number"
                step="0.5"
                value={s.markup_percent}
                onChange={(e) => patch({ markup_percent: Number(e.target.value) })}
                className="input mt-1 w-full"
                disabled={!s.auto_reprice_enabled}
              />
              <p className="mt-1 text-xs text-muted">
                Used when the tiered ladder below is empty. eBay price =
                Amazon × (1 + markup/100).
              </p>
            </div>
            <div>
              <label className="text-xs uppercase text-muted">Min change to trigger %</label>
              <input
                type="number"
                step="0.1"
                value={s.min_reprice_change_percent}
                onChange={(e) =>
                  patch({ min_reprice_change_percent: Number(e.target.value) })
                }
                className="input mt-1 w-full"
                disabled={!s.auto_reprice_enabled}
              />
              <p className="mt-1 text-xs text-muted">
                Skip tiny changes (e.g. rounding noise) below this threshold.
              </p>
            </div>
          </div>

          <MarginLadderEditor
            rules={s.margin_rules || []}
            disabled={!s.auto_reprice_enabled}
            onChange={(rules) => patch({ margin_rules: rules })}
          />
        </div>
      )}
    </div>
  );
}

function MarginLadderEditor({
  rules,
  disabled,
  onChange,
}: {
  rules: { max_price: number | null; markup_percent: number }[];
  disabled: boolean;
  onChange: (rules: { max_price: number | null; markup_percent: number }[]) => void;
}) {
  function update(i: number, patch: Partial<{ max_price: number | null; markup_percent: number }>) {
    const next = rules.map((r, idx) => (idx === i ? { ...r, ...patch } : r));
    onChange(next);
  }
  function add() {
    onChange([...rules, { max_price: rules.length === 0 ? 20 : null, markup_percent: 25 }]);
  }
  function remove(i: number) {
    onChange(rules.filter((_, idx) => idx !== i));
  }

  return (
    <div className="rounded-lg border border-border bg-panel2 p-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs uppercase text-muted">Tiered margin ladder</div>
          <p className="mt-1 text-xs text-muted">
            Applied in order. The first row whose <i>up to</i> price covers the
            Amazon price wins. Leave the cap blank for the top row.
          </p>
        </div>
        <button
          onClick={add}
          disabled={disabled}
          className="btn-secondary text-xs"
          title="Add a price bracket"
        >
          <Plus size={12} /> Add tier
        </button>
      </div>

      {rules.length === 0 ? (
        <div className="mt-3 rounded border border-dashed border-border bg-panel px-3 py-3 text-xs text-muted">
          No tiers configured — the flat markup above is used.
        </div>
      ) : (
        <div className="mt-3 space-y-2">
          {rules.map((r, i) => (
            <div key={i} className="grid grid-cols-[1fr,1fr,auto] gap-2">
              <div>
                <label className="text-xs text-muted">Up to (Amazon price)</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={r.max_price ?? ""}
                  placeholder="∞ (top tier)"
                  onChange={(e) =>
                    update(i, {
                      max_price: e.target.value === "" ? null : Number(e.target.value),
                    })
                  }
                  className="input mt-1 w-full"
                  disabled={disabled}
                />
              </div>
              <div>
                <label className="text-xs text-muted">Markup %</label>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  value={r.markup_percent}
                  onChange={(e) => update(i, { markup_percent: Number(e.target.value) })}
                  className="input mt-1 w-full"
                  disabled={disabled}
                />
              </div>
              <button
                onClick={() => remove(i)}
                disabled={disabled}
                className="btn-danger self-end text-xs"
                title="Remove tier"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AmazonFulfillmentSection() {
  const [s, setS] = useState<AppSettings | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api<AppSettings>("/api/settings").then((s) => {
      setS(s);
      setEmail(s.amazon_email || "");
    }).catch(() => {});
  }, []);

  async function patch(update: Record<string, unknown>) {
    setBusy(true);
    try {
      const fresh = await api<AppSettings>("/api/settings", {
        method: "PUT",
        body: JSON.stringify(update),
      });
      setS(fresh);
      if (fresh.amazon_email !== undefined) setEmail(fresh.amazon_email);
      if ("amazon_password" in update) setPassword("");
      setSavedAt(Date.now());
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="flex items-center gap-3">
        <Store size={20} className="text-muted" />
        <h2 className="text-lg font-semibold">Auto-fulfillment (Amazon)</h2>
        {busy && <Loader2 size={14} className="animate-spin text-muted" />}
        {!busy && savedAt && Date.now() - savedAt < 3000 && (
          <span className="text-xs text-accent">Saved</span>
        )}
      </div>

      <div className="mt-3 flex items-start gap-2 rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-300">
        <AlertTriangle size={14} className="mt-0.5 shrink-0" />
        <div>
          Credentials are stored in plaintext in <code>droply.db</code>. Don't commit
          the database. Amazon may flag automated checkouts — keep dry-run on
          until you've watched the flow succeed a few times.
        </div>
      </div>

      {!s ? (
        <div className="mt-4 text-sm text-muted">Loading…</div>
      ) : (
        <div className="mt-4 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="text-xs uppercase text-muted">Amazon email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onBlur={() => {
                  if (email !== s.amazon_email) patch({ amazon_email: email });
                }}
                placeholder="you@example.com"
                className="input mt-1 w-full"
              />
            </div>
            <div>
              <label className="text-xs uppercase text-muted">
                Amazon password {s.amazon_password_set && <span className="text-accent">(set)</span>}
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={s.amazon_password_set ? "•••••••• (leave blank to keep)" : "Set password"}
                className="input mt-1 w-full"
              />
              <div className="mt-1 flex gap-2">
                <button
                  className="btn-secondary text-xs"
                  onClick={() => password && patch({ amazon_password: password })}
                  disabled={!password || busy}
                >
                  Save password
                </button>
                {s.amazon_password_set && (
                  <button
                    className="btn-danger text-xs"
                    onClick={() => patch({ amazon_password: "__CLEAR__" })}
                  >
                    Clear
                  </button>
                )}
              </div>
            </div>
          </div>

          <div className="space-y-2 border-t border-border pt-3">
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={s.fulfillment_dry_run}
                onChange={(e) => patch({ fulfillment_dry_run: e.target.checked })}
                className="mt-1 h-4 w-4 accent-accent"
              />
              <div>
                <div className="font-medium">Dry-run mode</div>
                <p className="text-xs text-muted">
                  Drives the Amazon checkout up to the review page and captures a
                  screenshot, but never clicks <b>Place your order</b>. Recommended.
                </p>
              </div>
            </label>

            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={s.fulfillment_headless}
                onChange={(e) => patch({ fulfillment_headless: e.target.checked })}
                className="mt-1 h-4 w-4 accent-accent"
              />
              <div>
                <div className="font-medium">Headless</div>
                <p className="text-xs text-muted">
                  Run Chromium without a visible window. Disable for the first few
                  runs so you can intervene on CAPTCHA / 2FA.
                </p>
              </div>
            </label>

            <label className="flex items-start gap-3 cursor-pointer opacity-60">
              <input
                type="checkbox"
                checked={s.auto_fulfill_enabled}
                onChange={(e) => patch({ auto_fulfill_enabled: e.target.checked })}
                className="mt-1 h-4 w-4 accent-accent"
              />
              <div>
                <div className="font-medium">Auto-fulfill on order sync</div>
                <p className="text-xs text-muted">
                  Run the Amazon checkout automatically each time a new eBay order
                  is synced. Leave off until you've validated the flow manually.
                </p>
              </div>
            </label>
          </div>
        </div>
      )}
    </div>
  );
}

function AliExpressFulfillmentSection() {
  const [s, setS] = useState<AppSettings | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api<AppSettings>("/api/settings").then((s) => {
      setS(s);
      setEmail(s.aliexpress_email || "");
    }).catch(() => {});
  }, []);

  async function patch(update: Record<string, unknown>) {
    setBusy(true);
    try {
      const fresh = await api<AppSettings>("/api/settings", {
        method: "PUT",
        body: JSON.stringify(update),
      });
      setS(fresh);
      if (fresh.aliexpress_email !== undefined) setEmail(fresh.aliexpress_email);
      if ("aliexpress_password" in update) setPassword("");
      setSavedAt(Date.now());
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="flex items-center gap-3">
        <Store size={20} className="text-muted" />
        <h2 className="text-lg font-semibold">Auto-fulfillment (AliExpress)</h2>
        {busy && <Loader2 size={14} className="animate-spin text-muted" />}
        {!busy && savedAt && Date.now() - savedAt < 3000 && (
          <span className="text-xs text-accent">Saved</span>
        )}
      </div>

      <div className="mt-3 flex items-start gap-2 rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-300">
        <AlertTriangle size={14} className="mt-0.5 shrink-0" />
        <div>
          Credentials are stored in plaintext in <code>droply.db</code>. Use a
          dedicated AliExpress account (not your shopping account). The dry-run
          and headless toggles in the Amazon section above apply here too.
        </div>
      </div>

      {!s ? (
        <div className="mt-4 text-sm text-muted">Loading…</div>
      ) : (
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <label className="text-xs uppercase text-muted">AliExpress email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onBlur={() => {
                if (email !== s.aliexpress_email) patch({ aliexpress_email: email });
              }}
              placeholder="you@example.com"
              className="input mt-1 w-full"
            />
          </div>
          <div>
            <label className="text-xs uppercase text-muted">
              AliExpress password {s.aliexpress_password_set && <span className="text-accent">(set)</span>}
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={s.aliexpress_password_set ? "•••••••• (leave blank to keep)" : "Set password"}
              className="input mt-1 w-full"
            />
            <div className="mt-1 flex gap-2">
              <button
                className="btn-secondary text-xs"
                onClick={() => password && patch({ aliexpress_password: password })}
                disabled={!password || busy}
              >
                Save password
              </button>
              {s.aliexpress_password_set && (
                <button
                  className="btn-danger text-xs"
                  onClick={() => patch({ aliexpress_password: "__CLEAR__" })}
                >
                  Clear
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function DescriptionTemplatesSection() {
  const [templates, setTemplates] = useState<DescriptionTemplate[] | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [preview, setPreview] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadAll() {
    try {
      const [t, s] = await Promise.all([
        api<DescriptionTemplate[]>("/api/description-templates"),
        api<AppSettings>("/api/settings"),
      ]);
      setTemplates(t);
      setSettings(s);
      if (selectedId === null && t.length) {
        const def = t.find((x) => x.slug === (s.default_description_template_slug || "default")) || t[0];
        select(def);
      }
    } catch (e: any) {
      setError(e.message || "Failed to load templates");
    }
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function select(t: DescriptionTemplate) {
    setSelectedId(t.id);
    setName(t.name);
    setBody(t.body);
  }

  async function refreshPreview(id: number) {
    try {
      const r = await api<{ rendered: string }>(
        `/api/description-templates/${id}/preview`,
        { method: "POST" },
      );
      setPreview(r.rendered);
    } catch {
      setPreview("");
    }
  }

  useEffect(() => {
    if (selectedId !== null) refreshPreview(selectedId);
  }, [selectedId]);

  async function save() {
    if (selectedId === null) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/api/description-templates/${selectedId}`, {
        method: "PUT",
        body: JSON.stringify({ name, body }),
      });
      await loadAll();
      await refreshPreview(selectedId);
      setSavedAt(Date.now());
    } catch (e: any) {
      setError(e.message || "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const t = await api<DescriptionTemplate>("/api/description-templates", {
        method: "POST",
        body: JSON.stringify({ name: "New template", body: "<p>{title}</p>\n<p>{description}</p>" }),
      });
      await loadAll();
      select(t);
    } catch (e: any) {
      setError(e.message || "Create failed");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (selectedId === null) return;
    if (!confirm(`Delete template "${name}"?`)) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/api/description-templates/${selectedId}`, { method: "DELETE" });
      setSelectedId(null);
      setName("");
      setBody("");
      setPreview("");
      await loadAll();
    } catch (e: any) {
      setError(e.message || "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  async function setDefault(slug: string) {
    setBusy(true);
    try {
      await api<AppSettings>("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ default_description_template_slug: slug }),
      });
      await loadAll();
      setSavedAt(Date.now());
    } finally {
      setBusy(false);
    }
  }

  const defaultSlug = settings?.default_description_template_slug || "";

  return (
    <div className="card">
      <div className="flex items-center gap-3">
        <FileText size={20} className="text-muted" />
        <h2 className="text-lg font-semibold">Description templates</h2>
        {busy && <Loader2 size={14} className="animate-spin text-muted" />}
        {!busy && savedAt && Date.now() - savedAt < 3000 && (
          <span className="text-xs text-accent">Saved</span>
        )}
        <button
          onClick={create}
          className="btn-secondary ml-auto text-xs"
          disabled={busy}
          title="Create a new description template"
        >
          <Plus size={12} /> New
        </button>
      </div>

      <p className="mt-2 text-sm text-muted">
        Wraps the raw Amazon description with your seller branding when
        publishing to eBay. Variables: <code>{`{title}`}</code> <code>{`{brand}`}</code>{" "}
        <code>{`{asin}`}</code> <code>{`{description}`}</code>{" "}
        <code>{`{price}`}</code> <code>{`{currency}`}</code>, plus any key from
        the product's spec table (e.g. <code>{`{Color}`}</code>). Basic HTML is
        OK. The marked-default template is used for every publish.
      </p>

      {error && (
        <div className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {!templates ? (
        <div className="mt-4 text-sm text-muted">Loading…</div>
      ) : (
        <div className="mt-4 grid gap-4 lg:grid-cols-[200px,1fr,1fr]">
          {/* Template list */}
          <div className="space-y-1">
            {templates.map((t) => (
              <button
                key={t.id}
                onClick={() => select(t)}
                className={`block w-full rounded-lg border px-2 py-2 text-left text-sm ${
                  selectedId === t.id
                    ? "border-accent/40 bg-accent/5"
                    : "border-border bg-panel2 hover:border-accent/20"
                }`}
              >
                <div className="truncate font-medium">{t.name}</div>
                <div className="mt-1 flex items-center gap-1 text-xs text-muted">
                  <span className="font-mono">{t.slug}</span>
                  {t.slug === defaultSlug && (
                    <span className="badge bg-accent/15 text-accent">Default</span>
                  )}
                </div>
              </button>
            ))}
          </div>

          {/* Editor */}
          {selectedId !== null ? (
            <>
              <div className="space-y-3">
                <div>
                  <label className="text-xs uppercase text-muted">Name</label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="input mt-1 w-full"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase text-muted">Body (HTML allowed)</label>
                  <textarea
                    value={body}
                    onChange={(e) => setBody(e.target.value)}
                    rows={14}
                    className="input mt-1 w-full font-mono text-xs"
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <button onClick={save} disabled={busy} className="btn-primary text-xs">
                    {busy ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
                    Save
                  </button>
                  {templates.find((t) => t.id === selectedId)?.slug !== defaultSlug && (
                    <button
                      onClick={() => {
                        const t = templates.find((x) => x.id === selectedId);
                        if (t) setDefault(t.slug);
                      }}
                      disabled={busy}
                      className="btn-secondary text-xs"
                      title="Use this template for every publish"
                    >
                      Make default
                    </button>
                  )}
                  {templates.find((t) => t.id === selectedId)?.slug !== "default" && (
                    <button
                      onClick={remove}
                      disabled={busy}
                      className="btn-danger text-xs"
                      title="Delete this template"
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              </div>

              {/* Preview */}
              <div>
                <div className="flex items-center gap-2 text-xs uppercase text-muted">
                  <Eye size={12} /> Preview (sample product)
                </div>
                <div
                  className="prose prose-invert mt-1 max-h-[440px] overflow-y-auto rounded-lg border border-border bg-panel2 p-3 text-sm"
                  // Render trusted HTML from the editor preview endpoint. The
                  // variables are server-controlled (sample) so XSS surface
                  // here is limited to what the user already typed.
                  dangerouslySetInnerHTML={{ __html: preview }}
                />
              </div>
            </>
          ) : (
            <div className="lg:col-span-2 text-sm text-muted">Select a template to edit.</div>
          )}
        </div>
      )}
    </div>
  );
}

function TrackingSection() {
  const [s, setS] = useState<AppSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [ttl, setTtl] = useState<number>(60);
  const [busy, setBusy] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api<AppSettings>("/api/settings").then((s) => {
      setS(s);
      setTtl(s.easypost_cache_ttl_minutes ?? 60);
    }).catch(() => {});
  }, []);

  async function patch(update: Record<string, unknown>) {
    setBusy(true);
    try {
      const fresh = await api<AppSettings>("/api/settings", {
        method: "PUT",
        body: JSON.stringify(update),
      });
      setS(fresh);
      setTtl(fresh.easypost_cache_ttl_minutes ?? 60);
      if ("easypost_api_key" in update) setApiKey("");
      setSavedAt(Date.now());
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="flex items-center gap-3">
        <Truck size={20} className="text-muted" />
        <h2 className="text-lg font-semibold">Carrier tracking (EasyPost)</h2>
        {busy && <Loader2 size={14} className="animate-spin text-muted" />}
        {!busy && savedAt && Date.now() - savedAt < 3000 && (
          <span className="text-xs text-accent">Saved</span>
        )}
      </div>
      <p className="mt-2 text-sm text-muted">
        Connect an EasyPost API key to fetch live status for USPS, UPS, FedEx,
        DHL and 100+ other carriers. Without a key the dashboard falls back to
        manual <i>mark delivered</i>. Get a key at{" "}
        <a className="text-accent hover:underline" href="https://www.easypost.com/account/api-keys" target="_blank" rel="noreferrer">
          easypost.com/account/api-keys
        </a>.
      </p>

      {!s ? (
        <div className="mt-4 text-sm text-muted">Loading…</div>
      ) : (
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <label className="text-xs uppercase text-muted">
              EasyPost API key {s.easypost_api_key_set && <span className="text-accent">(set)</span>}
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={s.easypost_api_key_set ? "•••••••• (leave blank to keep)" : "EZAK… or EZTK…"}
              className="input mt-1 w-full"
            />
            <div className="mt-1 flex gap-2">
              <button
                className="btn-secondary text-xs"
                onClick={() => apiKey && patch({ easypost_api_key: apiKey })}
                disabled={!apiKey || busy}
              >
                Save key
              </button>
              {s.easypost_api_key_set && (
                <button
                  className="btn-danger text-xs"
                  onClick={() => patch({ easypost_api_key: "__CLEAR__" })}
                >
                  Clear
                </button>
              )}
            </div>
          </div>

          <div>
            <label className="text-xs uppercase text-muted">Re-poll interval (minutes)</label>
            <input
              type="number"
              min={1}
              step={1}
              value={ttl}
              onChange={(e) => setTtl(Number(e.target.value) || 60)}
              onBlur={() => {
                if (ttl !== s.easypost_cache_ttl_minutes) {
                  patch({ easypost_cache_ttl_minutes: ttl });
                }
              }}
              className="input mt-1 w-full"
            />
            <p className="mt-1 text-xs text-muted">
              EasyPost is billed per tracker. We cache results per (carrier,
              number) and re-poll at most this often.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

export default function SettingsPage() {
  const [apiOk, setApiOk] = useState<boolean | null>(null);
  const [stats, setStats] = useState<{ total: number; saved_today: number } | null>(null);

  useEffect(() => {
    api<{ status: string }>("/health")
      .then(() => setApiOk(true))
      .catch(() => setApiOk(false));
    api<{ total: number; saved_today: number }>("/api/stats")
      .then((s) => setStats({ total: s.total, saved_today: s.saved_today }))
      .catch(() => {});
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-sm text-muted">Configure backend, Chrome extension, and eBay connection.</p>
      </div>

      {/* Backend status */}
      <div className="card">
        <div className="flex items-center gap-3">
          <Server size={20} className="text-muted" />
          <h2 className="text-lg font-semibold">Backend API</h2>
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <div>
            <div className="text-xs uppercase text-muted">URL</div>
            <div className="mt-1 font-mono text-sm">{API_URL}</div>
          </div>
          <div>
            <div className="text-xs uppercase text-muted">Status</div>
            <div className="mt-1 flex items-center gap-2">
              {apiOk === null ? (
                <span className="text-muted">Checking…</span>
              ) : apiOk ? (
                <span className="flex items-center gap-1 text-accent"><CheckCircle2 size={16} /> Online</span>
              ) : (
                <span className="flex items-center gap-1 text-red-400"><XCircle size={16} /> Unreachable</span>
              )}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase text-muted">Synced products</div>
            <div className="mt-1 font-medium">
              {stats ? `${stats.total} total · ${stats.saved_today} today` : "—"}
            </div>
          </div>
        </div>
        <p className="mt-4 text-xs text-muted">
          Change the URL by setting <code>NEXT_PUBLIC_API_URL</code> in <code>frontend/.env.local</code> and restarting the dev server.
        </p>
      </div>

      {/* eBay */}
      <Suspense fallback={<div className="card text-muted">Loading eBay status…</div>}>
        <EbaySection />
      </Suspense>

      <FeeStructureSection />

      <AutoRepriceSection />

      <AmazonFulfillmentSection />

      <AliExpressFulfillmentSection />

      <DescriptionTemplatesSection />

      <TrackingSection />

      {/* Chrome extension */}
      <div className="card">
        <div className="flex items-center gap-3">
          <Chrome size={20} className="text-muted" />
          <h2 className="text-lg font-semibold">Chrome extension</h2>
        </div>
        <p className="mt-2 text-sm text-muted">
          Install the Droply extension to add a one-click "Save product" button on every Amazon product page.
          Each save automatically syncs to this dashboard.
        </p>
        <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm text-white/90">
          <li>Download the extension zip below and unzip it.</li>
          <li>Open <code>chrome://extensions</code> and enable <b>Developer mode</b>.</li>
          <li>Click <b>Load unpacked</b> and select the unzipped folder.</li>
          <li>Open the extension popup → expand <b>Backend URL</b> → enter <code>{API_URL}</code> and click <b>Save</b>.</li>
          <li>Visit any Amazon product page and click the green <b>Save product (Droply)</b> button.</li>
        </ol>
        <div className="mt-4">
          <a
            href="https://github.com/MianTaha0/coursera-test/raw/claude/droopify-clone-4wssG/extension/droply-extension.zip"
            className="btn-primary"
          >
            <Download size={16} /> Download extension (.zip)
          </a>
        </div>
      </div>
    </div>
  );
}
