"use client";

import { useSyncExternalStore } from "react";

/**
 * Browser preferences. Stored only in this browser (localStorage), never sent to the server, and applied to the page by
 * setting data-* attributes on <html> plus one small injected stylesheet. Everything has a safe default, and the site works
 * if storage is blocked.
 */
export type TextSize = "normal" | "large" | "xlarge";
export type Prefs = {
  text: TextSize;
  contrast: "normal" | "high";
  motion: "system" | "reduce";
  effects: "on" | "off"; // the cursor glow and hover lighting
  links: "normal" | "underline";
  voiceLang: string; // BCP-47 tag for the assistant's voice; "auto" follows the browser
  speakReplies: boolean; // read assistant answers aloud
};

export const DEFAULT_PREFS: Prefs = { text: "normal", contrast: "normal", motion: "system", effects: "on", links: "normal", voiceLang: "auto", speakReplies: false };
const KEY = "sq-prefs-v1";
const EVENT = "sq-prefs-change";

const STYLE = `
html[data-text="large"]{font-size:112.5%}
html[data-text="xlarge"]{font-size:125%}
html[data-contrast="high"]{--color-ink-soft:#1b2638;--color-line:#6b7a8c;--color-lapis-50:#dfe9f8;--color-saffron-400:#d89a12}
html[data-contrast="high"] :focus-visible{outline-width:4px}
html[data-links="underline"] a:not([class*="rounded-full"]):not([class*="rounded-xl"]){text-decoration:underline;text-underline-offset:3px}
html[data-motion="reduce"] *,html[data-motion="reduce"] *::before,html[data-motion="reduce"] *::after{animation-duration:.001ms!important;animation-iteration-count:1!important;transition-duration:.001ms!important;scroll-behavior:auto!important}
html[data-fx="off"] *{--mx:-9999px!important;--my:-9999px!important;--nx:0!important;--ny:0!important}
html[data-fx="off"] .sq-cursor-glow{display:none!important}
`;

function read(): Prefs {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULT_PREFS;
    const p = JSON.parse(raw) as Partial<Prefs>;
    return {
      text: p.text === "large" || p.text === "xlarge" ? p.text : "normal",
      contrast: p.contrast === "high" ? "high" : "normal",
      motion: p.motion === "reduce" ? "reduce" : "system",
      effects: p.effects === "off" ? "off" : "on",
      links: p.links === "underline" ? "underline" : "normal",
      voiceLang: typeof p.voiceLang === "string" && /^[a-zA-Z-]{2,12}$|^auto$/.test(p.voiceLang) ? p.voiceLang : "auto",
      speakReplies: p.speakReplies === true,
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

let cache: Prefs | null = null;
export function getPrefs(): Prefs {
  return (cache ??= read());
}

export function applyPrefs(p: Prefs = getPrefs()): void {
  if (typeof document === "undefined") return;
  const el = document.documentElement;
  const set = (name: string, value: string, off: string) => (value === off ? el.removeAttribute(name) : el.setAttribute(name, value));
  set("data-text", p.text, "normal");
  set("data-contrast", p.contrast, "normal");
  set("data-motion", p.motion, "system");
  set("data-fx", p.effects, "on");
  set("data-links", p.links, "normal");
  if (!document.getElementById("sq-prefs-style")) {
    const style = document.createElement("style");
    style.id = "sq-prefs-style";
    style.textContent = STYLE;
    document.head.appendChild(style);
  }
}

export function setPrefs(patch: Partial<Prefs>): void {
  cache = { ...getPrefs(), ...patch };
  try {
    localStorage.setItem(KEY, JSON.stringify(cache));
  } catch {
    /* storage blocked: the choice still applies until the tab is closed */
  }
  applyPrefs(cache);
  window.dispatchEvent(new Event(EVENT));
}

export function resetPrefs(): void {
  cache = DEFAULT_PREFS;
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
  applyPrefs(cache);
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(cb: () => void) {
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) {
      cache = null;
      cb();
    }
  };
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(EVENT, cb);
    window.removeEventListener("storage", onStorage);
  };
}

/** Current preferences; re-renders when they change. The server snapshot is the default so hydration always matches. */
export function usePrefs(): Prefs {
  return useSyncExternalStore(subscribe, getPrefs, () => DEFAULT_PREFS);
}
