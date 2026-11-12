import { homeFor } from "@/hooks/useAuth";
import type { Role } from "@/types/api";

/** `?next=` may only point inside this site: a relative path, never `//host` or a backslash trick. */
export function safeNext(raw: string | null | undefined): string | null {
  if (!raw) return null;
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.includes("\\") || /[\u0000-\u001f]/.test(raw)) return null;
  return raw;
}

export function landingFor(role: Role, next: string | null | undefined): string {
  return safeNext(next) ?? homeFor(role);
}
