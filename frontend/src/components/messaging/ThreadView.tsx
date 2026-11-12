"use client";

import { useState, type FormEvent } from "react";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/format";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Field";

export type ThreadMessage = { id: string; sender: "donor" | "recipient"; body: string; status: "approved" | "pending" | "rejected"; created_at: string };

type Props = {
  messages: ThreadMessage[];
  /** Who is looking at this thread. Their own messages sit on the right. */
  viewerRole: "donor" | "recipient";
  /** False until the gift has been delivered (thread_open). */
  canPost: boolean;
  /** Shown instead of the composer when canPost is false. */
  lockedText?: string;
  /** Sends the message. Throw the ApiError from lib/api so moderation reasons are shown. */
  onSend: (body: string) => Promise<void>;
  otherPartyLabel: string; // e.g. "A SadQah donor" or the recipient's public name
};

/** Platform-moderated private conversation. A rejected message was reviewed and not delivered; it stays visible to its sender only. */
export function ThreadView({ messages, viewerRole, canPost, lockedText, onSend, otherPartyLabel }: Props) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const body = draft.trim();
    if (!body) return;
    setSending(true);
    setError(null);
    try {
      await onSend(body);
      setDraft("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Your message could not be sent. Please try again.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div>
      <ol className="space-y-3" aria-label={`Conversation with ${otherPartyLabel}`}>
        {messages.length === 0 && <li className="text-ink-soft">No messages yet.</li>}
        {messages.map((m) => {
          const mine = m.sender === viewerRole;
          return (
            <li key={m.id} className={cn("flex", mine ? "justify-end" : "justify-start")}>
              <div className={cn("max-w-[85%] rounded-2xl px-4 py-3", mine ? "bg-lapis-900 text-white" : "bg-white ring-1 ring-line")}>
                <p className="whitespace-pre-wrap break-words">{m.body}</p>
                <p className={cn("mt-1 text-sm", mine ? "text-lapis-100" : "text-ink-soft")}>
                  {mine ? "You" : otherPartyLabel} · {timeAgo(m.created_at)}
                  {m.status === "pending" && " · waiting for review"}
                  {m.status === "rejected" && " · Not delivered"}
                </p>
              </div>
            </li>
          );
        })}
      </ol>

      {canPost ? (
        <form onSubmit={submit} className="mt-5 space-y-3">
          <Textarea
            label="Write a message"
            hint="Messages are reviewed before they are delivered. Please do not share phone numbers, emails, links or payment details."
            value={draft}
            maxLength={1000}
            onChange={(e) => setDraft(e.target.value)}
            error={error}
          />
          <Button type="submit" loading={sending} disabled={!draft.trim()}>
            Send message
          </Button>
        </form>
      ) : (
        <Alert tone="info" className="mt-5">
          {lockedText ?? "Messaging opens once the gift has been delivered."}
        </Alert>
      )}
    </div>
  );
}
