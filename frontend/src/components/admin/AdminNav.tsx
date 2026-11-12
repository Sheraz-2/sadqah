"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import type { Role } from "@/types/api";

const TABS = [
  { href: "/admin", label: "To do" },
  { href: "/admin/kyc", label: "Verification" },
  { href: "/admin/payouts", label: "Payouts" },
  { href: "/admin/ledger", label: "Ledger" },
  { href: "/admin/reconciliation", label: "Reconciliation" },
  { href: "/admin/moderation", label: "Moderation" },
  { href: "/admin/needs", label: "Needs checks" },
  { href: "/admin/reports", label: "Reports" },
  { href: "/admin/recovery", label: "Password resets", adminOnly: true },
];

export function AdminNav({ role }: { role: Role }) {
  const path = usePathname();
  return (
    <nav aria-label="Staff console" className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
      <ul className="flex items-center gap-2 whitespace-nowrap">
        {TABS.filter((t) => !("adminOnly" in t && t.adminOnly) || role === "admin").map((t) => {
          const on = t.href === "/admin" ? path === t.href : path.startsWith(t.href);
          return (
            <li key={t.href}>
              <Link href={t.href} aria-current={on ? "page" : undefined} className={cn("inline-flex h-10 items-center rounded-full px-4 font-medium", on ? "bg-lapis-900 text-white" : "bg-white text-ink-soft ring-1 ring-line hover:bg-lapis-50")}>
                {t.label}
              </Link>
            </li>
          );
        })}
        <li className="ml-auto pl-4 text-sm text-ink-soft">{role === "admin" ? "Administrator" : "Reviewer"}</li>
      </ul>
    </nav>
  );
}
