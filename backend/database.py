"""Supabase client + small helpers used across the backend."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


class Settings:
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    EBAY_CLIENT_ID: str = os.getenv("EBAY_CLIENT_ID", "")
    EBAY_CLIENT_SECRET: str = os.getenv("EBAY_CLIENT_SECRET", "")
    EBAY_RUNAME: str = os.getenv("EBAY_RUNAME", "")
    EBAY_ENV: str = os.getenv("EBAY_ENV", "production")

    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")
    BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000")

    AMAZON_EMAIL: str = os.getenv("AMAZON_EMAIL", "")
    AMAZON_PASSWORD: str = os.getenv("AMAZON_PASSWORD", "")

    DEFAULT_MARKUP_PERCENT: float = float(os.getenv("DEFAULT_MARKUP_PERCENT", "30"))


settings = Settings()


@lru_cache(maxsize=1)
def admin_client() -> Client:
    """Service-role client. Bypasses RLS — use only for trusted server logic."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Supabase service role credentials not configured")
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def user_client(access_token: str) -> Client:
    """Per-request client scoped to a user's JWT (respects RLS)."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
        raise RuntimeError("Supabase anon credentials not configured")
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    client.postgrest.auth(access_token)
    return client


def verify_token(access_token: str) -> Optional[dict]:
    """Verify a JWT against Supabase Auth and return the user payload."""
    try:
        sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
        res = sb.auth.get_user(access_token)
        if res and res.user:
            return {
                "id": res.user.id,
                "email": res.user.email,
                "user_metadata": res.user.user_metadata or {},
            }
    except Exception:
        return None
    return None
