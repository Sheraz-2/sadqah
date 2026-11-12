"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { resetPrefs, setPrefs, usePrefs, type Prefs } from "@/lib/prefs";

function Seg<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: { v: T; t: string }[]; onChange: (v: T) => void }) {
  return (
    <div role="group" aria-label={label} className="flex rounded-full bg-lapis-50 p-0.5 ring-1 ring-line">
      {options.map((o) => (
        <button
          key={o.v}
          type="button"
          aria-pressed={value === o.v}
          onClick={() => onChange(o.v)}
          className={cn("flex-1 rounded-full px-2.5 py-1.5 text-sm font-medium", value === o.v ? "bg-lapis-900 text-white" : "text-ink-soft hover:text-lapis-900")}
        >
          {o.t}
        </button>
      ))}
    </div>
  );
}

function Switch({ label, on, onChange }: { label: string; on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)} className="flex w-full items-center justify-between gap-3 rounded-lg px-1 py-1.5 text-left">
      <span className="text-[0.95rem] text-ink">{label}</span>
      <span className={cn("relative h-6 w-11 shrink-0 rounded-full transition-colors", on ? "bg-lapis-900" : "bg-lapis-100 ring-1 ring-line")}>
        <span className={cn("absolute top-0.5 size-5 rounded-full bg-white shadow transition-all", on ? "left-[1.375rem]" : "left-0.5")} />
      </span>
    </button>
  );
}

/** The gear at the top right: quick browser settings. Everything else lives on /settings. */
export function SettingsMenu() {
  const [open, setOpen] = useState(false);
  const prefs = usePrefs();
  const pathname = usePathname() || "/";
  const root = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const id = useId();

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        btn.current?.focus();
      }
    };
    document.addEventListener("pointerdown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", down);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  const set = <K extends keyof Prefs>(k: K, v: Prefs[K]) => setPrefs({ [k]: v } as Partial<Prefs>);

  return (
    <div ref={root} className="relative">
      <button
        ref={btn}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="Settings"
        aria-expanded={open}
        aria-controls={id}
        className="grid size-10 place-items-center rounded-full text-lapis-900 ring-1 ring-line hover:bg-lapis-50"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
        </svg>
      </button>

      {open && (
        <div id={id} role="dialog" aria-label="Quick settings" className="absolute right-0 top-full z-50 mt-2 w-[19rem] max-w-[calc(100vw-2rem)] space-y-3 rounded-2xl bg-white p-4 shadow-[var(--shadow-lift)] ring-1 ring-line">
          <p className="font-display text-lg font-semibold text-lapis-900">Settings</p>
          <div className="space-y-1.5">
            <p className="text-sm font-medium text-ink-soft">Text size</p>
            <Seg label="Text size" value={prefs.text} onChange={(v) => set("text", v)} options={[{ v: "normal", t: "Normal" }, { v: "large", t: "Large" }, { v: "xlarge", t: "Larger" }]} />
          </div>
          <div className="space-y-0.5">
            <Switch label="High contrast" on={prefs.contrast === "high"} onChange={(v) => set("contrast", v ? "high" : "normal")} />
            <Switch label="Underline links" on={prefs.links === "underline"} onChange={(v) => set("links", v ? "underline" : "normal")} />
            <Switch label="Reduce motion" on={prefs.motion === "reduce"} onChange={(v) => set("motion", v ? "reduce" : "system")} />
            <Switch label="Pointer glow and tilt" on={prefs.effects === "on"} onChange={(v) => set("effects", v ? "on" : "off")} />
          </div>
          <div className="flex items-center justify-between gap-2 border-t border-line pt-3">
            <Link href="/settings" className="font-semibold text-lapis-700 underline underline-offset-2">All settings and account</Link>
            <button type="button" onClick={resetPrefs} className="text-sm text-ink-soft underline underline-offset-2 hover:text-lapis-900">Reset</button>
          </div>
        </div>
      )}
    </div>
  );
}
