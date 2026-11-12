"use client";

import { useState } from "react";
import { get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatUsd, timeAgo } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { RecipientShell } from "@/components/recipient/RecipientNav";
import { ThreadView } from "@/components/messaging/ThreadView";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import type { Thread, ThreadMessageDto } from "@/types/recipient";

export default function MessagesPage() {
  return (
    <RecipientShell title="Messages" intro="Anonymous conversations with the people who gave to you. Neither side sees the other's identity, and every message is reviewed before it is delivered.">
      {() => <Threads />}
    </RecipientShell>
  );
}

function Threads() {
  const list = useAsync((s) => get<{ items: Thread[] }>("/recipient/threads", s), []);
  const [open, setOpen] = useState<string | null>(null);

  if (list.loading && !list.data) return <Spinner label="Loading conversations" />;
  if (list.error && !list.data) return <Alert tone="bad">We could not load your conversations.</Alert>;
  const items = list.data?.items ?? [];
  if (items.length === 0) return <Alert tone="info">Conversations open once a gift has been delivered to you. Nothing here yet.</Alert>;

  return (
    <div className="grid gap-6 md:grid-cols-[18rem_1fr]">
      <ul aria-label="Conversations" className="space-y-2">
        {items.map((t) => (
          <li key={t.thread_id}>
            <button type="button" aria-current={open === t.thread_id} onClick={() => setOpen(t.thread_id)} className={cn("w-full rounded-2xl p-4 text-left ring-1", open === t.thread_id ? "bg-lapis-50 ring-lapis-500" : "bg-paper ring-line hover:bg-lapis-50")}>
              <span className="flex items-center justify-between gap-2">
                <span className="font-semibold">{t.donor_label}</span>
                {t.unread_count > 0 && <Badge tone="info">{t.unread_count} new</Badge>}
              </span>
              <span className="block text-sm text-ink-soft">{formatUsd(t.amount_cents)}{t.last_message_at ? ` · ${timeAgo(t.last_message_at)}` : " · no messages yet"}</span>
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
    const r = await get<{ messages: ThreadMessageDto[] }>(`/recipient/threads/${id}`, s);
    onRead();
    return r;
  }, [id]);
  if (t.loading && !t.data) return <Spinner label="Loading messages" />;
  if (t.error && !t.data) return <Alert tone="bad">{t.error}</Alert>;
  return (
    <ThreadView
      messages={t.data?.messages ?? []}
      viewerRole="recipient"
      canPost
      otherPartyLabel="A SadQah donor"
      onSend={async (body) => {
        await post(`/recipient/threads/${id}/messages`, { body });
        await t.reload();
      }}
    />
  );
}
