"use client";

import { useEffect, useMemo, useState } from "react";
import { X, Tag, AlertTriangle, CheckCircle2, Info, Loader2, Wand2 } from "lucide-react";
import { Product } from "@/lib/api";

const MAX_LEN = 80;

type Issue = {
  level: "good" | "warn" | "info";
  message: string;
};

function analyze(title: string, brand?: string | null): { length: number; issues: Issue[] } {
  const issues: Issue[] = [];
  const len = title.length;

  // Length checks
  if (len === 0) {
    issues.push({ level: "warn", message: "Empty title — eBay will reject the listing." });
  } else if (len > MAX_LEN) {
    issues.push({
      level: "warn",
      message: `${len}/${MAX_LEN} — too long. eBay truncates at ${MAX_LEN}.`,
    });
  } else if (len < 40) {
    issues.push({
      level: "warn",
      message: `Only ${len}/${MAX_LEN} chars used. Pack in more keywords for better search ranking.`,
    });
  } else if (len < 60) {
    issues.push({
      level: "info",
      message: `${len}/${MAX_LEN} — okay, but you have room for ~${MAX_LEN - len} more chars of keywords.`,
    });
  } else {
    issues.push({ level: "good", message: `${len}/${MAX_LEN} — strong length.` });
  }

  // Brand
  if (brand) {
    if (title.toLowerCase().includes(brand.toLowerCase())) {
      if (title.toLowerCase().startsWith(brand.toLowerCase())) {
        issues.push({ level: "good", message: `Starts with brand "${brand}" — ideal.` });
      } else {
        issues.push({ level: "info", message: `Brand "${brand}" is in the title.` });
      }
    } else {
      issues.push({ level: "warn", message: `Brand "${brand}" missing from the title.` });
    }
  }

  // ALL CAPS check (only meaningful if there are letters)
  const upper = title.replace(/[^A-Z]/g, "").length;
  const lower = title.replace(/[^a-z]/g, "").length;
  if (upper + lower > 4 && upper / (upper + lower) > 0.5) {
    issues.push({
      level: "warn",
      message: "Mostly uppercase — eBay search penalizes shouty titles.",
    });
  }

  // Excessive punctuation / decoration
  if (/!{2,}|\*{2,}/.test(title)) {
    issues.push({ level: "warn", message: "Repeated !! or ** — looks spammy, hurts ranking." });
  }
  if (/[★✓✦◆●♦☆⭐]/.test(title)) {
    issues.push({
      level: "warn",
      message: "Decorative symbols (★, ✓, etc.) drag down search ranking.",
    });
  }

  // Filler keywords
  const fillers = ["new", "free shipping", "look", "wow", "awesome"];
  const lcText = title.toLowerCase();
  const foundFillers = fillers.filter((w) => new RegExp(`\\b${w}\\b`, "i").test(lcText));
  if (foundFillers.length) {
    issues.push({
      level: "info",
      message: `Filler words detected (${foundFillers.join(", ")}) — replace with concrete specs (size, color, model).`,
    });
  }

  // Forbidden char check (eBay disallows leading/trailing whitespace; keep simple)
  if (title !== title.trim()) {
    issues.push({ level: "warn", message: "Trim whitespace from start/end." });
  }

  // Encourage attributes
  const hasColor = /\b(black|white|red|blue|green|yellow|grey|gray|silver|gold|pink|purple|orange|brown|beige|navy|tan|ivory)\b/i.test(
    title,
  );
  const hasSize = /\b(small|medium|large|xl|xxl|\d+(?:\s*(?:in|inch|cm|mm|ft|m|kg|g|oz|lb|lbs|ml|l|tb|gb)))\b/i.test(
    title,
  );
  if (!hasColor) {
    issues.push({
      level: "info",
      message: "No color mentioned — buyers often filter by color.",
    });
  }
  if (!hasSize) {
    issues.push({
      level: "info",
      message: "No size/spec mentioned — useful for keyword matches.",
    });
  }

  return { length: len, issues };
}

export default function TitleOptimizerModal({
  product,
  onClose,
  onPublish,
  busy,
}: {
  product: Product;
  onClose: () => void;
  onPublish: (title: string) => void;
  busy: boolean;
}) {
  const initial = (product.title || product.asin).slice(0, MAX_LEN);
  const [title, setTitle] = useState(initial);

  useEffect(() => {
    setTitle((product.title || product.asin).slice(0, MAX_LEN));
  }, [product.asin, product.title]);

  const { length, issues } = useMemo(
    () => analyze(title, product.brand),
    [title, product.brand],
  );
  const overLimit = length > MAX_LEN;

  function autoOptimize() {
    // Light pass: trim, collapse spaces, prepend brand if missing, drop decoration
    let t = title.replace(/[★✓✦◆●♦☆⭐]/g, "").replace(/!{2,}/g, "!").replace(/\*{2,}/g, "");
    t = t.replace(/\s+/g, " ").trim();
    if (product.brand && !t.toLowerCase().includes(product.brand.toLowerCase())) {
      t = `${product.brand} ${t}`;
    }
    if (t.length > MAX_LEN) t = t.slice(0, MAX_LEN).replace(/\s\S*$/, ""); // word-safe trim
    setTitle(t);
  }

  const counterColor =
    length === 0 ? "text-muted" : overLimit ? "text-red-400" : length < 40 ? "text-yellow-300" : "text-accent";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-xl rounded-xl border border-border bg-panel p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 rounded p-1 text-muted hover:bg-panel2 hover:text-white"
        >
          <X size={18} />
        </button>

        <div className="flex items-start gap-4">
          {product.images?.[0] && (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={product.images[0]}
              alt=""
              referrerPolicy="no-referrer"
              className="h-12 w-12 rounded border border-border bg-white object-contain"
            />
          )}
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold">Optimize eBay title</h2>
            <p className="text-xs text-muted">
              eBay listing search rewards keyword-dense titles. {product.asin}
            </p>
          </div>
        </div>

        <div className="mt-4">
          <label className="flex items-center justify-between text-xs uppercase text-muted">
            <span>Title</span>
            <span className={`font-mono ${counterColor}`}>{length}/{MAX_LEN}</span>
          </label>
          <textarea
            rows={3}
            value={title}
            onChange={(e) => setTitle(e.target.value.slice(0, MAX_LEN + 50))}
            className={`input mt-1 w-full font-mono text-sm ${
              overLimit ? "border-red-500/60" : ""
            }`}
            spellCheck
          />
          <button
            onClick={autoOptimize}
            className="mt-2 btn-secondary text-xs"
            type="button"
          >
            <Wand2 size={12} /> Auto-optimize
          </button>
        </div>

        <ul className="mt-4 space-y-1.5 text-xs">
          {issues.map((iss, i) => (
            <li
              key={i}
              className={`flex items-start gap-2 ${
                iss.level === "warn"
                  ? "text-yellow-300"
                  : iss.level === "good"
                  ? "text-accent"
                  : "text-muted"
              }`}
            >
              {iss.level === "warn" ? (
                <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              ) : iss.level === "good" ? (
                <CheckCircle2 size={12} className="mt-0.5 shrink-0" />
              ) : (
                <Info size={12} className="mt-0.5 shrink-0" />
              )}
              <span>{iss.message}</span>
            </li>
          ))}
        </ul>

        <div className="mt-6 flex justify-end gap-2">
          <button onClick={onClose} className="btn-secondary text-sm">
            Cancel
          </button>
          <button
            onClick={() => onPublish(title.trim().slice(0, MAX_LEN))}
            disabled={busy || length === 0}
            className="btn-primary text-sm"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Tag size={14} />}
            Publish to eBay
          </button>
        </div>
      </div>
    </div>
  );
}
