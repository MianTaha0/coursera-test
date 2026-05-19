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
  // eBay category + item-specifics (Phase 2.1 / 2.2)
  ebay_category_id?: string | null;
  ebay_category_name?: string | null;
  ebay_aspects?: Record<string, string[]> | null;
  spec_table?: Record<string, string> | null;
  aspects_needs_attention?: number;
  // Manual marketplace override (Phase 2.5). When null, the backend infers
  // from source_marketplace (amazon.de → EBAY_DE, etc.).
  preferred_marketplace_id?: string | null;
};

export type EbayMarketplace = {
  marketplace_id: string;
  language: string;
  country: string | null;
  default_city: string | null;
};

export type EbayAspect = {
  name: string;
  required: boolean;
  mode: "FREE_TEXT" | "SELECTION_ONLY";
  cardinality: "SINGLE" | "MULTI";
  aspect_data_type: string;
  values: string[];
};

export type AspectSchema = {
  category_id: string | null;
  category_name?: string | null;
  schema: EbayAspect[];
  auto: Record<string, string[]>;
  missing: string[];
  user_overrides: Record<string, string[]>;
};

export type CategorySuggestion = {
  category_id: string;
  category_name: string;
  category_path: string;
  score?: number;
  cached?: boolean;
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
  ebay_order_id: string;
  product_asin: string | null;
  sku: string | null;
  line_item_id: string | null;
  ebay_item_id: string | null;
  quantity: number;
  buyer_name: string | null;
  buyer_username: string | null;
  ship_to_name: string | null;
  ship_to_line1: string | null;
  ship_to_line2: string | null;
  ship_to_city: string | null;
  ship_to_state: string | null;
  ship_to_postal: string | null;
  ship_to_country: string | null;
  sale_price: number | null;
  amazon_cost: number | null;
  profit: number | null;
  currency: string;
  status: string;
  tracking_number: string | null;
  tracking_carrier: string | null;
  tracking_submitted_at: string | null;
  tracking_status: string | null;          // unknown | in_transit | out_for_delivery | delivered | exception
  tracking_status_text: string | null;
  tracking_checked_at: string | null;
  created_at: string;
  synced_at: string | null;
};

export const CARRIER_TRACKING_URLS: Record<string, string> = {
  USPS: "https://tools.usps.com/go/TrackConfirmAction?qtc_tLabels1={}",
  UPS: "https://www.ups.com/track?tracknum={}",
  FEDEX: "https://www.fedex.com/fedextrack/?tracknumbers={}",
  DHL: "https://www.dhl.com/global-en/home/tracking/tracking-parcel.html?submit=1&tracking-id={}",
};

export function carrierTrackingUrl(carrier: string | null | undefined, num: string | null | undefined): string | null {
  if (!carrier || !num) return null;
  const tpl = CARRIER_TRACKING_URLS[carrier.toUpperCase()];
  return tpl ? tpl.replace("{}", num) : null;
}

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
  amazon_email: string;
  amazon_password_set: boolean;
  auto_fulfill_enabled: boolean;
  fulfillment_headless: boolean;
  fulfillment_dry_run: boolean;
  ebay_fvf_percent: number;
  ebay_per_order_fee: number;
  ebay_ad_rate_percent: number;
  amazon_shipping_cost: number;
  easypost_api_key_set: boolean;
  easypost_cache_ttl_minutes: number;
  scheduler_enabled?: boolean;
  default_description_template_slug?: string;
  margin_rules?: MarginRule[];
};

export type MarginRule = {
  max_price: number | null;   // null = open-ended (top tier)
  markup_percent: number;
};

export type DescriptionTemplate = {
  id: number;
  slug: string;
  name: string;
  body: string;
  created_at: string;
  updated_at: string;
};

// Partial settings payload accepted by PUT /api/settings. Includes write-only
// fields (e.g. plaintext secrets) that the GET response masks.
export type AppSettingsPatch = Partial<AppSettings> & {
  amazon_password?: string;
  easypost_api_key?: string;
};

/**
 * Compute net profit per unit on an Amazon→eBay flip.
 *
 *   net = sale - (sale × fvf%) - per_order_fee - (sale × ad_rate%)
 *         - amazon_price - amazon_shipping
 *
 * (Buyer-paid eBay shipping is assumed to net out with the seller's actual
 * shipping cost. If you ship for less than you charge, this underestimates
 * net by the difference.)
 */
export function computeNet(
  amazonPrice: number | null | undefined,
  salePrice: number | null | undefined,
  s: AppSettings | null,
): { net: number | null; netMargin: number | null; breakdown: Record<string, number> } {
  if (!s || amazonPrice == null || salePrice == null || isNaN(amazonPrice) || isNaN(salePrice)) {
    return { net: null, netMargin: null, breakdown: {} };
  }
  const fvf = salePrice * (s.ebay_fvf_percent / 100);
  const ad = salePrice * (s.ebay_ad_rate_percent / 100);
  const perOrder = s.ebay_per_order_fee;
  const amazonShip = s.amazon_shipping_cost;
  const cost = amazonPrice + amazonShip;
  const net = +(salePrice - fvf - ad - perOrder - cost).toFixed(2);
  const netMargin = salePrice > 0 ? +((net / salePrice) * 100).toFixed(1) : null;
  return {
    net,
    netMargin,
    breakdown: {
      sale: +salePrice.toFixed(2),
      fvf: +fvf.toFixed(2),
      ad: +ad.toFixed(2),
      per_order_fee: +perOrder.toFixed(2),
      amazon_price: +amazonPrice.toFixed(2),
      amazon_shipping: +amazonShip.toFixed(2),
    },
  };
}

export type VeroMatch = {
  keyword: string;
  reason: string | null;
  level: "block" | "warn";
};

export type VeroBrand = {
  id: number;
  keyword: string;
  reason: string | null;
  level: "block" | "warn";
  created_at: string;
};

export type OutboundMessage = {
  id: number;
  ebay_order_id: string;
  template_slug: string;
  subject: string;
  body: string;
  status: "queued" | "sent";
  trigger_event: string;
  created_at: string;
  sent_at: string | null;
};

export type FulfillmentAttempt = {
  id: number;
  ebay_order_id: string;
  product_asin: string | null;
  status: string;
  amazon_order_id: string | null;
  tracking_number: string | null;
  carrier: string | null;
  error: string | null;
  screenshot_path: string | null;
  started_at: string;
  finished_at: string | null;
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
  paused?: number;                  // 1 when quantity has been set to 0
  paused_at?: string | null;
  paused_reason?: "amazon_oos" | "manual" | null;
  last_quantity?: number;
};

export type EbayStatus = {
  connected: boolean;
  token_valid?: boolean;
  token_expires_at?: number;
  connected_at?: string;
  sandbox?: boolean;
};
