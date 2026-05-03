"""Automated buyer messages sent through eBay."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from . import ebay as ebay_api
from .database import admin_client

log = logging.getLogger("droply.messages")


TEMPLATES = {
    "confirmation": (
        "Hi {buyer_name}, thank you for your order! We have received your order "
        "and it is now being processed. You will receive a tracking number as "
        "soon as your item is dispatched. Please feel free to message us if you "
        "have any questions!"
    ),
    "shipping": (
        "Great news {buyer_name}! Your order has been dispatched and is on its "
        "way to you. Your tracking number is {tracking_number}. You can use this "
        "to track your delivery. Thank you for shopping with us!"
    ),
    "delivery": (
        "Hi {buyer_name}, we hope you have received your order and are happy with "
        "it! If you are satisfied with your purchase, we would really appreciate "
        "it if you could leave us positive feedback. It helps us a lot. Thank you "
        "for your support!"
    ),
    "feedback": (
        "Hi {buyer_name}, just a quick follow-up on your recent order — if you "
        "loved it, would you mind leaving us a positive review on eBay? It would "
        "mean the world to a small seller like us. Thanks again!"
    ),
}


def _load_order(order_id: str, requester_id: Optional[str] = None) -> dict:
    db = admin_client()
    res = db.table("orders").select("*").eq("id", order_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Order not found")
    order = res.data[0]
    if requester_id and order["user_id"] != requester_id:
        raise HTTPException(status_code=403, detail="Not your order")
    return order


def _send(order: dict, body: str) -> None:
    if not order.get("ebay_order_id"):
        raise HTTPException(status_code=400, detail="Order missing ebay_order_id")
    ebay_api.send_message(order["user_id"], order["ebay_order_id"], body)


def send_order_confirmation_message(order_id: str) -> dict:
    order = _load_order(order_id)
    body = TEMPLATES["confirmation"].format(buyer_name=order.get("buyer_name") or "there")
    _send(order, body)
    return {"ok": True, "kind": "confirmation"}


def send_shipping_message(order_id: str) -> dict:
    order = _load_order(order_id)
    body = TEMPLATES["shipping"].format(
        buyer_name=order.get("buyer_name") or "there",
        tracking_number=order.get("tracking_number") or "",
    )
    _send(order, body)
    return {"ok": True, "kind": "shipping"}


def send_delivery_message(order_id: str) -> dict:
    order = _load_order(order_id)
    body = TEMPLATES["delivery"].format(buyer_name=order.get("buyer_name") or "there")
    _send(order, body)
    admin_client().table("orders").update(
        {"status": "delivered", "delivered_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", order_id).execute()
    return {"ok": True, "kind": "delivery"}


def send_feedback_request(order_id: str) -> dict:
    """Sent 3 days after delivery confirmation."""
    order = _load_order(order_id)
    delivered_at = order.get("delivered_at")
    if delivered_at:
        ts = datetime.fromisoformat(delivered_at.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - ts < timedelta(days=3):
            return {"ok": False, "reason": "too early"}
    body = TEMPLATES["feedback"].format(buyer_name=order.get("buyer_name") or "there")
    _send(order, body)
    return {"ok": True, "kind": "feedback"}


def send(kind: str, order_id: str, requester_id: Optional[str] = None) -> dict:
    """Generic dispatch — used by /api/messages/{order}/{kind}."""
    if requester_id:
        _load_order(order_id, requester_id)  # auth check
    handler = {
        "confirmation": send_order_confirmation_message,
        "shipping": send_shipping_message,
        "delivery": send_delivery_message,
        "feedback": send_feedback_request,
    }.get(kind)
    if not handler:
        raise HTTPException(status_code=400, detail=f"Unknown message kind: {kind}")
    return handler(order_id)
