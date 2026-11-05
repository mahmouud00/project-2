// Hash router: "#/quotations/123?tab=lines" -> { path: ["quotations", "123"], query: { tab: "lines" } }.
// Every page change is a history entry numbered by its position (history.state.i), so the app can show back /
// forward buttons and know when there is nowhere to go. Screens with unsaved work register a guard: leaving them
// (by a link, a button, back / forward, the mouse or the keyboard) first asks.
import { useEffect, useState } from "react";

export type Route = { path: string[]; query: Record<string, string> };

function parse(): Route {
  const h = location.hash.replace(/^#\/?/, "");
  const [p, q = ""] = h.split("?");
  return { path: p.split("/").filter(Boolean).map(decodeURIComponent), query: Object.fromEntries(new URLSearchParams(q)) };
}

// ---------------------------------------------------------------- history position
const idx = (): number => (typeof history.state?.i === "number" ? history.state.i : 0);
let maxIdx = 0;
try { maxIdx = Number(sessionStorage.getItem("nav.max") ?? 0) || 0; } catch { /* storage blocked: start at 0 */ }
const saveMax = () => { try { sessionStorage.setItem("nav.max", String(maxIdx)); } catch { /* ignore */ } };
if (typeof history.state?.i !== "number") history.replaceState({ ...(history.state ?? {}), i: 0 }, "");
maxIdx = Math.max(maxIdx, idx());

let synced = { hash: location.hash, i: idx() };
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((f) => f());

// ---------------------------------------------------------------- unsaved-work guard
const guards = new Map<symbol, string>();
let pending: (() => void) | null = null;
const askers = new Set<(message: string | null) => void>();
const dirtyMessage = (): string | null => (guards.size ? [...guards.values()][0] : null);

/** Asks before leaving this screen while `dirty` (the message says what would be lost). */
export function useUnsavedGuard(dirty: boolean, message = "فيه تعديلات لسه متحفظتش. تخرج من غير حفظ؟") {
  useEffect(() => {
    if (!dirty) return;
    const key = Symbol("guard");
    guards.set(key, message);
    const unload = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", unload);
    return () => { guards.delete(key); window.removeEventListener("beforeunload", unload); };
  }, [dirty, message]);
}

function ask(message: string, then: () => void) {
  pending = then;
  askers.forEach((f) => f(message));
}

/** For the confirmation shown by the app: leave anyway, or stay. */
export const navGuard = {
  subscribe(f: (message: string | null) => void) { askers.add(f); return () => { askers.delete(f); }; },
  leave() { const p = pending; pending = null; guards.clear(); askers.forEach((f) => f(null)); p?.(); },
  stay() { pending = null; askers.forEach((f) => f(null)); },
};

// ---------------------------------------------------------------- browser navigation (back / forward / plain links)
let restoring = false;
function onBrowserNav() {
  if (typeof history.state?.i !== "number") {   // a plain hash change (a link or typed address): the next entry
    const i = synced.i + 1;
    history.replaceState({ ...(history.state ?? {}), i }, "");
    maxIdx = i;
    saveMax();
  }
  const now = { hash: location.hash, i: idx() };
  if (now.hash === synced.hash && now.i === synced.i) { restoring = false; return; }
  if (restoring) return;
  const delta = now.i - synced.i;
  const msg = dirtyMessage();
  if (msg && delta) {
    restoring = true;
    history.go(-delta);                          // stay on this screen until the user decides
    ask(msg, () => history.go(delta));
    return;
  }
  synced = now;
  emit();
}
window.addEventListener("popstate", onBrowserNav);
window.addEventListener("hashchange", onBrowserNav);

function navigate(hash: string, replace: boolean) {
  if (hash === location.hash) return;
  const msg = replace ? null : dirtyMessage();
  if (msg) { ask(msg, () => navigate(hash, replace)); return; }
  const i = replace ? idx() : idx() + 1;
  if (replace) history.replaceState({ ...(history.state ?? {}), i }, "", hash);
  else { history.pushState({ i }, "", hash); maxIdx = i; saveMax(); }
  synced = { hash: location.hash, i };
  emit();
}

const toHash = (path: string, query?: Record<string, string | undefined>) => {
  const q = query ? new URLSearchParams(Object.entries(query).filter(([, v]) => v) as [string, string][]).toString() : "";
  return "#/" + path.replace(/^\//, "") + (q ? "?" + q : "");
};

export function useRoute(): Route {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    listeners.add(on);
    return () => { listeners.delete(on); };
  }, []);
  return route;
}

/** Opens a page (a new history entry). */
export function go(path: string, query?: Record<string, string | undefined>) {
  navigate(toHash(path, query), false);
}

/** Opens a page in place of the current one (no history entry): for redirects. */
export function redirect(path: string, query?: Record<string, string | undefined>) {
  navigate(toHash(path, query), true);
}

/** Changes the current page's tab / filters in place: back goes to the previous page, not the previous tab. */
export function setQuery(patch: Record<string, string | undefined>) {
  const r = parse();
  navigate(toHash(r.path.map(encodeURIComponent).join("/"), { ...r.query, ...patch }), true);
}

// ---------------------------------------------------------------- back / forward
export function back() { if (idx() > 0) history.back(); }
export function forward() { if (idx() < maxIdx) history.forward(); }

/** Whether there is a page to go back / forward to (for the arrows in the top bar). */
export function useHistoryNav(): { canBack: boolean; canForward: boolean } {
  const get = () => ({ canBack: idx() > 0, canForward: idx() < maxIdx });
  const [s, set] = useState(get);
  useEffect(() => {
    const on = () => set(get());
    listeners.add(on);
    return () => { listeners.delete(on); };
  }, []);
  return s;
}

/** Alt + ← / → and the mouse's back / forward buttons. The webview may already handle them natively; then the
 * position has changed by the time this runs and nothing is done twice. */
export function useHistoryKeys() {
  useEffect(() => {
    const later = (f: () => void) => { const at = idx(); setTimeout(() => { if (idx() === at) f(); }, 60); };
    const key = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      if (e.key === "ArrowLeft") { e.preventDefault(); later(back); }
      else if (e.key === "ArrowRight") { e.preventDefault(); later(forward); }
    };
    const mouse = (e: MouseEvent) => {
      if (e.button === 3) { e.preventDefault(); later(back); }
      else if (e.button === 4) { e.preventDefault(); later(forward); }
    };
    window.addEventListener("keydown", key);
    window.addEventListener("mouseup", mouse);
    return () => { window.removeEventListener("keydown", key); window.removeEventListener("mouseup", mouse); };
  }, []);
}
