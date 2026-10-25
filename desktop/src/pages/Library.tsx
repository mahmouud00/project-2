// المكتبة: MYTech authors systems / materials / models once and publishes them for every customer.
// Customers see library rows read-only, add their own calibration, and may keep private systems.
import { useState, type ReactNode } from "react";
import { api, raw, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad } from "../lib/hooks";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, Confirm, ErrorBox, Field, FilePick, Loading, Modal, Money, NumIn, PageHead, Select, Table, Tabs, TextArea, TextIn } from "../components/ui";
import { RowsEditor } from "../components/rows";
import { MediaImg } from "../components/media";
import { MATERIAL_KINDS, MATERIAL_TYPES, UNITS, invalidate } from "../lib/lookups";
import { go, setQuery } from "../lib/router";
import { clean, dateTime } from "../lib/format";
import ModelEditor from "./ModelEditor";

type System = S<"SystemOut">;

export function useAuthor() {
  const s = useSession();
  const author = s.isPlatform ? s.can("platform.library.author") : s.can("library.manage");
  return {
    author,
    /** Can this row be edited by the current company? */
    canEdit: (row: { company_id: string } | undefined) => !!row && author && row.company_id === s.me.company_id,
  };
}

export default function Library({ route }: PageProps) {
  const [, systemId, sub, modelId] = route.path;
  if (systemId === "colors") return <LibraryShell tab="colors"><Colors /></LibraryShell>;
  if (systemId === "packages") return <LibraryShell tab="packages"><Packages /></LibraryShell>;
  if (systemId && sub === "models" && modelId) return <ModelEditor systemId={systemId} modelId={modelId} tab={route.query.tab ?? "info"} />;
  return <LibraryShell tab="systems"><Systems selected={systemId} tab={route.query.tab ?? "info"} /></LibraryShell>;
}

function LibraryShell({ tab, children }: { tab: string; children: ReactNode }) {
  useTitle("مكتبة القطاعات");
  return (
    <div className="col" style={{ gap: 14 }}>
      <Card flush>
        <Tabs value={tab} onChange={(t) => go(t === "systems" ? "library" : `library/${t}`)} tabs={[
          { id: "systems", label: "القطاعات والخامات والنماذج" }, { id: "colors", label: "الألوان" }, { id: "packages", label: "حزم التحديث" },
        ]} />
      </Card>
      {children}
    </div>
  );
}

function Systems({ selected, tab }: { selected?: string; tab: string }) {
  const { author } = useAuthor();
  const s = useSession();
  const [type, setType] = useState("");
  const [creating, setCreating] = useState(false);
  const list = useLoad(() => api.get<System[]>("/library/systems", { material_type: type || undefined, include_inactive: author || undefined }), [type]);
  const current = list.data?.find((x) => x.id === selected);
  return (
    <div className="split">
      <Card flush title={<div className="row grow"><h3>القطاعات</h3>
        <div className="end" style={{ width: 120 }}><Select value={type} onChange={setType} placeholder="الكل"
          options={Object.entries(MATERIAL_TYPES).map(([value, label]) => ({ value, label }))} /></div></div>}>
        <div className="list-pick">
          {(list.data ?? []).map((x) => (
            <button key={x.id} className={"sys-item" + (x.id === selected ? " on" : "")} onClick={() => go(`library/${x.id}`)}>
              <div className="row"><b className="grow">{x.name}</b>{!x.is_active && <Chip color="red">متوقف</Chip>}</div>
              <div className="meta row" style={{ gap: 6 }}>
                <span className="code">{x.code}</span><span>{MATERIAL_TYPES[x.material_type]}</span>
                {x.status === "trial" ? <Chip color="amber">تجربة</Chip> : <Chip color="green">معتمد</Chip>}
                {x.current_version_id ? <Chip color="blue">منشور</Chip> : <Chip>مش منشور</Chip>}
                {!x.is_library && <Chip color="violet">خاص بالشركة</Chip>}
              </div>
            </button>
          ))}
          {list.loading && <Loading />}
          {list.data && !list.data.length && <div className="empty">مفيش قطاعات. {author ? "ضيف أول قطاع." : "MYTech بتضيف القطاعات."}</div>}
        </div>
        {author && <div className="card-b"><Btn kind="primary" icon="plus" onClick={() => setCreating(true)} className="grow" style={{ width: "100%" }}>
          {s.isPlatform ? "قطاع جديد في المكتبة" : "قطاع خاص بالشركة"}</Btn></div>}
      </Card>
      <div>
        {current ? <SystemPanel system={current} tab={tab} onChanged={() => { invalidate("systems"); invalidate("models"); list.reload(); }} />
          : <Card><div className="empty">اختار قطاع من القائمة.</div></Card>}
      </div>
      {creating && <SystemForm onClose={() => setCreating(false)} onSaved={(x) => { invalidate("systems"); list.reload(); go(`library/${x.id}`); }} />}
    </div>
  );
}

function SystemForm({ system, onClose, onSaved }: { system?: System; onClose: () => void; onSaved: (s: System) => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState<Partial<System>>(system ?? { material_type: "upvc", unit: "cm", rounding_step_mm: "0", rounding_mode: "half_up", status: "trial", supplier: "", description: "" });
  const set = (k: keyof System) => (v: any) => setD((x) => ({ ...x, [k]: v }));
  const save = () => run(async () => {
    const body = { name: d.name, supplier: d.supplier ?? "", unit: d.unit, rounding_step_mm: d.rounding_step_mm || "0", rounding_mode: d.rounding_mode,
      status: d.status, description: d.description ?? "", image_id: d.image_id ?? null };
    const out = system ? await api.patch<System>(`/library/systems/${system.id}`, { ...body, version: system.version })
      : await api.post<System>("/library/systems", { ...body, code: d.code, material_type: d.material_type });
    onSaved(out);
    onClose();
  });
  return (
    <Modal title={system ? "بيانات القطاع" : "قطاع جديد"} size="wide" onClose={onClose}
      footer={<><Btn kind="primary" busy={busy} disabled={!d.name || !d.code} onClick={save}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g3">
        <Field label="الكود"><TextIn value={d.code} onChange={set("code")} code disabled={!!system} autoFocus /></Field>
        <Field label="الاسم" className="span2"><TextIn value={d.name} onChange={set("name")} /></Field>
        <Field label="النوع"><Select value={d.material_type} onChange={set("material_type")} disabled={!!system}
          options={Object.entries(MATERIAL_TYPES).map(([value, label]) => ({ value, label }))} /></Field>
        <Field label="المورد / الشركة المنتجة"><TextIn value={d.supplier} onChange={set("supplier")} /></Field>
        <Field label="الحالة"><Select value={d.status} onChange={set("status")} options={[{ value: "trial", label: "تحت التجربة" }, { value: "approved", label: "معتمد" }]} /></Field>
        <Field label="وحدة المعادلات" hint="الأرقام اللي في المعادلات والثوابت بالوحدة دي"><Select value={d.unit} onChange={set("unit")}
          options={[{ value: "cm", label: "سنتيمتر" }, { value: "mm", label: "مليمتر" }]} /></Field>
        <Field label="تقريب أطوال القطع (مم)" hint="0 = من غير تقريب"><NumIn value={d.rounding_step_mm} onChange={set("rounding_step_mm")} unit="مم" /></Field>
        <Field label="طريقة التقريب"><Select value={d.rounding_mode} onChange={set("rounding_mode")}
          options={[{ value: "half_up", label: "لأقرب قيمة" }, { value: "up", label: "لفوق" }, { value: "down", label: "لتحت" }]} /></Field>
        <Field label="وصف" className="span-all"><TextArea value={d.description} onChange={set("description")} rows={2} /></Field>
      </div>
    </Modal>
  );
}

function SystemPanel({ system, tab, onChanged }: { system: System; tab: string; onChanged: () => void }) {
  const s = useSession();
  const { canEdit } = useAuthor();
  const editable = canEdit(system);
  const [edit, setEdit] = useState(false);
  return (
    <Card flush>
      <div className="card-h">
        <div className="grow">
          <h3>{system.name}</h3>
          <div className="muted small row" style={{ gap: 6, marginTop: 2 }}><span className="code">{system.code}</span>{MATERIAL_TYPES[system.material_type]}
            · {system.supplier || "—"} · المعادلات بـ{system.unit === "cm" ? "السنتيمتر" : "المليمتر"}</div>
        </div>
        {!editable && system.is_library && !s.isPlatform && <Chip color="blue">من مكتبة MYTech (قراءة بس)</Chip>}
        {editable && <Btn small icon="edit" onClick={() => setEdit(true)}>تعديل</Btn>}
      </div>
      <Tabs value={tab} onChange={(t) => setQuery({ tab: t })} tabs={[
        { id: "info", label: "الثوابت" }, { id: "materials", label: "الخامات" }, { id: "models", label: "النماذج" },
        { id: "publish", label: "النشر والنسخ" }, { id: "calibration", label: "معايرة الشركة", hidden: s.isPlatform },
      ]} />
      <div className="card-b">
        {tab === "info" && <Constants system={system} editable={editable} />}
        {tab === "materials" && <Materials system={system} editable={editable} />}
        {tab === "models" && <Models system={system} editable={editable} />}
        {tab === "publish" && <Publish system={system} editable={editable} onChanged={onChanged} />}
        {tab === "calibration" && <Calibration system={system} />}
      </div>
      {edit && <SystemForm system={system} onClose={() => setEdit(false)} onSaved={onChanged} />}
    </Card>
  );
}

// ---------------------------------------------------------------- constants
function Constants({ system, editable }: { system: System; editable: boolean }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const list = useLoad(() => api.get<S<"ConstantOut">[]>(`/library/systems/${system.id}/constants`), [system.id]);
  const [edit, setEdit] = useState<Partial<S<"ConstantOut">> | null>(null);
  const [del, setDel] = useState<S<"ConstantOut"> | null>(null);
  return (
    <div className="col">
      <p className="def-help">الثوابت بتتكتب في المعادلات باسمها، بالعربي كلمة واحدة (زي <code>سماحية_اللحام</code>). <code>خلوص_العرض</code> و<code>خلوص_الارتفاع</code> (خلوص التركيب) موجودين دايمًا، عشان مقاس التصنيع = الفتحة − الخلوص. الأرقام بوحدة القطاع ({system.unit === "cm" ? "سم" : "مم"}).</p>
      {editable && <PageHead><Btn kind="primary" small icon="plus" onClick={() => setEdit({ unit: system.unit, sort: 0 })}>ثابت جديد</Btn></PageHead>}
      <Table rows={list.data} loading={list.loading} onRow={editable ? (c) => setEdit(c) : undefined} columns={[
        { key: "name", label: "الاسم في المعادلات", render: (c) => <span className="code">{BUILTIN_CONSTANTS[c.name] ?? c.name}</span> },
        { key: "label", label: "الوصف", render: (c) => c.label },
        { key: "value", label: "القيمة", num: true, render: (c) => <b className="num">{clean(c.value)}</b> },
        { key: "unit", label: "الوحدة", render: (c) => <span className="muted">{c.unit}</span> },
        { key: "d", label: "ملاحظة", render: (c) => <span className="muted small">{c.description}</span> },
        ...(editable ? [{ key: "x", label: "", width: 50, render: (c: S<"ConstantOut">) => <Btn small icon="trash" kind="danger" onClick={(e) => { e.stopPropagation(); setDel(c); }} /> }] : []),
      ]} empty="مفيش ثوابت" />
      {edit && <Modal title={edit.id ? "تعديل الثابت" : "ثابت جديد"} onClose={() => setEdit(null)} footer={<><Btn kind="primary" busy={busy}
        disabled={!edit.name || edit.value === undefined || edit.value === ""} onClick={() => run(async () => {
          const body = { label: edit.label ?? "", value: edit.value, unit: edit.unit ?? "", description: edit.description ?? "", sort: Number(edit.sort ?? 0) };
          if (edit.id) await api.patch(`/library/constants/${edit.id}`, { ...body, version: edit.version });
          else await api.post(`/library/systems/${system.id}/constants`, { ...body, name: edit.name });
          setEdit(null); list.reload();
        })}>حفظ</Btn><Btn onClick={() => setEdit(null)}>رجوع</Btn></>}>
        <div className="grid g2">
          <Field label="الاسم في المعادلات" hint="كلمة واحدة، والمسافة بتبقى _ (مثلًا سماحية_اللحام)"><TextIn value={edit.id ? BUILTIN_CONSTANTS[edit.name ?? ""] ?? edit.name : edit.name}
            onChange={(v) => setEdit({ ...edit, name: v.replace(/\s+/g, "_").replace(/[^\p{L}\p{N}_]/gu, "") })} code disabled={!!edit.id} autoFocus /></Field>
          <Field label="الوصف"><TextIn value={edit.label} onChange={(v) => setEdit({ ...edit, label: v })} /></Field>
          <Field label="القيمة"><NumIn value={edit.value} onChange={(v) => setEdit({ ...edit, value: v })} /></Field>
          <Field label="الوحدة"><TextIn value={edit.unit} onChange={(v) => setEdit({ ...edit, unit: v })} /></Field>
          <Field label="ملاحظة" className="span-all"><TextIn value={edit.description} onChange={(v) => setEdit({ ...edit, description: v })} /></Field>
        </div>
      </Modal>}
      {del && <Confirm title="حذف الثابت" danger yes="حذف" busy={busy} onClose={() => setDel(null)} text={`هتحذف ${BUILTIN_CONSTANTS[del.name] ?? del.name}. لو مستخدم في معادلة، النموذج هيفشل في الفحص.`}
        onYes={() => run(async () => { await api.del(`/library/constants/${del.id}`); setDel(null); list.reload(); })} />}
    </div>
  );
}

/** the two clearance constants every system has, shown with their Arabic names */
const BUILTIN_CONSTANTS: Record<string, string> = { install_clearance_width: "خلوص_العرض", install_clearance_height: "خلوص_الارتفاع" };

// ---------------------------------------------------------------- materials
type Material = S<"MaterialOut">;

function Materials({ system, editable }: { system: System; editable: boolean }) {
  const s = useSession();
  const list = useLoad(() => api.get<S<"Page_MaterialOut_">>("/library/materials", { system_id: system.id, limit: 500 }).then((p) => p.items), [system.id]);
  const [edit, setEdit] = useState<Partial<Material> | null>(null);
  const [setting, setSetting] = useState<Material | null>(null);
  return (
    <div className="col">
      <p className="def-help">كل خامة ليها كود بيتكتب في القطع والزجاج والإكسسوار، وألوانها (كل لون ليه SKU في المخزن). الطول والأطوال هنا بالمليمتر.</p>
      {editable && <PageHead><Btn kind="primary" small icon="plus" onClick={() => setEdit({ kind: "profile", unit: "m", status: "trial", variants: [] })}>خامة جديدة</Btn></PageHead>}
      <Table rows={list.data} loading={list.loading} onRow={(m) => editable ? setEdit(m) : !s.isPlatform && setSetting(m)} columns={[
        { key: "img", label: "", width: 70, render: (m) => <MediaImg id={m.image_id} /> },
        { key: "code", label: "الكود", render: (m) => <span className="code">{m.code}</span> },
        { key: "name", label: "الاسم", render: (m) => <b>{m.name}</b> },
        { key: "kind", label: "النوع", render: (m) => <Chip>{MATERIAL_KINDS[m.kind] ?? m.kind}</Chip> },
        { key: "bar", label: "طول العود", num: true, render: (m) => m.bar_length_mm ? <span className="num">{clean(m.bar_length_mm)} مم</span> : <span className="faint">—</span> },
        { key: "v", label: "الألوان", render: (m) => <span className="small">{(m.variants ?? []).map((v) => v.color_code).join("، ") || "—"}</span> },
        { key: "c", label: "تكلفة مرجعية", num: true, render: (m) => <Money v={m.reference_cost} /> },
        { key: "st", label: "", render: (m) => <>{m.status === "trial" && <Chip color="amber">تجربة</Chip>}{!m.is_active && <Chip color="red">متوقفة</Chip>}</> },
      ]} empty="مفيش خامات" />
      {!editable && !s.isPlatform && <div className="muted small">اضغط على خامة عشان تحط سعرها عند شركتك أو كودك الداخلي.</div>}
      {edit && <MaterialForm system={system} material={edit} onClose={() => setEdit(null)} onSaved={() => { invalidate("glass"); list.reload(); }} />}
      {setting && <MaterialSetting material={setting} onClose={() => setSetting(null)} />}
    </div>
  );
}

function MaterialForm({ system, material, onClose, onSaved }: { system: System; material: Partial<Material>; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState<Partial<Material>>(material);
  const [variants, setVariants] = useState<S<"VariantIn">[]>((material.variants ?? []).map((v) => ({ color_code: v.color_code, sku: v.sku, name: v.name,
    reference_cost: v.reference_cost, is_active: v.is_active })));
  const colors = useLoad(() => api.get<S<"ColorOut">[]>("/library/colors"), []);
  const set = (k: keyof Material) => (v: any) => setD((x) => ({ ...x, [k]: v }));
  const save = () => run(async () => {
    const body = { system_id: system.id, name: d.name, category: d.category ?? "", kind: d.kind, unit: d.unit, bar_length_mm: d.bar_length_mm || null,
      min_piece_mm: d.min_piece_mm || null, weight_kg_per_m: d.weight_kg_per_m || null, reference_cost: d.reference_cost || null,
      image_id: d.image_id ?? null, status: d.status, variants: variants.map((v) => ({ ...v, reference_cost: v.reference_cost || null })) };
    if (material.id) await api.patch(`/library/materials/${material.id}`, { ...body, version: material.version, is_active: d.is_active });
    else await api.post("/library/materials", { ...body, code: d.code });
    toast.ok("اتحفظت الخامة.");
    onSaved();
    onClose();
  });
  const upload = (f: File) => run(async () => { const m = await api.upload<S<"MediaOut">>("/library/media", f); setD((x) => ({ ...x, image_id: m.id })); });
  return (
    <Modal title={material.id ? `خامة ${material.code}` : "خامة جديدة"} size="xwide" onClose={onClose}
      footer={<><Btn kind="primary" busy={busy} disabled={!d.code || !d.name} onClick={save}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="row top" style={{ gap: 18 }}>
        <div className="col" style={{ width: 150 }}>
          <MediaImg id={d.image_id} className="thumb lg" />
          <FilePick accept="image/png,image/jpeg,image/webp" onFile={upload} busy={busy}>صورة</FilePick>
        </div>
        <div className="grid g4 grow">
          <Field label="الكود"><TextIn value={d.code} onChange={set("code")} code disabled={!!material.id} autoFocus /></Field>
          <Field label="الاسم" className="span2"><TextIn value={d.name} onChange={set("name")} /></Field>
          <Field label="التصنيف"><TextIn value={d.category} onChange={set("category")} placeholder="حلق، ضلفة، باكتة…" /></Field>
          <Field label="النوع"><Select value={d.kind} onChange={set("kind")} options={Object.entries(MATERIAL_KINDS).map(([value, label]) => ({ value, label }))} /></Field>
          <Field label="وحدة المخزن"><Select value={d.unit} onChange={set("unit")} options={Object.entries(UNITS).map(([value, label]) => ({ value, label }))} /></Field>
          <Field label="طول العود (مم)"><NumIn value={d.bar_length_mm} onChange={set("bar_length_mm")} unit="مم" /></Field>
          <Field label="أقل طول قطعة (مم)"><NumIn value={d.min_piece_mm} onChange={set("min_piece_mm")} unit="مم" /></Field>
          <Field label="الوزن كجم/متر"><NumIn value={d.weight_kg_per_m} onChange={set("weight_kg_per_m")} /></Field>
          <Field label="تكلفة مرجعية للوحدة"><NumIn value={d.reference_cost} onChange={set("reference_cost")} /></Field>
          <Field label="الحالة"><Select value={d.status} onChange={set("status")} options={[{ value: "trial", label: "تحت التجربة" }, { value: "approved", label: "معتمدة" }]} /></Field>
          {material.id && <Field label="نشطة"><Select value={d.is_active ? "1" : "0"} onChange={(v) => set("is_active")(v === "1")} options={[{ value: "1", label: "نشطة" }, { value: "0", label: "متوقفة" }]} /></Field>}
        </div>
      </div>
      <h4 style={{ margin: "18px 0 8px" }}>الألوان (كل لون = SKU في المخزن)</h4>
      <RowsEditor rows={variants} onChange={setVariants} addLabel="لون" blank={() => ({ color_code: "", sku: "", name: "", reference_cost: null, is_active: true })} columns={[
        { key: "color_code", label: "اللون", kind: "select", placeholder: "اختار…", options: (colors.data ?? []).map((c) => ({ value: c.code, label: `${c.name} (${c.code})` })) },
        { key: "sku", label: "SKU", kind: "code", render: (v, set) => <input className="input code-in" value={v.sku} placeholder={d.code && v.color_code ? `${d.code}-${v.color_code}` : ""}
          onChange={(e) => set({ sku: e.target.value })} onFocus={() => !v.sku && d.code && v.color_code && set({ sku: `${d.code}-${v.color_code}` })} /> },
        { key: "name", label: "اسم اللون عند الخامة" },
        { key: "reference_cost", label: "تكلفة مرجعية", kind: "number" },
        { key: "is_active", label: "نشط", kind: "check", width: 50 },
      ]} />
    </Modal>
  );
}

function MaterialSetting({ material, onClose }: { material: Material; onClose: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState({ color_code: "", unit_cost: "", internal_code: "", is_hidden: false });
  return (
    <Modal title={`إعداد ${material.name} عند شركتك`} onClose={onClose} footer={<><Btn kind="primary" busy={busy} onClick={() => run(async () => {
      await api.put(`/library/materials/${material.id}/settings`, { ...d, unit_cost: d.unit_cost || null, internal_code: d.internal_code || null });
      toast.ok("اتحفظ."); onClose();
    })}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col">
        <div className="notice info">ده بيتحفظ عند شركتك بس ومش بيغيّر المكتبة. التسعير بيستخدم تكلفتك بدل التكلفة المرجعية.</div>
        <Field label="اللون" hint="فاضي = كل الألوان"><Select value={d.color_code} onChange={(v) => setD((x) => ({ ...x, color_code: v }))} placeholder="كل الألوان"
          options={(material.variants ?? []).map((v) => ({ value: v.color_code, label: `${v.color_code} · ${v.sku}` }))} /></Field>
        <Field label="تكلفة الوحدة عندك"><NumIn value={d.unit_cost} onChange={(v) => setD((x) => ({ ...x, unit_cost: v }))} /></Field>
        <Field label="كودك الداخلي"><TextIn value={d.internal_code} onChange={(v) => setD((x) => ({ ...x, internal_code: v }))} code /></Field>
        <label className="check"><input type="checkbox" checked={d.is_hidden} onChange={(e) => setD((x) => ({ ...x, is_hidden: e.target.checked }))} />إخفاء الخامة عند شركتي</label>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- models
function Models({ system, editable }: { system: System; editable: boolean }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const list = useLoad(() => api.get<S<"ModelOut">[]>("/library/models", { system_id: system.id, include_inactive: editable || undefined }), [system.id]);
  const [d, setD] = useState<{ code: string; name: string; category: string } | null>(null);
  return (
    <div className="col">
      {editable && <PageHead><Btn kind="primary" small icon="plus" onClick={() => setD({ code: "", name: "", category: "" })}>نموذج جديد</Btn></PageHead>}
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))" }}>
        {(list.data ?? []).map((m) => (
          <button key={m.id} className="card" style={{ padding: 12, cursor: "pointer", textAlign: "start" }} onClick={() => go(`library/${system.id}/models/${m.id}`)}>
            <MediaImg id={m.image_id} className="thumb lg" />
            <div className="mt"><b>{m.name}</b></div>
            <div className="row small muted" style={{ gap: 6 }}><span className="code">{m.code}</span>{({ window: "شباك", door: "باب", shutter: "شيش" } as Record<string, string>)[m.category] ?? m.category}
              {m.status === "trial" && <Chip color="amber">تجربة</Chip>}{!m.is_active && <Chip color="red">متوقف</Chip>}</div>
            <div className="small muted">{((m.definition as any)?.pieces ?? []).length} قطعة · {((m.definition as any)?.params ?? []).length} متغير</div>
          </button>
        ))}
      </div>
      {list.loading && <Loading />}
      {list.data && !list.data.length && <div className="empty">مفيش نماذج</div>}
      {d && <Modal title="نموذج جديد" onClose={() => setD(null)} footer={<><Btn kind="primary" busy={busy} disabled={!d.code || !d.name} onClick={() => run(async () => {
        const m = await api.post<S<"ModelOut">>("/library/models", { system_id: system.id, ...d, definition: {} });
        invalidate("models");
        go(`library/${system.id}/models/${m.id}`);
      })}>إنشاء</Btn><Btn onClick={() => setD(null)}>رجوع</Btn></>}>
        <div className="col">
          <Field label="الكود"><TextIn value={d.code} onChange={(v) => setD({ ...d, code: v })} code autoFocus /></Field>
          <Field label="الاسم"><TextIn value={d.name} onChange={(v) => setD({ ...d, name: v })} placeholder="شباك جرار ضلفتين…" /></Field>
          <Field label="التصنيف"><TextIn value={d.category} onChange={(v) => setD({ ...d, category: v })} placeholder="شباك، باب، شاتر…" /></Field>
        </div>
      </Modal>}
    </div>
  );
}

// ---------------------------------------------------------------- publish
function Publish({ system, editable, onChanged }: { system: System; editable: boolean; onChanged: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const versions = useLoad(() => api.get<S<"VersionOut">[]>(`/library/systems/${system.id}/versions`), [system.id]);
  const [notes, setNotes] = useState("");
  const [failure, setFailure] = useState<unknown>(null);
  const publish = () => run(async () => {
    setFailure(null);
    try {
      const v = await api.post<S<"VersionOut">>(`/library/systems/${system.id}/publish`, { notes });
      toast.ok(`اتنشرت النسخة رقم ${v.version_no}.`);
      setNotes("");
      versions.reload();
      onChanged();
    } catch (e: any) {
      if (e?.details) setFailure(e.details);
      throw e;
    }
  });
  return (
    <div className="col">
      <div className="notice info">النشر بيعمل نسخة مجمّدة من الثوابت والخامات والنماذج. الحسابات وأوامر التصنيع بتستخدم آخر نسخة منشورة، والأوامر القديمة بتفضل على نسختها. النشر بيترفض لو فيه نموذج فيه غلط أو اختبار مرجعي مش مطابق (فرق أكبر من 0.1 مم).</div>
      {editable && (
        <div className="row top">
          <div className="grow"><TextIn value={notes} onChange={setNotes} placeholder="ملاحظات النسخة: إيه اللي اتغير؟" /></div>
          <Btn kind="primary" icon="upload" busy={busy} onClick={publish}>نشر نسخة جديدة</Btn>
        </div>
      )}
      {failure != null && <pre className="notice err" style={{ whiteSpace: "pre-wrap", direction: "ltr", textAlign: "left", fontSize: 12 }}>{JSON.stringify(failure, null, 2)}</pre>}
      <Table rows={versions.data} loading={versions.loading} columns={[
        { key: "no", label: "النسخة", render: (v) => <b className="num">#{v.version_no}</b> },
        { key: "at", label: "اتنشرت", render: (v) => <span className="num">{dateTime(v.published_at)}</span> },
        { key: "cur", label: "", render: (v) => v.id === system.current_version_id ? <Chip color="green">الحالية</Chip> : null },
        { key: "n", label: "ملاحظات", render: (v) => v.notes },
        { key: "h", label: "البصمة", render: (v) => <span className="code small" title={v.sha256}>{v.sha256.slice(0, 12)}</span> },
      ]} empty="لسه متنشرش" />
    </div>
  );
}

// ---------------------------------------------------------------- company calibration
function Calibration({ system }: { system: System }) {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const consts = useLoad(() => api.get<S<"ConstantOut">[]>(`/library/systems/${system.id}/constants`), [system.id]);
  const adj = useLoad(() => api.get<S<"SystemAdjustments-Output">>(`/library/systems/${system.id}/adjustments`), [system.id]);
  const [cal, setCal] = useState<S<"CalibrationItem-Input">[] | null>(null);
  const [ovr, setOvr] = useState<S<"OverrideItem-Input">[] | null>(null);
  const calibrations = cal ?? (adj.data?.calibrations ?? []);
  const overrides = ovr ?? (adj.data?.overrides ?? []);
  const options = (consts.data ?? []).map((c) => ({ value: c.name, label: `${c.label || c.name} (${clean(c.value)})` }));
  const editable = s.can("library.manage");
  if (adj.error) return <ErrorBox text={adj.error} onRetry={adj.reload} />;
  return (
    <div className="col">
      <div className="notice info">المعايرة خاصة بشركتك ومحفوظة لوحدها: تحديث المكتبة من MYTech مش بيمسحها. بتتطبق على الحسابات الجديدة بس. القيم بوحدة القطاع ({system.unit === "cm" ? "سم" : "مم"}).</div>
      <h4 style={{ margin: "4px 0" }}>فرق معايرة (بيتجمع على قيمة المكتبة)</h4>
      <RowsEditor rows={calibrations} onChange={setCal} readOnly={!editable} addLabel="فرق" blank={() => ({ constant_name: "", delta: "", note: "" })} columns={[
        { key: "constant_name", label: "الثابت", kind: "select", placeholder: "اختار…", options },
        { key: "delta", label: "الفرق (+ أو −)", kind: "number" },
        { key: "note", label: "السبب" },
      ]} />
      <h4 style={{ margin: "10px 0 4px" }}>قيمة بديلة (بتحل محل قيمة المكتبة)</h4>
      <RowsEditor rows={overrides} onChange={setOvr} readOnly={!editable} addLabel="قيمة بديلة" blank={() => ({ constant_name: "", value: "", note: "" })} columns={[
        { key: "constant_name", label: "الثابت", kind: "select", placeholder: "اختار…", options },
        { key: "value", label: "القيمة", kind: "number" },
        { key: "note", label: "السبب" },
      ]} />
      {editable && <div className="row"><Btn kind="primary" busy={busy} onClick={() => run(async () => {
        adj.set(await api.put(`/library/systems/${system.id}/adjustments`, { calibrations, overrides }));
        setCal(null); setOvr(null);
        toast.ok("اتحفظت المعايرة.");
      })}>حفظ المعايرة</Btn></div>}
    </div>
  );
}

// ---------------------------------------------------------------- colours
function Colors() {
  const { author } = useAuthor();
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const list = useLoad(() => api.get<S<"ColorOut">[]>("/library/colors"), []);
  const [edit, setEdit] = useState<Partial<S<"ColorOut">> | null>(null);
  return (
    <Card title="ألوان القطاعات" actions={author && <Btn kind="primary" small icon="plus" onClick={() => setEdit({ hex: "#FFFFFF" })}>لون جديد</Btn>} flush>
      <Table rows={list.data} loading={list.loading} onRow={(c) => author && c.company_id === s.me.company_id && setEdit(c)} columns={[
        { key: "s", label: "", width: 40, render: (c) => <span className="swatch" style={{ background: c.hex ?? "transparent", width: 22, height: 22 }} /> },
        { key: "code", label: "الكود", render: (c) => <span className="code">{c.code}</span> },
        { key: "name", label: "الاسم", render: (c) => <b>{c.name}</b> },
        { key: "o", label: "", render: (c) => c.company_id !== s.me.company_id ? <Chip color="blue">المكتبة</Chip> : !s.isPlatform ? <Chip color="violet">خاص</Chip> : null },
        { key: "a", label: "", render: (c) => !c.is_active && <Chip color="red">متوقف</Chip> },
      ]} />
      {edit && <Modal title={edit.id ? "تعديل اللون" : "لون جديد"} onClose={() => setEdit(null)} footer={<><Btn kind="primary" busy={busy} disabled={!edit.code || !edit.name}
        onClick={() => run(async () => {
          if (edit.id) await api.patch(`/library/colors/${edit.id}`, { version: edit.version, name: edit.name, hex: edit.hex, is_active: edit.is_active });
          else await api.post("/library/colors", { code: edit.code, name: edit.name, hex: edit.hex });
          invalidate("colors"); list.reload(); setEdit(null);
        })}>حفظ</Btn><Btn onClick={() => setEdit(null)}>رجوع</Btn></>}>
        <div className="col">
          <Field label="الكود" hint="بيتضاف للـ SKU (مثال: W، B، WOOD)"><TextIn value={edit.code} onChange={(v) => setEdit({ ...edit, code: v.toUpperCase() })} code disabled={!!edit.id} autoFocus /></Field>
          <Field label="الاسم"><TextIn value={edit.name} onChange={(v) => setEdit({ ...edit, name: v })} /></Field>
          <Field label="اللون"><input type="color" className="input" value={edit.hex ?? "#ffffff"} onChange={(e) => setEdit({ ...edit, hex: e.target.value })} style={{ padding: 2 }} /></Field>
          {edit.id && <label className="check"><input type="checkbox" checked={edit.is_active ?? true} onChange={(e) => setEdit({ ...edit, is_active: e.target.checked })} />نشط</label>}
        </div>
      </Modal>}
    </Card>
  );
}

// ---------------------------------------------------------------- packages
type ImportRow = { id: string; package_id: string; package_created_at: string; status: string; created_at: string; applied_at: string | null };
type Diff = { package_id: string; created_at: string; notes: string; systems: { code: string; name: string; status: string;
  constants: Record<string, any[]>; materials: Record<string, any[]>; models: Record<string, any[]>; new_versions: number[] }[] };

function Packages() {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const systems = useLoad(() => api.get<System[]>("/library/systems"), []);
  const imports = useLoad<ImportRow[]>(() => s.can("library.import") || s.isPlatform ? api.get<ImportRow[]>("/library/packages/imports").catch(() => []) : Promise.resolve([]), []);
  const [codes, setCodes] = useState<string[]>([]);
  const [notes, setNotes] = useState("");
  const [preview, setPreview] = useState<{ import_id: string; diff: Diff } | null>(null);

  const exportPkg = () => run(async () => {
    const r = await raw("/library/packages/export", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ system_codes: codes, notes }) });
    if (!r.ok) throw new Error((await r.json().catch(() => null))?.error?.message ?? "Export failed");
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `mytech-library-${new Date().toISOString().slice(0, 10)}.zip`;
    a.click();
    toast.ok("اتعملت الحزمة. وقّعها بأداة الترخيص (توقيع حزمة) قبل ما تبعتها للعملاء.");
  });

  return (
    <div className="grid g2" style={{ alignItems: "start" }}>
      {s.isPlatform && (
        <Card title="تصدير حزمة للعملاء (MYTech)">
          <div className="col">
            <p className="def-help" style={{ margin: 0 }}>اختار القطاعات المنشورة اللي عايز تبعتها (فاضي = الكل). الحزمة بتتوقّع بأداة الترخيص بالمفتاح الخاص، وبعدين العميل يستوردها من الشاشة دي.</p>
            <div className="col" style={{ gap: 4, maxHeight: 260, overflow: "auto" }}>
              {(systems.data ?? []).filter((x) => x.current_version_id).map((x) => (
                <label key={x.id} className="check"><input type="checkbox" checked={codes.includes(x.code)}
                  onChange={(e) => setCodes((c) => e.target.checked ? [...c, x.code] : c.filter((k) => k !== x.code))} />{x.name} <span className="code">{x.code}</span></label>
              ))}
            </div>
            <Field label="ملاحظات"><TextIn value={notes} onChange={setNotes} /></Field>
            <div><Btn kind="primary" icon="download" busy={busy} onClick={exportPkg}>تصدير الحزمة</Btn></div>
          </div>
        </Card>
      )}
      {!s.isPlatform && s.can("library.import") && (
        <Card title="استيراد حزمة تحديث من MYTech">
          <div className="col">
            <p className="def-help" style={{ margin: 0 }}>الحزمة لازم تكون موقّعة من MYTech. هتشوف كل التغييرات قبل التطبيق. المعايرة الخاصة بيك مش بتتغير، والنسخ المنشورة القديمة بتفضل زي ما هي.</p>
            <div><FilePick accept=".zip,.mtlib" busy={busy} onFile={(f) => run(async () => setPreview(await api.upload("/library/packages/preview", f)))}>اختار ملف الحزمة</FilePick></div>
          </div>
        </Card>
      )}
      <Card title="الحزم اللي اتطبقت" flush>
        <Table rows={imports.data} loading={imports.loading} rowKey={(r) => r.id} columns={[
          { key: "p", label: "الحزمة", render: (r) => <span className="code small">{String(r.package_id).slice(0, 13)}</span> },
          { key: "c", label: "اتعملت", render: (r) => <span className="num">{dateTime(r.package_created_at)}</span> },
          { key: "s", label: "الحالة", render: (r) => <Chip color={r.status === "applied" ? "green" : "gray"}>{r.status === "applied" ? "اتطبقت" : r.status}</Chip> },
          { key: "a", label: "", render: (r) => <span className="num small">{dateTime(r.applied_at)}</span> },
        ]} empty="مفيش" />
      </Card>
      {preview && (
        <Modal title="التغييرات اللي في الحزمة" size="wide" onClose={() => setPreview(null)} footer={<>
          <Btn kind="primary" busy={busy} onClick={() => run(async () => {
            await api.post(`/library/packages/${preview.import_id}/apply`);
            toast.ok("اتطبقت الحزمة."); invalidate(); setPreview(null); imports.reload(); systems.reload();
          })}>تطبيق التحديث</Btn><Btn onClick={() => setPreview(null)}>إلغاء</Btn></>}>
          {preview.diff.notes && <div className="notice info mb">{preview.diff.notes}</div>}
          {preview.diff.systems.map((x) => (
            <div key={x.code} className="card mb" style={{ padding: 12 }}>
              <div className="row"><b>{x.name}</b><span className="code">{x.code}</span>
                <Chip color={x.status === "new" ? "green" : x.status === "changed" ? "amber" : "gray"}>{x.status === "new" ? "جديد" : x.status === "changed" ? "اتغير" : "زي ما هو"}</Chip></div>
              {(["constants", "materials", "models"] as const).map((k) => {
                const g = x[k];
                const n = (g.added?.length ?? 0) + (g.changed?.length ?? 0) + (g.removed?.length ?? 0);
                if (!n) return null;
                const label = { constants: "الثوابت", materials: "الخامات", models: "النماذج" }[k];
                const show = (v: any) => typeof v === "string" ? v : v.code ?? v.name;
                return (
                  <div key={k} className="small mt">
                    <b>{label}:</b>
                    {!!g.added?.length && <span className="success-text"> جديد: {g.added.map(show).join("، ")}</span>}
                    {!!g.changed?.length && <span style={{ color: "var(--warning)" }}> اتغير: {g.changed.map((c: any) => c.name ? `${c.name} (${c.old} ← ${c.new})` : show(c)).join("، ")}</span>}
                    {!!g.removed?.length && <span className="danger-text"> هيتوقف: {g.removed.map(show).join("، ")}</span>}
                  </div>
                );
              })}
              {!!x.new_versions?.length && <div className="small mt">نسخ منشورة جديدة: <span className="num">{x.new_versions.map((n) => "#" + n).join("، ")}</span></div>}
            </div>
          ))}
        </Modal>
      )}
    </div>
  );
}

