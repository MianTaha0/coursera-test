# Droply — Project Status

Last updated: 2026-05-20.

## What this is

**Droply** is a Droopify-style Amazon/AliExpress → eBay dropshipping tool. Three components:

| Layer | Stack | Location |
|---|---|---|
| Backend | FastAPI · SQLite · APScheduler · Playwright | `backend/` |
| Frontend | Next.js 14 · TypeScript · Tailwind · recharts | `frontend/` |
| Chrome extension | Manifest V3 · vanilla JS | `extension/` |

## Branches

| Branch | Purpose |
|---|---|
| [`droply-development`](https://github.com/MianTaha0/coursera-test/tree/droply-development) | **Active work — all Phase 1–5 commits live here.** Cut from `droply-base`. |
| `droply-base` | The original Droopify-clone work that predates this session's improvements. |
| `main` | Repo default — older background-remover code. Not used for Droply. |

## Sub-phases shipped (19 commits)

| Phase | Title | Commit |
|---|---|---|
| 1.1 | EasyPost carrier tracking | [`e1d0108`](https://github.com/MianTaha0/coursera-test/commit/e1d0108) |
| 1.2 | eBay buyer-message auto-send (Trading API) | [`b3129fb`](https://github.com/MianTaha0/coursera-test/commit/b3129fb) |
| 1.3 | APScheduler in-process | [`6b12153`](https://github.com/MianTaha0/coursera-test/commit/6b12153) |
| 1.4 | Chrome extension polish (icons, retry queue, ASIN regex, minimized recheck) | [`b59c49a`](https://github.com/MianTaha0/coursera-test/commit/b59c49a) |
| 2.1 | Smart eBay category detection via Taxonomy API | [`42ef1a9`](https://github.com/MianTaha0/coursera-test/commit/42ef1a9) |
| 2.2 | Real item specifics (aspects) on every eBay listing | [`c99d744`](https://github.com/MianTaha0/coursera-test/commit/c99d744) |
| — | Ignore tsbuildinfo | [`1d42dc9`](https://github.com/MianTaha0/coursera-test/commit/1d42dc9) |
| 2.4 | Inventory sync (Amazon OOS → eBay pause) | [`7357eb0`](https://github.com/MianTaha0/coursera-test/commit/7357eb0) |
| 2.5 | Per-marketplace publishing (16 eBay sites) | [`9eb5f36`](https://github.com/MianTaha0/coursera-test/commit/9eb5f36) |
| 2.3 | Description templates with variable substitution | [`d97cba8`](https://github.com/MianTaha0/coursera-test/commit/d97cba8) |
| 2.6 | Tiered margin rules by price bracket | [`37e0869`](https://github.com/MianTaha0/coursera-test/commit/37e0869) |
| 4.1 | Inbound buyer-message poll (Trading GetMyMessages) | [`4e76543`](https://github.com/MianTaha0/coursera-test/commit/4e76543) |
| 4.2 | Conversation thread view on Messages page | [`e376fd7`](https://github.com/MianTaha0/coursera-test/commit/e376fd7) |
| 4.3 | Rule-based auto-reply (WISMO, damaged, returns, cancel) | [`a2c04b3`](https://github.com/MianTaha0/coursera-test/commit/a2c04b3) |
| 5.1a | Chrome extension scrapes AliExpress | [`906c873`](https://github.com/MianTaha0/coursera-test/commit/906c873) |
| 5.1c | Playwright AliExpress auto-fulfillment | [`d452b4b`](https://github.com/MianTaha0/coursera-test/commit/d452b4b) |
| 3.1 | Shipping deadline alerts | [`1c71a92`](https://github.com/MianTaha0/coursera-test/commit/1c71a92) |
| 3.4 | Auto-feedback request scheduling | [`d6e3de4`](https://github.com/MianTaha0/coursera-test/commit/d6e3de4) |
| 3.2 | Buyer offers (Best Offer) sync + accept/decline | [`e0179d8`](https://github.com/MianTaha0/coursera-test/commit/e0179d8) |

## Droopify-parity scorecard

**23 of ~25 features done.** Remaining:

- ❌ **Phase 3.3** — Cancellations / returns / disputes workflow (only ops gap still open)
- ❌ **Phase 5.2 / 5.3** — Winning Products feed / Competitors Scanner (research features)
- ❌ **Phase 10** — iOS/native mobile (likely PWA-first if ever)

Skipped intentionally:
- **Phase 5.1b** (backend AliExpress polish) — turned out to be effectively a no-op; the existing publish flow accepts AliExpress products verbatim.
- **Phase 9 (SaaS-ify — Postgres, Clerk, Stripe, deploy)** — deferred until the product is mature enough to sell. User decided "first finish features, then SaaS."

## How everything runs

### Backend (FastAPI · SQLite)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DROPLY_DB=./droply.db uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

- DB auto-creates on first boot (17 tables, 41 VeRO defaults, 4 message templates, 4 inbound rules, 1 description template seeded).
- Scheduler runs 6 jobs in-process:
  - `message_flush` — every 1 min — sends queued buyer messages via Trading API
  - `inbox_poll` — every 5 min — pulls new buyer messages
  - `order_sync` — every 10 min — pulls new orders from eBay Fulfillment API
  - `best_offer_poll` — every 15 min — pulls active Best Offers + applies auto-rules
  - `tracking_refresh` — every 30 min — re-polls EasyPost for shipped orders
  - `feedback_followup` — every 6 h — queues `feedback_request` template N days post-delivery

### Frontend (Next.js)

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Pages: `/dashboard` · `/products` · `/orders` · `/messages` · `/settings`.

### Chrome extension

Load unpacked from `extension/` (after icons + content scripts are in place) or use the prebuilt `extension/droply-extension.zip`. Supports 6 Amazon TLDs and 8 AliExpress TLDs.

## What's not tested yet (needs your accounts)

| Path | What you need |
|---|---|
| eBay OAuth + Inventory API + Trading API | A sandbox eBay app, connect at `/auth/ebay` |
| Real EasyPost tracking | API key from easypost.com (free 1k trackers/mo) |
| Amazon Playwright auto-checkout | Amazon credentials in Settings → Auto-fulfillment |
| AliExpress Playwright auto-checkout | AliExpress credentials in Settings → AliExpress fulfillment |
| Chrome extension on real Amazon / AliExpress pages | Load extension in Chrome |

Everything else has been smoke-tested with curl + the comprehensive 8-layer stack test (see git log).

## Latent issues found + fixed during this session

1. **Fresh-DB orders table was missing `tracking_status*` columns** — they only existed via the additive migration block, which never ran on a fresh DB. Fixed in commit 1c71a92 (Phase 3.1).
2. **`from fulfillment import` was broken** — only worked if `backend/` was on sys.path, which it isn't under `uvicorn backend.main:app`. Fixed in 5.1c (d452b4b).

## Where to resume

The next logical pieces (in priority order):

1. **Phase 3.3** — Cancellations / returns / disputes workflow (~2 days) — closes the remaining operations gap
2. **Phase 6.3** — Fulfillment hardening (CAPTCHA / 2FA detection + push notification + retry logic, ~1-2 days)
3. **Phase 9** — Start SaaS-ify (Postgres + Clerk + Stripe, ~1 week) — only if ready to charge

Or: **boot the stack + connect a sandbox account** and exercise the full loop end-to-end. Lots of code is untested against real APIs.

## Roadmap source of truth

See `/Users/taha/.claude/plans/understand-it-we-have-sorted-puppy.md` for the full Droopify-parity roadmap (current phase status + future phases not yet picked up).
