import { useState } from "react";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad, when } from "../lib/hooks";
import { useDefaultBranch, useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, ErrorBox, Field, Loading, Modal, Money, NumIn, PageHead, Pager, Qty, Table, Tabs, TextArea, TextIn, Check } from "../components/ui";
import { BranchName, BranchSelect, CustomerName, SupplierSelect, WarehouseSelect } from "../components/pickers";
import { PO_STATUS, invalidate, lookups } from "../lib/lookups";
import { go, setQuery } from "../lib/router";
import { date, mulMoney, sumMoney } from "../lib/format";
import { SkuIn } from "./Inventory";
import { PaymentForm } from "./Treasury";
import { DeleteBtn } from "../components/actions";

type PO = S<"POOut">;

export default function Purchasing({ route }: PageProps) {
  const id = route.path[1];
  if (id === "new") return <NewPO />;
  if (id) return <PODetail id={id} />;
  return <PurchasingHome tab={route.query.tab ?? "orders"} />;
}

function PurchasingHome({ tab }: { tab: string }) {
  useTitle("المشتريات");
  return (
    <Card flush>
      <Tabs value={tab} onChange={(t) => setQuery({ tab: t })} tabs={[{ id: "orders", label: "أوامر الشراء" }, { id: "suppliers", label: "الموردين" }]} />
      <div className="card-b">{tab === "orders" ? <POList /> : <Suppliers />}</div>
    </Card>
  );
}

function POList() {
  const s = useSession();
  const [offset, setOffset] = useState(0);
  const list = useLoad(() => api.get<S<"Page_POOut_">>("/purchase-orders", { limit: 50, offset }), [offset]);
  const sup = useLoad(() => lookups.suppliers(), []);
  return (
    <div className="col">
      <PageHead>{s.can("purchasing.create") && <Btn kind="primary" icon="plus" onClick={() => go("purchasing/new")}>أمر شراء جديد</Btn>}</PageHead>
      {list.error && <ErrorBox text={list.error} onRetry={list.reload} />}
      <Table rows={list.data?.items} loading={list.loading} onRow={(p) => go(`purchasing/${p.id}`)} columns={[
        { key: "n", label: "الرقم", render: (p) => <span className="num bold">{p.number}</span> },
        { key: "s", label: "المورد", render: (p) => sup.data?.find((x) => x.id === p.supplier_id)?.name ?? "" },
        { key: "cu", label: "للعميل", render: (p) => p.customer_id ? <CustomerName id={p.customer_id} /> : <span className="faint">مخزن</span> },
        { key: "b", label: "الفرع", render: (p) => <BranchName id={p.branch_id} /> },
        { key: "d", label: "التاريخ", render: (p) => <span className="num">{date(p.order_date)}</span> },
        { key: "st", label: "الحالة", render: (p) => <Chip color={PO_STATUS[p.status]?.[1]}>{PO_STATUS[p.status]?.[0] ?? p.status}</Chip> },
        { key: "t", label: "الإجمالي", num: true, render: (p) => <Money v={p.total} /> },
        { key: "r", label: "المستلم", num: true, render: (p) => <Money v={p.received_value} /> },
        { key: "pd", label: "المدفوع", num: true, render: (p) => <Money v={p.paid_amount} /> },
        { key: "del", label: "", width: 80, render: (p) => p.status === "draft" && s.can("purchasing.delete", p.branch_id) &&
          <DeleteBtn path={`/purchase-orders/${p.id}`} what={`أمر الشراء ${p.number}`} onDone={list.reload} /> },
      ]} empty="مفيش أوامر شراء" />
      {list.data && <Pager total={list.data.total} limit={50} offset={offset} onChange={setOffset} />}
    </div>
  );
}

type Line = { sku: string; qty: string; unit_cost: string };

function NewPO() {
  useTitle("أمر شراء جديد", <a onClick={() => go("purchasing")} style={{ cursor: "pointer" }}>المشتريات</a>);
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const branch = useDefaultBranch("purchasing.create");
  const [d, setD] = useState({ supplier_id: "", branch_id: branch ?? "", warehouse_id: "", order_date: "", notes: "" });
  const [lines, setLines] = useState<Line[]>([{ sku: "", qty: "", unit_cost: "" }]);
  const setLine = (i: number, k: keyof Line, v: string) => setLines((x) => x.map((l, j) => j === i ? { ...l, [k]: v } : l));
  const total = sumMoney(lines.map((l) => mulMoney(l.qty, l.unit_cost)));
  return (
    <Card title="أمر الشراء">
      <div className="grid g4 mb">
        <Field label="المورد"><SupplierSelect value={d.supplier_id} onChange={(v) => setD((x) => ({ ...x, supplier_id: v }))} /></Field>
        <Field label="الفرع"><BranchSelect value={d.branch_id} onChange={(v) => setD((x) => ({ ...x, branch_id: v, warehouse_id: "" }))} perm="purchasing.create" /></Field>
        <Field label="المخزن"><WarehouseSelect value={d.warehouse_id} branchId={d.branch_id} onChange={(v) => setD((x) => ({ ...x, warehouse_id: v }))} /></Field>
        <Field label="التاريخ"><input type="date" className="input" value={d.order_date} onChange={(e) => setD((x) => ({ ...x, order_date: e.target.value }))} /></Field>
      </div>
      <table className="editor-table">
        <thead><tr><th>الكود</th><th>الكمية</th><th>تكلفة الوحدة</th><th className="n">الإجمالي</th><th /></tr></thead>
        <tbody>{lines.map((l, i) => (
          <tr key={i}>
            <td style={{ width: "40%" }}><SkuIn value={l.sku} onChange={(v) => setLine(i, "sku", v)} /></td>
            <td><NumIn value={l.qty} onChange={(v) => setLine(i, "qty", v)} /></td>
            <td><NumIn value={l.unit_cost} onChange={(v) => setLine(i, "unit_cost", v)} /></td>
            <td className="n"><Money v={mulMoney(l.qty, l.unit_cost)} /></td>
            <td><Btn small icon="trash" kind="danger" disabled={lines.length === 1} onClick={() => setLines((x) => x.filter((_, j) => j !== i))} /></td>
          </tr>))}</tbody>
      </table>
      <div className="row mt">
        <Btn small icon="plus" onClick={() => setLines((x) => [...x, { sku: "", qty: "", unit_cost: "" }])}>سطر</Btn>
        <span className="end">الإجمالي: <b><Money v={total} cur /></b></span>
      </div>
      <Field label="ملاحظات" className="mt"><TextArea value={d.notes} onChange={(v) => setD((x) => ({ ...x, notes: v }))} rows={2} /></Field>
      <div className="row mt">
        <Btn kind="primary" busy={busy} disabled={!d.supplier_id || !d.branch_id || !d.warehouse_id || lines.some((l) => !l.sku || !l.qty || l.unit_cost === "")}
          onClick={() => run(async () => {
            const po = await api.post<PO>("/purchase-orders", { ...d, order_date: d.order_date || null, lines });
            go(`purchasing/${po.id}`);
          })}>حفظ أمر الشراء</Btn>
      </div>
    </Card>
  );
}

function PODetail({ id }: { id: string }) {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const po = useLoad(() => api.get<PO>(`/purchase-orders/${id}`), [id]);
  const sup = useLoad(() => lookups.suppliers(), []);
  useTitle(po.data ? `أمر شراء ${po.data.number}` : "…", <a onClick={() => go("purchasing")} style={{ cursor: "pointer" }}>المشتريات</a>, [po.data?.number]);
  const [receiving, setReceiving] = useState(false);
  const [paying, setPaying] = useState(false);
  if (po.error) return <ErrorBox text={po.error} onRetry={po.reload} />;
  if (po.loading && !po.data) return <Loading />;
  if (!po.data) return <ErrorBox text="أمر الشراء مش موجود." />;
  const p = po.data;
  const write = s.can("purchasing.write", p.branch_id);
  const setStatus = (status: string) => run(async () => {
    await api.post(`/purchase-orders/${id}/status`, { version: p.version, status });
    po.reload();
  });
  return (
    <div className="col" style={{ gap: 14 }}>
      <Card>
        <div className="row wrap" style={{ gap: 18 }}>
          <div><div className="muted small">المورد</div><b>{sup.data?.find((x) => x.id === p.supplier_id)?.name}</b></div>
          {p.customer_id && <div><div className="muted small">طلبية للعميل</div><a style={{ cursor: "pointer", fontWeight: 700 }}
            onClick={() => go(`customers/${p.customer_id}`)}><CustomerName id={p.customer_id} /></a>
            {p.work_order_id && <> · <a style={{ cursor: "pointer" }} onClick={() => go(`work-orders/${p.work_order_id}`)}>أمر التصنيع</a></>}</div>}
          <div><div className="muted small">الحالة</div><Chip color={PO_STATUS[p.status]?.[1]}>{PO_STATUS[p.status]?.[0] ?? p.status}</Chip></div>
          <div><div className="muted small">الإجمالي</div><b><Money v={p.total} /></b></div>
          <div><div className="muted small">المستلم</div><Money v={p.received_value} /></div>
          <div><div className="muted small">المدفوع</div><Money v={p.paid_amount} /></div>
          <div className="end row wrap">
            {write && p.status === "draft" && <Btn kind="primary" busy={busy} onClick={() => setStatus("ordered")}>تأكيد الطلب</Btn>}
            {write && ["ordered", "partial"].includes(p.status) && <Btn kind="success" icon="box" onClick={() => setReceiving(true)}>استلام</Btn>}
            {s.can("treasury.create", p.branch_id) && p.status !== "cancelled" && <Btn icon="cash" onClick={() => setPaying(true)}>دفع للمورد</Btn>}
            {p.status === "draft" && s.can("purchasing.delete", p.branch_id) &&
              <DeleteBtn small={false} path={`/purchase-orders/${id}`} what={`أمر الشراء ${p.number}`} onDone={() => go("purchasing")} />}
            {write && (p.status === "draft" || (p.status === "ordered" && Number(p.received_value) === 0)) && <Btn kind="danger" busy={busy} onClick={() => setStatus("cancelled")}>إلغاء</Btn>}
          </div>
        </div>
      </Card>
      <Card title="الأصناف" flush>
        <Table rows={p.lines} columns={[
          { key: "sku", label: "الكود", render: (l) => <span className="code">{l.sku}</span> },
          { key: "q", label: "الكمية", num: true, render: (l) => <Qty v={l.qty} /> },
          { key: "r", label: "المستلم", num: true, render: (l) => <span className={Number(l.received_qty) >= Number(l.qty) ? "success-text bold" : ""}><Qty v={l.received_qty} /></span> },
          { key: "c", label: "تكلفة الوحدة", num: true, render: (l) => <Money v={l.unit_cost} /> },
        ]} />
      </Card>
      {p.notes && <Card title="ملاحظات"><div style={{ whiteSpace: "pre-wrap" }}>{p.notes}</div></Card>}
      {receiving && <Receive po={p} onClose={() => setReceiving(false)} onSaved={po.reload} />}
      {paying && <PaymentForm onClose={() => setPaying(false)} onSaved={po.reload}
        initial={{ direction: "out", party_type: "supplier", party_id: p.supplier_id, purchase_order_id: p.id }} />}
    </div>
  );
}

function Receive({ po, onClose, onSaved }: { po: PO; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [qty, setQty] = useState<Record<string, string>>(() => Object.fromEntries((po.lines ?? []).map((l) =>
    [l.id, String(Math.max(0, Number(l.qty) - Number(l.received_qty)))])));
  const [updateCost, setUpdateCost] = useState(true);
  return (
    <Modal title="استلام في المخزن" size="wide" onClose={onClose} footer={<><Btn kind="success" busy={busy} onClick={() => run(async () => {
      await api.post(`/purchase-orders/${po.id}/receive`, { version: po.version, update_company_cost: updateCost,
        lines: Object.entries(qty).filter(([, q]) => Number(q) > 0).map(([line_id, q]) => ({ line_id, qty: q })) });
      toast.ok("اتسجل الاستلام في المخزن."); onSaved(); onClose();
    })}>تسجيل الاستلام</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <table className="editor-table">
        <thead><tr><th>الكود</th><th className="n">المطلوب</th><th className="n">اتستلم قبل كده</th><th>المستلم دلوقتي</th></tr></thead>
        <tbody>{(po.lines ?? []).map((l) => (
          <tr key={l.id}><td><span className="code">{l.sku}</span></td><td className="n"><Qty v={l.qty} /></td><td className="n"><Qty v={l.received_qty} /></td>
            <td><NumIn value={qty[l.id]} onChange={(v) => setQty((x) => ({ ...x, [l.id]: v }))} /></td></tr>))}</tbody>
      </table>
      <div className="mt"><Check checked={updateCost} onChange={setUpdateCost} label="سعر الشراء ده يبقى تكلفة الخامة عند الشركة" /></div>
    </Modal>
  );
}

function Suppliers() {
  const s = useSession();
  const [offset, setOffset] = useState(0);
  const [edit, setEdit] = useState<Partial<S<"SupplierOut">> | null>(null);
  const [stmt, setStmt] = useState<S<"SupplierOut"> | null>(null);
  const list = useLoad(() => api.get<S<"Page_SupplierOut_">>("/suppliers", { limit: 50, offset }), [offset]);
  return (
    <div className="col">
      <PageHead>{s.can("purchasing.create") && <Btn kind="primary" icon="plus" onClick={() => setEdit({})}>مورد جديد</Btn>}</PageHead>
      <Table rows={list.data?.items} loading={list.loading} onRow={(x) => s.can("purchasing.write") && setEdit(x)} columns={[
        { key: "c", label: "الكود", render: (x) => <span className="code">{x.code}</span> },
        { key: "n", label: "الاسم", render: (x) => <b>{x.name}</b> },
        { key: "p", label: "المسؤول", render: (x) => x.contact_name ?? "" },
        { key: "t", label: "التليفون", render: (x) => <span className="num">{x.phone ?? ""}</span> },
        { key: "s", label: "", render: (x) => s.can("treasury.read") && <Btn small onClick={(e) => { e.stopPropagation(); setStmt(x); }}>كشف حساب</Btn> },
        { key: "del", label: "", width: 80, render: (x) => s.can("purchasing.delete") &&
          <DeleteBtn path={`/suppliers/${x.id}`} what={`المورد ${x.name}`} onDone={() => { invalidate("suppliers"); list.reload(); }} /> },
      ]} empty="مفيش موردين" />
      {list.data && <Pager total={list.data.total} limit={50} offset={offset} onChange={setOffset} />}
      {edit && <SupplierForm supplier={edit} onClose={() => setEdit(null)} onSaved={() => { invalidate("suppliers"); list.reload(); }} />}
      {stmt && <SupplierStatement supplier={stmt} onClose={() => setStmt(null)} />}
    </div>
  );
}

function SupplierForm({ supplier, onClose, onSaved }: { supplier: Partial<S<"SupplierOut">>; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState(supplier);
  const set = (k: keyof S<"SupplierOut">) => (v: string) => setD((x) => ({ ...x, [k]: v }));
  return (
    <Modal title={supplier.id ? "تعديل المورد" : "مورد جديد"} size="wide" onClose={onClose} footer={<><Btn kind="primary" busy={busy} disabled={!d.name}
      onClick={() => run(async () => {
        const body = { name: d.name, contact_name: d.contact_name || null, phone: d.phone || null, email: d.email || null,
          address: d.address || null, tax_number: d.tax_number || null, notes: d.notes ?? "" };
        if (supplier.id) await api.patch(`/suppliers/${supplier.id}`, { ...body, version: supplier.version });
        else await api.post("/suppliers", { ...body, code: d.code || null });
        onSaved(); onClose();
      })}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2">
        <Field label="الاسم"><TextIn value={d.name} onChange={set("name")} autoFocus /></Field>
        <Field label="الكود"><TextIn value={d.code} onChange={set("code")} code disabled={!!supplier.id} /></Field>
        <Field label="المسؤول"><TextIn value={d.contact_name} onChange={set("contact_name")} /></Field>
        <Field label="التليفون"><TextIn value={d.phone} onChange={set("phone")} code /></Field>
        <Field label="الإيميل"><TextIn value={d.email} onChange={set("email")} code /></Field>
        <Field label="الرقم الضريبي"><TextIn value={d.tax_number} onChange={set("tax_number")} code /></Field>
        <Field label="العنوان" className="span-all"><TextIn value={d.address} onChange={set("address")} /></Field>
        <Field label="ملاحظات" className="span-all"><TextArea value={d.notes} onChange={set("notes")} rows={2} /></Field>
      </div>
    </Modal>
  );
}

type SupStatement = { received_value: string; paid: string; balance: string; orders: { id: string; number: string; status: string; total: string; received_value: string; paid: string }[] };

function SupplierStatement({ supplier, onClose }: { supplier: S<"SupplierOut">; onClose: () => void }) {
  const st = useLoad(() => when(true, () => api.get<SupStatement>(`/suppliers/${supplier.id}/statement`)), [supplier.id]);
  return (
    <Modal title={`كشف حساب ${supplier.name}`} size="wide" onClose={onClose}>
      {!st.data ? <Loading /> : <>
        <div className="grid g3 mb">
          <div className="card kpi"><div className="label">قيمة المستلم</div><div className="value"><Money v={st.data.received_value} /></div></div>
          <div className="card kpi"><div className="label">المدفوع</div><div className="value"><Money v={st.data.paid} /></div></div>
          <div className="card kpi"><div className="label">المستحق للمورد</div><div className="value"><Money v={st.data.balance} /></div></div>
        </div>
        <Table rows={st.data.orders} onRow={(o) => { onClose(); go(`purchasing/${o.id}`); }} columns={[
          { key: "n", label: "الأمر", render: (o) => <span className="num">{o.number}</span> },
          { key: "s", label: "الحالة", render: (o) => <Chip color={PO_STATUS[o.status]?.[1]}>{PO_STATUS[o.status]?.[0] ?? o.status}</Chip> },
          { key: "t", label: "الإجمالي", num: true, render: (o) => <Money v={o.total} /> },
          { key: "r", label: "المستلم", num: true, render: (o) => <Money v={o.received_value} /> },
          { key: "p", label: "المدفوع", num: true, render: (o) => <Money v={o.paid} /> },
        ]} />
      </>}
    </Modal>
  );
}
