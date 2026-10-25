// Full definition of one window/door model. Nothing here is a deduction in code: every formula,
// piece length and quantity is data typed by MYTech, checked by the server and frozen on publish.
import { useEffect, useMemo, useState } from "react";
import { api, errorText, type S } from "../api/client";
import { useTitle } from "../lib/title";
import { useAction, useLoad } from "../lib/hooks";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, Confirm, Dim, ErrorBox, Field, FilePick, Loading, Modal, NumIn, Select, SizeIn, Table, Tabs, TextArea, TextIn } from "../components/ui";
import { RowsEditor } from "../components/rows";
import { Drawing, MediaImg } from "../components/media";
import { ElementPieces, Issues, ParamFields, cleanParams, type Calc } from "../components/items";
import { useAuthor } from "./Library";
import { go, setQuery } from "../lib/router";
import { clean } from "../lib/format";
import { invalidate } from "../lib/lookups";

type Model = S<"ModelOut">;
type Def = Required<S<"Definition">>;
const EMPTY: Def = { params: [], formulas: [], pieces: [], glass: [], accessories: [], validations: [], drawing: [] };

function normalize(d: any): Def {
  return { ...EMPTY, ...(d ?? {}) };
}

export default function ModelEditor({ systemId, modelId, tab }: { systemId: string; modelId: string; tab: string }) {
  const toast = useToast();
  const { canEdit } = useAuthor();
  const { busy, run } = useAction(toast.err);
  const model = useLoad(() => api.get<Model>(`/library/models/${modelId}`), [modelId]);
  const system = useLoad(() => api.get<S<"SystemOut">>(`/library/systems/${systemId}`), [systemId]);
  const materials = useLoad(() => api.get<S<"Page_MaterialOut_">>("/library/materials", { system_id: systemId, limit: 500 }).then((p) => p.items), [systemId]);
  const allMaterials = useLoad(() => api.get<S<"Page_MaterialOut_">>("/library/materials", { limit: 500 }).then((p) => p.items), []);
  const constants = useLoad(() => api.get<S<"ConstantOut">[]>(`/library/systems/${systemId}/constants`), [systemId]);
  const [def, setDef] = useState<Def | null>(null);
  const [info, setInfo] = useState<Partial<Model> | null>(null);
  const [errors, setErrors] = useState<any[] | null>(null);
  useTitle(model.data?.name ?? "…", <><a onClick={() => go("library")} style={{ cursor: "pointer" }}>المكتبة</a> · <a onClick={() => go(`library/${systemId}`, { tab: "models" })}
    style={{ cursor: "pointer" }}>{system.data?.name ?? ""}</a></>, [model.data?.name, system.data?.name]);
  useEffect(() => { if (model.data) { setDef(normalize(model.data.definition)); setInfo(model.data); } }, [model.data?.version]); // eslint-disable-line react-hooks/exhaustive-deps

  if (model.error) return <ErrorBox text={model.error} onRetry={model.reload} />;
  if (!model.data || !def || !info || !system.data) return <Loading />;
  const m = model.data;
  const editable = canEdit(m);
  const unit = system.data.unit === "cm" ? "سم" : "مم";
  const dirty = JSON.stringify(def) !== JSON.stringify(normalize(m.definition)) ||
    ["name", "category", "description", "image_id", "status", "sort", "is_active"].some((k) => (info as any)[k] !== (m as any)[k]);
  const matOptions = [...(materials.data ?? []), ...(allMaterials.data ?? []).filter((x) => x.system_id !== systemId)]
    .map((x) => ({ value: x.code, label: `${x.code} · ${x.name}` }));
  const names = [...(constants.data ?? []).map((c) => c.name), ...def.params.map((p) => p.name), ...def.formulas.map((f) => f.key)];

  const save = () => run(async () => {
    const out = await api.patch<Model>(`/library/models/${modelId}`, { version: m.version, name: info.name, category: info.category,
      description: info.description, image_id: info.image_id, status: info.status, sort: Number(info.sort ?? 0), is_active: info.is_active, definition: def });
    model.set(out);
    invalidate("models");
    const chk = await api.post<{ errors: any[] }>(`/library/models/${modelId}/check`);
    setErrors(chk.errors);
    toast.ok(chk.errors.length ? "اتحفظ، بس فيه أخطاء لازم تتصلح قبل النشر." : "اتحفظ النموذج والفحص سليم.");
  });
  const check = () => run(async () => setErrors((await api.post<{ errors: any[] }>(`/library/models/${modelId}/check`)).errors));
  const set = <K extends keyof Def>(k: K) => (rows: Def[K]) => setDef((d) => ({ ...(d as Def), [k]: rows }));

  return (
    <div className="col" style={{ gap: 14 }}>
      <Card>
        <div className="row wrap">
          <MediaImg id={info.image_id} className="thumb lg" />
          <div className="grow">
            <div className="row"><h3 style={{ margin: 0 }}>{m.name}</h3><span className="code">{m.code}</span>
              {m.status === "trial" ? <Chip color="amber">تحت التجربة</Chip> : <Chip color="green">معتمد</Chip>}
              {!editable && <Chip color="blue">قراءة بس</Chip>}</div>
            <div className="muted small">المعادلات والثوابت بالـ{unit}. المتغيرات المتاحة: <span className="code">width</span> <span className="code">height</span> (مقاس التصنيع)،
              <span className="code">opening_width</span> <span className="code">opening_height</span> (الفتحة)، والثوابت والمتغيرات والمعادلات بأسمائها.</div>
          </div>
          <div className="row">
            <Btn icon="check" busy={busy} onClick={check}>فحص</Btn>
            {editable && <Btn kind="primary" busy={busy} disabled={!dirty} onClick={save}>حفظ</Btn>}
          </div>
        </div>
        {errors && (errors.length
          ? <div className="col mt" style={{ gap: 6 }}>{errors.map((e, i) => <div key={i} className="notice err"><span className="code">{e.where ?? e.code}</span> {e.message}</div>)}</div>
          : <div className="notice ok mt">الفحص سليم: كل المعادلات والقطع صحيحة.</div>)}
        {dirty && editable && <div className="notice warn mt">فيه تعديلات لسه متحفظتش.</div>}
      </Card>

      <Card flush>
        <Tabs value={tab} onChange={(t) => setQuery({ tab: t })} tabs={[
          { id: "info", label: "البيانات والصورة" }, { id: "params", label: "المتغيرات", count: def.params.length },
          { id: "formulas", label: "المعادلات", count: def.formulas.length }, { id: "pieces", label: "القطع والتخصيمات", count: def.pieces.length },
          { id: "glass", label: "الزجاج", count: def.glass.length }, { id: "accessories", label: "الإكسسوار", count: def.accessories.length },
          { id: "validations", label: "التحقق", count: def.validations.length }, { id: "drawing", label: "الرسمة", count: def.drawing.length },
          { id: "try", label: "تجربة الحساب" }, { id: "tests", label: "الاختبارات المرجعية" },
        ]} />
        <div className="card-b">
          {tab === "info" && <InfoTab info={info} setInfo={setInfo} editable={editable} />}
          {tab === "params" && <>
            <p className="def-help">المتغيرات اللي البياع بيختارها مع المقاس (عدد الضلف، بسلك، نوع الزجاج…). الاسم بيتكتب في المعادلات، بالعربي أو بالإنجليزي، كلمة واحدة من غير مسافات (استخدم <code>_</code>)، مثلًا <code>عدد_الضلف</code>.</p>
            <RowsEditor rows={def.params} onChange={set("params")} readOnly={!editable} addLabel="متغير"
              blank={() => ({ name: "", label: "", type: "number" as const, default: null, min: null, max: null, choices: [] })} columns={[
                { key: "name", label: "الاسم", kind: "code", width: 140 },
                { key: "label", label: "الوصف" },
                { key: "type", label: "النوع", kind: "select", width: 120, options: [
                  { value: "number", label: "رقم" }, { value: "int", label: "رقم صحيح" }, { value: "count", label: "عدد" }, { value: "length", label: `طول (${unit})` },
                  { value: "bool", label: "نعم/لا" }, { value: "choice", label: "اختيارات" }] },
                { key: "default", label: "الافتراضي", width: 100, render: (r, setR) => r.type === "bool"
                  ? <select className="input" value={String(r.default ?? "")} disabled={!editable} onChange={(e) => setR({ default: e.target.value === "" ? null : e.target.value === "true" })}>
                      <option value="">—</option><option value="true">نعم</option><option value="false">لا</option></select>
                  : <input className="input num" dir="ltr" value={r.default === null || r.default === undefined ? "" : String(r.default)} readOnly={!editable}
                      onChange={(e) => setR({ default: e.target.value === "" ? null : e.target.value })} /> },
                { key: "min", label: "من", kind: "number", width: 80 },
                { key: "max", label: "لحد", kind: "number", width: 80 },
                { key: "choices", label: "الاختيارات (قيمة=اسم، …)", render: (r, setR) => r.type !== "choice" ? <span className="faint small">—</span> :
                  <ChoicesIn value={r.choices ?? []} onChange={(choices) => setR({ choices })} readOnly={!editable} /> },
              ]} />
          </>}
          {tab === "formulas" && <>
            <p className="def-help">قيم وسيطة بتتحسب بالترتيب حسب الاعتماد، وتتكتب باسمها في القطع (زي <code>sash_w = (width + overlap) / leaf_count</code>). تقدر تكتبها <b>بالعربي</b>: <code>عرض_الضلفة = (العرض + ركوب_الضلف) ÷ عدد_الضلف</code>. الأسامي الجاهزة: <code>العرض</code> و<code>الارتفاع</code> (مقاس التصنيع) و<code>عرض_الفتحة</code> و<code>ارتفاع_الفتحة</code> و<code>خلوص_العرض</code> و<code>خلوص_الارتفاع</code>. الكلمات: <code>و</code> <code>أو</code> <code>مش</code> <code>صح</code> <code>خطأ</code>. الدوال: <code>لو(شرط، لو صح، لو غلط)</code> <code>أصغر</code> <code>أكبر</code> <code>مطلق</code> <code>تقريب</code> <code>تقريب_لأعلى</code> <code>تقريب_لأسفل</code> <code>تقريب_لخطوة</code> <code>لأعلى_لخطوة</code> <code>لأسفل_لخطوة</code> <code>حصر</code> <code>جدول</code> <code>جدول_أقل</code>، وللأرج <code>طول_القوس(العرض، الارتفاع)</code> <code>مساحة_القطعة</code> <code>باي()</code> <code>جذر</code>. ينفع كمان الإنجليزي (<code>width</code>، <code>min</code>، <code>if</code>…) والأرقام العربي و<code>×</code> و<code>÷</code>.</p>
            <RowsEditor rows={def.formulas} onChange={set("formulas")} readOnly={!editable} addLabel="معادلة" blank={() => ({ key: "", label: "", expr: "", unit: "length" as const })} columns={[
              { key: "key", label: "الاسم", kind: "code", width: 150 },
              { key: "label", label: "الوصف", width: 200 },
              { key: "expr", label: "المعادلة", kind: "expr" },
              { key: "unit", label: "النوع", kind: "select", width: 120, options: [{ value: "length", label: `طول (${unit})` }, { value: "count", label: "عدد" },
                { value: "area_m2", label: "مساحة م²" }, { value: "number", label: "رقم" }] },
            ]} />
          </>}
          {tab === "pieces" && <PiecesTab def={def} setPieces={set("pieces")} editable={editable} matOptions={matOptions} unit={unit} />}
          {tab === "glass" && <>
            <p className="def-help">مقاس كل لوح زجاج: معادلة العرض ومعادلة الارتفاع والعدد. لو اللوح مش مستطيل (زي زجاج الأرج نص الدايرة) اكتب معادلة مساحته، مثلًا <code>segment_area(width, height)</code>.</p>
            <RowsEditor rows={def.glass} onChange={set("glass")} readOnly={!editable} addLabel="زجاج"
              blank={() => ({ key: "", label: "", material_code: null, width_expr: "", height_expr: "", area_expr: null, qty_expr: "1", condition: null })} columns={[
                { key: "key", label: "الاسم", kind: "code", width: 110 },
                { key: "label", label: "الوصف", width: 140 },
                { key: "material_code", label: "الخامة (فاضي = اختيار البياع)", kind: "select", placeholder: "اختيار البياع", options: matOptions, width: 200 },
                { key: "width_expr", label: <span className="side-w">معادلة العرض</span>, kind: "expr" },
                { key: "height_expr", label: <span className="side-h">معادلة الارتفاع</span>, kind: "expr" },
                { key: "area_expr", label: "المساحة (لو مش مستطيل)", kind: "expr", width: 170 },
                { key: "qty_expr", label: "العدد", kind: "expr", width: 100 },
                { key: "condition", label: "شرط", kind: "expr", width: 120 },
              ]} />
          </>}
          {tab === "accessories" && <>
            <p className="def-help">الإكسسوار بالكمية لكل شباك (مقابض، سكاكات، عجل…).</p>
            <RowsEditor rows={def.accessories} onChange={set("accessories")} readOnly={!editable} addLabel="إكسسوار"
              blank={() => ({ key: "", label: "", material_code: "", qty_expr: "1", condition: null })} columns={[
                { key: "key", label: "الاسم", kind: "code", width: 130 },
                { key: "label", label: "الوصف" },
                { key: "material_code", label: "الخامة", kind: "select", placeholder: "اختار…", options: matOptions, width: 240 },
                { key: "qty_expr", label: "الكمية", kind: "expr", width: 140 },
                { key: "condition", label: "شرط", kind: "expr", width: 160 },
              ]} />
          </>}
          {tab === "validations" && <>
            <p className="def-help">قواعد بتتأكد إن المقاس مناسب (زي <code>width &lt;= 300</code>). خطأ = الحساب يترفض، تحذير = يظهر للبياع بس.</p>
            <RowsEditor rows={def.validations} onChange={set("validations")} readOnly={!editable} addLabel="قاعدة"
              blank={() => ({ expr: "", level: "error" as const, code: "", message: "" })} columns={[
                { key: "expr", label: "الشرط (لازم يتحقق)", kind: "expr" },
                { key: "level", label: "المستوى", kind: "select", width: 100, options: [{ value: "error", label: "خطأ" }, { value: "warning", label: "تحذير" }] },
                { key: "code", label: "الكود", kind: "code", width: 130 },
                { key: "message", label: "الرسالة اللي تظهر" },
              ]} />
          </>}
          {tab === "drawing" && <DrawingTab def={def} setDrawing={set("drawing")} editable={editable} />}
          {tab === "try" && <TryTab modelId={modelId} def={def} unitCode={system.data.unit} dirty={dirty} />}
          {tab === "tests" && <TestsTab modelId={modelId} def={def} editable={editable} />}
        </div>
      </Card>
      {names.length > 0 && tab !== "info" && tab !== "try" && tab !== "tests" && (
        <Card title="الأسماء المتاحة في المعادلات">
          <div className="row wrap" style={{ gap: 6 }}>
            {["width", "height", "opening_width", "opening_height"].map((n) => <span key={n} className="code">{n}</span>)}
            {(constants.data ?? []).map((c) => <span key={c.name} className="code" title={`${c.label} = ${clean(c.value)}`}>{c.name}</span>)}
            {def.params.map((p) => <span key={p.name} className="code" style={{ color: "var(--violet)" }} title={p.label}>{p.name}</span>)}
            {def.formulas.map((f) => <span key={f.key} className="code" style={{ color: "var(--success)" }} title={f.label}>{f.key}</span>)}
          </div>
        </Card>
      )}
    </div>
  );
}

function ChoicesIn({ value, onChange, readOnly }: { value: S<"Choice">[]; onChange: (c: S<"Choice">[]) => void; readOnly?: boolean }) {
  const [text, setText] = useState(() => value.map((c) => `${c.value}=${c.label}`).join("، "));
  return <input className="input" value={text} readOnly={readOnly} placeholder="1=زجاج عادي، 2=دبل"
    onChange={(e) => {
      setText(e.target.value);
      onChange(e.target.value.split(/[،,]/).map((p) => p.trim()).filter(Boolean).map((p) => {
        const [v, ...l] = p.split("=");
        return { value: v.trim(), label: (l.join("=") || v).trim() };
      }));
    }} />;
}

function InfoTab({ info, setInfo, editable }: { info: Partial<Model>; setInfo: (m: Partial<Model>) => void; editable: boolean }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const set = (k: keyof Model) => (v: any) => setInfo({ ...info, [k]: v });
  return (
    <div className="row top" style={{ gap: 18 }}>
      <div className="col" style={{ width: 200 }}>
        <MediaImg id={info.image_id} className="thumb lg" />
        {editable && <FilePick accept="image/png,image/jpeg,image/webp" busy={busy}
          onFile={(f) => run(async () => set("image_id")((await api.upload<S<"MediaOut">>("/library/media", f)).id))}>صورة النموذج</FilePick>}
        <div className="muted small">الصورة بتظهر في عرض السعر والفاتورة وأمر التصنيع.</div>
      </div>
      <div className="grid g2 grow">
        <Field label="الاسم"><TextIn value={info.name} onChange={set("name")} disabled={!editable} /></Field>
        <Field label="التصنيف"><TextIn value={info.category} onChange={set("category")} disabled={!editable} /></Field>
        <Field label="الحالة"><Select value={info.status} onChange={set("status")} disabled={!editable}
          options={[{ value: "trial", label: "تحت التجربة" }, { value: "approved", label: "معتمد" }]} /></Field>
        <Field label="الترتيب"><NumIn value={String(info.sort ?? 0)} onChange={set("sort")} disabled={!editable} /></Field>
        <Field label="نشط"><Select value={info.is_active ? "1" : "0"} onChange={(v) => set("is_active")(v === "1")} disabled={!editable}
          options={[{ value: "1", label: "نشط" }, { value: "0", label: "متوقف" }]} /></Field>
        <Field label="وصف" className="span-all"><TextArea value={info.description} onChange={set("description")} disabled={!editable} /></Field>
      </div>
    </div>
  );
}

type PieceRow = S<"Piece">;

function PiecesTab({ def, setPieces, editable, matOptions, unit }:
  { def: Def; setPieces: (p: PieceRow[]) => void; editable: boolean; matOptions: { value: string; label: string }[]; unit: string }) {
  const [adding, setAdding] = useState(false);
  const rows = def.pieces;
  const elements = useMemo(() => [...new Set(rows.map((p) => p.element).filter(Boolean))] as string[], [rows]);
  return (
    <>
      <p className="def-help">كل عنصر (حلق، ضلفة، باكتة، …) ليه سطر <b className="side-w">للعرض</b> وسطر <b className="side-h">للارتفاع</b>: معادلة الطول بالتخصيم، العدد، وزوايا القص. القطع بتتجمع بالعنصر في كشف التقطيع.</p>
      <RowsEditor rows={rows} onChange={setPieces} readOnly={!editable} addLabel="قطعة لوحدها"
        rowClass={(r) => r.side === "width" ? "row-w" : r.side === "height" ? "row-h" : undefined}
        blank={() => ({ key: "", label: "", element: null, side: null, role: null, material_code: "", length_expr: "", qty_expr: "1", angle_left: "90", angle_right: "90", condition: null })}
        extraActions={editable && <Btn small kind="primary" icon="plus" onClick={() => setAdding(true)}>عنصر (عرض + ارتفاع)</Btn>}
        columns={[
          { key: "element", label: "العنصر", width: 110, render: (r, set) => <>
            <input className="input" list="elements" value={r.element ?? ""} readOnly={!editable} onChange={(e) => set({ element: e.target.value || null })} />
            <datalist id="elements">{[...new Set([...elements, "حلق", "ضلفة", "باكتة", "قاطوع", "سلك", "حديد", "بار"])].map((e) => <option key={e} value={e} />)}</datalist></> },
          { key: "side", label: "عرض/ارتفاع", width: 100, render: (r, set) => (
            <select className="input" value={r.side ?? ""} disabled={!editable} onChange={(e) => set({ side: (e.target.value || null) as PieceRow["side"] })}
              style={{ color: r.side === "width" ? "var(--side-w)" : r.side === "height" ? "var(--side-h)" : undefined, fontWeight: 700 }}>
              <option value="">—</option><option value="width">عرض</option><option value="height">ارتفاع</option></select>) },
          { key: "key", label: "الاسم", kind: "code", width: 120 },
          { key: "label", label: "الوصف", width: 120 },
          { key: "material_code", label: "الخامة", kind: "select", placeholder: "اختار…", options: matOptions, width: 170 },
          { key: "length_expr", label: `معادلة الطول (${unit})`, kind: "expr" },
          { key: "qty_expr", label: "العدد", kind: "expr", width: 90 },
          { key: "angle_left", label: "زاوية ١", kind: "expr", width: 64 },
          { key: "angle_right", label: "زاوية ٢", kind: "expr", width: 64 },
          { key: "condition", label: "شرط", kind: "expr", width: 110 },
        ]} />
      {adding && <AddElement onClose={() => setAdding(false)} matOptions={matOptions} onAdd={(pieces) => setPieces([...rows, ...pieces])} />}
    </>
  );
}

function AddElement({ onClose, onAdd, matOptions }: { onClose: () => void; onAdd: (p: PieceRow[]) => void; matOptions: { value: string; label: string }[] }) {
  const [d, setD] = useState({ element: "", prefix: "", material_code: "", w_expr: "", w_qty: "2", h_expr: "", h_qty: "2", angle: "45", role: "" });
  const set = (k: keyof typeof d) => (v: string) => setD((x) => ({ ...x, [k]: v }));
  const ok = d.element && d.prefix && d.material_code && d.w_expr && d.h_expr;
  return (
    <Modal title="عنصر جديد بعرض وارتفاع" size="wide" onClose={onClose} footer={<><Btn kind="primary" disabled={!ok} onClick={() => {
      const base = { element: d.element, role: d.role || null, material_code: d.material_code, angle_left: d.angle, angle_right: d.angle, condition: null };
      onAdd([
        { ...base, key: `${d.prefix}_w`, label: `${d.element} عرض`, side: "width", length_expr: d.w_expr, qty_expr: d.w_qty },
        { ...base, key: `${d.prefix}_h`, label: `${d.element} ارتفاع`, side: "height", length_expr: d.h_expr, qty_expr: d.h_qty },
      ]);
      onClose();
    }}>إضافة</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g3">
        <Field label="العنصر"><TextIn value={d.element} onChange={set("element")} placeholder="حلق، ضلفة، باكتة…" autoFocus /></Field>
        <Field label="اسم مختصر (إنجليزي)" hint="مثال: frame → frame_w و frame_h"><TextIn value={d.prefix} onChange={(v) => set("prefix")(v.replace(/[^a-zA-Z0-9_]/g, ""))} code /></Field>
        <Field label="الخامة"><Select value={d.material_code} onChange={set("material_code")} placeholder="اختار…" options={matOptions} /></Field>
        <Field label={<span className="side-w">معادلة طول العرض</span>} className="span2"><TextIn value={d.w_expr} onChange={set("w_expr")} code placeholder="width + 2 * weld_allowance" /></Field>
        <Field label="عدد قطع العرض"><TextIn value={d.w_qty} onChange={set("w_qty")} code /></Field>
        <Field label={<span className="side-h">معادلة طول الارتفاع</span>} className="span2"><TextIn value={d.h_expr} onChange={set("h_expr")} code placeholder="height + 2 * weld_allowance" /></Field>
        <Field label="عدد قطع الارتفاع"><TextIn value={d.h_qty} onChange={set("h_qty")} code /></Field>
        <Field label="زاوية القص"><TextIn value={d.angle} onChange={set("angle")} code /></Field>
        <Field label="الدور (اختياري)" hint="frame / sash / bead…"><TextIn value={d.role} onChange={set("role")} code /></Field>
      </div>
    </Modal>
  );
}

function DrawingTab({ def, setDrawing, editable }: { def: Def; setDrawing: (d: S<"DrawingElement">[]) => void; editable: boolean }) {
  return (
    <>
      <p className="def-help">الرسمة اللي بتظهر في العرض والفاتورة: مستطيلات بمعادلات (x, y, العرض, الارتفاع) بنفس أسماء المعادلات. النوع: frame / sash / glass / panel / mullion، وفتح الضلفة: sliding-left/right، casement-left/right، tilt-left/right.</p>
      <RowsEditor rows={def.drawing} onChange={setDrawing} readOnly={!editable} addLabel="عنصر رسمة"
        blank={() => ({ type: "sash", label: null, opening: null, x: "0", y: "0", w: "", h: "", condition: null })} columns={[
          { key: "type", label: "النوع", kind: "select", width: 110, options: ["frame", "sash", "glass", "panel", "mullion"].map((v) => ({ value: v, label: v })) },
          { key: "opening", label: "الفتح", kind: "select", width: 140, placeholder: "—",
            options: ["sliding-left", "sliding-right", "casement-left", "casement-right", "tilt-left", "tilt-right", "fixed"].map((v) => ({ value: v, label: v })) },
          { key: "x", label: "x", kind: "expr" }, { key: "y", label: "y", kind: "expr" },
          { key: "w", label: "العرض", kind: "expr" }, { key: "h", label: "الارتفاع", kind: "expr" },
          { key: "condition", label: "شرط", kind: "expr", width: 110 },
          { key: "label", label: "اسم" },
        ]} />
    </>
  );
}

function useDraftCalc(modelId: string) {
  return async (w: string, h: string, params: Record<string, any>) =>
    api.post<Calc>(`/library/models/${modelId}/preview`, { model_id: modelId, opening_width_mm: w, opening_height_mm: h, params });
}

function TryTab({ modelId, def, dirty }: { modelId: string; def: Def; unitCode: string; dirty: boolean }) {
  const [w, setW] = useState<string | null>("1800");
  const [h, setH] = useState<string | null>("1400");
  const [params, setParams] = useState<Record<string, any>>({});
  const [res, setRes] = useState<Calc | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const calc = useDraftCalc(modelId);
  const go_ = async () => {
    if (!w || !h) return;
    setBusy(true); setErr(null);
    try { setRes(await calc(w, h, cleanParams(def.params, params))); } catch (e) { setErr(errorText(e)); setRes(null); } finally { setBusy(false); }
  };
  return (
    <div className="col">
      {dirty && <div className="notice warn">التجربة بتستخدم آخر نسخة محفوظة من النموذج. احفظ الأول عشان تجرب تعديلاتك.</div>}
      <div className="grid g4" style={{ alignItems: "end" }}>
        <Field label="مقاس الفتحة (العرض × الارتفاع)" className="span2"><SizeIn w={w} h={h} onChange={(a, b) => { setW(a); setH(b); }} /></Field>
        <ParamFields params={def.params} values={params} onChange={setParams} unit="" />
        <div><Btn kind="primary" icon="calc" busy={busy} onClick={go_}>احسب</Btn></div>
      </div>
      {err && <div className="notice err">{err}</div>}
      {res && <CalcResult res={res} />}
    </div>
  );
}

function CalcResult({ res }: { res: Calc }) {
  return (
    <div className="col">
      <Issues issues={res.issues} />
      <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}>
        <div className="col">
          <div>الفتحة <Dim w={res.inputs?.opening_width_mm} h={res.inputs?.opening_height_mm} /> · التصنيع <Dim w={res.inputs?.width_mm} h={res.inputs?.height_mm} /></div>
          <div className="card"><div className="card-h"><h3>القطع</h3></div><div className="card-b flush"><ElementPieces pieces={res.pieces} /></div></div>
          {!!res.glass?.length && <div className="card"><div className="card-h"><h3>الزجاج</h3></div><div className="card-b flush"><table><tbody>
            {res.glass.map((g: any) => <tr key={g.key}><td>{g.label || g.key}</td><td><Dim w={g.width_mm} h={g.height_mm} /></td><td className="num">× {g.qty}</td><td className="code">{g.material_code}</td></tr>)}
          </tbody></table></div></div>}
          {!!res.accessories?.length && <div className="card"><div className="card-h"><h3>الإكسسوار</h3></div><div className="card-b flush"><table><tbody>
            {res.accessories.map((a: any) => <tr key={a.key}><td>{a.label || a.key}</td><td className="code">{a.material_code}</td><td className="num">{clean(a.qty)}</td></tr>)}
          </tbody></table></div></div>}
          {res.values && <div className="small muted">المعادلات: {Object.entries(res.values).map(([k, v]) => <span key={k} className="code" style={{ margin: 2 }}>{k} = {clean(v)}</span>)}</div>}
        </div>
        <Drawing elements={res.drawing} w={res.inputs?.width_mm} h={res.inputs?.height_mm} maxW={280} maxH={240} />
      </div>
    </div>
  );
}

type TestCase = S<"TestCaseOut">;
type Expected = { values?: Record<string, string>; pieces?: Record<string, string>; piece_qty?: Record<string, number>;
  glass?: Record<string, [string, string]>; accessories?: Record<string, string> };

function TestsTab({ modelId, def, editable }: { modelId: string; def: Def; editable: boolean }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const tests = useLoad(() => api.get<TestCase[]>(`/library/models/${modelId}/tests`), [modelId]);
  const [results, setResults] = useState<{ passed: boolean; results: { id: string; name: string; passed: boolean; failures: string[] }[] } | null>(null);
  const [adding, setAdding] = useState(false);
  const [del, setDel] = useState<TestCase | null>(null);
  const byId = Object.fromEntries((results?.results ?? []).map((r) => [r.id, r]));
  return (
    <div className="col">
      <p className="def-help">الاختبار المرجعي = مقاس حقيقي ومعاه الأطوال الصح المتأكد منها (من المصنع أو الشيت). النشر بيترفض لو أي رقم اختلف أكتر من 0.1 مم. الأطوال هنا بالمليمتر.</p>
      <div className="row">
        <Btn icon="play" busy={busy} onClick={() => run(async () => setResults(await api.post(`/library/models/${modelId}/tests/run`)))}>تشغيل كل الاختبارات</Btn>
        {results && (results.passed ? <Chip color="green">كله مطابق</Chip> : <Chip color="red">فيه اختلاف</Chip>)}
        {editable && <Btn kind="primary" icon="plus" className="end" onClick={() => setAdding(true)}>اختبار جديد</Btn>}
      </div>
      <Table rows={tests.data} loading={tests.loading} columns={[
        { key: "n", label: "الاسم", render: (t) => <b>{t.name || "—"}</b> },
        { key: "s", label: "الفتحة (عرض × ارتفاع)", render: (t) => <Dim w={t.opening_width_mm} h={t.opening_height_mm} /> },
        { key: "p", label: "المتغيرات", render: (t) => <span className="small code">{JSON.stringify(t.params)}</span> },
        { key: "e", label: "القيم المرجعية", render: (t) => <span className="small muted">{expectedCount(t.expected as Expected)} قيمة</span> },
        { key: "r", label: "النتيجة", render: (t) => byId[t.id] ? (byId[t.id].passed ? <Chip color="green">مطابق</Chip>
          : <div className="col" style={{ gap: 2 }}><Chip color="red">مش مطابق</Chip>{byId[t.id].failures.map((f, i) => <span key={i} className="small danger-text num">{f}</span>)}</div>) : null },
        ...(editable ? [{ key: "x", label: "", width: 50, render: (t: TestCase) => <Btn small icon="trash" kind="danger" onClick={() => setDel(t)} /> }] : []),
      ]} empty="مفيش اختبارات. ضيف اختبار واحد على الأقل بمقاس حقيقي قبل اعتماد النموذج." />
      {adding && <NewTest modelId={modelId} def={def} onClose={() => setAdding(false)} onSaved={tests.reload} />}
      {del && <Confirm title="حذف الاختبار" danger yes="حذف" busy={busy} onClose={() => setDel(null)}
        onYes={() => run(async () => { await api.del(`/library/tests/${del.id}`); setDel(null); tests.reload(); })} />}
    </div>
  );
}

function expectedCount(e: Expected) {
  return ["values", "pieces", "piece_qty", "glass", "accessories"].reduce((n, k) => n + Object.keys((e as any)?.[k] ?? {}).length, 0);
}

function NewTest({ modelId, def, onClose, onSaved }: { modelId: string; def: Def; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [name, setName] = useState("");
  const [w, setW] = useState<string | null>(null);
  const [h, setH] = useState<string | null>(null);
  const [params, setParams] = useState<Record<string, any>>({});
  const [pieces, setPieces] = useState<Record<string, string>>({});
  const [qty, setQty] = useState<Record<string, string>>({});
  const [glass, setGlass] = useState<Record<string, [string, string]>>({});
  const [calc, setCalc] = useState<Calc | null>(null);
  const draft = useDraftCalc(modelId);
  const fillFromEngine = () => run(async () => {
    if (!w || !h) return;
    const r = await draft(w, h, cleanParams(def.params, params));
    setCalc(r);
  });
  const save = () => run(async () => {
    const expected: Expected = {
      pieces: Object.fromEntries(Object.entries(pieces).filter(([, v]) => v !== "")),
      piece_qty: Object.fromEntries(Object.entries(qty).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)])),
      glass: Object.fromEntries(Object.entries(glass).filter(([, v]) => v[0] !== "" && v[1] !== "")),
    };
    if (!expectedCount(expected)) throw new Error("اكتب قيمة مرجعية واحدة على الأقل.");
    await api.post(`/library/models/${modelId}/tests`, { name, opening_width_mm: w, opening_height_mm: h, params: cleanParams(def.params, params), expected });
    toast.ok("اتضاف الاختبار.");
    onSaved();
    onClose();
  });
  return (
    <Modal title="اختبار مرجعي جديد" size="xwide" onClose={onClose} footer={<><Btn kind="primary" busy={busy} disabled={!w || !h} onClick={save}>حفظ الاختبار</Btn>
      <Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g4 mb" style={{ alignItems: "end" }}>
        <Field label="الاسم"><TextIn value={name} onChange={setName} placeholder="شباك 180×140 من المصنع" autoFocus /></Field>
        <Field label="مقاس الفتحة (العرض × الارتفاع)" className="span2"><SizeIn w={w} h={h} onChange={(a, b) => { setW(a); setH(b); }} /></Field>
        <ParamFields params={def.params} values={params} onChange={setParams} unit="" />
      </div>
      <div className="notice warn mb">اكتب الأطوال الصح المتأكد منها <b>بالمليمتر</b>. زرار "اعرض حساب البرنامج" بيوريك رقم البرنامج جنب كل خانة للمقارنة بس، ومش بيملأ الخانات: القيمة المرجعية لازم تيجي من الواقع.</div>
      <div className="row mb"><Btn icon="calc" busy={busy} disabled={!w || !h} onClick={fillFromEngine}>اعرض حساب البرنامج للمقارنة</Btn></div>
      <table className="editor-table">
        <thead><tr><th>القطعة</th><th>العنصر</th><th>الطول الصح (مم)</th><th>العدد الصح</th><th>حساب البرنامج</th></tr></thead>
        <tbody>{def.pieces.map((p) => {
          const got = calc?.pieces?.find((x) => x.key === p.key);
          const diff = got && pieces[p.key] ? Math.abs(Number(got.length_mm) - Number(pieces[p.key])) : null;
          return (
            <tr key={p.key}>
              <td><span className="code">{p.key}</span> {p.label}</td>
              <td>{p.element} {p.side === "width" ? <span className="side-w">عرض</span> : p.side === "height" ? <span className="side-h">ارتفاع</span> : ""}</td>
              <td style={{ width: 140 }}><NumIn value={pieces[p.key] ?? ""} onChange={(v) => setPieces((x) => ({ ...x, [p.key]: v }))} unit="مم" /></td>
              <td style={{ width: 100 }}><NumIn value={qty[p.key] ?? ""} onChange={(v) => setQty((x) => ({ ...x, [p.key]: v.replace(/\D/g, "") }))} /></td>
              <td className="num">{got ? <span className={diff !== null && diff > 0.1 ? "danger-text bold" : ""}>{clean(got.length_mm)} مم × {got.qty}</span> : "—"}</td>
            </tr>
          );
        })}</tbody>
      </table>
      {def.glass.length > 0 && <>
        <h4 style={{ margin: "14px 0 6px" }}>الزجاج</h4>
        <table className="editor-table">
          <thead><tr><th>اللوح</th><th>العرض الصح (مم)</th><th>الارتفاع الصح (مم)</th><th>حساب البرنامج</th></tr></thead>
          <tbody>{def.glass.map((g) => {
            const got = calc?.glass?.find((x: any) => x.key === g.key);
            const v = glass[g.key] ?? ["", ""];
            return (
              <tr key={g.key}><td><span className="code">{g.key}</span> {g.label}</td>
                <td><NumIn value={v[0]} onChange={(x) => setGlass((o) => ({ ...o, [g.key]: [x, v[1]] }))} unit="مم" /></td>
                <td><NumIn value={v[1]} onChange={(x) => setGlass((o) => ({ ...o, [g.key]: [v[0], x] }))} unit="مم" /></td>
                <td>{got ? <span><span className="dim"><b>{clean(got.width_mm)}</b><span className="x">×</span>{clean(got.height_mm)}</span> مم</span> : "—"}</td></tr>
            );
          })}</tbody>
        </table>
      </>}
    </Modal>
  );
}
