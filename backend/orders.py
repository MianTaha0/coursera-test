"""Order webhook + auto-fulfillment via Amazon Playwright."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Request

from . import amazon
from . import ebay as ebay_api
from . import messages as messages_mod
from .database import admin_client

log = logging.getLogger("droply.orders")

EBAY_VERIFICATION_TOKEN = os.getenv("EBAY_VERIFICATION_TOKEN", "")


# ---------------------------------------------------------------
# Webhook handler
# ---------------------------------------------------------------
async def handle_webhook(req: Request):
    raw = await req.body()

    # eBay account-deletion notification challenge (returns SHA-256 hash).
    challenge = req.query_params.get("challenge_code")
    if challenge:
        endpoint = str(req.url).split("?")[0]
        h = hashlib.sha256()
        h.update((challenge + EBAY_VERIFICATION_TOKEN + endpoint).encode())
        return {"challengeResponse": h.hexdigest()}

    # Verify signature header (best-effort).
    sig = req.headers.get("x-ebay-signature", "")
    if EBAY_VERIFICATION_TOKEN and sig:
        expected = hmac.new(EBAY_VERIFICATION_TOKEN.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw or b"{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    notification = payload.get("notification") or payload
    data = notification.get("data") or {}
    ebay_order_id = data.get("orderId") or data.get("OrderID") or payload.get("orderId")
    if not ebay_order_id:
        return {"ok": True, "ignored": True}

    db = admin_client()
    # Find the user that owns the listing for this order.
    order_meta = data
    line_items = order_meta.get("lineItems") or []
    listing_id = (line_items[0] if line_items else {}).get("listingId")

    user_id: Optional[str] = None
    product_id: Optional[str] = None
    amazon_cost: Optional[float] = None
    if listing_id:
        match = (
            db.table("products")
            .select("id, user_id, amazon_price")
            .eq("ebay_listing_id", str(listing_id))
            .limit(1)
            .execute()
            .data
        )
        if match:
            user_id = match[0]["user_id"]
            product_id = match[0]["id"]
            amazon_cost = match[0]["amazon_price"]

    if not user_id:
        # Fallback: look up by ebay account when only the seller username is provided
        seller = order_meta.get("sellerUsername")
        if seller:
            acc = db.table("ebay_accounts").select("user_id").eq("ebay_username", seller).limit(1).execute().data
            if acc:
                user_id = acc[0]["user_id"]

    if not user_id:
        log.warning("Webhook for order %s could not be linked to a user", ebay_order_id)
        return {"ok": True, "unlinked": True}

    sale_price = float((order_meta.get("totalAmount") or {}).get("value") or 0)
    buyer = order_meta.get("buyer") or {}
    address = order_meta.get("shipTo") or {}

    row = {
        "user_id": user_id,
        "ebay_order_id": ebay_order_id,
        "product_id": product_id,
        "buyer_name": buyer.get("username") or address.get("fullName"),
        "buyer_address": address,
        "sale_price": sale_price,
        "amazon_cost": amazon_cost,
        "profit": (sale_price - amazon_cost) if (sale_price and amazon_cost is not None) else None,
        "status": "pending",
    }
    saved = db.table("orders").upsert(row, on_conflict="ebay_order_id").execute()
    order_db_id = saved.data[0]["id"] if saved.data else None

    if order_db_id:
        try:
            auto_fulfill_order(order_db_id)
        except Exception as e:
            log.warning("auto_fulfill failed: %s", e)

    return {"ok": True}


# ---------------------------------------------------------------
# Auto-fulfill
# ---------------------------------------------------------------
def auto_fulfill_order(order_id: str, requester_id: Optional[str] = None) -> dict:
    db = admin_client()
    res = db.table("orders").select("*").eq("id", order_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Order not found")
    order = res.data[0]
    if requester_id and order["user_id"] != requester_id:
        raise HTTPException(status_code=403, detail="Not your order")

    if order.get("amazon_order_id"):
        return {"ok": True, "already": True, "amazon_order_id": order["amazon_order_id"]}

    if not order.get("product_id"):
        raise HTTPException(status_code=400, detail="Order has no linked product")

    prod = db.table("products").select("asin, amazon_url").eq("id", order["product_id"]).limit(1).execute().data
    if not prod:
        raise HTTPException(status_code=400, detail="Product not found")
    asin = prod[0]["asin"]

    address = order.get("buyer_address") or {}
    amazon_order_id = amazon.place_order(asin, address)

    if not amazon_order_id:
        db.table("orders").update({"status": "fulfillment_failed"}).eq("id", order_id).execute()
        raise HTTPException(status_code=502, detail="Amazon checkout did not return an order ID")

    db.table("orders").update(
        {
            "amazon_order_id": amazon_order_id,
            "status": "fulfilled",
            "fulfilled_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", order_id).execute()

    try:
        messages_mod.send("confirmation", order_id)
    except Exception as e:
        log.warning("confirmation message failed: %s", e)

    return {"ok": True, "amazon_order_id": amazon_order_id}


# ---------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------
async def get_tracking_async(order_id: str) -> dict:
    db = admin_client()
    res = db.table("orders").select("*").eq("id", order_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Order not found")
    order = res.data[0]
    if not order.get("amazon_order_id"):
        return {"ok": False, "reason": "no amazon order"}
    if order.get("tracking_number"):
        return {"ok": True, "tracking_number": order["tracking_number"], "cached": True}

    tracking = await amazon.get_tracking_async(order["amazon_order_id"])
    if not tracking:
        return {"ok": False, "reason": "tracking not yet available"}

    try:
        ebay_api.add_tracking(order["user_id"], order["ebay_order_id"], tracking)
    except Exception as e:
        log.warning("eBay add_tracking failed: %s", e)

    db.table("orders").update(
        {
            "tracking_number": tracking,
            "status": "shipped",
            "shipped_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", order_id).execute()

    try:
        messages_mod.send("shipping", order_id)
    except Exception as e:
        log.warning("shipping message failed: %s", e)

    return {"ok": True, "tracking_number": tracking}


def get_tracking(order_id: str) -> dict:
    import asyncio as _aio
    return _aio.run(get_tracking_async(order_id))
