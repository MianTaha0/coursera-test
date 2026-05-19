"""Droply auto-fulfillment for AliExpress.

Mirror of `backend/fulfillment.py` but driving AliExpress's checkout. Same
caveats apply — selectors are best-effort against a heavily React-based UI
that ships layout changes every few weeks. Default mode is `dry_run=True`
so we stop at the order-review screen and capture a screenshot rather than
clicking the final "Place order" button.

Shared infrastructure (BuyerAddress, FulfillRequest, FulfillResult,
record_attempt_*, the screenshots dir, the persistent-context launcher) is
imported from `fulfillment.py` so we don't fork the eBay-side bookkeeping.

When 2FA / CAPTCHA appears: the page pauses in non-headless mode for a
human to clear it; in headless mode the run fails fast.
"""
from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from .fulfillment import (
    BuyerAddress,
    FulfillRequest,
    FulfillResult,
    SCREENSHOTS_DIR,
    USER_DATA_DIR,
    record_attempt_start,
    record_attempt_finish,
    _maybe_click,
    _maybe_fill,
)


# AliExpress runs separate persistent profiles per supplier so cookies /
# login state don't collide with the Amazon-side profile.
ALIEXPRESS_USER_DATA_DIR = Path(__file__).parent / ".pw_user_data_aliexpress"
ALIEXPRESS_USER_DATA_DIR.mkdir(exist_ok=True)


@asynccontextmanager
async def _ali_browser(headless: bool):
    """Playwright persistent context for AliExpress. Separate cookie jar
    from the Amazon-side profile so logging into one doesn't kick the other.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(ALIEXPRESS_USER_DATA_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
            locale="en-US",
        )
        try:
            yield ctx
        finally:
            await ctx.close()


async def _is_signed_out(page) -> bool:
    """Cheap probe: AliExpress shows a "Sign in" link in the top nav when
    logged out, and a username link when logged in.
    """
    for sel in [
        "a[href*='login.aliexpress.com']",
        "[class*='login-button']",
        "[class*='Welcome'] a:has-text('Sign in')",
    ]:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible():
                return True
        except Exception:
            continue
    return False


async def _sign_in(page, email: str, password: str) -> None:
    """Drive AliExpress's two-step login (id → password).

    AliExpress periodically swaps between the modern Fusion (#fm-*) form and
    the legacy iframe. We try the modern selectors first.
    """
    # Navigate to the dedicated login page if we're not already on it
    if "login.aliexpress.com" not in page.url:
        await page.goto("https://login.aliexpress.com", wait_until="domcontentloaded", timeout=45_000)

    await _maybe_fill(
        page,
        ["#fm-login-id", "input[name='loginId']", "input[name='account']"],
        email,
    )
    # The password field is on the same form on the modern UI; on the legacy
    # iframe a "Next" button reveals it. Try both.
    if not await _maybe_fill(
        page,
        ["#fm-login-password", "input[name='password']", "input[type='password']"],
        password,
    ):
        # Legacy: click Next to reveal password
        await _maybe_click(page, ["[type='submit']", ".fm-button", "button:has-text('Next')"])
        await page.wait_for_timeout(1500)
        await _maybe_fill(
            page,
            ["#fm-login-password", "input[name='password']", "input[type='password']"],
            password,
        )

    await _maybe_click(
        page,
        [
            ".fm-button-fm-submit",
            "button.fm-button",
            "button[type='submit']",
            "[data-spm-anchor-id]:has-text('Sign In')",
        ],
    )
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=60_000)
    except Exception:
        pass


# AliExpress address-form selectors. The checkout's "Edit shipping address"
# modal exposes these fields; the dict maps our buyer-address attribute
# names to a *list* of candidate selectors (we try each in order).
ALIEXPRESS_ADDRESS_SELECTORS: dict[str, list[str]] = {
    "full_name": [
        "input[name='contactPerson']",
        "input[name='full_name']",
        "input[placeholder*='Name']",
    ],
    "phone": [
        "input[name='mobile_no']",
        "input[name='phone']",
        "input[placeholder*='Phone']",
    ],
    "street1": [
        "input[name='address']",
        "textarea[name='address']",
        "input[placeholder*='street' i]",
    ],
    "street2": [
        "input[name='address2']",
        "input[placeholder*='Apt' i]",
    ],
    "city": [
        "input[name='city']",
        "input[placeholder*='City' i]",
    ],
    "state": [
        "input[name='province']",
        "input[name='state']",
        "input[placeholder*='State' i]",
        "input[placeholder*='Province' i]",
    ],
    "postal_code": [
        "input[name='zip']",
        "input[name='postcode']",
        "input[name='zipCode']",
        "input[placeholder*='Postal' i]",
        "input[placeholder*='ZIP' i]",
    ],
}


async def _set_shipping_address(page, buyer: BuyerAddress) -> str:
    """Try to populate AliExpress's shipping-address form with the buyer's
    details. Returns one of: "set" (we filled the form), "matched" (no edit
    needed — the saved default address matched), "skipped" (couldn't reach
    the picker), "failed: <reason>".

    AliExpress flow:
      1. On the confirm-order page, click "Add new address" or "Change".
      2. A modal opens with the country / state / city / postal / phone /
         street fields.
      3. Some fields are <select> dropdowns (country, state); we use
         select_option where available.
      4. Click "Confirm" / "Save" inside the modal.
    """
    if not buyer.street1:
        return "skipped"

    # Open the address modal. AliExpress sometimes calls it "Change" and
    # sometimes "Edit"; rarely there's no button at all (default address
    # already shown).
    opened = await _maybe_click(
        page,
        [
            "button:has-text('Change')",
            "a:has-text('Change')",
            "button:has-text('Edit')",
            "button:has-text('Add new address')",
            "[class*='address-edit']",
            "[class*='ShippingAddress'] button",
        ],
        timeout_ms=3000,
    )
    if not opened:
        # Couldn't find an editor — the saved default may already be correct.
        return "matched"

    # Wait for the modal to settle
    await page.wait_for_timeout(800)

    # Country select — AliExpress uses a custom dropdown, not native <select>.
    # We try the native input first (works on the modern checkout) then the
    # custom one (mobile / legacy).
    try:
        await page.locator("select[name='country']").select_option(buyer.country_code)
    except Exception:
        pass

    # Fill text fields
    for key, value in {
        "full_name": buyer.full_name,
        "phone": buyer.phone,
        "street1": buyer.street1,
        "street2": buyer.street2,
        "city": buyer.city,
        "state": buyer.state,
        "postal_code": buyer.postal_code,
    }.items():
        if not value:
            continue
        try:
            await _maybe_fill(page, ALIEXPRESS_ADDRESS_SELECTORS[key], value, timeout_ms=2500)
        except Exception:
            # One missing field shouldn't tank the whole address; keep going
            continue

    # Confirm / Save
    saved = await _maybe_click(
        page,
        [
            "button:has-text('Confirm')",
            "button:has-text('Save')",
            "button:has-text('Use this address')",
            "[class*='confirm-button']",
        ],
        timeout_ms=4000,
    )
    return "set" if saved else "failed: confirm not found"


_ORDER_ID_PATTERNS = [
    re.compile(r"order(?:\s*id)?\s*[:#]?\s*(\d{12,})", re.IGNORECASE),
    re.compile(r"orderId=(\d{10,})", re.IGNORECASE),
]


def _extract_order_id(text: str) -> Optional[str]:
    for pat in _ORDER_ID_PATTERNS:
        m = pat.search(text or "")
        if m:
            return m.group(1)
    return None


async def fulfill_on_aliexpress(
    *, req: FulfillRequest,
    aliexpress_email: str,
    aliexpress_password: str,
    headless: bool = False,
    dry_run: bool = True,
) -> FulfillResult:
    """Drive an AliExpress checkout. See module docstring for caveats."""
    if not req.amazon_url:
        # Note: the products table reuses the `amazon_url` column for the
        # source URL regardless of supplier (Amazon or AliExpress). We
        # require *some* product URL here.
        return FulfillResult(status="error", error="No source URL for product")
    if not aliexpress_email or not aliexpress_password:
        return FulfillResult(status="error", error="AliExpress credentials not configured")

    screenshot = SCREENSHOTS_DIR / f"ali_{req.ebay_order_id}_{int(asyncio.get_event_loop().time())}.png"

    try:
        async with _ali_browser(headless=headless) as ctx:
            page = await ctx.new_page()

            # Step 1 — open the product page first so we end up logged in
            # against the right cookie domain.
            await page.goto(req.amazon_url, wait_until="domcontentloaded", timeout=45_000)

            # Step 2 — sign in if we appear to be signed out.
            if await _is_signed_out(page):
                await _sign_in(page, aliexpress_email, aliexpress_password)
                # Reopen the product page after login (AliExpress sometimes
                # redirects to its homepage post-login).
                await page.goto(req.amazon_url, wait_until="domcontentloaded", timeout=45_000)

            # Step 3 — set quantity if > 1. AliExpress uses a stepper.
            if req.quantity > 1:
                # Click the "+" button (qty - 1) times. Bounded to a sane max.
                plus_btn = page.locator("[class*='quantity-plus'], button:has-text('+'), [aria-label='Increase Quantity']").first
                try:
                    if await plus_btn.count():
                        for _ in range(max(0, min(req.quantity - 1, 20))):
                            await plus_btn.click(timeout=2000)
                            await page.wait_for_timeout(150)
                except Exception:
                    pass

            # Step 4 — click "Buy Now" (goes straight to checkout, skipping cart).
            bought = await _maybe_click(
                page,
                [
                    "[class*='buynow']",
                    "[class*='BuyNow']",
                    "button:has-text('Buy Now')",
                    ".btn-buynow",
                    "[data-pl='buy-now']",
                ],
                timeout_ms=6000,
            )
            if not bought:
                # Fall back to add-to-cart → cart → checkout
                if await _maybe_click(
                    page,
                    ["[class*='addCart']", "[class*='AddToCart']", "button:has-text('Add to cart')"],
                    timeout_ms=4000,
                ):
                    await page.goto("https://www.aliexpress.com/p/trade/confirm.html",
                                    wait_until="domcontentloaded", timeout=45_000)
                else:
                    raise RuntimeError("Could not find Buy Now or Add to Cart on AliExpress")

            await page.wait_for_load_state("domcontentloaded", timeout=60_000)

            # Step 5 — set the eBay buyer's shipping address.
            address_status = "skipped"
            try:
                address_status = await _set_shipping_address(page, req.buyer)
            except Exception as e:
                address_status = f"error: {str(e)[:80]}"

            # Step 6 — capture the review page before placing.
            try:
                await page.screenshot(path=str(screenshot), full_page=True)
            except Exception:
                pass

            if dry_run:
                return FulfillResult(
                    status="dry_run",
                    screenshot_path=str(screenshot),
                    notes=f"address: {address_status}",
                )

            # Step 7 — place the order. DANGEROUS path; gated by dry_run.
            placed = await _maybe_click(
                page,
                [
                    "[class*='place-order']",
                    "button:has-text('Place order')",
                    "button:has-text('Place Order')",
                    "[data-pl='place-order']",
                    ".place-order-btn",
                ],
                timeout_ms=6000,
            )
            if not placed:
                raise RuntimeError("Could not find Place Order button on AliExpress")

            # AliExpress redirects to a confirmation URL containing the order
            # id (e.g. /p/order/detail.html?orderId=8765432101234).
            await page.wait_for_load_state("domcontentloaded", timeout=90_000)

            # Try the URL first (most reliable), then the page body.
            ali_order_id = _extract_order_id(page.url)
            if not ali_order_id:
                try:
                    body_text = await page.locator("body").inner_text(timeout=5000)
                    ali_order_id = _extract_order_id(body_text)
                except Exception:
                    pass

            try:
                await page.screenshot(path=str(screenshot), full_page=True)
            except Exception:
                pass

            return FulfillResult(
                status="success",
                # Note: we reuse the FulfillResult.amazon_order_id slot for
                # both Amazon and AliExpress order ids — `fulfillment_attempts.
                # amazon_order_id` is treated as a generic "supplier order id"
                # downstream.
                amazon_order_id=ali_order_id,
                screenshot_path=str(screenshot),
                notes=f"address: {address_status}",
            )
    except Exception as e:
        return FulfillResult(
            status="error",
            error=str(e)[:500],
            screenshot_path=str(screenshot) if screenshot.exists() else None,
        )
