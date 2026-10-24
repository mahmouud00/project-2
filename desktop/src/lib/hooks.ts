import { useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "../api/client";

/** Load data on mount and whenever deps change. reload() fetches again; set() replaces the data locally. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const reload = useCallback(async () => {
    const n = ++seq.current;
    setLoading(true);
    try {
      const d = await fnRef.current();
      if (n === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (n === seq.current) setError(errorText(e));
    } finally {
      if (n === seq.current) setLoading(false);
    }
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, deps);
  return { data, error, loading, reload, set: setData };
}

/** Wrap an async action: tracks busy state and reports errors via the given toast function. */
export function useAction(onError: (msg: string) => void) {
  const [busy, setBusy] = useState(false);
  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    try {
      return await fn();
    } catch (e) {
      onError(errorText(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  }, [onError]);
  return { busy, run };
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Run fn only when allowed (e.g. the user has the permission); otherwise resolve to undefined. */
export function when<T>(cond: boolean, fn: () => Promise<T>): Promise<T | undefined> {
  return cond ? fn() : Promise.resolve(undefined);
}
