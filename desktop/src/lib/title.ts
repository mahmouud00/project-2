import { createContext, useContext, useEffect, type ReactNode } from "react";
import type { Route } from "./router";

export type Title = { title: ReactNode; crumbs?: ReactNode };
export const TitleCtx = createContext<(t: Title) => void>(() => undefined);
export type PageProps = { route: Route };

/** Pages call this to set the title in the top bar. */
export function useTitle(title: ReactNode, crumbs?: ReactNode, deps: unknown[] = []) {
  const set = useContext(TitleCtx);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { set({ title, crumbs }); }, deps);
}
