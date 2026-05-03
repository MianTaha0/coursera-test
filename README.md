# Droply — eBay Dropshipping Automation

A full-stack clone of [Droopify](https://www.droopify.co/en):
import Amazon products to eBay in one click, automatically monitor price and
stock, auto-fulfill orders from Amazon, and message buyers throughout the order
lifecycle.

## Stack

| Layer            | Tech                                                       |
| ---------------- | ---------------------------------------------------------- |
| Backend API      | Python 3.11 · FastAPI · APScheduler · Playwright (stealth) |
| Database + Auth  | Supabase (PostgreSQL + Auth + Realtime + RLS)              |
| Frontend         | Next.js 14 (App Router) · TypeScript · Tailwind · Recharts |
| Chrome extension | Manifest V3 · plain JavaScript                             |
| eBay             | eBay REST APIs (Inventory, Fulfillment, Account)           |
| Amazon           | Chrome extension scrapes the page DOM directly             |

```
your-app/
├─ backend/        FastAPI app (eBay, monitor, fulfillment, messages)
├─ frontend/       Next.js dashboard
├─ extension/      Chrome MV3 extension
└─ database/       schema.sql for Supabase
```

---

## 1. Create the Supabase project (5 min)

1. Go to [supabase.com](https://supabase.com), click **New project**, set a strong DB password.
2. Once provisioned, open **Project Settings → API** and copy:
   - `Project URL` → `SUPABASE_URL`
   - `anon public` key → `SUPABASE_ANON_KEY`
   - `service_role` key → `SUPABASE_SERVICE_ROLE_KEY` (keep secret)
3. Open the **SQL editor** and paste the contents of `database/schema.sql`. Click **Run**.
   - This creates the `users`, `ebay_accounts`, `products`, `orders`, and
     `monitoring_logs` tables, the `handle_new_user` trigger, and all RLS policies.
4. Open **Authentication → Providers → Email** and:
   - Disable "Confirm email" while testing (optional), or keep it on for production.

---

## 2. Create an eBay developer app (5 min)

1. Sign up at <https://developer.ebay.com> and create a Production keyset.
2. From **Application Keys** copy:
   - `App ID (Client ID)` → `EBAY_CLIENT_ID`
   - `Cert ID (Client Secret)` → `EBAY_CLIENT_SECRET`
3. Go to **User Tokens → Get a User Token → Add eBay Redirect URL (RuName)**.
   - Set the *Auth accepted URL* to `https://YOUR_BACKEND/api/ebay/oauth/callback`
   - Set the *Auth declined URL* to the same (or your settings page)
   - Save and copy the RuName → `EBAY_RUNAME`
4. Make sure your eBay seller account has **Business Policies** for fulfillment,
   payment, and returns (eBay → Account settings → Business policies). Droply uses
   the first policy of each kind for new listings.
5. (Optional) For account-deletion notifications set
   `EBAY_VERIFICATION_TOKEN` to any string ≥ 32 chars and configure the same value
   in your eBay developer notifications panel pointing at `/api/ebay/webhook`.

---

## 3. Run the backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium     # for the price monitor + auto-order

cp .env.example .env            # then fill in the values from steps 1 + 2
# Required:
#   SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY
#   EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EBAY_RUNAME
# Optional (only needed for auto-fulfill):
#   AMAZON_EMAIL, AMAZON_PASSWORD

uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Visit <http://localhost:8000/health> — you should see `{"status":"healthy"}`.

The APScheduler price monitor + tracking sync start automatically (every 4h /
6h respectively).

---

## 4. Run the frontend

```bash
cd frontend
cp .env.example .env.local
# Fill in:
#   NEXT_PUBLIC_SUPABASE_URL=...        (same Project URL)
#   NEXT_PUBLIC_SUPABASE_ANON_KEY=...   (same anon key)
#   NEXT_PUBLIC_API_URL=http://localhost:8000

npm install
npm run dev
```

Open <http://localhost:3000>. You'll be redirected to **Login**. Click
**Sign up**, create an account, then connect your eBay store from **Settings**.

---

## 5. Install the Chrome extension

1. Open `chrome://extensions` and toggle **Developer mode** on.
2. Click **Load unpacked** and select the `extension/` folder.
3. The extension reads its API + app URL from the top of `extension/content.js`
   and `extension/popup.js`. Update both `API_URL` and `APP_URL` if you're not
   running everything on localhost (e.g. set them to your deployed URLs).
4. Sign in to the dashboard once — the extension reads your Supabase token from
   `chrome.storage.local`. To populate it the first time, open the extension's
   *background page* console and run:

   ```js
   chrome.storage.local.set({ droply_token: '<paste your Supabase access token here>' })
   ```

   You can copy the token from DevTools → Application → Local Storage on the
   dashboard tab (key `sb-<project>-auth-token` → `access_token`).
5. Visit any Amazon product page (e.g. `amazon.com/dp/B0CHX1W1XY`) — a green
   **Import to eBay** button appears in the buy box. One click sends the data
   to `POST /api/import-product`, which:
   - validates your Supabase JWT,
   - publishes a fixed-price eBay offer using your business policies,
   - saves the product to Supabase.

---

## 6. What's running automatically

| Job                  | Where                  | Frequency | What it does                                                                     |
| -------------------- | ---------------------- | --------- | -------------------------------------------------------------------------------- |
| Price + stock sync   | `backend/monitor.py`   | every 4h  | Re-scrapes each active product on Amazon and reconciles eBay listing             |
| Tracking sync        | `backend/monitor.py`   | every 6h  | Pulls tracking from Amazon order pages and pushes to eBay                        |
| Order webhook        | `POST /api/ebay/webhook` | on demand | Saves new eBay orders + triggers `auto_fulfill_order` (Playwright Amazon checkout) |
| Buyer messages       | `backend/messages.py`  | on event  | Sends confirmation / shipping / delivery / feedback messages via the eBay API   |

To trigger anything manually for testing:

```bash
# Force one full monitor pass
curl -X POST http://localhost:8000/api/ebay/orders/sync \
     -H "Authorization: Bearer $YOUR_SUPABASE_JWT"

# Force fulfillment of a single Droply order id
curl -X POST http://localhost:8000/api/orders/<order_uuid>/fulfill \
     -H "Authorization: Bearer $YOUR_SUPABASE_JWT"

# Force a buyer message
curl -X POST http://localhost:8000/api/messages/<order_uuid>/confirmation \
     -H "Authorization: Bearer $YOUR_SUPABASE_JWT"
```

---

## 7. Deploying for real

| Component       | Recommended host                                           |
| --------------- | ---------------------------------------------------------- |
| Frontend        | Vercel — set the same three `NEXT_PUBLIC_*` env vars        |
| Backend         | Fly.io / Render / Railway — needs Chromium for Playwright   |
| Supabase        | Hosted (already done)                                       |
| Chrome extension| Pack via `chrome://extensions → Pack extension` and host    |

When you deploy:

1. Update `extension/content.js` and `extension/popup.js` to point `API_URL`
   and `APP_URL` at your deployed URLs, then rezip and re-upload.
2. Update the eBay RuName so its accepted URL matches your deployed
   `/api/ebay/oauth/callback`.
3. Update Supabase **Auth → URL Configuration** with your production site URL.
4. Tighten CORS in `backend/main.py` to your frontend domain only.

---

## File map

```
backend/
  main.py           FastAPI app + auth dep + extension endpoints + OAuth + webhook
  database.py       Supabase clients (admin + per-user) + token verification
  ebay.py           OAuth, refresh, create/update/end listing, send_message, get_orders, add_tracking
  amazon.py         Playwright scraper, place_order, get_tracking
  monitor.py        APScheduler jobs (price/stock + tracking)
  orders.py         eBay webhook handler, auto_fulfill_order, get_tracking
  messages.py       Buyer message templates + senders + dispatcher

frontend/
  app/
    layout.tsx              Root HTML + globals
    page.tsx                Redirects to /login
    login/page.tsx
    signup/page.tsx
    (app)/                  Auth-protected route group
      layout.tsx            Sidebar + auth gate
      dashboard/page.tsx    Stats, chart, recent orders + imports
      products/page.tsx     Searchable products table
      orders/page.tsx       Status-filterable orders table
      settings/page.tsx     eBay connect/disconnect, extension download
  components/
    Sidebar.tsx
    StatsCard.tsx
    ProductsTable.tsx
    OrdersTable.tsx
  lib/
    supabase.ts             Browser client
    api.ts                  Authed fetch helper for the FastAPI backend
    format.ts               money / percent / date

extension/
  manifest.json   MV3 manifest, content script + action popup
  content.js      Scrapes Amazon product page + injects "Import to eBay" button
  popup.html      Login state + counters + dashboard link
  popup.js        Reads chrome.storage.local + refreshes connected eBay info

database/
  schema.sql      Tables, indexes, trigger, RLS policies
```

---

## Notes & caveats

- **eBay business policies** must exist on your seller account before
  `create_listing` will succeed. Create one of each (fulfillment, payment,
  return) in eBay seller hub.
- **Categories.** `create_listing` uses category `139973` (Everything Else →
  Other) by default — you'll want a smarter category lookup for production
  (eBay `getCategorySuggestions`).
- **Amazon scraping & auto-purchase.** Amazon actively blocks bots; the
  Playwright flows include random user agents + delays + stealth, but you
  should expect to maintain selectors and use residential proxies for serious
  volume. Auto-purchase also requires you to log in to a real Amazon account
  and disable 2FA (or implement an OTP capture flow).
- **CORS.** The backend currently allows `*` for ease of local dev — restrict
  it to your dashboard origin in production.
- **Webhook signature verification.** Set `EBAY_VERIFICATION_TOKEN` to enable
  HMAC verification; the same token must be configured in the eBay developer
  notifications panel.
