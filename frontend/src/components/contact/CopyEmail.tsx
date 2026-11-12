"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { SUPPORT_EMAIL } from "@/lib/contact";

type State = "idle" | "copied" | "failed";

/** "Copy email address" with feedback that screen readers announce (a polite live region that is always in the page). */
export function CopyEmail() {
  const [state, setState] = useState<State>("idle");
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function copy() {
    window.clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(SUPPORT_EMAIL);
      setState("copied");
    } catch {
      setState("failed"); // no clipboard permission or an insecure page: the address is on screen and can be selected by hand
    }
    timer.current = window.setTimeout(() => setState("idle"), 4000);
  }

  return (
    <>
      <Button type="button" variant="secondary" size="lg" onClick={() => void copy()}>
        {state === "copied" ? "Copied" : "Copy email address"}
      </Button>
      <p role="status" aria-live="polite" className="basis-full text-sm font-medium text-ink-soft">
        {state === "copied" && `Copied ${SUPPORT_EMAIL} to the clipboard.`}
        {state === "failed" && "Could not copy automatically. Please select the address above and copy it."}
      </p>
    </>
  );
}
