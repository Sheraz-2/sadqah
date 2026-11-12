"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { ApiError, get, post } from "@/lib/api";
import { useAsync } from "@/hooks/useAsync";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Field";
import { PasswordInput } from "@/components/ui/PasswordInput";

const MIN_PASSWORD = 12;
type Step = "ask" | "code" | "done";

export default function ForgotPasswordPage() {
  const options = useAsync((s) => get<{ email: boolean; sms: boolean }>("/auth/recovery/options", s), []);
  const [step, setStep] = useState<Step>("ask");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});

  const unavailable = options.data !== null && !options.data.email;

  function fail(err: unknown) {
    if (err instanceof ApiError) {
      setError(err.message);
      setFields(err.fields ?? {});
    } else setError("Something went wrong. Please try again.");
  }

  async function ask(e: FormEvent) {
    e.preventDefault();
    setError(null); setFields({}); setBusy(true);
    try {
      const res = await post<{ message: string }>("/auth/password-reset/request", { email: email.trim(), channel: "email" });
      setNotice(res.message);
      setStep("code");
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(e: FormEvent) {
    e.preventDefault();
    setError(null); setFields({});
    if (password !== again) return setFields({ again: "The two passwords do not match." });
    setBusy(true);
    try {
      await post("/auth/password-reset/confirm", { email: email.trim(), code: code.trim(), new_password: password });
      setPassword(""); setAgain(""); setCode("");
      setStep("done");
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md px-4 py-16 sm:px-6">
      <h1 className="text-4xl font-bold">Reset your password</h1>

      {unavailable && (
        <Alert tone="warn" className="mt-6" title="Recovery by e-mail is not set up yet">
          This site cannot send e-mail right now, so a code cannot be sent. Please <Link href="/contact" className="font-semibold underline underline-offset-2">contact SadQah support</Link>.
        </Alert>
      )}

      {step === "ask" && (
        <Card className="mt-6">
          <form onSubmit={ask} className="space-y-5">
            <p className="text-ink-soft">Enter the e-mail address of your account. If it exists, we will send a one-time code to it.</p>
            <Input label="E-mail" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            {error && <Alert tone="bad">{error}</Alert>}
            <Button type="submit" size="lg" className="w-full" loading={busy} disabled={!email || unavailable}>Send me a code</Button>
            <p className="text-center text-sm">
              <button type="button" onClick={() => { setError(null); setNotice(null); setStep("code"); }} className="font-semibold text-lapis-700 underline underline-offset-2">
                I already have a code
              </button>
            </p>
          </form>
        </Card>
      )}

      {step === "code" && (
        <Card className="mt-6">
          <form onSubmit={confirm} className="space-y-5" noValidate>
            {notice && <Alert tone="info">{notice}</Alert>}
            <Input label="E-mail" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            <Input
              label="One-time code"
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              maxLength={12}
              placeholder="1234 5678"
              hint="8 digits. It works once and expires after a few minutes."
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
            <PasswordInput
              label="New password"
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              error={fields.new_password}
              hint={`At least ${MIN_PASSWORD} characters. A few random words work well.`}
            />
            <PasswordInput label="New password again" autoComplete="new-password" required value={again} onChange={(e) => setAgain(e.target.value)} error={fields.again} />
            {error && <Alert tone="bad">{error}</Alert>}
            <Button type="submit" size="lg" className="w-full" loading={busy} disabled={!email || code.replace(/\D/g, "").length !== 8 || password.length < MIN_PASSWORD || !again}>
              Change password
            </Button>
            <p className="text-center text-sm">
              <button type="button" onClick={() => { setError(null); setFields({}); setStep("ask"); }} className="font-semibold text-lapis-700 underline underline-offset-2">
                Send a new code
              </button>
            </p>
          </form>
        </Card>
      )}

      {step === "done" && (
        <Card className="mt-6 space-y-4">
          <Alert tone="ok" title="Your password has been changed">You can now sign in with your new password.</Alert>
          <Link href="/login" className="inline-flex h-12 w-full items-center justify-center rounded-full bg-lapis-900 text-lg font-semibold text-white hover:bg-lapis-700">Sign in</Link>
        </Card>
      )}

      <p className="mt-5 text-center text-ink-soft">
        <Link href="/login" className="font-semibold text-lapis-700 underline">Back to sign in</Link>
      </p>
    </div>
  );
}
