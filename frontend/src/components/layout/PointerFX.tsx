"use client";

import { useEffect } from "react";

/**
 * Cursor-aware polish (light version). Writes four tiny CSS variables on the ONE button and the ONE campaign card
 * under the mouse, at most once per animation frame (all reads first, then all writes, so the browser never has to
 * re-measure the page mid-frame), and moves one small fixed glow. Does nothing on touch screens or when the visitor
 * prefers reduced motion. All styling lives in globals.css.
 */
const BTN = 'button:not(:disabled), a[class~="rounded-full"][class~="inline-flex"]';
const CARD = "article";

type Box = { el: HTMLElement; r: DOMRect };

export function PointerFX() {
  useEffect(() => {
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)");
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (!fine.matches || calm.matches) return;

    const glow = document.createElement("div");
    glow.className = "sq-cursor-glow";
    glow.setAttribute("aria-hidden", "true");
    document.body.appendChild(glow);

    let x = 0;
    let y = 0;
    let frame = 0;
    let btn: HTMLElement | null = null;
    let card: HTMLElement | null = null;

    const clear = (el: HTMLElement | null) => {
      if (!el) return;
      el.style.removeProperty("--mx");
      el.style.removeProperty("--my");
      el.style.removeProperty("--nx");
      el.style.removeProperty("--ny");
    };
    const write = ({ el, r }: Box) => {
      const px = x - r.left;
      const py = y - r.top;
      el.style.setProperty("--mx", `${px.toFixed(0)}px`);
      el.style.setProperty("--my", `${py.toFixed(0)}px`);
      el.style.setProperty("--nx", Math.max(-1, Math.min(1, (px / r.width) * 2 - 1)).toFixed(2));
      el.style.setProperty("--ny", Math.max(-1, Math.min(1, (py / r.height) * 2 - 1)).toFixed(2));
    };
    const paint = () => {
      frame = 0;
      // 1) read
      const boxes: Box[] = [];
      if (btn) boxes.push({ el: btn, r: btn.getBoundingClientRect() });
      if (card) boxes.push({ el: card, r: card.getBoundingClientRect() });
      // 2) write
      glow.style.transform = `translate3d(${x}px, ${y}px, 0)`;
      boxes.forEach(write);
    };
    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      x = e.clientX;
      y = e.clientY;
      const t = e.target instanceof Element ? e.target : null;
      const nextBtn = (t?.closest(BTN) as HTMLElement | null) ?? null;
      const nextCard = (t?.closest(CARD) as HTMLElement | null) ?? null;
      if (nextBtn !== btn) { clear(btn); btn = nextBtn; }
      if (nextCard !== card) { clear(card); card = nextCard; }
      glow.dataset.on = "";
      if (!frame) frame = requestAnimationFrame(paint);
    };
    const onLeave = () => {
      clear(btn); clear(card);
      btn = null; card = null;
      delete glow.dataset.on;
    };

    document.addEventListener("pointermove", onMove, { passive: true });
    document.documentElement.addEventListener("mouseleave", onLeave);
    window.addEventListener("blur", onLeave);
    return () => {
      document.removeEventListener("pointermove", onMove);
      document.documentElement.removeEventListener("mouseleave", onLeave);
      window.removeEventListener("blur", onLeave);
      if (frame) cancelAnimationFrame(frame);
      clear(btn); clear(card);
      glow.remove();
    };
  }, []);

  return null;
}