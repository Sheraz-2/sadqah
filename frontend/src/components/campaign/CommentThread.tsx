"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { ApiError, post } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useAuth } from "@/hooks/useAuth";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Field";
import type { CampaignDetail } from "@/types/api";

type Props = { slug: string; comments: CampaignDetail["comments"]; onPosted: () => void };

/** Kind words under a campaign. Signed-in people only; every comment is screened (no contact details) before it shows. */
export function CommentThread({ slug, comments, onPosted }: Props) {
  const { me, loading } = useAuth();
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const body = draft.trim();
    if (!body) return;
    setSending(true);
    setError(null);
    setNotice(null);
    try {
      const res = await post<{ id: string; status: "approved" | "pending" }>(`/campaigns/${slug}/comments`, { body });
      setDraft("");
      setNotice(res.status === "approved" ? "Thank you. Your comment is up." : "Thank you. Your comment will appear once it has been reviewed.");
      onPosted();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Your comment could not be posted. Please try again.");
    } finally {
      setSending(false);
    }
  }

  return (
    <section aria-labelledby="comments-h">
      <h2 id="comments-h" className="text-3xl font-semibold">
        Kind words
      </h2>
      <ol className="mt-5 space-y-4">
        {comments.length === 0 && <li className="text-ink-soft">No comments yet. Be the first to write something kind.</li>}
        {comments.map((c) => (
          <li key={c.id} className="rounded-2xl bg-paper p-5 ring-1 ring-line">
            <p className="whitespace-pre-wrap break-words">{c.body}</p>
            {c.media_url && <img src={c.media_url} alt="Attached to the comment" loading="lazy" className="mt-3 max-h-72 rounded-xl" />}
            <p className="mt-2 text-sm text-ink-soft">
              {c.author_name} · {timeAgo(c.created_at)}
            </p>
          </li>
        ))}
      </ol>

      <div className="mt-6">
        {loading ? null : me ? (
          <form onSubmit={submit} className="space-y-3">
            <Textarea
              label="Leave a comment"
              hint="Please don't share links, phone numbers or e-mail addresses. Comments are screened first."
              value={draft}
              maxLength={1000}
              onChange={(e) => setDraft(e.target.value)}
              error={error}
            />
            {notice && <Alert tone="ok">{notice}</Alert>}
            <Button type="submit" loading={sending} disabled={!draft.trim()}>
              Post comment
            </Button>
          </form>
        ) : (
          <Alert tone="info">
            <Link href={`/login?next=${encodeURIComponent(`/campaigns/${slug}`)}`} className="font-semibold underline">
              Sign in
            </Link>{" "}
            to leave a comment.
          </Alert>
        )}
      </div>
    </section>
  );
}
