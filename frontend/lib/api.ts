"use client";

import { supabase } from "./supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function authHeader(): Promise<HeadersInit> {
  const { data } = await supabase().auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function api<T = any>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = {
    "Content-Type": "application/json",
    ...(await authHeader()),
    ...(init.headers || {}),
  };
  const res = await fetch(`${API}${path}`, { ...init, headers });
  const text = await res.text();
  const json = text ? JSON.parse(text) : {};
  if (!res.ok) {
    throw new Error(json.detail || json.error || `HTTP ${res.status}`);
  }
  return json as T;
}

export const API_URL = API;
