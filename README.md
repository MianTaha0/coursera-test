# Droply — Self-hosted Amazon → eBay product workspace

A Droopify-style web dashboard plus a Chrome extension. Save Amazon products
in one click; the extension syncs them to a local SQLite-backed dashboard so
you can browse, search, and export your library on the web.

> Stage 2 milestone: the eBay listing automation, price monitor, auto-fulfill
> and buyer messaging are scaffolded but currently disabled. The current build
> is fully self-contained: no Supabase, no eBay credentials, no login.

---

## Stack

| Layer            | Tech                                            |
| ---------------- | ----------------------------------------------- |
| Backend API      | Python 3.11 · FastAPI · SQLite (stdlib)         |
| Frontend         | Next.js 14 · TypeScript · Tailwind · Recharts   |
| Chrome extension | Manifest V3 · plain JavaScript                  |

```
your-app/
├─ backend/        FastAPI + SQLite (1 file: main.py)
├─ frontend/       Next.js dashboard
├─ extension/      Chrome MV3 extension (drop-in zip)
└─ README.md
```

---

## 1 · Run the backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

The SQLite DB is created automatically at `backend/droply.db`.

Sanity check:

```bash
curl http://localhost:8000/health        # {"status":"healthy"}
curl http://localhost:8000/api/stats     # zeros + 14-day series
```

---

## 2 · Run the dashboard

```bash
cd frontend
cp .env.example .env.local       # default points at localhost:8000
npm install
npm run dev
```

Open <http://localhost:3000>. You'll land on **/dashboard**.

Pages:

- **/dashboard** — 4 stat cards, 14-day imports bar chart, top brands, recent imports.
- **/products** — searchable + sortable table of every synced product.
- **/orders** — placeholder for the eBay milestone.
- **/settings** — backend status + extension download instructions.

---

## 3 · Install the Chrome extension

1. Download <https://github.com/MianTaha0/coursera-test/raw/claude/droopify-clone-4wssG/extension/droply-extension.zip>
   (or use the **Download extension (.zip)** button on the Settings page).
2. Unzip it.
3. Open `chrome://extensions` → enable **Developer mode** → **Load unpacked** → pick the unzipped folder.
4. Click the Droply icon in the toolbar → expand **Backend URL** → enter
   `http://localhost:8000` (or wherever your backend is) → **Save**.
5. Visit any Amazon product page (US/UK/DE/FR/IT/ES) — a green
   **Save product (Droply)** button appears in the buy box.
6. Click it. The button shows `Saved — N in library · synced` if the dashboard
   received it; `· local only` if the backend was unreachable (the data is
   still safe in `chrome.storage.local` and will be visible in the
   extension's **Library** view).

The extension also exposes its own full-tab view at
`chrome-extension://<id>/library.html` (open from the popup → **Open library**).

---

## What's running

| Component             | Port              | What it does                                            |
| --------------------- | ----------------- | ------------------------------------------------------- |
| FastAPI backend       | 8000              | SQLite-backed API: products, stats, orders              |
| Next.js dashboard     | 3000              | Reads from backend; no auth                             |
| Chrome extension      | n/a (in browser)  | Scrapes Amazon, saves locally + POSTs to backend        |

---

## API quick-reference

| Method | Path                       | Description                              |
| ------ | -------------------------- | ---------------------------------------- |
| GET    | `/health`                  | Liveness probe                           |
| GET    | `/api/stats`               | Aggregates for the dashboard             |
| GET    | `/api/products?q=foo`      | List (optionally filtered)               |
| GET    | `/api/products/{asin}`     | Single product                           |
| POST   | `/api/products`            | Upsert one product (called by extension) |
| POST   | `/api/products/bulk`       | Upsert many                              |
| DELETE | `/api/products/{asin}`     | Remove one                               |
| DELETE | `/api/products`            | Clear all                                |
| GET    | `/api/orders`              | Orders list (empty until eBay flow lands)|

---

## Roadmap (next milestones)

1. **List on eBay (URL-prefill)** — per-product button that opens eBay's *Sell similar* flow with the title/price filled in. No credentials needed.
2. **eBay API publish** — one-click goes live via the Inventory API.
3. **Price + stock monitor** — re-scrape saved ASINs periodically; alert / re-price.
4. **Auto-fulfillment** — Playwright Amazon checkout when an eBay order arrives.
5. **Buyer messages** — confirmation / shipping / delivery / feedback templates.

The original Supabase-backed multi-tenant version is preserved in git history at
commit `6f9d861` and earlier.
