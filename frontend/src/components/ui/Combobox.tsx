"use client";

import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export type ComboOption = {
  value: string;
  label: string;
  /** Small badge on the left, e.g. the ISO code. */
  badge?: string;
  /** Muted text on the right, e.g. the calling code. */
  meta?: string;
  /** Extra words that should also match when searching. */
  keywords?: string;
};

type Props = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly ComboOption[];
  placeholder?: string;
  hint?: string;
  error?: string | null;
  required?: boolean;
  disabled?: boolean;
  className?: string;
  /** Let people keep text that is not in the list (used for province / state). */
  allowCustom?: boolean;
  /** Shown when nothing matches and custom text is not allowed. */
  emptyText?: string;
  /** Options listed first, before anything is typed. */
  featured?: readonly string[];
  /** Heading for the featured group. */
  featuredLabel?: string;
  /** Text for the first "no selection" row, e.g. "All countries". Selecting it sets the value to "". */
  anyLabel?: string;
  autoComplete?: string;
  /** Optional element drawn inside the field on the left (e.g. a calling code). */
  leading?: ReactNode;
};

const MAX_ROWS = 80;

const control =
  "w-full rounded-xl border-0 bg-white py-3 pl-4 pr-20 text-base text-ink ring-1 ring-inset ring-line placeholder:text-ink-soft/60 focus:ring-2 focus:ring-lapis-500 aria-[invalid=true]:ring-2 aria-[invalid=true]:ring-bad disabled:bg-lapis-50 disabled:text-ink-soft";

function norm(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}

function score(o: ComboOption, q: string): number {
  const label = norm(o.label);
  if (label === q) return 0;
  if (label.startsWith(q)) return 1;
  if (norm(o.badge ?? "") === q) return 1;
  if (label.split(/[\s\-/(),]+/).some((w) => w.startsWith(q))) return 2;
  if (label.includes(q)) return 3;
  const hay = norm(`${o.keywords ?? ""} ${o.badge ?? ""} ${o.meta ?? ""}`);
  const words = hay.split(/\s+/);
  if (words.some((w) => w === q)) return 0.5; // a whole nickname such as "uk" or "usa" beats a mere prefix of another name
  if (words.some((w) => w.startsWith(q))) return 4;
  if (hay.includes(q)) return 5;
  return 99;
}

function Highlight({ text, query }: { text: string; query: string }) {
  const q = norm(query);
  if (!q) return <>{text}</>;
  const at = norm(text).indexOf(q);
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <strong className="font-bold text-lapis-900">{text.slice(at, at + q.length)}</strong>
      {text.slice(at + q.length)}
    </>
  );
}

/**
 * Accessible type-ahead select (WAI-ARIA combobox with a listbox popup).
 * Type to filter, use the arrow keys and Enter, or click. With `allowCustom` the typed text itself is kept.
 */
export function Combobox({
  label, value, onChange, options, placeholder, hint, error, required, disabled, className, allowCustom, emptyText = "No match",
  featured, featuredLabel = "Most common", anyLabel, autoComplete = "off", leading,
}: Props) {
  const id = useId();
  const listId = `${id}-list`;
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const selected = useMemo(() => options.find((o) => o.value === value), [options, value]);
  const shown = selected ? selected.label : value; // custom text is shown as typed
  const [query, setQuery] = useState<string | null>(null); // null = not editing
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [fresh, setFresh] = useState(false); // opened on an existing value and nothing typed yet: show every option

  const editing = query !== null;
  const q = fresh ? "" : norm(query ?? "");

  const rows = useMemo(() => {
    const out: Array<ComboOption & { group?: string }> = [];
    if (anyLabel && !q) out.push({ value: "", label: anyLabel });
    if (!q) {
      const set = new Set(featured ?? []);
      const top = (featured ?? []).map((v) => options.find((o) => o.value === v)).filter((o): o is ComboOption => !!o);
      top.forEach((o, i) => out.push({ ...o, group: i === 0 ? featuredLabel : undefined }));
      let first = true;
      for (const o of options) {
        if (set.has(o.value)) continue;
        out.push({ ...o, group: first && top.length ? "All" : undefined });
        first = false;
      }
    } else {
      options
        .map((o) => [score(o, q), o] as const)
        .filter(([s]) => s < 99)
        .sort((a, b) => a[0] - b[0] || a[1].label.localeCompare(b[1].label))
        .forEach(([, o]) => out.push(o));
    }
    return out;
  }, [options, q, anyLabel, featured, featuredLabel]);

  const custom = allowCustom && !fresh && !!query && !options.some((o) => norm(o.label) === q) ? query.trim() : "";
  const visible = rows.slice(0, MAX_ROWS);
  const total = visible.length + (custom ? 1 : 0);

  // opening on an existing value highlights it (so Enter keeps it) rather than the first row
  useEffect(() => {
    if (!open || !fresh) return;
    const i = visible.findIndex((o) => o.value === value);
    setActive(i >= 0 ? i : 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, fresh]);

  // keep the highlighted row inside the scroll area
  useEffect(() => {
    if (!open) return;
    listRef.current?.querySelector<HTMLElement>(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  // close when clicking elsewhere
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) finish(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, query, allowCustom]);

  function pick(v: string) {
    onChange(v);
    setQuery(null);
    setOpen(false);
  }

  /** Leave the field: keep custom text when allowed, otherwise fall back to the current selection. */
  function finish(refocus: boolean) {
    if (editing) {
      const typed = (query ?? "").trim();
      if (allowCustom) {
        const exact = options.find((o) => norm(o.label) === norm(typed));
        onChange(exact ? exact.value : typed);
      } else if (!typed && !required) {
        onChange("");
      }
    }
    setQuery(null);
    setOpen(false);
    if (refocus) inputRef.current?.focus();
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) { setOpen(true); setActive(0); } else setActive((a) => Math.min(total - 1, a + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) setOpen(true);
      setActive((a) => Math.max(0, a - 1));
    } else if (e.key === "Home" && open) {
      e.preventDefault(); setActive(0);
    } else if (e.key === "End" && open) {
      e.preventDefault(); setActive(Math.max(0, total - 1));
    } else if (e.key === "Enter") {
      if (open) {
        e.preventDefault();
        if (active < visible.length) pick(visible[active].value);
        else if (custom) pick(custom);
        else finish(false);
      }
    } else if (e.key === "Escape") {
      if (open) { e.preventDefault(); setQuery(null); setOpen(false); }
    } else if (e.key === "Tab") {
      // a single clear match is accepted when tabbing away
      if (editing && !allowCustom && q && visible.length >= 1 && score(visible[0], q) <= 1) onChange(visible[0].value);
      else finish(false);
    }
  }

  const invalid = !!error;
  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={id} className="block text-base font-semibold text-ink">
        {label}
      </label>
      <div ref={wrapRef} className="relative">
        {leading && <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-soft">{leading}</span>}
        <input
          ref={inputRef}
          id={id}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && total ? `${id}-o${active}` : undefined}
          aria-invalid={invalid}
          aria-describedby={error ? `${id}-err` : hint ? `${id}-hint` : undefined}
          autoComplete={autoComplete}
          autoCapitalize="off"
          spellCheck={false}
          enterKeyHint="done"
          required={required}
          disabled={disabled}
          placeholder={placeholder}
          value={editing ? query ?? "" : shown}
          className={cn(control, leading ? "pl-11" : "")}
          onFocus={(e) => {
            if (disabled) return;
            setQuery(shown);
            setFresh(true);
            setOpen(true);
            setActive(0);
            const el = e.currentTarget;
            requestAnimationFrame(() => el?.select());
          }}
          onChange={(e) => {
            setQuery(e.target.value);
            setFresh(false);
            setOpen(true);
            setActive(0);
          }}
          onKeyDown={onKey}
        />
        <div className="absolute inset-y-0 right-1.5 flex items-center gap-0.5">
          {!!shown && !disabled && !required && (
            <button type="button" tabIndex={-1} aria-label={`Clear ${label}`} onMouseDown={(e) => e.preventDefault()} onClick={() => { pick(""); inputRef.current?.focus(); }}
              className="grid size-8 place-items-center rounded-full text-ink-soft hover:bg-lapis-50 hover:text-ink">
              <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden><path d="M5 5l10 10M15 5L5 15" /></svg>
            </button>
          )}
          <button type="button" tabIndex={-1} disabled={disabled} aria-label={`Show ${label} options`} onMouseDown={(e) => e.preventDefault()}
            onClick={() => { if (open) finish(true); else { setQuery(shown); setFresh(true); setOpen(true); setActive(0); inputRef.current?.focus(); } }}
            className="grid size-8 place-items-center rounded-full text-ink-soft hover:bg-lapis-50 hover:text-ink">
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden className={cn("transition-transform duration-200", open && "rotate-180")}><path d="M5 8l5 5 5-5" /></svg>
          </button>
        </div>

        {open && !disabled && (
          <ul
            ref={listRef}
            id={listId}
            role="listbox"
            aria-label={label}
            className="absolute left-0 right-0 z-50 mt-2 max-h-72 origin-top overflow-y-auto overscroll-contain rounded-2xl bg-white p-1.5 shadow-[var(--shadow-lift)] ring-1 ring-line [animation:sq-pop_160ms_ease-out_both]"
          >
            {visible.map((o, i) => (
              <li key={`${o.value}-${i}`} role="presentation">
                {o.group && <p className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">{o.group}</p>}
                <div
                  id={`${id}-o${i}`}
                  data-i={i}
                  role="option"
                  aria-selected={o.value === value}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => pick(o.value)}
                  onMouseMove={() => active !== i && setActive(i)}
                  className={cn("flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5", i === active ? "bg-lapis-50" : "", o.value === value && "font-semibold")}
                >
                  {o.badge && <span className="grid h-6 min-w-8 place-items-center rounded-md bg-lapis-100 px-1 text-xs font-bold text-lapis-900">{o.badge}</span>}
                  <span className="min-w-0 flex-1 truncate"><Highlight text={o.label} query={query ?? ""} /></span>
                  {o.meta && <span className="text-sm tabular-nums text-ink-soft">{o.meta}</span>}
                  {o.value === value && (
                    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className="text-tile-700" aria-hidden><path d="M4 10.5l4 4 8-9" /></svg>
                  )}
                </div>
              </li>
            ))}
            {custom && (
              <li role="presentation">
                <div id={`${id}-o${visible.length}`} data-i={visible.length} role="option" aria-selected={false} onMouseDown={(e) => e.preventDefault()} onClick={() => pick(custom)}
                  onMouseMove={() => active !== visible.length && setActive(visible.length)}
                  className={cn("flex cursor-pointer items-center gap-2 rounded-xl px-3 py-2.5", active === visible.length && "bg-lapis-50")}>
                  <span className="text-ink-soft">Use</span> <strong className="truncate">“{custom}”</strong>
                </div>
              </li>
            )}
            {!visible.length && !custom && <li role="presentation" className="px-3 py-3 text-ink-soft">{emptyText}</li>}
            {rows.length > MAX_ROWS && <li role="presentation" className="px-3 py-2 text-sm text-ink-soft">Keep typing to narrow {rows.length - MAX_ROWS} more.</li>}
          </ul>
        )}
      </div>
      {hint && !error && <p id={`${id}-hint`} className="text-sm text-ink-soft">{hint}</p>}
      {error && <p id={`${id}-err`} role="alert" className="text-sm font-medium text-bad">{error}</p>}
    </div>
  );
}
