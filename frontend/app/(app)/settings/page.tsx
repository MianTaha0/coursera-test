"use client";

import { useEffect, useState } from "react";
import { Chrome, Server, CheckCircle2, XCircle, Download, Store, LogOut, Loader2, AlertTriangle, RefreshCw } from "lucide-react";
import { api, API_URL, AppSettings } from "@/lib/api";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

type EbayStatus = {
  connected: boolean;
  token_valid?: boolean;
  token_expires_at?: number;
  connected_at?: string;
  sandbox?: boolean;
};

function EbaySection() {
  const params = useSearchParams();
  const [status, setStatus] = useState<EbayStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [flashMsg, setFlashMsg] = useState<string | null>(null);

  async function load() {
    try {
      const s = await api<EbayStatus>("/auth/ebay/status");
      setStatus(s);
    } catch {
      setStatus({ connected: false });
    }
  }

  useEffect(() => {
    load();
    if (params.get("ebay") === "connected") {
      setFlashMsg("eBay connected successfully!");
      window.history.replaceState({}, "", "/settings");
    }
  }, [params]);

  async function disconnect() {
    if (!confirm("Disconnect your eBay account?")) return;
    setBusy(true);
    try {
      await api("/auth/ebay", { method: "DELETE" });
      await load();
    } finally {
      setBusy(false);
    }
  }

  const connectUrl = `${API_URL}/auth/ebay`;

  return (
    <div className="card">
      <div className="flex items-center gap-3">
        <Store size={20} className="text-muted" />
        <h2 className="text-lg font-semibold">eBay Account</h2>
        {status?.sandbox && (
          <span className="badge bg-yellow-500/15 text-yellow-400">Sandbox</span>
        )}
      </div>

      {flashMsg && (
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-sm text-accent">
          <CheckCircle2 size={16} /> {flashMsg}
        </div>
      )}

      <div className="mt-4">
        {status === null ? (
          <div className="flex items-center gap-2 text-sm text-muted">
            <Loader2 size={16} className="animate-spin" /> Checking connection…
          </div>
        ) : status.connected ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-accent">
              <CheckCircle2 size={18} />
              <span className="font-medium">Connected</span>
              {status.token_valid === false && (
                <span className="flex items-center gap-1 text-yellow-400">
                  <AlertTriangle size={14} /> Token expired — reconnect below
                </span>
              )}
            </div>
            {status.connected_at && (
              <p className="text-xs text-muted">
                Connected {new Date(status.connected_at).toLocaleString()}
              </p>
            )}
            <div className="flex gap-2">
              <a href={connectUrl} className="btn-secondary text-sm">
                Reconnect
              </a>
              <button
                onClick={disconnect}
                disabled={busy}
                className="btn-danger text-sm"
              >
                {busy ? <Loader2 size={14} className="animate-spin" /> : <LogOut size={14} />}
                Disconnect
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-muted">
              <XCircle size={18} className="text-red-400" />
              <span>Not connected</span>
            </div>
            <p className="text-sm text-muted">
              Connect your eBay seller account to publish products directly from the Products page.
            </p>
            <a href={connectUrl} className="btn-primary inline-flex">
              <Store size={16} /> Connect eBay
            </a>
          </div>
        )}
      </div>

      <div className="mt-4 rounded-lg border border-border bg-panel2 p-3 text-xs text-muted space-y-1">
        <p className="font-medium text-white/60">Setup required</p>
        <p>1. In the <a href="https://developer.ebay.com/my/keys" target="_blank" rel="noopener" className="text-accent hover:underline">eBay Developer Portal</a>, copy your <b>App ID</b> and <b>Cert ID</b>.</p>
        <p>2. Set <code>EBAY_CLIENT_ID</code>, <code>EBAY_CLIENT_SECRET</code>, and <code>EBAY_RU_NAME</code> in your backend environment.</p>
        <p>3. Update the <b>Auth accepted URL</b> in your eBay app to <code>{API_URL}/auth/ebay/callback</code>.</p>
        <p>4. Click <b>Connect eBay</b> above.</p>
      </div>
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
              <label className="text-xs uppercase text-muted">Markup %</label>
              <input
                type="number"
                step="0.5"
                value={s.markup_percent}
                onChange={(e) => patch({ markup_percent: Number(e.target.value) })}
                className="input mt-1 w-full"
                disabled={!s.auto_reprice_enabled}
              />
              <p className="mt-1 text-xs text-muted">
                eBay price = Amazon price × (1 + markup/100)
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

      <AutoRepriceSection />

      <AmazonFulfillmentSection />

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
