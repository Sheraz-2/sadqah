"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { get } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useAsync } from "@/hooks/useAsync";
import { useRequireRole } from "@/hooks/useRequireRole";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import type { RecipientMe } from "@/types/api";

const TABS = [
  { href: "/recipient", label: "Overview" },
  { href: "/recipient/profile", label: "Profile & payout" },
  { href: "/recipient/verify", label: "Verification" },
  { href: "/recipient/campaign", label: "Campaign" },
  { href: "/recipient/needs", label: "Needs & prices" },
  { href: "/recipient/messages", label: "Messages" },
  { href: "/recipient/thanks", label: "Thank-yous" },
];

export function RecipientNav() {
  const path = usePathname();
  return (
    <nav aria-label="Recipient portal" className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
      <ul className="flex gap-2 whitespace-nowrap">
        {TABS.map((t) => {
          const on = t.href === "/recipient" ? path === t.href : path.startsWith(t.href);
          return (
            <li key={t.href}>
              <Link href={t.href} aria-current={on ? "page" : undefined} className={cn("inline-flex h-10 items-center rounded-full px-4 font-medium", on ? "bg-lapis-900 text-white" : "bg-white text-ink-soft ring-1 ring-line hover:bg-lapis-50")}>
                {t.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export type ShellCtx = { rme: RecipientMe; reload: () => Promise<void> };

/** Page frame for every recipient screen: role guard, navigation, and one shared load of RecipientMe. */
export function RecipientShell({ title, intro, children }: { title: string; intro?: string; children: (ctx: ShellCtx) => ReactNode }) {
  const me = useRequireRole("recipient");
  const state = useAsync((s) => get<RecipientMe>("/recipient/me", s), [me?.id]);
  return (
    <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6">
      <h1 className="text-4xl font-bold sm:text-5xl">{title}</h1>
      {intro && <p className="mt-3 max-w-2xl text-lg text-ink-soft">{intro}</p>}
      <div className="mt-6">
        <RecipientNav />
      </div>
      <div className="mt-8">
        {!me || (state.loading && !state.data) ? (
          <Spinner label="Loading your portal" />
        ) : state.error && !state.data ? (
          <Alert tone="bad" title="We could not load your portal.">
            <Button variant="secondary" size="sm" className="mt-2" onClick={() => void state.reload()}>
              Try again
            </Button>
          </Alert>
        ) : state.data ? (
          children({ rme: state.data, reload: state.reload })
        ) : null}
      </div>
    </div>
  );
}
