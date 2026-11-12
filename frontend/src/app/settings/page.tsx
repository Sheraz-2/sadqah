"use client";

import Link from "next/link";
import { useState, type FormEvent, type ReactNode } from "react";
import { ApiError, get, patch, post } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { useAsync } from "@/hooks/useAsync";
import { resetPrefs, setPrefs, usePrefs, type Prefs } from "@/lib/prefs";
import { VOICE_LANGS, canSpeak } from "@/lib/speech";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Field";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { Spinner } from "@/components/ui/Spinner";
import type { Me } from "@/types/api";

type AccountSettings = {
  role: string;
  email: string;
  phone: string | null;
  display_name: string | null;
  country_code: string | null;
  show_on_leaderboard: boolean;
  can_delete: boolean;
  delete_blockers: string[];
};

function Section({ id, title, intro, children }: { id: string; title: string; intro?: string; children: ReactNode }) {
  return (
    <Card className="space-y-4 p-5 sm:p-6" >
      <div>
        <h2 id={id} className="font-display text-xl font-semibold text-lapis-900">{title}</h2>
        {intro && <p className="mt-1 text-ink-soft">{intro}</p>}
      </div>
      {children}
    </Card>
  );
}

export default function SettingsPage() {
  const { me, loading } = useAuth();
  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-10 sm:px-6">
      <div>
        <h1 className="font-display text-3xl font-bold text-lapis-900">Settings</h1>
        <p className="mt-1 text-lg text-ink-soft">Your browser settings are saved on this device only. Account settings appear when you are signed in.</p>
      </div>
      <BrowserSettings />
      {loading ? <Spinner label="Loading your account" /> : me ? <AccountSettingsBlock me={me} /> : (
        <Alert tone="info" title="Signed out">
          <Link href="/login?next=%2Fsettings" className="font-semibold underline underline-offset-2">Sign in</Link> to change your password, download your data or delete your account.
        </Alert>
      )}
    </div>
  );
}

function Choice<T extends string>({ name, label, value, options, onChange }: { name: string; label: string; value: T; options: { v: T; t: string; d?: string }[]; onChange: (v: T) => void }) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-base font-semibold text-ink">{label}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => (
          <label key={o.v} className="cursor-pointer">
            <input type="radio" name={name} className="peer sr-only" checked={value === o.v} onChange={() => onChange(o.v)} />
            <span className="block rounded-xl bg-white px-4 py-2.5 ring-1 ring-inset ring-line peer-checked:bg-lapis-900 peer-checked:text-white peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2">
              <span className="block font-medium">{o.t}</span>
              {o.d && <span className="block text-sm opacity-80">{o.d}</span>}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Toggle({ label, hint, on, onChange }: { label: string; hint: string; on: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4 rounded-xl p-2 hover:bg-lapis-50">
      <span>
        <span className="block font-medium text-ink">{label}</span>
        <span className="block text-sm text-ink-soft">{hint}</span>
      </span>
      <input type="checkbox" role="switch" checked={on} onChange={(e) => onChange(e.target.checked)} className="mt-1 size-5 shrink-0 accent-[var(--color-lapis-900)]" />
    </label>
  );
}

function BrowserSettings() {
  const p = usePrefs();
  const set = <K extends keyof Prefs>(k: K, v: Prefs[K]) => setPrefs({ [k]: v } as Partial<Prefs>);
  return (
    <>
      <Section id="appearance" title="Appearance and accessibility" intro="Applied straight away on every page of SadQah in this browser.">
        <Choice name="text" label="Text size" value={p.text} onChange={(v) => set("text", v)} options={[{ v: "normal", t: "Normal" }, { v: "large", t: "Large", d: "12% bigger" }, { v: "xlarge", t: "Larger", d: "25% bigger" }]} />
        <div className="space-y-1">
          <Toggle label="High contrast" hint="Darker text and stronger borders." on={p.contrast === "high"} onChange={(v) => set("contrast", v ? "high" : "normal")} />
          <Toggle label="Underline links" hint="Links are always underlined, not only on hover." on={p.links === "underline"} onChange={(v) => set("links", v ? "underline" : "normal")} />
          <Toggle label="Reduce motion" hint="Turns off animations and transitions. We also follow your device's own setting." on={p.motion === "reduce"} onChange={(v) => set("motion", v ? "reduce" : "system")} />
          <Toggle label="Pointer glow and card tilt" hint="The light that follows your pointer. Turn off for a calmer page." on={p.effects === "on"} onChange={(v) => set("effects", v ? "on" : "off")} />
        </div>
        <Button variant="secondary" size="sm" onClick={resetPrefs}>Reset browser settings</Button>
      </Section>

      <Section id="voice" title="Voice and language" intro="For the assistant's microphone and read-aloud.">
        <Select label="Language I speak" hint="Automatic uses your browser's language. Pick one if voice typing mishears you." value={p.voiceLang} onChange={(e) => set("voiceLang", e.target.value)}>
          {VOICE_LANGS.map((l) => <option key={l.tag} value={l.tag}>{l.label}</option>)}
        </Select>
        {canSpeak() && <Toggle label="Read assistant answers aloud" hint="Uses your device's voices. Quality depends on the language installed on your device." on={p.speakReplies} onChange={(v) => set("speakReplies", v)} />}
        <p className="text-sm text-ink-soft">Voice typing is done by your browser. Some browsers, including Chrome, send the audio to their own speech service. SadQah receives only the text you choose to send. You can always type instead.</p>
      </Section>
    </>
  );
}

function AccountSettingsBlock({ me }: { me: Me }) {
  const acct = useAsync((s) => get<AccountSettings>("/account/settings", s), [me.id]);
  if (acct.loading && !acct.data) return <Spinner label="Loading your account" />;
  if (acct.error || !acct.data) return <Alert tone="bad" title="We could not load your account settings">Please refresh the page and try again.</Alert>;
  return (
    <>
      <PrivacyCard me={me} />
      <AccountCard a={acct.data} />
      <PasswordCard />
      <DataCard />
      <DeleteCard a={acct.data} />
    </>
  );
}

function PrivacyCard({ me }: { me: Me }) {
  const { setMe } = useAuth();
  const [name, setName] = useState(me.display_name ?? "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  async function save(body: Record<string, unknown>) {
    setBusy(true);
    setMsg(null);
    try {
      setMe(await patch<Me>("/me", body));
      setMsg({ tone: "ok", text: "Saved." });
    } catch (err) {
      setMsg({ tone: "bad", text: err instanceof ApiError ? err.message : "Could not save. Please try again." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section id="privacy" title="Privacy" intro="Choose what other people can see.">
      <form onSubmit={(e: FormEvent) => { e.preventDefault(); void save({ display_name: name.trim() || null }); }} className="space-y-3">
        <Input label="Display name" hint="Shown on the leaderboard and on thank-you notes if you give publicly. Leave empty to stay unnamed." value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" size="sm" loading={busy}>Save name</Button>
      </form>
      {me.role === "donor" && (
        <Toggle label="Show me on the public leaderboard" hint="Only public gifts are ever ranked. Anonymous gifts never appear." on={me.show_on_leaderboard} onChange={(v) => void save({ show_on_leaderboard: v })} />
      )}
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
    </Section>
  );
}

function AccountCard({ a }: { a: AccountSettings }) {
  return (
    <Section id="account" title="Your account">
      <dl className="grid gap-3 sm:grid-cols-2">
        <div><dt className="text-sm text-ink-soft">Email</dt><dd className="break-all font-medium">{a.email}</dd></div>
        <div><dt className="text-sm text-ink-soft">Phone</dt><dd className="font-medium">{a.phone ?? "Not added"}</dd></div>
        <div><dt className="text-sm text-ink-soft">Role</dt><dd className="font-medium capitalize">{a.role}</dd></div>
        <div><dt className="text-sm text-ink-soft">Country</dt><dd className="font-medium">{a.country_code ?? "Not set"}</dd></div>
      </dl>
      <p className="text-sm text-ink-soft">To change your email or phone, <Link href="/contact" className="font-semibold underline underline-offset-2">contact support</Link> by email. Recipients can edit their public profile under Profile &amp; payout.</p>
    </Section>
  );
}

function PasswordCard() {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    if (next !== again) return setMsg({ tone: "bad", text: "The two new passwords do not match." });
    setBusy(true);
    try {
      await post("/account/password", { current_password: cur, new_password: next });
      setCur(""); setNext(""); setAgain("");
      setMsg({ tone: "ok", text: "Password changed." });
    } catch (err) {
      setMsg({ tone: "bad", text: err instanceof ApiError ? err.message : "Could not change the password. Please try again." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section id="password" title="Change password">
      <form onSubmit={save} className="space-y-3">
        <PasswordInput label="Current password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required />
        <PasswordInput label="New password" autoComplete="new-password" hint="Use a long phrase you do not use anywhere else." value={next} onChange={(e) => setNext(e.target.value)} required />
        <PasswordInput label="New password again" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} required />
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        <Button type="submit" loading={busy} disabled={!cur || !next || !again}>Change password</Button>
      </form>
    </Section>
  );
}

function DataCard() {
  return (
    <Section id="data" title="Download my data" intro="A JSON file with your profile, your gifts and your messages.">
      <a href="/api/v1/account/export" download className="inline-flex h-11 items-center rounded-full bg-white px-6 font-semibold text-lapis-900 ring-1 ring-inset ring-line hover:bg-lapis-50">
        Download my data
      </a>
    </Section>
  );
}

function DeleteCard({ a }: { a: AccountSettings }) {
  const { setMe } = useAuth();
  const [open, setOpen] = useState(false);
  const [pw, setPw] = useState("");
  const [word, setWord] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function remove(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await post("/account/delete", { password: pw, confirm: "DELETE" });
      setMe(null);
      window.location.href = "/?account=deleted";
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : "Could not delete the account. Please try again.");
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-4 border-2 border-pomegranate-500/40 p-5 sm:p-6">
      <div>
        <h2 id="danger" className="font-display text-xl font-semibold text-pomegranate-600">Delete my account</h2>
        <p className="mt-1 text-ink-soft">
          This closes your account for good and removes your personal details: your name, email, phone and identity documents. You cannot undo it.
          Records of money that moved are kept in anonymous form, because financial and audit records cannot be erased.
        </p>
      </div>
      {!a.can_delete ? (
        <Alert tone="warn" title="You cannot delete your account yet">
          <ul className="list-disc space-y-1 pl-5">{a.delete_blockers.map((b) => <li key={b}>{b}</li>)}</ul>
          <p className="mt-2">Once these are finished you can come back and delete your account.</p>
        </Alert>
      ) : !open ? (
        <Button variant="danger" onClick={() => setOpen(true)}>Delete my account…</Button>
      ) : (
        <form onSubmit={remove} className="space-y-3" aria-label="Confirm account deletion">
          <Alert tone="bad" title="Are you sure?">Your campaigns close and your public profile is removed. Consider downloading your data first.</Alert>
          <PasswordInput label="Your password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} required />
          <Input label="Type DELETE to confirm" value={word} onChange={(e) => setWord(e.target.value)} autoComplete="off" required />
          {err && <Alert tone="bad">{err}</Alert>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="danger" loading={busy} disabled={!pw || word !== "DELETE"}>Permanently delete my account</Button>
            <Button type="button" variant="secondary" onClick={() => { setOpen(false); setPw(""); setWord(""); setErr(null); }}>Keep my account</Button>
          </div>
        </form>
      )}
    </Card>
  );
}
