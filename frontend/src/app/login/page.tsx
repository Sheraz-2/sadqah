"use client";

import Link from "next/link";
import { Suspense, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, post } from "@/lib/api";
import { landingFor } from "@/lib/nav";
import { useAuth } from "@/hooks/useAuth";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Field";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { Spinner } from "@/components/ui/Spinner";
import type { Me } from "@/types/api";

export default function LoginPage() {
  return (
    <Suspense fallback={<Spinner label="Loading" />}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const next = useSearchParams().get("next");
  const { setMe } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await post<{ user: Me }>("/auth/login", { email: email.trim(), password });
      setMe(res.user);
      router.replace(landingFor(res.user.role, next));
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 429
          ? `Too many attempts. Please wait ${err.retryAfter ? Math.ceil(err.retryAfter / 60) + " minute(s)" : "a moment"} and try again.`
          : err instanceof ApiError
            ? err.message
            : "Something went wrong. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md px-4 py-16 sm:px-6">
      <h1 className="text-4xl font-bold">Sign in</h1>
      <Card className="mt-6">
        <form onSubmit={submit} className="space-y-5">
          <Input label="E-mail" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <PasswordInput label="Password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)}
            footer={<p className="text-sm"><Link href="/forgot-password" className="font-semibold text-lapis-700 underline underline-offset-2">Forgot your password?</Link></p>} />
          {error && <Alert tone="bad">{error}</Alert>}
          <Button type="submit" size="lg" className="w-full" loading={busy} disabled={!email || !password}>
            Sign in
          </Button>
        </form>
      </Card>
      <p className="mt-5 text-center text-ink-soft">
        New here?{" "}
        <Link href={`/register${next ? `?next=${encodeURIComponent(next)}` : ""}`} className="font-semibold text-lapis-700 underline">
          Create an account
        </Link>
      </p>
    </div>
  );
}
