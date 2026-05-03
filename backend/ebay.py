"""eBay REST API client for Droply.

Handles OAuth, listing creation/update, message sending, and order sync via the
modern Inventory API (sell.inventory) and Fulfillment API (sell.fulfillment).
"""
from __future__ import annotations

import base64
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from .database import admin_client, settings


# ---------------------------------------------------------------
# Hosts (production / sandbox)
# ---------------------------------------------------------------
def _is_sandbox() -> bool:
    return settings.EBAY_ENV.lower() == "sandbox"


def _api_host() -> str:
    return "https://api.sandbox.ebay.com" if _is_sandbox() else "https://api.ebay.com"


def _oauth_host() -> str:
    return "https://auth.sandbox.ebay.com" if _is_sandbox() else "https://auth.ebay.com"


SCOPES = [
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
]

DEFAULT_MARKETPLACE = "EBAY_US"
DEFAULT_LOCATION_KEY = "droply-default-loc"


# ---------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------
def get_oauth_url(state: Optional[str] = None) -> dict:
    """Return the eBay OAuth consent URL."""
    state = state or secrets.token_urlsafe(16)
    params = {
        "client_id": settings.EBAY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.EBAY_RUNAME,
        "scope": " ".join(SCOPES),
        "state": state,
    }
    return {
        "url": f"{_oauth_host()}/oauth2/authorize?{urlencode(params)}",
        "state": state,
    }


def _basic_auth_header() -> str:
    raw = f"{settings.EBAY_CLIENT_ID}:{settings.EBAY_CLIENT_SECRET}".encode()
    return f"Basic {base64.b64encode(raw).decode()}"


def handle_oauth_callback(code: str, user_id: str) -> dict:
    """Exchange auth code for tokens, persist them against the user."""
    resp = httpx.post(
        f"{_api_host()}/identity/v1/oauth2/token",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": _basic_auth_header(),
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.EBAY_RUNAME,
        },
        timeout=30,
    )
    resp.raise_for_status()
    tokens = resp.json()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 7200) - 60)

    # Get the seller's eBay username via Identity API.
    me = httpx.get(
        f"{_api_host()}/commerce/identity/v1/user/",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=30,
    )
    username = me.json().get("username") if me.status_code == 200 else None

    db = admin_client()
    db.table("ebay_accounts").upsert(
        {
            "user_id": user_id,
            "ebay_username": username,
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token"),
            "token_expires_at": expires_at.isoformat(),
            "connected_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="user_id",
    ).execute()
    return {"ebay_username": username}


def disconnect(user_id: str) -> None:
    admin_client().table("ebay_accounts").delete().eq("user_id", user_id).execute()


def get_account(user_id: str) -> Optional[dict]:
    res = (
        admin_client()
        .table("ebay_accounts")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def refresh_token(user_id: str) -> str:
    """Return a valid access token, refreshing it if expired."""
    account = get_account(user_id)
    if not account:
        raise RuntimeError("eBay account not connected")
    expires_at = account.get("token_expires_at")
    if expires_at:
        ts = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if ts > datetime.now(timezone.utc):
            return account["access_token"]
    if not account.get("refresh_token"):
        raise RuntimeError("eBay refresh token missing — please reconnect")
    resp = httpx.post(
        f"{_api_host()}/identity/v1/oauth2/token",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": _basic_auth_header(),
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": account["refresh_token"],
            "scope": " ".join(SCOPES),
        },
        timeout=30,
    )
    resp.raise_for_status()
    tokens = resp.json()
    new_access = tokens["access_token"]
    new_expires = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 7200) - 60)
    admin_client().table("ebay_accounts").update(
        {"access_token": new_access, "token_expires_at": new_expires.isoformat()}
    ).eq("user_id", user_id).execute()
    return new_access


# ---------------------------------------------------------------
# Internal HTTP helper
# ---------------------------------------------------------------
def _headers(token: str, marketplace: str = DEFAULT_MARKETPLACE, lang: str = "en-US") -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Content-Language": lang,
        "X-EBAY-C-MARKETPLACE-ID": marketplace,
    }


def _request(method: str, user_id: str, path: str, **kw) -> httpx.Response:
    token = refresh_token(user_id)
    marketplace = kw.pop("marketplace", DEFAULT_MARKETPLACE)
    headers = _headers(token, marketplace)
    headers.update(kw.pop("headers", {}))
    return httpx.request(method, f"{_api_host()}{path}", headers=headers, timeout=30, **kw)


# ---------------------------------------------------------------
# Default location + policies (created on demand the first time)
# ---------------------------------------------------------------
def _ensure_location(user_id: str) -> str:
    """Create a generic merchant location if one doesn't exist. Returns key."""
    r = _request("GET", user_id, f"/sell/inventory/v1/location/{DEFAULT_LOCATION_KEY}")
    if r.status_code == 200:
        return DEFAULT_LOCATION_KEY
    body = {
        "location": {"address": {"country": "US", "postalCode": "10001"}},
        "locationInstructions": "Items ship from supplier",
        "name": "Droply Default",
        "merchantLocationStatus": "ENABLED",
        "locationTypes": ["WAREHOUSE"],
    }
    r2 = _request(
        "POST",
        user_id,
        f"/sell/inventory/v1/location/{DEFAULT_LOCATION_KEY}",
        json=body,
    )
    if r2.status_code not in (200, 204):
        raise RuntimeError(f"Failed to create eBay location: {r2.text}")
    return DEFAULT_LOCATION_KEY


def _first_policy(user_id: str, kind: str, marketplace: str) -> Optional[str]:
    path = {
        "fulfillment": "/sell/account/v1/fulfillment_policy",
        "payment": "/sell/account/v1/payment_policy",
        "return": "/sell/account/v1/return_policy",
    }[kind]
    r = _request("GET", user_id, f"{path}?marketplace_id={marketplace}")
    if r.status_code != 200:
        return None
    data = r.json()
    arr = data.get(f"{kind}Policies") or []
    if arr:
        return arr[0].get(f"{kind}PolicyId") or arr[0].get("policyId")
    return None


# ---------------------------------------------------------------
# Listing CRUD
# ---------------------------------------------------------------
def _calc_ebay_price(amazon_price: float, markup_percent: Optional[float] = None) -> float:
    pct = markup_percent if markup_percent is not None else settings.DEFAULT_MARKUP_PERCENT
    return round(float(amazon_price) * (1 + pct / 100.0), 2)


def create_listing(user_id: str, product_data: dict) -> dict:
    """Create a complete eBay listing for an Amazon product.

    product_data is the JSON payload from the Chrome extension.
    Returns {ebay_listing_id, ebay_listing_url, ebay_price, sku, offer_id}.
    """
    sku = f"DROPLY-{product_data.get('asin') or uuid.uuid4().hex[:10]}"
    marketplace = DEFAULT_MARKETPLACE
    price = _calc_ebay_price(product_data.get("price") or 0)
    currency = (product_data.get("currency") or "USD").upper()
    images = [u for u in (product_data.get("images") or []) if u.startswith("http")][:12]
    title = (product_data.get("title") or "")[:80]  # eBay max 80 chars
    description = product_data.get("description") or title
    brand = product_data.get("brand") or "Unbranded"

    # 1) Inventory item
    inv_body = {
        "availability": {"shipToLocationAvailability": {"quantity": 1}},
        "condition": "NEW",
        "product": {
            "title": title,
            "description": description,
            "imageUrls": images,
            "brand": brand,
            "aspects": {"Brand": [brand]},
        },
    }
    r = _request("PUT", user_id, f"/sell/inventory/v1/inventory_item/{sku}", json=inv_body)
    if r.status_code not in (200, 201, 204):
        raise RuntimeError(f"Inventory item failed: {r.text}")

    # 2) Make sure location + policies exist
    location_key = _ensure_location(user_id)
    fulfillment = _first_policy(user_id, "fulfillment", marketplace)
    payment = _first_policy(user_id, "payment", marketplace)
    ret = _first_policy(user_id, "return", marketplace)
    if not (fulfillment and payment and ret):
        raise RuntimeError(
            "Missing eBay business policies — create fulfillment, payment, and return "
            "policies in your eBay seller account, then retry."
        )

    # 3) Offer
    offer_body = {
        "sku": sku,
        "marketplaceId": marketplace,
        "format": "FIXED_PRICE",
        "availableQuantity": 1,
        "categoryId": "139973",  # generic — recommend overriding per category
        "listingDescription": description,
        "listingPolicies": {
            "fulfillmentPolicyId": fulfillment,
            "paymentPolicyId": payment,
            "returnPolicyId": ret,
        },
        "pricingSummary": {"price": {"value": f"{price:.2f}", "currency": currency}},
        "merchantLocationKey": location_key,
    }
    r = _request("POST", user_id, "/sell/inventory/v1/offer", json=offer_body)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Offer create failed: {r.text}")
    offer_id = r.json().get("offerId")

    # 4) Publish
    r = _request("POST", user_id, f"/sell/inventory/v1/offer/{offer_id}/publish")
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Publish failed: {r.text}")
    listing_id = r.json().get("listingId")

    domain = "sandbox.ebay.com" if _is_sandbox() else "ebay.com"
    return {
        "ebay_listing_id": listing_id,
        "ebay_listing_url": f"https://www.{domain}/itm/{listing_id}",
        "ebay_price": price,
        "sku": sku,
        "offer_id": offer_id,
    }


def update_listing_price(user_id: str, listing_id: str, new_price: float) -> None:
    """Update the price on an existing eBay listing by SKU/offer."""
    # Find offer by listingId
    r = _request("GET", user_id, f"/sell/inventory/v1/offer?listing_ids={listing_id}")
    if r.status_code != 200 or not r.json().get("offers"):
        raise RuntimeError(f"Offer lookup failed for listing {listing_id}: {r.text}")
    offer = r.json()["offers"][0]
    offer_id = offer["offerId"]
    currency = offer["pricingSummary"]["price"].get("currency", "USD")
    body = {"pricingSummary": {"price": {"value": f"{new_price:.2f}", "currency": currency}}}
    r = _request("POST", user_id, f"/sell/inventory/v1/offer/{offer_id}", json=body)
    if r.status_code not in (200, 204):
        raise RuntimeError(f"Price update failed: {r.text}")


def end_listing(user_id: str, listing_id: str) -> None:
    """End an eBay listing (withdraws the offer)."""
    r = _request("GET", user_id, f"/sell/inventory/v1/offer?listing_ids={listing_id}")
    if r.status_code != 200 or not r.json().get("offers"):
        return
    offer_id = r.json()["offers"][0]["offerId"]
    _request("POST", user_id, f"/sell/inventory/v1/offer/{offer_id}/withdraw")


def send_message(user_id: str, order_id: str, message_text: str) -> None:
    """Send an eBay buyer message about a specific order via the Post Order API."""
    body = {
        "subject": "About your order",
        "body": message_text,
        "recipientUserId": None,  # eBay derives from order
    }
    r = _request(
        "POST",
        user_id,
        f"/post-order/v2/return/contact_buyer/{order_id}",
        json=body,
    )
    if r.status_code not in (200, 201, 204):
        # Fall back to the inquiry contact endpoint
        _request(
            "POST",
            user_id,
            f"/post-order/v2/inquiry/contact_seller/{order_id}",
            json=body,
        )


def get_orders(user_id: str) -> list[dict]:
    """Fetch recent orders, persist any new ones, return them."""
    r = _request(
        "GET",
        user_id,
        "/sell/fulfillment/v1/order?limit=50",
    )
    if r.status_code != 200:
        raise RuntimeError(f"Order fetch failed: {r.text}")
    orders = r.json().get("orders", [])
    db = admin_client()
    saved = []
    for o in orders:
        ebay_order_id = o.get("orderId")
        if not ebay_order_id:
            continue
        line = (o.get("lineItems") or [{}])[0]
        sku = line.get("sku")
        product = (
            db.table("products")
            .select("id, amazon_price")
            .eq("user_id", user_id)
            .ilike("ebay_listing_url", f"%{line.get('listingId') or ''}%")
            .limit(1)
            .execute()
            .data
        )
        product_id = product[0]["id"] if product else None
        amazon_cost = product[0]["amazon_price"] if product else None
        sale_price = float((line.get("total") or {}).get("value") or 0)
        ship = (o.get("fulfillmentStartInstructions") or [{}])[0].get("shippingStep", {})
        addr = (ship.get("shipTo") or {})
        row = {
            "user_id": user_id,
            "ebay_order_id": ebay_order_id,
            "product_id": product_id,
            "buyer_name": (addr.get("fullName") or o.get("buyer", {}).get("username")),
            "buyer_address": addr,
            "sale_price": sale_price,
            "amazon_cost": amazon_cost,
            "profit": (sale_price - amazon_cost) if amazon_cost is not None else None,
            "status": "pending",
        }
        db.table("orders").upsert(row, on_conflict="ebay_order_id").execute()
        saved.append(row)
    return saved


def add_tracking(user_id: str, ebay_order_id: str, tracking_number: str, carrier: str = "USPS") -> None:
    """Push a tracking number to an eBay order."""
    # Need the line item id
    r = _request("GET", user_id, f"/sell/fulfillment/v1/order/{ebay_order_id}")
    if r.status_code != 200:
        raise RuntimeError(f"Order lookup failed: {r.text}")
    line_items = [
        {"lineItemId": li["lineItemId"], "quantity": li["quantity"]}
        for li in r.json().get("lineItems", [])
    ]
    body = {
        "lineItems": line_items,
        "shippedDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "shippingCarrierCode": carrier,
        "trackingNumber": tracking_number,
    }
    r = _request(
        "POST",
        user_id,
        f"/sell/fulfillment/v1/order/{ebay_order_id}/shipping_fulfillment",
        json=body,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Add tracking failed: {r.text}")
