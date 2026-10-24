import { useEffect, useState } from "react";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useDebounced, useLoad } from "../lib/hooks";
import { useDefaultBranch, useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, ErrorBox, Field, Modal, Money, NumIn, PageHead, Pager, Qty, SearchBox, Table, Tabs, TextIn } from "../components/ui";
import { BranchName, BranchSelect, WarehouseSelect } from "../components/pickers";
import { invalidate, lookups, UNITS } from "../lib/lookups";
import { setQuery } from "../lib/router";
import { dateTime } from "../lib/format";

const KINDS: Record<string, string> = { receipt: "استلام شراء", issue: "صرف لأمر تصنيع", adjustment: "تسوية", transfer_out: "تحويل خارج",
  transfer_in: "تحويل داخل", return: "مرتجع" };

export default function Inventory({ route }: PageProps) {
  useTitle("المخازن");
  const s = useSession();
  const tab = route.query.tab ?? "balances";
  const [wh, setWh] = useState("");
  const whs = useLoad(() => lookups.warehouses(), []);
  useEffect(() => {
    if (!wh && whs.data?.length) setWh(whs.data.find((w) => w.is_active && (!s.branchId || w.branch_id === s.branchId))?.id ?? whs.data[0].id);
  }, [whs.data, s.branchId]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="col" style={{ gap: 14 }}>
      <Card flush>
        <Tabs value={tab} onChange={(t) => setQuery({ tab: t })} tabs={[
          { id: "balances", label: "الأرصدة" }, { id: "movements", label: "الحركات" }, { id: "transfers", label: "التحويلات" },
          { id: "warehouses", label: "المخازن", hidden: !s.can("org.manage") },
        ]} />
        <div className="card-b">
          {tab !== "warehouses" && tab !== "transfers" && <div className="row" style={{ width: 260 }}><WarehouseSelect value={wh} onChange={setWh} allowAll={tab === "movements" ? "كل المخازن" : undefined} /></div>}
          {tab === "balances" && <Balances wh={wh} />}
          {tab === "movements" && <Movements wh={wh} />}
          {tab === "transfers" && <Transfers />}
          {tab === "warehouses" && <Warehouses />}
        </div>
      </Card>
    </div>
  );
}

/** SKU input with suggestions from the library (material code + colour). */
export function SkuIn({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const skus = useLoad(() => api.get<S<"Page_MaterialOut_">>("/library/materials", { limit: 500 })
    .then((p) => p.items.flatMap((m) => m.variants?.length ? m.variants.map((v) => ({ sku: v.sku, name: `${m.name} ${v.name || v.color_code}` })) : [{ sku: m.code, name: m.name }])), []);
  return (
    <>
      <input className="input code-in" list="sku-list" value={value} onChange={(e) => onChange(e.target.value.trim())} placeholder="SKU" />
      <datalist id="sku-list">{(skus.data ?? []).map((x) => <option key={x.sku} value={x.sku}>{x.name}</option>)}</datalist>
    </>
  );
}

function Balances({ wh }: { wh: string }) {
  const s = useSession();
  const [q, setQ] = useState("");
  const [adjust, setAdjust] = useState(false);
  const list = useLoad(() => wh ? api.get<S<"BalanceOut">[]>("/inventory/balances", { warehouse_id: wh }) : Promise.resolve([]), [wh]);
  const rows = (list.data ?? []).filter((b) => !q || b.sku.toLowerCase().includes(q.trim().toLowerCase()));
  const whs = useLoad(() => lookups.warehouses(), []);
  return (
    <div className="col mt">
      <PageHead>
        <SearchBox value={q} onChange={setQ} placeholder="بحث بالكود…" />
        {s.can("inventory.write") && <Btn kind="primary" icon="plus" onClick={() => setAdjust(true)}>تسوية / رصيد افتتاحي</Btn>}
      </PageHead>
      {list.error && <ErrorBox text={list.error} onRetry={list.reload} />}
      <Table rows={rows} loading={list.loading} rowKey={(b) => b.warehouse_id + b.sku} columns={[
        { key: "sku", label: "الكود", render: (b) => <span className="code">{b.sku}</span> },
        { key: "w", label: "المخزن", render: (b) => whs.data?.find((w) => w.id === b.warehouse_id)?.name ?? "" },
        { key: "q", label: "الرصيد", num: true, render: (b) => <span className={Number(b.qty) < 0 ? "danger-text bold" : "bold"}><Qty v={b.qty} /> <span className="muted small">{UNITS[b.unit] ?? b.unit}</span></span> },
        { key: "c", label: "متوسط التكلفة", num: true, render: (b) => <Money v={b.avg_cost} /> },
      ]} empty="مفيش أرصدة" />
      {adjust && <Adjust onClose={() => setAdjust(false)} onSaved={list.reload} defaultWh={wh} />}
    </div>
  );
}

function Adjust({ onClose, onSaved, defaultWh }: { onClose: () => void; onSaved: () => void; defaultWh: string }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [wh, setWh] = useState(defaultWh);
  const [reason, setReason] = useState("");
  const [lines, setLines] = useState([{ sku: "", qty: "", unit_cost: "", note: "" }]);
  const setLine = (i: number, k: string, v: string) => setLines((x) => x.map((l, j) => j === i ? { ...l, [k]: v } : l));
  return (
    <Modal title="تسوية مخزن" size="wide" onClose={onClose} footer={<><Btn kind="primary" busy={busy} disabled={!wh || !reason || lines.some((l) => !l.sku || !l.qty)}
      onClick={() => run(async () => {
        await api.post("/inventory/adjustments", { warehouse_id: wh, reason, lines: lines.map((l) => ({ ...l, unit_cost: l.unit_cost || null })) });
        toast.ok("اتسجلت التسوية."); onSaved(); onClose();
      })}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2 mb">
        <Field label="المخزن"><WarehouseSelect value={wh} onChange={setWh} /></Field>
        <Field label="السبب"><TextIn value={reason} onChange={setReason} placeholder="جرد، رصيد افتتاحي، تالف…" /></Field>
      </div>
      <div className="notice info mb">الكمية بالموجب للزيادة وبالسالب للنقص.</div>
      <table className="editor-table">
        <thead><tr><th>الكود</th><th>الكمية</th><th>تكلفة الوحدة</th><th>ملاحظة</th><th /></tr></thead>
        <tbody>{lines.map((l, i) => (
          <tr key={i}>
            <td><SkuIn value={l.sku} onChange={(v) => setLine(i, "sku", v)} /></td>
            <td><NumIn value={l.qty} onChange={(v) => setLine(i, "qty", v)} /></td>
            <td><NumIn value={l.unit_cost} onChange={(v) => setLine(i, "unit_cost", v)} /></td>
            <td><TextIn value={l.note} onChange={(v) => setLine(i, "note", v)} /></td>
            <td><Btn small icon="trash" kind="danger" disabled={lines.length === 1} onClick={() => setLines((x) => x.filter((_, j) => j !== i))} /></td>
          </tr>))}</tbody>
      </table>
      <Btn small icon="plus" className="mt" onClick={() => setLines((x) => [...x, { sku: "", qty: "", unit_cost: "", note: "" }])}>سطر</Btn>
    </Modal>
  );
}

function Movements({ wh }: { wh: string }) {
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const list = useLoad(() => api.get<S<"Page_MovementOut_">>("/inventory/movements", { warehouse_id: wh || undefined, sku: dq || undefined, limit: 50, offset }), [wh, dq, offset]);
  const whs = useLoad(() => lookups.warehouses(), []);
  return (
    <div className="col mt">
      <PageHead><SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="بحث بالكود…" /></PageHead>
      <Table rows={list.data?.items} loading={list.loading} columns={[
        { key: "at", label: "الوقت", render: (m) => <span className="num">{dateTime(m.at)}</span> },
        { key: "w", label: "المخزن", render: (m) => whs.data?.find((w) => w.id === m.warehouse_id)?.name ?? "" },
        { key: "sku", label: "الكود", render: (m) => <span className="code">{m.sku}</span> },
        { key: "k", label: "النوع", render: (m) => <Chip>{KINDS[m.kind] ?? m.kind}</Chip> },
        { key: "q", label: "الكمية", num: true, render: (m) => <b className={Number(m.qty) < 0 ? "danger-text" : "success-text"}><Qty v={m.qty} /></b> },
        { key: "c", label: "التكلفة", num: true, render: (m) => <Money v={m.unit_cost} /> },
        { key: "n", label: "ملاحظة", render: (m) => <span className="muted small">{m.note}</span> },
      ]} empty="مفيش حركات" />
      {list.data && <Pager total={list.data.total} limit={50} offset={offset} onChange={setOffset} />}
    </div>
  );
}

const T_STATUS: Record<string, [string, "gray" | "amber" | "green" | "red"]> = { draft: ["مسودة", "gray"], sent: ["في الطريق", "amber"],
  received: ["اتستلم", "green"], cancelled: ["ملغي", "red"] };

function Transfers() {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [creating, setCreating] = useState(false);
  const list = useLoad(() => api.get<S<"TransferOut">[]>("/inventory/transfers"), []);
  const whs = useLoad(() => lookups.warehouses(), []);
  const name = (id: string) => whs.data?.find((w) => w.id === id)?.name ?? "";
  const act = (t: S<"TransferOut">, what: "send" | "receive") => run(async () => {
    await api.post(`/inventory/transfers/${t.id}/${what}`, { version: t.version });
    toast.ok(what === "send" ? "اتبعت التحويل." : "اتستلم التحويل.");
    list.reload();
  });
  return (
    <div className="col mt">
      <PageHead>{s.can("inventory.write") && <Btn kind="primary" icon="swap" onClick={() => setCreating(true)}>تحويل جديد</Btn>}</PageHead>
      <Table rows={list.data} loading={list.loading} columns={[
        { key: "n", label: "الرقم", render: (t) => <span className="num">{t.number}</span> },
        { key: "f", label: "من", render: (t) => name(t.from_warehouse_id) },
        { key: "t", label: "إلى", render: (t) => name(t.to_warehouse_id) },
        { key: "l", label: "الأصناف", render: (t) => <span className="small">{(t.lines as any[]).map((l) => `${l.sku} × ${Number(l.qty)}`).join("، ")}</span> },
        { key: "s", label: "الحالة", render: (t) => <Chip color={T_STATUS[t.status]?.[1]}>{T_STATUS[t.status]?.[0] ?? t.status}</Chip> },
        { key: "a", label: "", render: (t) => s.can("inventory.write") && (t.status === "draft"
          ? <Btn small busy={busy} onClick={() => act(t, "send")}>إرسال</Btn>
          : t.status === "sent" ? <Btn small kind="success" busy={busy} onClick={() => act(t, "receive")}>استلام</Btn> : null) },
      ]} empty="مفيش تحويلات" />
      {creating && <NewTransfer onClose={() => setCreating(false)} onSaved={list.reload} />}
    </div>
  );
}

function NewTransfer({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [note, setNote] = useState("");
  const [lines, setLines] = useState([{ sku: "", qty: "" }]);
  const setLine = (i: number, k: string, v: string) => setLines((x) => x.map((l, j) => j === i ? { ...l, [k]: v } : l));
  return (
    <Modal title="تحويل بين المخازن" size="wide" onClose={onClose} footer={<><Btn kind="primary" busy={busy}
      disabled={!from || !to || from === to || lines.some((l) => !l.sku || !l.qty)}
      onClick={() => run(async () => { await api.post("/inventory/transfers", { from_warehouse_id: from, to_warehouse_id: to, note, lines }); onSaved(); onClose(); })}>حفظ</Btn>
      <Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g3 mb">
        <Field label="من مخزن"><WarehouseSelect value={from} onChange={setFrom} /></Field>
        <Field label="إلى مخزن"><WarehouseSelect value={to} onChange={setTo} /></Field>
        <Field label="ملاحظة"><TextIn value={note} onChange={setNote} /></Field>
      </div>
      <table className="editor-table">
        <thead><tr><th>الكود</th><th>الكمية</th><th /></tr></thead>
        <tbody>{lines.map((l, i) => (
          <tr key={i}><td><SkuIn value={l.sku} onChange={(v) => setLine(i, "sku", v)} /></td>
            <td><NumIn value={l.qty} onChange={(v) => setLine(i, "qty", v)} /></td>
            <td><Btn small icon="trash" kind="danger" disabled={lines.length === 1} onClick={() => setLines((x) => x.filter((_, j) => j !== i))} /></td></tr>))}</tbody>
      </table>
      <Btn small icon="plus" className="mt" onClick={() => setLines((x) => [...x, { sku: "", qty: "" }])}>سطر</Btn>
    </Modal>
  );
}

function Warehouses() {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const list = useLoad(() => api.get<S<"WarehouseOut">[]>("/warehouses"), []);
  const branch = useDefaultBranch("org.manage");
  const [d, setD] = useState<{ code: string; name: string; branch_id: string } | null>(null);
  return (
    <div className="col mt">
      <PageHead><Btn kind="primary" icon="plus" onClick={() => setD({ code: "", name: "", branch_id: branch ?? "" })}>مخزن جديد</Btn></PageHead>
      <Table rows={list.data} loading={list.loading} columns={[
        { key: "c", label: "الكود", render: (w) => <span className="code">{w.code}</span> },
        { key: "n", label: "الاسم", render: (w) => <b>{w.name}</b> },
        { key: "b", label: "الفرع", render: (w) => <BranchName id={w.branch_id} /> },
        { key: "a", label: "الحالة", render: (w) => <Btn small onClick={() => run(async () => {
          await api.patch(`/warehouses/${w.id}`, { version: w.version, is_active: !w.is_active }); invalidate("warehouses"); list.reload(); })}>
          {w.is_active ? "نشط · إيقاف" : "متوقف · تفعيل"}</Btn> },
      ]} />
      {d && <Modal title="مخزن جديد" onClose={() => setD(null)} footer={<><Btn kind="primary" busy={busy} disabled={!d.code || !d.name || !d.branch_id}
        onClick={() => run(async () => { await api.post("/warehouses", d); invalidate("warehouses"); list.reload(); setD(null); })}>حفظ</Btn><Btn onClick={() => setD(null)}>رجوع</Btn></>}>
        <div className="col">
          <Field label="الكود"><TextIn value={d.code} onChange={(v) => setD({ ...d, code: v })} code /></Field>
          <Field label="الاسم"><TextIn value={d.name} onChange={(v) => setD({ ...d, name: v })} /></Field>
          <Field label="الفرع"><BranchSelect value={d.branch_id} onChange={(v) => setD({ ...d, branch_id: v })} /></Field>
        </div>
      </Modal>}
    </div>
  );
}
