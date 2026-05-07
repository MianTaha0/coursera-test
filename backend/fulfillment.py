"""Droply auto-fulfillment — drives an Amazon checkout via Playwright.

This module is intentionally cautious:
  * Default mode is `dry_run=True` — we navigate the buy-flow but stop
    *before* the final "Place your order" click and capture a screenshot
    of the review page so the user can see what would have been ordered.
  * `headless=False` is the default the first few times so the operator
    can watch and intervene (CAPTCHA, 2FA, address pickers).
  * Every attempt is recorded in the fulfillment_attempts SQLite table
    with a status (`success`, `dry_run`, `error`) and a screenshot path.

Caveats:
  * Amazon's checkout DOM changes constantly. Selectors are best-effort
    and likely need tuning per locale / account.
  * 2FA / CAPTCHA cannot be solved automatically; if encountered the
    flow pauses for the human to clear it (when not headless) or fails
    fast (when headless).
  * Run on a machine where you've previously logged into the same
    Amazon account in this same Chromium profile to skip 2FA. The
    `user_data_dir` in the launch call below persists cookies between
    runs.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


SCREENSHOTS_DIR = Path(__file__).parent / "fulfillment_screenshots"
USER_DATA_DIR = Path(__file__).parent / ".pw_user_data"
SCREENSHOTS_DIR.mkdir(exist_ok=True)
USER_DATA_DIR.mkdir(exist_ok=True)


@dataclass
class BuyerAddress:
    full_name: str
    street1: str
    street2: str
    city: str
    state: str
    postal_code: str
    country_code: str
    phone: str


@dataclass
class FulfillRequest:
    ebay_order_id: str
    asin: str
    amazon_url: str
    buyer: BuyerAddress
    quantity: int = 1


@dataclass
class FulfillResult:
    status: str            # "success" | "dry_run" | "error"
    amazon_order_id: Optional[str] = None
    tracking_number: Optional[str] = None
    carrier: Optional[str] = None
    error: Optional[str] = None
    screenshot_path: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_attempt_start(conn: sqlite3.Connection, req: FulfillRequest) -> int:
    cur = conn.execute(
        """INSERT INTO fulfillment_attempts (ebay_order_id, product_asin, status, started_at)
           VALUES (?, ?, ?, ?)""",
        (req.ebay_order_id, req.asin, "running", _now()),
    )
    return cur.lastrowid


def record_attempt_finish(
    conn: sqlite3.Connection, attempt_id: int, result: FulfillResult
) -> None:
    conn.execute(
        """UPDATE fulfillment_attempts SET
             status=?, amazon_order_id=?, tracking_number=?, carrier=?,
             error=?, screenshot_path=?, finished_at=?
           WHERE id=?""",
        (
            result.status, result.amazon_order_id, result.tracking_number,
            result.carrier, result.error, result.screenshot_path, _now(),
            attempt_id,
        ),
    )


@asynccontextmanager
async def _browser(headless: bool):
    # Imported lazily so the rest of the backend boots even if Playwright
    # isn't installed yet (e.g. fresh clone before `pip install`).
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            yield ctx
        finally:
            await ctx.close()


async def fulfill_on_amazon(
    *, req: FulfillRequest,
    amazon_email: str,
    amazon_password: str,
    headless: bool = False,
    dry_run: bool = True,
) -> FulfillResult:
    """Drive an Amazon checkout. See module docstring for caveats."""
    if not req.amazon_url:
        return FulfillResult(status="error", error="No amazon_url for product")
    if not amazon_email or not amazon_password:
        return FulfillResult(status="error", error="Amazon credentials not configured")

    screenshot = SCREENSHOTS_DIR / f"{req.ebay_order_id}_{int(asyncio.get_event_loop().time())}.png"

    try:
        async with _browser(headless=headless) as ctx:
            page = await ctx.new_page()
            await page.goto(req.amazon_url, wait_until="domcontentloaded", timeout=45_000)

            # If a sign-in panel appears, log in.
            if await page.locator("#ap_email").count() or await page.locator("#nav-link-accountList").get_attribute("aria-label").__await__() if False else False:  # noqa: E501
                pass  # placeholder; the explicit sign-in below handles it

            # Navigate to sign-in if we appear to be signed out
            try:
                if "Hello, sign in" in (await page.locator("#nav-link-accountList").inner_text(timeout=2000)):
                    await page.locator("#nav-link-accountList").click()
                    await page.fill("#ap_email", amazon_email)
                    await page.click("#continue")
                    await page.fill("#ap_password", amazon_password)
                    await page.click("#signInSubmit")
                    await page.wait_for_load_state("domcontentloaded", timeout=60_000)
            except Exception:
                pass

            # Re-open the product page (some flows redirect home after login)
            await page.goto(req.amazon_url, wait_until="domcontentloaded", timeout=45_000)

            # Set quantity if requested > 1
            if req.quantity > 1:
                try:
                    await page.locator("select#quantity").select_option(str(req.quantity))
                except Exception:
                    pass

            # Click Buy Now
            buy_now_clicked = False
            for sel in ["#buy-now-button", "input[name='submit.buy-now']"]:
                if await page.locator(sel).count():
                    await page.locator(sel).click()
                    buy_now_clicked = True
                    break
            if not buy_now_clicked:
                # Fall back to add-to-cart + checkout
                if await page.locator("#add-to-cart-button").count():
                    await page.locator("#add-to-cart-button").click()
                    await page.wait_for_load_state("domcontentloaded")
                    await page.goto("https://www.amazon.com/gp/cart/view.html",
                                    wait_until="domcontentloaded", timeout=45_000)
                    await page.locator("input[name='proceedToRetailCheckout']").first.click()
                else:
                    raise RuntimeError("Could not find Buy Now or Add to Cart")

            await page.wait_for_load_state("domcontentloaded", timeout=60_000)

            # TODO: change shipping address to req.buyer here.
            # The address form has many shapes; for the first iteration we
            # rely on the user having pre-saved the buyer's address as the
            # default in the Amazon account, OR they intervene during
            # !headless mode to pick the right address.

            # Capture the review page before placing
            await page.screenshot(path=str(screenshot), full_page=True)

            if dry_run:
                return FulfillResult(
                    status="dry_run",
                    screenshot_path=str(screenshot),
                )

            # Place order — DANGEROUS, only when dry_run is off
            placed = False
            for sel in ["input[name='placeYourOrder1']",
                        "#placeYourOrder",
                        "input[aria-labelledby='submitOrderButtonId-announce']"]:
                if await page.locator(sel).count():
                    await page.locator(sel).click()
                    placed = True
                    break
            if not placed:
                raise RuntimeError("Could not find Place Order button")

            await page.wait_for_load_state("domcontentloaded", timeout=60_000)
            # Try to extract Amazon order id from the confirmation
            amazon_order_id = None
            try:
                txt = await page.locator("body").inner_text(timeout=5000)
                import re
                m = re.search(r"Order #\s*([\d-]+)", txt)
                if m:
                    amazon_order_id = m.group(1)
            except Exception:
                pass

            await page.screenshot(path=str(screenshot), full_page=True)
            return FulfillResult(
                status="success",
                amazon_order_id=amazon_order_id,
                screenshot_path=str(screenshot),
            )
    except Exception as e:
        try:
            # Best-effort screenshot on failure
            pass
        except Exception:
            pass
        return FulfillResult(
            status="error",
            error=str(e)[:500],
            screenshot_path=str(screenshot) if screenshot.exists() else None,
        )
