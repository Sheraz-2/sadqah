"use client";

import { useRef, useState } from "react";
import { ApiError, upload } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import type { KycDocType } from "@/types/api";

const MAX_BYTES = 10 * 1024 * 1024;
const TYPES = ["image/jpeg", "image/png", "application/pdf"];

type Existing = { uploaded_at: string; scan_status: "pending" | "clean" | "infected" | "failed" } | undefined;

/** Why this file cannot be uploaded, or null. The server checks again (and re-encodes) regardless. */
export function fileProblem(file: { type: string; size: number }, imageOnly: boolean): string | null {
  if (file.size > MAX_BYTES) return "That file is larger than 10 MB. Please choose a smaller one.";
  const ok = imageOnly ? TYPES.slice(0, 2) : TYPES;
  if (!ok.includes(file.type)) return imageOnly ? "Please use a JPG or PNG photo." : "Please use a JPG, PNG or PDF file.";
  return null;
}

export function DocumentUploader({
  docType,
  label,
  help,
  existing,
  disabled,
  challengeToken,
  imageOnly,
  camera,
  onUploaded,
}: {
  docType: KycDocType;
  label: string;
  help?: string;
  existing: Existing;
  disabled?: boolean;
  /** Required for selfies: the signed liveness challenge. */
  challengeToken?: string | null;
  imageOnly?: boolean;
  camera?: boolean;
  onUploaded: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<File | null>(null);

  async function send(file: File) {
    const problem = fileProblem(file, !!imageOnly);
    if (problem) return setError(problem);
    if (docType === "selfie" && !challengeToken) return setError("Get your code first, then take the photo.");
    setBusy(true);
    setError(null);
    setLast(file);
    try {
      const form = new FormData();
      form.set("doc_type", docType);
      form.set("file", file);
      if (challengeToken) form.set("challenge_token", challengeToken);
      await upload(`/recipient/kyc/documents`, form);
      setLast(null);
      onUploaded();
    } catch (err) {
      setError(err instanceof ApiError ? err.fields?.file ?? err.fields?.challenge_token ?? err.message : "The upload failed. Please try again.");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  const status = existing?.scan_status;
  return (
    <div className="rounded-2xl bg-paper p-4 ring-1 ring-line">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-semibold">{label}</p>
          {help && <p className="text-sm text-ink-soft">{help}</p>}
        </div>
        {existing ? (
          <Badge tone={status === "infected" || status === "failed" ? "bad" : status === "clean" ? "ok" : "info"}>
            {status === "clean" ? "Checked" : status === "pending" ? "Uploaded, being checked" : status === "infected" ? "Rejected by security check" : "Check failed"}
          </Badge>
        ) : (
          <Badge>Not uploaded</Badge>
        )}
      </div>
      {existing && <p className="mt-1 text-sm text-ink-soft">Uploaded {formatDate(existing.uploaded_at)}</p>}
      {error && (
        <Alert tone="bad" className="mt-3">
          {error}
          {last && (
            <Button size="sm" variant="secondary" className="ml-3" onClick={() => void send(last)}>
              Retry
            </Button>
          )}
        </Alert>
      )}
      <input
        ref={input}
        type="file"
        accept={imageOnly ? "image/jpeg,image/png" : "image/jpeg,image/png,application/pdf"}
        capture={camera ? "user" : undefined}
        className="sr-only"
        id={`file-${docType}`}
        aria-label={`Choose a file for ${label}`}
        disabled={disabled || busy}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void send(f);
        }}
      />
      <Button type="button" variant="secondary" size="sm" className="mt-3" loading={busy} disabled={disabled} onClick={() => input.current?.click()}>
        {existing ? "Replace" : camera ? "Take photo" : "Choose file"}
      </Button>
    </div>
  );
}
