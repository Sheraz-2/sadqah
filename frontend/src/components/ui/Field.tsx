import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

const control =
  "w-full rounded-xl border-0 bg-white px-4 py-3 text-base text-ink ring-1 ring-inset ring-line placeholder:text-ink-soft/60 focus:ring-2 focus:ring-lapis-500 aria-[invalid=true]:ring-2 aria-[invalid=true]:ring-bad";

type Shared = { label: string; hint?: string; error?: string | null; className?: string };

function Wrap({ id, label, hint, error, children, className }: Shared & { id: string; children: ReactNode }) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={id} className="block text-base font-semibold text-ink">
        {label}
      </label>
      {children}
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
    </div>
  );
}

const describedBy = (id: string, hint?: string, error?: string | null) => (error ? `${id}-err` : hint ? `${id}-hint` : undefined);

export function Input({ label, hint, error, className, ...rest }: Shared & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <Wrap id={id} label={label} hint={hint} error={error} className={className}>
      <input id={id} className={control} aria-invalid={!!error} aria-describedby={describedBy(id, hint, error)} {...rest} />
    </Wrap>
  );
}

export function Textarea({ label, hint, error, className, ...rest }: Shared & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId();
  return (
    <Wrap id={id} label={label} hint={hint} error={error} className={className}>
      <textarea id={id} rows={4} className={control} aria-invalid={!!error} aria-describedby={describedBy(id, hint, error)} {...rest} />
    </Wrap>
  );
}

export function Select({ label, hint, error, className, children, ...rest }: Shared & SelectHTMLAttributes<HTMLSelectElement>) {
  const id = useId();
  return (
    <Wrap id={id} label={label} hint={hint} error={error} className={className}>
      <select id={id} className={control} aria-invalid={!!error} aria-describedby={describedBy(id, hint, error)} {...rest}>
        {children}
      </select>
    </Wrap>
  );
}
