// The survey sheet: the factory's paper form as an editable table. Windows/doors (UPVC, aluminium) and
// shutters have their own columns. Sizes are typed in the company unit (cm) and kept in mm for the API.
import { useEffect, useRef, useState } from "react";
import { api, errorText, type S } from "../api/client";
import { lookups } from "../lib/lookups";
import { useLoad } from "../lib/hooks";
import { useSession } from "../state/session";
import { Btn, Loading, Money } from "./ui";

export type SurveyKind = "window" | "shutter";

export type SheetRow = {
  key: string;
  location: string;
  opening_width_mm: string | null;
  opening_height_mm: string | null;
  total_height_mm: string | null;
  qty: number;
  model_id: string | null;
  params: Record<string, any>;
  color_code: string | null;
  color_text: string | null;
  glass_material_code: string | null;
  glass_layers: string | null;
  glass_color: string | null;
  screen_type: string | null;
  unit_kind: string | null;
  application: string;
  installation_method: string | null;
  motor_type: string | null;
  photo_id: string | null;
  notes: string;
};

let seq = 0;
export function blankRow(): SheetRow {
  return { key: "n" + ++seq, location: "", opening_width_mm: null, opening_height_mm: null, total_height_mm: null, qty: 1,
    model_id: null, params: {}, color_code: null, color_text: null, glass_material_code: null, glass_layers: null,
    glass_color: null, screen_type: null, unit_kind: null, application: "", installation_method: null, motor_type: null,
    photo_id: null, notes: "" };
}

export function rowFromApi(o: S<"OpeningOut">): SheetRow {
  const str = (v: unknown) => (v === null || v === undefined ? null : String(v));
  return { ...blankRow(), ...o, key: o.id, opening_width_mm: str(o.opening_width_mm), opening_height_mm: str(o.opening_height_mm),
    total_height_mm: str(o.total_height_mm), params: o.params ?? {}, application: o.application ?? "", notes: o.notes ?? "" };
}

export function rowToApi(r: SheetRow) {
  const t = (v: string | null) => (v && v.trim() ? v.trim() : null);
  return { location: r.location.trim(), opening_width_mm: r.opening_width_mm, opening_height_mm: r.opening_height_mm,
    total_height_mm: r.total_height_mm || null, qty: r.qty || 1, model_id: r.model_id || null, params: r.params ?? {},
    color_code: r.color_code || null, color_text: t(r.color_text), glass_material_code: r.glass_material_code || null,
    glass_layers: r.glass_layers || null, glass_color: t(r.glass_color), screen_type: r.screen_type || null,
    unit_kind: r.unit_kind || null, application: r.application.trim(), installation_method: t(r.installation_method),
    motor_type: t(r.motor_type), photo_id: r.photo_id || null, notes: r.notes };
}

/** A row nobody typed in (ignored on save). */
export function isEmptyRow(r: SheetRow): boolean {
  const b = blankRow();
  return (Object.keys(b) as (keyof SheetRow)[]).every((k) => k === "key" || k === "params" || r[k] === b[k] || (r[k] === "" && !b[k]));
}

export function rowMissingSize(r: SheetRow): boolean {
  return !isEmptyRow(r) && (!r.opening_width_mm || !r.opening_height_mm);
}

function LenCell({ mm, onChange, disabled }: { mm: string | null; onChange: (mm: string | null) => void; disabled?: boolean }) {
  const s = useSession();
  const [text, setText] = useState(() => s.len(mm));
  const last = useRef(mm);
  useEffect(() => {
    if (mm !== last.current) { last.current = mm; if (s.toApiLen(text) !== (mm ?? null)) setText(s.len(mm)); }
  }, [mm]); // eslint-disable-line react-hooks/exhaustive-deps
  const bad = text !== "" && s.toApiLen(text) === null;
  return (
    <input className={"cell num" + (bad ? " bad" : "")} inputMode="decimal" dir="ltr" value={text} disabled={disabled}
      onChange={(e) => {
        setText(e.target.value);
        const v = e.target.value === "" ? null : s.toApiLen(e.target.value);
        last.current = v;
        if (e.target.value === "" || v !== null) onChange(v);
      }} />
  );
}

function TextCell({ value, onChange, disabled, list }:
  { value: string | null; onChange: (v: string) => void; disabled?: boolean; list?: string }) {
  return <input className="cell" value={value ?? ""} disabled={disabled} list={list} onChange={(e) => onChange(e.target.value)} />;
}

/** One of a group of exclusive marks (جرار / مفصلي ...): click to set, click again to clear. */
function Mark({ on, onClick, disabled }: { on: boolean; onClick: () => void; disabled?: boolean }) {
  return (
    <button type="button" className={"mark" + (on ? " on" : "")} disabled={disabled} onClick={onClick} aria-pressed={on}>
      {on ? "✓" : ""}
    </button>
  );
}

function ModelCell({ value, onChange, disabled }: { value: string | null; onChange: (id: string | null) => void; disabled?: boolean }) {
  const models = useLoad(() => lookups.allModels(), []);
  const groups = new Map<string, { name: string; items: S<"ModelOut">[] }>();
  for (const m of models.data ?? []) {
    if (!m.is_active) continue;
    const g = groups.get(m.system.id) ?? { name: m.system.name, items: [] };
    g.items.push(m);
    groups.set(m.system.id, g);
  }
  return (
    <select className="cell" value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value || null)}
      title={models.data?.find((m) => m.id === value)?.name}>
      <option value="">—</option>
      {[...groups.entries()].map(([id, g]) => (
        <optgroup key={id} label={g.name}>
          {g.items.map((m) => <option key={m.id} value={m.id}>{m.code} · {m.name}</option>)}
        </optgroup>
      ))}
    </select>
  );
}

function ColorCell({ row, set, disabled }: { row: SheetRow; set: (p: Partial<SheetRow>) => void; disabled?: boolean }) {
  const colors = useLoad(() => lookups.colors(), []);
  const shown = row.color_text ?? colors.data?.find((c) => c.code === row.color_code)?.name ?? row.color_code ?? "";
  return (
    <input className="cell" list="sheet-colors" value={shown} disabled={disabled} onChange={(e) => {
      const v = e.target.value;
      const c = colors.data?.find((x) => x.name === v.trim() || x.code === v.trim());
      // a library colour keeps its code (its cost is used for the suggested price); anything else is kept as written
      set(c ? { color_code: c.code, color_text: null } : { color_code: null, color_text: v });
    }} />
  );
}

export function SurveySheet({ kind, rows, onChange, editable, onDetails }:
  { kind: SurveyKind; rows: SheetRow[]; onChange: (rows: SheetRow[]) => void; editable: boolean;
    onDetails?: (index: number) => void }) {
  const colors = useLoad(() => lookups.colors(), []);
  const set = (i: number) => (p: Partial<SheetRow>) => onChange(rows.map((r, k) => (k === i ? { ...r, ...p } : r)));
  const toggle = (i: number, field: "unit_kind" | "glass_layers" | "screen_type", value: string) =>
    set(i)({ [field]: rows[i][field] === value ? null : value } as Partial<SheetRow>);
  const off = !editable;
  const actions = (i: number) => editable || onDetails ? (
    <td className="act">
      <div className="row" style={{ gap: 2, flexWrap: "nowrap" }}>
        {onDetails && <Btn small icon="edit" onClick={() => onDetails(i)} title="تفاصيل (النموذج، الزجاج، العدد، ملاحظات)" />}
        {editable && <Btn small icon="trash" kind="danger" onClick={() => onChange(rows.filter((_, k) => k !== i))} title="حذف الصف" />}
      </div>
    </td>
  ) : null;
  const num = (i: number, r: SheetRow) => (
    <td className="num muted pos" title={r.qty > 1 ? `العدد ${r.qty}` : undefined}>{i + 1}{r.qty > 1 && <span className="qty">×{r.qty}</span>}</td>
  );

  return (
    <div className="sheet-wrap">
      <datalist id="sheet-colors">{(colors.data ?? []).filter((c) => c.is_active).map((c) => <option key={c.code} value={c.name} />)}</datalist>
      {kind === "shutter" ? (
        <table className="sheet">
          <thead>
            <tr><th colSpan={2}>رقم الوحدة</th><th>العرض</th><th>الارتفاع</th><th>طريقة التركيب</th><th>نوع الموتور</th><th>اللون</th><th>مكان الوحدة</th>{(editable || onDetails) && <th />}</tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.key} className={rowMissingSize(r) ? "missing" : undefined}>
                {num(i, r)}
                <td className="w-model"><ModelCell value={r.model_id} disabled={off} onChange={(v) => set(i)({ model_id: v })} /></td>
                <td className="w-len"><LenCell mm={r.opening_width_mm} disabled={off} onChange={(v) => set(i)({ opening_width_mm: v })} /></td>
                <td className="w-len"><LenCell mm={r.opening_height_mm} disabled={off} onChange={(v) => set(i)({ opening_height_mm: v })} /></td>
                <td><TextCell value={r.installation_method} disabled={off} onChange={(v) => set(i)({ installation_method: v })} /></td>
                <td><TextCell value={r.motor_type} disabled={off} onChange={(v) => set(i)({ motor_type: v })} /></td>
                <td><ColorCell row={r} disabled={off} set={set(i)} /></td>
                <td><TextCell value={r.location} disabled={off} onChange={(v) => set(i)({ location: v })} /></td>
                {actions(i)}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <table className="sheet">
          <thead>
            <tr>
              <th colSpan={2} rowSpan={2}>رقم الوحدة</th><th colSpan={3}>المساحة</th><th colSpan={2}>نوع الوحدة</th>
              <th rowSpan={2}>اللون</th><th colSpan={2}>الزجاج</th><th rowSpan={2}>اللون</th><th colSpan={4}>السلك</th>
              <th rowSpan={2}>نوع الغرفة</th><th rowSpan={2}>التطبيق</th>{(editable || onDetails) && <th rowSpan={2} />}
            </tr>
            <tr>
              <th>عرض</th><th>ارتفاع</th><th>ارتفاع كلي</th><th>جرار</th><th>مفصلي</th><th>سنجل</th><th>دبل</th>
              <th>جرار</th><th>بليسيه</th><th>ض.ض</th><th>ثابت</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.key} className={rowMissingSize(r) ? "missing" : undefined}>
                {num(i, r)}
                <td className="w-model"><ModelCell value={r.model_id} disabled={off} onChange={(v) => set(i)({ model_id: v })} /></td>
                <td className="w-len"><LenCell mm={r.opening_width_mm} disabled={off} onChange={(v) => set(i)({ opening_width_mm: v })} /></td>
                <td className="w-len"><LenCell mm={r.opening_height_mm} disabled={off} onChange={(v) => set(i)({ opening_height_mm: v })} /></td>
                <td className="w-len"><LenCell mm={r.total_height_mm} disabled={off} onChange={(v) => set(i)({ total_height_mm: v })} /></td>
                <td className="w-mark"><Mark on={r.unit_kind === "sliding"} disabled={off} onClick={() => toggle(i, "unit_kind", "sliding")} /></td>
                <td className="w-mark"><Mark on={r.unit_kind === "hinged"} disabled={off} onClick={() => toggle(i, "unit_kind", "hinged")} /></td>
                <td className="w-color"><ColorCell row={r} disabled={off} set={set(i)} /></td>
                <td className="w-mark"><Mark on={r.glass_layers === "single"} disabled={off} onClick={() => toggle(i, "glass_layers", "single")} /></td>
                <td className="w-mark"><Mark on={r.glass_layers === "double"} disabled={off} onClick={() => toggle(i, "glass_layers", "double")} /></td>
                <td className="w-color"><TextCell value={r.glass_color} disabled={off} onChange={(v) => set(i)({ glass_color: v })} /></td>
                {(["sliding", "pleated", "hinged", "fixed"] as const).map((t) => (
                  <td key={t} className="w-mark"><Mark on={r.screen_type === t} disabled={off} onClick={() => toggle(i, "screen_type", t)} /></td>
                ))}
                <td className="w-room"><TextCell value={r.location} disabled={off} onChange={(v) => set(i)({ location: v })} /></td>
                <td className="w-app"><TextCell value={r.application} disabled={off} onChange={(v) => set(i)({ application: v })} /></td>
                {actions(i)}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!rows.length && <div className="empty">مفيش صفوف لسه</div>}
    </div>
  );
}

type Pricing = S<"SurveyPricing">;

/** Suggested price per m² of a whole survey (average), from the real cost of each opening at its sizes. */
export function SuggestedPrice({ surveyId, version, compact }: { surveyId: string; version?: number; compact?: boolean }) {
  const p = useLoad(() => api.get<Pricing>(`/surveys/${surveyId}/pricing`).catch((e) => ({ error: errorText(e) })), [surveyId, version]);
  if (p.loading && !p.data) return compact ? <span className="spinner" /> : <Loading />;
  const d = p.data as Pricing | { error: string } | undefined;
  if (!d) return null;
  if ("error" in d) return compact ? <span className="faint small">—</span> : <div className="notice warn">{d.error}</div>;
  if (compact) {
    return d.price_per_m2
      ? <span title={d.unpriced ? `${d.unpriced} فتحة من غير نموذج مش داخلة في الحساب` : undefined}><Money v={d.price_per_m2} /><span className="muted small"> / م²</span>{d.unpriced ? <span className="faint small"> *</span> : null}</span>
      : <span className="faint small">محتاج نموذج</span>;
  }
  return (
    <div className="totals" style={{ width: "100%" }}>
      <div className="r big"><span>سعر المتر المقترح</span>{d.price_per_m2 ? <span><Money v={d.price_per_m2} cur /> <span className="muted small">/ م²</span></span> : <span className="faint">—</span>}</div>
      <div className="r"><span>المساحة المحسوبة</span><span className="num">{Number(d.billed_area_m2).toFixed(2)} م²</span></div>
      <div className="r"><span>الإجمالي المقترح</span><Money v={d.suggested_total} /></div>
      <div className="r small muted"><span>محسوب من تكلفة الخامات بالتخصيمات + المصنعية والربح من قائمة الأسعار، وأي فتحة أقل من الحد الأدنى بتتحسب بيه.</span></div>
      {d.unpriced > 0 && <div className="notice warn small" style={{ marginTop: 6 }}>{d.unpriced} فتحة مش داخلة في الحساب (من غير نموذج أو النموذج مش منشور).</div>}
    </div>
  );
}

