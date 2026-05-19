"use client";

import { useEffect, useState } from "react";
import { Loader2, X, RefreshCw, Tag, CheckCircle2, AlertTriangle } from "lucide-react";
import { api, AspectSchema, CategorySuggestion, Product } from "@/lib/api";

/**
 * Edit a product's eBay category + item-specifics. Driven by
 *   GET  /api/products/{asin}/aspect-schema        (fetches schema + auto-filled values)
 *   POST /api/products/{asin}/suggest-category     (re-runs detection)
 *   PUT  /api/products/{asin}/category             (manual category override)
 *   PUT  /api/products/{asin}/aspects              (saves aspect overrides)
 *
 * Surfaces required vs recommended, pre-fills from auto-detection, and lets
 * the user override SELECTION_ONLY aspects via a <select> or FREE_TEXT via
 * an <input>. Required aspects with no value are highlighted red.
 */
export default function CategoryAspectsModal({
  product,
  marketplaceId = "EBAY_US",
  onClose,
  onSaved,
}: {
  product: Product;
  marketplaceId?: string;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const [schema, setSchema] = useState<AspectSchema | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<CategorySuggestion[] | null>(null);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      const s = await api<AspectSchema>(
        `/api/products/${encodeURIComponent(product.asin)}/aspect-schema?marketplace_id=${marketplaceId}`,
      );
      setSchema(s);
      // Seed inputs: user overrides win > auto-fill > empty
      const seed: Record<string, string> = {};
      for (const a of s.schema || []) {
        const ov = s.user_overrides?.[a.name];
        const auto = s.auto?.[a.name];
        seed[a.name] = (ov?.[0] ?? auto?.[0] ?? "").toString();
      }
      setValues(seed);
    } catch (e: any) {
      setError(e.message || "Failed to load aspect schema");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [product.asin, marketplaceId]);

  async function reDetect() {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{
        ok: boolean;
        suggestions: CategorySuggestion[];
        selected: CategorySuggestion;
      }>(`/api/products/${encodeURIComponent(product.asin)}/suggest-category?marketplace_id=${marketplaceId}`, {
        method: "POST",
      });
      setSuggestions(r.suggestions);
      // Schema will need a refresh because the category changed
      await load();
    } catch (e: any) {
      setError(e.message || "Category detection failed");
    } finally {
      setBusy(false);
    }
  }

  async function pickCategory(s: CategorySuggestion) {
    setBusy(true);
    try {
      await api(`/api/products/${encodeURIComponent(product.asin)}/category`, {
        method: "PUT",
        body: JSON.stringify({
          category_id: s.category_id,
          category_name: s.category_name,
          marketplace_id: marketplaceId,
        }),
      });
      setSuggestions(null);
      await load();
    } catch (e: any) {
      setError(e.message || "Failed to save category");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!schema) return;
    setBusy(true);
    setError(null);
    try {
      const aspects: Record<string, string[]> = {};
      for (const a of schema.schema) {
        const v = (values[a.name] || "").trim();
        if (v) aspects[a.name] = [v];
      }
      await api(`/api/products/${encodeURIComponent(product.asin)}/aspects`, {
        method: "PUT",
        body: JSON.stringify({ aspects }),
      });
      onSaved?.();
      onClose();
    } catch (e: any) {
      setError(e.message || "Failed to save aspects");
    } finally {
      setBusy(false);
    }
  }

  const required = (schema?.schema || []).filter((a) => a.required);
  const recommended = (schema?.schema || []).filter((a) => !a.required);
  const stillMissing = required.filter((a) => !(values[a.name] || "").trim());

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="card max-h-[90vh] w-full max-w-3xl overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-lg font-semibold">
              <Tag size={18} className="text-accent" />
              Category & item specifics
            </div>
            <p className="mt-1 text-sm text-muted truncate" title={product.title}>
              {product.title || product.asin}
            </p>
          </div>
          <button className="text-muted hover:text-white" onClick={onClose} title="Close">
            <X size={18} />
          </button>
        </div>

        {/* Category */}
        <div className="mt-4 rounded-lg border border-border bg-panel2 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs uppercase text-muted">eBay category</span>
            {schema?.category_id ? (
              <span className="font-mono text-sm">{schema.category_id}</span>
            ) : (
              <span className="text-sm text-yellow-300">not set</span>
            )}
            {schema?.category_name && (
              <span className="text-sm text-white/80">— {schema.category_name}</span>
            )}
            <button
              className="btn-secondary ml-auto text-xs"
              onClick={reDetect}
              disabled={busy}
              title="Re-run eBay's category detection on the product title"
            >
              {busy ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              Re-detect
            </button>
          </div>

          {suggestions && suggestions.length > 1 && (
            <div className="mt-3 space-y-1">
              <div className="text-xs text-muted">Other candidates — click to switch:</div>
              {suggestions.slice(0, 5).map((s) => (
                <button
                  key={s.category_id}
                  className="block w-full rounded border border-border bg-panel px-2 py-1 text-left text-xs hover:border-accent"
                  onClick={() => pickCategory(s)}
                  disabled={busy}
                >
                  <span className="font-mono">{s.category_id}</span> — {s.category_path}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Aspects */}
        {busy && !schema && (
          <div className="mt-4 flex items-center gap-2 text-sm text-muted">
            <Loader2 size={14} className="animate-spin" /> Loading aspects…
          </div>
        )}

        {error && (
          <div className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        {schema?.category_id && schema.schema?.length > 0 && (
          <>
            <div className="mt-4">
              <div className="mb-2 flex items-center justify-between">
                <div className="text-xs uppercase text-muted">Required ({required.length})</div>
                {stillMissing.length > 0 ? (
                  <span className="flex items-center gap-1 text-xs text-red-300">
                    <AlertTriangle size={12} /> {stillMissing.length} missing
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-xs text-accent">
                    <CheckCircle2 size={12} /> all filled
                  </span>
                )}
              </div>
              <div className="space-y-2">
                {required.map((a) => (
                  <AspectInput
                    key={a.name}
                    aspect={a}
                    value={values[a.name] || ""}
                    onChange={(v) => setValues((p) => ({ ...p, [a.name]: v }))}
                  />
                ))}
              </div>
            </div>

            {recommended.length > 0 && (
              <details className="mt-4" open={recommended.length <= 6}>
                <summary className="cursor-pointer text-xs uppercase text-muted">
                  Recommended ({recommended.length})
                </summary>
                <div className="mt-2 space-y-2">
                  {recommended.map((a) => (
                    <AspectInput
                      key={a.name}
                      aspect={a}
                      value={values[a.name] || ""}
                      onChange={(v) => setValues((p) => ({ ...p, [a.name]: v }))}
                    />
                  ))}
                </div>
              </details>
            )}
          </>
        )}

        {schema?.category_id && schema.schema?.length === 0 && (
          <div className="mt-4 text-sm text-muted">
            eBay returned no item specifics for this category. Publish should work as-is.
          </div>
        )}

        <div className="mt-6 flex justify-end gap-2">
          <button className="btn-secondary text-sm" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            className="btn-primary text-sm"
            onClick={save}
            disabled={busy || !schema?.category_id}
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

function AspectInput({
  aspect,
  value,
  onChange,
}: {
  aspect: { name: string; required: boolean; mode: string; values: string[] };
  value: string;
  onChange: (v: string) => void;
}) {
  const isMissing = aspect.required && !value.trim();
  return (
    <label className="block">
      <div className="flex items-center gap-2 text-xs text-muted">
        <span className={isMissing ? "text-red-300" : ""}>{aspect.name}</span>
        {aspect.required && <span className="text-red-300">*</span>}
      </div>
      {aspect.mode === "SELECTION_ONLY" && aspect.values?.length ? (
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={`input mt-1 w-full ${isMissing ? "border-red-500/50" : ""}`}
        >
          <option value="">— choose —</option>
          {aspect.values.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={aspect.required ? "Required" : "Optional"}
          className={`input mt-1 w-full ${isMissing ? "border-red-500/50" : ""}`}
          list={aspect.values?.length ? `aspect-${aspect.name}` : undefined}
        />
      )}
      {aspect.mode !== "SELECTION_ONLY" && aspect.values?.length > 0 && (
        <datalist id={`aspect-${aspect.name}`}>
          {aspect.values.map((v) => (
            <option key={v} value={v} />
          ))}
        </datalist>
      )}
    </label>
  );
}
