"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage } from "@/lib/api";

type State<T> = { data: T | null; error: string | null; loading: boolean };

/** Loads data on mount (and when `deps` change). `reload()` refetches without clearing existing data. */
export function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true });
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const run = useCallback(async (signal: AbortSignal) => {
    try {
      const data = await fnRef.current(signal);
      if (!signal.aborted) setState({ data, error: null, loading: false });
    } catch (err) {
      if (signal.aborted || (err as Error).name === "AbortError") return;
      setState((s) => ({ data: s.data, error: errorMessage(err), loading: false }));
    }
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    setState((s) => ({ ...s, loading: true }));
    void run(ctrl.signal);
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const reload = useCallback(() => run(new AbortController().signal), [run]);
  return { ...state, reload };
}
