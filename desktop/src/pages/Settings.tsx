import { useState } from "react";
import { ModelSelect } from "../components/pickers";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad } from "../lib/hooks";
import { useSession, type Company } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, Field, FilePick, Modal, NumIn, PageHead, Select, Table, Tabs, TextArea, TextIn } from "../components/ui";
import { setQuery } from "../lib/router";

const BRANCH_KINDS: Record<string, string> = { factory: "مصنع", warehouse: "مخزن", showroom: "معرض", office: "مكتب" };

export default function Settings({ route }: PageProps) {
  useTitle("بيانات الشركة");
  const tab = route.query.tab ?? "brand";
  return (
    <Card flush>
      <Tabs value={tab} onChange={(t) => setQuery({ tab: t })} tabs={[
        { id: "brand", label: "الاسم واللوجو" }, { id: "defaults", label: "الإعدادات الافتراضية" }, { id: "branches", label: "الفروع" },
      ]} />
      <div className="card-b">{tab === "brand" ? <Brand /> : tab === "defaults" ? <Defaults /> : <Branches />}</div>
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
    min_billed_area_m2: st.min_billed_area_m2, default_arch_model_id: st.default_arch_model_id ?? null });
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
      <Field label="أقل باقي يرجع المخزن"><NumIn value={d.min_reusable_offcut_mm as string} onChange={set("min_reusable_offcut_mm")} unit="مم" /></Field>
      <Field label="أقل مساحة بتتحسب للوحدة" hint="أي وحدة أصغر بتتحسب بالمساحة دي في سعر المتر"><NumIn value={d.min_billed_area_m2 as string} onChange={set("min_billed_area_m2")} unit="م²" /></Field>
      <Field label="نموذج الأرج الافتراضي" hint="بيتستخدم لما الوحدة يكون ليها ارتفاع كلي (أرج نص دايرة بحلق لوحده)" className="span-3">
        <ModelSelect value={d.default_arch_model_id} onChange={(id) => set("default_arch_model_id")(id || null)} /></Field>
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
