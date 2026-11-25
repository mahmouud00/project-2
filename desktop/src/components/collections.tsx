// التحصيل من الفاتورة: the salesperson records money on an issued invoice; the accounts confirm it into a cashbox
// (then it counts) or refuse it with a reason. The bar over the invoice shows how much of it is collected.
import { useState } from "react";
import { api, type S } from "../api/client";
import { useAction, useLoad } from "../lib/hooks";
import { METHODS } from "../lib/lookups";
import { go } from "../lib/router";
import { dateTime } from "../lib/format";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { CashboxSelect, CustomerName } from "./pickers";
import { Btn, Card, Chip, Field, Modal, Money, NumIn, Select, Table, TextIn } from "./ui";

type Invoice = S<"InvoiceOut">;
type Collection = S<"CollectionOut">;

const STATUS: Record<string, [string, "amber" | "green" | "red"]> = {
  pending: ["مستني الحسابات", "amber"], confirmed: ["اتأكد", "green"], rejected: ["مرفوض", "red"],
};
const METHOD_OPTIONS = Object.entries(METHODS).map(([value, label]) => ({ value, label }));

/** The collection indicator over the invoice: confirmed / total, what waits for the accounts, and the deposit. */
export function CollectionBar({ invoice }: { invoice: Invoice }) {
  const pct = Math.min(100, Number(invoice.collected_pct));
  const pendingPct = Math.min(100 - pct, Number(invoice.total) ? Number(invoice.pending_amount) * 100 / Number(invoice.total) : 0);
  const depositPct = Number(invoice.total) ? Number(invoice.deposit_amount) * 100 / Number(invoice.total) : 0;
  return (
    <div className="col" style={{ gap: 6 }}>
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <b>نسبة التحصيل <span className="num">{pct}%</span></b>
        <span className="small muted">اتحصّل <Money v={invoice.paid_amount} /> من <Money v={invoice.total} />
          {Number(invoice.pending_amount) > 0 && <> · مستني الحسابات <Money v={invoice.pending_amount} /></>}
          {" · "}الباقي <Money v={invoice.balance} /></span>
      </div>
      <div style={{ position: "relative", height: 14, borderRadius: 7, background: "var(--line)", overflow: "hidden" }}>
        <span style={{ position: "absolute", insetInlineStart: 0, top: 0, bottom: 0, width: `${pct}%`, background: "var(--green, #16A34A)" }} />
        <span style={{ position: "absolute", insetInlineStart: `${pct}%`, top: 0, bottom: 0, width: `${pendingPct}%`, background: "var(--amber, #F59E0B)", opacity: .7 }} />
        {depositPct > 0 && depositPct < 100 && <span title="العربون" style={{ position: "absolute", insetInlineStart: `${depositPct}%`, top: 0, bottom: 0, width: 2, background: "var(--text, #111)" }} />}
      </div>
      <div className="small muted">العربون المطلوب قبل أمر التصنيع <Money v={invoice.deposit_amount} /> {Number(invoice.paid_amount) >= Number(invoice.deposit_amount)
        ? <Chip color="green">اتحصّل</Chip> : <Chip color="amber">لسه</Chip>}</div>
    </div>
  );
}

export function CollectForm({ invoice, onClose, onSaved }: { invoice: Invoice; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const left = Math.max(0, Number(invoice.balance) - Number(invoice.pending_amount));
  const firstDeposit = Number(invoice.paid_amount) + Number(invoice.pending_amount) < Number(invoice.deposit_amount);
  const [d, setD] = useState({ amount: String(firstDeposit ? Number(invoice.deposit_amount) - Number(invoice.paid_amount) - Number(invoice.pending_amount) : left),
    method: "cash", reference: "", note: firstDeposit ? "عربون" : "" });
  const save = () => run(async () => {
    await api.post(`/invoices/${invoice.id}/collections`, d);
    toast.ok("اتسجل التحصيل، ومستني تأكيد الحسابات.");
    onSaved();
    onClose();
  });
  return (
    <Modal title="تسجيل تحصيل" onClose={onClose}
      footer={<><Btn kind="primary" busy={busy} disabled={!(Number(d.amount) > 0)} onClick={save}>تسجيل</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2">
        <Field label="المبلغ" hint={<>الباقي <Money v={String(left)} /></>}><NumIn value={d.amount} onChange={(v) => setD((x) => ({ ...x, amount: v }))} autoFocus /></Field>
        <Field label="طريقة الدفع"><Select value={d.method} onChange={(v) => setD((x) => ({ ...x, method: v }))} options={METHOD_OPTIONS} /></Field>
        <Field label="رقم التحويل / الشيك"><TextIn value={d.reference} onChange={(v) => setD((x) => ({ ...x, reference: v }))} code /></Field>
        <Field label="ملاحظة"><TextIn value={d.note} onChange={(v) => setD((x) => ({ ...x, note: v }))} /></Field>
      </div>
      <div className="notice info small mt">التحصيل مش بيتحسب ولا بيدخل الخزينة غير لما الحسابات تأكده.</div>
    </Modal>
  );
}

/** The accounts decide: confirm into a cashbox, or refuse with the reason. */
function Decide({ c, onClose, onSaved }: { c: Collection; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [box, setBox] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const confirm = () => run(async () => {
    await api.post(`/collections/${c.id}/confirm`, { version: c.version, cashbox_id: box });
    toast.ok("اتأكد التحصيل ودخل الخزينة.");
    onSaved(); onClose();
  });
  const reject = () => run(async () => {
    if (reason.trim().length < 3) throw new Error("اكتب سبب الرفض.");
    await api.post(`/collections/${c.id}/reject`, { version: c.version, reason });
    toast.ok("اترفض التحصيل.");
    onSaved(); onClose();
  });
  return (
    <Modal title={`تحصيل ${c.number}: ${c.amount}`} onClose={onClose} footer={<>
      <Btn kind="success" busy={busy} disabled={!box} onClick={confirm}>تأكيد ودخول الخزينة</Btn>
      <Btn kind="danger" busy={busy} onClick={reject}>رفض</Btn>
      <Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col">
        <div className="small">{METHODS[c.method] ?? c.method}{c.reference && <> · <span className="num">{c.reference}</span></>}{c.note && <> · {c.note}</>}</div>
        <Field label="الخزينة"><CashboxSelect value={box} onChange={setBox} /></Field>
        <Field label="سبب الرفض (لو هترفض)"><TextIn value={reason} onChange={setReason} /></Field>
      </div>
    </Modal>
  );
}

/** The invoice's collections (with the accounts' buttons for them). */
export function InvoiceCollections({ invoice, onChanged }: { invoice: Invoice; onChanged: () => void }) {
  const s = useSession();
  const list = useLoad(() => api.get<Collection[]>(`/invoices/${invoice.id}/collections`), [invoice.id, invoice.version, invoice.paid_amount, invoice.pending_amount]);
  const [deciding, setDeciding] = useState<Collection | null>(null);
  const can = s.can("collections.confirm", invoice.branch_id);
  return (
    <Card title="التحصيلات" flush>
      <Table rows={list.data ?? []} empty="مفيش تحصيلات لسه" columns={[
        { key: "n", label: "رقم", render: (c) => <span className="code">{c.number}</span> },
        { key: "d", label: "التاريخ", render: (c) => <span className="num small">{dateTime(c.created_at)}</span> },
        { key: "a", label: "المبلغ", num: true, render: (c) => <b><Money v={c.amount} /></b> },
        { key: "m", label: "الطريقة", render: (c) => <span>{METHODS[c.method] ?? c.method}{c.reference && <span className="muted small"> · {c.reference}</span>}</span> },
        { key: "s", label: "الحالة", render: (c) => <span><Chip color={STATUS[c.status]?.[1]}>{STATUS[c.status]?.[0] ?? c.status}</Chip>
          {c.reject_reason && <div className="small danger-text">{c.reject_reason}</div>}</span> },
        ...(can ? [{ key: "x", label: "", render: (c: Collection) => c.status === "pending" &&
          <Btn small kind="primary" onClick={() => setDeciding(c)}>تأكيد / رفض</Btn> }] : []),
      ]} />
      {deciding && <Decide c={deciding} onClose={() => setDeciding(null)} onSaved={() => { list.reload(); onChanged(); }} />}
    </Card>
  );
}

/** The accounts' list: every collection waiting for them. */
export function PendingCollections() {
  const list = useLoad(() => api.get<Collection[]>("/collections", { status: "pending" }), []);
  const [deciding, setDeciding] = useState<Collection | null>(null);
  return (
    <Card title={`تحصيلات مستنية تأكيد (${list.data?.length ?? 0})`} flush>
      <Table rows={list.data ?? []} empty="مفيش تحصيلات مستنية" columns={[
        { key: "n", label: "رقم", render: (c) => <span className="code">{c.number}</span> },
        { key: "c", label: "العميل", render: (c) => <CustomerName id={c.customer_id} /> },
        { key: "i", label: "الفاتورة", render: (c) => <a style={{ cursor: "pointer" }} onClick={() => go(`invoices/${c.invoice_id}`)}>{c.invoice_number}</a> },
        { key: "a", label: "المبلغ", num: true, render: (c) => <b><Money v={c.amount} /></b> },
        { key: "m", label: "الطريقة", render: (c) => <span>{METHODS[c.method] ?? c.method}{c.reference && <span className="muted small"> · {c.reference}</span>}</span> },
        { key: "d", label: "التاريخ", render: (c) => <span className="num small">{dateTime(c.created_at)}</span> },
        { key: "x", label: "", render: (c) => <Btn small kind="primary" onClick={() => setDeciding(c)}>تأكيد / رفض</Btn> },
      ]} />
      {deciding && <Decide c={deciding} onClose={() => setDeciding(null)} onSaved={() => list.reload()} />}
    </Card>
  );
}
