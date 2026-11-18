// المشروع: شغل عميل واحد على مراحل؛ كل مرحلة عرض سعر لوحده بمقاساته وأمر تصنيع وطلبيات لوحدهم، والمشروع بيجمعهم.
import { useState } from "react";
import { api, type S } from "../api/client";
import { useAction, useLoad } from "../lib/hooks";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Chip, ErrorBox, Field, Loading, Modal, Money, Table, TextIn } from "./ui";
import { QUOTE_STATUS, STAGE_NAMES } from "../lib/lookups";
import { go } from "../lib/router";
import { date } from "../lib/format";

type Project = S<"ProjectOut">;

export function ProjectView({ id, onClose }: { id: string; onClose: () => void }) {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const p = useLoad(() => api.get<Project>(`/projects/${id}`), [id]);
  const [name, setName] = useState<string | null>(null);
  const x = p.data;
  const open = (path: string) => { onClose(); go(path); };
  return (
    <Modal title={x ? `${x.name} · ${x.number}` : "المشروع"} size="xwide" onClose={onClose} footer={<Btn onClick={onClose}>رجوع</Btn>}>
      {p.error && <ErrorBox text={p.error} onRetry={p.reload} />}
      {!x ? <Loading /> : <div className="col" style={{ gap: 12 }}>
        <div className="row wrap" style={{ gap: 18 }}>
          <span>العميل: <b>{x.customer_name}</b></span>
          <span>إجمالي العروض: <b><Money v={x.quoted_total} /></b></span>
          <span>إجمالي أوامر التصنيع: <b><Money v={x.ordered_total} /></b></span>
          <span>المدفوع: <b className="success-text"><Money v={x.paid} /></b></span>
          <span>الباقي: <b className="danger-text"><Money v={x.remaining} cur /></b></span>
        </div>
        {s.can("quotes.write", x.branch_id) && <div className="row" style={{ gap: 8 }}>
          {name === null ? <Btn small icon="edit" onClick={() => setName(x.name)}>تغيير اسم المشروع</Btn> : <>
            <div style={{ width: 280 }}><TextIn value={name} onChange={setName} autoFocus /></div>
            <Btn small kind="primary" busy={busy} disabled={!name.trim()} onClick={() => run(async () => {
              p.set(await api.patch<Project>(`/projects/${id}`, { version: x.version, name: name.trim() })); setName(null); })}>حفظ</Btn>
            <Btn small onClick={() => setName(null)}>رجوع</Btn></>}
        </div>}
        <Table rows={x.phases} rowKey={(ph) => ph.quotation_id} empty="مفيش مراحل" columns={[
          { key: "n", label: "المرحلة", render: (ph) => <b>{ph.phase_name ?? "—"}</b> },
          { key: "q", label: "عرض السعر", render: (ph) => <a style={{ cursor: "pointer" }} onClick={() => open(`quotations/${ph.quotation_id}`)}>
            <span className="num">{ph.quotation_number}</span></a> },
          { key: "d", label: "التاريخ", render: (ph) => <span className="num">{date(ph.issue_date)}</span> },
          { key: "l", label: "البنود", num: true, render: (ph) => <span className="num">{ph.lines}</span> },
          { key: "s", label: "حالة العرض", render: (ph) => <Chip color={QUOTE_STATUS[ph.status]?.[1]}>{QUOTE_STATUS[ph.status]?.[0] ?? ph.status}</Chip> },
          { key: "t", label: "إجمالي العرض", num: true, render: (ph) => <Money v={ph.total} /> },
          { key: "w", label: "أمر التصنيع", render: (ph) => ph.work_order_id ? <a style={{ cursor: "pointer" }} onClick={() => open(`work-orders/${ph.work_order_id}`)}>
            <span className="num">{ph.work_order_number}</span> <Chip>{STAGE_NAMES[ph.stage ?? ""] ?? ph.stage}</Chip></a> : <span className="muted small">لسه</span> },
          { key: "p", label: "المدفوع", num: true, render: (ph) => ph.paid != null ? <Money v={ph.paid} /> : "—" },
        ]} />
        <div className="muted small">كل مرحلة ليها مقاساتها وأمر تصنيعها وطلبيات شرائها لوحدها. «مرحلة جديدة» من أي عرض سعر في المشروع بتضيف مرحلة.</div>
      </div>}
    </Modal>
  );
}

/** «مرحلة جديدة» من عرض سعر: عرض سعر فاضي لنفس العميل في نفس المشروع. */
export function NewPhase({ quote, onClose }: { quote: { id: string; project_id?: string | null }; onClose: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [phase, setPhase] = useState("");
  const [project, setProject] = useState("");
  return (
    <Modal title="مرحلة جديدة لنفس المشروع" onClose={onClose} footer={<><Btn kind="primary" busy={busy} onClick={() => run(async () => {
      const out = await api.post<{ id: string }>(`/quotations/${quote.id}/phase`, { phase_name: phase.trim() || null,
        project_name: project.trim() || null });
      toast.ok("اتعمل عرض سعر المرحلة الجديدة: ضيف مقاساتها.");
      onClose(); go(`quotations/${out.id}`);
    })}>إنشاء</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col">
        {!quote.project_id && <Field label="اسم المشروع" hint="فاضي = «مشروع» + اسم العميل. العرض ده هيبقى المرحلة 1">
          <TextIn value={project} onChange={setProject} autoFocus /></Field>}
        <Field label="اسم المرحلة" hint="فاضي = المرحلة 2، 3…"><TextIn value={phase} onChange={setPhase} /></Field>
        <div className="muted small">هيتعمل عرض سعر جديد فاضي لنفس العميل، تضيف فيه مقاسات المرحلة دي. وليه أمر تصنيع وطلبيات لوحده، والمشروع بيجمع الكل.</div>
      </div>
    </Modal>
  );
}

/** مشاريع العميل */
export function CustomerProjects({ customerId }: { customerId: string }) {
  const list = useLoad(() => api.get<Project[]>("/projects", { customer_id: customerId }), [customerId]);
  const [open, setOpen] = useState<string | null>(null);
  return <>
    <Table rows={list.data} loading={list.loading} onRow={(p) => setOpen(p.id)}
      empty="مفيش مشاريع. من أي عرض سعر دوس «مرحلة جديدة» عشان تعمل مشروع على مراحل." columns={[
        { key: "n", label: "المشروع", render: (p) => <b>{p.name}</b> },
        { key: "c", label: "الرقم", render: (p) => <span className="num">{p.number}</span> },
        { key: "ph", label: "المراحل", num: true, render: (p) => <span className="num">{p.phases.length}</span> },
        { key: "q", label: "إجمالي العروض", num: true, render: (p) => <Money v={p.quoted_total} /> },
        { key: "o", label: "أوامر التصنيع", num: true, render: (p) => <Money v={p.ordered_total} /> },
        { key: "p", label: "المدفوع", num: true, render: (p) => <Money v={p.paid} /> },
        { key: "r", label: "الباقي", num: true, render: (p) => <b><Money v={p.remaining} /></b> },
      ]} />
    {open && <ProjectView id={open} onClose={() => { setOpen(null); list.reload(); }} />}
  </>;
}
