import { useEffect, useRef, useState } from "react";
import { api, type S } from "../api/client";
import { lookups } from "../lib/lookups";
import { useDebounced, useLoad } from "../lib/hooks";
import { useSession } from "../state/session";
import { MediaImg } from "./media";

export function CustomerPicker({ value, onChange, disabled }:
  { value: string | null | undefined; onChange: (id: string | null, c?: S<"CustomerOut">) => void; disabled?: boolean }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState<S<"CustomerOut"> | null>(null);
  const dq = useDebounced(q, 250);
  const box = useRef<HTMLDivElement>(null);
  const list = useLoad(() => open ? api.get<S<"Page_CustomerOut_">>("/customers", { q: dq || undefined, limit: 20 }).then((p) => p.items)
    : Promise.resolve([]), [dq, open]);
  useEffect(() => {
    if (value && value !== current?.id) lookups.customer(value).then(setCurrent).catch(() => setCurrent(null));
    if (!value) setCurrent(null);
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const on = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", on);
    return () => document.removeEventListener("mousedown", on);
  }, []);
  return (
    <div ref={box} style={{ position: "relative" }}>
      <input className="input" disabled={disabled} placeholder="ابحث بالاسم أو التليفون أو الكود…"
        value={open ? q : current ? `${current.name} · ${current.code}` : ""}
        onFocus={() => { setOpen(true); setQ(""); }} onChange={(e) => setQ(e.target.value)} />
      {open && (
        <div className="card" style={{ position: "absolute", insetInline: 0, top: 40, zIndex: 40, maxHeight: 280, overflow: "auto" }}>
          {(list.data ?? []).map((c) => (
            <button key={c.id} type="button" className="btn ghost" style={{ width: "100%", justifyContent: "flex-start", color: "var(--text)",
              borderRadius: 0 }} onClick={() => { setCurrent(c); onChange(c.id, c); setOpen(false); }}>
              <span className="grow" style={{ textAlign: "start" }}>{c.name}</span>
              <span className="muted small num">{c.phone ?? ""}</span><span className="code">{c.code}</span>
            </button>
          ))}
          {list.data && !list.data.length && <div className="empty small">مفيش عميل بالاسم ده</div>}
          {list.loading && <div className="empty"><span className="spinner" /></div>}
        </div>
      )}
    </div>
  );
}

export function ModelSelect({ value, onChange, publishedOnly = true }:
  { value: string | null | undefined; onChange: (id: string, m?: S<"ModelOut">) => void; publishedOnly?: boolean }) {
  const models = useLoad(() => lookups.allModels(), []);
  const groups = new Map<string, { name: string; items: S<"ModelOut">[] }>();
  for (const m of models.data ?? []) {
    if (!m.is_active || (publishedOnly && !m.system.current_version_id)) continue;
    const g = groups.get(m.system.id) ?? { name: m.system.name, items: [] };
    g.items.push(m);
    groups.set(m.system.id, g);
  }
  return (
    <select className="input" value={value ?? ""} onChange={(e) => onChange(e.target.value, models.data?.find((m) => m.id === e.target.value))}>
      <option value="">اختار النموذج…</option>
      {[...groups.entries()].map(([id, g]) => (
        <optgroup key={id} label={g.name}>
          {g.items.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.code})</option>)}
        </optgroup>
      ))}
    </select>
  );
}

export function ModelThumb({ modelId, className }: { modelId: string | null | undefined; className?: string }) {
  const m = useLoad(() => modelId ? lookups.model(modelId) : Promise.resolve(undefined), [modelId]);
  return <MediaImg id={m.data?.image_id} className={className} />;
}

export function ColorSelect({ value, onChange, allowEmpty = true }:
  { value: string | null | undefined; onChange: (code: string | null) => void; allowEmpty?: boolean }) {
  const colors = useLoad(() => lookups.colors(), []);
  return (
    <select className="input" value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      {allowEmpty && <option value="">— اللون —</option>}
      {(colors.data ?? []).filter((c) => c.is_active).map((c) => <option key={c.code} value={c.code}>{c.name} ({c.code})</option>)}
    </select>
  );
}

export function GlassSelect({ value, onChange }: { value: string | null | undefined; onChange: (code: string | null) => void }) {
  const glass = useLoad(() => lookups.glass(), []);
  return (
    <select className="input" value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">— الزجاج (الافتراضي) —</option>
      {(glass.data ?? []).filter((g) => g.is_active).map((g) => <option key={g.code} value={g.code}>{g.name}</option>)}
    </select>
  );
}

export function BranchSelect({ value, onChange, perm, allowAll }:
  { value: string | null | undefined; onChange: (id: string) => void; perm?: string; allowAll?: string }) {
  const s = useSession();
  const branches = s.branches.filter((b) => b.is_active && (!perm || s.can(perm, b.id)));
  return (
    <select className="input" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
      {allowAll !== undefined ? <option value="">{allowAll}</option> : !value && <option value="">اختار الفرع…</option>}
      {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
    </select>
  );
}

export function WarehouseSelect({ value, onChange, branchId, allowAll }:
  { value: string | null | undefined; onChange: (id: string) => void; branchId?: string | null; allowAll?: string }) {
  const list = useLoad(() => lookups.warehouses(), []);
  const items = (list.data ?? []).filter((w) => w.is_active && (!branchId || w.branch_id === branchId));
  return (
    <select className="input" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
      {allowAll !== undefined ? <option value="">{allowAll}</option> : <option value="">اختار المخزن…</option>}
      {items.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
    </select>
  );
}

export function CashboxSelect({ value, onChange, allowAll }: { value: string | null | undefined; onChange: (id: string) => void; allowAll?: string }) {
  const list = useLoad(() => lookups.cashboxes(), []);
  return (
    <select className="input" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
      {allowAll !== undefined ? <option value="">{allowAll}</option> : <option value="">اختار الخزينة…</option>}
      {(list.data ?? []).filter((c) => c.is_active).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
    </select>
  );
}

export function SupplierSelect({ value, onChange }: { value: string | null | undefined; onChange: (id: string) => void }) {
  const list = useLoad(() => lookups.suppliers(), []);
  return (
    <select className="input" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
      <option value="">اختار المورد…</option>
      {(list.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
    </select>
  );
}

export function CustomerName({ id }: { id: string | null | undefined }) {
  const c = useLoad(() => id ? lookups.customer(id) : Promise.resolve(undefined), [id]);
  return <>{c.data?.name ?? "…"}</>;
}

export function BranchName({ id }: { id: string | null | undefined }) {
  const s = useSession();
  return <>{s.branches.find((b) => b.id === id)?.name ?? "—"}</>;
}

export function ColorName({ code }: { code: string | null | undefined }) {
  const colors = useLoad(() => lookups.colors(), []);
  const c = colors.data?.find((x) => x.code === code);
  if (!code) return <span className="faint">—</span>;
  return <span className="row" style={{ gap: 5, display: "inline-flex" }}>{c?.hex && <span className="swatch" style={{ background: c.hex }} />}{c?.name ?? code}</span>;
}
