"use client";

import Link from "next/link";
import { Suspense, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { landingFor } from "@/lib/nav";
import { useAuth } from "@/hooks/useAuth";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Field";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { CountrySelect } from "@/components/ui/CountrySelect";
import { PhoneField } from "@/components/ui/PhoneField";
import { Spinner } from "@/components/ui/Spinner";
import type { Me } from "@/types/api";

const MIN_PASSWORD = 12;

export default function RegisterPage() {
  return (
    <Suspense fallback={<Spinner label="Loading" />}>
      <RegisterForm />
    </Suspense>
  );
}

function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next");
  const { setMe } = useAuth();
  const [role, setRole] = useState<"donor" | "recipient">(params.get("role") === "recipient" ? "recipient" : "donor");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [country, setCountry] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});

  const long = password.length >= MIN_PASSWORD;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setFields({});
    try {
      const body: Record<string, unknown> = { email: email.trim(), password, role };
      if (displayName.trim()) body.display_name = displayName.trim();
      if (country) body.country_code = country;
      if (phone.trim()) body.phone = phone.trim();
      const res = await post<{ user: Me }>("/auth/register", body);
      setMe(res.user);
      router.replace(landingFor(res.user.role, next));
    } catch (err) {
      if (err instanceof ApiError) {
        setFields(err.fields ?? {});
        setError(err.message);
      } else setError("Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-lg px-4 py-14 sm:px-6">
      <h1 className="text-4xl font-bold">Create your account</h1>

      <div role="radiogroup" aria-label="Account type" className="mt-6 grid grid-cols-2 gap-3">
        {(
          [
            ["donor", "I want to give", "Give publicly or anonymously and follow your gifts."],
            ["recipient", "I need a small grant", "Apply for verification and a small grant for your work."],
          ] as const
        ).map(([value, title, body]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={role === value}
            onClick={() => setRole(value)}
            className={cn("rounded-2xl p-4 text-left ring-1 ring-inset", role === value ? "bg-lapis-50 ring-2 ring-lapis-700" : "bg-white ring-line hover:bg-lapis-50")}
          >
            <span className="block font-semibold">{title}</span>
            <span className="mt-1 block text-sm text-ink-soft">{body}</span>
          </button>
        ))}
      </div>

      <Card className="mt-6">
        <form onSubmit={submit} className="space-y-5" noValidate>
          <Input label="E-mail" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} error={fields.email} />
          <div>
            <PasswordInput
              label="Password"
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              error={fields.password}
              hint={`At least ${MIN_PASSWORD} characters. A few random words work well.`}
            />
            <p className={cn("mt-1 text-sm font-medium", long ? "text-tile-700" : "text-ink-soft")} aria-live="polite">
              {long ? "Long enough" : `${password.length} of ${MIN_PASSWORD} characters`}
            </p>
          </div>
          <Input
            label={role === "donor" ? "Display name (optional)" : "Your first name (optional)"}
            hint={role === "donor" ? "Shown only on gifts you choose to give publicly." : "You choose the name donors see when you set up your profile."}
            value={displayName}
            maxLength={40}
            onChange={(e) => setDisplayName(e.target.value)}
            error={fields.display_name}
          />
          <CountrySelect label="Country (optional)" value={country} onChange={setCountry} anyLabel="Prefer not to say" hint="Type to search any country." error={fields.country_code} />
          {role === "recipient" && (
            <PhoneField label="Phone (optional)" country={country} value={phone} onChange={setPhone} hint="Never shown to donors." error={fields.phone} />
          )}
          {error && <Alert tone="bad">{error}</Alert>}
          <Button type="submit" size="lg" className="w-full" loading={busy} disabled={!email || !long}>
            Create account
          </Button>
        </form>
      </Card>
      <p className="mt-5 text-center text-ink-soft">
        Already have an account?{" "}
        <Link href={`/login${next ? `?next=${encodeURIComponent(next)}` : ""}`} className="font-semibold text-lapis-700 underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
