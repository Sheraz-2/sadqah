import { cn } from "@/lib/cn";

/** Eight-point star, the repeating unit of SadQah's visual language (one star = one verified person helped). */
export function Star({ className, lit = true, title }: { className?: string; lit?: boolean; title?: string }) {
  return (
    <svg viewBox="0 0 72 72" className={cn("block", className)} role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      <path
        d="M36 4l8.2 16.2L62 14.8 56.2 32 70 36l-13.8 4L62 57.2 44.2 51.8 36 68l-8.2-16.2L10 57.2 15.8 40 2 36l13.8-4L10 14.8l17.8 5.4z"
        fill={lit ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth={lit ? 0 : 2.5}
        strokeLinejoin="round"
        opacity={lit ? 1 : 0.35}
      />
    </svg>
  );
}
