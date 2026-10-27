// الفُضل (offcuts): leftovers of 40 cm and more kept after cutting. Orders cut from them first; the rest is scrap.
import { useState } from "react";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useDebounced, useLoad } from "../lib/hooks";
import { useDefaultBranch, useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Chip, Field, Len, Modal, NumIn, PageHead, Pager, SearchBox, Select, Table, TextIn, Card } from "../components/ui";
import { BranchName, BranchSelect, SkuIn } from "../components/pickers";
import { go } from "../lib/router";
import { date } from "../lib/format";

const STATUS: Record<string, [string, "green" | "blue" | "gray"]> = {
  available: ["موجود", "green"], used: ["اتقطع منه", "blue"], scrapped: ["اتشال هالك", "gray"] };

export default function Offcuts(_: PageProps) {
  useTitle("الفُضل");
  const s = useSession();
  const toast = useToast();
  const { run } = useAction(toast.err);
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [status, setStatus] = useState("available");
  const [offset, setOffset] = useState(0);
  const [adding, setAdding] = useState(false);
  const list = useLoad(() => api.get<S<"Page_OffcutOut_">>("/offcuts", { status: status || undefined, sku: dq || undefined, limit: 100, offset }),
    [status, dq, offset]);
  const minimum = Number(s.company.settings.min_reusable_offcut_mm ?? 400);
  return (
    <Card flush>
      <div className="card-b col">
        <PageHead>
          <div style={{ width: 220 }}><SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="كود القطاع…" /></div>
          <div style={{ width: 160 }}><Select value={status} onChange={(v) => { setStatus(v); setOffset(0); }} placeholder="الكل"
            options={Object.entries(STATUS).map(([value, [label]]) => ({ value, label }))} /></div>
          {s.can("workorders.write") && <Btn kind="primary" icon="plus" onClick={() => setAdding(true)}>فضلة موجودة</Btn>}
        </PageHead>
        <div className="muted small">الفُضل من <Len mm={minimum} /> وأطول بتتشال بعد التقطيع، والأوامر الجاية بتقطع منها الأول قبل الأعواد الجديدة.
          الأقصر هالك. (الحد من «بيانات الشركة ← الإعدادات الافتراضية»)</div>
        <Table rows={list.data?.items} loading={list.loading} empty="مفيش فُضل" columns={[
          { key: "s", label: "القطاع", render: (o) => <span className="code">{o.sku}</span> },
          { key: "l", label: "الطول", num: true, render: (o) => <b><Len mm={o.length_mm} /></b> },
          { key: "b", label: "الفرع", render: (o) => <BranchName id={o.branch_id} /> },
          { key: "st", label: "الحالة", render: (o) => <Chip color={STATUS[o.status]?.[1]}>{STATUS[o.status]?.[0] ?? o.status}</Chip> },
          { key: "f", label: "من أمر", render: (o) => o.source_work_order_id
            ? <a style={{ cursor: "pointer" }} onClick={() => go(`work-orders/${o.source_work_order_id}`)}>فتح</a> : <span className="muted small">جرد</span> },
          { key: "u", label: "اتقطع في", render: (o) => o.used_work_order_id
            ? <a style={{ cursor: "pointer" }} onClick={() => go(`work-orders/${o.used_work_order_id}`)}>فتح</a> : "" },
          { key: "d", label: "التاريخ", render: (o) => <span className="num">{date(o.created_at ?? null)}</span> },
          { key: "n", label: "ملاحظة", render: (o) => <span className="small muted">{o.note}</span> },
          { key: "x", label: "", width: 90, render: (o) => o.status === "available" && s.can("workorders.write", o.branch_id) &&
            <Btn small kind="danger" onClick={() => run(async () => {
              await api.post(`/offcuts/${o.id}/scrap`, { version: o.version, note: "اتشال" }); list.reload(); })}>هالك</Btn> },
        ]} />
        {list.data && <Pager total={list.data.total} limit={100} offset={offset} onChange={setOffset} />}
      </div>
      {adding && <AddOffcut onClose={() => setAdding(false)} onSaved={list.reload} />}
    </Card>
  );
}

function AddOffcut({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const branch = useDefaultBranch("workorders.write");
  const [d, setD] = useState({ branch_id: branch ?? "", sku: "", length_mm: "", note: "" });
  return (
    <Modal title="فضلة موجودة في المصنع" onClose={onClose} footer={<><Btn kind="primary" busy={busy} disabled={!d.sku || !d.length_mm || !d.branch_id}
      onClick={() => run(async () => { await api.post("/offcuts", d); onSaved(); onClose(); })}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col">
        <Field label="القطاع (الكود باللون)"><SkuIn value={d.sku} onChange={(v) => setD((x) => ({ ...x, sku: v }))} /></Field>
        <Field label="الطول (مم)"><NumIn value={d.length_mm} onChange={(v) => setD((x) => ({ ...x, length_mm: v }))} unit="مم" /></Field>
        <Field label="الفرع"><BranchSelect value={d.branch_id} onChange={(v) => setD((x) => ({ ...x, branch_id: v }))} perm="workorders.write" /></Field>
        <Field label="ملاحظة"><TextIn value={d.note} onChange={(v) => setD((x) => ({ ...x, note: v }))} /></Field>
      </div>
    </Modal>
  );
}
