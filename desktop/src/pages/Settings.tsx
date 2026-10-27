import { useState } from "react";
import { ModelSelect } from "../components/pickers";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad } from "../lib/hooks";
import { useSession, type Company } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, Field, FilePick, KV, Modal, Money, NumIn, PageHead, Select, Table, Tabs, TextArea, TextIn } from "../components/ui";
import { DeleteBtn } from "../components/actions";
import { date } from "../lib/format";
import { setQuery } from "../lib/router";

import { STAGE_NAMES, lookups } from "../lib/lookups";
const WORK_STAGES = ["survey", "quotation", "approved", "manufacturing", "assembly", "quality"] as const;
const BRANCH_KINDS: Record<string, string> = { factory: "مصنع", warehouse: "مخزن", showroom: "معرض", office: "مكتب" };

export default function Settings({ route }: PageProps) {
  useTitle("بيانات الشركة");
  const tab = route.query.tab ?? "brand";
  return (
    <Card flush>
      <Tabs value={tab} onChange={(t) => setQuery({ tab: t })} tabs={[
        { id: "brand", label: "الاسم واللوجو" }, { id: "defaults", label: "الإعدادات الافتراضية" }, { id: "branches", label: "الفروع" },
        { id: "assets", label: "الأصول ورأس المال" },
      ]} />
      <div className="card-b">{tab === "brand" ? <Brand /> : tab === "defaults" ? <Defaults /> : tab === "assets" ? <AssetsCapital />
        : <Branches />}</div>
    </Card>
  );
}

type Settings = S<"CompanySettings">;

function useCompanySave() {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const save = (patch: Partial<Settings>, name?: string) => run(async () => {
    const c = await api.patch<Company>("/company", { version: s.company.version, name: name ?? s.company.name,
      settings: { ...s.company.settings, ...patch } });
    s.setCompany(c);
    toast.ok("اتحفظت بيانات الشركة.");
  });
  return { busy, save, run };
}

function Brand() {
  const s = useSession();
  const { busy, save, run } = useCompanySave();
  const st = s.company.settings;
  const [name, setName] = useState(s.company.name);
  const [d, setD] = useState<Partial<Settings>>({ display_name: st.display_name, phone: st.phone, phone2: st.phone2, email: st.email, website: st.website,
    address: st.address, tax_number: st.tax_number, commercial_register: st.commercial_register, invoice_footer: st.invoice_footer,
    accent_color: st.accent_color || "#5048E5" });
  const set = (k: keyof Settings) => (v: string) => setD((x) => ({ ...x, [k]: v }));
  const upload = (f: File) => run(async () => { await api.upload("/company/logo", f); await s.reload(); });
  return (
    <div className="row top" style={{ gap: 24 }}>
      <div className="col" style={{ width: 220 }}>
        <div className="card" style={{ height: 160, display: "grid", placeItems: "center", background: "#fff" }}>
          {s.logoUrl ? <img src={s.logoUrl} alt="" style={{ maxWidth: "90%", maxHeight: 140, objectFit: "contain" }} /> : <span className="faint">مفيش لوجو</span>}
        </div>
        <FilePick accept="image/png,image/jpeg,image/webp" onFile={upload} busy={busy}>{s.logoUrl ? "تغيير اللوجو" : "رفع اللوجو"}</FilePick>
        <div className="muted small">اللوجو بيظهر في كل صفحات البرنامج وفي الفواتير وعروض الأسعار وكشوف التقطيع. PNG بخلفية شفافة أحسن.</div>
      </div>
      <div className="grid g3 grow">
        <Field label="الاسم المعروض" hint="بيظهر في البرنامج والمطبوعات" className="span2"><TextIn value={d.display_name} onChange={set("display_name")} /></Field>
        <Field label="الاسم القانوني"><TextIn value={name} onChange={setName} /></Field>
        <Field label="التليفون"><TextIn value={d.phone} onChange={set("phone")} code /></Field>
        <Field label="تليفون تاني"><TextIn value={d.phone2} onChange={set("phone2")} code /></Field>
        <Field label="الإيميل"><TextIn value={d.email} onChange={set("email")} code /></Field>
        <Field label="العنوان" className="span2"><TextIn value={d.address} onChange={set("address")} /></Field>
        <Field label="الموقع"><TextIn value={d.website} onChange={set("website")} code /></Field>
        <Field label="الرقم الضريبي"><TextIn value={d.tax_number} onChange={set("tax_number")} code /></Field>
        <Field label="السجل التجاري"><TextIn value={d.commercial_register} onChange={set("commercial_register")} code /></Field>
        <Field label="لون الشركة في المطبوعات">
          <div className="row"><input type="color" className="input" style={{ width: 60, padding: 2 }} value={d.accent_color ?? "#5048E5"} onChange={(e) => set("accent_color")(e.target.value)} />
            <span className="code">{d.accent_color}</span></div></Field>
        <Field label="تذييل الفاتورة" className="span-all"><TextArea value={d.invoice_footer} onChange={set("invoice_footer")} rows={2} /></Field>
        <div className="span-all"><Btn kind="primary" busy={busy} onClick={() => save(d, name)}>حفظ</Btn></div>
      </div>
    </div>
  );
}

function Defaults() {
  const s = useSession();
  const { busy, save } = useCompanySave();
  const st = s.company.settings;
  const [d, setD] = useState<Partial<Settings>>({ currency: st.currency, default_tax_pct: st.default_tax_pct, quote_validity_days: st.quote_validity_days,
    quote_waste_pct: st.quote_waste_pct, deposit_pct: st.deposit_pct, saw_kerf_mm: st.saw_kerf_mm, bar_trim_mm: st.bar_trim_mm,
    min_reusable_offcut_mm: st.min_reusable_offcut_mm, quote_terms: st.quote_terms, length_unit: st.length_unit ?? "cm",
    min_billed_area_m2: st.min_billed_area_m2, default_arch_model_id: st.default_arch_model_id ?? null,
    stage_durations_days: { ...(st.stage_durations_days ?? {}) }, supplier_discounts: { ...(st.supplier_discounts ?? {}) } });
  const systems = useLoad(() => lookups.systems().catch(() => []), []);
  const discounts = (d.supplier_discounts ?? {}) as Record<string, string | number>;
  const setDiscount = (code: string) => (v: string) => setD((x) => {
    const next = { ...(x.supplier_discounts ?? {}) } as Record<string, string>;
    if (v === "") delete next[code]; else next[code] = v;
    return { ...x, supplier_discounts: next as Settings["supplier_discounts"] };
  });
  const durations = (d.stage_durations_days ?? {}) as Record<string, string | number>;
  const setDuration = (stage: string) => (v: string) =>
    setD((x) => ({ ...x, stage_durations_days: { ...(x.stage_durations_days ?? {}), [stage]: v || "0" } as Settings["stage_durations_days"] }));
  const totalDays = WORK_STAGES.reduce((t, k) => t + (Number(durations[k]) || 0), 0);
  const set = (k: keyof Settings) => (v: any) => setD((x) => ({ ...x, [k]: v }));
  return (
    <div className="grid g4" style={{ maxWidth: 1000 }}>
      <Field label="وحدة المقاسات في البرنامج"><Select value={d.length_unit as string} onChange={set("length_unit")}
        options={[{ value: "cm", label: "سنتيمتر" }, { value: "mm", label: "مليمتر" }]} /></Field>
      <Field label="العملة"><TextIn value={d.currency} onChange={set("currency")} code /></Field>
      <Field label="الضريبة الافتراضية"><NumIn value={d.default_tax_pct as string} onChange={set("default_tax_pct")} unit="%" /></Field>
      <Field label="نسبة العربون"><NumIn value={d.deposit_pct as string} onChange={set("deposit_pct")} unit="%" /></Field>
      <Field label="صلاحية عرض السعر (يوم)"><NumIn value={String(d.quote_validity_days ?? "")} onChange={(v) => set("quote_validity_days")(Number(v) || 0)} /></Field>
      <Field label="هالك التسعير"><NumIn value={d.quote_waste_pct as string} onChange={set("quote_waste_pct")} unit="%" /></Field>
      <Field label="سُمك سلاح المنشار"><NumIn value={d.saw_kerf_mm as string} onChange={set("saw_kerf_mm")} unit="مم" /></Field>
      <Field label="تشذيب طرف العود"><NumIn value={d.bar_trim_mm as string} onChange={set("bar_trim_mm")} unit="مم" /></Field>
      <Field label="أقل باقي يتشال (مش هالك)"><NumIn value={d.min_reusable_offcut_mm as string} onChange={set("min_reusable_offcut_mm")} unit="مم" /></Field>
      <Field label="أقل مساحة بتتحسب للوحدة" hint="أي وحدة أصغر بتتحسب بالمساحة دي في سعر المتر"><NumIn value={d.min_billed_area_m2 as string} onChange={set("min_billed_area_m2")} unit="م²" /></Field>
      <Field label="نموذج الأرج الافتراضي" hint="بيتستخدم لما الوحدة يكون ليها ارتفاع كلي (أرج نص دايرة بحلق لوحده)" className="span-3">
        <ModelSelect value={d.default_arch_model_id} onChange={(id) => set("default_arch_model_id")(id || null)} /></Field>
      <div className="span-all">
        <h4 style={{ margin: "8px 0 2px" }}>مدة كل مرحلة في التصنيع (بالأيام)</h4>
        <div className="muted small">بيتحسب منها نسبة كل أمر في بروفايل العميل، وتاريخ التسليم المتوقع، والأوامر المتأخرة.
          الإجمالي: <b className="num">{totalDays}</b> يوم.</div>
      </div>
      {WORK_STAGES.map((k) => (
        <Field key={k} label={STAGE_NAMES[k]}><NumIn value={String(durations[k] ?? "")} onChange={setDuration(k)} unit="يوم" /></Field>
      ))}
      <div className="span-all">
        <h4 style={{ margin: "8px 0 2px" }}>خصم المورد لكل نوع قطاع (%)</h4>
        <div className="muted small">التكلفة = سعر المورد ناقص الخصم. الخصم اللي على الخامة نفسها (من المكتبة أو ملف الإكسيل) بيتقدّم على ده.</div>
      </div>
      {(systems.data ?? []).map((x) => (
        <Field key={x.id} label={x.name}><NumIn value={String(discounts[x.code] ?? "")} onChange={setDiscount(x.code)} unit="%" /></Field>
      ))}
      <Field label="شروط عرض السعر الافتراضية" className="span-all"><TextArea value={d.quote_terms} onChange={set("quote_terms")} /></Field>
      <div className="span-all"><Btn kind="primary" busy={busy} onClick={() => save(d)}>حفظ</Btn></div>
    </div>
  );
}

function Branches() {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const list = useLoad(() => api.get<S<"Page_BranchOut_">>("/branches", { limit: 200 }).then((p) => p.items), []);
  const [edit, setEdit] = useState<Partial<S<"BranchOut">> | null>(null);
  return (
    <div className="col">
      <PageHead>
        {s.license.max_branches && <span className="muted small">الترخيص: حتى <span className="num">{s.license.max_branches}</span> فرع</span>}
        <Btn kind="primary" icon="plus" onClick={() => setEdit({ kind: "factory", is_active: true })}>فرع جديد</Btn>
      </PageHead>
      <Table rows={list.data} loading={list.loading} onRow={(b) => setEdit(b)} columns={[
        { key: "c", label: "الكود", render: (b) => <span className="code">{b.code}</span> },
        { key: "n", label: "الاسم", render: (b) => <b>{b.name}</b> },
        { key: "k", label: "النوع", render: (b) => BRANCH_KINDS[b.kind] ?? b.kind },
        { key: "s", label: "", render: (b) => b.is_active ? <Chip color="green">نشط</Chip> : <Chip color="red">متوقف</Chip> },
      ]} />
      {edit && <Modal title={edit.id ? "تعديل الفرع" : "فرع جديد"} onClose={() => setEdit(null)} footer={<><Btn kind="primary" busy={busy} disabled={!edit.code || !edit.name}
        onClick={() => run(async () => {
          if (edit.id) await api.patch(`/branches/${edit.id}`, { version: edit.version, name: edit.name, kind: edit.kind, is_active: edit.is_active });
          else await api.post("/branches", { code: edit.code, name: edit.name, kind: edit.kind });
          setEdit(null); list.reload(); s.reload();
        })}>حفظ</Btn><Btn onClick={() => setEdit(null)}>رجوع</Btn></>}>
        <div className="col">
          <Field label="الكود" hint="بيظهر في أرقام المستندات (QT-MAIN-…)"><TextIn value={edit.code} onChange={(v) => setEdit({ ...edit, code: v.toUpperCase() })} code disabled={!!edit.id} autoFocus /></Field>
          <Field label="الاسم"><TextIn value={edit.name} onChange={(v) => setEdit({ ...edit, name: v })} /></Field>
          <Field label="النوع"><Select value={edit.kind} onChange={(v) => setEdit({ ...edit, kind: v })} options={Object.entries(BRANCH_KINDS).map(([value, label]) => ({ value, label }))} /></Field>
          {edit.id && <label className="check"><input type="checkbox" checked={edit.is_active ?? true} onChange={(e) => setEdit({ ...edit, is_active: e.target.checked })} />نشط</label>}
        </div>
      </Modal>}
    </div>
  );
}

export const ASSET_CATEGORIES: Record<string, string> = { vehicle: "عربيات", machine: "ماكينات", building: "مباني وأراضي",
  equipment: "معدات وعدد", furniture: "أثاث وأجهزة", other: "أخرى" };
type Asset = S<"AssetOut">;

/** أصول الشركة (بقيمتها، من غير إهلاك) ورأس المال = رأس المال الأساسي + الأصول + الأرباح المتراكمة. */
function AssetsCapital() {
  const s = useSession();
  const { busy, save } = useCompanySave();
  const [opening, setOpening] = useState(String(s.company.settings.opening_capital ?? "0"));
  const [edit, setEdit] = useState<Partial<Asset> | null>(null);
  const assets = useLoad(() => api.get<Asset[]>("/assets"), []);
  const cap = useLoad(() => api.get<Record<string, string>>("/finance/capital"), [s.company.version]);
  const reload = () => { assets.reload(); cap.reload(); };
  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="grid g2" style={{ alignItems: "start" }}>
        <div className="col">
          <Field label="رأس المال الأساسي" hint="الفلوس اللي الشركة بدأت بيها (من غير الأصول)">
            <NumIn value={opening} onChange={setOpening} /></Field>
          <div><Btn kind="primary" busy={busy} onClick={() => save({ opening_capital: opening || "0" })}>حفظ</Btn></div>
        </div>
        {cap.data && <KV items={[
          ["رأس المال الأساسي", <Money v={cap.data.opening_capital} />],
          ["الأصول", <Money v={cap.data.assets} />],
          ["الأرباح المتراكمة", <b className={Number(cap.data.accumulated_profit) < 0 ? "danger-text" : "success-text"}><Money v={cap.data.accumulated_profit} /></b>],
          ["رأس المال الحالي", <b><Money v={cap.data.capital} cur /></b>],
        ]} />}
      </div>
      <PageHead title="الأصول"><Btn kind="primary" icon="plus" onClick={() => setEdit({ category: "machine" })}>أصل جديد</Btn></PageHead>
      <Table rows={assets.data} loading={assets.loading} onRow={(a) => setEdit(a)} empty="مفيش أصول" columns={[
        { key: "n", label: "الأصل", render: (a) => <b>{a.name}</b> },
        { key: "c", label: "النوع", render: (a) => ASSET_CATEGORIES[a.category] ?? a.category },
        { key: "d", label: "تاريخ الشراء", render: (a) => <span className="num">{date(a.purchase_date)}</span> },
        { key: "s", label: "الحالة", render: (a) => a.status === "active" ? <Chip color="green">موجود</Chip>
          : <Chip color="gray">اتباع / اتشال {a.disposed_date ? date(a.disposed_date) : ""}</Chip> },
        { key: "v", label: "القيمة", num: true, render: (a) => <Money v={a.value} /> },
        { key: "x", label: "", width: 80, render: (a) => <DeleteBtn path={`/assets/${a.id}`} what={`الأصل ${a.name}`} onDone={reload}
          note="المسح للإدخال الغلط بس. لو الأصل اتباع أو اتشال غيّر حالته عشان التاريخ يفضل." /> },
      ]} />
      {edit && <AssetForm asset={edit} onClose={() => setEdit(null)} onSaved={reload} />}
    </div>
  );
}

function AssetForm({ asset, onClose, onSaved }: { asset: Partial<Asset>; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState({ name: asset.name ?? "", category: asset.category ?? "other", value: asset.value ?? "",
    purchase_date: asset.purchase_date ?? "", status: asset.status ?? "active", notes: asset.notes ?? "" });
  const set = (k: keyof typeof d) => (v: string) => setD((x) => ({ ...x, [k]: v }));
  return (
    <Modal title={asset.id ? asset.name ?? "" : "أصل جديد"} onClose={onClose} footer={<><Btn kind="primary" busy={busy}
      disabled={!d.name.trim() || d.value === ""} onClick={() => run(async () => {
        const body = { name: d.name, category: d.category, value: d.value, purchase_date: d.purchase_date || null, notes: d.notes };
        if (asset.id) await api.patch(`/assets/${asset.id}`, { ...body, version: asset.version, status: d.status });
        else await api.post("/assets", body);
        onSaved(); onClose();
      })}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2">
        <Field label="الاسم" className="span-all"><TextIn value={d.name} onChange={set("name")} /></Field>
        <Field label="النوع"><Select value={d.category} onChange={set("category")}
          options={Object.entries(ASSET_CATEGORIES).map(([value, label]) => ({ value, label }))} /></Field>
        <Field label="القيمة"><NumIn value={String(d.value)} onChange={set("value")} /></Field>
        <Field label="تاريخ الشراء"><input type="date" className="input" value={d.purchase_date} onChange={(e) => set("purchase_date")(e.target.value)} /></Field>
        {asset.id && <Field label="الحالة"><Select value={d.status} onChange={set("status")}
          options={[{ value: "active", label: "موجود" }, { value: "disposed", label: "اتباع / اتشال" }]} /></Field>}
        <Field label="ملاحظات" className="span-all"><TextArea value={d.notes} onChange={set("notes")} rows={2} /></Field>
      </div>
    </Modal>
  );
}
