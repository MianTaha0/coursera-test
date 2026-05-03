"""Droply FastAPI app — entrypoint for all backend endpoints."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import ebay as ebay_api
from . import messages as messages_mod
from . import orders as orders_mod
from .database import admin_client, settings, verify_token
from .monitor import start_scheduler, stop_scheduler

log = logging.getLogger("droply")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Droply API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------
def current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    user = verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


# ---------------------------------------------------------------
# Health + meta
# ---------------------------------------------------------------
@app.get("/")
def root():
    return {"service": "Droply API", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/api/me")
def me(user=Depends(current_user)):
    db = admin_client()
    profile = db.table("users").select("*").eq("id", user["id"]).limit(1).execute().data
    ebay = db.table("ebay_accounts").select("ebay_username, connected_at").eq("user_id", user["id"]).limit(1).execute().data
    return {
        "id": user["id"],
        "email": user["email"],
        "profile": profile[0] if profile else None,
        "ebay_username": ebay[0]["ebay_username"] if ebay else None,
        "ebay_connected": bool(ebay),
    }


# ---------------------------------------------------------------
# Extension auth
# ---------------------------------------------------------------
class ExtensionLogin(BaseModel):
    email: str
    password: str


@app.post("/api/auth/extension")
def auth_extension(payload: ExtensionLogin):
    """Validates email+password against Supabase Auth and returns a session token."""
    from supabase import create_client

    sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    try:
        res = sb.auth.sign_in_with_password({"email": payload.email, "password": payload.password})
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Login failed: {e}")
    if not res.session:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {
        "access_token": res.session.access_token,
        "refresh_token": res.session.refresh_token,
        "user_id": res.user.id,
        "email": res.user.email,
    }


# ---------------------------------------------------------------
# Product import (called by Chrome extension)
# ---------------------------------------------------------------
class ImportProductIn(BaseModel):
    asin: str
    title: str = ""
    price: Optional[float] = None
    currency: Optional[str] = "USD"
    images: list[str] = Field(default_factory=list)
    description: Optional[str] = ""
    stock_status: Optional[str] = "in_stock"
    brand: Optional[str] = ""
    amazon_url: Optional[str] = None
    source_marketplace: Optional[str] = None


@app.post("/api/import-product")
def import_product(payload: ImportProductIn, user=Depends(current_user)):
    if not payload.asin:
        raise HTTPException(status_code=400, detail="ASIN missing")
    if payload.price is None or payload.price <= 0:
        raise HTTPException(status_code=400, detail="Could not read Amazon price")

    db = admin_client()

    # 1) Try to publish on eBay first; if that fails, still save the product as draft.
    listing: Optional[dict] = None
    listing_error: Optional[str] = None
    try:
        listing = ebay_api.create_listing(user["id"], payload.model_dump())
    except Exception as e:
        listing_error = str(e)
        log.warning("eBay listing failed for user %s asin %s: %s", user["id"], payload.asin, e)

    ebay_price = listing["ebay_price"] if listing else round(payload.price * (1 + settings.DEFAULT_MARKUP_PERCENT / 100.0), 2)
    profit_margin = round(ebay_price - payload.price, 2)

    row = {
        "user_id": user["id"],
        "asin": payload.asin,
        "title": payload.title,
        "images": payload.images,
        "description": payload.description,
        "brand": payload.brand,
        "amazon_url": payload.amazon_url,
        "amazon_price": payload.price,
        "ebay_price": ebay_price,
        "profit_margin": profit_margin,
        "ebay_listing_id": listing["ebay_listing_id"] if listing else None,
        "ebay_listing_url": listing["ebay_listing_url"] if listing else None,
        "stock_status": payload.stock_status or "in_stock",
        "monitor_status": "active",
    }
    res = db.table("products").upsert(row, on_conflict="user_id,asin").execute()

    return {
        "ok": True,
        "product": (res.data or [row])[0],
        "ebay_listing": listing,
        "warning": listing_error,
    }


# ---------------------------------------------------------------
# eBay OAuth
# ---------------------------------------------------------------
@app.get("/api/ebay/oauth/url")
def ebay_oauth_url(user=Depends(current_user)):
    return ebay_api.get_oauth_url(state=user["id"])


@app.get("/api/ebay/oauth/callback")
def ebay_oauth_callback(code: str, state: str):
    """eBay redirects here after consent. `state` carries our user id."""
    try:
        result = ebay_api.handle_oauth_callback(code, state)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings?ebay=connected&user={result.get('ebay_username','')}")


@app.post("/api/ebay/disconnect")
def ebay_disconnect(user=Depends(current_user)):
    ebay_api.disconnect(user["id"])
    return {"ok": True}


@app.get("/api/ebay/orders/sync")
def ebay_orders_sync(user=Depends(current_user)):
    return {"orders": ebay_api.get_orders(user["id"])}


# ---------------------------------------------------------------
# eBay order webhook + auto-fulfill
# ---------------------------------------------------------------
@app.post("/api/ebay/webhook")
async def ebay_webhook(req: Request):
    return await orders_mod.handle_webhook(req)


# ---------------------------------------------------------------
# Manual triggers (useful for testing)
# ---------------------------------------------------------------
@app.post("/api/orders/{order_id}/fulfill")
def trigger_fulfill(order_id: str, user=Depends(current_user)):
    return orders_mod.auto_fulfill_order(order_id, requester_id=user["id"])


@app.post("/api/messages/{order_id}/{kind}")
def trigger_message(order_id: str, kind: str, user=Depends(current_user)):
    return messages_mod.send(kind, order_id, requester_id=user["id"])
