"use client";

import { useEffect, useId, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { countryName } from "@/lib/format";
import { findCountry } from "@/lib/countries";

type Props = {
  label: string;
  /** Full international number, e.g. "+923001234567". Empty when nothing has been typed. */
  value: string;
  onChange: (full: string) => void;
  /** ISO-2 code of the selected country. Its calling code is shown as a fixed prefix and follows the country. */
  country: string;
  hint?: string;
  error?: string | null;
  required?: boolean;
  disabled?: boolean;
  className?: string;
  placeholder?: string;
  autoComplete?: string;
};

const control =
  "min-w-0 flex-1 border-0 bg-transparent px-3 py-3 text-base text-ink outline-none placeholder:text-ink-soft/60 focus:ring-0";

/** Keep digits and light formatting only; drop a leading trunk zero so "0300…" becomes "300…". */
function cleanNational(raw: string, dial: string): string {
  let s = raw.replace(/[^\d+\s\-()]/g, "");
  const plain = s.replace(/[\s\-()]/g, "");
  if (plain.startsWith("+" + dial)) s = plain.slice(dial.length + 1);
  else if (plain.startsWith("00" + dial)) s = plain.slice(dial.length + 2);
  else s = s.replace(/\+/g, "");
  return s.replace(/^[\s\-()]*0+/, "").replace(/^\s+/, "");
}

/**
 * Phone input whose country code is chosen by the country field: the prefix (for example +92) is fixed text, the
 * person types only the national number, and the full "+92…" value is passed up. Without a country it behaves like
 * a normal phone box where the number is typed with its own "+" code.
 */
export function PhoneField({ label, value, onChange, country, hint, error, required, disabled, className, placeholder, autoComplete = "tel-national" }: Props) {
  const id = useId();
  const c = findCountry(country);
  const dial = c?.dial ?? "";
  const [national, setNational] = useState(() => (dial && value.startsWith("+" + dial) ? value.slice(dial.length + 1) : dial ? "" : value));
  const lastEmitted = useRef(value);

  // The parent cleared or replaced the whole value (for example after saving): follow it.
  useEffect(() => {
    if (value === lastEmitted.current) return;
    lastEmitted.current = value;
    setNational(dial && value.startsWith("+" + dial) ? value.slice(dial.length + 1) : value ? value : "");
  }, [value, dial]);

  // The country changed: keep what was typed, swap the code in front of it.
  const prevDial = useRef(dial);
  useEffect(() => {
    if (prevDial.current === dial) return;
    prevDial.current = dial;
    const digits = national.replace(/\D/g, "");
    const full = dial ? (digits ? `+${dial}${digits}` : "") : national.trim();
    lastEmitted.current = full;
    onChange(full);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dial]);

  function edit(raw: string) {
    if (!dial) {
      setNational(raw);
      lastEmitted.current = raw;
      onChange(raw);
      return;
    }
    const next = cleanNational(raw, dial);
    setNational(next);
    const digits = next.replace(/\D/g, "");
    const full = digits ? `+${dial}${digits}` : "";
    lastEmitted.current = full;
    onChange(full);
  }

  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={id} className="block text-base font-semibold text-ink">
        {label}
      </label>
      <div
        className={cn(
          "flex items-stretch overflow-hidden rounded-xl bg-white ring-1 ring-inset ring-line transition-shadow focus-within:ring-2 focus-within:ring-lapis-500",
          error && "ring-2 ring-bad focus-within:ring-bad",
          disabled && "bg-lapis-50",
        )}
      >
        <span
          aria-hidden={!c}
          title={c ? `${countryName(country)} calling code` : undefined}
          className={cn(
            "flex shrink-0 items-center gap-1.5 border-r border-line bg-lapis-50 px-3.5 font-semibold tabular-nums text-lapis-900",
            !c && "text-ink-soft",
          )}
        >
          {c ? (
            <>
              <span className="text-xs font-bold text-lapis-700">{c.code}</span>
              <span>+{c.dial}</span>
            </>
          ) : (
            <span>+</span>
          )}
        </span>
        <input
          id={id}
          type="tel"
          inputMode="tel"
          autoComplete={autoComplete}
          required={required}
          disabled={disabled}
          value={national}
          placeholder={placeholder ?? (c ? "Phone number" : "Include your code, e.g. +92 300 1234567")}
          aria-invalid={!!error}
          aria-describedby={error ? `${id}-err` : hint ? `${id}-hint` : undefined}
          onChange={(e) => edit(e.target.value)}
          className={control}
          style={{ outline: "none" }} /* the wrapper draws the focus ring; the global :focus-visible outline would be clipped by it */
        />
      </div>
      {hint && !error && <p id={`${id}-hint`} className="text-sm text-ink-soft">{c ? `${hint} Code is +${c.dial} for ${countryName(country)}.` : hint}</p>}
      {error && <p id={`${id}-err`} role="alert" className="text-sm font-medium text-bad">{error}</p>}
    </div>
  );
}
