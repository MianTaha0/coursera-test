"use client";

import type { LucideIcon } from "lucide-react";

export default function StatsCard({
  label,
  value,
  icon: Icon,
  hint,
}: {
  label: string;
  value: string | number;
  icon?: LucideIcon;
  hint?: string;
}) {
  return (
    <div className="card flex items-start gap-4">
      {Icon && (
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent/15 text-accent">
          <Icon size={20} />
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="text-xs uppercase tracking-wider text-muted">{label}</div>
        <div className="mt-1 truncate text-2xl font-bold">{value}</div>
        {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
      </div>
    </div>
  );
}
