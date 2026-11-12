"use client";

import { useId, useState, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Same look, label, hint and error handling as `Input` in Field.tsx, plus an eye / eye-off button that shows or hides the text.
 *  Hidden (masked) by default. The button is a real button with a state-aware name, so it works with a keyboard and a screen reader. */
type Props = { label: string; hint?: string; error?: string | null; className?: string; footer?: ReactNode } & Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "type" | "className"
>;

const control =
  "w-full rounded-xl border-0 bg-white py-3 pl-4 pr-12 text-base text-ink ring-1 ring-inset ring-line placeholder:text-ink-soft/60 focus:ring-2 focus:ring-lapis-500 aria-[invalid=true]:ring-2 aria-[invalid=true]:ring-bad";

export function PasswordInput({ label, hint, error, className, footer, ...rest }: Props) {
  const id = useId();
  const [shown, setShown] = useState(false);
  const describedBy = error ? `${id}-err` : hint ? `${id}-hint` : undefined;
  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={id} className="block text-base font-semibold text-ink">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type={shown ? "text" : "password"}
          className={control}
          aria-invalid={!!error}
          aria-describedby={describedBy}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          {...rest}
        />
        <button
          type="button"
          onClick={() => setShown((s) => !s)}
          aria-label={shown ? "Hide password" : "Show password"}
          aria-pressed={shown}
          aria-controls={id}
          className="absolute inset-y-0 right-0 grid w-12 place-items-center rounded-r-xl text-ink-soft hover:text-lapis-900"
        >
          {shown ? (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M17.94 17.94A10.9 10.9 0 0 1 12 20C5 20 1 12 1 12a18.5 18.5 0 0 1 5.06-5.94M9.9 4.24A10.9 10.9 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19M14.12 14.12a3 3 0 1 1-4.24-4.24" />
              <path d="m1 1 22 22" />
            </svg>
          ) : (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M1 12S5 4 12 4s11 8 11 8-4 8-11 8S1 12 1 12Z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          )}
        </button>
      </div>
      {hint && !error && (
        <p id={`${id}-hint`} className="text-sm text-ink-soft">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-err`} role="alert" className="text-sm font-medium text-bad">
          {error}
        </p>
      )}
      {footer}
    </div>
  );
}
