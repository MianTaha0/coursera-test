-- Droply database schema (Supabase / PostgreSQL)
-- Run in the Supabase SQL editor.

create extension if not exists "uuid-ossp";

-- ---------------------------------------------------------------
-- Users (mirrors auth.users, holds plan + trial info)
-- ---------------------------------------------------------------
create table if not exists public.users (
    id uuid primary key references auth.users(id) on delete cascade,
    email text,
    full_name text,
    plan text not null default 'trial',
    trial_ends_at timestamptz default (now() + interval '14 days'),
    created_at timestamptz default now()
);

-- ---------------------------------------------------------------
-- eBay account connection (OAuth tokens)
-- ---------------------------------------------------------------
create table if not exists public.ebay_accounts (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references public.users(id) on delete cascade,
    ebay_username text,
    access_token text,
    refresh_token text,
    token_expires_at timestamptz,
    connected_at timestamptz default now(),
    unique (user_id)
);

-- ---------------------------------------------------------------
-- Imported products
-- ---------------------------------------------------------------
create table if not exists public.products (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references public.users(id) on delete cascade,
    asin text,
    title text,
    images jsonb default '[]'::jsonb,
    description text,
    brand text,
    amazon_url text,
    amazon_price numeric(10,2),
    ebay_price numeric(10,2),
    profit_margin numeric(10,2),
    ebay_listing_id text,
    ebay_listing_url text,
    stock_status text not null default 'in_stock',
    monitor_status text not null default 'active',
    last_checked_at timestamptz,
    imported_at timestamptz default now()
);

create index if not exists idx_products_user on public.products(user_id);
create index if not exists idx_products_asin on public.products(asin);
create index if not exists idx_products_monitor on public.products(monitor_status);

-- ---------------------------------------------------------------
-- Orders
-- ---------------------------------------------------------------
create table if not exists public.orders (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references public.users(id) on delete cascade,
    ebay_order_id text unique,
    amazon_order_id text,
    product_id uuid references public.products(id) on delete set null,
    buyer_name text,
    buyer_address jsonb,
    sale_price numeric(10,2),
    amazon_cost numeric(10,2),
    profit numeric(10,2),
    status text not null default 'pending', -- pending | fulfilled | shipped | delivered | cancelled
    tracking_number text,
    fulfilled_at timestamptz,
    shipped_at timestamptz,
    delivered_at timestamptz,
    created_at timestamptz default now()
);

create index if not exists idx_orders_user on public.orders(user_id);
create index if not exists idx_orders_status on public.orders(status);
create index if not exists idx_orders_ebay on public.orders(ebay_order_id);

-- ---------------------------------------------------------------
-- Monitoring logs (price + stock checks)
-- ---------------------------------------------------------------
create table if not exists public.monitoring_logs (
    id uuid primary key default uuid_generate_v4(),
    product_id uuid not null references public.products(id) on delete cascade,
    old_price numeric(10,2),
    new_price numeric(10,2),
    stock_change text,
    checked_at timestamptz default now()
);

create index if not exists idx_monitor_product on public.monitoring_logs(product_id);

-- ---------------------------------------------------------------
-- Auto-create public.users row when a new auth user signs up
-- ---------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
    insert into public.users (id, email, full_name)
    values (new.id, new.email, coalesce(new.raw_user_meta_data->>'full_name', ''))
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------
-- Row-level security
-- ---------------------------------------------------------------
alter table public.users           enable row level security;
alter table public.ebay_accounts   enable row level security;
alter table public.products        enable row level security;
alter table public.orders          enable row level security;
alter table public.monitoring_logs enable row level security;

drop policy if exists "users self read"   on public.users;
drop policy if exists "users self update" on public.users;
create policy "users self read"   on public.users for select using (auth.uid() = id);
create policy "users self update" on public.users for update using (auth.uid() = id);

drop policy if exists "ebay accounts owner" on public.ebay_accounts;
create policy "ebay accounts owner" on public.ebay_accounts
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "products owner" on public.products;
create policy "products owner" on public.products
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "orders owner" on public.orders;
create policy "orders owner" on public.orders
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "monitoring logs owner" on public.monitoring_logs;
create policy "monitoring logs owner" on public.monitoring_logs
    for select using (
        exists (
            select 1 from public.products p
            where p.id = monitoring_logs.product_id and p.user_id = auth.uid()
        )
    );
