"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { usePrefs, setPrefs } from "@/lib/prefs";
import { VOICE_LANGS, canSpeak, speak, stopSpeaking, useDictation } from "@/lib/speech";
import { useAuth } from "@/hooks/useAuth";

type Msg = { role: "user" | "assistant"; content: string; ai?: boolean; error?: boolean };

/** How long to wait for a reply before giving up with a message the person can act on (the local model can be slow on a CPU). */
const REPLY_TIMEOUT_MS = 150_000;
const SLOW_HINT_MS = 12_000;

const PAGES = [
  "/recipient/verify", "/recipient/profile", "/recipient/campaign", "/recipient/messages", "/recipient/thanks", "/recipient/needs",
  "/recipient", "/campaigns", "/leaderboard", "/dashboard", "/settings", "/about", "/track", "/trust", "/login", "/register", "/give", "/contact",
];
const PAGE_RE = new RegExp(`(${PAGES.map((p) => p.replace(/\//g, "\\/")).join("|")})(?![\\w/-])`, "g");

/** Plain text with internal page paths turned into links. Never renders HTML from the model. */
function Rich({ text, onNavigate }: { text: string; onNavigate: () => void }): ReactNode {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(PAGE_RE)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    out.push(
      <Link key={at} href={m[0]} onClick={onNavigate} className="font-semibold text-lapis-700 underline underline-offset-2">
        {m[0]}
      </Link>,
    );
    last = at + m[0].length;
  }
  out.push(text.slice(last));
  return <>{out}</>;
}

const SUGGEST: Record<string, string[]> = {
  guest: ["How do I give anonymously?", "How do I track my gift?", "I cannot sign in", "Is my donation safe?"],
  donor: ["Where is my gift now?", "How do I stay anonymous?", "How do I delete my account?", "How do I report a campaign?"],
  recipient: ["How do I get verified?", "What proof do I need for my list?", "Why was my request not approved yet?", "How do I delete my account?"],
  staff: ["How do the needs checks work?", "Where do I see reports?"],
};

export function AssistantWidget() {
  const { me } = useAuth();
  const path = usePathname() || "/";
  const prefs = usePrefs();
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [slow, setSlow] = useState(false);
  const inflight = useRef(false);               // a ref, so a double Enter / double click cannot send twice before React re-renders
  const abort = useRef<AbortController | null>(null);
  const log = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const role = me ? (me.role === "donor" || me.role === "recipient" ? me.role : "staff") : "guest";

  const dictation = useDictation(prefs.voiceLang, (t, final) => {
    setText(t);
    if (final) input.current?.focus();
  });

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight, behavior: "smooth" });
  }, [msgs, busy, open]);

  useEffect(() => {
    if (open) input.current?.focus();
    else stopSpeaking();
  }, [open]);

  // While open: Escape closes (and returns focus to the launcher); a press outside the launcher + panel closes too. One effect, one pair of
  // listeners, removed on close and on unmount. The launcher and panel share `root`, so pressing the launcher is "inside" (its own onClick
  // toggles) and pressing inside the panel never closes it. composedPath() is used because a clicked element can be removed from the DOM
  // (e.g. a suggestion button) before the event reaches the document.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        root.current?.querySelector<HTMLButtonElement>("[data-launcher]")?.focus();
      }
    };
    const onPress = (e: PointerEvent) => {
      const el = root.current;
      if (el && !e.composedPath().includes(el)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPress);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPress);
    };
  }, [open]);

  useEffect(() => {
    if (!busy) {
      setSlow(false);
      return;
    }
    const t = setTimeout(() => setSlow(true), SLOW_HINT_MS);
    return () => clearTimeout(t);
  }, [busy]);

  useEffect(() => () => abort.current?.abort(), []);   // leaving the page cancels a request that is still waiting

  async function send(raw: string) {
    const content = raw.trim().slice(0, 2000);
    if (!content || inflight.current) return;
    inflight.current = true;
    dictation.stop();
    const next: Msg[] = [...msgs, { role: "user", content }];
    setMsgs(next);
    setText("");
    setBusy(true);
    const ctrl = new AbortController();
    abort.current = ctrl;
    const timer = setTimeout(() => ctrl.abort(), REPLY_TIMEOUT_MS);
    try {
      // The server makes the history valid (alternation, size). Here we only leave out what is not part of the conversation:
      // our own error notices. The newest 12 stay within the API's limit of 14.
      const history = next.filter((m) => !m.error).slice(-12).map(({ role: r, content: c }) => ({ role: r, content: c }));
      const res = await api<{ reply: string; ai: boolean }>("/assistant/chat", { method: "POST", body: { messages: history, page: path }, signal: ctrl.signal });
      setMsgs((m) => [...m, { role: "assistant", content: res.reply, ai: res.ai }]);
      if (prefs.speakReplies) speak(res.reply, prefs.voiceLang);
    } catch (err) {
      const timedOut = (err as Error).name === "AbortError";
      const note = timedOut ? "That took too long, so I stopped waiting. Please try again, or ask a shorter question." : errorMessage(err);
      setMsgs((m) => [...m, { role: "assistant", content: note, ai: false, error: true }]);
    } finally {
      clearTimeout(timer);
      abort.current = null;
      inflight.current = false;
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(text);
  }

  return (
    <div ref={root} className="print:hidden">
      <button
        type="button"
        data-launcher
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls="sq-assistant"
        className="fixed bottom-4 right-4 z-40 flex h-14 items-center gap-2 rounded-full bg-lapis-900 px-4 text-white shadow-[var(--shadow-lift)] ring-1 ring-white/10 hover:bg-lapis-700 sm:px-5"
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z" />
          <path d="M9 11h.01M12 11h.01M15 11h.01" />
        </svg>
        <span className="hidden font-semibold sm:inline">{open ? "Close" : "Ask SadQah"}</span>
        <span className="sr-only sm:hidden">{open ? "Close assistant" : "Open assistant"}</span>
      </button>

      {open && (
        <section
          id="sq-assistant"
          role="dialog"
          aria-labelledby={titleId}
          className="fixed bottom-20 right-4 z-40 flex h-[min(36rem,calc(100dvh-7rem))] w-[min(26rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl bg-white shadow-[var(--shadow-lift)] ring-1 ring-line"
        >
          <header className="flex items-center gap-2 border-b border-line bg-lapis-900 px-4 py-3 text-white">
            <div className="min-w-0 flex-1">
              <h2 id={titleId} className="font-display text-lg font-semibold leading-tight">SadQah assistant</h2>
              <p className="text-xs text-lapis-100">AI guide in your language. A person makes every final decision.</p>
            </div>
            <label className="sr-only" htmlFor="sq-voice-lang">Language for voice</label>
            <select
              id="sq-voice-lang"
              value={prefs.voiceLang}
              onChange={(e) => setPrefs({ voiceLang: e.target.value })}
              className="max-w-[8.5rem] truncate rounded-lg border-0 bg-white/10 px-2 py-1.5 text-sm text-white ring-1 ring-white/25 focus:ring-2 [&>option]:text-ink"
            >
              {VOICE_LANGS.map((l) => (
                <option key={l.tag} value={l.tag}>{l.label}</option>
              ))}
            </select>
            {canSpeak() && (
              <button
                type="button"
                onClick={() => {
                  if (prefs.speakReplies) stopSpeaking();
                  setPrefs({ speakReplies: !prefs.speakReplies });
                }}
                aria-pressed={prefs.speakReplies}
                aria-label="Read answers aloud"
                title="Read answers aloud"
                className={cn("grid size-9 place-items-center rounded-full ring-1 ring-white/25", prefs.speakReplies ? "bg-saffron-400 text-lapis-900" : "hover:bg-white/10")}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="M11 5 6 9H3v6h3l5 4V5Z" />
                  <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
                </svg>
              </button>
            )}
          </header>

          <div ref={log} role="log" aria-live="polite" aria-relevant="additions" className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {msgs.length === 0 && (
              <div className="space-y-3">
                <p className="text-ink">
                  Hello! I can help if you are stuck or unsure. Ask in any language, by typing{dictation.supported ? " or with the microphone" : ""}.
                </p>
                {role === "recipient" && (
                  <Link href="/recipient/needs" onClick={() => setOpen(false)} className="block rounded-xl bg-tile-50 px-3 py-2 font-medium text-tile-700 ring-1 ring-tile-500/30 hover:bg-tile-50/70">
                    Price-check what you need and attach proof →
                  </Link>
                )}
                <div className="flex flex-wrap gap-2">
                  {(SUGGEST[role] ?? SUGGEST.guest).map((s) => (
                    <button key={s} type="button" onClick={() => void send(s)} className="rounded-full bg-lapis-50 px-3 py-1.5 text-sm font-medium text-lapis-900 ring-1 ring-line hover:bg-lapis-100">
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                <div
                  className={cn(
                    "max-w-[88%] whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2.5 text-[0.95rem] leading-relaxed",
                    m.role === "user" ? "bg-lapis-900 text-white" : "bg-lapis-50 text-ink ring-1 ring-line",
                  )}
                  dir="auto"
                >
                  {m.role === "assistant" ? <Rich text={m.content} onNavigate={() => setOpen(false)} /> : m.content}
                  {m.role === "assistant" && m.ai === false && !m.error && (
                    <p className="mt-1.5 text-xs text-ink-soft">Quick answer from SadQah&apos;s built-in help. The AI did not answer this one.</p>
                  )}
                </div>
              </div>
            ))}
            {busy && (
              <div className="flex justify-start" aria-label="The assistant is typing">
                <div className="rounded-2xl bg-lapis-50 px-3.5 py-2.5 text-ink-soft ring-1 ring-line">
                  Thinking…
                  {slow && <span className="mt-1 block text-xs">Still working. The AI runs on this computer and can take up to a minute or two.</span>}
                </div>
              </div>
            )}
          </div>

          <form onSubmit={onSubmit} className="border-t border-line bg-paper p-3">
            {dictation.error && <p role="alert" className="mb-2 text-sm font-medium text-bad">{dictation.error}</p>}
            <div className="flex items-end gap-2">
              <label htmlFor="sq-assistant-input" className="sr-only">Your message</label>
              <textarea
                id="sq-assistant-input"
                ref={input}
                value={text}
                rows={1}
                maxLength={2000}
                dir="auto"
                placeholder={dictation.listening ? "Listening…" : "Type your question…"}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send(text);
                  }
                }}
                className="max-h-28 min-h-11 flex-1 resize-none rounded-xl border-0 bg-white px-3 py-2.5 text-base ring-1 ring-inset ring-line placeholder:text-ink-soft/60 focus:ring-2 focus:ring-lapis-500"
              />
              {dictation.supported && (
                <button
                  type="button"
                  onClick={() => (dictation.listening ? dictation.stop() : dictation.start())}
                  aria-pressed={dictation.listening}
                  aria-label={dictation.listening ? "Stop listening" : "Speak your question"}
                  className={cn("grid size-11 shrink-0 place-items-center rounded-full ring-1 ring-line", dictation.listening ? "animate-pulse bg-pomegranate-500 text-white" : "bg-white text-lapis-900 hover:bg-lapis-50")}
                >
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <rect x="9" y="3" width="6" height="12" rx="3" />
                    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
                  </svg>
                </button>
              )}
              <button type="submit" disabled={busy || !text.trim()} aria-label="Send" className="grid size-11 shrink-0 place-items-center rounded-full bg-lapis-900 text-white hover:bg-lapis-700 disabled:opacity-50">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" />
                </svg>
              </button>
            </div>
            <p className="mt-2 text-xs text-ink-soft">
              AI can make mistakes. Never share passwords, card or ID numbers.{dictation.supported ? " Voice typing is handled by your browser, which may send audio to its speech service." : ""}
            </p>
          </form>
        </section>
      )}
    </div>
  );
}
