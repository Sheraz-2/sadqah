export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 py-8 text-ink-soft">
      <span className="size-5 animate-spin rounded-full border-2 border-lapis-500 border-t-transparent" aria-hidden />
      <span>{label}…</span>
    </div>
  );
}
