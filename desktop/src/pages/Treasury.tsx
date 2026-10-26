import { useState } from "react";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad } from "../lib/hooks";
import { useDefaultBranch, useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, Confirm, ErrorBox, Field, Modal, Money, NumIn, PageHead, Pager, Select, Table, TextIn } from "../components/ui";
import { BranchName, BranchSelect, CashboxSelect, CustomerName, CustomerPicker, SupplierSelect } from "../components/pickers";
import { METHODS, invalidate, lookups } from "../lib/lookups";
import { DeleteBtn } from "../components/actions";
import { dateTime } from "../lib/format";

type Tx = S<"TxOut">;

export default function Treasury(_: PageProps) {
  useTitle("الخزينة");
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [box, setBox] = useState("");
  const [offset, setOffset] = useState(0);
  const [form, setForm] = useState<"in" | "out" | null>(null);
  const [newBox, setNewBox] = useState(false);
  const [reverse, setReverse] = useState<Tx | null>(null);
  const [note, setNote] = useState("");
  const boxes = useLoad(() => api.get<S<"CashboxOut">[]>("/cashboxes"), []);
  const txs = useLoad(() => api.get<S<"Page_TxOut_">>("/cash-transactions", { cashbox_id: box || undefined, limit: 50, offset }), [box, offset]);
  const reload = () => { invalidate("cashboxes"); boxes.reload(); txs.reload(); };
  const boxName = (id: string) => boxes.data?.find((b) => b.id === id)?.name ?? "";
  const write = s.can("treasury.create");
  const reverser = s.can("treasury.delete");

  return (
    <div className="col" style={{ gap: 14 }}>
      <PageHead>
        {write && <Btn kind="success" icon="plus" onClick={() => setForm("in")}>قبض</Btn>}
        {write && <Btn kind="danger" icon="send" onClick={() => setForm("out")}>صرف</Btn>}
        {s.can("treasury.create") && <Btn icon="plus" onClick={() => setNewBox(true)}>خزينة جديدة</Btn>}
      </PageHead>
      {boxes.error && <ErrorBox text={boxes.error} onRetry={boxes.reload} />}
      <div className="grid g4">
        {(boxes.data ?? []).map((b) => (
          <div key={b.id} style={{ position: "relative" }}>
            <button className="card kpi" style={{ width: "100%", textAlign: "start", cursor: "pointer", outline: box === b.id ? "2px solid var(--primary)" : undefined }}
              onClick={() => { setBox(box === b.id ? "" : b.id); setOffset(0); }}>
              <div className="label">{b.name} · <BranchName id={b.branch_id} /></div>
              <div className="value"><Money v={b.balance} /></div>
            </button>
            {s.can("treasury.delete", b.branch_id) && (
              <div className="no-print" style={{ position: "absolute", top: 8, left: 8 }}>
                <DeleteBtn label="" path={`/cashboxes/${b.id}`} what={`الخزينة ${b.name}`} onDone={() => { if (box === b.id) setBox(""); reload(); }}
                  note="الخزينة هتتمسح بس لو عمرها ما كان عليها حركات. لو عليها حركات هتتوقف وتختفي، والحركات القديمة بتفضل زي ما هي." />
              </div>
            )}
          </div>
        ))}
      </div>
      <Card title={box ? `حركات ${boxName(box)}` : "كل الحركات"} flush>
        <Table rows={txs.data?.items} loading={txs.loading} columns={[
          { key: "n", label: "الرقم", render: (t) => <span className="num">{t.number}</span> },
          { key: "at", label: "الوقت", render: (t) => <span className="num">{dateTime(t.at)}</span> },
          { key: "b", label: "الخزينة", render: (t) => boxName(t.cashbox_id) },
          { key: "d", label: "النوع", render: (t) => t.reverses_id ? <Chip color="amber">عكس حركة</Chip>
            : t.direction === "in" ? <Chip color="green">قبض</Chip> : <Chip color="red">صرف</Chip> },
          { key: "p", label: "الطرف", render: (t) => t.party_type === "customer" ? <CustomerName id={t.party_id} />
            : t.party_type === "supplier" ? <SupplierName id={t.party_id} /> : <span className="muted">أخرى</span> },
          { key: "m", label: "الطريقة", render: (t) => METHODS[t.method] ?? t.method },
          { key: "r", label: "بيان", render: (t) => <span className="muted small">{[t.reference, t.note].filter(Boolean).join(" · ")}</span> },
          { key: "a", label: "المبلغ", num: true, render: (t) => <b className={t.direction === "in" ? "success-text" : "danger-text"}>
            {t.direction === "in" ? "+" : "−"}<Money v={t.amount} /></b> },
          ...(reverser ? [{ key: "x", label: "", width: 70, render: (t: Tx) => !t.reversed && !t.reverses_id
            ? <Btn small kind="danger" onClick={() => { setReverse(t); setNote(""); }}>عكس</Btn> : t.reversed ? <Chip>معكوسة</Chip> : null }] : []),
        ]} empty="مفيش حركات" />
        {txs.data && <Pager total={txs.data.total} limit={50} offset={offset} onChange={setOffset} />}
      </Card>
      {form && <PaymentForm initial={{ direction: form, party_type: form === "in" ? "customer" : "supplier", cashbox_id: box || undefined }}
        onClose={() => setForm(null)} onSaved={reload} />}
      {newBox && <NewCashbox onClose={() => setNewBox(false)} onSaved={reload} />}
      {reverse && (
        <Confirm title="عكس الحركة" danger yes="عكس الحركة" busy={busy} onClose={() => setReverse(null)}
          text={<>الحركات مابتتمسحش. هتتعمل حركة عكسية بنفس المبلغ (<Money v={reverse.amount} />).</>}
          onYes={() => run(async () => { await api.post(`/cash-transactions/${reverse.id}/reverse`, { note }); setReverse(null); reload(); toast.ok("اتعكست الحركة."); })}>
          <Field label="السبب"><TextIn value={note} onChange={setNote} /></Field>
        </Confirm>
      )}
    </div>
  );
}

function SupplierName({ id }: { id: string | null | undefined }) {
  const list = useLoad(() => lookups.suppliers().catch(() => []), []);
  return <>{list.data?.find((x) => x.id === id)?.name ?? "…"}</>;
}

function NewCashbox({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const branch = useDefaultBranch("treasury.create");
  const [d, setD] = useState({ code: "", name: "", branch_id: branch ?? "" });
  return (
    <Modal title="خزينة جديدة" onClose={onClose} footer={<><Btn kind="primary" busy={busy} disabled={!d.code || !d.name || !d.branch_id}
      onClick={() => run(async () => { await api.post("/cashboxes", d); onSaved(); onClose(); })}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col">
        <Field label="الكود"><TextIn value={d.code} onChange={(v) => setD((x) => ({ ...x, code: v }))} code /></Field>
        <Field label="الاسم"><TextIn value={d.name} onChange={(v) => setD((x) => ({ ...x, name: v }))} /></Field>
        <Field label="الفرع"><BranchSelect value={d.branch_id} onChange={(v) => setD((x) => ({ ...x, branch_id: v }))} perm="treasury.create" /></Field>
      </div>
    </Modal>
  );
}

type TxDraft = Partial<S<"TxIn">>;

/** Receipt (قبض) or payment (صرف), optionally tied to a work order, an invoice or a purchase order. */
export function PaymentForm({ initial, onClose, onSaved }: { initial: TxDraft; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState<TxDraft>({ method: "cash", amount: "", reference: "", note: "", ...initial });
  const set = <K extends keyof TxDraft>(k: K, v: TxDraft[K]) => setD((x) => ({ ...x, [k]: v }));
  const customer = d.party_type === "customer" ? d.party_id : null;
  const supplier = d.party_type === "supplier" ? d.party_id : null;
  const wos = useLoad(() => customer ? api.get<S<"Page_WorkOrderOut_">>("/work-orders", { customer_id: customer, limit: 100 }).then((p) => p.items) : Promise.resolve([]), [customer]);
  const invs = useLoad(() => customer ? api.get<S<"Page_InvoiceOut_">>("/invoices", { customer_id: customer, status: "issued", limit: 100 }).then((p) => p.items) : Promise.resolve([]), [customer]);
  const pos = useLoad(() => supplier ? api.get<S<"Page_POOut_">>("/purchase-orders", { supplier_id: supplier, limit: 100 }).then((p) => p.items) : Promise.resolve([]), [supplier]);
  const save = () => run(async () => {
    await api.post("/cash-transactions", { ...d, party_id: d.party_type === "other" ? null : d.party_id,
      work_order_id: d.invoice_id ? null : d.work_order_id || null, invoice_id: d.invoice_id || null, purchase_order_id: d.purchase_order_id || null });
    toast.ok(d.direction === "in" ? "اتسجل القبض." : "اتسجل الصرف.");
    onSaved();
    onClose();
  });
  const valid = d.cashbox_id && d.amount && Number(d.amount) > 0 && (d.party_type === "other" || d.party_id);
  return (
    <Modal title={d.direction === "in" ? "قبض نقدية" : "صرف نقدية"} size="wide" onClose={onClose}
      footer={<><Btn kind={d.direction === "in" ? "success" : "solid-danger"} busy={busy} disabled={!valid} onClick={save}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2">
        <Field label="النوع"><Select value={d.direction} onChange={(v) => set("direction", v)} options={[{ value: "in", label: "قبض" }, { value: "out", label: "صرف" }]} /></Field>
        <Field label="الخزينة"><CashboxSelect value={d.cashbox_id} onChange={(v) => set("cashbox_id", v)} /></Field>
        <Field label="المبلغ"><NumIn value={d.amount as string} onChange={(v) => set("amount", v)} autoFocus /></Field>
        <Field label="الطريقة"><Select value={d.method} onChange={(v) => set("method", v)} options={Object.entries(METHODS).map(([value, label]) => ({ value, label }))} /></Field>
        <Field label="الطرف"><Select value={d.party_type} onChange={(v) => setD((x) => ({ ...x, party_type: v, party_id: null, work_order_id: null, invoice_id: null, purchase_order_id: null }))}
          options={[{ value: "customer", label: "عميل" }, { value: "supplier", label: "مورد" }, { value: "other", label: "أخرى (مصروفات…)" }]} /></Field>
        {d.party_type === "customer" && <Field label="العميل"><CustomerPicker value={d.party_id} onChange={(id) => setD((x) => ({ ...x, party_id: id, work_order_id: null, invoice_id: null }))} /></Field>}
        {d.party_type === "supplier" && <Field label="المورد"><SupplierSelect value={d.party_id} onChange={(id) => setD((x) => ({ ...x, party_id: id, purchase_order_id: null }))} /></Field>}
        {d.party_type === "other" && <div />}
        {customer && <Field label="فاتورة"><Select value={d.invoice_id ?? ""} onChange={(v) => set("invoice_id", v || null)} placeholder="من غير فاتورة"
          options={(invs.data ?? []).map((i) => ({ value: i.id, label: `${i.number} · الباقي ${Number(i.balance).toLocaleString("en-US")}` }))} /></Field>}
        {customer && !d.invoice_id && <Field label="أمر تصنيع"><Select value={d.work_order_id ?? ""} onChange={(v) => set("work_order_id", v || null)} placeholder="من غير أمر"
          options={(wos.data ?? []).filter((w) => w.stage !== "cancelled").map((w) => ({ value: w.id, label: w.number }))} /></Field>}
        {supplier && <Field label="أمر شراء"><Select value={d.purchase_order_id ?? ""} onChange={(v) => set("purchase_order_id", v || null)} placeholder="من غير أمر"
          options={(pos.data ?? []).map((p) => ({ value: p.id, label: p.number }))} /></Field>}
        <Field label="مرجع (رقم شيك، تحويل…)"><TextIn value={d.reference} onChange={(v) => set("reference", v)} /></Field>
        <Field label="بيان" className="span-all"><TextIn value={d.note} onChange={(v) => set("note", v)} /></Field>
      </div>
    </Modal>
  );
}

