import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type Toast = { id: number; kind: "ok" | "err" | "info"; text: string };
type Ctx = { ok: (t: string) => void; err: (t: string) => void; info: (t: string) => void };
const ToastCtx = createContext<Ctx>({ ok: () => {}, err: () => {}, info: () => {} });
let next = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = next++;
    setItems((x) => [...x.slice(-3), { id, kind, text }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "err" ? 7000 : 3500);
  }, []);
  const [ctx] = useState<Ctx>(() => ({ ok: (t) => push("ok", t), err: (t) => push("err", t), info: (t) => push("info", t) }));
  return (
    <ToastCtx.Provider value={ctx}>
      {children}
      <div className="toasts" role="status">
        {items.map((t) => (
          <div key={t.id} className={"toast " + t.kind} onClick={() => setItems((x) => x.filter((i) => i.id !== t.id))}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);
