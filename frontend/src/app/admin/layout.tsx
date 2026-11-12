"use client";

import type { ReactNode } from "react";
import { useRequireRole } from "@/hooks/useRequireRole";
import { AdminNav } from "@/components/admin/AdminNav";
import { Spinner } from "@/components/ui/Spinner";

/** Staff only (reviewer or admin). The API re-checks the role on every call; this just keeps the console out of sight. */
export default function AdminLayout({ children }: { children: ReactNode }) {
  const me = useRequireRole("reviewer", "admin");
  if (!me) return <div className="mx-auto max-w-6xl px-4 py-14"><Spinner label="Checking your access" /></div>;
  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <AdminNav role={me.role} />
      <div className="mt-8">{children}</div>
    </div>
  );
}
