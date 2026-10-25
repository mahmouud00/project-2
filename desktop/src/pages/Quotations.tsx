import { useEffect, useState } from "react";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad } from "../lib/hooks";
import { useDefaultBranch, useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, Confirm, Dim, ErrorBox, Field, Len, Loading, Modal, Money, NumIn, PageHead, Pager, Select, Table, TextArea } from "../components/ui";
import { BranchName, BranchSelect, ColorName, CustomerName, CustomerPicker } from "../components/pickers";
import { ItemForm, ParamLabels, type ItemDraft } from "../components/items";
import { Drawing, MediaImg, PrintPreview } from "../components/media";
import { QUOTE_STATUS, lookups } from "../lib/lookups";
import { go } from "../lib/router";
import { date, mulMoney, sumMoney } from "../lib/format";

type Quote = S<"QuotationOut">;
type Line = S<"app__modules__sales__router__LineOut">;

export default function Quotations({ route }: PageProps) {
  const id = route.path[1];
  if (id === "new") return <NewQuotation customerId={route.query.customer} surveyId={route.query.survey} />;
  return id ? <QuotationDetail id={id} /> : <QuotationList />;
}

function QuotationList() {
  useTitle("عروض الأسعار");
  const s = useSession();
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const list = useLoad(() => api.get<S<"Page_QuotationOut_">>("/quotations", { status: status || undefined, limit: 50, offset }), [status, offset]);
  const rows = (list.data?.items ?? []).filter((q) => !s.branchId || q.branch_id === s.branchId);
  return (
    <>
      <PageHead>
        <div style={{ width: 180 }}>
          <Select value={status} onChange={(v) => { setStatus(v); setOffset(0); }} placeholder="كل الحالات"
            options={Object.entries(QUOTE_STATUS).filter(([k]) => k !== "ordered").map(([value, [label]]) => ({ value, label }))} />
        </div>
        {s.can("quotes.write") && <Btn kind="primary" icon="plus" onClick={() => go("quotations/new")}>عرض سعر جديد</Btn>}
      </PageHead>
      {list.error && <ErrorBox text={list.error} onRetry={list.reload} />}
      <Card flush>
        <Table rows={rows} loading={list.loading} onRow={(q) => go(`quotations/${q.id}`)} columns={[
          { key: "n", label: "الرقم", render: (q) => <span className="num bold">{q.number}</span> },
          { key: "c", label: "العميل", render: (q) => <CustomerName id={q.customer_id} /> },
          { key: "b", label: "الفرع", render: (q) => <BranchName id={q.branch_id} /> },
          { key: "d", label: "التاريخ", render: (q) => <span className="num">{date(q.issue_date ?? q.created_at)}</span> },
          { key: "v", label: "صالح لحد", render: (q) => <span className="num">{date(q.valid_until)}</span> },
          { key: "s", label: "الحالة", render: (q) => <Chip color={QUOTE_STATUS[q.status]?.[1]}>{QUOTE_STATUS[q.status]?.[0] ?? q.status}</Chip> },
          { key: "t", label: "الإجمالي", num: true, render: (q) => <b><Money v={q.total} /></b> },
        ]} empty="مفيش عروض أسعار" />
        {list.data && <Pager total={list.data.total} limit={50} offset={offset} onChange={setOffset} />}
      </Card>
    </>
  );
}

function NewQuotation({ customerId, surveyId }: { customerId?: string; surveyId?: string }) {
  useTitle("عرض سعر جديد", <a onClick={() => go("quotations")} style={{ cursor: "pointer" }}>عروض الأسعار</a>);
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const branch = useDefaultBranch("quotes.write");
  const [d, setD] = useState<{ customer_id?: string | null; branch_id?: string | null; price_list_id?: string; survey_id?: string }>(
    { customer_id: customerId ?? null, branch_id: branch, survey_id: surveyId });
  const priceLists = useLoad(() => lookups.priceLists().catch(() => []), []);
  const surveys = useLoad(() => d.customer_id ? api.get<S<"Page_SurveyOut_">>("/surveys", { customer_id: d.customer_id, limit: 50 }).then((p) => p.items)
    : Promise.resolve([]), [d.customer_id]);
  const create = () => run(async () => {
    const q = await api.post<Quote>("/quotations", { customer_id: d.customer_id, branch_id: d.branch_id,
      price_list_id: d.price_list_id || null, survey_id: d.survey_id || null });
    go(`quotations/${q.id}`);
  });
  return (
    <Card title="بيانات العرض" className="" >
      <div className="grid g2" style={{ maxWidth: 820 }}>
        <Field label="العميل" className="span-all"><CustomerPicker value={d.customer_id} onChange={(id) => setD((x) => ({ ...x, customer_id: id, survey_id: undefined }))} /></Field>
        <Field label="الفرع"><BranchSelect value={d.branch_id} onChange={(v) => setD((x) => ({ ...x, branch_id: v }))} perm="quotes.write" /></Field>
        <Field label="قائمة الأسعار" hint="لو فاضية بتتاخد قائمة العميل أو نوعه">
          <Select value={d.price_list_id ?? ""} onChange={(v) => setD((x) => ({ ...x, price_list_id: v }))} placeholder="حسب العميل"
            options={(priceLists.data ?? []).filter((p) => p.is_active).map((p) => ({ value: p.id, label: p.name }))} /></Field>
        <Field label="من معاينة" hint="فتحات المعاينة اللي ليها نموذج بتتنقل للعرض" className="span-all">
          <Select value={d.survey_id ?? ""} onChange={(v) => setD((x) => ({ ...x, survey_id: v }))} placeholder="من غير معاينة"
            options={(surveys.data ?? []).map((s) => ({ value: s.id, label: `${s.number} · ${s.openings?.length ?? 0} فتحة` }))} /></Field>
      </div>
      <div className="row mt"><Btn kind="primary" busy={busy} disabled={!d.customer_id || !d.branch_id} onClick={create}>إنشاء العرض</Btn></div>
    </Card>
  );
}

const NEXT: Record<string, { to: string; label: string; kind?: "primary" | "success" | "danger" }[]> = {
  draft: [{ to: "sent", label: "اتبعت للعميل" }, { to: "accepted", label: "العميل وافق", kind: "success" }, { to: "rejected", label: "العميل رفض", kind: "danger" }],
  sent: [{ to: "accepted", label: "العميل وافق", kind: "success" }, { to: "rejected", label: "العميل رفض", kind: "danger" }, { to: "draft", label: "رجوع لمسودة" }],
  rejected: [{ to: "draft", label: "رجوع لمسودة" }],
  expired: [{ to: "draft", label: "رجوع لمسودة" }],
};

function QuotationDetail({ id }: { id: string }) {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const q = useLoad(() => api.get<Quote>(`/quotations/${id}`), [id]);
  useTitle(q.data ? `عرض سعر ${q.data.number}` : "…", <a onClick={() => go("quotations")} style={{ cursor: "pointer" }}>عروض الأسعار</a>, [q.data?.number]);
  const [lineEdit, setLineEdit] = useState<Line | "new" | null>(null);
  const [allPpm, setAllPpm] = useState(false);
  const [del, setDel] = useState<Line | null>(null);
  const [printing, setPrinting] = useState(false);
  const [toWo, setToWo] = useState(false);
  const [header, setHeader] = useState(false);
  if (q.error) return <ErrorBox text={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const quote = q.data;
  const editable = ["draft", "sent"].includes(quote.status) && s.can("quotes.write", quote.branch_id);
  const allLines = quote.lines ?? [];
  // an arch (أرج) line is a unit of its own for manufacturing, shown and priced inside its unit
  const lines = allLines.filter((l) => !l.parent_line_id);
  const archOf = (l: Line) => allLines.find((x) => x.parent_line_id === l.id);

  const saveLine = (line: Line | null) => async (d: ItemDraft) => {
    const body = { location: d.location ?? "", model_id: d.model_id, opening_width_mm: d.opening_width_mm, opening_height_mm: d.opening_height_mm,
      total_height_mm: d.total_height_mm || null, top_model_id: d.top_model_id || null,
      params: d.params ?? {}, color_code: d.color_code || null, glass_material_code: d.glass_material_code || null,
      qty: Number(d.qty), manual_unit_price: d.manual_unit_price || null, price_per_m2: d.price_per_m2 || null, notes: d.notes ?? "" };
    const out = line
      ? await api.patch<Quote>(`/quotation-lines/${line.id}`, { ...body, version: line.version })
      : await api.post<Quote>(`/quotations/${id}/lines`, body);
    q.set(out);
    toast.ok("اتحفظ البند.");
  };
  const setStatus = (to: string) => run(async () => {
    q.set(await api.post<Quote>(`/quotations/${id}/status`, { version: quote.version, status: to }));
    toast.ok("اتغيرت حالة العرض.");
  });
  const recalc = () => run(async () => {
    q.set(await api.post<Quote>(`/quotations/${id}/recalculate`, { version: quote.version }));
    toast.ok("اتحسب العرض من جديد بآخر أسعار ومعادلات منشورة.");
  });
  const setPpm = (line: Line, value: string | null) => run(async () => {
    q.set(await api.patch<Quote>(`/quotation-lines/${line.id}`, { version: line.version, price_per_m2: value }));
  });
  const totalArea = sumMoney(lines.map((l) => mulMoney(l.billed_area_m2, l.qty)));
  const makeInvoice = () => run(async () => {
    const inv = await api.post<S<"InvoiceOut">>("/invoices", { quotation_id: id });
    go(`invoices/${inv.id}`);
  });

  return (
    <div className="col" style={{ gap: 14 }}>
      <Card>
        <div className="row wrap" style={{ gap: 18 }}>
          <div>
            <div className="muted small">العميل</div>
            <a style={{ cursor: "pointer", fontWeight: 700 }} onClick={() => go(`customers/${quote.customer_id}`)}><CustomerName id={quote.customer_id} /></a>
          </div>
          <div><div className="muted small">الحالة</div><Chip color={QUOTE_STATUS[quote.status]?.[1]}>{QUOTE_STATUS[quote.status]?.[0] ?? quote.status}</Chip></div>
          <div><div className="muted small">الفرع</div><BranchName id={quote.branch_id} /></div>
          <div><div className="muted small">التاريخ</div><span className="num">{date(quote.issue_date ?? quote.created_at)}</span></div>
          <div><div className="muted small">صالح لحد</div><span className="num">{date(quote.valid_until)}</span></div>
          <div className="end row wrap">
            <Btn icon="print" onClick={() => setPrinting(true)}>طباعة</Btn>
            {editable && <Btn icon="refresh" busy={busy} onClick={recalc}>إعادة حساب</Btn>}
            {s.can("quotes.write", quote.branch_id) && (NEXT[quote.status] ?? []).map((n) => (
              <Btn key={n.to} kind={n.kind} busy={busy} onClick={() => setStatus(n.to)}>{n.label}</Btn>
            ))}
            {quote.status === "accepted" && s.can("workorders.write", quote.branch_id) && <Btn kind="primary" icon="factory" onClick={() => setToWo(true)}>أمر تصنيع</Btn>}
            {quote.status === "accepted" && s.can("treasury.write", quote.branch_id) && <Btn icon="invoice" busy={busy} onClick={makeInvoice}>فاتورة</Btn>}
          </div>
        </div>
      </Card>

      <Card title={`البنود (${lines.length})`} flush actions={editable && <>
        {lines.length > 0 && <Btn small icon="calc" onClick={() => setAllPpm(true)}>سعر متر لكل البنود</Btn>}
        <Btn kind="primary" small icon="plus" onClick={() => setLineEdit("new")}>إضافة بند</Btn></>}>
        <Table rows={lines} empty="مفيش بنود. ضيف شباك أو باب." columns={[
          { key: "c", label: "رقم النموذج", render: (l) => <span className="code bold">{l.model_code}</span> },
          { key: "w", label: "العرض", num: true, render: (l) => <Len mm={l.opening_width_mm} /> },
          { key: "h", label: "الارتفاع", num: true, render: (l) => (
            <div><Len mm={l.opening_height_mm} />{l.total_height_mm && <div className="muted small">كلي <Len mm={l.total_height_mm} /></div>}</div>) },
          { key: "q", label: "العدد", num: true, render: (l) => <span className="num">{l.qty}</span> },
          { key: "a", label: "مساحة الفتحة", num: true, render: (l) => (
            <div><span className="num">{mulMoney(l.billed_area_m2, "1")}</span>
              {l.area_m2 !== l.billed_area_m2 && Number(l.area_m2) < Number(l.billed_area_m2) &&
                <div className="faint small" title="أقل من الحد الأدنى للمساحة، فبتتحسب بالحد الأدنى">الفعلية <span className="num">{mulMoney(l.area_m2, "1")}</span></div>}</div>) },
          { key: "ta", label: "المساحة الكلية", num: true, render: (l) => <b className="num">{mulMoney(l.billed_area_m2, l.qty)}</b> },
          { key: "m", label: "نوع وشكل النموذج", render: (l) => (
            <div className="row" style={{ gap: 8 }}>
              <MediaImg id={l.model_image_id} />
              <Drawing elements={(l.calc as any)?.drawing} w={(l.calc as any)?.inputs?.width_mm} h={(l.calc as any)?.inputs?.height_mm} maxW={70} maxH={52} />
              <div><b>{l.model_name}</b>{l.location && <span className="muted"> · {l.location}</span>}
                <div className="small"><ColorName code={l.color_code} /> {l.glass_material_code && <span className="muted">· {l.glass_material_code}</span>}</div>
                <ParamLabels modelId={l.model_id} values={l.params} />
                {archOf(l) && <ArchNote arch={archOf(l)!} />}</div>
            </div>) },
          { key: "p", label: "سعر المتر", width: 150, render: (l) => (
            <PpmCell line={l} editable={editable} busy={busy} onSave={(v) => setPpm(l, v)} />) },
          { key: "t", label: "التكلفة", num: true, render: (l) => <b><Money v={l.line_total} /></b> },
          ...(editable ? [{ key: "x", label: "", width: 80, render: (l: Line) => (
            <div className="row" style={{ gap: 4 }}>
              <Btn small icon="edit" onClick={() => setLineEdit(l)} />
              <Btn small icon="trash" kind="danger" onClick={() => setDel(l)} />
            </div>) }] : []),
        ]} />
      </Card>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 340px" }}>
        <Card title="الشروط والملاحظات" actions={editable && <Btn small icon="edit" onClick={() => setHeader(true)}>تعديل</Btn>}>
          <div style={{ whiteSpace: "pre-wrap" }}>{quote.terms || <span className="faint">—</span>}</div>
          {quote.notes && <div className="muted mt" style={{ whiteSpace: "pre-wrap" }}>{quote.notes}</div>}
        </Card>
        <Card title="الإجمالي">
          <div className="totals" style={{ width: "100%" }}>
            <div className="r"><span>إجمالي المساحة</span><span className="num">{totalArea} م²</span></div>
            <div className="r"><span>المجموع</span><Money v={sumMoney(lines.map((l) => l.line_total))} /></div>
            <div className="r"><span>الخصم</span><Money v={quote.discount_amount} /></div>
            <div className="r"><span>قبل الضريبة</span><Money v={quote.subtotal} /></div>
            <div className="r"><span>الضريبة <span className="num">{Number(quote.tax_pct)}%</span></span><Money v={quote.tax_amount} /></div>
            <div className="r big"><span>الإجمالي</span><Money v={quote.total} cur /></div>
            {s.can("pricelists.manage") && <div className="r small muted"><span>التكلفة التقديرية</span><Money v={quote.total_cost} /></div>}
          </div>
        </Card>
      </div>

      {lineEdit && <ItemForm title={lineEdit === "new" ? "بند جديد" : "تعديل البند"} withPrice onClose={() => setLineEdit(null)}
        initial={lineEdit === "new" ? undefined : { ...lineEdit, manual_unit_price: lineEdit.manual_unit_price, price_per_m2: lineEdit.price_per_m2,
          total_height_mm: lineEdit.total_height_mm, top_model_id: lineEdit.top_model_id }}
        onSave={saveLine(lineEdit === "new" ? null : lineEdit)} />}
      {del && <Confirm title="حذف البند" danger yes="حذف" busy={busy} onClose={() => setDel(null)} text={`هتحذف ${del.model_name} (${del.location || "بدون مكان"}).`}
        onYes={() => run(async () => { q.set(await api.del<Quote>(`/quotation-lines/${del.id}`)); setDel(null); })} />}
      {printing && <PrintPreview path={`/quotations/${id}/print`} title={`عرض سعر ${quote.number}`} onClose={() => setPrinting(false)} />}
      {allPpm && <AllPricePerM2 quote={quote} onClose={() => setAllPpm(false)} onSaved={(x) => q.set(x)} />}
      {toWo && <ToWorkOrder quote={quote} onClose={() => setToWo(false)} />}
      {header && <QuoteHeader quote={quote} onClose={() => setHeader(false)} onSaved={(x) => q.set(x)} />}
    </div>
  );
}

function ArchNote({ arch }: { arch: Line }) {
  return (
    <div className="row small" style={{ gap: 6, marginTop: 4 }}>
      <Chip color="violet">+ أرج</Chip>
      <span className="code">{arch.model_code}</span><span className="muted">{arch.model_name}</span>
      <Dim w={arch.opening_width_mm} h={arch.opening_height_mm} strong={false} />
      {(arch.calc as any)?.issues?.some((i: any) => i.level === "error") && <Chip color="red">فيه أخطاء</Chip>}
    </div>
  );
}

/** Price per m² typed for one line; the suggestion (cost + margin from the price list) under it. */
function PpmCell({ line, editable, busy, onSave }: { line: Line; editable: boolean; busy: boolean; onSave: (v: string | null) => void }) {
  const [v, setV] = useState(line.price_per_m2 ?? "");
  useEffect(() => { setV(line.price_per_m2 ?? ""); }, [line.version, line.price_per_m2]);
  const commit = () => {
    const next = v.trim() === "" ? null : v.trim();
    if ((next ?? "") !== (line.price_per_m2 ?? "")) onSave(next);
  };
  return (
    <div className="col" style={{ gap: 2 }}>
      {editable
        ? <NumIn value={v} onChange={setV} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
            placeholder={line.suggested_price_per_m2 ?? ""} disabled={busy} />
        : line.price_per_m2 ? <Money v={line.price_per_m2} /> : <span className="faint">—</span>}
      {line.suggested_price_per_m2 && (
        <span className="small muted">مقترح <a style={{ cursor: editable ? "pointer" : "default" }} onClick={() => editable && onSave(line.suggested_price_per_m2!)}>
          <Money v={line.suggested_price_per_m2} /></a></span>
      )}
      {line.price_per_m2 === null && line.manual_unit_price && <span className="small"><Chip color="amber">سعر وحدة يدوي</Chip></span>}
    </div>
  );
}

function AllPricePerM2({ quote, onClose, onSaved }: { quote: Quote; onClose: () => void; onSaved: (q: Quote) => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const pricing = useLoad(() => quote.survey_id ? api.get<S<"SurveyPricing">>(`/surveys/${quote.survey_id}/pricing`, { price_list_id: quote.price_list_id }).catch(() => null)
    : Promise.resolve(null), [quote.survey_id]);
  const [v, setV] = useState("");
  useEffect(() => { if (!v && pricing.data?.price_per_m2) setV(pricing.data.price_per_m2); }, [pricing.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const apply = (value: string | null) => run(async () => {
    onSaved(await api.post<Quote>(`/quotations/${quote.id}/price-per-m2`, { version: quote.version, price_per_m2: value }));
    toast.ok(value ? "اتطبق سعر المتر على كل البنود." : "رجعت أسعار البنود لقائمة الأسعار.");
    onClose();
  });
  return (
    <Modal title="سعر متر لكل البنود" onClose={onClose} footer={<>
      <Btn kind="primary" busy={busy} disabled={!v.trim()} onClick={() => apply(v.trim())}>تطبيق على كل البنود</Btn>
      <Btn busy={busy} onClick={() => apply(null)}>مسح سعر المتر من البنود</Btn>
      <Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col">
        <Field label="سعر المتر" hint="كل بند = مساحة الفتحة (بحد أدنى المساحة المحددة في الإعدادات) × سعر المتر × العدد">
          <NumIn value={v} onChange={setV} autoFocus /></Field>
        {pricing.data?.price_per_m2 && <div className="notice info small">سعر المتر المقترح للمعاينة: <b><Money v={pricing.data.price_per_m2} /></b></div>}
      </div>
    </Modal>
  );
}

function QuoteHeader({ quote, onClose, onSaved }: { quote: Quote; onClose: () => void; onSaved: (q: Quote) => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState({ discount_amount: quote.discount_amount, tax_pct: quote.tax_pct, valid_until: quote.valid_until ?? "",
    notes: quote.notes, terms: quote.terms, price_list_id: quote.price_list_id });
  const priceLists = useLoad(() => lookups.priceLists().catch(() => []), []);
  const save = () => run(async () => {
    onSaved(await api.patch<Quote>(`/quotations/${quote.id}`, { version: quote.version, ...d, valid_until: d.valid_until || null }));
    onClose();
  });
  return (
    <Modal title="بيانات العرض" size="wide" onClose={onClose} footer={<><Btn kind="primary" busy={busy} onClick={save}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2">
        <Field label="الخصم (مبلغ)"><NumIn value={d.discount_amount} onChange={(v) => setD((x) => ({ ...x, discount_amount: v }))} /></Field>
        <Field label="الضريبة %"><NumIn value={d.tax_pct} onChange={(v) => setD((x) => ({ ...x, tax_pct: v }))} /></Field>
        <Field label="صالح لحد"><input type="date" className="input" value={d.valid_until} onChange={(e) => setD((x) => ({ ...x, valid_until: e.target.value }))} /></Field>
        <Field label="قائمة الأسعار" hint="تغييرها بيعيد حساب الأسعار">
          <Select value={d.price_list_id} onChange={(v) => setD((x) => ({ ...x, price_list_id: v }))}
            options={(priceLists.data ?? []).map((p) => ({ value: p.id, label: p.name }))} /></Field>
        <Field label="الشروط" className="span-all"><TextArea value={d.terms} onChange={(v) => setD((x) => ({ ...x, terms: v }))} /></Field>
        <Field label="ملاحظات" className="span-all"><TextArea value={d.notes} onChange={(v) => setD((x) => ({ ...x, notes: v }))} rows={2} /></Field>
      </div>
    </Modal>
  );
}

function ToWorkOrder({ quote, onClose }: { quote: Quote; onClose: () => void }) {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const pct = s.company.settings?.deposit_pct ?? "0";
  const [due, setDue] = useState("");
  const [deposit, setDeposit] = useState("");
  return (
    <Modal title="أمر تصنيع من العرض" onClose={onClose} footer={<>
      <Btn kind="primary" busy={busy} onClick={() => run(async () => {
        const wo = await api.post<S<"WorkOrderOut">>("/work-orders/from-quotation", { quotation_id: quote.id, due_date: due || null,
          deposit_required: deposit || null });
        toast.ok(`اتعمل أمر التصنيع ${wo.number}.`);
        go(`work-orders/${wo.id}`);
      })}>إنشاء أمر التصنيع</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col">
        <div className="notice info">البنود بتتنقل بنفس نسخة المعادلات اللي اتحسب بيها العرض، ومش هتتغير لو المعادلات اتحدثت بعدين.</div>
        <Field label="تاريخ التسليم"><input type="date" className="input" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
        <Field label="العربون المطلوب" hint={`لو فاضي: ${Number(pct)}% من إجمالي العرض`}><NumIn value={deposit} onChange={setDeposit} /></Field>
      </div>
    </Modal>
  );
}
