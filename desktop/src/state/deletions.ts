// What is waiting to be deleted (the 30-day countdown), shared by every delete button on the screen.
import { useEffect, useState } from "react";
import { api, type S } from "../api/client";

export type Deletion = S<"DeletionOut">;

let items: Deletion[] = [];
let loadedAt = 0;
let inflight: Promise<void> | null = null;
const subs = new Set<() => void>();

export function reloadDeletions(): Promise<void> {
  inflight ??= api.get<Deletion[]>("/deletions")
    .then((x) => { items = x; loadedAt = Date.now(); subs.forEach((f) => f()); })
    .catch(() => undefined)
    .finally(() => { inflight = null; });
  return inflight;
}

export function useDeletions(): Deletion[] {
  const [, tick] = useState(0);
  useEffect(() => {
    const f = () => tick((n) => n + 1);
    subs.add(f);
    if (Date.now() - loadedAt > 30_000) void reloadDeletions();
    return () => { subs.delete(f); };
  }, []);
  return items;
}

/** "/library/materials/<id>" -> its waiting deletion, if any */
export function pendingFor(list: Deletion[], path: string): Deletion | undefined {
  const parts = path.replace(/^\/+/, "").split("/");
  const id = parts.pop();
  const kind = parts.join("/");
  return list.find((d) => d.kind === kind && d.target_id === id);
}

/** A clock that moves every second (for the countdowns). */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), ms); return () => clearInterval(t); }, [ms]);
  return now;
}

/** days left and the clock of the last day ("23:59:58") */
export function countdown(dueAt: string, now: number): { days: number; clock: string } {
  const left = Math.max(0, new Date(dueAt).getTime() - now);
  const s = Math.floor(left / 1000);
  const h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const two = (n: number) => String(n).padStart(2, "0");
  return { days: Math.floor(s / 86400), clock: `${two(h)}:${two(m)}:${two(sec)}` };
}
