"use client";

import { useEffect, useState } from "react";
import { Search, RefreshCw, Trash2 } from "lucide-react";
import ProductsTable from "@/components/ProductsTable";
import { api, Product } from "@/lib/api";

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    try {
      setErr(null);
      const data = await api<Product[]>(`/api/products${q ? `?q=${encodeURIComponent(q)}` : ""}`);
      setProducts(data);
    } catch (e: any) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  async function clearAll() {
    if (!confirm("Remove ALL products from the dashboard? (Local extension storage is kept.)")) return;
    await api("/api/products", { method: "DELETE" });
    load();
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold">Products</h1>
          <p className="text-sm text-muted">{products.length} synced from extension</p>
        </div>
        <div className="flex gap-2">
          <div className="relative">
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search title, brand, ASIN"
              className="input w-full pl-9 sm:w-72"
            />
          </div>
          <button onClick={load} className="btn-secondary" title="Refresh">
            <RefreshCw size={16} />
          </button>
          <button onClick={clearAll} className="btn-danger" title="Clear all">
            <Trash2 size={16} />
          </button>
        </div>
      </div>
      {err && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {err}
        </div>
      )}
      {loading ? (
        <div className="card text-muted">Loading products…</div>
      ) : (
        <ProductsTable products={products} onChange={load} />
      )}
    </div>
  );
}
