"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { homeFor, useAuth } from "@/hooks/useAuth";
import type { Me, Role } from "@/types/api";

/** The signed-in person if they hold one of `roles`; otherwise sends them to sign in or to their own home and returns null. */
export function useRequireRole(...roles: Role[]): Me | null {
  const { me, loading } = useAuth();
  const router = useRouter();
  const path = usePathname();
  useEffect(() => {
    if (loading) return;
    if (!me) router.replace(`/login?next=${encodeURIComponent(path)}`);
    else if (!roles.includes(me.role)) router.replace(homeFor(me.role));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me, loading, path, router]);
  return me && roles.includes(me.role) ? me : null;
}
