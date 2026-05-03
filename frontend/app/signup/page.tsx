"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { supabase } from "@/lib/supabase";

export default function SignupPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setInfo(null);
    setBusy(true);
    const { data, error } = await supabase().auth.signUp({
      email,
      password,
      options: { data: { full_name: fullName } },
    });
    setBusy(false);
    if (error) {
      setErr(error.message);
      return;
    }
    if (!data.session) {
      setInfo("Check your email to confirm your account, then log in.");
      return;
    }
    router.replace("/settings");
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-2 text-lg font-bold">
          <span className="inline-block h-3 w-3 rounded-full bg-accent shadow-[0_0_10px_rgba(34,197,94,.6)]" />
          Droply
        </div>
        <div className="card">
          <h1 className="text-xl font-semibold">Create your account</h1>
          <p className="mt-1 text-sm text-muted">14-day free trial. No credit card.</p>
          <form onSubmit={onSubmit} className="mt-5 space-y-3">
            <div>
              <label className="mb-1 block text-xs text-muted">Full name</label>
              <input
                required
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted">Email</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted">Password</label>
              <input
                type="password"
                minLength={8}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input"
              />
            </div>
            {err && (
              <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                {err}
              </div>
            )}
            {info && (
              <div className="rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-sm text-accent">
                {info}
              </div>
            )}
            <button type="submit" disabled={busy} className="btn-primary w-full">
              {busy ? "Creating…" : "Create account"}
            </button>
          </form>
          <div className="mt-4 text-center text-sm text-muted">
            Already have an account?{" "}
            <Link href="/login" className="text-accent hover:underline">
              Log in
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
