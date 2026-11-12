"use client";

import Link from "next/link";
import { useState } from "react";
import { get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { useRequireRole } from "@/hooks/useRequireRole";
import { ThreadView } from "@/components/messaging/ThreadView";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import type { DonorThread, DonorThreadMessage } from "@/types/api";

const NOT_OPEN = "Messaging will open once your gift has been delivered.";

export default function DonorMessagesPage() {
  const me = useRequireRole("donor");
  return (
    <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6">
      <p><Link href="/dashboard" className="font-semibold underline">Back to my giving</Link></p>
      <h1 className="mt-4 text-4xl font-bold sm:text-5xl">Messages</h1>
      <p className="mt-3 max-w-2xl text-lg text-ink-soft">
        Private conversations about the gifts you gave publicly. The recipient can see the public name on your account, and every message is reviewed before it is delivered.
        Gifts you gave anonymously are not linked to this account: follow those with your token on the <Link href="/track" className="font-semibold underline">Track page</Link>.
      </p>
      <div className="mt-8">{me ? <Threads /> : <Spinner label="Loading your messages" />}</div>
    </div>
  );
}

function Threads() {
  const list = useAsync((s) => get<{ items: DonorThread[] }>("/me/threads", s), []);
  const [open, setOpen] = useState<string | null>(null);

  if (list.loading && !list.data) return <Spinner label="Loading conversations" />;
  if (list.error && !list.data) return <Alert tone="bad">We could not load your conversations. Please refresh.</Alert>;
  const items = list.data?.items ?? [];
  if (items.length === 0) return <Alert tone="info">No conversations yet. They appear here once you have given a public gift.</Alert>;

  return (
    <div className="grid gap-6 md:grid-cols-[18rem_1fr]">
      <ul aria-label="Conversations" className="space-y-2">
        {items.map((t) => (
          <li key={t.donation_id}>
            <button type="button" aria-current={open === t.donation_id} onClick={() => setOpen(t.donation_id)} className={cn("w-full rounded-2xl p-4 text-left ring-1", open === t.donation_id ? "bg-lapis-50 ring-lapis-500" : "bg-paper ring-line hover:bg-lapis-50")}>
              <span className="flex items-center justify-between gap-2">
                <span className="font-semibold">{t.recipient_name}</span>
                {t.unread_count > 0 && <Badge tone="info">{t.unread_count} new</Badge>}
              </span>
              <span className="block text-sm text-ink-soft">{t.campaign_title}</span>
              <span className="block text-sm text-ink-soft">
                {t.thread_open ? (t.last_message_at ? `Last message ${timeAgo(t.last_message_at)}` : "No messages yet") : "Opens once your gift is delivered"}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <div>{open ? <ThreadPane key={open} id={open} onRead={() => void list.reload()} /> : <p className="text-ink-soft">Choose a conversation.</p>}</div>
    </div>
  );
}

function ThreadPane({ id, onRead }: { id: string; onRead: () => void }) {
  const t = useAsync(async (s) => {
    const r = await get<{ thread: DonorThread; messages: DonorThreadMessage[] }>(`/me/threads/${id}`, s);
    onRead();
    return r;
  }, [id]);
  if (t.loading && !t.data) return <Spinner label="Loading messages" />;
  if (t.error && !t.data) return <Alert tone="bad">{t.error}</Alert>;
  const thread = t.data?.thread;
  return (
    <div>
      {thread && (
        <p className="mb-4 text-ink-soft">
          {thread.campaign_title} · {thread.donation_status === "paid_out" ? "Delivered" : "Gift received, not yet delivered"}
        </p>
      )}
      <ThreadView
        messages={t.data?.messages ?? []}
        viewerRole="donor"
        canPost={Boolean(thread?.thread_open)}
        lockedText={NOT_OPEN}
        otherPartyLabel={thread?.recipient_name ?? "The recipient"}
        onSend={async (body) => {
          await post(`/me/threads/${id}/messages`, { body });
          await t.reload();
        }}
      />
    </div>
  );
}
