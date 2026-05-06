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
from fastapi import FastAPI, HTTPException, Query
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_asin TEXT,
                buyer_name TEXT,
                sale_price REAL,
                amazon_cost REAL,
                profit REAL,
                status TEXT DEFAULT 'pending',
                tracking_number TEXT,
                created_at TEXT
            )
        """)
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
def save_product(payload: ProductIn):
    with db() as conn:
        return {"ok": True, "product": _upsert(conn, payload)}


@app.post("/api/products/bulk")
def save_products_bulk(payload: list[ProductIn]):
    with db() as conn:
        out = [_upsert(conn, p) for p in payload]
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
@app.get("/api/orders")
def list_orders():
    with db() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
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
