"""Amazon scraping helpers (used by the price/stock monitor and the auto-order flow).

The Chrome extension scrapes during product import; this module is the
server-side equivalent for background monitoring + auto-purchasing.
"""
from __future__ import annotations

import asyncio
import random
import re
from contextlib import asynccontextmanager
from typing import Optional

from playwright.async_api import Browser, BrowserContext, async_playwright

try:
    from playwright_stealth import stealth_async  # type: ignore
except Exception:  # pragma: no cover
    stealth_async = None

from .database import settings

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
]


def amazon_url_for(asin: str, marketplace: str = "amazon.com") -> str:
    return f"https://www.{marketplace}/dp/{asin}"


@asynccontextmanager
async def browser_context(headless: bool = True):
    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(headless=headless, args=["--no-sandbox"])
        context: BrowserContext = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1366, "height": 850},
            locale="en-US",
        )
        try:
            yield context
        finally:
            await context.close()
            await browser.close()


async def _scrape_product_page(page) -> dict:
    if stealth_async:
        try:
            await stealth_async(page)
        except Exception:
            pass

    title = await page.locator("#productTitle").first.text_content() if await page.locator("#productTitle").count() else None

    price = None
    for sel in [
        "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
        "#corePrice_feature_div .a-price .a-offscreen",
        ".a-price .a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
    ]:
        loc = page.locator(sel).first
        if await loc.count():
            try:
                txt = (await loc.text_content()) or ""
                m = re.search(r"[\d.,]+", txt.replace("\xa0", " "))
                if m:
                    s = m.group(0)
                    s = re.sub(r"\.(?=\d{3}\b)", "", s).replace(",", ".")
                    price = float(s)
                    break
            except Exception:
                continue

    avail_txt = ""
    if await page.locator("#availability").count():
        avail_txt = (await page.locator("#availability").first.text_content()) or ""
    stock = "in_stock"
    if re.search(r"out of stock|currently unavailable|non disponibile|nicht verfügbar|no disponible|épuisé",
                 avail_txt, re.I):
        stock = "out_of_stock"

    return {
        "title": (title or "").strip(),
        "price": price,
        "stock_status": stock,
    }


async def scrape_async(asin: str, marketplace: str = "amazon.com") -> Optional[dict]:
    url = amazon_url_for(asin, marketplace)
    async with browser_context(headless=True) as ctx:
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await page.wait_for_timeout(random.randint(2_000, 5_000))
            data = await _scrape_product_page(page)
            data["asin"] = asin
            data["amazon_url"] = url
            return data
        finally:
            await page.close()


def scrape(asin: str, marketplace: str = "amazon.com") -> Optional[dict]:
    """Synchronous wrapper around scrape_async."""
    return asyncio.run(scrape_async(asin, marketplace))


async def place_order_async(asin: str, address: dict) -> Optional[str]:
    """Open Amazon, log in, add ASIN to cart, set address, place order.

    Returns the Amazon order ID on success.
    Requires AMAZON_EMAIL/AMAZON_PASSWORD in env. Highly fragile by nature
    (Amazon UI changes; expect to maintain selectors over time).
    """
    if not (settings.AMAZON_EMAIL and settings.AMAZON_PASSWORD):
        raise RuntimeError("AMAZON_EMAIL / AMAZON_PASSWORD not configured")

    async with browser_context(headless=True) as ctx:
        page = await ctx.new_page()
        if stealth_async:
            try:
                await stealth_async(page)
            except Exception:
                pass

        # 1) Login
        await page.goto("https://www.amazon.com/ap/signin", wait_until="domcontentloaded", timeout=45_000)
        await page.fill("#ap_email", settings.AMAZON_EMAIL)
        await page.click("#continue")
        await page.wait_for_selector("#ap_password", timeout=30_000)
        await page.fill("#ap_password", settings.AMAZON_PASSWORD)
        await page.click("#signInSubmit")
        await page.wait_for_load_state("domcontentloaded")

        # 2) Add to cart
        await page.goto(amazon_url_for(asin), wait_until="domcontentloaded", timeout=45_000)
        await page.click("#add-to-cart-button", timeout=20_000)
        await page.wait_for_timeout(2000)

        # 3) Proceed to checkout
        await page.goto("https://www.amazon.com/gp/cart/view.html", wait_until="domcontentloaded")
        await page.click("input[name='proceedToRetailCheckout']", timeout=20_000)
        await page.wait_for_load_state("domcontentloaded")

        # 4) Enter / select shipping address
        try:
            await page.click("text=Add a new address", timeout=8000)
            await page.fill("#address-ui-widgets-enterAddressFullName", address.get("fullName", ""))
            await page.fill("#address-ui-widgets-enterAddressPhoneNumber", address.get("primaryPhone", ""))
            await page.fill("#address-ui-widgets-enterAddressLine1", address.get("addressLine1", ""))
            if address.get("addressLine2"):
                await page.fill("#address-ui-widgets-enterAddressLine2", address["addressLine2"])
            await page.fill("#address-ui-widgets-enterAddressCity", address.get("city", ""))
            await page.select_option("#address-ui-widgets-enterAddressStateOrRegion", address.get("stateOrProvince", ""))
            await page.fill("#address-ui-widgets-enterAddressPostalCode", address.get("postalCode", ""))
            await page.click("input[name='shipToThisAddress']")
        except Exception:
            # Address widget varies by region; fall back to default address.
            pass

        # 5) Place order
        await page.click("input[name='placeYourOrder1']", timeout=30_000)
        await page.wait_for_load_state("domcontentloaded")

        # 6) Capture order id
        try:
            await page.wait_for_url(re.compile(r"thankyou", re.I), timeout=30_000)
        except Exception:
            pass
        body = (await page.content()) or ""
        m = re.search(r"order[# ]?\s*([0-9-]{10,25})", body, re.I)
        return m.group(1) if m else None


def place_order(asin: str, address: dict) -> Optional[str]:
    return asyncio.run(place_order_async(asin, address))


async def get_tracking_async(amazon_order_id: str) -> Optional[str]:
    """Open the Amazon order page and try to extract a tracking number."""
    if not (settings.AMAZON_EMAIL and settings.AMAZON_PASSWORD):
        raise RuntimeError("AMAZON_EMAIL / AMAZON_PASSWORD not configured")
    async with browser_context(headless=True) as ctx:
        page = await ctx.new_page()
        await page.goto("https://www.amazon.com/ap/signin", wait_until="domcontentloaded")
        await page.fill("#ap_email", settings.AMAZON_EMAIL)
        await page.click("#continue")
        await page.wait_for_selector("#ap_password", timeout=30_000)
        await page.fill("#ap_password", settings.AMAZON_PASSWORD)
        await page.click("#signInSubmit")
        await page.wait_for_load_state("domcontentloaded")
        await page.goto(
            f"https://www.amazon.com/gp/your-account/order-details?orderID={amazon_order_id}",
            wait_until="domcontentloaded",
        )
        body = await page.content()
        m = re.search(r"Tracking ID:\s*</span>\s*<span[^>]*>([A-Z0-9]+)", body)
        if m:
            return m.group(1)
        m = re.search(r"trackingId=([A-Z0-9]+)", body)
        return m.group(1) if m else None


def get_tracking(amazon_order_id: str) -> Optional[str]:
    return asyncio.run(get_tracking_async(amazon_order_id))
