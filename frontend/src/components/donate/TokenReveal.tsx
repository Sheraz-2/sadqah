"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";

/** The Donation Token, grouped for reading aloud and copying. Shown exactly once: it is not stored on SadQah's side in a form we can show again. */
export function groupToken(token: string): string[] {
  return token.split("-");
}

/**
 * Full-screen, not dismissible by Esc or a stray click: the donor must confirm they saved it.
 * The token lives only in memory (props); nothing is written to storage or the URL.
 */
export function TokenReveal({ token, amountLabel, unconfirmed, onDone }: { token: string; amountLabel: string; unconfirmed?: boolean; onDone: () => void }) {
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const warn = (e: { preventDefault(): void; returnValue?: unknown }) => {
      e.preventDefault();
      e.returnValue = "";
    };
    if (!saved) window.addEventListener("beforeunload", warn as never);
    return () => window.removeEventListener("beforeunload", warn as never);
  }, [saved]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2500);
    } catch {
      setCopied(false); // the token is on screen: selecting it by hand always works
    }
  }

  function download() {
    const text = `SadQah Donation Token\n\n${token}\n\nKeep this safe. Anyone who has it can follow this gift. Track it at /track. SadQah cannot recover it for you.\n`;
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "sadqah-donation-token.txt";
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const parts = groupToken(token);
  return (
    <div role="alertdialog" aria-modal="true" aria-labelledby="token-h" aria-describedby="token-d" className="fixed inset-0 z-50 overflow-y-auto bg-lapis-900/95 p-4 backdrop-blur-sm">
      <div className="mx-auto my-8 max-w-xl rounded-3xl bg-white p-6 shadow-2xl sm:p-8">
        <p className="text-sm font-semibold uppercase tracking-wide text-tile-700">
          {unconfirmed ? `Your ${amountLabel} gift is not confirmed yet` : `Your ${amountLabel} gift was received`}
        </p>
        <h2 id="token-h" className="mt-1 text-3xl font-bold">
          Save your Donation Token
        </h2>
        <p id="token-d" className="mt-3 text-ink-soft">
          You gave anonymously, so there is no account to sign in to. This token is the only way to follow your gift and read a thank-you.
          <strong className="text-ink"> We cannot recover it and we cannot show it to you again.</strong>
        </p>
        {unconfirmed && (
          <p className="mt-3 rounded-xl bg-saffron-100 p-3 text-base">
            We could not confirm your payment just now. If PayPal charged you, the gift will show up shortly: use this token on the Track page to check. If it
            never appears, you were not charged.
          </p>
        )}

        <div className="mt-5 rounded-2xl bg-lapis-50 p-4 ring-1 ring-lapis-100">
          <p className="select-all break-all text-center font-mono text-lg font-semibold leading-relaxed tracking-wider text-lapis-900" aria-label="Donation Token">
            {parts.map((p, i) => (
              <span key={i}>
                {p}
                {i < parts.length - 1 && <span className="text-lapis-500">-</span>}
                {i < parts.length - 1 && <wbr />}
              </span>
            ))}
          </p>
        </div>

        <div className="mt-4 flex flex-wrap gap-3">
          <Button variant="secondary" onClick={() => void copy()}>
            {copied ? "Copied" : "Copy token"}
          </Button>
          <Button variant="secondary" onClick={download}>
            Download as a file
          </Button>
        </div>

        <label className="mt-6 flex cursor-pointer items-start gap-3 text-base">
          <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} className="mt-1 size-5 accent-[#1b4580]" />
          <span>I have saved my token somewhere safe, such as a password manager or a note only I can open.</span>
        </label>
        <Button className="mt-5 w-full" size="lg" disabled={!saved} onClick={onDone}>
          I&rsquo;ve saved it, continue
        </Button>
      </div>
    </div>
  );
}
