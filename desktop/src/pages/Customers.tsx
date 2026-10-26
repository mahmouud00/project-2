import { useState } from "react";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useDebounced, useLoad, when } from "../lib/hooks";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, Confirm, Field, KV, Loading, ErrorBox, Modal, Money, PageHead, Pager, SearchBox, Select, Table, Tabs, TextArea, TextIn } from "../components/ui";
import { CUSTOMER_TYPES, INVOICE_STATUS, QUOTE_STATUS, STAGE_COLOR, STAGE_NAMES, SURVEY_KIND, SURVEY_STATUS } from "../lib/lookups";
import { invalidate } from "../lib/lookups";
import { go, setQuery } from "../lib/router";
import { date } from "../lib/format";
import { BranchSelect } from "../components/pickers";
import { SuggestedPrice } from "../components/surveysheet";
import { DeleteBtn } from "../components/actions";
import { Maintenance, Visits } from "../components/maintenance";
import { Progress } from "../components/field";

export default function Customers({ route }: PageProps) {
  const id = route.path[1];
  return id ? <CustomerDetail id={id} tab={route.query.tab} /> : <CustomerList />;
}

function CustomerList() {
  useTitle("العملاء");
  const s = useSession();
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const dq = useDebounced(q);
  const list = useLoad(() => api.get<S<"Page_CustomerOut_">>("/customers", { q: dq || undefined, customer_type: type || undefined, limit: 50, offset }),
    [dq, type, offset]);
  return (
    <>
      <PageHead>
        <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="بحث بالاسم أو التليفون أو الكود…" />
        <div style={{ width: 160 }}>
          <Select value={type} onChange={(v) => { setType(v); setOffset(0); }} placeholder="كل الأنواع"
            options={Object.entries(CUSTOMER_TYPES).map(([value, label]) => ({ value, label }))} />
        </div>
        {s.can("customers.create") && <Btn kind="primary" icon="plus" onClick={() => setCreating(true)}>عميل جديد</Btn>}
      </PageHead>
      {list.error && <ErrorBox text={list.error} onRetry={list.reload} />}
      <Card flush>
        <Table rows={list.data?.items} loading={list.loading} onRow={(c) => go(`customers/${c.id}`)} columns={[
          { key: "code", label: "الكود", width: 110, render: (c) => <span className="code">{c.code}</span> },
          { key: "name", label: "الاسم", render: (c) => <b>{c.name}</b> },
          { key: "type", label: "النوع", render: (c) => <Chip>{CUSTOMER_TYPES[c.customer_type] ?? c.customer_type}</Chip> },
          { key: "phone", label: "التليفون", render: (c) => <span className="num">{c.phone ?? ""}</span> },
          { key: "address", label: "العنوان", render: (c) => <span className="muted ellipsis" style={{ maxWidth: 320, display: "block" }}>{c.address ?? ""}</span> },
          ...(s.can("customers.delete") ? [{ key: "del", label: "", width: 80, render: (c: S<"CustomerOut">) =>
            <DeleteBtn path={`/customers/${c.id}`} what={`العميل ${c.name}`} onDone={list.reload} /> }] : []),
        ]} empty="مفيش عملاء لسه" />
        {list.data && <Pager total={list.data.total} limit={50} offset={offset} onChange={setOffset} />}
      </Card>
      {creating && <CustomerForm onClose={() => setCreating(false)} onSaved={(c) => go(`customers/${c.id}`)} />}
    </>
  );
}

type CustomerDraft = Partial<S<"CustomerOut">>;

export function CustomerForm({ customer, onClose, onSaved }:
  { customer?: S<"CustomerOut">; onClose: () => void; onSaved: (c: S<"CustomerOut">) => void }) {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState<CustomerDraft>(customer ?? { customer_type: "end", branch_id: s.branchId ?? s.branches[0]?.id });
  const set = (k: keyof CustomerDraft) => (v: string) => setD((x) => ({ ...x, [k]: v }));
  const priceLists = useLoad(() => api.get<S<"PriceListOut">[]>("/price-lists").catch(() => []), []);
  const save = () => run(async () => {
    const body = { name: d.name, customer_type: d.customer_type, phone: d.phone || null, phone2: d.phone2 || null,
      email: d.email || null, address: d.address || null, national_id: d.national_id || null, tax_number: d.tax_number || null,
      branch_id: d.branch_id || null, price_list_id: d.price_list_id || null, notes: d.notes || null };
    const c = customer
      ? await api.patch<S<"CustomerOut">>(`/customers/${customer.id}`, { ...body, version: customer.version })
      : await api.post<S<"CustomerOut">>("/customers", { ...body, code: d.code || null });
    invalidate("customer:" + c.id);
    toast.ok(customer ? "اتحفظت بيانات العميل." : "اتضاف العميل.");
    onSaved(c);
    onClose();
  });
  return (
    <Modal title={customer ? "تعديل بيانات العميل" : "عميل جديد"} size="wide" onClose={onClose}
      footer={<><Btn kind="primary" busy={busy} disabled={!d.name?.trim()} onClick={save}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g3">
        <Field label="الاسم" className="span2"><TextIn value={d.name} onChange={set("name")} autoFocus /></Field>
        <Field label="الكود" hint={customer ? undefined : "سيبه فاضي ويتعمل أوتوماتيك"}>
          <TextIn value={d.code} onChange={set("code")} code disabled={!!customer} /></Field>
        <Field label="النوع"><Select value={d.customer_type} onChange={set("customer_type")}
          options={Object.entries(CUSTOMER_TYPES).map(([value, label]) => ({ value, label }))} /></Field>
        <Field label="التليفون"><TextIn value={d.phone} onChange={set("phone")} code /></Field>
        <Field label="تليفون تاني"><TextIn value={d.phone2} onChange={set("phone2")} code /></Field>
        <Field label="العنوان" className="span2"><TextIn value={d.address} onChange={set("address")} /></Field>
        <Field label="الإيميل"><TextIn value={d.email} onChange={set("email")} code /></Field>
        <Field label="الرقم القومي"><TextIn value={d.national_id} onChange={set("national_id")} code /></Field>
        <Field label="الرقم الضريبي"><TextIn value={d.tax_number} onChange={set("tax_number")} code /></Field>
        <Field label="الفرع"><BranchSelect value={d.branch_id} onChange={set("branch_id")} perm={customer ? "customers.write" : "customers.create"} /></Field>
        <Field label="قائمة الأسعار" hint="لو فاضية بيتاخد قائمة نوع العميل">
          <Select value={d.price_list_id ?? ""} onChange={set("price_list_id")} placeholder="حسب نوع العميل"
            options={(priceLists.data ?? []).map((p) => ({ value: p.id, label: p.name }))} /></Field>
        <Field label="ملاحظات" className="span-all"><TextArea value={d.notes} onChange={set("notes")} rows={2} /></Field>
      </div>
    </Modal>
  );
}

type Statement = { billed: string; paid: string; balance: string;
  orders: { id: string; number: string; stage: string; total: string; paid: string; invoiced?: boolean }[];
  invoices?: { id: string; number: string; issue_date: string | null; total: string }[] };

function CustomerDetail({ id, tab: tabQuery }: { id: string; tab?: string }) {
  const s = useSession();
  const toast = useToast();
  const c = useLoad(() => api.get<S<"CustomerOut">>(`/customers/${id}`), [id]);
  useTitle(c.data?.name ?? "…", <a onClick={() => go("customers")} style={{ cursor: "pointer" }}>العملاء</a>, [c.data?.name]);
  const [edit, setEdit] = useState(false);
  const [erase, setErase] = useState(false);
  const [reason, setReason] = useState("");
  const { busy, run } = useAction(toast.err);
  const tab = tabQuery ?? (s.can("surveys.read") ? "surveys" : "quotes");
  const surveys = useLoad(() => when(s.can("surveys.read"), () => api.get<S<"Page_SurveyOut_">>("/surveys", { customer_id: id, limit: 100 })), [id]);
  const quotes = useLoad(() => when(s.can("quotes.read"), () => api.get<S<"Page_QuotationOut_">>("/quotations", { customer_id: id, limit: 100 })), [id]);
  const invoices = useLoad(() => when(s.can("treasury.read"), () => api.get<S<"Page_InvoiceOut_">>("/invoices", { customer_id: id, limit: 100 })), [id]);
  const wos = useLoad(() => when(s.can("workorders.read"), () => api.get<S<"Page_WorkOrderOut_">>("/work-orders", { customer_id: id, limit: 100 })), [id]);
  const st = useLoad(() => when(s.can("treasury.read"), () => api.get<Statement>(`/customers/${id}/statement`)), [id]);
  if (c.error) return <ErrorBox text={c.error} onRetry={c.reload} />;
  if (!c.data) return <Loading />;
  const cu = c.data;

  const exportData = () => run(async () => {
    const data = await api.get<unknown>(`/privacy/subjects/customer/${id}/export`);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    a.download = `customer-${cu.code}.json`;
    a.click();
  });

  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0,2fr) minmax(0,1fr)" }}>
        <Card title="بيانات العميل" actions={<>
          {s.can("customers.write") && !cu.anonymized && <Btn small icon="edit" onClick={() => setEdit(true)}>تعديل</Btn>}
          {s.can("quotes.create") && <Btn small kind="primary" icon="plus" onClick={() => go("quotations/new", { customer: id })}>عرض سعر</Btn>}
          {s.can("surveys.create") && <Btn small icon="ruler" onClick={() => go("surveys/new", { customer: id })}>معاينة</Btn>}
          {s.can("maintenance.create") && <Btn small icon="wrench" onClick={() => setQuery({ tab: "maintenance", new: "1" })}>طلب صيانة</Btn>}
          {s.can("customers.delete") && <DeleteBtn path={`/customers/${id}`} what={`العميل ${cu.name}`} onDone={() => go("customers")} />}
        </>}>
          {cu.anonymized && <div className="notice warn mb">البيانات الشخصية للعميل ده اتمسحت بناءً على طلبه. السجلات المالية فاضلة.</div>}
          <div className="grid g2">
            <KV items={[["الكود", <span className="code">{cu.code}</span>], ["النوع", CUSTOMER_TYPES[cu.customer_type] ?? cu.customer_type],
              ["التليفون", <span className="num">{cu.phone ?? "—"}</span>], ["تليفون تاني", <span className="num">{cu.phone2 ?? "—"}</span>]]} />
            <KV items={[["العنوان", cu.address ?? "—"], ["الإيميل", <span className="num">{cu.email ?? "—"}</span>],
              ["الرقم الضريبي", <span className="num">{cu.tax_number ?? "—"}</span>], ["ملاحظات", cu.notes ?? "—"]]} />
          </div>
        </Card>
        {st.data && (
          <Card title="الحساب">
            <div className="totals" style={{ width: "100%" }}>
              <div className="r"><span>إجمالي المطلوب</span><Money v={st.data.billed} /></div>
              <div className="r"><span>المدفوع</span><Money v={st.data.paid} /></div>
              <div className="r big"><span>الباقي</span><Money v={st.data.balance} cur /></div>
            </div>
          </Card>
        )}
      </div>

      <Card flush>
        <Tabs value={tab} onChange={(t) => setQuery({ tab: t })} tabs={[
          { id: "surveys", label: "المعاينات", count: surveys.data?.total, hidden: !s.can("surveys.read") },
          { id: "quotes", label: "عروض الأسعار", count: quotes.data?.total, hidden: !s.can("quotes.read") },
          { id: "orders", label: "أوامر التصنيع", count: wos.data?.total, hidden: !s.can("workorders.read") },
          { id: "invoices", label: "الفواتير", count: invoices.data?.total, hidden: !s.can("treasury.read") },
          { id: "maintenance", label: "الصيانة", hidden: !s.can("maintenance.read") },
          { id: "visits", label: "زيارات الفنيين", hidden: !s.can("field.read") },
          { id: "privacy", label: "البيانات الشخصية", hidden: !s.can("privacy.manage") },
        ]} />
        {tab === "surveys" && <Table rows={surveys.data?.items} loading={surveys.loading} onRow={(x) => go(`surveys/${x.id}`)} empty="مفيش معاينات" columns={[
          { key: "n", label: "الرقم", render: (x) => <span className="num">{x.number}</span> },
          { key: "k", label: "النوع", render: (x) => <Chip color={x.kind === "shutter" ? "amber" : "violet"}>{SURVEY_KIND[x.kind] ?? x.kind}</Chip> },
          { key: "d", label: "التاريخ", render: (x) => <span className="num">{date(x.survey_date ?? x.created_at)}</span> },
          { key: "o", label: "الوحدات", num: true, render: (x) => <span className="num">{x.openings?.length ?? 0}</span> },
          { key: "s", label: "الحالة", render: (x) => <Chip color={SURVEY_STATUS[x.status]?.[1]}>{SURVEY_STATUS[x.status]?.[0] ?? x.status}</Chip> },
          ...(s.can("quotes.read") ? [{ key: "p", label: "سعر المتر المقترح", num: true,
            render: (x: S<"SurveyOut">) => <SuggestedPrice surveyId={x.id} version={x.version} compact /> }] : []),
        ]} />}
        {tab === "quotes" && <Table rows={quotes.data?.items} loading={quotes.loading} onRow={(q) => go(`quotations/${q.id}`)} columns={[
          { key: "n", label: "الرقم", render: (q) => <span className="num">{q.number}</span> },
          { key: "d", label: "التاريخ", render: (q) => <span className="num">{date(q.issue_date ?? q.created_at)}</span> },
          { key: "s", label: "الحالة", render: (q) => <Chip color={QUOTE_STATUS[q.status]?.[1]}>{QUOTE_STATUS[q.status]?.[0] ?? q.status}</Chip> },
          { key: "t", label: "الإجمالي", num: true, render: (q) => <Money v={q.total} /> },
        ]} />}
        {tab === "orders" && <Table rows={wos.data?.items} loading={wos.loading} onRow={(w) => go(`work-orders/${w.id}`)} columns={[
          { key: "n", label: "الرقم", render: (w) => <span className="num">{w.number}</span> },
          { key: "s", label: "المرحلة", render: (w) => <Chip color={STAGE_COLOR[w.stage]}>{STAGE_NAMES[w.stage] ?? w.stage}</Chip> },
          { key: "t", label: "الإجمالي", num: true, render: (w) => <Money v={w.total} /> },
          { key: "p", label: "المدفوع", num: true, render: (w) => <Money v={w.paid_amount} /> },
          { key: "pr", label: "نسبة الإنجاز", width: 220, render: (w) => <Progress pct={w.progress_pct} late={w.late} expected={w.expected_delivery} /> },
          { key: "ex", label: "التسليم المتوقع", render: (w) => <span className="num">{date(w.expected_delivery)}</span> },
        ]} />}
        {tab === "maintenance" && <Maintenance customer={cu} />}
        {tab === "visits" && <Visits customerId={cu.id} />}
        {tab === "invoices" && <Table rows={invoices.data?.items} loading={invoices.loading} onRow={(i) => go(`invoices/${i.id}`)} columns={[
          { key: "n", label: "الرقم", render: (i) => <span className="num">{i.number ?? "مسودة"}</span> },
          { key: "d", label: "التاريخ", render: (i) => <span className="num">{date(i.issue_date)}</span> },
          { key: "s", label: "الحالة", render: (i) => <Chip color={INVOICE_STATUS[i.status]?.[1]}>{INVOICE_STATUS[i.status]?.[0]}</Chip> },
          { key: "t", label: "الإجمالي", num: true, render: (i) => <Money v={i.total} /> },
          { key: "b", label: "الباقي", num: true, render: (i) => <Money v={i.balance} /> },
        ]} />}
        {tab === "privacy" && (
          <div className="card-b col">
            <p className="muted" style={{ margin: 0 }}>حسب قانون حماية البيانات الشخصية (151 لسنة 2020): تقدر تصدّر كل بيانات العميل، أو تمسح بياناته الشخصية بناءً على طلبه (السجلات المالية بتفضل من غير اسم).</p>
            <div className="row">
              <Btn icon="download" busy={busy} onClick={exportData}>تصدير بيانات العميل</Btn>
              {!cu.anonymized && <Btn kind="danger" icon="trash" onClick={() => setErase(true)}>مسح البيانات الشخصية</Btn>}
            </div>
          </div>
        )}
      </Card>
      {edit && <CustomerForm customer={cu} onClose={() => setEdit(false)} onSaved={(x) => c.set(x)} />}
      {erase && (
        <Confirm title="مسح البيانات الشخصية" danger yes="مسح نهائي" busy={busy} onClose={() => setErase(false)}
          onYes={() => run(async () => {
            await api.post(`/privacy/subjects/customer/${id}/erase`, { reason });
            invalidate("customer:" + id);
            toast.ok("اتمسحت البيانات الشخصية.");
            setErase(false);
            c.reload();
          })}
          text="الاسم والتليفون والعنوان والرقم القومي هيتمسحوا ومش هيرجعوا. الفواتير والحركات المالية هتفضل.">
          <Field label="سبب المسح"><TextIn value={reason} onChange={setReason} /></Field>
        </Confirm>
      )}
    </div>
  );
}
