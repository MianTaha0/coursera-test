"use client";

import { useEffect, useState } from "react";
import { Chrome, Server, CheckCircle2, XCircle, Download } from "lucide-react";
import { api, API_URL } from "@/lib/api";

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
        <p className="text-sm text-muted">Configure how your dashboard talks to the Chrome extension.</p>
      </div>

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
