"use client";

const BASE =
  (typeof window !== "undefined" && (window as any).__DROPLY_API__) ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

export const API_URL = BASE;

export async function api<T = any>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
    cache: "no-store",
  });
  const text = await res.text();
  const json = text ? JSON.parse(text) : ({} as any);
  if (!res.ok) throw new Error(json.detail || json.error || `HTTP ${res.status}`);
  return json as T;
}

export type Product = {
  asin: string;
  title: string;
  brand: string;
  price: number | null;
  currency: string;
  images: string[];
  description: string;
  stock_status: string;
  amazon_url: string;
  source_marketplace: string;
  saved_at: string;
};

export type Stats = {
  total: number;
  in_stock: number;
  out_of_stock: number;
  saved_today: number;
  avg_price: number;
  total_value: number;
  min_price: number;
  max_price: number;
  series: { day: string; count: number }[];
  top_brands: { brand: string; count: number }[];
};

export type Order = {
  id: number;
  product_asin: string;
  buyer_name: string | null;
  sale_price: number | null;
  amazon_cost: number | null;
  profit: number | null;
  status: string;
  tracking_number: string | null;
  created_at: string;
};

export type PriceSnapshot = {
  price: number | null;
  currency: string;
  stock_status: string;
  checked_at: string;
};

export type Alert = {
  asin: string;
  title: string;
  brand: string;
  image: string | null;
  amazon_url: string;
  price: number | null;
  currency: string;
  stock_status: string;
  checked_at: string;
  price_delta: number | null;
  stock_delta: string | null;
};

export type MessageTemplate = {
  id: number;
  slug: string;
  name: string;
  kind: string;
  subject: string;
  body: string;
  created_at: string;
  updated_at: string;
};

export type AppSettings = {
  auto_reprice_enabled: boolean;
  markup_percent: number;
  min_reprice_change_percent: number;
};

export type EbayListing = {
  asin: string;
  marketplace_id: string;
  sku: string;
  offer_id: string | null;
  listing_id: string | null;
  listing_url: string | null;
  last_price: number | null;
  currency: string | null;
  markup_percent: number | null;
  listed_at: string | null;
  updated_at: string | null;
};

export type EbayStatus = {
  connected: boolean;
  token_valid?: boolean;
  token_expires_at?: number;
  connected_at?: string;
  sandbox?: boolean;
};
