import { useState } from "react";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad } from "../lib/hooks";
import { useDefaultBranch, useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, Confirm, Dim, ErrorBox, Field, Loading, Modal, Money, NumIn, PageHead, Pager, Qty, Select, SizeIn, Table, TextArea, TextIn } from "../components/ui";
import { BranchName, BranchSelect, ColorName, ColorSelect, CustomerName, CustomerPicker, GlassSelect, ModelSelect } from "../components/pickers";
import { Drawing, MediaImg, PrintPreview } from "../components/media";
import { INVOICE_STATUS } from "../lib/lookups";
import { go } from "../lib/router";
import { date } from "../lib/format";
import { PaymentForm } from "./Treasury";

type Invoice = S<"InvoiceOut">;
type Line = S<"app__modules__invoicing__router__LineOut">;

export default function Invoices({ route }: PageProps) {
  const id = route.path[1];
  if (id === "new") return <NewInvoice />;
  return id ? <InvoiceDetail id={id} /> : <InvoiceList />;
}

function InvoiceList() {
  useTitle("الفواتير");
  const s = useSession();
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const list = useLoad(() => api.get<S<"Page_InvoiceOut_">>("/invoices", { status: status || undefined, limit: 50, offset }), [status, offset]);
  const rows = (list.data?.items ?? []).filter((x) => !s.branchId || x.branch_id === s.branchId);
  return (
    <>
      <PageHead>
        <div style={{ width: 170 }}>
          <Select value={status} onChange={(v) => { setStatus(v); setOffset(0); }} placeholder="كل الحالات"
            options={Object.entries(INVOICE_STATUS).map(([value, [label]]) => ({ value, label }))} />
        </div>
        {s.can("treasury.write") && <Btn kind="primary" icon="plus" onClick={() => go("invoices/new")}>فاتورة جديدة</Btn>}
      </PageHead>
      {list.error && <ErrorBox text={list.error} onRetry={list.reload} />}
      <Card flush>
        <Table rows={rows} loading={list.loading} onRow={(i) => go(`invoices/${i.id}`)} columns={[
          { key: "n", label: "الرقم", render: (i) => <span className="num bold">{i.number ?? <span className="faint">مسودة</span>}</span> },
          { key: "c", label: "العميل", render: (i) => <CustomerName id={i.customer_id} /> },
          { key: "d", label: "التاريخ", render: (i) => <span className="num">{date(i.issue_date)}</span> },
          { key: "due", label: "الاستحقاق", render: (i) => <span className="num">{date(i.due_date)}</span> },
          { key: "s", label: "الحالة", render: (i) => <Chip color={INVOICE_STATUS[i.status]?.[1]}>{INVOICE_STATUS[i.status]?.[0] ?? i.status}</Chip> },
          { key: "t", label: "الإجمالي", num: true, render: (i) => <b><Money v={i.total} /></b> },
          { key: "p", label: "المدفوع", num: true, render: (i) => <Money v={i.paid_amount} /> },
          { key: "b", label: "الباقي", num: true, render: (i) => <span className={Number(i.balance) > 0 && i.status === "issued" ? "danger-text bold" : ""}><Money v={i.balance} /></span> },
        ]} empty="مفيش فواتير" />
        {list.data && <Pager total={list.data.total} limit={50} offset={offset} onChange={setOffset} />}
      </Card>
    </>
  );
}

function NewInvoice() {
  useTitle("فاتورة جديدة", <a onClick={() => go("invoices")} style={{ cursor: "pointer" }}>الفواتير</a>);
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const branch = useDefaultBranch("treasury.write");
  const [d, setD] = useState<{ customer_id: string | null; branch_id: string | null; source: string; ref: string }>(
    { customer_id: null, branch_id: branch, source: "manual", ref: "" });
  const wos = useLoad(() => d.customer_id ? api.get<S<"Page_WorkOrderOut_">>("/work-orders", { customer_id: d.customer_id, limit: 100 }).then((p) => p.items) : Promise.resolve([]), [d.customer_id]);
  const quotes = useLoad(() => d.customer_id ? api.get<S<"Page_QuotationOut_">>("/quotations", { customer_id: d.customer_id, status: "accepted", limit: 100 }).then((p) => p.items) : Promise.resolve([]), [d.customer_id]);
  const create = () => run(async () => {
    const body = d.source === "wo" ? { work_order_id: d.ref } : d.source === "quote" ? { quotation_id: d.ref }
      : { customer_id: d.customer_id, branch_id: d.branch_id, lines: [] };
    const inv = await api.post<Invoice>("/invoices", body);
    go(`invoices/${inv.id}`);
  });
  return (
    <Card title="بيانات الفاتورة">
      <div className="grid g2" style={{ maxWidth: 820 }}>
        <Field label="العميل" className="span-all"><CustomerPicker value={d.customer_id} onChange={(id) => setD((x) => ({ ...x, customer_id: id, ref: "" }))} /></Field>
        <Field label="من"><Select value={d.source} onChange={(v) => setD((x) => ({ ...x, source: v, ref: "" }))} options={[
          { value: "manual", label: "فاتورة يدوي" }, { value: "wo", label: "أمر تصنيع" }, { value: "quote", label: "عرض سعر مقبول" }]} /></Field>
        {d.source === "manual" && <Field label="الفرع"><BranchSelect value={d.branch_id} onChange={(v) => setD((x) => ({ ...x, branch_id: v }))} perm="treasury.write" /></Field>}
        {d.source === "wo" && <Field label="أمر التصنيع"><Select value={d.ref} onChange={(v) => setD((x) => ({ ...x, ref: v }))} placeholder="اختار…"
          options={(wos.data ?? []).filter((w) => w.stage !== "cancelled").map((w) => ({ value: w.id, label: w.number }))} /></Field>}
        {d.source === "quote" && <Field label="عرض السعر"><Select value={d.ref} onChange={(v) => setD((x) => ({ ...x, ref: v }))} placeholder="اختار…"
          options={(quotes.data ?? []).map((q) => ({ value: q.id, label: q.number }))} /></Field>}
      </div>
      <div className="notice info mt" style={{ maxWidth: 820 }}>من أمر تصنيع أو عرض سعر: البنود بتتنقل بصورها ورسمتها ومقاساتها وأسعارها. تقدر تضيف خدمات (تركيب، نقل) وخصومات قبل الإصدار.</div>
      <div className="row mt"><Btn kind="primary" busy={busy} onClick={create}
        disabled={!d.customer_id || (d.source === "manual" ? !d.branch_id : !d.ref)}>إنشاء الفاتورة</Btn></div>
    </Card>
  );
}

function InvoiceDetail({ id }: { id: string }) {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const inv = useLoad(() => api.get<Invoice>(`/invoices/${id}`), [id]);
  useTitle(inv.data ? (inv.data.number ? `فاتورة ${inv.data.number}` : "فاتورة (مسودة)") : "…",
    <a onClick={() => go("invoices")} style={{ cursor: "pointer" }}>الفواتير</a>, [inv.data?.number]);
  const [printing, setPrinting] = useState(false);
  const [line, setLine] = useState<Line | "new" | null>(null);
  const [del, setDel] = useState<Line | null>(null);
  const [header, setHeader] = useState(false);
  const [issue, setIssue] = useState(false);
  const [cancel, setCancel] = useState(false);
  const [reason, setReason] = useState("");
  const [paying, setPaying] = useState(false);
  if (inv.error) return <ErrorBox text={inv.error} onRetry={inv.reload} />;
  if (!inv.data) return <Loading />;
  const v = inv.data;
  const draft = v.status === "draft" && s.can("treasury.write", v.branch_id);
  const lines = v.lines ?? [];

  return (
    <div className="col" style={{ gap: 14 }}>
      <Card>
        <div className="row wrap" style={{ gap: 18 }}>
          <div><div className="muted small">العميل</div><a style={{ cursor: "pointer", fontWeight: 700 }} onClick={() => go(`customers/${v.customer_id}`)}><CustomerName id={v.customer_id} /></a></div>
          <div><div className="muted small">الحالة</div><Chip color={INVOICE_STATUS[v.status]?.[1]}>{INVOICE_STATUS[v.status]?.[0] ?? v.status}</Chip></div>
          <div><div className="muted small">الفرع</div><BranchName id={v.branch_id} /></div>
          <div><div className="muted small">التاريخ</div><span className="num">{date(v.issue_date)}</span></div>
          <div><div className="muted small">الاستحقاق</div><span className="num">{date(v.due_date)}</span></div>
          {v.work_order_id && <div><div className="muted small">أمر التصنيع</div><a style={{ cursor: "pointer" }} onClick={() => go(`work-orders/${v.work_order_id}`)}>فتح</a></div>}
          <div className="end row wrap">
            <Btn icon="print" onClick={() => setPrinting(true)}>طباعة</Btn>
            {draft && <Btn icon="edit" onClick={() => setHeader(true)}>الخصم والضريبة</Btn>}
            {draft && <Btn kind="primary" icon="check" disabled={!lines.length} onClick={() => setIssue(true)}>إصدار الفاتورة</Btn>}
            {v.status === "issued" && s.can("treasury.write", v.branch_id) && Number(v.balance) > 0 && <Btn kind="success" icon="cash" onClick={() => setPaying(true)}>تحصيل</Btn>}
            {v.status !== "cancelled" && s.can("treasury.write", v.branch_id) && <Btn kind="danger" icon="ban" onClick={() => { setReason(""); setCancel(true); }}>إلغاء</Btn>}
          </div>
        </div>
        {v.status === "cancelled" && <div className="notice err mt">الفاتورة ملغية: {v.cancel_reason}</div>}
      </Card>

      <Card title={`البنود (${lines.length})`} flush actions={draft && <Btn small kind="primary" icon="plus" onClick={() => setLine("new")}>إضافة بند</Btn>}>
        <Table rows={lines} empty="مفيش بنود" columns={[
          { key: "p", label: "#", width: 36, render: (l) => <span className="num muted">{l.position}</span> },
          { key: "img", label: "الشكل", width: 160, render: (l) => l.kind === "service" ? <Chip>خدمة</Chip> : (
            <div className="row" style={{ gap: 6 }}><MediaImg id={l.model_image_id} />
              <Drawing elements={l.drawing as any[]} w={l.width_mm} h={l.height_mm} maxW={80} maxH={56} /></div>) },
          { key: "m", label: "الصنف", render: (l) => (
            <div><b>{l.model_name || l.description}</b>{l.location && <span className="muted"> · {l.location}</span>}
              {l.model_name && l.description && l.description !== l.model_name && <div className="muted small">{l.description}</div>}
              {l.kind !== "service" && <div className="small"><ColorName code={l.color_code} />{l.glass_material_code && <span className="muted"> · {l.glass_material_code}</span>}</div>}
            </div>) },
          { key: "s", label: "المقاس (عرض × ارتفاع)", render: (l) => l.opening_width_mm ? (
            <div><Dim w={l.opening_width_mm} h={l.opening_height_mm} />
              {l.width_mm && <div className="muted small">تصنيع <Dim w={l.width_mm} h={l.height_mm} strong={false} /></div>}</div>) : <span className="faint">—</span> },
          { key: "q", label: "الكمية", num: true, render: (l) => <Qty v={l.qty} /> },
          { key: "u", label: "سعر الوحدة", num: true, render: (l) => <Money v={l.unit_price} /> },
          { key: "d", label: "خصم", num: true, render: (l) => Number(l.discount_pct) ? <span><span className="num">{Number(l.discount_pct)}%</span><div className="muted small"><Money v={l.discount_amount} /></div></span> : <span className="faint">—</span> },
          { key: "t", label: "الإجمالي", num: true, render: (l) => <b><Money v={l.line_total} /></b> },
          ...(draft ? [{ key: "a", label: "", width: 80, render: (l: Line) => (
            <div className="row" style={{ gap: 4 }}><Btn small icon="edit" onClick={() => setLine(l)} /><Btn small icon="trash" kind="danger" onClick={() => setDel(l)} /></div>) }] : []),
        ]} />
      </Card>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 340px" }}>
        <Card title="الشروط والملاحظات">
          <div style={{ whiteSpace: "pre-wrap" }}>{v.terms || <span className="faint">—</span>}</div>
          {v.notes && <div className="muted mt" style={{ whiteSpace: "pre-wrap" }}>{v.notes}</div>}
        </Card>
        <Card title="الإجمالي">
          <div className="totals" style={{ width: "100%" }}>
            <div className="r"><span>إجمالي البنود</span><Money v={v.lines_total} /></div>
            {Number(v.lines_discount) > 0 && <div className="r"><span>خصومات البنود</span><Money v={v.lines_discount} /></div>}
            <div className="r"><span>خصم الفاتورة</span><Money v={v.discount_amount} /></div>
            <div className="r"><span>الضريبة <span className="num">{Number(v.tax_pct)}%</span></span><Money v={v.tax_amount} /></div>
            <div className="r big"><span>الإجمالي</span><Money v={v.total} cur /></div>
            <div className="r"><span>المدفوع</span><Money v={v.paid_amount} /></div>
            <div className="r bold"><span>الباقي</span><Money v={v.balance} /></div>
          </div>
        </Card>
      </div>

      {printing && <PrintPreview path={`/invoices/${id}/print`} title={v.number ? `فاتورة ${v.number}` : "فاتورة مسودة"} onClose={() => setPrinting(false)} />}
      {line && <LineForm invoice={v} line={line === "new" ? null : line} onClose={() => setLine(null)} onSaved={(x) => inv.set(x)} />}
      {del && <Confirm title="حذف البند" danger yes="حذف" busy={busy} onClose={() => setDel(null)}
        onYes={() => run(async () => { inv.set(await api.del<Invoice>(`/invoice-lines/${del.id}`)); setDel(null); })} />}
      {header && <InvoiceHeader invoice={v} onClose={() => setHeader(false)} onSaved={(x) => inv.set(x)} />}
      {issue && <Confirm title="إصدار الفاتورة" yes="إصدار" busy={busy} onClose={() => setIssue(false)}
        text="الفاتورة هتاخد رقم متسلسل ومش هينفع تتعدل بعد كده (تقدر تلغيها بس)."
        onYes={() => run(async () => { inv.set(await api.post<Invoice>(`/invoices/${id}/issue`, { version: v.version })); setIssue(false); toast.ok("اتصدرت الفاتورة."); })} />}
      {cancel && <Confirm title="إلغاء الفاتورة" danger yes="إلغاء الفاتورة" busy={busy} onClose={() => setCancel(false)}
        text="الفاتورة مابتتمسحش. هتفضل موجودة كملغية بالسبب."
        onYes={() => run(async () => { if (!reason.trim()) throw new Error("اكتب سبب الإلغاء."); inv.set(await api.post<Invoice>(`/invoices/${id}/cancel`, { version: v.version, reason })); setCancel(false); })}>
        <Field label="السبب"><TextIn value={reason} onChange={setReason} autoFocus /></Field>
      </Confirm>}
      {paying && <PaymentForm onClose={() => setPaying(false)} onSaved={() => inv.reload()}
        initial={{ direction: "in", party_type: "customer", party_id: v.customer_id, invoice_id: v.id, amount: v.balance }} />}
    </div>
  );
}

function LineForm({ invoice, line, onClose, onSaved }: { invoice: Invoice; line: Line | null; onClose: () => void; onSaved: (i: Invoice) => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState({
    kind: line?.kind ?? "service", description: line?.description ?? "", location: line?.location ?? "", qty: line?.qty ?? "1",
    unit_price: line?.unit_price ?? "", discount_pct: line?.discount_pct ?? "0", model_id: line?.model_id ?? null as string | null,
    opening_width_mm: line?.opening_width_mm ?? null as string | null, opening_height_mm: line?.opening_height_mm ?? null as string | null,
    color_code: line?.color_code ?? null as string | null, glass_material_code: line?.glass_material_code ?? null as string | null,
  });
  const set = (k: keyof typeof d) => (v: any) => setD((x) => ({ ...x, [k]: v }));
  const save = () => run(async () => {
    const out = line
      ? await api.patch<Invoice>(`/invoice-lines/${line.id}`, { version: line.version, description: d.description, location: d.location,
        qty: d.qty, unit_price: d.unit_price, discount_pct: d.discount_pct || "0" })
      : await api.post<Invoice>(`/invoices/${invoice.id}/lines`, d.kind === "service"
        ? { kind: "service", description: d.description, qty: d.qty, unit_price: d.unit_price, discount_pct: d.discount_pct || "0" }
        : { ...d, discount_pct: d.discount_pct || "0" });
    onSaved(out);
    onClose();
  });
  const item = d.kind !== "service";
  return (
    <Modal title={line ? "تعديل البند" : "بند جديد"} size="wide" onClose={onClose} footer={<>
      <Btn kind="primary" busy={busy} disabled={!d.unit_price || !(Number(d.qty) > 0) || (!item && !d.description)} onClick={save}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2">
        {!line && <Field label="النوع" className="span-all"><Select value={d.kind} onChange={set("kind")} options={[
          { value: "service", label: "خدمة (تركيب، نقل، صيانة…)" }, { value: "item", label: "شباك / باب" }]} /></Field>}
        {item && !line && <Field label="النموذج" className="span-all"><ModelSelect value={d.model_id} onChange={(v) => set("model_id")(v || null)} /></Field>}
        {item && !line && <Field label="مقاس الفتحة (العرض × الارتفاع)" className="span-all">
          <SizeIn w={d.opening_width_mm} h={d.opening_height_mm} onChange={(w, h) => setD((x) => ({ ...x, opening_width_mm: w, opening_height_mm: h }))} /></Field>}
        {item && !line && <Field label="اللون"><ColorSelect value={d.color_code} onChange={set("color_code")} /></Field>}
        {item && !line && <Field label="الزجاج"><GlassSelect value={d.glass_material_code} onChange={set("glass_material_code")} /></Field>}
        <Field label="البيان" className={item ? "" : "span-all"}><TextIn value={d.description} onChange={set("description")} autoFocus /></Field>
        {item && <Field label="المكان"><TextIn value={d.location} onChange={set("location")} /></Field>}
        <Field label="الكمية"><NumIn value={d.qty} onChange={set("qty")} /></Field>
        <Field label="سعر الوحدة"><NumIn value={d.unit_price} onChange={set("unit_price")} /></Field>
        <Field label="خصم %"><NumIn value={d.discount_pct} onChange={set("discount_pct")} unit="%" /></Field>
      </div>
    </Modal>
  );
}

function InvoiceHeader({ invoice, onClose, onSaved }: { invoice: Invoice; onClose: () => void; onSaved: (i: Invoice) => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState({ discount_amount: invoice.discount_amount, tax_pct: invoice.tax_pct, due_date: invoice.due_date ?? "",
    notes: invoice.notes, terms: invoice.terms });
  return (
    <Modal title="الخصم والضريبة والشروط" size="wide" onClose={onClose} footer={<><Btn kind="primary" busy={busy} onClick={() => run(async () => {
      onSaved(await api.patch<Invoice>(`/invoices/${invoice.id}`, { version: invoice.version, ...d, due_date: d.due_date || null }));
      onClose();
    })}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g3">
        <Field label="خصم على الفاتورة (مبلغ)"><NumIn value={d.discount_amount} onChange={(v) => setD((x) => ({ ...x, discount_amount: v }))} /></Field>
        <Field label="الضريبة %"><NumIn value={d.tax_pct} onChange={(v) => setD((x) => ({ ...x, tax_pct: v }))} unit="%" /></Field>
        <Field label="تاريخ الاستحقاق"><input type="date" className="input" value={d.due_date} onChange={(e) => setD((x) => ({ ...x, due_date: e.target.value }))} /></Field>
        <Field label="الشروط" className="span-all"><TextArea value={d.terms} onChange={(v) => setD((x) => ({ ...x, terms: v }))} /></Field>
        <Field label="ملاحظات" className="span-all"><TextArea value={d.notes} onChange={(v) => setD((x) => ({ ...x, notes: v }))} rows={2} /></Field>
      </div>
    </Modal>
  );
}
