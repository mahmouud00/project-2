import { createContext, useContext, useEffect, type ReactNode } from "react";
import type { Route } from "./router";

export type Title = { title: ReactNode; crumbs?: ReactNode };
export const TitleCtx = createContext<(t: Title) => void>(() => undefined);
export type PageProps = { route: Route };

export type RecordRef = { kind: string; id: string };
export const RecordCtx = createContext<(r: RecordRef | null) => void>(() => undefined);

/** A record's page calls this: the top bar then shows «سجل التغييرات» for it. */
export function useRecordHistory(kind: string, id: string | null | undefined) {
  const set = useContext(RecordCtx);
  useEffect(() => {
    if (!id) return;
    set({ kind, id });
    return () => set(null);
  }, [kind, id, set]);
}

/** Pages call this to set the title in the top bar (`null`: a page inside this one sets it). */
export function useTitle(title: ReactNode | null, crumbs?: ReactNode, deps: unknown[] = []) {
  const set = useContext(TitleCtx);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (title !== null) set({ title, crumbs }); }, deps);
}
