"""Droply backend — SQLite-backed, eBay OAuth + Inventory API.

Product endpoints (used by Chrome extension and Next.js dashboard):
  POST   /api/products              save / upsert one product
  GET    /api/products              list all
  GET    /api/products/{asin}       fetch one
  DELETE /api/products/{asin}       remove one
  POST   /api/products/bulk         upsert many
  DELETE /api/products              clear all
  POST   /api/products/{asin}/list-ebay  publish to eBay via Inventory API
  GET    /api/stats                 aggregate stats for dashboard
  GET    /api/orders                list orders

eBay OAuth endpoints:
  GET    /auth/ebay                 redirect to eBay consent screen
  GET    /auth/ebay/callback        exchange code for tokens (eBay redirects here)
  GET    /auth/ebay/status          check connection status
  DELETE /auth/ebay                 disconnect (clear stored tokens)

Misc:
  GET    /privacy                   privacy policy (required by eBay app config)
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, date, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_PATH = os.getenv("DROPLY_DB", os.path.join(os.path.dirname(__file__), "droply.db"))

EBAY_CLIENT_ID     = os.getenv("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET", "")
EBAY_RU_NAME       = os.getenv("EBAY_RU_NAME", "")       # e.g. Mian_Taha-MianTaha-MTS-SB-vbcinsx
EBAY_SANDBOX       = os.getenv("EBAY_SANDBOX", "true").lower() != "false"
FRONTEND_URL       = os.getenv("FRONTEND_URL", "http://localhost:3000")

EBAY_AUTH_BASE  = "https://auth.sandbox.ebay.com"  if EBAY_SANDBOX else "https://auth.ebay.com"
EBAY_API_BASE   = "https://api.sandbox.ebay.com"   if EBAY_SANDBOX else "https://api.ebay.com"
EBAY_TOKEN_URL  = f"{EBAY_API_BASE}/identity/v1/oauth2/token"

EBAY_SCOPES = " ".join([
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
])

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Droply API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Default message templates (seeded on first launch into message_templates)
#   Variables supported: {buyer_name} {item_title} {order_id}
#                        {tracking_number} {carrier} {seller_name}
#                        {est_delivery_date}
# ---------------------------------------------------------------------------
DEFAULT_MESSAGE_TEMPLATES: list[tuple[str, str, str, str, str]] = [
    (
        "order_confirmed",
        "Order confirmed",
        "order_confirmed",
        "Thanks for your order — {item_title}",
        "Hi {buyer_name},\n\n"
        "Thanks so much for your order! I've received your purchase of "
        "\"{item_title}\" (order #{order_id}) and will get it shipped out shortly.\n\n"
        "I'll send tracking information as soon as the package is on its way.\n\n"
        "Thanks again,\n{seller_name}",
    ),
    (
        "shipped",
        "Shipped + tracking",
        "shipped",
        "Your order has shipped — {item_title}",
        "Hi {buyer_name},\n\n"
        "Good news — your order has shipped!\n\n"
        "  Item: {item_title}\n"
        "  Order: #{order_id}\n"
        "  Carrier: {carrier}\n"
        "  Tracking: {tracking_number}\n"
        "  Estimated delivery: {est_delivery_date}\n\n"
        "Thanks again for your order,\n{seller_name}",
    ),
    (
        "delivered",
        "Delivered check-in",
        "delivered",
        "Hope you're enjoying your purchase",
        "Hi {buyer_name},\n\n"
        "Tracking shows your order #{order_id} (\"{item_title}\") was delivered. "
        "I hope it arrived in great shape and meets your expectations!\n\n"
        "If anything's off, please reply to this message before leaving feedback "
        "and I'll make it right.\n\n"
        "Thanks,\n{seller_name}",
    ),
    (
        "feedback_request",
        "Feedback request",
        "feedback_request",
        "Quick favor? — {item_title}",
        "Hi {buyer_name},\n\n"
        "Thanks again for your purchase of \"{item_title}\"! If you've got a moment, "
        "I'd really appreciate a positive feedback rating — it makes a huge "
        "difference for a small seller.\n\n"
        "If anything wasn't perfect, please reply first so I can fix it.\n\n"
        "Thanks,\n{seller_name}",
    ),
]


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        # Migrate the old orders schema (auto-incrementing id) → new ebay_order_id PK
        cur = conn.execute("PRAGMA table_info(orders)").fetchall()
        if cur and not any(c["name"] == "ebay_order_id" for c in cur):
            existing = conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"]
            if existing == 0:
                conn.execute("DROP TABLE orders")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                asin TEXT PRIMARY KEY,
                title TEXT,
                brand TEXT,
                price REAL,
                currency TEXT,
                images TEXT,
                description TEXT,
                stock_status TEXT,
                amazon_url TEXT,
                source_marketplace TEXT,
                saved_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                ebay_order_id TEXT PRIMARY KEY,
                product_asin TEXT,
                sku TEXT,
                line_item_id TEXT,
                ebay_item_id TEXT,
                quantity INTEGER DEFAULT 1,
                buyer_name TEXT,
                buyer_username TEXT,
                ship_to_name TEXT,
                ship_to_line1 TEXT,
                ship_to_line2 TEXT,
                ship_to_city TEXT,
                ship_to_state TEXT,
                ship_to_postal TEXT,
                ship_to_country TEXT,
                sale_price REAL,
                amazon_cost REAL,
                profit REAL,
                currency TEXT,
                status TEXT DEFAULT 'pending',
                tracking_number TEXT,
                tracking_carrier TEXT,
                tracking_submitted_at TEXT,
                created_at TEXT,
                synced_at TEXT
            )
        """)
        # Active eBay listings (one row per ASIN/marketplace pair)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ebay_listings (
                asin TEXT NOT NULL,
                marketplace_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                offer_id TEXT,
                listing_id TEXT,
                listing_url TEXT,
                last_price REAL,
                currency TEXT,
                markup_percent REAL,
                listed_at TEXT,
                updated_at TEXT,
                PRIMARY KEY (asin, marketplace_id)
            )
        """)

        # Simple key/value config store
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Fulfillment attempts (one row per Amazon checkout run for an eBay order)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fulfillment_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ebay_order_id TEXT NOT NULL,
                product_asin TEXT,
                status TEXT NOT NULL,
                amazon_order_id TEXT,
                tracking_number TEXT,
                carrier TEXT,
                error TEXT,
                screenshot_path TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                tracking_pushed_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attempts_order ON fulfillment_attempts(ebay_order_id, started_at DESC)")

        # Buyer-message templates
        conn.execute("""
            CREATE TABLE IF NOT EXISTS message_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # Seed defaults if the table is empty
        existing = conn.execute("SELECT COUNT(*) AS c FROM message_templates").fetchone()["c"]
        if existing == 0:
            now = datetime.now(timezone.utc).isoformat()
            for slug, name, kind, subject, body in DEFAULT_MESSAGE_TEMPLATES:
                conn.execute(
                    """INSERT INTO message_templates
                       (slug, name, kind, subject, body, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (slug, name, kind, subject, body, now, now),
                )

        # Price/stock snapshots — one row per change, never updated
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asin TEXT NOT NULL,
                price REAL,
                currency TEXT,
                stock_status TEXT,
                checked_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_asin ON price_history(asin, checked_at DESC)")

        # Single-row table: stores the active eBay OAuth tokens
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ebay_tokens (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                access_token TEXT,
                refresh_token TEXT,
                expires_at INTEGER,
                refresh_expires_at INTEGER,
                scope TEXT,
                connected_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_saved_at ON products(saved_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")


init_db()


# ---------------------------------------------------------------------------
# Helpers — products
# ---------------------------------------------------------------------------
def row_to_product(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    try:
        d["images"] = json.loads(d.get("images") or "[]")
    except Exception:
        d["images"] = []
    return d


# ---------------------------------------------------------------------------
# Helpers — eBay tokens
# ---------------------------------------------------------------------------
def _token_row(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM ebay_tokens WHERE id = 1").fetchone()


def _save_tokens(conn: sqlite3.Connection, data: dict) -> None:
    expires_at = int(time.time()) + int(data.get("expires_in", 7200))
    refresh_expires_at = int(time.time()) + int(data.get("refresh_token_expires_in", 47304000))
    conn.execute(
        """
        INSERT INTO ebay_tokens (id, access_token, refresh_token, expires_at, refresh_expires_at, scope, connected_at)
        VALUES (1, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            access_token=excluded.access_token,
            refresh_token=excluded.refresh_token,
            expires_at=excluded.expires_at,
            refresh_expires_at=excluded.refresh_expires_at,
            scope=excluded.scope,
            connected_at=excluded.connected_at
        """,
        (
            data["access_token"],
            data.get("refresh_token", ""),
            expires_at,
            refresh_expires_at,
            data.get("scope", ""),
            datetime.now(timezone.utc).isoformat(),
        ),
    )


async def _refresh_access_token(refresh_token: str) -> dict:
    creds = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            EBAY_TOKEN_URL,
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": EBAY_SCOPES,
            },
        )
    if r.status_code != 200:
        raise HTTPException(502, f"eBay token refresh failed: {r.text}")
    return r.json()


# ---------------------------------------------------------------------------
# Helpers — settings (key/value)
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "auto_reprice_enabled": "false",
    "markup_percent": "30",
    "min_reprice_change_percent": "1.0",
    "amazon_email": "",
    "amazon_password": "",
    "auto_fulfill_enabled": "false",
    "fulfillment_headless": "false",
    "fulfillment_dry_run": "true",
    # eBay fee schedule (US managed-payments defaults — buyer can override)
    "ebay_fvf_percent": "13.25",       # Final Value Fee % on (item + shipping)
    "ebay_per_order_fee": "0.30",      # Fixed per-order fee
    "ebay_ad_rate_percent": "0",       # Promoted Listings ad rate %
    "amazon_shipping_cost": "0",       # Default extra cost added to Amazon price
}


def get_settings_dict() -> dict[str, str]:
    with db() as conn:
        rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    out = dict(DEFAULT_SETTINGS)
    out.update({r["key"]: r["value"] for r in rows})
    return out


def set_setting(key: str, value: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# ---------------------------------------------------------------------------
# Helpers — eBay listings persistence + auto-reprice
# ---------------------------------------------------------------------------
def save_listing(
    *, asin: str, marketplace_id: str, sku: str, offer_id: str,
    listing_id: str, listing_url: str, price: float, currency: str,
    markup_percent: float,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO ebay_listings (asin, marketplace_id, sku, offer_id, listing_id,
                                       listing_url, last_price, currency, markup_percent,
                                       listed_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(asin, marketplace_id) DO UPDATE SET
                sku=excluded.sku,
                offer_id=excluded.offer_id,
                listing_id=excluded.listing_id,
                listing_url=excluded.listing_url,
                last_price=excluded.last_price,
                currency=excluded.currency,
                markup_percent=excluded.markup_percent,
                updated_at=excluded.updated_at
            """,
            (asin, marketplace_id, sku, offer_id, listing_id, listing_url,
             price, currency, markup_percent, now, now),
        )


async def update_offer_price(offer_id: str, price: float, currency: str, marketplace_id: str) -> bool:
    """Push a new price to an existing eBay offer. Republishes so it goes live."""
    token = await get_valid_token()
    content_language = "en-US" if marketplace_id == "EBAY_US" else "en-GB"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept-Language": content_language,
        "Content-Language": content_language,
        "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
    }
    async with httpx.AsyncClient() as client:
        # Fetch the current offer, patch the price, PUT it back
        rg = await client.get(f"{EBAY_API_BASE}/sell/inventory/v1/offer/{offer_id}", headers=headers)
        if rg.status_code != 200:
            return False
        offer = rg.json()
        offer["pricingSummary"] = {"price": {"currency": currency, "value": str(price)}}
        # PUT requires a complete payload; strip read-only / status fields
        for k in ("listing", "status", "offerId", "listingDuration"):
            offer.pop(k, None)
        rp = await client.put(
            f"{EBAY_API_BASE}/sell/inventory/v1/offer/{offer_id}",
            headers=headers, json=offer,
        )
        if rp.status_code not in (200, 204):
            return False
        # Re-publish (needed for the price change to go live on a published offer)
        rpub = await client.post(
            f"{EBAY_API_BASE}/sell/inventory/v1/offer/{offer_id}/publish",
            headers=headers,
        )
        return rpub.status_code in (200, 201)


async def maybe_auto_reprice(asin: str, new_amazon_price: Optional[float]) -> None:
    """Called after a product upsert. Re-prices the eBay listing if enabled."""
    if new_amazon_price is None or new_amazon_price <= 0:
        return
    cfg = get_settings_dict()
    if cfg.get("auto_reprice_enabled", "false").lower() != "true":
        return
    with db() as conn:
        listing = conn.execute(
            "SELECT * FROM ebay_listings WHERE asin = ?", (asin,)
        ).fetchone()
    if not listing or not listing["offer_id"]:
        return

    markup = float(listing["markup_percent"] or cfg.get("markup_percent") or 30)
    min_change_pct = float(cfg.get("min_reprice_change_percent") or 1.0)
    new_listing_price = round(new_amazon_price * (1 + markup / 100), 2)
    old_listing_price = float(listing["last_price"] or 0)

    if old_listing_price > 0:
        change_pct = abs(new_listing_price - old_listing_price) / old_listing_price * 100
        if change_pct < min_change_pct:
            return
    if new_listing_price == old_listing_price:
        return

    ok = await update_offer_price(
        offer_id=listing["offer_id"],
        price=new_listing_price,
        currency=listing["currency"] or "USD",
        marketplace_id=listing["marketplace_id"],
    )
    if ok:
        with db() as conn:
            conn.execute(
                "UPDATE ebay_listings SET last_price = ?, updated_at = ? "
                "WHERE asin = ? AND marketplace_id = ?",
                (new_listing_price, datetime.now(timezone.utc).isoformat(),
                 asin, listing["marketplace_id"]),
            )


async def ensure_business_policies(headers: dict, marketplace_id: str) -> dict:
    """Ensure default fulfillment/payment/return policies exist; return their IDs."""
    policy_headers = {**headers}
    base = f"{EBAY_API_BASE}/sell/account/v1"
    out = {}

    async with httpx.AsyncClient() as client:
        # Ensure seller is opted into Business Policies
        try:
            await client.post(
                f"{base}/program/opt_in",
                headers=policy_headers,
                json={"programType": "SELLING_POLICY_MANAGEMENT"},
            )
        except Exception:
            pass  # already opted in or transient — policy create will surface real errors

    async with httpx.AsyncClient() as client:
        # Fulfillment policy
        r = await client.get(f"{base}/fulfillment_policy", headers=policy_headers,
                             params={"marketplace_id": marketplace_id})
        existing = (r.json().get("fulfillmentPolicies") or []) if r.status_code == 200 else []
        match = next((p for p in existing if p.get("name") == "Droply Default Fulfillment"), None)
        if match:
            out["fulfillmentPolicyId"] = match["fulfillmentPolicyId"]
        else:
            payload = {
                "name": "Droply Default Fulfillment",
                "marketplaceId": marketplace_id,
                "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
                "handlingTime": {"value": 1, "unit": "DAY"},
                "shippingOptions": [{
                    "optionType": "DOMESTIC",
                    "costType": "FLAT_RATE",
                    "shippingServices": [{
                        "sortOrder": 1,
                        "shippingCarrierCode": "USPS",
                        "shippingServiceCode": "USPSPriority",
                        "shippingCost": {"value": "5.00", "currency": "USD"},
                        "freeShipping": False,
                        "buyerResponsibleForShipping": False,
                        "buyerResponsibleForPickup": False,
                    }],
                }],
            }
            rc = await client.post(f"{base}/fulfillment_policy", headers=policy_headers, json=payload)
            if rc.status_code not in (200, 201):
                raise HTTPException(502, f"create fulfillment policy failed: {rc.text}")
            out["fulfillmentPolicyId"] = rc.json()["fulfillmentPolicyId"]

        # Payment policy
        r = await client.get(f"{base}/payment_policy", headers=policy_headers,
                             params={"marketplace_id": marketplace_id})
        existing = (r.json().get("paymentPolicies") or []) if r.status_code == 200 else []
        match = next((p for p in existing if p.get("name") == "Droply Default Payment"), None)
        if match:
            out["paymentPolicyId"] = match["paymentPolicyId"]
        else:
            payload = {
                "name": "Droply Default Payment",
                "marketplaceId": marketplace_id,
                "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
                "immediatePay": True,
            }
            rc = await client.post(f"{base}/payment_policy", headers=policy_headers, json=payload)
            if rc.status_code not in (200, 201):
                raise HTTPException(502, f"create payment policy failed: {rc.text}")
            out["paymentPolicyId"] = rc.json()["paymentPolicyId"]

        # Return policy
        r = await client.get(f"{base}/return_policy", headers=policy_headers,
                             params={"marketplace_id": marketplace_id})
        existing = (r.json().get("returnPolicies") or []) if r.status_code == 200 else []
        match = next((p for p in existing if p.get("name") == "Droply Default Return"), None)
        if match:
            out["returnPolicyId"] = match["returnPolicyId"]
        else:
            payload = {
                "name": "Droply Default Return",
                "marketplaceId": marketplace_id,
                "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
                "returnsAccepted": True,
                "returnPeriod": {"value": 30, "unit": "DAY"},
                "refundMethod": "MONEY_BACK",
                "returnShippingCostPayer": "BUYER",
            }
            rc = await client.post(f"{base}/return_policy", headers=policy_headers, json=payload)
            if rc.status_code not in (200, 201):
                raise HTTPException(502, f"create return policy failed: {rc.text}")
            out["returnPolicyId"] = rc.json()["returnPolicyId"]

    return out


async def get_valid_token() -> str:
    """Return a valid access token, refreshing if needed."""
    with db() as conn:
        row = _token_row(conn)
        if not row:
            raise HTTPException(401, "eBay not connected. Go to Settings → Connect eBay.")
        now = int(time.time())
        if now < row["expires_at"] - 60:
            return row["access_token"]
        # Refresh
        if not row["refresh_token"]:
            raise HTTPException(401, "eBay token expired and no refresh token. Please reconnect.")
        data = await _refresh_access_token(row["refresh_token"])
        with db() as conn2:
            _save_tokens(conn2, data)
        return data["access_token"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ProductIn(BaseModel):
    asin: str
    title: str = ""
    brand: str = ""
    price: Optional[float] = None
    currency: str = "USD"
    images: list[str] = Field(default_factory=list)
    description: str = ""
    stock_status: str = "in_stock"
    amazon_url: str = ""
    source_marketplace: str = ""
    saved_at: Optional[str] = None


class ListEbayIn(BaseModel):
    price: Optional[float] = None          # override listing price (defaults to Amazon price + 30%)
    quantity: int = 1
    category_id: str = "139971"            # default: "Everything Else" (works in sandbox)
    marketplace_id: str = "EBAY_US"
    fulfillment_policy_id: Optional[str] = None
    payment_policy_id: Optional[str] = None
    return_policy_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes — misc
# ---------------------------------------------------------------------------
@app.get("/")
async def root(code: Optional[str] = None, state: Optional[str] = None):
    # If eBay redirected here with an OAuth code, handle it as the callback
    # (so the auth-accepted-URL in the eBay portal can be set to the bare host).
    if code and state:
        return await ebay_auth_callback(code=code, state=state)
    return {"service": "Droply API", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Privacy Policy — Droply</title>
<style>body{font-family:system-ui,sans-serif;max-width:680px;margin:60px auto;padding:0 24px;line-height:1.7}
h1{font-size:1.6rem}h2{font-size:1.1rem;margin-top:2rem}</style></head>
<body>
<h1>Privacy Policy</h1>
<p>Last updated: May 2025</p>
<h2>What we collect</h2>
<p>Droply stores Amazon product data you choose to save (titles, prices, images, ASINs) and eBay OAuth tokens
needed to list products on your behalf. All data is stored locally on your machine in a SQLite database.</p>
<h2>eBay data</h2>
<p>When you connect your eBay account, Droply receives OAuth access tokens. These tokens are used solely
to create and publish listings on eBay through the eBay Inventory API. We do not share your tokens or
eBay account data with any third party.</p>
<h2>No external servers</h2>
<p>Droply is fully self-hosted. No data leaves your machine except when communicating directly with eBay's API.</p>
<h2>Contact</h2>
<p>Questions? Open an issue on the project repository.</p>
</body></html>
""")


# ---------------------------------------------------------------------------
# Routes — eBay OAuth
# ---------------------------------------------------------------------------
# Simple in-memory state store (survives for the duration of the OAuth redirect)
_oauth_states: dict[str, float] = {}


@app.get("/auth/ebay")
def ebay_auth_start():
    """Redirect the browser to eBay's OAuth consent screen."""
    if not EBAY_CLIENT_ID or not EBAY_RU_NAME:
        raise HTTPException(500, "EBAY_CLIENT_ID and EBAY_RU_NAME env vars must be set.")
    state = secrets.token_urlsafe(16)
    _oauth_states[state] = time.time()
    params = urlencode({
        "client_id": EBAY_CLIENT_ID,
        "redirect_uri": EBAY_RU_NAME,
        "response_type": "code",
        "scope": EBAY_SCOPES,
        "state": state,
    })
    return RedirectResponse(f"{EBAY_AUTH_BASE}/oauth2/authorize?{params}")


@app.get("/auth/ebay/callback")
async def ebay_auth_callback(code: str = Query(...), state: str = Query(...)):
    """eBay redirects here after the user approves. Exchange code for tokens."""
    # Validate state
    if state not in _oauth_states:
        raise HTTPException(400, "Invalid OAuth state. Try connecting again.")
    age = time.time() - _oauth_states.pop(state)
    if age > 300:
        raise HTTPException(400, "OAuth state expired. Try connecting again.")

    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET or not EBAY_RU_NAME:
        raise HTTPException(500, "EBAY_CLIENT_ID / EBAY_CLIENT_SECRET / EBAY_RU_NAME not configured.")

    creds = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            EBAY_TOKEN_URL,
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": EBAY_RU_NAME,
            },
        )
    if r.status_code != 200:
        raise HTTPException(502, f"eBay token exchange failed: {r.text}")

    with db() as conn:
        _save_tokens(conn, r.json())

    return RedirectResponse(f"{FRONTEND_URL}/settings?ebay=connected")


@app.get("/auth/ebay/status")
def ebay_status():
    """Return current eBay connection status."""
    with db() as conn:
        row = _token_row(conn)
    if not row:
        return {"connected": False}
    now = int(time.time())
    return {
        "connected": True,
        "token_valid": now < row["expires_at"],
        "token_expires_at": row["expires_at"],
        "refresh_valid": now < row["refresh_expires_at"],
        "connected_at": row["connected_at"],
        "scope": row["scope"],
        "sandbox": EBAY_SANDBOX,
    }


@app.delete("/auth/ebay")
def ebay_disconnect():
    """Remove stored eBay tokens."""
    with db() as conn:
        conn.execute("DELETE FROM ebay_tokens WHERE id = 1")
    return {"ok": True, "message": "eBay disconnected."}


# ---------------------------------------------------------------------------
# Routes — eBay listing
# ---------------------------------------------------------------------------
@app.post("/api/products/{asin}/list-ebay")
async def list_on_ebay(asin: str, body: ListEbayIn = ListEbayIn()):
    """Publish a saved product to eBay via the Inventory API (3-step flow)."""
    with db() as conn:
        row = conn.execute("SELECT * FROM products WHERE asin = ?", (asin,)).fetchone()
    if not row:
        raise HTTPException(404, "Product not found.")

    product = row_to_product(row)
    token = await get_valid_token()
    content_language = "en-US" if body.marketplace_id == "EBAY_US" else "en-GB"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept-Language": content_language,
        "Content-Language": content_language,
        "X-EBAY-C-MARKETPLACE-ID": body.marketplace_id,
    }

    listing_price = body.price
    if listing_price is None and product.get("price"):
        listing_price = round(float(product["price"]) * 1.30, 2)
    if not listing_price:
        raise HTTPException(400, "No price available. Pass 'price' in the request body.")

    sku = f"DROPLY-{asin}"
    merchant_location_key = "DROPLY_DEFAULT"
    title = (product.get("title") or asin)[:80]
    description = product.get("description") or title
    images = product.get("images") or []

    # Step 0 — ensure a merchant location exists (eBay needs Item.Country)
    async with httpx.AsyncClient() as client:
        r_loc_check = await client.get(
            f"{EBAY_API_BASE}/sell/inventory/v1/location/{merchant_location_key}",
            headers=headers,
        )
        if r_loc_check.status_code == 404:
            location_payload = {
                "location": {
                    "address": {
                        "country": "US",
                        "postalCode": "94103",
                        "stateOrProvince": "CA",
                        "city": "San Francisco",
                        "addressLine1": "1 Market St",
                    }
                },
                "name": "Droply Default Location",
                "merchantLocationStatus": "ENABLED",
                "locationTypes": ["WAREHOUSE"],
            }
            r_loc = await client.post(
                f"{EBAY_API_BASE}/sell/inventory/v1/location/{merchant_location_key}",
                headers=headers,
                json=location_payload,
            )
            if r_loc.status_code not in (200, 201, 204):
                raise HTTPException(502, f"eBay create location failed: {r_loc.text}")

    # Step 1 — create/update inventory item
    brand = product.get("brand") or "Unbranded"
    mpn = (product.get("asin") or "N/A")
    item_payload: dict[str, Any] = {
        "product": {
            "title": title,
            "description": description,
            "imageUrls": images[:12],
            "brand": brand,
            "mpn": mpn,
            "aspects": {
                "Brand": [brand],
                "MPN": [mpn],
                "Model": [mpn],
                "Type": ["Generic"],
            },
        },
        "condition": "NEW",
        "availability": {
            "shipToLocationAvailability": {
                "quantity": body.quantity,
            }
        },
    }

    async with httpx.AsyncClient() as client:
        r1 = await client.put(
            f"{EBAY_API_BASE}/sell/inventory/v1/inventory_item/{sku}",
            headers=headers,
            json=item_payload,
        )
    if r1.status_code not in (200, 204):
        raise HTTPException(502, f"eBay create inventory item failed: {r1.text}")

    # Step 2 — create offer
    offer_payload: dict[str, Any] = {
        "sku": sku,
        "marketplaceId": body.marketplace_id,
        "format": "FIXED_PRICE",
        "listingDescription": description[:500],
        "categoryId": body.category_id,
        "merchantLocationKey": merchant_location_key,
        "pricingSummary": {
            "price": {
                "currency": (product.get("currency") or "USD"),
                "value": str(listing_price),
            }
        },
        "quantityLimitPerBuyer": 1,
        "includeCatalogProductDetails": False,
    }
    # Use provided policy IDs, or auto-create defaults
    if body.fulfillment_policy_id and body.payment_policy_id and body.return_policy_id:
        policies = {
            "fulfillmentPolicyId": body.fulfillment_policy_id,
            "paymentPolicyId": body.payment_policy_id,
            "returnPolicyId": body.return_policy_id,
        }
    else:
        policies = await ensure_business_policies(headers, body.marketplace_id)
    offer_payload["listingPolicies"] = policies

    async with httpx.AsyncClient() as client:
        # Check if an offer already exists for this SKU
        r_check = await client.get(
            f"{EBAY_API_BASE}/sell/inventory/v1/offer",
            headers=headers,
            params={"sku": sku, "marketplace_id": body.marketplace_id},
        )
        existing_offer_id = None
        if r_check.status_code == 200:
            offers = r_check.json().get("offers", []) or []
            if offers:
                existing_offer_id = offers[0].get("offerId")

        if existing_offer_id:
            r2 = await client.put(
                f"{EBAY_API_BASE}/sell/inventory/v1/offer/{existing_offer_id}",
                headers=headers,
                json=offer_payload,
            )
            if r2.status_code not in (200, 204):
                raise HTTPException(502, f"eBay update offer failed: {r2.text}")
            offer_id = existing_offer_id
        else:
            r2 = await client.post(
                f"{EBAY_API_BASE}/sell/inventory/v1/offer",
                headers=headers,
                json=offer_payload,
            )
            if r2.status_code not in (200, 201):
                raise HTTPException(502, f"eBay create offer failed: {r2.text}")
            offer_id = r2.json().get("offerId")

    if not offer_id:
        raise HTTPException(502, "eBay did not return an offerId.")

    # Step 3 — publish offer
    async with httpx.AsyncClient() as client:
        r3 = await client.post(
            f"{EBAY_API_BASE}/sell/inventory/v1/offer/{offer_id}/publish",
            headers=headers,
        )
    if r3.status_code not in (200, 201):
        raise HTTPException(502, f"eBay publish offer failed: {r3.text}")

    listing_id = r3.json().get("listingId", "")
    ebay_url = (
        f"https://www.sandbox.ebay.com/itm/{listing_id}"
        if EBAY_SANDBOX
        else f"https://www.ebay.com/itm/{listing_id}"
    )

    # Persist the listing so auto-reprice + UI badges can find it
    markup_pct = 0.0
    if product.get("price"):
        try:
            markup_pct = round((listing_price / float(product["price"]) - 1) * 100, 2)
        except Exception:
            markup_pct = 0.0
    save_listing(
        asin=asin,
        marketplace_id=body.marketplace_id,
        sku=sku,
        offer_id=offer_id,
        listing_id=listing_id,
        listing_url=ebay_url,
        price=listing_price,
        currency=(product.get("currency") or "USD"),
        markup_percent=markup_pct,
    )

    return {
        "ok": True,
        "sku": sku,
        "offer_id": offer_id,
        "listing_id": listing_id,
        "listing_url": ebay_url,
        "listing_price": listing_price,
    }


# ---------------------------------------------------------------------------
# Routes — products (unchanged)
# ---------------------------------------------------------------------------
def _upsert(conn: sqlite3.Connection, p: ProductIn) -> dict[str, Any]:
    if not p.asin:
        raise HTTPException(status_code=400, detail="asin required")
    saved_at = p.saved_at or datetime.now(timezone.utc).isoformat()

    # Snapshot price/stock if changed (or first time saving this ASIN)
    prev = conn.execute(
        "SELECT price, stock_status FROM products WHERE asin = ?", (p.asin,)
    ).fetchone()
    price_changed = prev is None or (prev["price"] != p.price)
    stock_changed = prev is None or (prev["stock_status"] != p.stock_status)
    if price_changed or stock_changed:
        conn.execute(
            "INSERT INTO price_history (asin, price, currency, stock_status, checked_at) VALUES (?,?,?,?,?)",
            (p.asin, p.price, p.currency, p.stock_status, saved_at),
        )

    conn.execute(
        """
        INSERT INTO products (asin, title, brand, price, currency, images, description,
                              stock_status, amazon_url, source_marketplace, saved_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(asin) DO UPDATE SET
            title=excluded.title,
            brand=excluded.brand,
            price=excluded.price,
            currency=excluded.currency,
            images=excluded.images,
            description=excluded.description,
            stock_status=excluded.stock_status,
            amazon_url=excluded.amazon_url,
            source_marketplace=excluded.source_marketplace,
            saved_at=excluded.saved_at
        """,
        (
            p.asin, p.title, p.brand, p.price, p.currency,
            json.dumps(p.images), p.description, p.stock_status,
            p.amazon_url, p.source_marketplace, saved_at,
        ),
    )
    row = conn.execute("SELECT * FROM products WHERE asin = ?", (p.asin,)).fetchone()
    return row_to_product(row)


@app.post("/api/products")
def save_product(payload: ProductIn, background: BackgroundTasks):
    with db() as conn:
        prev = conn.execute(
            "SELECT price FROM products WHERE asin = ?", (payload.asin,)
        ).fetchone()
        prev_price = prev["price"] if prev else None
        product = _upsert(conn, payload)
    if payload.price is not None and prev_price != payload.price:
        background.add_task(maybe_auto_reprice, payload.asin, payload.price)
    return {"ok": True, "product": product}


@app.post("/api/products/bulk")
def save_products_bulk(payload: list[ProductIn], background: BackgroundTasks):
    out = []
    with db() as conn:
        for p in payload:
            prev = conn.execute("SELECT price FROM products WHERE asin = ?", (p.asin,)).fetchone()
            prev_price = prev["price"] if prev else None
            out.append(_upsert(conn, p))
            if p.price is not None and prev_price != p.price:
                background.add_task(maybe_auto_reprice, p.asin, p.price)
    return {"ok": True, "count": len(out), "products": out}


@app.get("/api/products")
def list_products(q: Optional[str] = None, limit: int = 500):
    with db() as conn:
        if q:
            like = f"%{q.lower()}%"
            rows = conn.execute(
                """
                SELECT * FROM products
                WHERE lower(title) LIKE ? OR lower(asin) LIKE ? OR lower(brand) LIKE ?
                ORDER BY saved_at DESC LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM products ORDER BY saved_at DESC LIMIT ?", (limit,),
            ).fetchall()
    return [row_to_product(r) for r in rows]


@app.get("/api/products/{asin}")
def get_product(asin: str):
    with db() as conn:
        r = conn.execute("SELECT * FROM products WHERE asin = ?", (asin,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="not found")
    return row_to_product(r)


@app.delete("/api/products/{asin}")
def delete_product(asin: str):
    with db() as conn:
        cur = conn.execute("DELETE FROM products WHERE asin = ?", (asin,))
        conn.execute("DELETE FROM price_history WHERE asin = ?", (asin,))
    return {"ok": True, "deleted": cur.rowcount}


@app.get("/api/products/{asin}/history")
def product_history(asin: str, limit: int = 100):
    """Return chronological price/stock snapshots for one product."""
    with db() as conn:
        rows = conn.execute(
            """
            SELECT price, currency, stock_status, checked_at
            FROM price_history
            WHERE asin = ?
            ORDER BY checked_at ASC
            LIMIT ?
            """,
            (asin, limit),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/alerts")
def alerts(days: int = 7, limit: int = 50):
    """Recent price/stock changes across all products."""
    with db() as conn:
        rows = conn.execute(
            """
            SELECT h.asin, h.price, h.currency, h.stock_status, h.checked_at,
                   p.title, p.brand, p.images, p.amazon_url
            FROM price_history h
            JOIN products p ON p.asin = h.asin
            WHERE h.checked_at >= datetime('now', ?)
            ORDER BY h.checked_at DESC
            LIMIT ?
            """,
            (f"-{int(days)} days", limit),
        ).fetchall()

    # Group by asin and pair each snapshot with the previous one to compute deltas
    by_asin: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_asin.setdefault(r["asin"], []).append(r)

    out = []
    for asin, snaps in by_asin.items():
        # snaps are newest-first within this asin (since global query is DESC)
        # need previous snapshot from the full table to compute delta vs older state
        with db() as conn:
            full = conn.execute(
                "SELECT price, stock_status, checked_at FROM price_history WHERE asin = ? ORDER BY checked_at ASC",
                (asin,),
            ).fetchall()
        for snap in snaps:
            idx = next((i for i, x in enumerate(full) if x["checked_at"] == snap["checked_at"]), -1)
            prev_snap = full[idx - 1] if idx > 0 else None
            price_delta = None
            if prev_snap is not None and prev_snap["price"] is not None and snap["price"] is not None:
                price_delta = round(float(snap["price"]) - float(prev_snap["price"]), 2)
            stock_delta = None
            if prev_snap is not None and prev_snap["stock_status"] != snap["stock_status"]:
                stock_delta = f"{prev_snap['stock_status']} → {snap['stock_status']}"
            try:
                images = json.loads(snap["images"] or "[]")
            except Exception:
                images = []
            out.append({
                "asin": asin,
                "title": snap["title"],
                "brand": snap["brand"],
                "image": images[0] if images else None,
                "amazon_url": snap["amazon_url"],
                "price": snap["price"],
                "currency": snap["currency"],
                "stock_status": snap["stock_status"],
                "checked_at": snap["checked_at"],
                "price_delta": price_delta,
                "stock_delta": stock_delta,
                "is_first_snapshot": prev_snap is None,
            })

    out.sort(key=lambda x: x["checked_at"], reverse=True)
    # Filter out "first-time saves" — they aren't real change alerts
    out = [a for a in out if not a["is_first_snapshot"]]
    return out[:limit]


@app.delete("/api/products")
def clear_products():
    with db() as conn:
        cur = conn.execute("DELETE FROM products")
    return {"ok": True, "deleted": cur.rowcount}


# ---------------------------------------------------------------------------
# Routes — orders
# ---------------------------------------------------------------------------
@app.get("/api/settings")
def api_get_settings():
    s = get_settings_dict()
    return {
        "auto_reprice_enabled": s["auto_reprice_enabled"].lower() == "true",
        "markup_percent": float(s["markup_percent"]),
        "min_reprice_change_percent": float(s["min_reprice_change_percent"]),
        "amazon_email": s.get("amazon_email", ""),
        # Never return the password — only indicate whether one is set
        "amazon_password_set": bool(s.get("amazon_password", "").strip()),
        "auto_fulfill_enabled": s.get("auto_fulfill_enabled", "false").lower() == "true",
        "fulfillment_headless": s.get("fulfillment_headless", "false").lower() == "true",
        "fulfillment_dry_run": s.get("fulfillment_dry_run", "true").lower() == "true",
        "ebay_fvf_percent": float(s.get("ebay_fvf_percent", "13.25")),
        "ebay_per_order_fee": float(s.get("ebay_per_order_fee", "0.30")),
        "ebay_ad_rate_percent": float(s.get("ebay_ad_rate_percent", "0")),
        "amazon_shipping_cost": float(s.get("amazon_shipping_cost", "0")),
    }


class SettingsIn(BaseModel):
    auto_reprice_enabled: Optional[bool] = None
    markup_percent: Optional[float] = None
    min_reprice_change_percent: Optional[float] = None
    amazon_email: Optional[str] = None
    amazon_password: Optional[str] = None
    auto_fulfill_enabled: Optional[bool] = None
    fulfillment_headless: Optional[bool] = None
    fulfillment_dry_run: Optional[bool] = None
    ebay_fvf_percent: Optional[float] = None
    ebay_per_order_fee: Optional[float] = None
    ebay_ad_rate_percent: Optional[float] = None
    amazon_shipping_cost: Optional[float] = None


@app.put("/api/settings")
def api_update_settings(payload: SettingsIn):
    if payload.auto_reprice_enabled is not None:
        set_setting("auto_reprice_enabled", "true" if payload.auto_reprice_enabled else "false")
    if payload.markup_percent is not None:
        set_setting("markup_percent", str(payload.markup_percent))
    if payload.min_reprice_change_percent is not None:
        set_setting("min_reprice_change_percent", str(payload.min_reprice_change_percent))
    if payload.amazon_email is not None:
        set_setting("amazon_email", payload.amazon_email.strip())
    if payload.amazon_password is not None:
        # Empty string = leave unchanged; "—" sentinel = clear it
        if payload.amazon_password == "":
            pass
        elif payload.amazon_password == "__CLEAR__":
            set_setting("amazon_password", "")
        else:
            set_setting("amazon_password", payload.amazon_password)
    if payload.auto_fulfill_enabled is not None:
        set_setting("auto_fulfill_enabled", "true" if payload.auto_fulfill_enabled else "false")
    if payload.fulfillment_headless is not None:
        set_setting("fulfillment_headless", "true" if payload.fulfillment_headless else "false")
    if payload.fulfillment_dry_run is not None:
        set_setting("fulfillment_dry_run", "true" if payload.fulfillment_dry_run else "false")
    if payload.ebay_fvf_percent is not None:
        set_setting("ebay_fvf_percent", str(payload.ebay_fvf_percent))
    if payload.ebay_per_order_fee is not None:
        set_setting("ebay_per_order_fee", str(payload.ebay_per_order_fee))
    if payload.ebay_ad_rate_percent is not None:
        set_setting("ebay_ad_rate_percent", str(payload.ebay_ad_rate_percent))
    if payload.amazon_shipping_cost is not None:
        set_setting("amazon_shipping_cost", str(payload.amazon_shipping_cost))
    return api_get_settings()


# ---------------------------------------------------------------------------
# Routes — buyer-message templates
# ---------------------------------------------------------------------------
class TemplateIn(BaseModel):
    slug: Optional[str] = None
    name: str
    kind: str = "custom"
    subject: str
    body: str


def _row_to_template(r: sqlite3.Row) -> dict[str, Any]:
    return dict(r)


def _slugify(s: str) -> str:
    out = "".join(c if c.isalnum() else "_" for c in s.strip().lower())
    return "_".join(filter(None, out.split("_")))[:60] or "template"


@app.get("/api/message-templates")
def list_templates():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM message_templates ORDER BY id ASC"
        ).fetchall()
    return [_row_to_template(r) for r in rows]


@app.post("/api/message-templates")
def create_template(payload: TemplateIn):
    now = datetime.now(timezone.utc).isoformat()
    slug = payload.slug or _slugify(payload.name)
    with db() as conn:
        # Ensure unique slug
        base, n = slug, 2
        while conn.execute("SELECT 1 FROM message_templates WHERE slug = ?", (slug,)).fetchone():
            slug = f"{base}_{n}"
            n += 1
        cur = conn.execute(
            """INSERT INTO message_templates (slug, name, kind, subject, body, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (slug, payload.name, payload.kind, payload.subject, payload.body, now, now),
        )
        row = conn.execute(
            "SELECT * FROM message_templates WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return _row_to_template(row)


@app.put("/api/message-templates/{template_id}")
def update_template(template_id: int, payload: TemplateIn):
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        if not conn.execute("SELECT 1 FROM message_templates WHERE id = ?", (template_id,)).fetchone():
            raise HTTPException(404, "template not found")
        conn.execute(
            """UPDATE message_templates SET name=?, kind=?, subject=?, body=?, updated_at=?
               WHERE id=?""",
            (payload.name, payload.kind, payload.subject, payload.body, now, template_id),
        )
        row = conn.execute(
            "SELECT * FROM message_templates WHERE id = ?", (template_id,)
        ).fetchone()
    return _row_to_template(row)


@app.delete("/api/message-templates/{template_id}")
def delete_template(template_id: int):
    with db() as conn:
        cur = conn.execute("DELETE FROM message_templates WHERE id = ?", (template_id,))
    return {"ok": True, "deleted": cur.rowcount}


class RenderIn(BaseModel):
    variables: dict[str, str] = Field(default_factory=dict)


@app.post("/api/message-templates/{template_id}/render")
def render_template(template_id: int, payload: RenderIn):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM message_templates WHERE id = ?", (template_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "template not found")

    def safe_sub(text: str) -> str:
        for key, value in payload.variables.items():
            text = text.replace("{" + key + "}", str(value))
        return text

    return {
        "subject": safe_sub(row["subject"]),
        "body": safe_sub(row["body"]),
    }


@app.get("/api/listings")
def api_listings():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM ebay_listings ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Routes — orders (eBay sync + tracking submit)
# ---------------------------------------------------------------------------
@app.get("/api/orders")
def list_orders():
    with db() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def _addr_field(addr: dict, *keys, default="") -> str:
    cur = addr
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur or default


def _persist_order(order: dict[str, Any]) -> None:
    """Map an eBay Fulfillment API order JSON into our orders table."""
    line_items = order.get("lineItems", []) or []
    if not line_items:
        return
    li = line_items[0]
    sku = li.get("sku") or ""
    asin = sku[len("DROPLY-"):] if sku.startswith("DROPLY-") else None

    buyer = order.get("buyer", {}) or {}
    fs = (order.get("fulfillmentStartInstructions") or [{}])[0]
    ship = (fs.get("shippingStep") or {}).get("shipTo") or {}
    addr = ship.get("contactAddress", {}) or {}
    total = (order.get("pricingSummary") or {}).get("total", {}) or {}

    sale_price = float(total.get("value") or 0)
    amazon_cost = 0.0
    if asin:
        with db() as conn:
            row = conn.execute("SELECT price FROM products WHERE asin = ?", (asin,)).fetchone()
        amazon_cost = float((row["price"] if row and row["price"] is not None else 0) or 0)
    profit = round(sale_price - amazon_cost, 2)

    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO orders (
                ebay_order_id, product_asin, sku, line_item_id, ebay_item_id, quantity,
                buyer_name, buyer_username,
                ship_to_name, ship_to_line1, ship_to_line2, ship_to_city,
                ship_to_state, ship_to_postal, ship_to_country,
                sale_price, amazon_cost, profit, currency,
                status, tracking_number, tracking_carrier, tracking_submitted_at,
                created_at, synced_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ebay_order_id) DO UPDATE SET
                product_asin=excluded.product_asin,
                sku=excluded.sku,
                quantity=excluded.quantity,
                buyer_name=excluded.buyer_name,
                buyer_username=excluded.buyer_username,
                ship_to_name=excluded.ship_to_name,
                ship_to_line1=excluded.ship_to_line1,
                ship_to_line2=excluded.ship_to_line2,
                ship_to_city=excluded.ship_to_city,
                ship_to_state=excluded.ship_to_state,
                ship_to_postal=excluded.ship_to_postal,
                ship_to_country=excluded.ship_to_country,
                sale_price=excluded.sale_price,
                amazon_cost=excluded.amazon_cost,
                profit=excluded.profit,
                currency=excluded.currency,
                status=excluded.status,
                synced_at=excluded.synced_at
            """,
            (
                order.get("orderId"),
                asin,
                sku,
                li.get("lineItemId"),
                li.get("legacyItemId"),
                int(li.get("quantity") or 1),
                ship.get("fullName") or buyer.get("username") or "",
                buyer.get("username") or "",
                ship.get("fullName") or "",
                _addr_field(addr, "addressLine1"),
                _addr_field(addr, "addressLine2"),
                _addr_field(addr, "city"),
                _addr_field(addr, "stateOrProvince"),
                _addr_field(addr, "postalCode"),
                _addr_field(addr, "countryCode"),
                sale_price,
                amazon_cost,
                profit,
                total.get("currency") or "USD",
                (order.get("orderFulfillmentStatus") or "PENDING").lower(),
                None, None, None,
                order.get("creationDate") or now,
                now,
            ),
        )


@app.post("/api/orders/sync")
async def sync_orders(limit: int = 50):
    """Fetch recent orders from eBay Fulfillment API and persist them."""
    token = await get_valid_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{EBAY_API_BASE}/sell/fulfillment/v1/order",
            headers=headers,
            params={"limit": min(max(int(limit), 1), 200)},
        )
    if r.status_code != 200:
        raise HTTPException(502, f"eBay order fetch failed: {r.text}")
    data = r.json()
    orders = data.get("orders", []) or []
    for o in orders:
        _persist_order(o)
    return {"ok": True, "synced": len(orders)}


class TrackingIn(BaseModel):
    tracking_number: str
    carrier: str = "USPS"  # eBay carrier code, e.g. "USPS", "FEDEX", "UPS"


@app.post("/api/orders/{order_id}/tracking")
async def submit_tracking(order_id: str, payload: TrackingIn):
    """Push tracking to eBay (creates a shipping_fulfillment) and store locally."""
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE ebay_order_id = ?", (order_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "order not found")
    if not row["line_item_id"]:
        raise HTTPException(400, "order has no line item id")

    token = await get_valid_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "lineItems": [{
            "lineItemId": row["line_item_id"],
            "quantity": int(row["quantity"] or 1),
        }],
        "shippedDate": datetime.now(timezone.utc).isoformat(),
        "shippingCarrierCode": payload.carrier.upper(),
        "trackingNumber": payload.tracking_number,
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{EBAY_API_BASE}/sell/fulfillment/v1/order/{order_id}/shipping_fulfillment",
            headers=headers,
            json=body,
        )
    if r.status_code not in (200, 201):
        raise HTTPException(502, f"eBay tracking submit failed: {r.text}")

    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """UPDATE orders SET tracking_number = ?, tracking_carrier = ?,
                                  tracking_submitted_at = ?, status = 'shipped'
               WHERE ebay_order_id = ?""",
            (payload.tracking_number, payload.carrier.upper(), now, order_id),
        )
    return {"ok": True}


@app.get("/api/orders/{order_id}")
def get_order(order_id: str):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE ebay_order_id = ?", (order_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "order not found")
    return dict(row)


# ---------------------------------------------------------------------------
# Routes — auto-fulfillment (Playwright Amazon checkout)
# ---------------------------------------------------------------------------
class FulfillIn(BaseModel):
    dry_run: Optional[bool] = None
    headless: Optional[bool] = None


@app.post("/api/orders/{order_id}/fulfill")
async def fulfill_order(order_id: str, body: FulfillIn = FulfillIn()):
    from fulfillment import (
        BuyerAddress, FulfillRequest, fulfill_on_amazon,
        record_attempt_start, record_attempt_finish,
    )

    with db() as conn:
        order = conn.execute(
            "SELECT * FROM orders WHERE ebay_order_id = ?", (order_id,)
        ).fetchone()
    if not order:
        raise HTTPException(404, "order not found")
    if not order["product_asin"]:
        raise HTTPException(400, "order has no linked product ASIN")

    with db() as conn:
        product = conn.execute(
            "SELECT * FROM products WHERE asin = ?", (order["product_asin"],)
        ).fetchone()
    if not product or not product["amazon_url"]:
        raise HTTPException(400, "product (or its amazon_url) is missing")

    cfg = get_settings_dict()
    email = cfg.get("amazon_email", "").strip()
    password = cfg.get("amazon_password", "").strip()
    if not email or not password:
        raise HTTPException(400, "Amazon credentials not configured (Settings → Amazon account)")

    dry_run = body.dry_run if body.dry_run is not None else cfg.get("fulfillment_dry_run", "true").lower() == "true"
    headless = body.headless if body.headless is not None else cfg.get("fulfillment_headless", "false").lower() == "true"

    req = FulfillRequest(
        ebay_order_id=order["ebay_order_id"],
        asin=order["product_asin"],
        amazon_url=product["amazon_url"],
        quantity=int(order["quantity"] or 1),
        buyer=BuyerAddress(
            full_name=order["ship_to_name"] or order["buyer_name"] or "",
            street1=order["ship_to_line1"] or "",
            street2=order["ship_to_line2"] or "",
            city=order["ship_to_city"] or "",
            state=order["ship_to_state"] or "",
            postal_code=order["ship_to_postal"] or "",
            country_code=order["ship_to_country"] or "US",
            phone="",
        ),
    )

    with db() as conn:
        attempt_id = record_attempt_start(conn, req)

    result = await fulfill_on_amazon(
        req=req, amazon_email=email, amazon_password=password,
        headless=headless, dry_run=dry_run,
    )

    with db() as conn:
        record_attempt_finish(conn, attempt_id, result)
        if result.amazon_order_id:
            conn.execute(
                "UPDATE orders SET status = 'fulfilled' WHERE ebay_order_id = ?",
                (order_id,),
            )

    return {
        "ok": result.status in ("success", "dry_run"),
        "attempt_id": attempt_id,
        "status": result.status,
        "amazon_order_id": result.amazon_order_id,
        "tracking_number": result.tracking_number,
        "carrier": result.carrier,
        "error": result.error,
        "screenshot_path": result.screenshot_path,
    }


@app.get("/api/orders/{order_id}/fulfillment-attempts")
def list_attempts(order_id: str):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM fulfillment_attempts WHERE ebay_order_id = ? ORDER BY started_at DESC",
            (order_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Routes — stats
# ---------------------------------------------------------------------------
@app.get("/api/stats")
def stats():
    today = date.today().isoformat()
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
        in_stock = conn.execute(
            "SELECT COUNT(*) AS c FROM products WHERE stock_status = 'in_stock'"
        ).fetchone()["c"]
        out_of_stock = conn.execute(
            "SELECT COUNT(*) AS c FROM products WHERE stock_status = 'out_of_stock'"
        ).fetchone()["c"]
        avg_row = conn.execute(
            "SELECT AVG(price) AS a, SUM(price) AS s, MIN(price) AS lo, MAX(price) AS hi "
            "FROM products WHERE price IS NOT NULL AND price > 0"
        ).fetchone()
        saved_today = conn.execute(
            "SELECT COUNT(*) AS c FROM products WHERE substr(saved_at,1,10) = ?", (today,),
        ).fetchone()["c"]
        rows = conn.execute(
            """
            SELECT substr(saved_at,1,10) AS day, COUNT(*) AS c
            FROM products
            GROUP BY day
            ORDER BY day DESC
            LIMIT 14
            """
        ).fetchall()
        brands = conn.execute(
            """
            SELECT brand, COUNT(*) AS c FROM products
            WHERE brand IS NOT NULL AND brand <> ''
            GROUP BY brand ORDER BY c DESC LIMIT 6
            """
        ).fetchall()

    by_day_map = {r["day"]: r["c"] for r in rows}
    series = []
    for i in range(13, -1, -1):
        d = (datetime.utcnow().date().toordinal() - i)
        d_str = date.fromordinal(d).isoformat()
        series.append({"day": d_str[5:], "count": by_day_map.get(d_str, 0)})

    return {
        "total": total,
        "in_stock": in_stock,
        "out_of_stock": out_of_stock,
        "saved_today": saved_today,
        "avg_price": float(avg_row["a"] or 0),
        "total_value": float(avg_row["s"] or 0),
        "min_price": float(avg_row["lo"] or 0),
        "max_price": float(avg_row["hi"] or 0),
        "series": series,
        "top_brands": [{"brand": b["brand"], "count": b["c"]} for b in brands],
    }
