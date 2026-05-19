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
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, date, timedelta, timezone
from html import escape as html_escape
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
# Legacy Trading API endpoint — still the only supported channel for buyer messages.
EBAY_TRADING_URL = f"{EBAY_API_BASE}/ws/api.dll"
EBAY_TRADING_COMPAT_LEVEL = "1193"
EBAY_TRADING_SITE_ID = os.getenv("EBAY_TRADING_SITE_ID", "0")  # 0 = US, 3 = UK, 77 = DE …

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
# ---------------------------------------------------------------------------
# Default VeRO brand watchlist (Verified Rights Owner programs publicly known
# for aggressive enforcement on eBay / dropshipping). Sellers can add or
# remove entries via /api/vero/brands.
#   keyword: substring matched case-insensitively against title + brand
#   reason:  short human-readable explanation
#   level:   "block" (refuse to publish) or "warn" (just badge it)
# ---------------------------------------------------------------------------
DEFAULT_VERO_BRANDS: list[tuple[str, str, str]] = [
    ("apple", "Apple — VeRO IP holder, frequent takedowns", "block"),
    ("airpods", "Apple AirPods — high-risk", "block"),
    ("nike", "Nike — VeRO IP holder", "block"),
    ("adidas", "Adidas — VeRO IP holder", "block"),
    ("yeezy", "Adidas Yeezy", "block"),
    ("supreme", "Supreme — VeRO IP holder", "block"),
    ("disney", "Disney — VeRO IP holder", "block"),
    ("marvel", "Marvel / Disney IP", "block"),
    ("star wars", "Lucasfilm / Disney IP", "block"),
    ("pokemon", "Pokémon Company / Nintendo", "block"),
    ("pokémon", "Pokémon Company / Nintendo", "block"),
    ("nintendo", "Nintendo — VeRO IP holder", "block"),
    ("sony", "Sony — VeRO IP holder", "warn"),
    ("microsoft", "Microsoft — VeRO IP holder", "warn"),
    ("xbox", "Microsoft Xbox", "block"),
    ("playstation", "Sony PlayStation", "block"),
    ("louis vuitton", "Louis Vuitton — luxury VeRO", "block"),
    ("gucci", "Gucci — luxury VeRO", "block"),
    ("chanel", "Chanel — luxury VeRO", "block"),
    ("hermes", "Hermès — luxury VeRO", "block"),
    ("hermès", "Hermès — luxury VeRO", "block"),
    ("rolex", "Rolex — VeRO IP holder", "block"),
    ("cartier", "Cartier — luxury VeRO", "block"),
    ("tiffany", "Tiffany & Co — VeRO IP holder", "block"),
    ("burberry", "Burberry — VeRO IP holder", "block"),
    ("prada", "Prada — VeRO IP holder", "block"),
    ("versace", "Versace — VeRO IP holder", "block"),
    ("ralph lauren", "Ralph Lauren — VeRO IP holder", "warn"),
    ("calvin klein", "Calvin Klein — VeRO IP holder", "warn"),
    ("tommy hilfiger", "Tommy Hilfiger — VeRO IP holder", "warn"),
    ("coach", "Coach — VeRO IP holder", "warn"),
    ("lego", "LEGO — VeRO IP holder", "block"),
    ("nfl", "NFL — license required", "block"),
    ("nba", "NBA — license required", "block"),
    ("mlb", "MLB — license required", "block"),
    ("harry potter", "Warner Bros / Wizarding World", "block"),
    ("beats by dre", "Beats by Dre / Apple", "block"),
    ("bose", "Bose — VeRO IP holder", "warn"),
    ("fitbit", "Fitbit / Google", "warn"),
    ("tesla", "Tesla — VeRO IP holder", "warn"),
    ("dyson", "Dyson — VeRO IP holder", "warn"),
]


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
        # Migrate orders schema additively for tracking_status if needed
        cur = conn.execute("PRAGMA table_info(orders)").fetchall()
        if cur:
            cols = {c["name"] for c in cur}
            if "tracking_status" not in cols:
                conn.execute("ALTER TABLE orders ADD COLUMN tracking_status TEXT")
            if "tracking_status_text" not in cols:
                conn.execute("ALTER TABLE orders ADD COLUMN tracking_status_text TEXT")
            if "tracking_checked_at" not in cols:
                conn.execute("ALTER TABLE orders ADD COLUMN tracking_checked_at TEXT")

        # Migrate the old orders schema (auto-incrementing id) → new ebay_order_id PK
        cur = conn.execute("PRAGMA table_info(orders)").fetchall()
        if cur and not any(c["name"] == "ebay_order_id" for c in cur):
            existing = conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"]
            if existing == 0:
                conn.execute("DROP TABLE orders")

        # Additive migration for outbound_messages: track per-row send errors.
        cur = conn.execute("PRAGMA table_info(outbound_messages)").fetchall()
        if cur:
            ocols = {c["name"] for c in cur}
            if "error" not in ocols:
                conn.execute("ALTER TABLE outbound_messages ADD COLUMN error TEXT")
            if "last_attempt_at" not in ocols:
                conn.execute("ALTER TABLE outbound_messages ADD COLUMN last_attempt_at TEXT")

        # Additive migration for ebay_listings: inventory-sync state.
        # `paused` = 1 when Droply has set the listing's quantity to 0 because
        # the upstream Amazon product went out of stock. `last_quantity` holds
        # the pre-pause quantity so we can restore it when stock comes back.
        cur = conn.execute("PRAGMA table_info(ebay_listings)").fetchall()
        if cur:
            lcols = {c["name"] for c in cur}
            if "paused" not in lcols:
                conn.execute("ALTER TABLE ebay_listings ADD COLUMN paused INTEGER NOT NULL DEFAULT 0")
            if "paused_at" not in lcols:
                conn.execute("ALTER TABLE ebay_listings ADD COLUMN paused_at TEXT")
            if "paused_reason" not in lcols:
                conn.execute("ALTER TABLE ebay_listings ADD COLUMN paused_reason TEXT")
            if "last_quantity" not in lcols:
                conn.execute("ALTER TABLE ebay_listings ADD COLUMN last_quantity INTEGER NOT NULL DEFAULT 1")

        # Additive migration for products: store the resolved eBay category so
        # we don't re-call the Taxonomy API on every publish, plus item
        # specifics (Phase 2.2): aspects, scraped Amazon spec table, and a
        # flag the UI uses to surface "needs attention" rows.
        cur = conn.execute("PRAGMA table_info(products)").fetchall()
        if cur:
            pcols = {c["name"] for c in cur}
            if "ebay_category_id" not in pcols:
                conn.execute("ALTER TABLE products ADD COLUMN ebay_category_id TEXT")
            if "ebay_category_name" not in pcols:
                conn.execute("ALTER TABLE products ADD COLUMN ebay_category_name TEXT")
            if "ebay_aspects" not in pcols:
                conn.execute("ALTER TABLE products ADD COLUMN ebay_aspects TEXT")
            if "spec_table" not in pcols:
                conn.execute("ALTER TABLE products ADD COLUMN spec_table TEXT")
            if "aspects_needs_attention" not in pcols:
                conn.execute("ALTER TABLE products ADD COLUMN aspects_needs_attention INTEGER NOT NULL DEFAULT 0")
            if "preferred_marketplace_id" not in pcols:
                conn.execute("ALTER TABLE products ADD COLUMN preferred_marketplace_id TEXT")

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
                saved_at TEXT,
                ebay_category_id TEXT,
                ebay_category_name TEXT,
                ebay_aspects TEXT,
                spec_table TEXT,
                aspects_needs_attention INTEGER NOT NULL DEFAULT 0,
                preferred_marketplace_id TEXT
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
                paused INTEGER NOT NULL DEFAULT 0,
                paused_at TEXT,
                paused_reason TEXT,
                last_quantity INTEGER NOT NULL DEFAULT 1,
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

        # VeRO (Verified Rights Owner) brand watchlist — flags products before
        # they get listed and risk an account suspension.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vero_brands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT UNIQUE NOT NULL,
                reason TEXT,
                level TEXT NOT NULL DEFAULT 'block',
                created_at TEXT NOT NULL
            )
        """)
        existing = conn.execute("SELECT COUNT(*) AS c FROM vero_brands").fetchone()["c"]
        if existing == 0:
            now = datetime.now(timezone.utc).isoformat()
            for keyword, reason, level in DEFAULT_VERO_BRANDS:
                conn.execute(
                    """INSERT INTO vero_brands (keyword, reason, level, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (keyword.lower(), reason, level, now),
                )

        # Outbound buyer messages. Queued by event triggers (order_confirmed,
        # shipped, delivered, …), then flushed to eBay's Trading API by the
        # scheduler. `status` ∈ {queued, sent, failed}.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS outbound_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ebay_order_id TEXT NOT NULL,
                template_slug TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                trigger_event TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sent_at TEXT,
                error TEXT,
                last_attempt_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_outbound_order ON outbound_messages(ebay_order_id, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_outbound_status ON outbound_messages(status, created_at DESC)")

        # Inbound buyer messages (Phase 4.1). Polled from eBay Trading
        # GetMyMessages; each row corresponds to one MessageID. Multi-account
        # safe via the account_id column. `needs_reply` flips to 0 when we
        # auto-reply or the user marks the row replied.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS inbound_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                ebay_message_id TEXT NOT NULL,
                ebay_order_id TEXT,
                ebay_item_id TEXT,
                sender_username TEXT,
                subject TEXT,
                body TEXT,
                received_at TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                read_at TEXT,
                replied_at TEXT,
                auto_replied INTEGER NOT NULL DEFAULT 0,
                matched_rule_id INTEGER,
                needs_reply INTEGER NOT NULL DEFAULT 1,
                raw_json TEXT,
                UNIQUE (account_id, ebay_message_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inbound_received ON inbound_messages(received_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inbound_needs_reply ON inbound_messages(needs_reply, received_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inbound_order ON inbound_messages(ebay_order_id, received_at DESC)")

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

        # Description templates — used at publish time to wrap the raw Amazon
        # description with seller branding, shipping/returns notices, etc.
        # Variables supported: {title} {brand} {asin} {description} {price}
        # {currency} plus any key from the product's spec_table.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS description_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        existing = conn.execute("SELECT COUNT(*) AS c FROM description_templates").fetchone()["c"]
        if existing == 0:
            now = datetime.now(timezone.utc).isoformat()
            default_body = (
                "<p><b>{title}</b></p>\n"
                "<p><b>Brand:</b> {brand}</p>\n"
                "<p>{description}</p>\n"
                "<hr>\n"
                "<ul>\n"
                "  <li>Brand new in original packaging</li>\n"
                "  <li>Fast dispatch from a trusted seller</li>\n"
                "  <li>30-day returns accepted</li>\n"
                "</ul>"
            )
            conn.execute(
                """INSERT INTO description_templates
                   (slug, name, body, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                ("default", "Default", default_body, now, now),
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

        # EasyPost tracker cache. Avoids re-billing on every refresh tick — we
        # only re-poll if `checked_at` is older than `easypost_cache_ttl_minutes`.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tracking_cache (
                carrier TEXT NOT NULL,
                tracking_number TEXT NOT NULL,
                easypost_tracker_id TEXT,
                status TEXT NOT NULL,
                status_text TEXT,
                checked_at TEXT NOT NULL,
                raw_json TEXT,
                PRIMARY KEY (carrier, tracking_number)
            )
        """)

        # eBay Taxonomy API: suggested-category cache per (marketplace, title).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS category_suggestions_cache (
                marketplace_id TEXT NOT NULL,
                title_hash TEXT NOT NULL,
                category_id TEXT NOT NULL,
                category_name TEXT,
                category_path TEXT,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (marketplace_id, title_hash)
            )
        """)

        # eBay Taxonomy API: aspect-schema cache per (marketplace, category).
        # The taxonomy moves slowly, so we re-fetch at most once per 30 days.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS category_aspects_cache (
                marketplace_id TEXT NOT NULL,
                category_id TEXT NOT NULL,
                aspects_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (marketplace_id, category_id)
            )
        """)

        # eBay seller accounts ("stores"). One row per connected eBay account.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ebay_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                sandbox INTEGER NOT NULL DEFAULT 1,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        # Per-account OAuth tokens. Replaces the old single-row ebay_tokens table.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ebay_tokens (
                account_id INTEGER PRIMARY KEY,
                access_token TEXT,
                refresh_token TEXT,
                expires_at INTEGER,
                refresh_expires_at INTEGER,
                scope TEXT,
                connected_at TEXT,
                FOREIGN KEY (account_id) REFERENCES ebay_accounts(id) ON DELETE CASCADE
            )
        """)

        # Migrate from the old single-row tokens table (id=1) → first account row.
        try:
            old = conn.execute(
                "SELECT * FROM ebay_tokens WHERE account_id IS NULL OR account_id = 1"
            ).fetchall()
        except sqlite3.OperationalError:
            old = []
        cols = {c["name"] for c in conn.execute("PRAGMA table_info(ebay_tokens)").fetchall()}
        if "id" in cols and "account_id" not in cols:
            # Old schema (id PK). Pull the legacy row, then rebuild the table.
            legacy_rows = conn.execute("SELECT * FROM ebay_tokens").fetchall()
            conn.execute("DROP TABLE ebay_tokens")
            conn.execute("""
                CREATE TABLE ebay_tokens (
                    account_id INTEGER PRIMARY KEY,
                    access_token TEXT,
                    refresh_token TEXT,
                    expires_at INTEGER,
                    refresh_expires_at INTEGER,
                    scope TEXT,
                    connected_at TEXT
                )
            """)
            now = datetime.now(timezone.utc).isoformat()
            if legacy_rows:
                # Create the default account (id=1) and copy the legacy tokens.
                conn.execute(
                    """INSERT INTO ebay_accounts (id, label, sandbox, is_active, created_at)
                       VALUES (1, 'Default account', ?, 1, ?)""",
                    (1 if EBAY_SANDBOX else 0, now),
                )
                lr = legacy_rows[0]
                conn.execute(
                    """INSERT INTO ebay_tokens (account_id, access_token, refresh_token,
                       expires_at, refresh_expires_at, scope, connected_at)
                       VALUES (1, ?, ?, ?, ?, ?, ?)""",
                    (lr["access_token"], lr["refresh_token"], lr["expires_at"],
                     lr["refresh_expires_at"], lr["scope"], lr["connected_at"]),
                )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_saved_at ON products(saved_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")


init_db()


# ---------------------------------------------------------------------------
# Background scheduler — AsyncIOScheduler needs a running event loop, so
# wire it through FastAPI's startup/shutdown hooks rather than module init.
# ---------------------------------------------------------------------------
from backend import scheduler as _droply_scheduler  # noqa: E402


@app.on_event("startup")
async def _start_droply_scheduler() -> None:
    _droply_scheduler.start()


@app.on_event("shutdown")
async def _stop_droply_scheduler() -> None:
    _droply_scheduler.shutdown()


# ---------------------------------------------------------------------------
# Helpers — products
# ---------------------------------------------------------------------------
def row_to_product(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    try:
        d["images"] = json.loads(d.get("images") or "[]")
    except Exception:
        d["images"] = []
    for jcol in ("ebay_aspects", "spec_table"):
        if jcol in d and d.get(jcol):
            try:
                d[jcol] = json.loads(d[jcol])
            except Exception:
                d[jcol] = {}
        elif jcol in d:
            d[jcol] = {}
    return d


# ---------------------------------------------------------------------------
# Helpers — eBay accounts + tokens (multi-store)
# ---------------------------------------------------------------------------
def get_active_account_id() -> Optional[int]:
    with db() as conn:
        r = conn.execute(
            "SELECT id FROM ebay_accounts WHERE is_active = 1 LIMIT 1"
        ).fetchone()
        if r:
            return r["id"]
        # Fall back to lowest-id account if none flagged active
        r = conn.execute("SELECT id FROM ebay_accounts ORDER BY id ASC LIMIT 1").fetchone()
        return r["id"] if r else None


def set_active_account_id(account_id: int) -> None:
    with db() as conn:
        conn.execute("UPDATE ebay_accounts SET is_active = 0")
        conn.execute("UPDATE ebay_accounts SET is_active = 1 WHERE id = ?", (account_id,))


def list_accounts_with_status() -> list[dict[str, Any]]:
    """Used by /api/ebay/accounts. Joins tokens to surface connection state."""
    now = int(time.time())
    with db() as conn:
        rows = conn.execute(
            """SELECT a.*, t.access_token, t.expires_at, t.refresh_expires_at,
                      t.connected_at AS token_connected_at
               FROM ebay_accounts a
               LEFT JOIN ebay_tokens t ON t.account_id = a.id
               ORDER BY a.id ASC"""
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["connected"] = bool(d.get("access_token"))
        d["token_valid"] = bool(d.get("access_token") and (d.get("expires_at") or 0) > now)
        d["refresh_valid"] = bool(d.get("refresh_token") if False else (d.get("refresh_expires_at") or 0) > now)
        d["sandbox"] = bool(d.get("sandbox"))
        d["is_active"] = bool(d.get("is_active"))
        # Don't leak the access token
        d.pop("access_token", None)
        out.append(d)
    return out


def _token_row(conn: sqlite3.Connection, account_id: Optional[int] = None) -> Optional[sqlite3.Row]:
    aid = account_id if account_id is not None else get_active_account_id()
    if aid is None:
        return None
    return conn.execute(
        "SELECT * FROM ebay_tokens WHERE account_id = ?", (aid,)
    ).fetchone()


def _save_tokens(conn: sqlite3.Connection, data: dict, account_id: int) -> None:
    expires_at = int(time.time()) + int(data.get("expires_in", 7200))
    refresh_expires_at = int(time.time()) + int(data.get("refresh_token_expires_in", 47304000))
    conn.execute(
        """
        INSERT INTO ebay_tokens (account_id, access_token, refresh_token, expires_at, refresh_expires_at, scope, connected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id) DO UPDATE SET
            access_token=excluded.access_token,
            refresh_token=excluded.refresh_token,
            expires_at=excluded.expires_at,
            refresh_expires_at=excluded.refresh_expires_at,
            scope=excluded.scope,
            connected_at=excluded.connected_at
        """,
        (
            account_id,
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
    # Carrier tracking (EasyPost)
    "easypost_api_key": "",
    "easypost_cache_ttl_minutes": "60",  # Re-poll EasyPost at most this often per (carrier, number)
    # Background scheduler — when "true", APScheduler runs the recurring jobs
    "scheduler_enabled": "true",
    # Description template used at publish time. Empty string = use raw
    # product description (the Amazon bullets).
    "default_description_template_slug": "default",
    # Tiered markup ladder (Phase 2.6). JSON list of brackets, processed in
    # order; the first bracket whose `max_price` is null or > amazon_price
    # wins. Falls back to `markup_percent` if empty.
    #   [{"max_price": 20, "markup_percent": 35},
    #    {"max_price": 50, "markup_percent": 25},
    #    {"max_price": null, "markup_percent": 20}]
    "margin_rules": "",
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
    markup_percent: float, quantity: int = 1,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO ebay_listings (asin, marketplace_id, sku, offer_id, listing_id,
                                       listing_url, last_price, currency, markup_percent,
                                       listed_at, updated_at, last_quantity, paused)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)
            ON CONFLICT(asin, marketplace_id) DO UPDATE SET
                sku=excluded.sku,
                offer_id=excluded.offer_id,
                listing_id=excluded.listing_id,
                listing_url=excluded.listing_url,
                last_price=excluded.last_price,
                currency=excluded.currency,
                markup_percent=excluded.markup_percent,
                updated_at=excluded.updated_at,
                last_quantity=excluded.last_quantity,
                paused=0,
                paused_at=NULL,
                paused_reason=NULL
            """,
            (asin, marketplace_id, sku, offer_id, listing_id, listing_url,
             price, currency, markup_percent, now, now, quantity),
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


def _parse_margin_rules(raw: str) -> list[dict[str, Any]]:
    """Best-effort JSON-decode of the saved `margin_rules` string for the
    settings GET response. Bad input → []."""
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(v, list):
        return []
    out = []
    for r in v:
        if isinstance(r, dict) and "markup_percent" in r:
            out.append({
                "max_price": r.get("max_price"),
                "markup_percent": r.get("markup_percent"),
            })
    return out


def markup_for_amazon_price(amazon_price: Optional[float]) -> float:
    """Return the markup-% to apply for a given Amazon price.

    Reads `margin_rules` from settings; brackets are processed in order and
    the first one matching wins. Falls back to flat `markup_percent` when
    the ladder is empty or malformed.
    """
    cfg = get_settings_dict()
    raw = (cfg.get("margin_rules") or "").strip()
    flat = float(cfg.get("markup_percent") or 30)
    if not raw or amazon_price is None:
        return flat
    try:
        rules = json.loads(raw)
    except (ValueError, TypeError):
        return flat
    if not isinstance(rules, list) or not rules:
        return flat
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        max_price = rule.get("max_price")
        try:
            markup = float(rule.get("markup_percent"))
        except (TypeError, ValueError):
            continue
        if max_price is None:
            return markup
        try:
            if float(amazon_price) <= float(max_price):
                return markup
        except (TypeError, ValueError):
            continue
    return flat


async def update_listing_quantity(
    *, sku: str, marketplace_id: str, quantity: int,
) -> tuple[bool, str]:
    """Set the eBay inventory item's availableQuantity for a SKU.

    Returns (ok, detail). We PUT the inventory_item rather than calling
    bulkUpdatePriceQuantity because we already have the SKU and the inventory
    endpoint is the canonical place that holds stock.
    """
    try:
        token = await get_valid_token()
    except HTTPException as e:
        return (False, f"no eBay token: {e.detail}")

    content_language = "en-US" if marketplace_id == "EBAY_US" else "en-GB"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept-Language": content_language,
        "Content-Language": content_language,
        "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
    }
    # eBay's PUT requires the full inventory item; fetch then patch availability.
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            rg = await client.get(
                f"{EBAY_API_BASE}/sell/inventory/v1/inventory_item/{sku}",
                headers=headers,
            )
            if rg.status_code != 200:
                return (False, f"GET inventory_item failed: HTTP {rg.status_code}")
            item = rg.json()
            item.setdefault("availability", {}).setdefault("shipToLocationAvailability", {})
            item["availability"]["shipToLocationAvailability"]["quantity"] = int(quantity)
            rp = await client.put(
                f"{EBAY_API_BASE}/sell/inventory/v1/inventory_item/{sku}",
                headers=headers,
                json=item,
            )
    except httpx.HTTPError as e:
        return (False, f"http error: {e}")

    if rp.status_code in (200, 204):
        return (True, "updated")
    return (False, f"PUT failed: HTTP {rp.status_code} {rp.text[:200]}")


async def maybe_sync_inventory(asin: str, new_stock_status: str) -> None:
    """Sync eBay availability with the latest Amazon stock signal.

    Called after a product upsert. If the product went out of stock and we
    have an active listing, pause it (quantity → 0). If it came back in stock
    and the listing is paused-by-Droply, restore the previous quantity.

    Listings paused manually by the user (with reason='manual') are left alone
    when stock comes back — the user can resume them explicitly.
    """
    if not new_stock_status:
        return
    with db() as conn:
        listings = conn.execute(
            "SELECT * FROM ebay_listings WHERE asin = ?", (asin,)
        ).fetchall()
    if not listings:
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    for listing in listings:
        sku = listing["sku"]
        marketplace_id = listing["marketplace_id"]

        if new_stock_status == "out_of_stock" and not listing["paused"]:
            ok, detail = await update_listing_quantity(
                sku=sku, marketplace_id=marketplace_id, quantity=0,
            )
            if ok:
                with db() as conn:
                    conn.execute(
                        """UPDATE ebay_listings
                              SET paused = 1, paused_at = ?, paused_reason = 'amazon_oos',
                                  updated_at = ?
                            WHERE asin = ? AND marketplace_id = ?""",
                        (now_iso, now_iso, asin, marketplace_id),
                    )

        elif new_stock_status == "in_stock" and listing["paused"] and (
            listing["paused_reason"] == "amazon_oos"
        ):
            qty = int(listing["last_quantity"] or 1)
            ok, detail = await update_listing_quantity(
                sku=sku, marketplace_id=marketplace_id, quantity=qty,
            )
            if ok:
                with db() as conn:
                    conn.execute(
                        """UPDATE ebay_listings
                              SET paused = 0, paused_at = NULL, paused_reason = NULL,
                                  updated_at = ?
                            WHERE asin = ? AND marketplace_id = ?""",
                        (now_iso, asin, marketplace_id),
                    )


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

    # Margin ladder (Phase 2.6) overrides any per-listing markup. If the
    # ladder is empty we fall back to the listing's saved markup, then the
    # flat `markup_percent` setting.
    if (cfg.get("margin_rules") or "").strip():
        markup = markup_for_amazon_price(new_amazon_price)
    else:
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


# ---------------------------------------------------------------------------
# Helpers — eBay Taxonomy API (category suggestions).
# Used at publish time so listings land in a real category instead of the
# catch-all "Everything Else". Item-specifics (aspects) build on this in 2.2.
# ---------------------------------------------------------------------------

# Marketplace → default category-tree id. Stable values, documented in
# https://developer.ebay.com/api-docs/sell/static/metadata/default-category-tree-ids.html
EBAY_CATEGORY_TREE_IDS = {
    "EBAY_US": "0",
    "EBAY_GB": "3",
    "EBAY_DE": "77",
    "EBAY_FR": "71",
    "EBAY_IT": "101",
    "EBAY_ES": "186",
    "EBAY_AU": "15",
    "EBAY_CA": "2",
    "EBAY_AT": "16",
    "EBAY_BE": "23",
    "EBAY_CH": "193",
    "EBAY_IE": "205",
    "EBAY_NL": "146",
    "EBAY_PL": "212",
    "EBAY_SG": "216",
    "EBAY_HK": "201",
}


def _category_tree_id(marketplace_id: str) -> str:
    return EBAY_CATEGORY_TREE_IDS.get(marketplace_id, "0")


# Marketplace-id → BCP-47 content language. eBay rejects requests where the
# Content-Language header doesn't match the marketplace's expected locale.
EBAY_MARKETPLACE_LANG = {
    "EBAY_US": "en-US",
    "EBAY_GB": "en-GB",
    "EBAY_AU": "en-AU",
    "EBAY_CA": "en-CA",
    "EBAY_DE": "de-DE",
    "EBAY_FR": "fr-FR",
    "EBAY_IT": "it-IT",
    "EBAY_ES": "es-ES",
    "EBAY_AT": "de-AT",
    "EBAY_BE": "nl-BE",
    "EBAY_CH": "de-CH",
    "EBAY_IE": "en-IE",
    "EBAY_NL": "nl-NL",
    "EBAY_PL": "pl-PL",
    "EBAY_SG": "en-SG",
    "EBAY_HK": "zh-HK",
}


def _content_language(marketplace_id: str) -> str:
    return EBAY_MARKETPLACE_LANG.get(marketplace_id, "en-US")


# Marketplace-id → ({country, postal_code, state, city, address}). eBay
# requires the merchant location's country to match the marketplace's country
# (i.e. you can't list on EBAY_GB from a US warehouse). These are sensible
# defaults so a fresh install works on every supported marketplace; users
# should override per-account in Phase 9 (`merchant_location` on ebay_accounts).
EBAY_MARKETPLACE_LOCATION = {
    "EBAY_US": {"country": "US", "postalCode": "94103", "stateOrProvince": "CA", "city": "San Francisco", "addressLine1": "1 Market St"},
    "EBAY_GB": {"country": "GB", "postalCode": "EC1A 1BB", "stateOrProvince": "England", "city": "London", "addressLine1": "1 Cheapside"},
    "EBAY_AU": {"country": "AU", "postalCode": "2000", "stateOrProvince": "NSW", "city": "Sydney", "addressLine1": "1 George St"},
    "EBAY_CA": {"country": "CA", "postalCode": "M5H 2N2", "stateOrProvince": "Ontario", "city": "Toronto", "addressLine1": "1 King St W"},
    "EBAY_DE": {"country": "DE", "postalCode": "10115", "stateOrProvince": "Berlin", "city": "Berlin", "addressLine1": "Friedrichstraße 1"},
    "EBAY_FR": {"country": "FR", "postalCode": "75001", "stateOrProvince": "Île-de-France", "city": "Paris", "addressLine1": "1 Rue de Rivoli"},
    "EBAY_IT": {"country": "IT", "postalCode": "00100", "stateOrProvince": "Lazio", "city": "Roma", "addressLine1": "Via del Corso 1"},
    "EBAY_ES": {"country": "ES", "postalCode": "28013", "stateOrProvince": "Madrid", "city": "Madrid", "addressLine1": "Gran Vía 1"},
    "EBAY_AT": {"country": "AT", "postalCode": "1010", "stateOrProvince": "Wien", "city": "Wien", "addressLine1": "Graben 1"},
    "EBAY_BE": {"country": "BE", "postalCode": "1000", "stateOrProvince": "Brussels", "city": "Brussels", "addressLine1": "Rue Neuve 1"},
    "EBAY_CH": {"country": "CH", "postalCode": "8001", "stateOrProvince": "Zürich", "city": "Zürich", "addressLine1": "Bahnhofstrasse 1"},
    "EBAY_IE": {"country": "IE", "postalCode": "D02", "stateOrProvince": "Dublin", "city": "Dublin", "addressLine1": "1 O'Connell St"},
    "EBAY_NL": {"country": "NL", "postalCode": "1012", "stateOrProvince": "Noord-Holland", "city": "Amsterdam", "addressLine1": "Damrak 1"},
    "EBAY_PL": {"country": "PL", "postalCode": "00-001", "stateOrProvince": "Mazowieckie", "city": "Warszawa", "addressLine1": "Marszałkowska 1"},
    "EBAY_SG": {"country": "SG", "postalCode": "238801", "stateOrProvince": "Singapore", "city": "Singapore", "addressLine1": "1 Orchard Rd"},
    "EBAY_HK": {"country": "HK", "postalCode": "999077", "stateOrProvince": "Hong Kong", "city": "Hong Kong", "addressLine1": "1 Queens Rd Central"},
}


def _merchant_location_for(marketplace_id: str) -> tuple[str, dict[str, str]]:
    """Return (location_key, address) for the marketplace. Key is namespaced
    per marketplace so locations don't collide across countries."""
    addr = EBAY_MARKETPLACE_LOCATION.get(marketplace_id) or EBAY_MARKETPLACE_LOCATION["EBAY_US"]
    return (f"DROPLY_{marketplace_id}", addr)


# Amazon hostname → eBay marketplace_id. Used to infer the default publish
# marketplace from a product's source. Falls back to EBAY_US.
AMAZON_HOST_TO_EBAY = {
    "www.amazon.com":   "EBAY_US",
    "amazon.com":       "EBAY_US",
    "www.amazon.co.uk": "EBAY_GB",
    "amazon.co.uk":     "EBAY_GB",
    "www.amazon.de":    "EBAY_DE",
    "amazon.de":        "EBAY_DE",
    "www.amazon.fr":    "EBAY_FR",
    "amazon.fr":        "EBAY_FR",
    "www.amazon.it":    "EBAY_IT",
    "amazon.it":        "EBAY_IT",
    "www.amazon.es":    "EBAY_ES",
    "amazon.es":        "EBAY_ES",
    "www.amazon.ca":    "EBAY_CA",
    "amazon.ca":        "EBAY_CA",
    "www.amazon.com.au": "EBAY_AU",
    "amazon.com.au":    "EBAY_AU",
}


def _default_marketplace_for_product(product: dict[str, Any]) -> str:
    """Pick a sensible default marketplace for a product.

    Precedence: product.preferred_marketplace_id > Amazon-host inference
    > EBAY_US.
    """
    pref = (product.get("preferred_marketplace_id") or "").strip()
    if pref:
        return pref
    source = (product.get("source_marketplace") or "").strip().lower()
    if source in AMAZON_HOST_TO_EBAY:
        return AMAZON_HOST_TO_EBAY[source]
    # Strip a possible leading www.
    if source.startswith("www."):
        source = source[4:]
        if source in AMAZON_HOST_TO_EBAY:
            return AMAZON_HOST_TO_EBAY[source]
    return "EBAY_US"


def _title_hash(s: str) -> str:
    """Cheap stable key so we cache suggestions per (marketplace, query).

    We don't care about cryptographic strength — just stable across runs.
    """
    import hashlib
    return hashlib.sha1((s or "").strip().lower().encode("utf-8")).hexdigest()[:16]


async def get_category_suggestions(
    *, token: str, marketplace_id: str, query: str,
) -> list[dict[str, Any]]:
    """Return up to 10 category suggestions for `query`.

    Each entry: {category_id, category_name, category_path, score}.
    Cached for 30 days per (marketplace, title hash) in `category_suggestions_cache`.
    """
    if not query or not query.strip():
        return []
    tree_id = _category_tree_id(marketplace_id)
    qhash = _title_hash(query)

    # Cache hit?
    with db() as conn:
        cached = conn.execute(
            "SELECT category_id, category_name, category_path, fetched_at "
            "FROM category_suggestions_cache "
            "WHERE marketplace_id = ? AND title_hash = ?",
            (marketplace_id, qhash),
        ).fetchone()
    if cached:
        try:
            age_days = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(cached["fetched_at"])
            ).days
        except (TypeError, ValueError):
            age_days = 999
        if age_days < 30:
            return [{
                "category_id": cached["category_id"],
                "category_name": cached["category_name"],
                "category_path": cached["category_path"],
                "cached": True,
            }]

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{EBAY_API_BASE}/commerce/taxonomy/v1/category_tree/{tree_id}/get_category_suggestions",
            headers=headers, params={"q": query[:80]},
        )
    if r.status_code != 200:
        raise HTTPException(502, f"eBay category-suggestions failed: {r.text[:300]}")

    suggestions = (r.json() or {}).get("categorySuggestions") or []
    out = []
    for s in suggestions[:10]:
        cat = s.get("category") or {}
        ancestors = s.get("categoryTreeNodeAncestors") or []
        # Build a human path "Home > Furniture > Chairs"
        path_parts = [a.get("categoryName") for a in reversed(ancestors)]
        path_parts.append(cat.get("categoryName") or "")
        out.append({
            "category_id": cat.get("categoryId"),
            "category_name": cat.get("categoryName"),
            "category_path": " > ".join([p for p in path_parts if p]),
            "score": s.get("relevancy"),
        })

    if out:
        top = out[0]
        now_iso = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            conn.execute(
                """INSERT INTO category_suggestions_cache
                     (marketplace_id, title_hash, category_id, category_name, category_path, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(marketplace_id, title_hash) DO UPDATE SET
                     category_id   = excluded.category_id,
                     category_name = excluded.category_name,
                     category_path = excluded.category_path,
                     fetched_at    = excluded.fetched_at""",
                (marketplace_id, qhash, top["category_id"],
                 top["category_name"], top["category_path"], now_iso),
            )
    return out


async def get_item_aspects_for_category(
    *, token: str, marketplace_id: str, category_id: str,
) -> list[dict[str, Any]]:
    """Return the aspect schema for a category.

    Each entry: {name, required, mode (FREE_TEXT|SELECTION_ONLY), cardinality
    (SINGLE|MULTI), values: [...], aspect_data_type}. Cached for 30 days per
    (marketplace, category) in `category_aspects_cache`.
    """
    if not category_id:
        return []
    tree_id = _category_tree_id(marketplace_id)

    with db() as conn:
        cached = conn.execute(
            "SELECT aspects_json, fetched_at FROM category_aspects_cache "
            "WHERE marketplace_id = ? AND category_id = ?",
            (marketplace_id, category_id),
        ).fetchone()
    if cached:
        try:
            age_days = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(cached["fetched_at"])
            ).days
        except (TypeError, ValueError):
            age_days = 999
        if age_days < 30:
            try:
                return json.loads(cached["aspects_json"]) or []
            except (TypeError, ValueError):
                pass

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{EBAY_API_BASE}/commerce/taxonomy/v1/category_tree/{tree_id}/get_item_aspects_for_category",
            headers=headers, params={"category_id": category_id},
        )
    if r.status_code != 200:
        raise HTTPException(502, f"eBay aspects fetch failed: {r.text[:300]}")

    aspects = (r.json() or {}).get("aspects") or []
    out = []
    for a in aspects:
        cons = a.get("aspectConstraint") or {}
        vals = a.get("aspectValues") or []
        out.append({
            "name": a.get("localizedAspectName"),
            "required": bool(cons.get("aspectRequired")),
            "mode": cons.get("aspectMode") or "FREE_TEXT",
            "cardinality": cons.get("itemToAspectCardinality") or "SINGLE",
            "aspect_data_type": cons.get("aspectDataType") or "STRING",
            "values": [v.get("localizedValue") for v in vals if v.get("localizedValue")],
        })

    now_iso = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """INSERT INTO category_aspects_cache
                 (marketplace_id, category_id, aspects_json, fetched_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(marketplace_id, category_id) DO UPDATE SET
                 aspects_json = excluded.aspects_json,
                 fetched_at   = excluded.fetched_at""",
            (marketplace_id, category_id, json.dumps(out), now_iso),
        )
    return out


def _autofill_aspects(
    *, product: dict[str, Any], schema: list[dict[str, Any]],
) -> tuple[dict[str, list[str]], list[str]]:
    """Auto-fill aspects from product data using the rules below.

    Returns (aspects, missing_required) where `aspects` maps name → list of
    string values (eBay's required shape) and `missing_required` is the list
    of required aspect names we couldn't fill.

    Rules per aspect (case-insensitive name match):
      - Brand / Marca / Marque  → product.brand
      - MPN / Model             → product.asin
      - Type / Subtype          → 'Generic' fallback
      - Anything else           → search title + description + spec_table values
    """
    title = (product.get("title") or "").strip()
    brand = (product.get("brand") or "").strip()
    asin  = (product.get("asin") or "").strip()
    desc  = (product.get("description") or "").strip()
    spec  = product.get("spec_table") or {}
    user_overrides = product.get("ebay_aspects") or {}

    # Normalise spec_table keys for searching
    spec_lower = {(k or "").strip().lower(): str(v) for k, v in spec.items()} if isinstance(spec, dict) else {}

    # Cheap haystack for FREE_TEXT searches
    haystack = f"{title}\n{desc}\n{' '.join(spec_lower.values())}".lower()

    aspects: dict[str, list[str]] = {}
    missing: list[str] = []

    BRAND_NAMES = {"brand", "marca", "marque", "marke"}
    MPN_NAMES   = {"mpn", "manufacturer part number", "model"}
    TYPE_NAMES  = {"type", "subtype", "style"}

    for a in schema:
        name = (a.get("name") or "").strip()
        if not name:
            continue
        # User override always wins
        override = user_overrides.get(name)
        if override is not None and str(override).strip():
            val = override if isinstance(override, list) else [str(override)]
            aspects[name] = [str(v) for v in val if str(v).strip()]
            continue

        lower = name.lower()
        value: Optional[str] = None

        if lower in BRAND_NAMES and brand:
            value = brand
        elif lower in MPN_NAMES and asin:
            value = asin
        elif lower in TYPE_NAMES:
            value = "Generic"

        # Try the spec table by case-insensitive key match
        if value is None and lower in spec_lower:
            v = spec_lower[lower].strip()
            if v:
                value = v[:80]

        # For SELECTION_ONLY aspects, try to find one of the listed values in the haystack
        if value is None and a.get("mode") == "SELECTION_ONLY":
            for opt in (a.get("values") or []):
                if opt and opt.lower() in haystack:
                    value = opt
                    break

        if value:
            aspects[name] = [value]
        elif a.get("required"):
            missing.append(name)

    return aspects, missing


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


async def get_valid_token(account_id: Optional[int] = None) -> str:
    """Return a valid access token for the given (or active) account."""
    aid = account_id if account_id is not None else get_active_account_id()
    if aid is None:
        raise HTTPException(401, "No eBay account connected. Go to Settings → Connect eBay.")
    with db() as conn:
        row = _token_row(conn, aid)
        if not row or not row["access_token"]:
            raise HTTPException(401, "eBay not connected for the active account. Go to Settings → Connect eBay.")
        now = int(time.time())
        if now < row["expires_at"] - 60:
            return row["access_token"]
        # Refresh
        if not row["refresh_token"]:
            raise HTTPException(401, "eBay token expired and no refresh token. Please reconnect.")
        data = await _refresh_access_token(row["refresh_token"])
        with db() as conn2:
            _save_tokens(conn2, data, aid)
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
    # Optional Amazon spec table scraped by the extension. Key-value strings,
    # used by the backend at publish time to auto-fill eBay item specifics.
    spec_table: Optional[dict[str, str]] = None
    source_marketplace: str = ""
    saved_at: Optional[str] = None


class ListEbayIn(BaseModel):
    price: Optional[float] = None          # override listing price (defaults to Amazon price + 30%)
    quantity: int = 1
    title: Optional[str] = None            # override the eBay listing title (≤80 chars)
    category_id: Optional[str] = None      # If None, auto-detect via Taxonomy API (or use stored override)
    marketplace_id: Optional[str] = None   # If None, infer from product.preferred_marketplace_id → source → EBAY_US
    fulfillment_policy_id: Optional[str] = None
    payment_policy_id: Optional[str] = None
    return_policy_id: Optional[str] = None
    override_vero: bool = False            # bypass VeRO blocklist (use carefully)
    override_aspects: bool = False         # publish even if required item-specifics are missing


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


def _ensure_pending_account(label: str) -> int:
    """Create or reuse a pending (no-tokens-yet) account row, return its id."""
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        # Reuse an existing token-less account with the same label, if any
        existing = conn.execute(
            """SELECT a.id FROM ebay_accounts a
               LEFT JOIN ebay_tokens t ON t.account_id = a.id
               WHERE a.label = ? AND t.access_token IS NULL""",
            (label,),
        ).fetchone()
        if existing:
            return existing["id"]
        cur = conn.execute(
            """INSERT INTO ebay_accounts (label, sandbox, is_active, created_at)
               VALUES (?, ?, 0, ?)""",
            (label, 1 if EBAY_SANDBOX else 0, now),
        )
        return cur.lastrowid


@app.get("/auth/ebay")
def ebay_auth_start(account_id: Optional[int] = None, label: Optional[str] = None):
    """Redirect the browser to eBay's OAuth consent screen.

    If `account_id` is given, the resulting tokens are bound to that account
    (used for re-connect). Otherwise a new pending account is created with
    the supplied `label` (or "Store N" if no label).
    """
    if not EBAY_CLIENT_ID or not EBAY_RU_NAME:
        raise HTTPException(500, "EBAY_CLIENT_ID and EBAY_RU_NAME env vars must be set.")

    if account_id is None:
        with db() as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM ebay_accounts").fetchone()["c"]
        chosen_label = (label or f"Store {count + 1}").strip() or f"Store {count + 1}"
        account_id = _ensure_pending_account(chosen_label)

    state = secrets.token_urlsafe(16)
    _oauth_states[state] = (time.time(), account_id)
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
    if state not in _oauth_states:
        raise HTTPException(400, "Invalid OAuth state. Try connecting again.")
    state_value = _oauth_states.pop(state)
    if isinstance(state_value, tuple):
        ts, account_id = state_value
    else:
        ts, account_id = state_value, None
    if time.time() - ts > 300:
        raise HTTPException(400, "OAuth state expired. Try connecting again.")
    if not account_id:
        raise HTTPException(400, "OAuth state missing account binding. Try connecting again.")

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
        _save_tokens(conn, r.json(), account_id)
        # If no other account is currently active, promote this one
        active = conn.execute(
            "SELECT id FROM ebay_accounts WHERE is_active = 1"
        ).fetchone()
        if not active:
            conn.execute("UPDATE ebay_accounts SET is_active = 1 WHERE id = ?", (account_id,))

    return RedirectResponse(f"{FRONTEND_URL}/settings?ebay=connected")


@app.get("/auth/ebay/status")
def ebay_status():
    """Return connection status for the currently-active account."""
    aid = get_active_account_id()
    if aid is None:
        return {"connected": False}
    with db() as conn:
        row = _token_row(conn, aid)
    if not row or not row["access_token"]:
        return {"connected": False, "active_account_id": aid}
    now = int(time.time())
    return {
        "connected": True,
        "active_account_id": aid,
        "token_valid": now < row["expires_at"],
        "token_expires_at": row["expires_at"],
        "refresh_valid": now < row["refresh_expires_at"],
        "connected_at": row["connected_at"],
        "scope": row["scope"],
        "sandbox": EBAY_SANDBOX,
    }


@app.delete("/auth/ebay")
def ebay_disconnect_active():
    """Remove tokens for the currently-active account (legacy single-account API)."""
    aid = get_active_account_id()
    if aid is None:
        return {"ok": True, "message": "Nothing connected."}
    with db() as conn:
        conn.execute("DELETE FROM ebay_tokens WHERE account_id = ?", (aid,))
    return {"ok": True, "message": "eBay disconnected."}


# ---------- Multi-account API ----------
@app.get("/api/ebay/accounts")
def api_list_accounts():
    return list_accounts_with_status()


class AccountIn(BaseModel):
    label: str


@app.put("/api/ebay/accounts/{account_id}")
def api_update_account(account_id: int, payload: AccountIn):
    with db() as conn:
        if not conn.execute(
            "SELECT 1 FROM ebay_accounts WHERE id = ?", (account_id,)
        ).fetchone():
            raise HTTPException(404, "account not found")
        conn.execute(
            "UPDATE ebay_accounts SET label = ? WHERE id = ?",
            (payload.label.strip() or "Untitled store", account_id),
        )
    return {"ok": True}


@app.post("/api/ebay/accounts/{account_id}/activate")
def api_activate_account(account_id: int):
    with db() as conn:
        if not conn.execute(
            "SELECT 1 FROM ebay_accounts WHERE id = ?", (account_id,)
        ).fetchone():
            raise HTTPException(404, "account not found")
    set_active_account_id(account_id)
    return {"ok": True, "active_account_id": account_id}


@app.delete("/api/ebay/accounts/{account_id}")
def api_delete_account(account_id: int):
    with db() as conn:
        was_active = conn.execute(
            "SELECT is_active FROM ebay_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if not was_active:
            raise HTTPException(404, "account not found")
        conn.execute("DELETE FROM ebay_tokens WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM ebay_accounts WHERE id = ?", (account_id,))
        # If we deleted the active one, promote the lowest remaining account
        if was_active["is_active"]:
            r = conn.execute(
                "SELECT id FROM ebay_accounts ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if r:
                conn.execute(
                    "UPDATE ebay_accounts SET is_active = 1 WHERE id = ?", (r["id"],)
                )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Routes — eBay listing
# ---------------------------------------------------------------------------
class ListEbayBulkIn(BaseModel):
    asins: list[str]
    price: Optional[float] = None
    quantity: int = 1
    titles: Optional[dict[str, str]] = None  # asin -> custom title
    category_id: Optional[str] = None        # If None, each product auto-detects (or uses its stored override)
    marketplace_id: Optional[str] = None     # If None, each product uses its preferred_marketplace_id or source-derived default
    override_vero: bool = False
    override_aspects: bool = False


@app.post("/api/products/list-ebay-bulk")
async def list_on_ebay_bulk(body: ListEbayBulkIn):
    """Publish many products in sequence. Returns a per-asin result."""
    if not body.asins:
        raise HTTPException(400, "asins required")
    results = []
    for asin in body.asins:
        try:
            r = await list_on_ebay(asin, ListEbayIn(
                price=body.price,
                quantity=body.quantity,
                title=(body.titles or {}).get(asin),
                category_id=body.category_id,
                marketplace_id=body.marketplace_id,
                override_vero=body.override_vero,
                override_aspects=body.override_aspects,
            ))
            results.append({"asin": asin, "ok": True, **r})
        except HTTPException as e:
            results.append({"asin": asin, "ok": False, "status": e.status_code, "detail": e.detail})
        except Exception as e:
            results.append({"asin": asin, "ok": False, "status": 500, "detail": str(e)[:200]})
    success = sum(1 for r in results if r["ok"])
    return {"total": len(results), "success": success, "failed": len(results) - success, "results": results}


@app.post("/api/products/{asin}/list-ebay")
async def list_on_ebay(asin: str, body: ListEbayIn = ListEbayIn()):
    """Publish a saved product to eBay via the Inventory API (3-step flow)."""
    with db() as conn:
        row = conn.execute("SELECT * FROM products WHERE asin = ?", (asin,)).fetchone()
    if not row:
        raise HTTPException(404, "Product not found.")

    product = row_to_product(row)

    # VeRO check — refuse to publish products matching a "block" entry unless
    # the caller explicitly opts to override.
    if not body.override_vero:
        vero_matches = check_vero_for_text(product.get("title", ""), product.get("brand", ""))
        blocking = [m for m in vero_matches if m["level"] == "block"]
        if blocking:
            kws = ", ".join(m["keyword"] for m in blocking)
            raise HTTPException(
                422,
                {
                    "error": "vero_blocked",
                    "message": f"Blocked by VeRO watchlist: {kws}",
                    "matches": vero_matches,
                },
            )

    # --- Resolve target marketplace ---
    # Precedence: explicit body.marketplace_id > product.preferred_marketplace_id
    # > Amazon-host inference (e.g. amazon.de → EBAY_DE) > EBAY_US.
    marketplace_id = body.marketplace_id or _default_marketplace_for_product(product)

    token = await get_valid_token()
    content_language = _content_language(marketplace_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept-Language": content_language,
        "Content-Language": content_language,
        "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
    }

    listing_price = body.price
    if listing_price is None and product.get("price"):
        # Use the tiered margin ladder (Phase 2.6) when configured.
        markup_pct = markup_for_amazon_price(float(product["price"]))
        listing_price = round(float(product["price"]) * (1 + markup_pct / 100), 2)
    if not listing_price:
        raise HTTPException(400, "No price available. Pass 'price' in the request body.")

    sku = f"DROPLY-{asin}"
    merchant_location_key, merchant_location_addr = _merchant_location_for(marketplace_id)
    title = (body.title or product.get("title") or asin)[:80]
    # Render the configured description template (falls back to raw bullets
    # when no template is set or the slug doesn't resolve).
    description = render_description_for_product(product) or product.get("description") or title
    images = product.get("images") or []

    # --- Resolve eBay category (Taxonomy API) ---
    # Precedence: explicit body.category_id > stored override on the product
    # > auto-detect from title. Result is persisted onto the product row so
    # subsequent publishes / UI lookups don't re-call the API.
    category_id = body.category_id or product.get("ebay_category_id")
    category_name = product.get("ebay_category_name")
    if not category_id:
        suggestions = await get_category_suggestions(
            token=token, marketplace_id=marketplace_id, query=title,
        )
        if not suggestions:
            raise HTTPException(
                422,
                {"error": "no_category_suggestion",
                 "message": "eBay returned no category suggestions for this title. Set a category manually."},
            )
        category_id = suggestions[0]["category_id"]
        category_name = suggestions[0].get("category_name")
        with db() as conn:
            conn.execute(
                "UPDATE products SET ebay_category_id = ?, ebay_category_name = ? WHERE asin = ?",
                (category_id, category_name, asin),
            )

    # --- Build item specifics (aspects) from product data + the category schema ---
    aspect_schema = await get_item_aspects_for_category(
        token=token, marketplace_id=marketplace_id, category_id=category_id,
    )
    auto_aspects, missing_required = _autofill_aspects(product=product, schema=aspect_schema)

    if missing_required and not body.override_aspects:
        # Flag the product so the UI can surface a "needs attention" badge.
        with db() as conn:
            conn.execute(
                "UPDATE products SET aspects_needs_attention = 1 WHERE asin = ?",
                (asin,),
            )
        raise HTTPException(
            422,
            {"error": "aspects_missing",
             "message": "Required item specifics are missing for this category.",
             "missing": missing_required,
             "category_id": category_id,
             "category_name": category_name},
        )

    # Clear the needs-attention flag once we have everything.
    with db() as conn:
        conn.execute(
            "UPDATE products SET aspects_needs_attention = 0 WHERE asin = ?",
            (asin,),
        )

    # Step 0 — ensure a merchant location exists (eBay needs the location's
    # country to match the marketplace, e.g. EBAY_GB needs a GB address).
    async with httpx.AsyncClient() as client:
        r_loc_check = await client.get(
            f"{EBAY_API_BASE}/sell/inventory/v1/location/{merchant_location_key}",
            headers=headers,
        )
        if r_loc_check.status_code == 404:
            location_payload = {
                "location": {"address": merchant_location_addr},
                "name": f"Droply Default Location ({marketplace_id})",
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
    # Ensure Brand / MPN are always present even if the category schema didn't
    # list them — eBay requires both at the product level for most categories.
    final_aspects: dict[str, list[str]] = {"Brand": [brand], "MPN": [mpn]}
    final_aspects.update(auto_aspects)
    item_payload: dict[str, Any] = {
        "product": {
            "title": title,
            "description": description,
            "imageUrls": images[:12],
            "brand": brand,
            "mpn": mpn,
            "aspects": final_aspects,
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
        "marketplaceId": marketplace_id,
        "format": "FIXED_PRICE",
        "listingDescription": description[:500],
        "categoryId": category_id,
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
        policies = await ensure_business_policies(headers, marketplace_id)
    offer_payload["listingPolicies"] = policies

    async with httpx.AsyncClient() as client:
        # Check if an offer already exists for this SKU
        r_check = await client.get(
            f"{EBAY_API_BASE}/sell/inventory/v1/offer",
            headers=headers,
            params={"sku": sku, "marketplace_id": marketplace_id},
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
        marketplace_id=marketplace_id,
        sku=sku,
        offer_id=offer_id,
        listing_id=listing_id,
        listing_url=ebay_url,
        price=listing_price,
        currency=(product.get("currency") or "USD"),
        markup_percent=markup_pct,
        quantity=body.quantity,
    )

    # Persist the aspects we actually published so the UI reflects ground truth.
    with db() as conn:
        conn.execute(
            "UPDATE products SET ebay_aspects = ? WHERE asin = ?",
            (json.dumps(final_aspects), asin),
        )

    return {
        "ok": True,
        "sku": sku,
        "offer_id": offer_id,
        "listing_id": listing_id,
        "listing_url": ebay_url,
        "listing_price": listing_price,
        "category_id": category_id,
        "category_name": category_name,
        "aspects": final_aspects,
        "marketplace_id": marketplace_id,
    }


# ---------------------------------------------------------------------------
# Routes — eBay category detection (Phase 2.1)
# ---------------------------------------------------------------------------

class CategoryOverrideIn(BaseModel):
    category_id: str
    category_name: Optional[str] = None
    marketplace_id: str = "EBAY_US"


class AspectsOverrideIn(BaseModel):
    aspects: dict[str, list[str]]


class MarketplaceOverrideIn(BaseModel):
    marketplace_id: Optional[str]  # null clears the override → re-infer from source


@app.post("/api/products/{asin}/suggest-category")
async def api_suggest_category(asin: str, marketplace_id: str = "EBAY_US"):
    """Run eBay's category detection for a product. Caches + persists the top hit."""
    with db() as conn:
        row = conn.execute("SELECT title FROM products WHERE asin = ?", (asin,)).fetchone()
    if not row:
        raise HTTPException(404, "Product not found")
    title = row["title"] or ""
    token = await get_valid_token()
    suggestions = await get_category_suggestions(
        token=token, marketplace_id=marketplace_id, query=title,
    )
    if not suggestions:
        return {"ok": False, "suggestions": [], "message": "No category suggestions"}
    top = suggestions[0]
    with db() as conn:
        conn.execute(
            "UPDATE products SET ebay_category_id = ?, ebay_category_name = ? WHERE asin = ?",
            (top["category_id"], top.get("category_name"), asin),
        )
    return {"ok": True, "suggestions": suggestions, "selected": top}


@app.put("/api/products/{asin}/category")
def api_set_category(asin: str, payload: CategoryOverrideIn):
    """Manually pin a product to a specific eBay category."""
    with db() as conn:
        existing = conn.execute("SELECT 1 FROM products WHERE asin = ?", (asin,)).fetchone()
        if not existing:
            raise HTTPException(404, "Product not found")
        conn.execute(
            "UPDATE products SET ebay_category_id = ?, ebay_category_name = ? WHERE asin = ?",
            (payload.category_id, payload.category_name, asin),
        )
    return {"ok": True}


@app.get("/api/marketplaces")
def api_list_marketplaces():
    """List the eBay marketplaces Droply knows how to publish to.

    The dropdown on the Products page reads this. Each entry includes the
    default merchant-location country so the UI can warn users their address
    is a placeholder.
    """
    out = []
    for mp in EBAY_CATEGORY_TREE_IDS.keys():
        addr = EBAY_MARKETPLACE_LOCATION.get(mp) or {}
        out.append({
            "marketplace_id": mp,
            "language": EBAY_MARKETPLACE_LANG.get(mp, "en-US"),
            "country": addr.get("country"),
            "default_city": addr.get("city"),
        })
    return out


@app.put("/api/products/{asin}/marketplace")
def api_set_marketplace(asin: str, payload: MarketplaceOverrideIn):
    """Pin a product to a specific eBay marketplace. Pass null to clear."""
    mp = (payload.marketplace_id or "").strip() or None
    if mp and mp not in EBAY_CATEGORY_TREE_IDS:
        raise HTTPException(400, f"Unknown marketplace_id '{mp}'")
    with db() as conn:
        existing = conn.execute("SELECT 1 FROM products WHERE asin = ?", (asin,)).fetchone()
        if not existing:
            raise HTTPException(404, "Product not found")
        conn.execute(
            "UPDATE products SET preferred_marketplace_id = ? WHERE asin = ?",
            (mp, asin),
        )
    return {"ok": True, "marketplace_id": mp}


@app.put("/api/products/{asin}/aspects")
def api_set_aspects(asin: str, payload: AspectsOverrideIn):
    """Manually set item-specifics for a product (overrides auto-fill).

    Clears the `aspects_needs_attention` flag in case the user filled the gaps.
    """
    with db() as conn:
        existing = conn.execute("SELECT 1 FROM products WHERE asin = ?", (asin,)).fetchone()
        if not existing:
            raise HTTPException(404, "Product not found")
        conn.execute(
            """UPDATE products
                  SET ebay_aspects = ?,
                      aspects_needs_attention = 0
                WHERE asin = ?""",
            (json.dumps(payload.aspects), asin),
        )
    return {"ok": True, "aspects": payload.aspects}


@app.get("/api/products/{asin}/aspect-schema")
async def api_aspect_schema(asin: str, marketplace_id: str = "EBAY_US"):
    """Return the aspect schema + auto-filled values for a product.

    Drives the "Edit category & aspects" modal. If the product has no category
    set, runs detection first.
    """
    with db() as conn:
        row = conn.execute("SELECT * FROM products WHERE asin = ?", (asin,)).fetchone()
    if not row:
        raise HTTPException(404, "Product not found")
    product = row_to_product(row)

    token = await get_valid_token()
    category_id = product.get("ebay_category_id")
    category_name = product.get("ebay_category_name")
    if not category_id:
        suggestions = await get_category_suggestions(
            token=token, marketplace_id=marketplace_id, query=product.get("title", ""),
        )
        if suggestions:
            top = suggestions[0]
            category_id = top["category_id"]
            category_name = top.get("category_name")
            with db() as conn:
                conn.execute(
                    "UPDATE products SET ebay_category_id = ?, ebay_category_name = ? WHERE asin = ?",
                    (category_id, category_name, asin),
                )

    if not category_id:
        return {"category_id": None, "schema": [], "auto": {}, "missing": []}

    schema = await get_item_aspects_for_category(
        token=token, marketplace_id=marketplace_id, category_id=category_id,
    )
    auto, missing = _autofill_aspects(product=product, schema=schema)
    return {
        "category_id": category_id,
        "category_name": category_name,
        "schema": schema,
        "auto": auto,
        "missing": missing,
        "user_overrides": product.get("ebay_aspects") or {},
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

    spec_json = json.dumps(p.spec_table) if p.spec_table else None
    conn.execute(
        """
        INSERT INTO products (asin, title, brand, price, currency, images, description,
                              stock_status, amazon_url, source_marketplace, saved_at,
                              spec_table)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
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
            saved_at=excluded.saved_at,
            spec_table=COALESCE(excluded.spec_table, products.spec_table)
        """,
        (
            p.asin, p.title, p.brand, p.price, p.currency,
            json.dumps(p.images), p.description, p.stock_status,
            p.amazon_url, p.source_marketplace, saved_at, spec_json,
        ),
    )
    row = conn.execute("SELECT * FROM products WHERE asin = ?", (p.asin,)).fetchone()
    return row_to_product(row)


@app.post("/api/products")
def save_product(payload: ProductIn, background: BackgroundTasks):
    with db() as conn:
        prev = conn.execute(
            "SELECT price, stock_status FROM products WHERE asin = ?", (payload.asin,)
        ).fetchone()
        prev_price = prev["price"] if prev else None
        prev_stock = prev["stock_status"] if prev else None
        product = _upsert(conn, payload)
    if payload.price is not None and prev_price != payload.price:
        background.add_task(maybe_auto_reprice, payload.asin, payload.price)
    if payload.stock_status and payload.stock_status != prev_stock:
        background.add_task(maybe_sync_inventory, payload.asin, payload.stock_status)
    return {"ok": True, "product": product}


@app.post("/api/products/bulk")
def save_products_bulk(payload: list[ProductIn], background: BackgroundTasks):
    out = []
    with db() as conn:
        for p in payload:
            prev = conn.execute(
                "SELECT price, stock_status FROM products WHERE asin = ?", (p.asin,)
            ).fetchone()
            prev_price = prev["price"] if prev else None
            prev_stock = prev["stock_status"] if prev else None
            out.append(_upsert(conn, p))
            if p.price is not None and prev_price != p.price:
                background.add_task(maybe_auto_reprice, p.asin, p.price)
            if p.stock_status and p.stock_status != prev_stock:
                background.add_task(maybe_sync_inventory, p.asin, p.stock_status)
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
        # EasyPost — never return the raw key; only indicate whether it's set
        "easypost_api_key_set": bool(s.get("easypost_api_key", "").strip()),
        "easypost_cache_ttl_minutes": float(s.get("easypost_cache_ttl_minutes", "60")),
        # In-process job scheduler
        "scheduler_enabled": s.get("scheduler_enabled", "true").lower() == "true",
        # Phase 2.3: which description template to render at publish time.
        # Empty string = skip the template and use the raw Amazon description.
        "default_description_template_slug": s.get("default_description_template_slug", "default"),
        # Phase 2.6: tiered margin ladder. Empty/invalid JSON ⇒ flat
        # `markup_percent` is used.
        "margin_rules": _parse_margin_rules(s.get("margin_rules", "")),
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
    easypost_api_key: Optional[str] = None
    easypost_cache_ttl_minutes: Optional[float] = None
    scheduler_enabled: Optional[bool] = None
    default_description_template_slug: Optional[str] = None
    margin_rules: Optional[list[dict[str, Any]]] = None


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
    if payload.easypost_api_key is not None:
        # Empty string = leave unchanged; "__CLEAR__" sentinel = wipe it
        if payload.easypost_api_key == "":
            pass
        elif payload.easypost_api_key == "__CLEAR__":
            set_setting("easypost_api_key", "")
        else:
            set_setting("easypost_api_key", payload.easypost_api_key.strip())
    if payload.easypost_cache_ttl_minutes is not None:
        set_setting("easypost_cache_ttl_minutes", str(payload.easypost_cache_ttl_minutes))
    if payload.scheduler_enabled is not None:
        set_setting("scheduler_enabled", "true" if payload.scheduler_enabled else "false")
    if payload.default_description_template_slug is not None:
        set_setting("default_description_template_slug", payload.default_description_template_slug)
    if payload.margin_rules is not None:
        # Empty list clears the ladder (fall back to flat markup_percent).
        cleaned: list[dict[str, Any]] = []
        for r in payload.margin_rules:
            if not isinstance(r, dict):
                continue
            try:
                markup = float(r.get("markup_percent"))
            except (TypeError, ValueError):
                continue
            max_p = r.get("max_price")
            if max_p is not None:
                try:
                    max_p = float(max_p)
                except (TypeError, ValueError):
                    continue
            cleaned.append({"max_price": max_p, "markup_percent": markup})
        set_setting("margin_rules", json.dumps(cleaned))
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


def _render_template_text(text: str, vars: dict[str, str]) -> str:
    for k, v in vars.items():
        text = text.replace("{" + k + "}", str(v or ""))
    return text


def render_description_for_product(product: dict[str, Any]) -> str:
    """Render the configured default description template for a product.

    Variables: {title} {brand} {asin} {description} {price} {currency} +
    any key from product.spec_table (e.g. {Color}, {Connectivity}). When no
    template is configured (empty slug) or the slug doesn't exist, falls
    back to the raw product description.
    """
    cfg = get_settings_dict()
    slug = (cfg.get("default_description_template_slug") or "").strip()
    raw = product.get("description") or product.get("title") or ""
    if not slug:
        return raw
    with db() as conn:
        tpl = conn.execute(
            "SELECT body FROM description_templates WHERE slug = ?", (slug,)
        ).fetchone()
    if not tpl:
        return raw
    spec = product.get("spec_table") or {}
    vars: dict[str, str] = {
        "title":       str(product.get("title") or ""),
        "brand":       str(product.get("brand") or ""),
        "asin":        str(product.get("asin") or ""),
        "description": str(raw),
        "price":       str(product.get("price") or ""),
        "currency":    str(product.get("currency") or ""),
    }
    if isinstance(spec, dict):
        for k, v in spec.items():
            if k and isinstance(k, str):
                vars[k] = str(v or "")
    return _render_template_text(tpl["body"], vars)


def _order_to_template_vars(order: sqlite3.Row) -> dict[str, str]:
    """Map an `orders` row to the variables our default templates expect."""
    item_title = order["sku"] or order["product_asin"] or "your order"
    if order["product_asin"]:
        with db() as conn:
            p = conn.execute(
                "SELECT title FROM products WHERE asin = ?", (order["product_asin"],)
            ).fetchone()
        if p and p["title"]:
            item_title = p["title"]
    return {
        "buyer_name": (order["ship_to_name"] or order["buyer_username"] or "there"),
        "item_title": item_title,
        "order_id": order["ebay_order_id"] or "",
        "tracking_number": order["tracking_number"] or "",
        "carrier": order["tracking_carrier"] or "",
        "est_delivery_date": "",   # not yet captured from eBay
        "seller_name": "Droply",
    }


# ---------------------------------------------------------------------------
# Tracking-status checker
#
# Uses EasyPost as the multi-carrier aggregator (USPS / UPS / FedEx / DHL /
# 100+ others). API key is stored in app_settings.easypost_api_key.
#
# Status mapping: EasyPost returns one of
#   pre_transit | in_transit | out_for_delivery | delivered |
#   available_for_pickup | return_to_sender | failure | cancelled | error | unknown
# We normalise into our canonical set: in_transit | out_for_delivery |
#   delivered | exception | returned | unknown
# ---------------------------------------------------------------------------
CARRIER_TRACKING_URLS = {
    "USPS": "https://tools.usps.com/go/TrackConfirmAction?qtc_tLabels1={}",
    "UPS":  "https://www.ups.com/track?tracknum={}",
    "FEDEX": "https://www.fedex.com/fedextrack/?tracknumbers={}",
    "DHL":  "https://www.dhl.com/global-en/home/tracking/tracking-parcel.html?submit=1&tracking-id={}",
}

# EasyPost expects the carrier as one of its canonical slugs.
EASYPOST_CARRIER_MAP = {
    "USPS": "USPS",
    "UPS": "UPS",
    "FEDEX": "FedEx",
    "DHL": "DHLExpress",
    "DHLE": "DHLExpress",
    "DHLEXPRESS": "DHLExpress",
    "DHLECOMMERCE": "DHLeCommerce",
}

EASYPOST_STATUS_MAP = {
    "pre_transit":           "in_transit",
    "in_transit":            "in_transit",
    "out_for_delivery":      "out_for_delivery",
    "delivered":             "delivered",
    "available_for_pickup":  "out_for_delivery",
    "return_to_sender":      "returned",
    "failure":               "exception",
    "cancelled":             "exception",
    "error":                 "exception",
    "unknown":               "unknown",
}


def carrier_tracking_url(carrier: Optional[str], number: Optional[str]) -> Optional[str]:
    if not carrier or not number:
        return None
    template = CARRIER_TRACKING_URLS.get(carrier.upper())
    return template.format(number) if template else None


def _normalize_easypost_carrier(carrier: str) -> str:
    return EASYPOST_CARRIER_MAP.get((carrier or "").upper().replace(" ", ""), carrier)


async def _lookup_status_remote(carrier: str, number: str) -> tuple[str, str]:
    """Fetch tracking status from EasyPost, with a per-(carrier, number) cache.

    Returns (status, status_text). Statuses: in_transit | out_for_delivery |
    delivered | exception | returned | unknown.
    """
    cfg = get_settings_dict()
    api_key = (cfg.get("easypost_api_key") or "").strip()
    if not api_key:
        return ("unknown", "Tracking API not configured (set EasyPost API key in settings).")
    if not carrier or not number:
        return ("unknown", "Missing carrier or tracking number.")

    try:
        ttl_min = float(cfg.get("easypost_cache_ttl_minutes", "60") or 60)
    except (TypeError, ValueError):
        ttl_min = 60.0
    cache_key = (carrier.upper(), number.strip())

    # Cache hit — return early if fresh
    with db() as conn:
        cached = conn.execute(
            "SELECT status, status_text, checked_at FROM tracking_cache "
            "WHERE carrier = ? AND tracking_number = ?",
            (cache_key[0], cache_key[1]),
        ).fetchone()
    if cached:
        try:
            checked = datetime.fromisoformat(cached["checked_at"])
            age = (datetime.now(timezone.utc) - checked).total_seconds() / 60.0
            if age < ttl_min:
                return (cached["status"], cached["status_text"] or "")
        except (TypeError, ValueError):
            pass

    ep_carrier = _normalize_easypost_carrier(carrier)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://api.easypost.com/v2/trackers",
                auth=(api_key, ""),
                json={"tracker": {"tracking_code": number.strip(), "carrier": ep_carrier}},
            )
    except httpx.HTTPError as e:
        return ("unknown", f"EasyPost request failed: {e}")

    if r.status_code >= 400:
        # EasyPost returns 422 for already-tracked codes — retry as GET on the
        # existing tracker by tracking_code.
        try:
            err = r.json().get("error", {}).get("message", r.text)
        except (ValueError, AttributeError):
            err = r.text
        return ("unknown", f"EasyPost {r.status_code}: {err}"[:300])

    data = r.json()
    ep_status = (data.get("status") or "unknown").lower()
    status = EASYPOST_STATUS_MAP.get(ep_status, "unknown")
    details = data.get("tracking_details") or []
    detail_msg = ""
    if details:
        last = details[-1]
        detail_msg = (last.get("message") or last.get("status_detail") or "")[:200]
    status_text = detail_msg or ep_status.replace("_", " ").title()

    now_iso = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """INSERT INTO tracking_cache
                 (carrier, tracking_number, easypost_tracker_id, status, status_text, checked_at, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(carrier, tracking_number) DO UPDATE SET
                 easypost_tracker_id = excluded.easypost_tracker_id,
                 status = excluded.status,
                 status_text = excluded.status_text,
                 checked_at = excluded.checked_at,
                 raw_json = excluded.raw_json""",
            (
                cache_key[0],
                cache_key[1],
                data.get("id"),
                status,
                status_text,
                now_iso,
                json.dumps(data)[:50000],
            ),
        )
    return (status, status_text)


async def refresh_tracking_for_order(order_id: str) -> dict[str, Any]:
    """Fetch latest tracking status, persist it, fire the delivered template."""
    with db() as conn:
        order = conn.execute(
            "SELECT * FROM orders WHERE ebay_order_id = ?", (order_id,)
        ).fetchone()
    if not order:
        raise HTTPException(404, "order not found")
    if not order["tracking_number"]:
        raise HTTPException(400, "order has no tracking number yet")

    carrier = order["tracking_carrier"] or ""
    number = order["tracking_number"]
    new_status, status_text = await _lookup_status_remote(carrier, number)
    now = datetime.now(timezone.utc).isoformat()

    with db() as conn:
        conn.execute(
            """UPDATE orders SET tracking_status = ?, tracking_status_text = ?,
                                  tracking_checked_at = ?
               WHERE ebay_order_id = ?""",
            (new_status, status_text, now, order_id),
        )

    if new_status == "delivered" and order["tracking_status"] != "delivered":
        queue_buyer_message(
            ebay_order_id=order_id,
            trigger_event="tracking_delivered",
            template_slug="delivered",
        )

    return {
        "ok": True,
        "status": new_status,
        "status_text": status_text,
        "checked_at": now,
        "tracking_url": carrier_tracking_url(carrier, number),
    }


def check_vero_for_text(title: str, brand: str) -> list[dict[str, Any]]:
    """Return all VeRO matches for a product's title/brand."""
    text = f"{title or ''} {brand or ''}".lower()
    if not text.strip():
        return []
    with db() as conn:
        rows = conn.execute(
            "SELECT keyword, reason, level FROM vero_brands"
        ).fetchall()
    matches = []
    for r in rows:
        kw = r["keyword"]
        if kw and kw.lower() in text:
            matches.append({"keyword": kw, "reason": r["reason"], "level": r["level"]})
    return matches


def check_vero_for_asin(asin: str) -> list[dict[str, Any]]:
    with db() as conn:
        p = conn.execute(
            "SELECT title, brand FROM products WHERE asin = ?", (asin,)
        ).fetchone()
    if not p:
        return []
    return check_vero_for_text(p["title"] or "", p["brand"] or "")


def queue_buyer_message(
    *, ebay_order_id: str, trigger_event: str, template_slug: str
) -> Optional[int]:
    """Render the named template using the order's data and append to outbound queue.

    Skips silently if the template/order doesn't exist or the event has already
    been queued for this order (idempotent on (order, event)).
    """
    with db() as conn:
        order = conn.execute(
            "SELECT * FROM orders WHERE ebay_order_id = ?", (ebay_order_id,)
        ).fetchone()
        if not order:
            return None
        tpl = conn.execute(
            "SELECT * FROM message_templates WHERE slug = ?", (template_slug,)
        ).fetchone()
        if not tpl:
            return None
        # Idempotency: don't queue the same event twice for an order
        existing = conn.execute(
            "SELECT id FROM outbound_messages WHERE ebay_order_id = ? AND trigger_event = ?",
            (ebay_order_id, trigger_event),
        ).fetchone()
        if existing:
            return existing["id"]

        vars = _order_to_template_vars(order)
        subject = _render_template_text(tpl["subject"], vars)
        body = _render_template_text(tpl["body"], vars)
        cur = conn.execute(
            """INSERT INTO outbound_messages
               (ebay_order_id, template_slug, subject, body, trigger_event, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ebay_order_id, template_slug, subject, body, trigger_event,
             datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


async def _send_member_message(
    *, token: str, item_id: str, recipient_username: str,
    subject: str, body: str, parent_message_id: Optional[str] = None,
) -> tuple[bool, str]:
    """Send a buyer message via the eBay Trading API.

    Returns (ok, detail). `detail` is the eBay error message on failure or the
    Trading API timestamp on success.
    """
    parent_xml = (
        f"<ParentMessageID>{html_escape(parent_message_id)}</ParentMessageID>"
        if parent_message_id else ""
    )
    xml_body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<AddMemberMessageAAQToPartnerRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f"  <ItemID>{html_escape(item_id)}</ItemID>"
        "  <MemberMessage>"
        f"    <Subject>{html_escape(subject)}</Subject>"
        f"    <Body>{html_escape(body)}</Body>"
        "    <QuestionType>General</QuestionType>"
        f"    <RecipientID>{html_escape(recipient_username)}</RecipientID>"
        f"    {parent_xml}"
        "  </MemberMessage>"
        "</AddMemberMessageAAQToPartnerRequest>"
    )
    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": EBAY_TRADING_COMPAT_LEVEL,
        "X-EBAY-API-CALL-NAME": "AddMemberMessageAAQToPartner",
        "X-EBAY-API-SITEID": EBAY_TRADING_SITE_ID,
        "X-EBAY-API-IAF-TOKEN": token,
        "Content-Type": "text/xml",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(EBAY_TRADING_URL, content=xml_body, headers=headers)
    except httpx.HTTPError as e:
        return (False, f"HTTP error: {e}")

    if r.status_code != 200:
        return (False, f"HTTP {r.status_code}: {r.text[:300]}")

    # Parse the XML. Trading API namespaces everything under
    # urn:ebay:apis:eBLBaseComponents — match locally to avoid the ns dance.
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError as e:
        return (False, f"Bad XML response: {e}")

    def find_text(tag: str) -> str:
        for el in root.iter():
            if el.tag.rsplit("}", 1)[-1] == tag and el.text:
                return el.text.strip()
        return ""

    ack = find_text("Ack")
    if ack.lower() in ("success", "warning"):
        return (True, find_text("Timestamp") or "sent")

    # Failure path: surface the first error short message.
    short = find_text("ShortMessage") or find_text("LongMessage") or "eBay rejected the message"
    return (False, short[:300])


async def flush_outbound_messages(*, limit: int = 50) -> dict[str, Any]:
    """Send queued outbound messages to eBay. Returns a summary."""
    with db() as conn:
        rows = conn.execute(
            """SELECT m.id, m.ebay_order_id, m.subject, m.body, m.template_slug,
                      o.ebay_item_id, o.buyer_username
                 FROM outbound_messages m
                 LEFT JOIN orders o ON o.ebay_order_id = m.ebay_order_id
               WHERE m.status = 'queued'
               ORDER BY m.id ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    if not rows:
        return {"ok": True, "sent": 0, "failed": 0, "skipped": 0}

    try:
        token = await get_valid_token()
    except HTTPException as e:
        # No connected eBay account — leave messages queued, surface the reason.
        return {"ok": False, "sent": 0, "failed": 0, "skipped": len(rows),
                "error": e.detail}

    sent = failed = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for row in rows:
        item_id = (row["ebay_item_id"] or "").strip()
        buyer = (row["buyer_username"] or "").strip()
        if not item_id or not buyer:
            failed += 1
            with db() as conn:
                conn.execute(
                    """UPDATE outbound_messages
                          SET status = 'failed',
                              error = ?,
                              last_attempt_at = ?
                        WHERE id = ?""",
                    ("missing eBay item_id or buyer_username on order", now_iso, row["id"]),
                )
            continue

        ok, detail = await _send_member_message(
            token=token, item_id=item_id, recipient_username=buyer,
            subject=row["subject"], body=row["body"],
        )
        with db() as conn:
            if ok:
                conn.execute(
                    """UPDATE outbound_messages
                          SET status = 'sent',
                              sent_at = ?,
                              last_attempt_at = ?,
                              error = NULL
                        WHERE id = ?""",
                    (now_iso, now_iso, row["id"]),
                )
                sent += 1
            else:
                conn.execute(
                    """UPDATE outbound_messages
                          SET status = 'failed',
                              error = ?,
                              last_attempt_at = ?
                        WHERE id = ?""",
                    (detail, now_iso, row["id"]),
                )
                failed += 1

    return {"ok": True, "sent": sent, "failed": failed, "skipped": 0,
            "processed": sent + failed}


# ---------------------------------------------------------------------------
# Inbound message poll (Phase 4.1)
# eBay Trading API GetMyMessages is the only channel that returns the full
# buyer-message stream including "Ask a question" threads. Polled once per
# connected eBay account on a 5-minute scheduler.
# ---------------------------------------------------------------------------

def _xml_text(root: ET.Element, tag: str) -> str:
    """Find the first descendant element with local-name `tag` and return text."""
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == tag and el.text:
            return el.text.strip()
    return ""


async def _fetch_member_messages(
    *, token: str, start: datetime, end: datetime,
) -> tuple[bool, str, list[dict[str, Any]]]:
    """Call Trading API GetMyMessages between `start` and `end`.

    Returns (ok, detail, messages). On success `messages` is a list of dicts
    with the fields we care about (ebay_message_id, sender_username, subject,
    body, received_at, ebay_order_id, ebay_item_id, raw_xml).
    """
    fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    xml_body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<GetMyMessagesRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        "  <DetailLevel>ReturnMessages</DetailLevel>"
        f"  <StartTime>{start.strftime(fmt)}</StartTime>"
        f"  <EndTime>{end.strftime(fmt)}</EndTime>"
        "</GetMyMessagesRequest>"
    )
    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": EBAY_TRADING_COMPAT_LEVEL,
        "X-EBAY-API-CALL-NAME": "GetMyMessages",
        "X-EBAY-API-SITEID": EBAY_TRADING_SITE_ID,
        "X-EBAY-API-IAF-TOKEN": token,
        "Content-Type": "text/xml",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(EBAY_TRADING_URL, content=xml_body, headers=headers)
    except httpx.HTTPError as e:
        return (False, f"HTTP error: {e}", [])
    if r.status_code != 200:
        return (False, f"HTTP {r.status_code}: {r.text[:300]}", [])
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError as e:
        return (False, f"Bad XML: {e}", [])

    ack = _xml_text(root, "Ack").lower()
    if ack not in ("success", "warning"):
        short = _xml_text(root, "ShortMessage") or "eBay GetMyMessages failed"
        return (False, short[:300], [])

    messages = []
    for msg in root.iter():
        if msg.tag.rsplit("}", 1)[-1] != "Message":
            continue
        raw_text = ET.tostring(msg, encoding="unicode")
        messages.append({
            "ebay_message_id":  _xml_text(msg, "MessageID"),
            "sender_username":  _xml_text(msg, "Sender"),
            "subject":          _xml_text(msg, "Subject"),
            "body":             _xml_text(msg, "Text") or _xml_text(msg, "Body"),
            "received_at":      _xml_text(msg, "ReceiveDate"),
            "ebay_item_id":     _xml_text(msg, "ItemID"),
            "ebay_order_id":    "",  # GetMyMessages doesn't return order id directly
            "raw_xml":          raw_text[:8000],
        })
    return (True, "ok", messages)


async def poll_inbound_for_account(
    *, account_id: int, lookback_days: int = 7,
) -> dict[str, Any]:
    """Fetch + persist inbound messages for one eBay account.

    On first run for an account, looks back `lookback_days` days. On
    subsequent runs, looks back from the saved `last_inbox_poll_at` setting
    (with a one-hour overlap to catch eBay's eventual-consistency lag).
    """
    last_key = f"last_inbox_poll_at_{account_id}"
    last_iso = (get_settings_dict().get(last_key) or "").strip()
    now = datetime.now(timezone.utc)
    if last_iso:
        try:
            start = datetime.fromisoformat(last_iso) - timedelta(hours=1)
        except (TypeError, ValueError):
            start = now - timedelta(days=lookback_days)
    else:
        start = now - timedelta(days=lookback_days)

    try:
        token = await get_valid_token(account_id=account_id)
    except HTTPException as e:
        return {"ok": False, "account_id": account_id, "skipped": True,
                "error": e.detail}

    ok, detail, messages = await _fetch_member_messages(token=token, start=start, end=now)
    if not ok:
        return {"ok": False, "account_id": account_id, "error": detail}

    inserted = 0
    now_iso = now.isoformat()
    with db() as conn:
        for m in messages:
            mid = (m.get("ebay_message_id") or "").strip()
            if not mid:
                continue
            try:
                conn.execute(
                    """INSERT INTO inbound_messages
                          (account_id, ebay_message_id, ebay_order_id, ebay_item_id,
                           sender_username, subject, body, received_at, fetched_at, raw_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        account_id, mid,
                        m.get("ebay_order_id") or None,
                        m.get("ebay_item_id") or None,
                        m.get("sender_username") or None,
                        m.get("subject") or None,
                        m.get("body") or None,
                        m.get("received_at") or now_iso,
                        now_iso,
                        m.get("raw_xml") or None,
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                # Already have this MessageID for this account
                pass

    set_setting(last_key, now_iso)
    return {"ok": True, "account_id": account_id, "fetched": len(messages),
            "inserted": inserted}


async def poll_inbound_for_all_accounts(*, lookback_days: int = 7) -> dict[str, Any]:
    """Run the inbound poll across every connected eBay account."""
    with db() as conn:
        rows = conn.execute("SELECT id FROM ebay_accounts").fetchall()
    if not rows:
        return {"ok": True, "accounts": 0, "details": []}
    out = []
    for r in rows:
        try:
            out.append(await poll_inbound_for_account(
                account_id=r["id"], lookback_days=lookback_days,
            ))
        except Exception as e:  # noqa: BLE001 — never break the scheduler loop
            out.append({"ok": False, "account_id": r["id"], "error": str(e)[:200]})
    return {"ok": True, "accounts": len(rows), "details": out}


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


# ---------------------------------------------------------------------------
# Routes — description templates (Phase 2.3)
# ---------------------------------------------------------------------------

class DescriptionTemplateIn(BaseModel):
    slug: Optional[str] = None
    name: str
    body: str


def _row_to_desc_template(r: sqlite3.Row) -> dict[str, Any]:
    return dict(r)


@app.get("/api/description-templates")
def list_description_templates():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM description_templates ORDER BY id ASC"
        ).fetchall()
    return [_row_to_desc_template(r) for r in rows]


@app.post("/api/description-templates")
def create_description_template(payload: DescriptionTemplateIn):
    now = datetime.now(timezone.utc).isoformat()
    slug = payload.slug or _slugify(payload.name)
    with db() as conn:
        base, n = slug, 2
        while conn.execute("SELECT 1 FROM description_templates WHERE slug = ?", (slug,)).fetchone():
            slug = f"{base}_{n}"
            n += 1
        cur = conn.execute(
            """INSERT INTO description_templates (slug, name, body, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (slug, payload.name, payload.body, now, now),
        )
        row = conn.execute(
            "SELECT * FROM description_templates WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return _row_to_desc_template(row)


@app.put("/api/description-templates/{template_id}")
def update_description_template(template_id: int, payload: DescriptionTemplateIn):
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        if not conn.execute(
            "SELECT 1 FROM description_templates WHERE id = ?", (template_id,)
        ).fetchone():
            raise HTTPException(404, "template not found")
        conn.execute(
            """UPDATE description_templates SET name = ?, body = ?, updated_at = ?
               WHERE id = ?""",
            (payload.name, payload.body, now, template_id),
        )
        row = conn.execute(
            "SELECT * FROM description_templates WHERE id = ?", (template_id,)
        ).fetchone()
    return _row_to_desc_template(row)


@app.delete("/api/description-templates/{template_id}")
def delete_description_template(template_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT slug FROM description_templates WHERE id = ?", (template_id,)
        ).fetchone()
        if row and row["slug"] == "default":
            raise HTTPException(400, "The 'default' template can't be deleted (it can be edited).")
        cur = conn.execute("DELETE FROM description_templates WHERE id = ?", (template_id,))
    return {"ok": True, "deleted": cur.rowcount}


@app.post("/api/description-templates/{template_id}/preview")
def preview_description_template(template_id: int, asin: Optional[str] = None):
    """Render a template against a real product (or a sample) for the editor preview."""
    with db() as conn:
        tpl = conn.execute(
            "SELECT * FROM description_templates WHERE id = ?", (template_id,)
        ).fetchone()
        if not tpl:
            raise HTTPException(404, "template not found")
        product: dict[str, Any]
        if asin:
            row = conn.execute("SELECT * FROM products WHERE asin = ?", (asin,)).fetchone()
            product = row_to_product(row) if row else {}
        else:
            product = {}
    if not product:
        product = {
            "asin": "B0SAMPLE01",
            "title": "Sample Wireless Headphones — Noise Cancelling",
            "brand": "Acme",
            "description": "• Comfortable over-ear fit\n• 20-hour battery\n• Bluetooth 5.3",
            "price": 39.99, "currency": "USD",
            "spec_table": {"Color": "Black", "Connectivity": "Bluetooth"},
        }

    spec = product.get("spec_table") or {}
    vars: dict[str, str] = {
        "title":       str(product.get("title") or ""),
        "brand":       str(product.get("brand") or ""),
        "asin":        str(product.get("asin") or ""),
        "description": str(product.get("description") or ""),
        "price":       str(product.get("price") or ""),
        "currency":    str(product.get("currency") or ""),
    }
    if isinstance(spec, dict):
        for k, v in spec.items():
            if k and isinstance(k, str):
                vars[k] = str(v or "")
    return {
        "rendered": _render_template_text(tpl["body"], vars),
        "variables": vars,
    }


# ---------------------------------------------------------------------------
# Routes — inbound buyer messages (Phase 4.1)
# ---------------------------------------------------------------------------
@app.get("/api/messages/inbound")
def list_inbound_messages(
    order_id: Optional[str] = None,
    sender: Optional[str] = None,
    needs_reply: Optional[bool] = None,
    limit: int = 200,
):
    sql = "SELECT * FROM inbound_messages WHERE 1=1"
    params: list[Any] = []
    if order_id:
        sql += " AND ebay_order_id = ?"
        params.append(order_id)
    if sender:
        sql += " AND sender_username = ?"
        params.append(sender)
    if needs_reply is not None:
        sql += " AND needs_reply = ?"
        params.append(1 if needs_reply else 0)
    sql += " ORDER BY received_at DESC LIMIT ?"
    params.append(int(limit))
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/messages/inbound/poll-now")
async def api_inbox_poll_now(lookback_days: int = 7):
    """Trigger the inbound poll across all connected eBay accounts."""
    return await poll_inbound_for_all_accounts(lookback_days=lookback_days)


@app.post("/api/messages/inbound/{message_id}/mark-read")
def api_inbox_mark_read(message_id: int):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM inbound_messages WHERE id = ?", (message_id,)).fetchone():
            raise HTTPException(404, "message not found")
        conn.execute(
            "UPDATE inbound_messages SET read_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), message_id),
        )
    return {"ok": True}


@app.post("/api/messages/inbound/{message_id}/mark-replied")
def api_inbox_mark_replied(message_id: int):
    """Manually flag a message as replied (clears the needs_reply badge)."""
    with db() as conn:
        if not conn.execute("SELECT 1 FROM inbound_messages WHERE id = ?", (message_id,)).fetchone():
            raise HTTPException(404, "message not found")
        conn.execute(
            """UPDATE inbound_messages
                  SET replied_at = ?, needs_reply = 0
                WHERE id = ?""",
            (datetime.now(timezone.utc).isoformat(), message_id),
        )
    return {"ok": True}


@app.delete("/api/messages/inbound/{message_id}")
def api_inbox_delete(message_id: int):
    with db() as conn:
        cur = conn.execute("DELETE FROM inbound_messages WHERE id = ?", (message_id,))
    return {"ok": True, "deleted": cur.rowcount}


# ---------------------------------------------------------------------------
# Routes — outbound buyer messages
# ---------------------------------------------------------------------------
@app.get("/api/messages/outbound")
def list_outbound_messages(
    order_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
):
    sql = "SELECT * FROM outbound_messages WHERE 1=1"
    params: list[Any] = []
    if order_id:
        sql += " AND ebay_order_id = ?"
        params.append(order_id)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(int(limit))
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/scheduler/status")
def api_scheduler_status():
    return _droply_scheduler.status()


@app.post("/api/scheduler/run-now/{job_id}")
async def api_scheduler_run_now(job_id: str):
    """Fire a specific scheduler job immediately (useful for sandbox testing)."""
    valid = {"message_flush", "order_sync", "tracking_refresh", "inbox_poll"}
    if job_id not in valid:
        raise HTTPException(400, f"unknown job '{job_id}'. expected one of {sorted(valid)}")
    if job_id == "message_flush":
        return await flush_outbound_messages(limit=50)
    if job_id == "order_sync":
        return await sync_orders(limit=50)
    if job_id == "tracking_refresh":
        return await refresh_all_tracking()
    if job_id == "inbox_poll":
        return await poll_inbound_for_all_accounts(lookback_days=7)
    raise HTTPException(500, "unreachable")


@app.post("/api/messages/outbound/flush")
async def api_flush_outbound(limit: int = 50):
    """Send all queued outbound buyer messages via the eBay Trading API.

    Called by the scheduler every minute, but also exposed for the dashboard.
    """
    return await flush_outbound_messages(limit=limit)


@app.post("/api/messages/outbound/{message_id}/retry")
async def api_retry_outbound(message_id: int):
    """Re-queue a failed message so the next flush re-attempts delivery."""
    with db() as conn:
        if not conn.execute(
            "SELECT 1 FROM outbound_messages WHERE id = ?", (message_id,)
        ).fetchone():
            raise HTTPException(404, "message not found")
        conn.execute(
            """UPDATE outbound_messages
                  SET status = 'queued',
                      error = NULL
                WHERE id = ?""",
            (message_id,),
        )
    return {"ok": True}


@app.post("/api/messages/outbound/{message_id}/mark-sent")
def mark_message_sent(message_id: int):
    with db() as conn:
        if not conn.execute(
            "SELECT 1 FROM outbound_messages WHERE id = ?", (message_id,)
        ).fetchone():
            raise HTTPException(404, "message not found")
        conn.execute(
            "UPDATE outbound_messages SET status = 'sent', sent_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), message_id),
        )
    return {"ok": True}


@app.delete("/api/messages/outbound/{message_id}")
def discard_message(message_id: int):
    with db() as conn:
        cur = conn.execute("DELETE FROM outbound_messages WHERE id = ?", (message_id,))
    return {"ok": True, "deleted": cur.rowcount}


class QueueIn(BaseModel):
    template_slug: str
    trigger_event: str = "manual"


@app.post("/api/orders/{order_id}/messages")
def queue_message_for_order(order_id: str, payload: QueueIn):
    """Manually queue any template for an order (e.g. delivered, feedback_request)."""
    msg_id = queue_buyer_message(
        ebay_order_id=order_id,
        trigger_event=payload.trigger_event,
        template_slug=payload.template_slug,
    )
    if msg_id is None:
        raise HTTPException(400, "could not queue — order or template missing")
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM outbound_messages WHERE id = ?", (msg_id,)
        ).fetchone()
    return dict(row) if row else {"id": msg_id}


# ---------------------------------------------------------------------------
# Routes — VeRO (Verified Rights Owner) brand watchlist
# ---------------------------------------------------------------------------
@app.get("/api/vero/brands")
def list_vero_brands():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM vero_brands ORDER BY keyword ASC"
        ).fetchall()
    return [dict(r) for r in rows]


class VeroBrandIn(BaseModel):
    keyword: str
    reason: Optional[str] = ""
    level: str = "block"  # block | warn


@app.post("/api/vero/brands")
def add_vero_brand(payload: VeroBrandIn):
    if not payload.keyword.strip():
        raise HTTPException(400, "keyword required")
    if payload.level not in ("block", "warn"):
        raise HTTPException(400, "level must be 'block' or 'warn'")
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        try:
            cur = conn.execute(
                """INSERT INTO vero_brands (keyword, reason, level, created_at)
                   VALUES (?, ?, ?, ?)""",
                (payload.keyword.strip().lower(), payload.reason or "", payload.level, now),
            )
            row = conn.execute(
                "SELECT * FROM vero_brands WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        except sqlite3.IntegrityError:
            raise HTTPException(409, "keyword already exists")
    return dict(row)


@app.delete("/api/vero/brands/{brand_id}")
def delete_vero_brand(brand_id: int):
    with db() as conn:
        cur = conn.execute("DELETE FROM vero_brands WHERE id = ?", (brand_id,))
    return {"ok": True, "deleted": cur.rowcount}


@app.get("/api/vero/scan")
def scan_all_vero():
    """Return {asin: matches[]} for every saved product. Used by the Products UI."""
    with db() as conn:
        prods = conn.execute("SELECT asin, title, brand FROM products").fetchall()
        brands = conn.execute("SELECT keyword, reason, level FROM vero_brands").fetchall()
    out: dict[str, list[dict[str, Any]]] = {}
    for p in prods:
        text = f"{p['title'] or ''} {p['brand'] or ''}".lower()
        if not text.strip():
            continue
        matches = []
        for b in brands:
            kw = b["keyword"]
            if kw and kw in text:
                matches.append({"keyword": kw, "reason": b["reason"], "level": b["level"]})
        if matches:
            out[p["asin"]] = matches
    return out


@app.get("/api/vero/check/{asin}")
def check_vero(asin: str):
    return {"matches": check_vero_for_asin(asin)}


@app.get("/api/listings")
def api_listings():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM ebay_listings ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/listings/{asin}/{marketplace_id}/pause")
async def api_listing_pause(asin: str, marketplace_id: str):
    """Manually set the eBay listing's quantity to 0 (without delisting)."""
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM ebay_listings WHERE asin = ? AND marketplace_id = ?",
            (asin, marketplace_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Listing not found")
    if row["paused"]:
        return {"ok": True, "already_paused": True}

    ok, detail = await update_listing_quantity(
        sku=row["sku"], marketplace_id=marketplace_id, quantity=0,
    )
    if not ok:
        raise HTTPException(502, f"eBay quantity update failed: {detail}")
    now_iso = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """UPDATE ebay_listings
                  SET paused = 1, paused_at = ?, paused_reason = 'manual',
                      updated_at = ?
                WHERE asin = ? AND marketplace_id = ?""",
            (now_iso, now_iso, asin, marketplace_id),
        )
    return {"ok": True, "paused": True}


@app.post("/api/listings/{asin}/{marketplace_id}/resume")
async def api_listing_resume(asin: str, marketplace_id: str):
    """Restore the eBay listing's previous quantity."""
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM ebay_listings WHERE asin = ? AND marketplace_id = ?",
            (asin, marketplace_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Listing not found")
    if not row["paused"]:
        return {"ok": True, "already_active": True}

    qty = int(row["last_quantity"] or 1)
    ok, detail = await update_listing_quantity(
        sku=row["sku"], marketplace_id=marketplace_id, quantity=qty,
    )
    if not ok:
        raise HTTPException(502, f"eBay quantity update failed: {detail}")
    now_iso = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """UPDATE ebay_listings
                  SET paused = 0, paused_at = NULL, paused_reason = NULL,
                      updated_at = ?
                WHERE asin = ? AND marketplace_id = ?""",
            (now_iso, asin, marketplace_id),
        )
    return {"ok": True, "resumed": True, "quantity": qty}


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
    """Map an eBay Fulfillment API order JSON into our orders table.

    Returns True if the order was newly inserted (so callers can fire one-time
    side effects like queueing the order_confirmed buyer message).
    """
    line_items = order.get("lineItems", []) or []
    if not line_items:
        return False
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
    is_new = False
    with db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM orders WHERE ebay_order_id = ?", (order.get("orderId"),)
        ).fetchone()
        is_new = existing is None
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
    return is_new


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
    new_count = 0
    for o in orders:
        if _persist_order(o):
            new_count += 1
            # Auto-queue the order_confirmed buyer message for new orders
            queue_buyer_message(
                ebay_order_id=o.get("orderId"),
                trigger_event="order_synced",
                template_slug="order_confirmed",
            )
    return {"ok": True, "synced": len(orders), "new": new_count}


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
    # Auto-queue the "shipped" buyer message with tracking variables filled in
    queue_buyer_message(
        ebay_order_id=order_id,
        trigger_event="tracking_submitted",
        template_slug="shipped",
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
    out = dict(row)
    out["tracking_url"] = carrier_tracking_url(row["tracking_carrier"], row["tracking_number"])
    return out


@app.post("/api/orders/{order_id}/tracking/refresh")
async def refresh_one_tracking(order_id: str):
    return await refresh_tracking_for_order(order_id)


@app.post("/api/orders/refresh-all-tracking")
async def refresh_all_tracking():
    """Refresh tracking for every order with a tracking number that isn't already delivered."""
    with db() as conn:
        rows = conn.execute(
            "SELECT ebay_order_id FROM orders "
            "WHERE tracking_number IS NOT NULL AND tracking_number != '' "
            "  AND (tracking_status IS NULL OR tracking_status != 'delivered')"
        ).fetchall()
    refreshed = 0
    delivered_now = 0
    for r in rows:
        try:
            res = await refresh_tracking_for_order(r["ebay_order_id"])
            refreshed += 1
            if res.get("status") == "delivered":
                delivered_now += 1
        except Exception:
            continue
    return {"ok": True, "refreshed": refreshed, "delivered_now": delivered_now}


@app.post("/api/orders/{order_id}/tracking/mark-delivered")
def mark_order_delivered(order_id: str):
    """Manual override — useful when no carrier API is wired up. Auto-queues
    the `delivered` buyer message."""
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        existing = conn.execute(
            "SELECT tracking_status FROM orders WHERE ebay_order_id = ?", (order_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(404, "order not found")
        was_delivered = existing["tracking_status"] == "delivered"
        conn.execute(
            """UPDATE orders SET tracking_status = 'delivered',
                                  tracking_status_text = 'Marked as delivered manually',
                                  tracking_checked_at = ?
               WHERE ebay_order_id = ?""",
            (now, order_id),
        )
    if not was_delivered:
        queue_buyer_message(
            ebay_order_id=order_id,
            trigger_event="manually_delivered",
            template_slug="delivered",
        )
    return {"ok": True, "status": "delivered"}


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
        "notes": result.notes,
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
