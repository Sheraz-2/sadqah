"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { ApiError, post, put } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { RecipientShell } from "@/components/recipient/RecipientNav";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Field";
import { CountrySelect } from "@/components/ui/CountrySelect";
import { RegionField } from "@/components/ui/RegionField";
import { PhoneField } from "@/components/ui/PhoneField";
import type { RecipientMe } from "@/types/api";


export default function ProfilePage() {
  return (
    <RecipientShell title="Profile & payout" intro="What donors see about you, and where your gifts are sent.">
      {({ rme, reload }) => (
        <div className="space-y-8">
          <ProfileForm rme={rme} reload={reload} />
          {rme.profile && <PayoutForm rme={rme} reload={reload} />}
          {rme.profile && <PublishCard rme={rme} reload={reload} />}
        </div>
      )}
    </RecipientShell>
  );
}

function errs(err: unknown): { message: string; fields: Record<string, string> } {
  return err instanceof ApiError ? { message: err.message, fields: err.fields ?? {} } : { message: "Something went wrong. Please try again.", fields: {} };
}

function ProfileForm({ rme, reload }: { rme: RecipientMe; reload: () => Promise<void> }) {
  const p = rme.profile;
  const [name, setName] = useState(p?.public_name ?? "");
  const [story, setStory] = useState(p?.story ?? "");
  const [business, setBusiness] = useState(p?.business_type ?? "");
  const { me } = useAuth();
  const [country, setCountry] = useState(p?.region_country ?? me?.country_code ?? "");
  const [region, setRegion] = useState(p?.region_admin1 ?? "");
  const [payType, setPayType] = useState<"EMAIL" | "PHONE">("EMAIL");
  const [handle, setHandle] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    setFields({});
    try {
      if (p) await put("/recipient/profile", { public_name: name, story, business_type: business || undefined, region_admin1: region || undefined });
      else await post("/recipient/profile", { public_name: name, story, business_type: business || undefined, region_country: country, region_admin1: region || undefined, payout_type: payType, payout_handle: handle });
      setMsg({ tone: "ok", text: p ? "Profile saved." : "Profile created. Next, complete your verification." });
      await reload();
    } catch (err) {
      const { message, fields: f } = errs(err);
      setFields(f);
      setMsg({ tone: "bad", text: message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <h2 className="text-2xl font-semibold">{p ? "Your public profile" : "Create your profile"}</h2>
      <p className="mt-1 text-ink-soft">Use a first name or a nickname, never your full legal name. Share only your region, never your street or town.</p>
      <form onSubmit={save} className="mt-5 space-y-4">
        <Input label="Name donors will see" value={name} maxLength={60} required onChange={(e) => setName(e.target.value)} error={fields.public_name} />
        <Input label="Your trade or small business" placeholder="e.g. tailoring, vegetable stall" value={business} maxLength={80} onChange={(e) => setBusiness(e.target.value)} error={fields.business_type} />
        <Textarea label="Your story" rows={6} maxLength={4000} value={story} onChange={(e) => setStory(e.target.value)} hint="What you do, what is holding you back, and what the money would change." error={fields.story} />
        <div className="grid gap-4 sm:grid-cols-2">
          <CountrySelect
            label="Country"
            value={country}
            disabled={!!p}
            required
            onChange={(c) => {
              if (c !== country) setRegion("");
              setCountry(c);
            }}
            hint={p ? "Locked once your profile exists." : "Type to search any country."}
            error={fields.region_country}
          />
          <RegionField label="Province or state (optional)" country={country} value={region} onChange={setRegion} error={fields.region_admin1} />
        </div>
        {!p && (
          <fieldset className="space-y-4 rounded-xl bg-lapis-50 p-4">
            <legend className="px-1 font-semibold">Where should your gifts be sent?</legend>
            <PayoutFields payType={payType} setPayType={setPayType} handle={handle} setHandle={setHandle} fields={fields} country={country} />
          </fieldset>
        )}
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        <Button type="submit" loading={busy} disabled={!name.trim() || (!p && (!country || !handle.trim()))}>{p ? "Save profile" : "Create profile"}</Button>
      </form>
    </Card>
  );
}

function PayoutFields({ payType, setPayType, handle, setHandle, fields, country }: { payType: "EMAIL" | "PHONE"; setPayType: (v: "EMAIL" | "PHONE") => void; handle: string; setHandle: (v: string) => void; fields: Record<string, string>; country: string }) {
  return (
    <>
      <Select label="Send gifts to my" value={payType} onChange={(e) => {
        setPayType(e.target.value as "EMAIL" | "PHONE");
        setHandle("");
      }} error={fields.payout_type}>
        <option value="EMAIL">PayPal e-mail address</option>
        <option value="PHONE">Phone number</option>
      </Select>
      {payType === "PHONE" ? (
        <PhoneField label="Phone number" country={country} value={handle} onChange={setHandle} error={fields.payout_handle} hint="We encrypt this number and never show it to donors." />
      ) : (
        <Input label="PayPal e-mail" type="email" value={handle} onChange={(e) => setHandle(e.target.value)} error={fields.payout_handle} hint="If this e-mail has no PayPal account yet, PayPal will invite you to create one and claim your money. We encrypt this address and never show it to donors." />
      )}
    </>
  );
}

function PayoutForm({ rme, reload }: { rme: RecipientMe; reload: () => Promise<void> }) {
  const locked = !!rme.kyc && !["not_started", "documents_pending", "rejected"].includes(rme.kyc.status);
  const [payType, setPayType] = useState<"EMAIL" | "PHONE">("EMAIL");
  const [handle, setHandle] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    setFields({});
    try {
      await put("/recipient/payout", { payout_type: payType, payout_handle: handle });
      setHandle("");
      setMsg({ tone: "ok", text: "Payout destination updated." });
      await reload();
    } catch (err) {
      const { message, fields: f } = errs(err);
      setFields(f);
      setMsg({ tone: "bad", text: message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <h2 className="text-2xl font-semibold">Payout destination</h2>
      <p className="mt-2">
        {rme.payout ? <>Gifts go to <strong>{rme.payout.handle_masked}</strong> <Badge className="ml-1">{rme.payout.type === "EMAIL" ? "PayPal e-mail" : "Phone"}</Badge></> : "Not set."}
      </p>
      {locked ? (
        <Alert tone="info" className="mt-4">To protect you from fraud, the payout destination is locked once your verification is under review or approved. To change it, please <Link href="/contact" className="font-semibold underline underline-offset-2">contact SadQah support</Link> by email.</Alert>
      ) : (
        <form onSubmit={save} className="mt-5 space-y-4">
          <PayoutFields payType={payType} setPayType={setPayType} handle={handle} setHandle={setHandle} fields={fields} country={rme.profile?.region_country ?? ""} />
          {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
          <Button type="submit" variant="secondary" loading={busy} disabled={!handle.trim()}>Change destination</Button>
        </form>
      )}
    </Card>
  );
}

function PublishCard({ rme, reload }: { rme: RecipientMe; reload: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const approved = rme.kyc?.status === "approved";
  const isPublic = !!rme.profile?.profile_public;

  async function toggle() {
    setBusy(true);
    setMsg(null);
    try {
      await post("/recipient/profile/public", { public: !isPublic });
      await reload();
    } catch (err) {
      setMsg(errs(err).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <h2 className="text-2xl font-semibold">Public listing</h2>
      <p className="mt-1 text-ink-soft">{isPublic ? "Your profile and campaign are visible to donors." : "Your profile is private. You can publish it once your verification is approved."}</p>
      {msg && <Alert tone="bad" className="mt-3">{msg}</Alert>}
      <Button className="mt-4" variant={isPublic ? "secondary" : "primary"} loading={busy} disabled={!approved && !isPublic} onClick={() => void toggle()}>
        {isPublic ? "Make my profile private" : "Publish my profile"}
      </Button>
      {!approved && !isPublic && <p className="mt-2 text-sm text-ink-soft">Available after approval.</p>}
    </Card>
  );
}
