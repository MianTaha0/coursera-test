"use client";

import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import ProductsTable, { Product } from "@/components/ProductsTable";
import { supabase } from "@/lib/supabase";

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    try {
      setLoading(true);
      const { data, error } = await supabase()
        .from("products")
        .select(
          "id, asin, title, images, amazon_price, ebay_price, profit_margin, stock_status, monitor_status, ebay_listing_url",
        )
        .order("imported_at", { ascending: false });
      if (error) throw error;
      setProducts((data || []) as Product[]);
    } catch (e: any) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const sb = supabase();
    const ch = sb
      .channel("products-page")
      .on("postgres_changes", { event: "*", schema: "public", table: "products" }, () => load())
      .subscribe();
    return () => {
      sb.removeChannel(ch);
    };
  }, []);

  const filtered = useMemo(() => {
    if (!q.trim()) return products;
    const needle = q.toLowerCase();
    return products.filter(
      (p) =>
        (p.title || "").toLowerCase().includes(needle) ||
        (p.asin || "").toLowerCase().includes(needle),
    );
  }, [products, q]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold">Products</h1>
        <div className="relative">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by title or ASIN"
            className="input w-full pl-9 sm:w-72"
          />
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
        <ProductsTable products={filtered} onChange={load} />
      )}
    </div>
  );
}
