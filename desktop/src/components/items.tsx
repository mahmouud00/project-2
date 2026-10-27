// Editing one window/door item (survey opening, quotation line): model, opening size (width first),
// parameters from the model definition, colour, glass, quantity, and a live calculation preview.
import { useEffect, useState, type ReactNode } from "react";
import { api, errorText, type S } from "../api/client";
import { lookups } from "../lib/lookups";
import { useDebounced, useLoad } from "../lib/hooks";
import { Btn, Check, Dim, Field, Len, LenIn, Modal, NumIn, Select, SizeIn, TextIn, Chip } from "./ui";
import { ColorSelect, GlassSelect, ModelSelect } from "./pickers";
import { useSession } from "../state/session";
import { subDec } from "../lib/format";
import { Drawing, MediaImg } from "./media";

type Param = S<"Param">;
export type Calc = {
  ok?: boolean; inputs?: Record<string, any>; values?: Record<string, string>; issues?: Issue[];
  pieces?: Piece[]; glass?: any[]; accessories?: any[]; drawing?: any[]; meta?: Record<string, any>;
};
export type Issue = { code: string; level: string; where?: string | null; message: string; item?: number };
export type Piece = { key: string; label?: string; element?: string | null; side?: "width" | "height" | null; role?: string | null;
  material_code: string; material_name?: string; length_mm: string; qty: number | string; angle_left?: string; angle_right?: string };

export function ParamFields({ params, values, onChange, unit }:
  { params: Param[]; values: Record<string, any>; onChange: (v: Record<string, any>) => void; unit: string }) {
  if (!params.length) return null;
  const set = (name: string, v: any) => onChange({ ...values, [name]: v });
  return (
    <>
      {params.map((p) => {
        const label = p.label || p.name;
        const v = values[p.name] ?? p.default ?? "";
        if (p.type === "bool") {
          return <Field key={p.name} label=" "><Check checked={v === true || v === "true" || v === 1} onChange={(b) => set(p.name, b)} label={label} /></Field>;
        }
        if (p.type === "choice") {
          return (
            <Field key={p.name} label={label}>
              <Select value={String(v)} onChange={(x) => set(p.name, x)}
                options={(p.choices ?? []).map((c) => ({ value: String(c.value), label: c.label }))} />
            </Field>
          );
        }
        const hint = [p.min !== null && p.min !== undefined && `من ${p.min}`, p.max !== null && p.max !== undefined && `لحد ${p.max}`]
          .filter(Boolean).join(" ");
        return (
          <Field key={p.name} label={label} hint={hint || undefined}>
            <NumIn value={String(v)} onChange={(x) => set(p.name, x)} unit={p.type === "length" ? (unit === "cm" ? "سم" : "مم") : undefined} />
          </Field>
        );
      })}
    </>
  );
}

const ISSUE_TEXT: Record<string, string> = {
  TRIAL_STATUS: "القطاع أو النموذج لسه تحت التجربة",
  PIECE_NOT_POSITIVE: "فيه قطعة طولها صفر أو بالسالب",
  PIECE_TOO_SHORT: "فيه قطعة أقصر من أقل طول مسموح",
  PIECE_TOO_LONG: "فيه قطعة أطول من طول العود",
  GLASS_AREA_INVALID: "مساحة الزجاج المشكّل (زي الأرج) أكبر من مقاسه أو بالسالب",
};

export function Issues({ issues }: { issues?: Issue[] }) {
  if (!issues?.length) return null;
  const seen = new Set<string>();
  const unique = issues.filter((i) => { const k = i.code + i.message + (i.where ?? ""); if (seen.has(k)) return false; seen.add(k); return true; });
  return (
    <div className="col" style={{ gap: 6 }}>
      {unique.map((i, k) => (
        <div key={k} className={"notice " + (i.level === "error" ? "err" : "warn")}>
          {ISSUE_TEXT[i.code] ?? i.message}
          {ISSUE_TEXT[i.code] && i.message && i.code !== "TRIAL_STATUS" && <span className="small faint num"> · {i.message}</span>}
        </div>
      ))}
    </div>
  );
}

/** Pieces grouped by element: each element on one row, width length then height length. */
export function ElementPieces({ pieces }: { pieces?: Piece[] }) {
  if (!pieces?.length) return null;
  type Row = { element: string; material: string; width?: Piece; height?: Piece; other: Piece[] };
  const rows = new Map<string, Row>();
  for (const p of pieces) {
    const el = p.element || p.label || p.key;
    const key = el + "|" + p.material_code;
    const r = rows.get(key) ?? { element: el, material: p.material_name || p.material_code, other: [] };
    if (p.side === "width" && !r.width) r.width = p;
    else if (p.side === "height" && !r.height) r.height = p;
    else r.other.push(p);
    rows.set(key, r);
  }
  const cell = (p?: Piece) => p
    ? <><b><Len mm={p.length_mm} /></b> <span className="muted small">· عدد <span className="num">{p.qty}</span></span>
        <span className="faint small"> · <span className="num">{p.angle_left}°/{p.angle_right}°</span></span></>
    : <span className="faint">—</span>;
  return (
    <table>
      <thead><tr><th>العنصر</th><th>الخامة</th><th className="side-w">العرض</th><th className="side-h">الارتفاع</th></tr></thead>
      <tbody>
        {[...rows.values()].flatMap((r) => [
          <tr key={r.element + r.material}><td><b>{r.element}</b></td><td className="muted">{r.material}</td><td>{cell(r.width)}</td><td>{cell(r.height)}</td></tr>,
          ...r.other.map((p) => (
            <tr key={r.element + p.key}><td>{p.label || p.key}</td><td className="muted">{r.material}</td><td colSpan={2}>{cell(p)}</td></tr>
          )),
        ])}
      </tbody>
    </table>
  );
}

export type ItemDraft = {
  model_id?: string | null; location?: string; opening_width_mm?: string | null; opening_height_mm?: string | null;
  total_height_mm?: string | null; top_model_id?: string | null;
  params?: Record<string, any>; color_code?: string | null; glass_material_code?: string | null; qty?: number | string;
  manual_unit_price?: string | null; price_per_m2?: string | null; notes?: string;
};

export function ItemForm({ title, initial, onClose, onSave, withPrice, requireModel = true, extra }:
  { title: string; initial?: ItemDraft; onClose: () => void; onSave: (d: ItemDraft) => Promise<void>; withPrice?: boolean;
    requireModel?: boolean; extra?: ReactNode }) {
  const s = useSession();
  const [d, setD] = useState<ItemDraft>(() => ({ qty: 1, params: {}, location: "", ...initial }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const models = useLoad(() => lookups.allModels(), []);
  const model = models.data?.find((m) => m.id === d.model_id);
  const def = (model?.definition ?? {}) as S<"Definition">;
  const params = def.params ?? [];

  // drop parameters that do not belong to the newly chosen model
  useEffect(() => {
    if (!model) return;
    const names = new Set(params.map((p) => p.name));
    setD((x) => ({ ...x, params: Object.fromEntries(Object.entries(x.params ?? {}).filter(([k]) => names.has(k))) }));
  }, [model?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const preview = useDebounced(JSON.stringify([d.model_id, d.opening_width_mm, d.opening_height_mm, d.params]), 400);
  const calc = useLoad<Calc | { error: string } | null>(async () => {
    if (!d.model_id || !d.opening_width_mm || !d.opening_height_mm || !model?.system.current_version_id) return null;
    try {
      return await api.post<Calc>("/engine/calculate", { model_id: d.model_id, opening_width_mm: d.opening_width_mm,
        opening_height_mm: d.opening_height_mm, params: cleanParams(params, d.params ?? {}) });
    } catch (e) {
      return { error: errorText(e) };
    }
  }, [preview]);
  const c = calc.data && !("error" in calc.data) ? calc.data : null;

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSave({ ...d, params: cleanParams(params, d.params ?? {}) });
      onClose();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const hasArch = !!d.total_height_mm && !!d.opening_height_mm && Number(d.total_height_mm) > Number(d.opening_height_mm);
  const archHeight = hasArch ? s.len(subDec(d.total_height_mm!, d.opening_height_mm!)) : "";
  const unitLabel = s.unit === "cm" ? " سم" : " مم";
  const valid = (!requireModel || d.model_id) && d.opening_width_mm && d.opening_height_mm && Number(d.qty) > 0;

  return (
    <Modal title={title} size="xwide" onClose={onClose} footer={<>
      <Btn kind="primary" busy={busy} disabled={!valid} onClick={save}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn>
      {error && <span className="danger-text small" style={{ alignSelf: "center" }}>{error}</span>}
    </>}>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0,1.1fr) minmax(0,1fr)", gap: 18 }}>
        <div className="grid g2" style={{ alignContent: "start" }}>
          <Field label="النموذج" className="span-all"><ModelSelect value={d.model_id} onChange={(id) => setD((x) => ({ ...x, model_id: id || null }))} /></Field>
          <Field label="مقاس الفتحة (العرض × الارتفاع)" className="span-all">
            <SizeIn w={d.opening_width_mm} h={d.opening_height_mm} onChange={(w, h) => setD((x) => ({ ...x, opening_width_mm: w, opening_height_mm: h }))} autoFocus />
          </Field>
          <Field label="الارتفاع الكلي (بالأرج)" hint="لو أكبر من الارتفاع: فيه أرج نص دايرة فوق الوحدة بحلق لوحده، والمساحة = العرض × الارتفاع الكلي">
            <LenIn mm={d.total_height_mm ?? null} onChange={(v) => setD((x) => ({ ...x, total_height_mm: v }))} />
          </Field>
          {hasArch && (
            <Field label="نموذج الأرج" hint={`ارتفاع الأرج ${archHeight ? archHeight + (unitLabel) : ""} · فاضي = النموذج الافتراضي من الإعدادات`}>
              <ModelSelect value={d.top_model_id} onChange={(id) => setD((x) => ({ ...x, top_model_id: id || null }))} />
            </Field>
          )}
          <ParamFields params={params} values={d.params ?? {}} onChange={(p) => setD((x) => ({ ...x, params: p }))} unit={model?.system.unit ?? "mm"} />
          <Field label="اللون"><ColorSelect value={d.color_code} onChange={(v) => setD((x) => ({ ...x, color_code: v }))} /></Field>
          <Field label="الزجاج"><GlassSelect value={d.glass_material_code} onChange={(v) => setD((x) => ({ ...x, glass_material_code: v }))} /></Field>
          <Field label="المكان"><TextIn value={d.location} onChange={(v) => setD((x) => ({ ...x, location: v }))} placeholder="صالة، مطبخ…" /></Field>
          <Field label="العدد"><NumIn value={String(d.qty ?? "")} onChange={(v) => setD((x) => ({ ...x, qty: v.replace(/\D/g, "") }))} /></Field>
          {withPrice && (
            <Field label="سعر المتر" hint="المساحة (بحد أدنى) × سعر المتر. الدليل (العادل والأعلى) ظاهر في البند بعد الحفظ">
              <NumIn value={d.price_per_m2 ?? ""} onChange={(v) => setD((x) => ({ ...x, price_per_m2: v || null }))} />
            </Field>
          )}
          {withPrice && !d.price_per_m2 && (
            <Field label="أو سعر للوحدة" hint="لو مكتبتش سعر، البند بيفضل من غير سعر">
              <NumIn value={d.manual_unit_price ?? ""} onChange={(v) => setD((x) => ({ ...x, manual_unit_price: v || null }))} />
            </Field>
          )}
          {extra}
          <Field label="ملاحظات" className="span-all"><TextIn value={d.notes} onChange={(v) => setD((x) => ({ ...x, notes: v }))} /></Field>
        </div>
        <div className="col">
          <div className="card" style={{ padding: 14 }}>
            <div className="row top">
              <MediaImg id={(model?.color_images as Record<string, string> | undefined)?.[d.color_code ?? ""] ?? model?.image_id} className="thumb lg" />
              <div className="grow">
                <b>{model?.name ?? "اختار النموذج"}</b>
                <div className="muted small">{model?.system.name}</div>
                {model && !model.system.current_version_id && <div className="notice warn small" style={{ marginTop: 6 }}>القطاع ده لسه مش منشور</div>}
                {c?.inputs && (
                  <div className="mt small">
                    <div>الفتحة: <Dim w={c.inputs.opening_width_mm} h={c.inputs.opening_height_mm} /></div>
                    <div>التصنيع: <Dim w={c.inputs.width_mm} h={c.inputs.height_mm} /></div>
                  </div>
                )}
              </div>
              {c?.drawing && <Drawing elements={c.drawing} w={c.inputs?.width_mm} h={c.inputs?.height_mm} maxW={150} maxH={120} />}
            </div>
          </div>
          {calc.loading && <div className="row muted small"><span className="spinner" />بيحسب…</div>}
          {calc.data && "error" in calc.data && <div className="notice err">{calc.data.error}</div>}
          {c && <Issues issues={c.issues} />}
          {c?.pieces && <div className="card"><div className="card-h"><h3>القطع (بالتخصيم)</h3>{c.ok === false && <Chip color="red">فيه أخطاء</Chip>}</div>
            <div className="card-b flush"><ElementPieces pieces={c.pieces} /></div></div>}
        </div>
      </div>
    </Modal>
  );
}

/** Send only parameters of the model, as plain values (numbers stay strings for exact decimals). */
export function cleanParams(params: Param[], values: Record<string, any>): Record<string, any> {
  const out: Record<string, any> = {};
  for (const p of params) {
    const v = values[p.name];
    if (v === undefined || v === "" || v === null) continue;
    out[p.name] = p.type === "bool" ? v === true || v === "true" || v === 1 : v;
  }
  return out;
}

export function ParamLabels({ modelId, values }: { modelId: string | null | undefined; values: Record<string, any> | undefined }) {
  const m = useLoad(() => modelId ? lookups.model(modelId) : Promise.resolve(undefined), [modelId]);
  const params = ((m.data?.definition ?? {}) as S<"Definition">).params ?? [];
  const parts: string[] = [];
  for (const p of params) {
    if (!values || !(p.name in values)) continue;
    const v = values[p.name];
    if (p.type === "bool") { if (v === true || v === "true") parts.push(p.label || p.name); continue; }
    if (p.type === "choice") { parts.push(`${p.label || p.name}: ${p.choices?.find((c) => String(c.value) === String(v))?.label ?? v}`); continue; }
    parts.push(`${p.label || p.name}: ${v}`);
  }
  return parts.length ? <span className="muted small">{parts.join(" · ")}</span> : null;
}
