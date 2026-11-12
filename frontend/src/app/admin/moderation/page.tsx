"use client";

import { useEffect, useState, type ReactNode } from "react";
import { ApiError, get, post } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import type { QueuedGratitude, QueuedMessage } from "@/types/admin";

export default function ModerationPage() {
  return (
    <div className="space-y-12">
      <h1 className="text-4xl font-bold">Moderation</h1>
      <p className="max-w-2xl text-ink-soft">Anonymous messages and thank-yous wait here. Approve what is kind and safe. Reject contact details, requests for money, personal questions and anything unkind. You never see who wrote what.</p>
      <Queue<QueuedMessage> title="Messages" path="messages" render={(m) => <><Badge>{m.sender === "donor" ? "from a donor" : "from a recipient"}</Badge><p className="mt-2 whitespace-pre-wrap break-words">{m.body}</p></>} />
      <Queue<QueuedGratitude> title="Thank-yous" path="gratitude" render={(g) => <><Badge>{g.is_community ? "to the community" : "to a donor"}</Badge><p className="mt-2 whitespace-pre-wrap break-words">{g.body}</p></>} />
    </div>
  );
}

function Queue<T extends { id: string; created_at: string }>({ title, path, render }: { title: string; path: "messages" | "gratitude"; render: (item: T) => ReactNode }) {
  const [items, setItems] = useState<T[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    get<{ items: T[] }>(`/admin/moderation/${path}`).then((r) => live && setItems(r.items)).catch((e) => live && setError(e instanceof ApiError ? e.message : "Could not load."));
    return () => { live = false; };
  }, [path]);

  // Optimistic: the card leaves at once; if the server refuses, it comes back with an explanation.
  async function decide(item: T, decision: "approved" | "rejected") {
    const before = items;
    setItems((cur) => (cur ?? []).filter((i) => i.id !== item.id));
    setError(null);
    try {
      await post(`/admin/moderation/${path}/${item.id}`, { decision });
    } catch (err) {
      setItems(before);
      setError(err instanceof ApiError ? err.message : "That decision could not be saved. It was put back in the queue.");
    }
  }

  return (
    <section aria-labelledby={`${path}-h`}>
      <h2 id={`${path}-h`} className="text-2xl font-semibold">{title} {items && <Badge tone={items.length ? "warn" : "ok"}>{items.length} waiting</Badge>}</h2>
      {error && <Alert tone="bad" className="mt-3">{error}</Alert>}
      {items === null && !error ? <Spinner label="Loading" /> : items && items.length === 0 ? <p className="mt-3 text-ink-soft">Nothing waiting.</p> : (
        <ul className="mt-4 space-y-3">
          {items?.map((i) => (
            <li key={i.id}>
              <Card className="p-5">
                {render(i)}
                <p className="mt-2 text-sm text-ink-soft">{timeAgo(i.created_at)}</p>
                <div className="mt-3 flex gap-2">
                  <Button size="sm" onClick={() => void decide(i, "approved")}>Approve</Button>
                  <Button size="sm" variant="danger" onClick={() => void decide(i, "rejected")}>Reject</Button>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
