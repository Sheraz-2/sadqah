import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Tone = "neutral" | "ok" | "warn" | "bad" | "info";
const tones: Record<Tone, string> = {
  neutral: "bg-lapis-50 text-ink-soft",
  ok: "bg-tile-50 text-tile-700",
  warn: "bg-saffron-100 text-saffron-600",
  bad: "bg-pomegranate-50 text-pomegranate-600",
  info: "bg-lapis-100 text-lapis-700",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-sm font-medium", tones[tone], className)}>{children}</span>;
}
