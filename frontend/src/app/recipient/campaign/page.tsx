"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { ApiError, post, upload } from "@/lib/api";
import { formatUsd, parseDollarsToCents } from "@/lib/format";
import { RecipientShell } from "@/components/recipient/RecipientNav";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button, LinkButton } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Field";
import { ProgressBar } from "@/components/ui/ProgressBar";
import type { RecipientMe } from "@/types/api";

const MAX_IMAGES = 4;

export default function CampaignPage() {
  return (
    <RecipientShell title="Your campaign" intro="Your ask, and the updates that show donors where their gifts went.">
      {({ rme, reload }) => {
        if (rme.kyc?.status !== "approved")
          return (
            <Alert tone="info" title="Available after verification">
              You can create your campaign once your verification is approved.
              <div className="mt-3"><LinkButton href="/recipient/verify" size="sm">Go to verification</LinkButton></div>
            </Alert>
          );
        return rme.campaign ? <Live rme={rme} /> : <Create rme={rme} reload={reload} />;
      }}
    </RecipientShell>
  );
}

function Create({ rme, reload }: { rme: RecipientMe; reload: () => Promise<void> }) {
  const max = rme.kyc?.approved_allocation_cents ?? 0;
  const [title, setTitle] = useState("");
  const [story, setStory] = useState("");
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const cents = parseDollarsToCents(goal);
  const tooHigh = cents > max;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setFields({});
    try {
      await post("/recipient/campaign", { title, story, goal_cents: cents });
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
      <h2 className="text-2xl font-semibold">Create your campaign</h2>
      <p className="mt-1 text-ink-soft">You were approved for up to <strong>{formatUsd(max)}</strong>. Ask for what you truly need.</p>
      <form onSubmit={submit} className="mt-5 space-y-4">
        <Input label="Title" value={title} maxLength={120} required onChange={(e) => setTitle(e.target.value)} placeholder="e.g. A second-hand sewing machine" error={fields.title} />
        <Textarea label="Your story" rows={6} value={story} maxLength={4000} onChange={(e) => setStory(e.target.value)} hint="What the money will buy and how it will change your work." error={fields.story} />
        <Input label="Goal (USD)" inputMode="decimal" value={goal} onChange={(e) => setGoal(e.target.value)} error={tooHigh ? `Your goal can be at most ${formatUsd(max)}.` : fields.goal_cents} hint={`Between $1 and ${formatUsd(max)}`} />
        {error && <Alert tone="bad">{error}</Alert>}
        <Button type="submit" loading={busy} disabled={title.trim().length < 3 || cents < 100 || tooHigh}>Create campaign</Button>
      </form>
    </Card>
  );
}

function Live({ rme }: { rme: RecipientMe }) {
  const c = rme.campaign!;
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState<"public" | "donors">("public");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const form = new FormData();
      form.set("body", body);
      form.set("visibility", visibility);
      files.forEach((f) => form.append("images", f));
      await upload("/recipient/updates", form);
      setBody("");
      setFiles([]);
      setMsg({ tone: "ok", text: "Your update was posted." });
    } catch (err) {
      setMsg({ tone: "bad", text: err instanceof ApiError ? err.fields?.images ?? err.fields?.body ?? err.message : "Could not post your update." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-2xl font-semibold">{c.title}</h2>
          <Badge tone={c.status === "active" ? "ok" : "info"}>{c.status}</Badge>
        </div>
        <p className="mt-1 text-ink-soft">{formatUsd(c.raised_cents)} raised of {formatUsd(c.goal_cents)} · {formatUsd(c.paid_out_cents)} delivered to you</p>
        <ProgressBar className="mt-3" percent={c.goal_cents ? (c.raised_cents / c.goal_cents) * 100 : 0} />
        {rme.profile?.profile_public ? (
          <Link href={`/campaigns/${c.slug}`} className="mt-3 inline-block font-semibold text-lapis-700 underline">See it as donors do</Link>
        ) : (
          <Alert tone="warn" className="mt-4">Donors cannot see your campaign yet. <Link href="/recipient/profile" className="font-semibold underline">Publish your profile</Link>.</Alert>
        )}
      </Card>

      <Card>
        <h2 className="text-2xl font-semibold">Post an update</h2>
        <p className="mt-1 text-ink-soft">Show donors what their gifts are doing. Please do not include phone numbers, e-mail addresses or links.</p>
        <form onSubmit={submit} className="mt-5 space-y-4">
          <Textarea label="What happened?" rows={5} value={body} maxLength={4000} onChange={(e) => setBody(e.target.value)} required />
          <Select label="Who can see it?" value={visibility} onChange={(e) => setVisibility(e.target.value as "public" | "donors")}>
            <option value="public">Everyone, on the campaign page</option>
            <option value="donors">Donors only, through their tracking page</option>
          </Select>
          <div>
            <label htmlFor="upd-images" className="block text-base font-semibold">Photos (up to {MAX_IMAGES}, JPG, PNG or WebP)</label>
            <input id="upd-images" type="file" multiple accept="image/jpeg,image/png,image/webp" className="mt-2 block w-full text-base" onChange={(e) => setFiles(Array.from<File>(e.target.files ?? []).slice(0, MAX_IMAGES))} />
            {files.length > 0 && <p className="mt-1 text-sm text-ink-soft">{files.length} selected: {files.map((f) => f.name).join(", ")}</p>}
          </div>
          {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
          <Button type="submit" loading={busy} disabled={!body.trim()}>Post update</Button>
        </form>
      </Card>
    </div>
  );
}
