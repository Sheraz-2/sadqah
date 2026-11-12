import { cn } from "@/lib/cn";

/** Honest progress: the number is the fill; colour changes only when the goal is met. */
export function ProgressBar({ percent, label, className }: { percent: number; label?: string; className?: string }) {
  const p = Math.max(0, Math.min(100, Math.round(percent)));
  return (
    <div
      role="progressbar"
      aria-valuenow={p}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ?? "Funding progress"}
      className={cn("h-3 w-full overflow-hidden rounded-full bg-lapis-100", className)}
    >
      <div
        className={cn("h-full rounded-full transition-[width] duration-700", p >= 100 ? "bg-tile-500" : "bg-lapis-500")}
        style={{ width: `${p}%` }}
      />
    </div>
  );
}
