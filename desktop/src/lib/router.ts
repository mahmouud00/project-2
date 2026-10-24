// Minimal hash router: "#/quotations/123?tab=lines" -> { path: ["quotations", "123"], query: { tab: "lines" } }
import { useEffect, useState } from "react";

export type Route = { path: string[]; query: Record<string, string> };

function parse(): Route {
  const h = location.hash.replace(/^#\/?/, "");
  const [p, q = ""] = h.split("?");
  return { path: p.split("/").filter(Boolean).map(decodeURIComponent), query: Object.fromEntries(new URLSearchParams(q)) };
}

export function useRoute(): Route {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function go(path: string, query?: Record<string, string | undefined>) {
  const q = query ? new URLSearchParams(Object.entries(query).filter(([, v]) => v) as [string, string][]).toString() : "";
  location.hash = "#/" + path.replace(/^\//, "") + (q ? "?" + q : "");
}

export function setQuery(patch: Record<string, string | undefined>) {
  const r = parse();
  go(r.path.map(encodeURIComponent).join("/"), { ...r.query, ...patch });
}
