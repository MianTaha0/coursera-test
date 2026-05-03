export function money(n: number | null | undefined, currency = "USD"): string {
  if (n === null || n === undefined || isNaN(Number(n))) return "—";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(Number(n));
  } catch {
    return `$${Number(n).toFixed(2)}`;
  }
}

export function percent(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${Number(n).toFixed(1)}%`;
}

export function date(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
