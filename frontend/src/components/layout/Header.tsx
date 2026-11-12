"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth, homeFor } from "@/hooks/useAuth";
import { Star } from "@/components/ui/Star";
import { buttonClass } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import { applyPrefs, getPrefs } from "@/lib/prefs";
import { SettingsMenu } from "@/components/layout/SettingsMenu";
import { AssistantWidget } from "@/components/assistant/AssistantWidget";

/* ----------------------------------------------------------------------------
   Menu model. Every top-level tab has a dropdown of sub-sections.
   `href` of the tab itself is where a plain click goes; the dropdown opens on
   hover, keyboard focus, or the little arrow button (touch / keyboard users).
---------------------------------------------------------------------------- */
type SubLink = { href: string; label: string; hint: string };
type Tab = { key: string; href: string; label: string; blurb: string; links: SubLink[] };

const TABS: Tab[] = [
  {
    key: "campaigns",
    href: "/campaigns",
    label: "Campaigns",
    blurb: "Verified people you can give to directly.",
    links: [
      { href: "/campaigns", label: "All campaigns", hint: "Browse and search everyone" },
      { href: "/campaigns?sort=almost_funded", label: "Closest to goal", hint: "Help finish what is nearly done" },
      { href: "/campaigns?sort=most_supported", label: "Most supported", hint: "Where the community is giving" },
      { href: "/campaigns?sort=newest", label: "Newest", hint: "Just opened this week" },
      { href: "/campaigns?country=PK", label: "In Pakistan", hint: "Filter by country" },
      { href: "/campaigns?country=BD", label: "In Bangladesh", hint: "Filter by country" },
      { href: "/campaigns?country=KE", label: "In Kenya", hint: "Filter by country" },
    ],
  },
  {
    key: "give",
    href: "/give",
    label: "Giving calculator",
    blurb: "Work out a gift that fits your year.",
    links: [
      { href: "/give", label: "Plan my giving", hint: "Pick a share of your income" },
      { href: "/about#plan", label: "How the plan works", hint: "From 1% of your year, or any amount" },
      { href: "/about#guide-give", label: "What the calculator does", hint: "And what it does not" },
    ],
  },
  {
    key: "about",
    href: "/about",
    label: "About",
    blurb: "Why SadQah exists and how it works.",
    links: [
      { href: "/about", label: "Overview", hint: "The idea in one page" },
      { href: "/about#name", label: "The name", hint: "Where the word comes from" },
      { href: "/about#why", label: "Why give through SadQah", hint: "What is different here" },
      { href: "/about#guide", label: "A guide to every tab", hint: "What each part of the site is for" },
      { href: "/about#promise", label: "Our promise", hint: "Truth, privacy, dignity, a clear trail" },
      { href: "/trust", label: "Trust & transparency", hint: "Fees, timelines, refunds, how to report" },
    ],
  },
  {
    key: "leaderboard",
    href: "/leaderboard",
    label: "Leaderboard",
    blurb: "Public thank-you to open-handed givers.",
    links: [
      { href: "/leaderboard", label: "Top givers", hint: "Public gifts only" },
      { href: "/about#guide-leaderboard", label: "How it works", hint: "Anonymous gifts are never ranked" },
    ],
  },
  {
    key: "track",
    href: "/track",
    label: "Track a gift",
    blurb: "Follow a gift from you to the person.",
    links: [
      { href: "/track", label: "Track with a token", hint: "Paste your Donation Token" },
      { href: "/about#guide-track", label: "What is a Donation Token?", hint: "How anonymous gifts stay traceable" },
      { href: "/login", label: "Sign in to see all gifts", hint: "If you gave with an account" },
    ],
  },
];

/** A tab is "open" when the current page is the tab's page or lives beneath it. */
function isActive(pathname: string, href: string): boolean {
  const base = href.split(/[?#]/)[0];
  return pathname === base || pathname.startsWith(base + "/");
}

export function Logo({ className = "" }: { className?: string }) {
  return (
    <Link href="/" className={`flex items-center gap-2.5 ${className}`} aria-label="SadQah home">
      <Star className="size-8 text-saffron-400" />
      <span className="font-display text-2xl font-bold tracking-tight">SadQah</span>
    </Link>
  );
}

function Chevron({ open, className = "" }: { open: boolean; className?: string }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={cn("shrink-0 transition-transform duration-200", open && "rotate-180", className)}
    >
      <path d="M2.5 4.5 6 8l3.5-3.5" />
    </svg>
  );
}

/* ---------------------------------------------------------------- desktop */
function DesktopTab({
  tab,
  pathname,
  open,
  onOpen,
  onToggle,
  onScheduleClose,
  onCloseNow,
}: {
  tab: Tab;
  pathname: string;
  open: boolean;
  onOpen: (key: string) => void;
  onToggle: (key: string) => void;
  onScheduleClose: () => void;
  onCloseNow: () => void;
}) {
  const active = isActive(pathname, tab.href);
  const wrap = useRef<HTMLDivElement>(null);
  const toggler = useRef<HTMLButtonElement>(null);
  const panelId = `menu-${tab.key}`;

  return (
    <div
      ref={wrap}
      className="relative"
      onPointerEnter={(e) => e.pointerType === "mouse" && onOpen(tab.key)}
      onPointerLeave={(e) => e.pointerType === "mouse" && onScheduleClose()}
      onBlur={(e) => {
        if (!wrap.current?.contains(e.relatedTarget as Node | null)) onCloseNow();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.stopPropagation();
          onCloseNow();
          toggler.current?.focus();
        }
        if (e.key === "ArrowDown" && !open) {
          e.preventDefault();
          onOpen(tab.key);
        }
      }}
    >
      <div
        className={cn(
          "group/tab relative flex items-center rounded-full transition-colors duration-150",
          active ? "bg-lapis-900 text-white shadow-sm" : open ? "bg-lapis-50 text-lapis-900" : "text-ink-soft hover:bg-lapis-50 hover:text-lapis-900",
        )}
      >
        <Link
          href={tab.href}
          aria-current={active ? "page" : undefined}
          className="rounded-l-full py-2 pl-3.5 pr-1.5 text-base font-medium outline-offset-2"
          onClick={onCloseNow}
        >
          {tab.label}
        </Link>
        <button
          ref={toggler}
          type="button"
          aria-label={`${tab.label} sections`}
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => onToggle(tab.key)}
          className="flex h-9 w-7 items-center justify-center rounded-r-full pr-1 opacity-80 hover:opacity-100"
        >
          <Chevron open={open} />
        </button>
        {/* A saffron bar under the open tab: visible long after the pointer has left. */}
        {active && <span aria-hidden className="pointer-events-none absolute inset-x-5 -bottom-[7px] h-[3px] rounded-full bg-saffron-400" />}
      </div>

      {open && (
        <div
          id={panelId}
          role="group"
          aria-label={`${tab.label} sections`}
          className="absolute left-0 top-full z-40 w-80 pt-3 [animation:sq-pop_160ms_ease-out_both]"
        >
          <div className="rounded-2xl bg-white p-2 shadow-[var(--shadow-lift)] ring-1 ring-line">
            <p className="px-3 pb-1 pt-2 text-sm text-ink-soft">{tab.blurb}</p>
            <ul>
              {tab.links.map((l) => {
                const here = !/[?#]/.test(l.href) && pathname === l.href;
                return (
                  <li key={l.href}>
                    <Link
                      href={l.href}
                      onClick={onCloseNow}
                      aria-current={here ? "page" : undefined}
                      className={cn(
                        "block rounded-xl px-3 py-2.5 transition-colors hover:bg-lapis-50 focus-visible:bg-lapis-50",
                        here && "bg-lapis-50",
                      )}
                    >
                      <span className="block font-medium text-lapis-900">{l.label}</span>
                      <span className="block text-sm text-ink-soft">{l.hint}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

/* ----------------------------------------------------------------- header */
export function Header() {
  const { me, loading, logout } = useAuth();
  const pathname = usePathname() || "/";

  /* desktop dropdowns: one open at a time, short close delay so the pointer can travel into the panel */
  const [openKey, setOpenKey] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clear = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  /* "pinned" = opened by a click/tap/Enter on the arrow: stays open until closed, instead of closing when the pointer leaves. */
  const pinned = useRef(false);
  const current = useRef<string | null>(null);
  const show = (key: string | null) => {
    current.current = key;
    setOpenKey(key);
  };
  const open = useCallback((key: string) => {
    clear();
    if (current.current !== key) pinned.current = false;
    show(key);
  }, []);
  const closeNow = useCallback(() => {
    clear();
    pinned.current = false;
    show(null);
  }, []);
  const scheduleClose = useCallback(() => {
    clear();
    timer.current = setTimeout(() => {
      if (!pinned.current) show(null);
    }, 160);
  }, []);
  const toggle = useCallback((key: string) => {
    clear();
    if (current.current === key && !pinned.current) {
      pinned.current = true; // it was opened by hover: a click keeps it open
    } else if (current.current === key) {
      pinned.current = false;
      show(null);
    } else {
      pinned.current = true;
      show(key);
    }
  }, []);
  useEffect(() => clear, []);

  /* mobile menu */
  const details = useRef<HTMLDetailsElement>(null);
  const [mOpen, setMOpen] = useState<string | null>(null);

  /* Close everything whenever the route changes (including hash-only jumps are handled by link clicks). */
  useEffect(() => {
    closeNow();
    details.current?.removeAttribute("open");
    setMOpen(null);
  }, [pathname, closeNow]);

  /* Click or tap anywhere outside the open dropdown / mobile menu closes it. */
  useEffect(() => {
    function onDown(e: PointerEvent) {
      const t = e.target as Node;
      if (!(t instanceof Element) || !t.closest("[data-menu-root]")) {
        pinned.current = false;
        current.current = null;
        setOpenKey(null);
        details.current?.removeAttribute("open");
      }
    }
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, []);

  /* Apply the visitor's saved browser settings (text size, contrast, motion) once on load. */
  useEffect(() => applyPrefs(getPrefs()), []);

  const home = me ? homeFor(me.role) : null;
  const inAccount = home ? isActive(pathname, home) : false;

  return (
    <>
    <header className="sticky top-0 z-30 border-b border-line bg-salt/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Logo className="text-lapis-900" />

        <nav aria-label="Primary" data-menu-root className="hidden items-center gap-1 lg:flex">
          {TABS.map((t) => (
            <DesktopTab
              key={t.key}
              tab={t}
              pathname={pathname}
              open={openKey === t.key}
              onOpen={open}
              onToggle={toggle}
              onScheduleClose={scheduleClose}
              onCloseNow={closeNow}
            />
          ))}
        </nav>

        <div className="flex items-center gap-2">
          {!loading && me ? (
            <>
              <Link href={home!} aria-current={inAccount ? "page" : undefined} className={buttonClass("secondary", "sm", inAccount ? "ring-2 ring-saffron-400" : "")}>
                My {me.role === "donor" ? "giving" : me.role === "recipient" ? "portal" : "console"}
              </Link>
              <button type="button" onClick={() => void logout().then(() => (window.location.href = "/"))} className={buttonClass("ghost", "sm", "hidden sm:inline-flex")}>
                Sign out
              </button>
            </>
          ) : (
            <>
              <Link href="/login" className={buttonClass("ghost", "sm", "hidden sm:inline-flex")}>
                Sign in
              </Link>
              <Link href="/campaigns" className={buttonClass("give", "sm")}>
                Give now
              </Link>
            </>
          )}

          <SettingsMenu />

          <details ref={details} data-menu-root className="relative lg:hidden">
            <summary className="flex size-10 cursor-pointer list-none items-center justify-center rounded-full ring-1 ring-line [&::-webkit-details-marker]:hidden" aria-label="Menu">
              <svg width="20" height="20" viewBox="0 0 20 20" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
                <path d="M3 6h14M3 10h14M3 14h14" />
              </svg>
            </summary>
            <nav aria-label="Mobile" className="absolute right-0 mt-2 max-h-[78vh] w-[19rem] max-w-[calc(100vw-2rem)] overflow-y-auto rounded-2xl bg-white p-2 shadow-[var(--shadow-lift)] ring-1 ring-line">
              {TABS.map((t) => {
                const active = isActive(pathname, t.href);
                const isOpen = mOpen === t.key;
                return (
                  <div key={t.key} className="rounded-xl">
                    <div className={cn("flex items-center rounded-xl", active ? "bg-lapis-900 text-white" : "hover:bg-lapis-50")}>
                      <Link
                        href={t.href}
                        aria-current={active ? "page" : undefined}
                        onClick={() => details.current?.removeAttribute("open")}
                        className="flex-1 rounded-xl px-4 py-3 font-medium"
                      >
                        {t.label}
                      </Link>
                      <button
                        type="button"
                        aria-label={`${t.label} sections`}
                        aria-expanded={isOpen}
                        onClick={() => setMOpen(isOpen ? null : t.key)}
                        className="flex size-11 items-center justify-center rounded-xl"
                      >
                        <Chevron open={isOpen} className="size-3.5" />
                      </button>
                    </div>
                    {isOpen && (
                      <ul className="mb-1 ml-4 mt-1 border-l-2 border-saffron-400/70 pl-2">
                        {t.links.map((l) => (
                          <li key={l.href}>
                            <Link
                              href={l.href}
                              onClick={() => details.current?.removeAttribute("open")}
                              className="block rounded-lg px-3 py-2 hover:bg-lapis-50"
                            >
                              <span className="block text-[0.95rem] font-medium text-lapis-900">{l.label}</span>
                              <span className="block text-sm text-ink-soft">{l.hint}</span>
                            </Link>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                );
              })}
              {!me ? (
                <Link href="/login" onClick={() => details.current?.removeAttribute("open")} className="block rounded-xl px-4 py-3 font-medium hover:bg-lapis-50">
                  Sign in
                </Link>
              ) : (
                <button
                  type="button"
                  onClick={() => void logout().then(() => (window.location.href = "/"))}
                  className="block w-full rounded-xl px-4 py-3 text-left font-medium hover:bg-lapis-50 sm:hidden"
                >
                  Sign out
                </button>
              )}
            </nav>
          </details>
        </div>
      </div>
    </header>
    <AssistantWidget />
    </>
  );
}
