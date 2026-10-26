// Customer profile: maintenance requests (طلبات الصيانة) and technicians' visits.
import { useState } from "react";
import { api, type S } from "../api/client";
import { useAction, useLoad } from "../lib/hooks";
import { JOB_KINDS, JOB_STATUS, MAINT_STATUS } from "../lib/lookups";
import { setQuery, useRoute } from "../lib/router";
import { date, dateTime, today } from "../lib/format";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { DeleteBtn } from "./actions";
import { AssignJob, LocationField, MapBtn } from "./field";
import { BranchSelect } from "./pickers";
import { Btn, Chip, Field, Modal, Money, NumIn, PageHead, Select, Table, TextArea, TextIn } from "./ui";

type Req = S<"MaintenanceOut">;

export function Maintenance({ customer }: { customer: S<"CustomerOut"> }) {
  const s = useSession();
  const route = useRoute();
  const list = useLoad(() => api.get<S<"Page_MaintenanceOut_">>("/maintenance", { customer_id: customer.id, limit: 100 }), [customer.id]);
  const [edit, setEdit] = useState<Partial<Req> | null>(null);
  const [assign, setAssign] = useState<Req | null>(null);
  const creating = route.query.new === "1";
  const close = () => { setEdit(null); if (creating) setQuery({ new: undefined }); };
  const blank: Partial<Req> = { branch_id: customer.branch_id ?? s.branchId ?? s.branches[0]?.id, address: customer.address ?? "" };
  return (
    <div className="card-b col">
      <PageHead>{s.can("maintenance.create") && <Btn kind="primary" icon="plus" onClick={() => setEdit(blank)}>طلب صيانة جديد</Btn>}</PageHead>
      <Table rows={list.data?.items} loading={list.loading} onRow={(m) => s.can("maintenance.write", m.branch_id) && setEdit(m)} empty="مفيش طلبات صيانة" columns={[
        { key: "n", label: "الرقم", render: (m) => <span className="num bold">{m.number}</span> },
        { key: "d", label: "التاريخ", render: (m) => <span className="num">{date(m.request_date)}</span> },
        { key: "t", label: "المشكلة", render: (m) => <span className="ellipsis" style={{ maxWidth: 320, display: "block" }}>{m.description}</span> },
        { key: "s", label: "الحالة", render: (m) => <Chip color={MAINT_STATUS[m.status]?.[1]}>{MAINT_STATUS[m.status]?.[0] ?? m.status}</Chip> },
        { key: "c", label: "التكلفة", num: true, render: (m) => <Money v={m.cost} /> },
        { key: "a", label: "", render: (m) => <div className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
          <MapBtn place={m} label="" />
          {s.can("field.manage", m.branch_id) && ["open", "scheduled"].includes(m.status) &&
            <Btn small icon="truck" onClick={(e) => { e.stopPropagation(); setAssign(m); }}>إسناد لفني</Btn>}
          {s.can("maintenance.delete", m.branch_id) && <DeleteBtn path={`/maintenance/${m.id}`} what={`طلب الصيانة ${m.number}`} onDone={list.reload} />}
        </div> },
      ]} />
      {(edit || creating) && <MaintenanceForm req={edit ?? blank} customerId={customer.id} onClose={close} onSaved={list.reload} />}
      {assign && <AssignJob job={{ kind: "maintenance", customer_id: customer.id, branch_id: assign.branch_id, maintenance_id: assign.id }}
        onClose={() => setAssign(null)} onSaved={list.reload} />}
    </div>
  );
}

function MaintenanceForm({ req, customerId, onClose, onSaved }: { req: Partial<Req>; customerId: string; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState({ description: req.description ?? "", address: req.address ?? "", location_url: req.location_url ?? "",
    branch_id: req.branch_id ?? "", request_date: req.request_date ?? today(), status: req.status ?? "open", cost: req.cost ?? "0", notes: req.notes ?? "" });
  const set = (k: keyof typeof d) => (v: string) => setD((x) => ({ ...x, [k]: v }));
  return (
    <Modal title={req.id ? `طلب صيانة ${req.number}` : "طلب صيانة جديد"} size="wide" onClose={onClose} footer={<>
      <Btn kind="primary" busy={busy} disabled={!d.description.trim() || !d.branch_id} onClick={() => run(async () => {
        const body = { description: d.description, address: d.address || null, location_url: d.location_url || null, cost: d.cost || "0", notes: d.notes };
        if (req.id) await api.patch(`/maintenance/${req.id}`, { ...body, version: req.version, status: d.status });
        else await api.post("/maintenance", { ...body, customer_id: customerId, branch_id: d.branch_id, request_date: d.request_date || null });
        toast.ok(req.id ? "اتحفظ طلب الصيانة." : "اتسجل طلب الصيانة.");
        onSaved();
        onClose();
      })}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2">
        <Field label="المشكلة" className="span-all"><TextArea value={d.description} onChange={set("description")} rows={3} /></Field>
        <Field label="العنوان" className="span-all"><TextIn value={d.address} onChange={set("address")} /></Field>
        <LocationField value={d.location_url} onChange={set("location_url")} />
        {!req.id && <Field label="التاريخ"><input type="date" className="input" value={d.request_date} onChange={(e) => set("request_date")(e.target.value)} /></Field>}
        {!req.id && <Field label="الفرع"><BranchSelect value={d.branch_id} onChange={set("branch_id")} perm="maintenance.create" /></Field>}
        {req.id && <Field label="الحالة"><Select value={d.status} onChange={set("status")}
          options={Object.entries(MAINT_STATUS).map(([value, [label]]) => ({ value, label }))} /></Field>}
        <Field label="التكلفة"><NumIn value={String(d.cost)} onChange={set("cost")} /></Field>
        <Field label="ملاحظات" className="span-all"><TextArea value={d.notes} onChange={set("notes")} rows={2} /></Field>
      </div>
    </Modal>
  );
}

/** Technicians' visits for this customer (surveys, installations, maintenance). */
export function Visits({ customerId }: { customerId: string }) {
  const jobs = useLoad(() => api.get<S<"JobOut">[]>("/field/jobs", { customer_id: customerId }), [customerId]);
  return (
    <Table rows={jobs.data} loading={jobs.loading} empty="مفيش زيارات" columns={[
      { key: "k", label: "الزيارة", render: (j) => <Chip color="violet">{JOB_KINDS[j.kind] ?? j.kind}</Chip> },
      { key: "r", label: "المرجع", render: (j) => <span className="num">{j.reference}</span> },
      { key: "t", label: "الفني", render: (j) => j.technician_name },
      { key: "w", label: "الميعاد", render: (j) => <span className="num">{dateTime(j.scheduled_at)}</span> },
      { key: "s", label: "الحالة", render: (j) => <Chip color={JOB_STATUS[j.status]?.[1]}>{JOB_STATUS[j.status]?.[0] ?? j.status}</Chip> },
      { key: "f", label: "خلصت", render: (j) => <span className="num">{dateTime(j.finished_at)}</span> },
      { key: "n", label: "ملاحظة الفني", render: (j) => <span className="small">{j.result_note}</span> },
    ]} />
  );
}
