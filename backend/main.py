"""Droply backend — SQLite-backed, no auth, no Supabase.

Endpoints used by the Chrome extension and the Next.js dashboard:
  POST   /api/products              save / upsert one product (called by extension)
  GET    /api/products              list all
  GET    /api/products/{asin}       fetch one
  DELETE /api/products/{asin}       remove one
  POST   /api/products/bulk         upsert many (used by "Sync from extension")
  DELETE /api/products              clear all
  GET    /api/stats                 aggregate stats for dashboard
  GET    /api/orders                list orders (empty until eBay flow is wired back)
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, date, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB_PATH = os.getenv("DROPLY_DB", os.path.join(os.path.dirname(__file__), "droply.db"))

app = FastAPI(title="Droply API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------
# DB
# ---------------------------------------------------------------
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_saved_at ON products(saved_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")


init_db()


def row_to_product(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    try:
        d["images"] = json.loads(d.get("images") or "[]")
    except Exception:
        d["images"] = []
    return d


# ---------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------
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


# ---------------------------------------------------------------
# Routes
# ---------------------------------------------------------------
@app.get("/")
def root():
    return {"service": "Droply API", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}


def _upsert(conn: sqlite3.Connection, p: ProductIn) -> dict[str, Any]:
    if not p.asin:
        raise HTTPException(status_code=400, detail="asin required")
    saved_at = p.saved_at or datetime.now(timezone.utc).isoformat()
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
    return {"ok": True, "deleted": cur.rowcount}


@app.delete("/api/products")
def clear_products():
    with db() as conn:
        cur = conn.execute("DELETE FROM products")
    return {"ok": True, "deleted": cur.rowcount}


@app.get("/api/orders")
def list_orders():
    with db() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


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
        # Last 14 days saved count
        rows = conn.execute(
            """
            SELECT substr(saved_at,1,10) AS day, COUNT(*) AS c
            FROM products
            GROUP BY day
            ORDER BY day DESC
            LIMIT 14
            """
        ).fetchall()
        # Top brands
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
