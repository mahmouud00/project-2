// الموارد البشرية: الموظفين (ملف كل موظف: بياناته، حوافز وخصومات وسلف، إجازات، مرتبات، مبيعاته) وكشوف المرتبات.
import { useState } from "react";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useDebounced, useLoad } from "../lib/hooks";
import { useDefaultBranch, useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, ErrorBox, Field, KV, Loading, Modal, Money, NumIn, PageHead, Pager, SearchBox, Select, Table, Tabs,
  TextArea, TextIn } from "../components/ui";
import { BranchName, BranchSelect, CashboxSelect } from "../components/pickers";
import { DeleteBtn } from "../components/actions";
import { QUOTE_STATUS, STAGE_NAMES, invalidate } from "../lib/lookups";
import { go, setQuery } from "../lib/router";
import { date, today } from "../lib/format";

type Emp = S<"EmployeeOut">;
type Entry = S<"EntryOut">;
type Leave = S<"LeaveOut">;
type Run = S<"RunOut">;

export const DEPARTMENTS: Record<string, string> = { sales: "مبيعات", production: "إنتاج", installation: "تركيبات",
  survey: "معاينات", accounts: "حسابات", hr: "موارد بشرية", admin: "إدارة", other: "أخرى" };
const ENTRY_KINDS: Record<string, [string, "green" | "red" | "amber"]> = {
  bonus: ["حافز", "green"], deduction: ["خصم", "red"], advance: ["سلفة", "amber"] };
const LEAVE_KINDS: Record<string, string> = { annual: "اعتيادي", sick: "مرضي", unpaid: "من غير مرتب", other: "أخرى" };
const LEAVE_STATUS: Record<string, [string, "gray" | "green" | "red"]> = {
  requested: ["طلب", "gray"], approved: ["موافق عليها", "green"], rejected: ["مرفوضة", "red"] };
const thisMonth = () => today().slice(0, 7);

export default function Hr({ route }: PageProps) {
  const id = route.path[1];
  if (id) return <EmployeeProfile id={id} tab={route.query.tab ?? "info"} />;
  return <HrHome tab={route.query.tab ?? "employees"} />;
}

function HrHome({ tab }: { tab: string }) {
  useTitle("الموارد البشرية");
  return (
    <Card flush>
      <Tabs value={tab} onChange={(t) => setQuery({ tab: t })} tabs={[{ id: "employees", label: "الموظفين" },
        { id: "payroll", label: "كشوف المرتبات" }]} />
      <div className="card-b">{tab === "payroll" ? <Payroll /> : <Employees />}</div>
    </Card>
  );
}

function Employees() {
  const s = useSession();
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [dept, setDept] = useState("");
  const [status, setStatus] = useState("active");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const list = useLoad(() => api.get<S<"Page_EmployeeOut_">>("/employees", { q: dq || undefined, department: dept || undefined,
    status: status || undefined, limit: 50, offset }), [dq, dept, status, offset]);
  return (
    <div className="col">
      <PageHead>
        <div style={{ width: 220 }}><SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="اسم، كود، وظيفة…" /></div>
        <div style={{ width: 160 }}><Select value={dept} onChange={(v) => { setDept(v); setOffset(0); }} placeholder="كل الأقسام"
          options={Object.entries(DEPARTMENTS).map(([value, label]) => ({ value, label }))} /></div>
        <div style={{ width: 140 }}><Select value={status} onChange={(v) => { setStatus(v); setOffset(0); }} placeholder="الكل"
          options={[{ value: "active", label: "شغالين" }, { value: "left", label: "سابوا الشغل" }]} /></div>
        {s.can("hr.create") && <Btn kind="primary" icon="plus" onClick={() => setCreating(true)}>موظف جديد</Btn>}
      </PageHead>
      {list.error && <ErrorBox text={list.error} onRetry={list.reload} />}
      <Table rows={list.data?.items} loading={list.loading} onRow={(e) => go(`hr/${e.id}`)} empty="مفيش موظفين" columns={[
        { key: "c", label: "الكود", render: (e) => <span className="code">{e.code}</span> },
        { key: "n", label: "الاسم", render: (e) => <b>{e.full_name}</b> },
        { key: "j", label: "الوظيفة", render: (e) => e.job_title },
        { key: "d", label: "القسم", render: (e) => <Chip color={e.department === "sales" ? "violet" : "gray"}>{DEPARTMENTS[e.department] ?? e.department}</Chip> },
        { key: "b", label: "الفرع", render: (e) => <BranchName id={e.branch_id} /> },
        { key: "p", label: "التليفون", render: (e) => <span className="num">{e.phone ?? ""}</span> },
        { key: "s", label: "المرتب", num: true, render: (e) => <Money v={e.base_salary} /> },
        { key: "st", label: "", render: (e) => e.status === "left" && <Chip>ساب الشغل</Chip> },
      ]} />
      {list.data && <Pager total={list.data.total} limit={50} offset={offset} onChange={setOffset} />}
      {creating && <EmployeeForm onClose={() => setCreating(false)} onSaved={(e) => go(`hr/${e.id}`)} />}
    </div>
  );
}

function EmployeeForm({ employee, onClose, onSaved }: { employee?: Emp; onClose: () => void; onSaved: (e: Emp) => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const branch = useDefaultBranch("hr.create");
  const users = useLoad(() => api.get<S<"Page_UserOut_">>("/users", { limit: 500 }).then((p) => p.items).catch(() => []), []);
  const e = employee;
  const [d, setD] = useState({ full_name: e?.full_name ?? "", job_title: e?.job_title ?? "", department: e?.department ?? "sales",
    branch_id: e?.branch_id ?? branch ?? "", phone: e?.phone ?? "", national_id: e?.national_id ?? "", address: e?.address ?? "",
    hire_date: e?.hire_date ?? "", base_salary: e?.base_salary ?? "0", annual_leave_days: e?.annual_leave_days ?? "21",
    user_id: e?.user_id ?? "", notes: e?.notes ?? "", status: e?.status ?? "active", end_date: e?.end_date ?? "" });
  const set = (k: keyof typeof d) => (v: string) => setD((x) => ({ ...x, [k]: v }));
  const save = () => run(async () => {
    const body = { full_name: d.full_name, job_title: d.job_title, department: d.department, branch_id: d.branch_id,
      phone: d.phone || null, national_id: d.national_id || null, address: d.address || null, hire_date: d.hire_date || null,
      base_salary: d.base_salary || "0", annual_leave_days: d.annual_leave_days || "0", user_id: d.user_id || null, notes: d.notes };
    const out = e ? await api.patch<Emp>(`/employees/${e.id}`, { ...body, version: e.version, status: d.status, end_date: d.end_date || null })
      : await api.post<Emp>("/employees", body);
    invalidate("salespeople");
    toast.ok("اتحفظ الموظف.");
    onSaved(out);
    onClose();
  });
  return (
    <Modal title={e ? e.full_name : "موظف جديد"} size="wide" onClose={onClose} footer={<><Btn kind="primary" busy={busy}
      disabled={!d.full_name.trim() || !d.branch_id} onClick={save}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g3">
        <Field label="الاسم" className="span-2"><TextIn value={d.full_name} onChange={set("full_name")} autoFocus /></Field>
        <Field label="الوظيفة"><TextIn value={d.job_title} onChange={set("job_title")} /></Field>
        <Field label="القسم"><Select value={d.department} onChange={set("department")}
          options={Object.entries(DEPARTMENTS).map(([value, label]) => ({ value, label }))} /></Field>
        <Field label="الفرع"><BranchSelect value={d.branch_id} onChange={set("branch_id")} perm={e ? "hr.write" : "hr.create"} /></Field>
        <Field label="تاريخ التعيين"><input type="date" className="input" value={d.hire_date} onChange={(x) => set("hire_date")(x.target.value)} /></Field>
        <Field label="التليفون"><TextIn value={d.phone} onChange={set("phone")} /></Field>
        <Field label="الرقم القومي"><TextIn value={d.national_id} onChange={set("national_id")} code /></Field>
        <Field label="المرتب الأساسي (شهري)"><NumIn value={String(d.base_salary)} onChange={set("base_salary")} /></Field>
        <Field label="العنوان" className="span-2"><TextIn value={d.address} onChange={set("address")} /></Field>
        <Field label="رصيد الإجازات السنوي (يوم)"><NumIn value={String(d.annual_leave_days)} onChange={set("annual_leave_days")} /></Field>
        <Field label="حسابه على البرنامج" hint="لو بيدخل البرنامج: مبيعاته بتتسجل باسمه أوتوماتيك">
          <Select value={d.user_id} onChange={set("user_id")} placeholder="مالوش حساب"
            options={(users.data ?? []).map((u) => ({ value: u.id, label: `${u.full_name} (${u.username})` }))} /></Field>
        {e && <Field label="الحالة"><Select value={d.status} onChange={set("status")}
          options={[{ value: "active", label: "شغال" }, { value: "left", label: "ساب الشغل" }]} /></Field>}
        {e && d.status === "left" && <Field label="تاريخ ترك الشغل"><input type="date" className="input" value={d.end_date}
          onChange={(x) => set("end_date")(x.target.value)} /></Field>}
        <Field label="ملاحظات" className="span-all"><TextArea value={d.notes} onChange={set("notes")} rows={2} /></Field>
      </div>
    </Modal>
  );
}

function EmployeeProfile({ id, tab }: { id: string; tab: string }) {
  const s = useSession();
  const emp = useLoad(() => api.get<Emp>(`/employees/${id}`), [id]);
  const summary = useLoad(() => api.get<{ annual_leave_left: string; advances_owed: string; leave_days: Record<string, string> }>(
    `/employees/${id}/summary`), [id, emp.data?.version]);
  const [editing, setEditing] = useState(false);
  useTitle(emp.data?.full_name ?? "…", <a onClick={() => go("hr")} style={{ cursor: "pointer" }}>الموارد البشرية</a>, [emp.data?.full_name]);
  if (emp.error) return <ErrorBox text={emp.error} onRetry={emp.reload} />;
  if (!emp.data) return <Loading />;
  const e = emp.data;
  return (
    <div className="col" style={{ gap: 14 }}>
      <Card>
        <div className="row wrap" style={{ gap: 18 }}>
          <div><div className="muted small">الكود</div><span className="code">{e.code}</span></div>
          <div><div className="muted small">الوظيفة</div><b>{e.job_title || "—"}</b></div>
          <div><div className="muted small">القسم</div><Chip color={e.department === "sales" ? "violet" : "gray"}>{DEPARTMENTS[e.department]}</Chip></div>
          <div><div className="muted small">الفرع</div><BranchName id={e.branch_id} /></div>
          <div><div className="muted small">المرتب</div><b><Money v={e.base_salary} /></b></div>
          {summary.data && <div><div className="muted small">باقي الإجازات</div><b className="num">{Number(summary.data.annual_leave_left)}</b> يوم</div>}
          {summary.data && Number(summary.data.advances_owed) > 0 &&
            <div><div className="muted small">سلف عليه</div><b className="danger-text"><Money v={summary.data.advances_owed} /></b></div>}
          {e.status === "left" && <Chip color="red">ساب الشغل {date(e.end_date)}</Chip>}
          <div className="end row wrap">
            {s.can("hr.write", e.branch_id) && <Btn icon="edit" onClick={() => setEditing(true)}>تعديل</Btn>}
            {s.can("hr.delete", e.branch_id) && <DeleteBtn small={false} path={`/employees/${id}`} what={`الموظف ${e.full_name}`}
              onDone={() => { invalidate("salespeople"); go("hr"); }}
              note="لو ليه مرتبات أو سلف أو مبيعات بيتعلم إنه ساب الشغل، ومرتباته ومبيعاته القديمة بتفضل باسمه." />}
          </div>
        </div>
      </Card>
      <Card flush>
        <Tabs value={tab} onChange={(t) => setQuery({ tab: t })} tabs={[
          { id: "info", label: "البيانات" }, { id: "entries", label: "حوافز وخصومات وسلف" }, { id: "leaves", label: "الإجازات" },
          { id: "payslips", label: "المرتبات" }, { id: "sales", label: "المبيعات" },
        ]} />
        <div className="card-b">
          {tab === "info" && <KV items={[
            ["التليفون", <span className="num">{e.phone ?? "—"}</span>], ["الرقم القومي", <span className="num">{e.national_id ?? "—"}</span>],
            ["العنوان", e.address ?? "—"], ["تاريخ التعيين", <span className="num">{date(e.hire_date)}</span>],
            ["رصيد الإجازات السنوي", `${Number(e.annual_leave_days)} يوم`], ["ملاحظات", e.notes || "—"],
          ]} />}
          {tab === "entries" && <Entries emp={e} onChange={summary.reload} />}
          {tab === "leaves" && <Leaves emp={e} onChange={summary.reload} />}
          {tab === "payslips" && <Payslips id={id} />}
          {tab === "sales" && <Sales id={id} />}
        </div>
      </Card>
      {editing && <EmployeeForm employee={e} onClose={() => setEditing(false)} onSaved={(x) => emp.set(x)} />}
    </div>
  );
}

function Entries({ emp, onChange }: { emp: Emp; onChange: () => void }) {
  const s = useSession();
  const list = useLoad(() => api.get<Entry[]>(`/employees/${emp.id}/entries`), [emp.id]);
  const [adding, setAdding] = useState<string | null>(null);
  const reload = () => { list.reload(); onChange(); };
  const create = s.can("hr.create", emp.branch_id);
  return (
    <div className="col">
      <PageHead>{create && <>
        <Btn kind="success" icon="plus" onClick={() => setAdding("bonus")}>حافز</Btn>
        <Btn kind="danger" icon="plus" onClick={() => setAdding("deduction")}>خصم</Btn>
        {s.can("treasury.create") && <Btn icon="cash" onClick={() => setAdding("advance")}>سلفة</Btn>}</>}
      </PageHead>
      <Table rows={list.data} loading={list.loading} empty="مفيش حركات" columns={[
        { key: "k", label: "النوع", render: (x) => <Chip color={ENTRY_KINDS[x.kind]?.[1]}>{ENTRY_KINDS[x.kind]?.[0] ?? x.kind}</Chip> },
        { key: "d", label: "التاريخ", render: (x) => <span className="num">{date(x.entry_date)}</span> },
        { key: "m", label: "على مرتب شهر", render: (x) => <span className="num">{x.month}</span> },
        { key: "a", label: "المبلغ", num: true, render: (x) => <b><Money v={x.amount} /></b> },
        { key: "r", label: "السلفة", render: (x) => x.kind === "advance" ? <span className="small">اتسدد <Money v={x.repaid} /> · قسط <Money v={x.installment} /></span> : "" },
        { key: "n", label: "ملاحظة", render: (x) => <span className="small muted">{x.note}</span> },
        { key: "p", label: "", render: (x) => x.payslip_id ? <Chip color="green">اتصرف</Chip> : null },
        { key: "x", label: "", width: 80, render: (x) => x.kind !== "advance" && !x.payslip_id && s.can("hr.delete", emp.branch_id) &&
          <DeleteBtn path={`/employee-entries/${x.id}`} what={`ال${ENTRY_KINDS[x.kind]?.[0]}`} onDone={reload} /> },
      ]} />
      <div className="muted small">السلفة بتتصرف من الخزينة دلوقتي وبتتخصم من المرتبات على أقساط. لإلغاء سلفة: اعكس حركة صرفها من الخزينة.</div>
      {adding && <EntryForm emp={emp} kind={adding} onClose={() => setAdding(null)} onSaved={reload} />}
    </div>
  );
}

function EntryForm({ emp, kind, onClose, onSaved }: { emp: Emp; kind: string; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState({ amount: "", entry_date: today(), month: thisMonth(), installment: "", cashbox_id: "", note: "" });
  const set = (k: keyof typeof d) => (v: string) => setD((x) => ({ ...x, [k]: v }));
  const advance = kind === "advance";
  return (
    <Modal title={`${ENTRY_KINDS[kind][0]} · ${emp.full_name}`} onClose={onClose} footer={<><Btn kind="primary" busy={busy}
      disabled={!Number(d.amount) || (advance && !d.cashbox_id)} onClick={() => run(async () => {
        await api.post("/employee-entries", { employee_id: emp.id, kind, amount: d.amount, entry_date: d.entry_date || null,
          month: d.month || null, note: d.note, ...(advance ? { installment: d.installment || null, cashbox_id: d.cashbox_id } : {}) });
        toast.ok(advance ? "اتصرفت السلفة من الخزينة." : "اتسجل.");
        onSaved(); onClose();
      })}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2">
        <Field label="المبلغ"><NumIn value={d.amount} onChange={set("amount")} autoFocus /></Field>
        <Field label="التاريخ"><input type="date" className="input" value={d.entry_date} onChange={(e) => set("entry_date")(e.target.value)} /></Field>
        <Field label={advance ? "أول قسط من مرتب شهر" : "على مرتب شهر"}><input type="month" className="input" value={d.month}
          onChange={(e) => set("month")(e.target.value)} /></Field>
        {advance && <Field label="القسط الشهري" hint="فاضي = تتخصم كلها من أول مرتب"><NumIn value={d.installment} onChange={set("installment")} /></Field>}
        {advance && <Field label="تتصرف من خزينة" className="span-all"><CashboxSelect value={d.cashbox_id} onChange={set("cashbox_id")} /></Field>}
        <Field label="ملاحظة" className="span-all"><TextIn value={d.note} onChange={set("note")} /></Field>
      </div>
    </Modal>
  );
}

function Leaves({ emp, onChange }: { emp: Emp; onChange: () => void }) {
  const s = useSession();
  const toast = useToast();
  const { run } = useAction(toast.err);
  const list = useLoad(() => api.get<Leave[]>(`/employees/${emp.id}/leaves`), [emp.id]);
  const [adding, setAdding] = useState(false);
  const reload = () => { list.reload(); onChange(); };
  const decide = (l: Leave, status: string) => run(async () => { await api.patch(`/employee-leaves/${l.id}`, { version: l.version, status }); reload(); });
  return (
    <div className="col">
      <PageHead>{s.can("hr.create", emp.branch_id) && <Btn kind="primary" icon="plus" onClick={() => setAdding(true)}>إجازة</Btn>}</PageHead>
      <Table rows={list.data} loading={list.loading} empty="مفيش إجازات" columns={[
        { key: "k", label: "النوع", render: (l) => LEAVE_KINDS[l.kind] ?? l.kind },
        { key: "f", label: "من", render: (l) => <span className="num">{date(l.start_date)}</span> },
        { key: "t", label: "لحد", render: (l) => <span className="num">{date(l.end_date)}</span> },
        { key: "d", label: "الأيام", num: true, render: (l) => <span className="num">{Number(l.days)}</span> },
        { key: "s", label: "الحالة", render: (l) => <Chip color={LEAVE_STATUS[l.status]?.[1]}>{LEAVE_STATUS[l.status]?.[0] ?? l.status}</Chip> },
        { key: "n", label: "ملاحظة", render: (l) => <span className="small muted">{l.note}</span> },
        { key: "a", label: "", render: (l) => <div className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
          {l.status === "requested" && s.can("hr.write", emp.branch_id) && <>
            <Btn small kind="success" onClick={() => decide(l, "approved")}>موافقة</Btn>
            <Btn small kind="danger" onClick={() => decide(l, "rejected")}>رفض</Btn></>}
          {s.can("hr.delete", emp.branch_id) && <DeleteBtn path={`/employee-leaves/${l.id}`} what="الإجازة" onDone={reload} />}</div> },
      ]} />
      <div className="muted small">الإجازة «من غير مرتب» بتتخصم من مرتب الشهر (المرتب ÷ 30 × الأيام).</div>
      {adding && <LeaveForm emp={emp} onClose={() => setAdding(false)} onSaved={reload} />}
    </div>
  );
}

function LeaveForm({ emp, onClose, onSaved }: { emp: Emp; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState({ kind: "annual", start_date: today(), end_date: today(), days: "", status: "approved", note: "" });
  const set = (k: keyof typeof d) => (v: string) => setD((x) => ({ ...x, [k]: v }));
  const span = d.start_date && d.end_date ? (Date.parse(d.end_date) - Date.parse(d.start_date)) / 86400000 + 1 : 0;
  return (
    <Modal title={`إجازة · ${emp.full_name}`} onClose={onClose} footer={<><Btn kind="primary" busy={busy} disabled={span < 1}
      onClick={() => run(async () => {
        await api.post("/employee-leaves", { employee_id: emp.id, ...d, days: d.days || null });
        onSaved(); onClose();
      })}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2">
        <Field label="النوع"><Select value={d.kind} onChange={set("kind")} options={Object.entries(LEAVE_KINDS).map(([value, label]) => ({ value, label }))} /></Field>
        <Field label="الحالة"><Select value={d.status} onChange={set("status")}
          options={Object.entries(LEAVE_STATUS).map(([value, [label]]) => ({ value, label }))} /></Field>
        <Field label="من"><input type="date" className="input" value={d.start_date} onChange={(e) => set("start_date")(e.target.value)} /></Field>
        <Field label="لحد"><input type="date" className="input" value={d.end_date} onChange={(e) => set("end_date")(e.target.value)} /></Field>
        <Field label="عدد الأيام" hint={span > 0 ? `فاضي = ${span} يوم` : ""}><NumIn value={d.days} onChange={set("days")} /></Field>
        <Field label="ملاحظة"><TextIn value={d.note} onChange={set("note")} /></Field>
      </div>
    </Modal>
  );
}

const SLIP_COLUMNS = [
  { key: "b", label: "الأساسي", num: true, render: (p: S<"PayslipOut">) => <Money v={p.base_salary} /> },
  { key: "bo", label: "حوافز", num: true, render: (p: S<"PayslipOut">) => <span className="success-text"><Money v={p.bonuses} /></span> },
  { key: "de", label: "خصومات", num: true, render: (p: S<"PayslipOut">) => <span className="danger-text"><Money v={p.deductions} /></span> },
  { key: "lv", label: "إجازة من غير مرتب", num: true, render: (p: S<"PayslipOut">) => Number(p.unpaid_leave_days)
    ? <span className="danger-text">{Number(p.unpaid_leave_days)} يوم · <Money v={p.unpaid_leave_deduction} /></span> : <span className="faint">—</span> },
  { key: "ad", label: "قسط سلفة", num: true, render: (p: S<"PayslipOut">) => <Money v={p.advance_repayment} /> },
  { key: "n", label: "الصافي", num: true, render: (p: S<"PayslipOut">) => <b><Money v={p.net} /></b> },
];

function Payslips({ id }: { id: string }) {
  const list = useLoad(() => api.get<S<"PayslipOut">[]>(`/employees/${id}/payslips`), [id]);
  return <Table rows={list.data} loading={list.loading} empty="مفيش مرتبات اتصرفت" columns={[
    { key: "m", label: "الشهر", render: (p) => <span className="num bold">{p.month}</span> }, ...SLIP_COLUMNS]} />;
}

type SalesData = { year: number; quotations: { count: number; accepted: number; accepted_total: string };
  work_orders: { count: number; total: string; paid: string }; invoices: { count: number; total: string };
  orders: { id: string; number: string; customer: string; stage: string; total: string; paid: string; date: string }[];
  quotes: { id: string; number: string; customer: string; status: string; total: string; date: string }[] };

function Sales({ id }: { id: string }) {
  const [year, setYear] = useState(new Date().getFullYear());
  const d = useLoad(() => api.get<SalesData>(`/employees/${id}/sales`, { year }), [id, year]);
  const x = d.data;
  return (
    <div className="col">
      <PageHead title={`مبيعات ${year}`}>
        <Btn small onClick={() => setYear(year - 1)}>{year - 1}</Btn>
        {year < new Date().getFullYear() && <Btn small onClick={() => setYear(year + 1)}>{year + 1}</Btn>}
      </PageHead>
      {!x ? <Loading /> : <>
        <div className="grid g4">
          <div className="card kpi"><div className="label">عروض الأسعار</div><div className="value">{x.quotations.count}</div></div>
          <div className="card kpi"><div className="label">اتقبل منها</div><div className="value">{x.quotations.accepted} · <Money v={x.quotations.accepted_total} /></div></div>
          <div className="card kpi"><div className="label">أوامر التصنيع</div><div className="value"><Money v={x.work_orders.total} /></div></div>
          <div className="card kpi"><div className="label">الفواتير الصادرة</div><div className="value"><Money v={x.invoices.total} /></div></div>
        </div>
        <h4 style={{ margin: "8px 0 0" }}>أوامر التصنيع</h4>
        <Table rows={x.orders} onRow={(o) => go(`work-orders/${o.id}`)} empty="مفيش أوامر" columns={[
          { key: "n", label: "الرقم", render: (o) => <span className="num bold">{o.number}</span> },
          { key: "c", label: "العميل", render: (o) => o.customer },
          { key: "d", label: "التاريخ", render: (o) => <span className="num">{date(o.date)}</span> },
          { key: "s", label: "المرحلة", render: (o) => STAGE_NAMES[o.stage] ?? o.stage },
          { key: "t", label: "الإجمالي", num: true, render: (o) => <Money v={o.total} /> },
          { key: "p", label: "المدفوع", num: true, render: (o) => <Money v={o.paid} /> },
        ]} />
        <h4 style={{ margin: "8px 0 0" }}>عروض الأسعار</h4>
        <Table rows={x.quotes} onRow={(q) => go(`quotations/${q.id}`)} empty="مفيش عروض" columns={[
          { key: "n", label: "الرقم", render: (q) => <span className="num bold">{q.number}</span> },
          { key: "c", label: "العميل", render: (q) => q.customer },
          { key: "d", label: "التاريخ", render: (q) => <span className="num">{date(q.date)}</span> },
          { key: "s", label: "الحالة", render: (q) => <Chip color={QUOTE_STATUS[q.status]?.[1]}>{QUOTE_STATUS[q.status]?.[0] ?? q.status}</Chip> },
          { key: "t", label: "الإجمالي", num: true, render: (q) => <Money v={q.total} /> },
        ]} />
      </>}
    </div>
  );
}

// ---------------------------------------------------------------- payroll
function Payroll() {
  const s = useSession();
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const list = useLoad(() => api.get<S<"Page_RunOut_">>("/payroll-runs", { limit: 50, offset }), [offset]);
  if (open) return <RunDetail id={open} onBack={() => { setOpen(null); list.reload(); }} />;
  return (
    <div className="col">
      <PageHead>{s.can("hr.payroll") && <Btn kind="primary" icon="plus" onClick={() => setCreating(true)}>كشف مرتبات</Btn>}</PageHead>
      <Table rows={list.data?.items} loading={list.loading} onRow={(r) => setOpen(r.id)} empty="مفيش كشوف مرتبات" columns={[
        { key: "n", label: "الرقم", render: (r) => <span className="num bold">{r.number}</span> },
        { key: "m", label: "الشهر", render: (r) => <span className="num">{r.month}</span> },
        { key: "b", label: "الفرع", render: (r) => <BranchName id={r.branch_id} /> },
        { key: "s", label: "الحالة", render: (r) => r.status === "paid" ? <Chip color="green">اتصرف</Chip> : <Chip>مسودة</Chip> },
        { key: "t", label: "الإجمالي", num: true, render: (r) => <b><Money v={r.total} /></b> },
      ]} />
      {list.data && <Pager total={list.data.total} limit={50} offset={offset} onChange={setOffset} />}
      {creating && <NewRun onClose={() => setCreating(false)} onSaved={(r) => setOpen(r.id)} />}
    </div>
  );
}

function NewRun({ onClose, onSaved }: { onClose: () => void; onSaved: (r: Run) => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const branch = useDefaultBranch("hr.payroll");
  const [d, setD] = useState({ month: thisMonth(), branch_id: branch ?? "" });
  return (
    <Modal title="كشف مرتبات جديد" onClose={onClose} footer={<><Btn kind="primary" busy={busy} disabled={!d.month || !d.branch_id}
      onClick={() => run(async () => { onSaved(await api.post<Run>("/payroll-runs", d)); onClose(); })}>عمل الكشف</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col">
        <Field label="الشهر"><input type="month" className="input" value={d.month} onChange={(e) => setD((x) => ({ ...x, month: e.target.value }))} /></Field>
        <Field label="الفرع"><BranchSelect value={d.branch_id} onChange={(v) => setD((x) => ({ ...x, branch_id: v }))} perm="hr.payroll" /></Field>
        <div className="muted small">الكشف بيتحسب لكل موظفين الفرع: المرتب + الحوافز − الخصومات − الإجازات من غير مرتب − قسط السلفة.</div>
      </div>
    </Modal>
  );
}

function RunDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const r = useLoad(() => api.get<Run>(`/payroll-runs/${id}`), [id]);
  const [paying, setPaying] = useState(false);
  const [box, setBox] = useState("");
  if (r.error) return <ErrorBox text={r.error} onRetry={r.reload} />;
  if (!r.data) return <Loading />;
  const x = r.data;
  const draft = x.status === "draft";
  return (
    <div className="col">
      <PageHead title={`كشف مرتبات ${x.month} · ${x.number}`}>
        <Btn onClick={onBack}>رجوع</Btn>
        {draft && s.can("hr.payroll", x.branch_id) && <>
          <Btn icon="refresh" busy={busy} onClick={() => run(async () => { r.set(await api.post<Run>(`/payroll-runs/${id}/recalculate`)); })}>إعادة حساب</Btn>
          {s.can("treasury.create") && <Btn kind="success" icon="cash" onClick={() => setPaying(true)}>صرف المرتبات</Btn>}
          <DeleteBtn small={false} path={`/payroll-runs/${id}`} what={`كشف ${x.month}`} onDone={onBack} /></>}
        {!draft && <Chip color="green">اتصرف {date(String(x.paid_at ?? ""))}</Chip>}
      </PageHead>
      <Table rows={x.payslips} rowKey={(p) => p.id} empty="مفيش موظفين في الفرع ده" columns={[
        { key: "e", label: "الموظف", render: (p) => <a style={{ cursor: "pointer" }} onClick={() => go(`hr/${p.employee_id}`)}><b>{p.employee_name}</b></a> },
        { key: "j", label: "الوظيفة", render: (p) => <span className="small muted">{p.job_title}</span> },
        ...SLIP_COLUMNS,
      ]} />
      <div className="row"><span className="end">إجمالي الصافي: <b><Money v={x.total} cur /></b></span></div>
      {paying && (
        <Modal title={`صرف مرتبات ${x.month}`} onClose={() => setPaying(false)} footer={<><Btn kind="success" busy={busy} disabled={!box}
          onClick={() => run(async () => {
            r.set(await api.post<Run>(`/payroll-runs/${id}/pay`, { version: x.version, cashbox_id: box }));
            setPaying(false); toast.ok("اتصرفت المرتبات واتقفل الكشف.");
          })}>صرف <Money v={x.total} /></Btn><Btn onClick={() => setPaying(false)}>رجوع</Btn></>}>
          <div className="col">
            <Field label="من خزينة"><CashboxSelect value={box} onChange={setBox} /></Field>
            <div className="muted small">كل موظف بتتعمل له حركة صرف باسمه، وأقساط السلف بتتخصم، والكشف بيتقفل.</div>
          </div>
        </Modal>
      )}
    </div>
  );
}
