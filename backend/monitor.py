"""Background price + stock monitor.

Every 4 hours: pull active products from Supabase, scrape Amazon for current
price + stock, and reconcile changes against the eBay listings.
Every 6 hours: pull tracking from Amazon for fulfilled orders and push to eBay.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import amazon, ebay as ebay_api
from .database import admin_client

log = logging.getLogger("droply.monitor")
_scheduler: Optional[AsyncIOScheduler] = None
BATCH_SIZE = 10


def start_scheduler() -> None:
    global _scheduler
    if _scheduler:
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(monitor_all_products, "interval", hours=4, id="monitor_products", coalesce=True, max_instances=1)
    _scheduler.add_job(sync_tracking, "interval", hours=6, id="sync_tracking", coalesce=True, max_instances=1)
    _scheduler.start()
    log.info("Scheduler started")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("Scheduler stopped")


# ---------------------------------------------------------------
# Product monitor
# ---------------------------------------------------------------
def _marketplace_from_url(url: str) -> str:
    if not url:
        return "amazon.com"
    for host in ("amazon.co.uk", "amazon.de", "amazon.fr", "amazon.it", "amazon.es", "amazon.com"):
        if host in url:
            return host
    return "amazon.com"


async def _check_one(product: dict) -> None:
    db = admin_client()
    asin = product.get("asin")
    if not asin:
        return
    marketplace = _marketplace_from_url(product.get("amazon_url") or "")
    try:
        scraped = await amazon.scrape_async(asin, marketplace)
    except Exception as e:
        log.warning("Scrape failed asin=%s err=%s", asin, e)
        return
    if not scraped:
        return

    new_price = scraped.get("price")
    new_stock = scraped.get("stock_status")
    old_price = float(product.get("amazon_price") or 0)
    old_stock = product.get("stock_status")

    log_row = {
        "product_id": product["id"],
        "old_price": old_price,
        "new_price": new_price,
        "stock_change": None,
    }

    update = {"last_checked_at": datetime.now(timezone.utc).isoformat()}

    # Stock change: in -> out
    if old_stock == "in_stock" and new_stock == "out_of_stock":
        try:
            if product.get("ebay_listing_id"):
                ebay_api.end_listing(product["user_id"], product["ebay_listing_id"])
        except Exception as e:
            log.warning("end_listing failed: %s", e)
        update["stock_status"] = "out_of_stock"
        log_row["stock_change"] = "in_to_out"

    # Stock change: out -> in (re-list)
    elif old_stock == "out_of_stock" and new_stock == "in_stock":
        try:
            new_listing = ebay_api.create_listing(
                product["user_id"],
                {
                    "asin": asin,
                    "title": product["title"],
                    "price": new_price or old_price,
                    "currency": "USD",
                    "images": product.get("images") or [],
                    "description": product.get("description") or product["title"],
                    "brand": product.get("brand") or "Unbranded",
                },
            )
            update.update({
                "ebay_listing_id": new_listing["ebay_listing_id"],
                "ebay_listing_url": new_listing["ebay_listing_url"],
                "ebay_price": new_listing["ebay_price"],
                "stock_status": "in_stock",
            })
        except Exception as e:
            log.warning("re-list failed: %s", e)
        log_row["stock_change"] = "out_to_in"

    # Price change
    if (
        new_price is not None
        and abs(new_price - old_price) >= 0.01
        and new_stock == "in_stock"
        and product.get("ebay_listing_id")
    ):
        from .database import settings
        new_ebay_price = round(new_price * (1 + settings.DEFAULT_MARKUP_PERCENT / 100.0), 2)
        try:
            ebay_api.update_listing_price(
                product["user_id"], product["ebay_listing_id"], new_ebay_price
            )
            update["amazon_price"] = new_price
            update["ebay_price"] = new_ebay_price
            update["profit_margin"] = round(new_ebay_price - new_price, 2)
        except Exception as e:
            log.warning("price update failed: %s", e)

    db.table("products").update(update).eq("id", product["id"]).execute()
    if log_row["stock_change"] or (new_price is not None and new_price != old_price):
        db.table("monitoring_logs").insert(log_row).execute()


async def monitor_all_products() -> None:
    db = admin_client()
    res = (
        db.table("products")
        .select("*")
        .eq("monitor_status", "active")
        .execute()
    )
    products = res.data or []
    log.info("Monitor pass: %d products", len(products))
    for i in range(0, len(products), BATCH_SIZE):
        batch = products[i : i + BATCH_SIZE]
        for p in batch:
            await _check_one(p)
            await asyncio.sleep(random.uniform(2.0, 5.0))


# ---------------------------------------------------------------
# Tracking sync
# ---------------------------------------------------------------
async def sync_tracking() -> None:
    from . import orders as orders_mod
    db = admin_client()
    res = (
        db.table("orders")
        .select("*")
        .eq("status", "fulfilled")
        .not_.is_("amazon_order_id", "null")
        .execute()
    )
    rows = res.data or []
    log.info("Tracking sync: %d orders", len(rows))
    for o in rows:
        try:
            await orders_mod.get_tracking_async(o["id"])
        except Exception as e:
            log.warning("tracking sync failed for %s: %s", o.get("ebay_order_id"), e)
        await asyncio.sleep(random.uniform(2.0, 5.0))
