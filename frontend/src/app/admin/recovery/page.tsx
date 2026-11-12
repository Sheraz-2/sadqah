"use client";

import { useState, type FormEvent } from "react";
import { ApiError, post } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Field";

type Result = { status: "code_sent" | "no_eligible_account" | "too_soon"; message: string };

/** Admin-only (the API enforces it; this page also hides itself from reviewers). The code goes to the person, never to the admin. */
export default function RecoveryPage() {
  const { me } = useAuth();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (me?.role !== "admin") {
    return <Alert tone="warn" title="Administrators only">Starting a password reset for someone else needs an administrator account.</Alert>;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null); setResult(null); setBusy(true);
    try {
      setResult(await post<Result>("/admin/users/password-reset", { email: email.trim() }));
      setEmail("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="font-display text-3xl font-bold">Start a password reset</h1>
        <p className="mt-1 text-ink-soft">
          For a person who cannot reset their own password. A one-time code is sent to the <strong>verified e-mail address on their account</strong>.
          You never see the code, their e-mail or their password, and they choose the new password themselves. This action is recorded in the audit log.
        </p>
      </div>
      <Card>
        <form onSubmit={submit} className="space-y-4">
          <Input label="The person's account e-mail" type="email" autoComplete="off" required value={email} onChange={(e) => setEmail(e.target.value)}
            hint="Ask them to confirm the address they registered with. Administrator accounts cannot be reset here." />
          {error && <Alert tone="bad">{error}</Alert>}
          <Button type="submit" loading={busy} disabled={!email}>Send reset code</Button>
        </form>
      </Card>
      {result && <Alert tone={result.status === "code_sent" ? "ok" : "warn"}>{result.message}</Alert>}
    </div>
  );
}
