// Unsaved work kept on this computer until it is saved: a survey sheet, a model being edited, a quotation line.
// Nothing is sent anywhere by itself (no offline sync): the draft only comes back on this computer, and only when
// the record has not been saved by someone since, so restoring it can never overwrite their changes.
import { useEffect, useRef, useState } from "react";

type Stored<T> = { v: T; base: string; at: string };
export type Draft<T> = { value: T; at: Date };

const PREFIX = "draft:";
const MAX_AGE_DAYS = 30;

function read<T>(key: string): Stored<T> | null {
  try {
    const s = JSON.parse(localStorage.getItem(PREFIX + key) ?? "null") as Stored<T> | null;
    if (!s || Date.now() - new Date(s.at).getTime() > MAX_AGE_DAYS * 864e5) return null;
    return s;
  } catch { return null; }
}
function write(key: string, s: Stored<unknown> | null) {
  try { if (s) localStorage.setItem(PREFIX + key, JSON.stringify(s)); else localStorage.removeItem(PREFIX + key); }
  catch { /* storage full or blocked: drafts are a convenience */ }
}

/** Keeps `value` while `dirty`, for the record `key` at version `base` (null: not loaded yet). Returns the draft
 * found when the screen opened (same version only) until it is restored or dropped. */
export function useDraft<T>(key: string, base: string | number | null | undefined, value: T, dirty: boolean) {
  const [found, setFound] = useState<Draft<T> | null>(null);
  const checked = useRef<string | null>(null);
  const wasDirty = useRef(false);
  const ready = base !== null && base !== undefined;

  // when the record is loaded: offer the draft made on this same version; drop one made on an older version
  useEffect(() => {
    if (!ready || checked.current === key) return;
    checked.current = key;
    const s = read<T>(key);
    if (!s) return;
    if (s.base === String(base)) setFound({ value: s.v, at: new Date(s.at) });
    else write(key, null);
  }, [key, base, ready]);

  // keep the work while it is unsaved (a moment after the last change); forget it once saved
  useEffect(() => {
    if (!ready || found) return;
    if (dirty) {
      wasDirty.current = true;
      const t = setTimeout(() => write(key, { v: value, base: String(base), at: new Date().toISOString() }), 600);
      return () => clearTimeout(t);
    }
    if (wasDirty.current) { wasDirty.current = false; write(key, null); }
  }, [key, base, ready, dirty, value, found]);

  return {
    found,
    restore: (apply: (v: T) => void) => { if (found) { apply(found.value); setFound(null); } },
    discard: () => { write(key, null); setFound(null); },
  };
}
