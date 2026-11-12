"use client";

import { useEffect, useState, type FormEvent } from "react";
import { ApiError, get, post, put } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { DocumentUploader } from "@/components/kyc/DocumentUploader";
import { RecipientShell } from "@/components/recipient/RecipientNav";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Field";
import { CountrySelect } from "@/components/ui/CountrySelect";
import { DOC_LABELS, type Liveness } from "@/types/recipient";
import type { KycDocType, RecipientMe } from "@/types/api";

const EDITABLE = ["not_started", "documents_pending", "rejected"];

export default function VerifyPage() {
  return (
    <RecipientShell title="Verification" intro="Every recipient is verified by checking identity, address and income, so donors can trust each gift. A human reviewer always makes the final decision.">
      {({ rme, reload }) => (rme.profile && rme.kyc ? <Wizard rme={rme} reload={reload} /> : <Alert tone="info">Create your profile first, then come back here.</Alert>)}
    </RecipientShell>
  );
}

function Wizard({ rme, reload }: { rme: RecipientMe; reload: () => Promise<void> }) {
  const k = rme.kyc!;
  const editable = EDITABLE.includes(k.status);

  // While we are reading documents or a reviewer is deciding, check for the result every 15 seconds.
  useEffect(() => {
    if (k.status !== "processing" && k.status !== "needs_human_review") return;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void reload();
    }, 15_000);
    return () => window.clearInterval(id);
  }, [k.status, reload]);

  return (
    <div className="space-y-8">
      <StatusBanner k={k} />
      {editable && (
        <>
          <IdentityForm rme={rme} reload={reload} />
          <Documents rme={rme} reload={reload} />
          <SubmitCard rme={rme} reload={reload} />
        </>
      )}
    </div>
  );
}

function StatusBanner({ k }: { k: NonNullable<RecipientMe["kyc"]> }) {
  switch (k.status) {
    case "processing":
      return <Alert tone="info" title="Reading your documents">We are checking your documents now. This usually takes a few minutes.</Alert>;
    case "needs_human_review":
      return <Alert tone="info" title="With a reviewer">A person on our team is reviewing your application and will decide soon.</Alert>;
    case "approved":
      return <Alert tone="ok" title="You are verified">You can create your campaign. Thank you for your patience.</Alert>;
    case "suspended":
      return <Alert tone="bad" title="Your account is paused">{k.rejection_reason ?? "Please contact SadQah support."}</Alert>;
    case "rejected":
      return <Alert tone="bad" title="Your application was not approved">{k.rejection_reason ?? "Please check your details."} You can correct them below and submit again.</Alert>;
    default:
      return <Alert tone="info" title="Three steps">1. Your details. 2. Documents and a live selfie. 3. Submit for review.</Alert>;
  }
}

function IdentityForm({ rme, reload }: { rme: RecipientMe; reload: () => Promise<void> }) {
  const saved = rme.kyc!.identity_saved;
  const [open, setOpen] = useState(!saved);
  const [f, setF] = useState({ full_name: "", date_of_birth: "", id_number: "", address: "", doc_country: rme.profile?.region_country ?? "" });
  const [bio, setBio] = useState(false);
  const [data, setData] = useState(false);
  const [busy, setBusy] = useState(false);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((p) => ({ ...p, [k]: e.target.value }));

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setFields({});
    try {
      await put("/recipient/kyc/identity", { ...f, consent_biometric: bio, consent_data: data });
      setF({ full_name: "", date_of_birth: "", id_number: "", address: "", doc_country: f.doc_country });
      setOpen(false);
      await reload();
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
    <Card>
      <h2 className="text-2xl font-semibold">1. Your details {saved && <span className="text-tile-700">✓</span>}</h2>
      {!open ? (
        <div className="mt-3">
          <p className="text-ink-soft">Your details are saved and encrypted. For your safety we do not show them again.</p>
          <Button variant="secondary" size="sm" className="mt-3" onClick={() => setOpen(true)}>Re-enter my details</Button>
        </div>
      ) : (
        <form onSubmit={save} className="mt-4 space-y-4">
          <p className="text-ink-soft">Exactly as they appear on your identity document. Only the SadQah review team can see them, and they are never shown to donors.</p>
          <Input label="Full legal name" autoComplete="off" value={f.full_name} onChange={set("full_name")} error={fields.full_name} required />
          <Input label="Date of birth" type="date" value={f.date_of_birth} onChange={set("date_of_birth")} error={fields.date_of_birth} required />
          <Input label="Identity document number" autoComplete="off" value={f.id_number} onChange={set("id_number")} error={fields.id_number} hint="National ID, passport or similar. One identity can only be registered once." required />
          <Input label="Home address" autoComplete="off" value={f.address} onChange={set("address")} error={fields.address} hint="Should match your utility bill." required />
          <CountrySelect label="Country that issued the document" required value={f.doc_country} onChange={(c) => setF((p) => ({ ...p, doc_country: c }))} error={fields.doc_country} hint="Type to search any country." />
          <fieldset className="space-y-3 rounded-xl bg-lapis-50 p-4">
            <legend className="px-1 font-semibold">Your consent</legend>
            <label className="flex cursor-pointer items-start gap-3">
              <input type="checkbox" className="mt-1 size-5 accent-[#1b4580]" checked={bio} onChange={(e) => setBio(e.target.checked)} />
              <span>I agree that SadQah may compare the face in my selfie with the photo on my identity document (biometric processing), only to confirm that I am the person on the document.</span>
            </label>
            <label className="flex cursor-pointer items-start gap-3">
              <input type="checkbox" className="mt-1 size-5 accent-[#1b4580]" checked={data} onChange={(e) => setData(e.target.checked)} />
              <span>I agree that SadQah may store my details and documents, encrypted, for verification and fraud prevention, and delete them after two years.</span>
            </label>
          </fieldset>
          {error && <Alert tone="bad">{error}</Alert>}
          <Button type="submit" loading={busy} disabled={!bio || !data || !f.doc_country}>Save my details</Button>
        </form>
      )}
    </Card>
  );
}

function Documents({ rme, reload }: { rme: RecipientMe; reload: () => Promise<void> }) {
  const docs = rme.kyc!.documents;
  const latest = (t: KycDocType) => [...docs].reverse().find((d) => d.doc_type === t);
  const [idKind, setIdKind] = useState<"national_id" | "passport">(latest("passport") ? "passport" : "national_id");
  const [incomeKind, setIncomeKind] = useState<"bank_statement" | "proof_of_income">(latest("proof_of_income") ? "proof_of_income" : "bank_statement");
  const [live, setLive] = useState<Liveness | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [liveBusy, setLiveBusy] = useState(false);

  async function getCode() {
    setLiveBusy(true);
    setLiveError(null);
    try {
      setLive(await get<Liveness>("/recipient/kyc/liveness"));
    } catch (err) {
      setLiveError(err instanceof ApiError ? err.message : "Could not get a code. Please try again.");
    } finally {
      setLiveBusy(false);
    }
  }

  const choice = (name: string, value: string, set: (v: never) => void, options: [string, string][]) => (
    <div role="radiogroup" aria-label={name} className="mb-3 flex gap-2">
      {options.map(([v, label]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v} onClick={() => set(v as never)} className={`rounded-full px-4 py-1.5 text-sm font-medium ring-1 ring-inset ${value === v ? "bg-lapis-900 text-white ring-lapis-900" : "bg-white ring-line"}`}>{label}</button>
      ))}
    </div>
  );

  return (
    <Card>
      <h2 className="text-2xl font-semibold">2. Documents</h2>
      <p className="mt-1 text-ink-soft">Clear photos or scans (JPG, PNG or PDF, up to 10 MB each). Files are checked, encrypted and only opened by reviewers, and every opening is logged.</p>
      <div className="mt-5 space-y-5">
        <div>
          {choice("Identity document type", idKind, setIdKind, [["national_id", "ID card"], ["passport", "Passport"]])}
          <DocumentUploader docType={idKind} label={DOC_LABELS[idKind]} existing={latest(idKind)} onUploaded={() => void reload()} />
        </div>
        <DocumentUploader docType="utility_bill" label={DOC_LABELS.utility_bill} help="A recent bill that shows your name and address." existing={latest("utility_bill")} onUploaded={() => void reload()} />
        <div>
          {choice("Income document type", incomeKind, setIncomeKind, [["bank_statement", "Bank or mobile-money statement"], ["proof_of_income", "Other proof of income"]])}
          <DocumentUploader docType={incomeKind} label={DOC_LABELS[incomeKind]} help="Shows what comes in each month. We check that it is under $50 a month." existing={latest(incomeKind)} onUploaded={() => void reload()} />
        </div>

        <div className="rounded-2xl bg-lapis-50 p-4 ring-1 ring-lapis-100">
          <p className="font-semibold">Live selfie</p>
          <p className="text-ink-soft">Take a photo of yourself holding a piece of paper with a one-time 4-digit code written on it. Your face and the code must both be visible. The code is valid for 15 minutes.</p>
          {live ? (
            <p className="my-3 text-center" aria-live="polite">
              <span className="block text-sm text-ink-soft">Write this on paper (valid until {new Date(live.expires_at).toLocaleTimeString()})</span>
              <span className="font-mono text-5xl font-bold tracking-[0.3em] text-lapis-900">{live.code}</span>
            </p>
          ) : (
            <Button variant="secondary" size="sm" className="my-3" loading={liveBusy} onClick={() => void getCode()}>Get my code</Button>
          )}
          {liveError && <Alert tone="bad" className="mb-3">{liveError}</Alert>}
          <DocumentUploader docType="selfie" label={DOC_LABELS.selfie} existing={latest("selfie")} imageOnly camera disabled={!live} challengeToken={live?.challenge_token} onUploaded={() => { setLive(null); void reload(); }} />
        </div>
      </div>
      {docs.length > 0 && <p className="mt-4 text-sm text-ink-soft">Last upload: {formatDate(docs[docs.length - 1].uploaded_at)}</p>}
    </Card>
  );
}

const MISSING_LABEL: Record<string, string> = {
  identity_details_and_consent: "Your details and consent",
  national_id_or_passport: "ID card or passport",
  utility_bill: "Utility bill",
  selfie: "Live selfie",
  bank_statement_or_proof_of_income: "Bank statement or proof of income",
};

function SubmitCard({ rme, reload }: { rme: RecipientMe; reload: () => Promise<void> }) {
  const missing = rme.kyc!.missing;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const res = await post<{ status: string; missing: string[] }>("/recipient/kyc/submit");
      if (res.missing.length) setError(`Still needed: ${res.missing.map((m) => MISSING_LABEL[m] ?? m).join(", ")}.`);
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not submit. Please try again.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <h2 className="text-2xl font-semibold">3. Submit for review</h2>
      {missing.length > 0 ? (
        <>
          <p className="mt-2 text-ink-soft">Before you can submit, we still need:</p>
          <ul className="mt-2 list-disc pl-6">{missing.map((m) => <li key={m}>{MISSING_LABEL[m] ?? m}</li>)}</ul>
        </>
      ) : (
        <p className="mt-2 text-ink-soft">Everything is in. After you submit, we read your documents and then a person decides.</p>
      )}
      {error && <Alert tone="bad" className="mt-3">{error}</Alert>}
      <Button className="mt-4" size="lg" loading={busy} disabled={missing.length > 0} onClick={() => void submit()}>Submit for review</Button>
    </Card>
  );
}