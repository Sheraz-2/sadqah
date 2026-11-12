"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Voice for the assistant, using the browser's own speech features (Web Speech API).
 * - Speech to text works in Chrome, Edge and Safari. Firefox does not offer it, so the microphone button is hidden there.
 *   In Chrome the browser sends the audio to its speech service to turn it into text: SadQah never receives the audio.
 * - Which languages are understood depends on the browser and device. Typing always works, in any language.
 */
export const VOICE_LANGS: { tag: string; label: string }[] = [
  { tag: "auto", label: "Automatic (browser language)" },
  { tag: "en-US", label: "English" },
  { tag: "ur-PK", label: "اردو (Urdu)" },
  { tag: "hi-IN", label: "हिन्दी (Hindi)" },
  { tag: "bn-BD", label: "বাংলা (Bangla)" },
  { tag: "ar-SA", label: "العربية (Arabic)" },
  { tag: "fa-IR", label: "فارسی (Persian)" },
  { tag: "ne-NP", label: "नेपाली (Nepali)" },
  { tag: "si-LK", label: "සිංහල (Sinhala)" },
  { tag: "ta-IN", label: "தமிழ் (Tamil)" },
  { tag: "te-IN", label: "తెలుగు (Telugu)" },
  { tag: "pa-IN", label: "ਪੰਜਾਬੀ (Punjabi)" },
  { tag: "gu-IN", label: "ગુજરાતી (Gujarati)" },
  { tag: "mr-IN", label: "मराठी (Marathi)" },
  { tag: "sw-KE", label: "Kiswahili" },
  { tag: "am-ET", label: "አማርኛ (Amharic)" },
  { tag: "zu-ZA", label: "isiZulu" },
  { tag: "af-ZA", label: "Afrikaans" },
  { tag: "fr-FR", label: "Français" },
  { tag: "es-ES", label: "Español" },
  { tag: "pt-BR", label: "Português" },
  { tag: "tr-TR", label: "Türkçe" },
  { tag: "id-ID", label: "Bahasa Indonesia" },
  { tag: "ms-MY", label: "Bahasa Melayu" },
  { tag: "fil-PH", label: "Filipino" },
  { tag: "vi-VN", label: "Tiếng Việt" },
  { tag: "th-TH", label: "ไทย" },
  { tag: "my-MM", label: "မြန်မာ (Burmese)" },
  { tag: "km-KH", label: "ខ្មែរ (Khmer)" },
];

type Recognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
};
type RecognitionCtor = new () => Recognition;

function ctor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function resolveLang(tag: string): string {
  if (tag !== "auto") return tag;
  return (typeof navigator !== "undefined" && navigator.language) || "en-US";
}

export function canSpeak(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function speak(text: string, lang: string): void {
  if (!canSpeak()) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text.replace(/[*_`#]/g, ""));
  u.lang = resolveLang(lang);
  const base = u.lang.split("-")[0].toLowerCase();
  const voice = window.speechSynthesis.getVoices().find((v) => v.lang.toLowerCase() === u.lang.toLowerCase()) ?? window.speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith(base));
  if (voice) u.voice = voice;
  window.speechSynthesis.speak(u);
}

export function stopSpeaking(): void {
  if (canSpeak()) window.speechSynthesis.cancel();
}

const ERRORS: Record<string, string> = {
  "not-allowed": "The microphone is blocked. Allow it for this site in your browser, or type instead.",
  "service-not-allowed": "Voice typing is not allowed in this browser. You can type instead.",
  "no-speech": "I did not hear anything. Try again, a little closer to the microphone.",
  "audio-capture": "No microphone was found.",
  "language-not-supported": "This browser cannot understand that language by voice. Choose another, or type.",
  network: "Voice typing needs an internet connection.",
};

/** Dictation into a text box. `onText` receives the best transcript so far (interim) and the final one. */
export function useDictation(lang: string, onText: (text: string, final: boolean) => void) {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [supported, setSupported] = useState(false);
  const rec = useRef<Recognition | null>(null);
  const cb = useRef(onText);
  cb.current = onText;

  useEffect(() => setSupported(ctor() !== null), []);
  useEffect(() => () => rec.current?.abort(), []);

  const start = useCallback(() => {
    const C = ctor();
    if (!C) return;
    setError(null);
    stopSpeaking(); // do not listen to ourselves
    const r = new C();
    r.lang = resolveLang(lang);
    r.interimResults = true;
    r.continuous = false;
    r.maxAlternatives = 1;
    r.onresult = (e) => {
      let text = "";
      let final = false;
      for (let i = e.resultIndex; i < e.results.length; i++) {
        text += e.results[i][0].transcript;
        final = final || e.results[i].isFinal;
      }
      cb.current(text.trim(), final);
    };
    r.onerror = (e) => setError(ERRORS[e.error] ?? "Voice typing stopped unexpectedly. You can type instead.");
    r.onend = () => setListening(false);
    rec.current = r;
    try {
      r.start();
      setListening(true);
    } catch {
      setListening(false);
    }
  }, [lang]);

  const stop = useCallback(() => rec.current?.stop(), []);
  return { supported, listening, error, start, stop };
}
