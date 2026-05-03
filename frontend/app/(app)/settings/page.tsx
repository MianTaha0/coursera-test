"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Check, Chrome, Link as LinkIcon, Unplug } from "lucide-react";
import { api } from "@/lib/api";
import { date } from "@/lib/format";

type Me = {
  id: string;
  email: string;
  ebay_username: string | null;
  ebay_connected: boolean;
  profile: { plan: string; trial_ends_at: string | null } | null;
};

export default function SettingsPage() {
  const params = useSearchParams();
  const [me, setMe] = useState<Me | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  async function load() {
    try {
      const m = await api<Me>("/api/me");
      setMe(m);
    } catch (e: any) {
      setErr(e.message || String(e));
    }
  }

  useEffect(() => {
    load();
    if (params.get("ebay") === "connected") {
      setInfo("eBay account connected successfully.");
    }
  }, [params]);

  async function connectEbay() {
    try {
      setBusy("ebay");
      setErr(null);
      const { url } = await api<{ url: string }>("/api/ebay/oauth/url");
      window.location.href = url;
    } catch (e: any) {
      setErr(e.message || String(e));
      setBusy(null);
    }
  }

  async function disconnectEbay() {
    if (!confirm("Disconnect your eBay store?")) return;
    try {
      setBusy("ebay");
      await api("/api/ebay/disconnect", { method: "POST" });
      await load();
    } catch (e: any) {
      setErr(e.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  function downloadExtension() {
    // The /extension folder is shipped as a zip alongside this app.
    window.location.href = "/extension/droply-extension.zip";
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      {info && (
        <div className="rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-sm text-accent">{info}</div>
      )}
      {err && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{err}</div>
      )}

      <div className="card">
        <h2 className="text-lg font-semibold">Account</h2>
        <div className="mt-3 grid gap-4 sm:grid-cols-3">
          <div>
            <div className="text-xs uppercase text-muted">Email</div>
            <div className="mt-1 font-medium">{me?.email || "—"}</div>
          </div>
          <div>
            <div className="text-xs uppercase text-muted">Plan</div>
            <div className="mt-1 font-medium capitalize">{me?.profile?.plan || "trial"}</div>
          </div>
          <div>
            <div className="text-xs uppercase text-muted">Trial ends</div>
            <div className="mt-1 font-medium">{date(me?.profile?.trial_ends_at)}</div>
          </div>
        </div>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold">eBay store</h2>
        <p className="mt-1 text-sm text-muted">
          Connect your eBay account so Droply can list, monitor, and message buyers on your behalf.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          {me?.ebay_connected ? (
            <>
              <span className="badge bg-accent/15 text-accent">
                <Check size={14} className="mr-1" /> Connected
              </span>
              <span className="text-sm">
                Store: <span className="font-medium">{me.ebay_username || "(unknown)"}</span>
              </span>
              <button onClick={disconnectEbay} disabled={busy === "ebay"} className="btn-secondary">
                <Unplug size={16} /> Disconnect
              </button>
            </>
          ) : (
            <button onClick={connectEbay} disabled={busy === "ebay"} className="btn-primary">
              <LinkIcon size={16} /> Connect eBay store
            </button>
          )}
        </div>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold">Chrome extension</h2>
        <p className="mt-1 text-sm text-muted">
          Install the Droply extension to add an "Import to eBay" button on every Amazon product page.
        </p>
        <div className="mt-4">
          <button onClick={downloadExtension} className="btn-primary">
            <Chrome size={16} /> Download extension (.zip)
          </button>
        </div>
      </div>
    </div>
  );
}
