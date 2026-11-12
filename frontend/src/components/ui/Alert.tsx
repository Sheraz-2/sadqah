import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Tone = "info" | "ok" | "warn" | "bad";
const tones: Record<Tone, string> = {
  info: "bg-lapis-50 text-lapis-900 ring-lapis-100",
  ok: "bg-tile-50 text-tile-700 ring-tile-500/30",
  warn: "bg-saffron-100 text-ink ring-saffron-400/50",
  bad: "bg-pomegranate-50 text-pomegranate-600 ring-pomegranate-500/30",
};

export function Alert({ tone = "info", title, children, className }: { tone?: Tone; title?: string; children?: ReactNode; className?: string }) {
  return (
    <div role={tone === "bad" ? "alert" : "status"} className={cn("rounded-xl p-4 text-base ring-1 ring-inset", tones[tone], className)}>
      {title && <p className="font-semibold">{title}</p>}
      {children && <div className={title ? "mt-1" : ""}>{children}</div>}
    </div>
  );
}
