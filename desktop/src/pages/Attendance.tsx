// الحضور والانصراف: البصمات بتيجي لوحدها من جهاز البصمة (ZKTeco ADMS) — حضور كل يوم، أرقام مش متربطة بموظف، والأجهزة.
import { useEffect, useState } from "react";
import { api, type S } from "../api/client";
import { useAction, useLoad } from "../lib/hooks";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, ErrorBox, Field, Modal, PageHead, Table, TextIn } from "../components/ui";
import { go, setQuery, useRoute } from "../lib/router";
import { Money, NumIn, Select } from "../components/ui";
import { date, dateTime, today } from "../lib/format";

type Device = S<"FingerprintDeviceOut">;
type Devices = S<"FingerprintDevicesOut">;
type Day = S<"DayOut">;

const clock = (x: string) => x.slice(11, 16);
const hours = (a: string, b: string) => {
  const m = Math.round((new Date(b).getTime() - new Date(a).getTime()) / 60000);
  return m > 0 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}` : "—";
};

export function Attendance() {
  const route = useRoute();
  const [from, setFrom] = useState(today());
  const [to, setTo] = useState(today());
  const days = useLoad(() => api.get<Day[]>("/attendance/days", { date_from: from, date_to: to }), [from, to]);
  const unlinked = useLoad(() => api.get<S<"UnlinkedOut">[]>("/attendance/unlinked"), []);
  useEffect(() => {                                   // new punches arrive by themselves: refresh every half minute
    const t = setInterval(() => { days.reload(); unlinked.reload(); }, 30000);
    return () => clearInterval(t);
  }, [days.reload, unlinked.reload]);
  return (
    <div className="col" style={{ gap: 14 }}>
      <EmployeeMonth employee={route.query.employee ?? ""} month={route.query.month ?? today().slice(0, 7)} />
      <h3 style={{ margin: "6px 0 0" }}>الحضور يوم بيوم</h3>
      <PageHead>
        <Field label="من"><input type="date" className="input" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label="إلى"><input type="date" className="input" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        <Btn icon="refresh" onClick={() => { days.reload(); unlinked.reload(); }}>تحديث</Btn>
      </PageHead>
      {days.error && <ErrorBox text={days.error} onRetry={days.reload} />}
      {!!unlinked.data?.length && <div className="notice warn">
        أرقام على جهاز البصمة مش متربطة بموظف: <b className="num">{unlinked.data.map((u) => `${u.pin} (${u.punches} بصمة)`).join("، ")}</b>.
        افتح ملف الموظف ← تعديل ← «رقم البصمة» واكتب رقمه، وبصماته القديمة هتتربط بيه.</div>}
      <Table rows={days.data} loading={days.loading} empty="مفيش بصمات في المدة دي"
        onRow={(d) => d.employee_id && go(`hr/${d.employee_id}`)} columns={[
          { key: "d", label: "اليوم", render: (d) => <span className="num">{date(d.day)}</span> },
          { key: "n", label: "الموظف", render: (d) => d.employee_name ? <b>{d.employee_name}</b>
            : <span className="muted">رقم {d.pin} (مش متربط)</span> },
          { key: "p", label: "رقم البصمة", render: (d) => <span className="num">{d.pin}</span> },
          { key: "f", label: "الحضور", num: true, render: (d) => <b className="num">{clock(d.first)}</b> },
          { key: "l", label: "الانصراف", num: true, render: (d) => d.punches > 1 ? <b className="num">{clock(d.last)}</b>
            : <Chip color="amber">بصمة واحدة</Chip> },
          { key: "h", label: "المدة", num: true, render: (d) => <span className="num">{d.punches > 1 ? hours(d.first, d.last) : "—"}</span> },
          { key: "c", label: "عدد البصمات", num: true, render: (d) => <span className="num">{d.punches}</span> },
        ]} />
      <DevicesCard />
    </div>
  );
}

function DevicesCard() {
  const s = useSession();
  const toast = useToast();
  const { run } = useAction(toast.err);
  const list = useLoad(() => api.get<Devices>("/attendance/devices"), []);
  const [adding, setAdding] = useState(false);
  const toggle = (d: Device) => run(async () => {
    await api.patch(`/attendance/devices/${d.id}`, { version: d.version, is_active: !d.is_active });
    list.reload();
  });
  const addr = list.data?.server_addresses?.[0] ?? "عنوان جهاز السيرفر";
  return (
    <Card title="أجهزة البصمة" actions={s.can("hr.write") && <Btn small icon="plus" onClick={() => setAdding(true)}>إضافة جهاز</Btn>}>
      {list.error && <ErrorBox text={list.error} onRetry={list.reload} />}
      <Table rows={list.data?.devices} loading={list.loading} empty="مفيش أجهزة لسه: دوس «إضافة جهاز»" columns={[
        { key: "n", label: "الجهاز", render: (d) => <b>{d.name}</b> },
        { key: "s", label: "الرقم التسلسلي", render: (d) => <span className="code">{d.serial}</span> },
        { key: "o", label: "الحالة", render: (d) => !d.is_active ? <Chip>متوقف</Chip>
          : d.online ? <Chip color="green">متصل</Chip> : <Chip color={d.last_seen_at ? "red" : "amber"}>{d.last_seen_at ? "مش متصل" : "لسه مااتصلش"}</Chip> },
        { key: "l", label: "آخر اتصال", render: (d) => <span className="num">{d.last_seen_at ? dateTime(d.last_seen_at) : "—"}</span> },
        { key: "p", label: "آخر بصمة", render: (d) => <span className="num">{d.last_punch_at ? `${date(d.last_punch_at)} ${clock(d.last_punch_at)}` : "—"}</span> },
        { key: "c", label: "البصمات", num: true, render: (d) => <span className="num">{d.punches}</span> },
        { key: "a", label: "", render: (d) => s.can("hr.write") && <Btn small onClick={() => toggle(d)}>{d.is_active ? "إيقاف" : "تشغيل"}</Btn> },
      ]} />
      <div className="notice" style={{ marginTop: 10, background: "var(--primary-soft)" }}>
        <b>ضبط الجهاز (مرة واحدة):</b> من قائمة الجهاز ← <b>COMM</b> ← <b>Cloud Server Setting</b> (أو ADMS):
        <ul style={{ margin: "6px 0" }}>
          <li>Server Address: <b className="num" dir="ltr">{addr}</b>{(list.data?.server_addresses?.length ?? 0) > 1 &&
            <span className="muted"> (أو: <span className="num" dir="ltr">{list.data!.server_addresses.slice(1).join("، ")}</span>)</span>}</li>
          <li>Server Port: <b className="num">{list.data?.server_port ?? 8000}</b></li>
          <li>Enable Domain Name: <b>{list.data?.server_domain ? "ON" : "OFF"}</b> · Enable Proxy Server: <b>OFF</b> ·
            HTTPS: <b>{list.data?.server_https ? "ON" : "OFF"}</b></li>
        </ul>
        {list.data?.server_domain ? "الجهاز لازم يكون متوصل بإنترنت المصنع (السيرفر على السحابة)."
          : "الجهاز لازم يكون متوصل بنفس شبكة جهاز السيرفر، وجهاز السيرفر ياخد IP ثابت."} الرقم التسلسلي (SN) مكتوب على ظهر الجهاز
        أو في القائمة ← <b>System Info</b> ← <b>Device Info</b>. أول ما يتصل بيبعت كل البصمات اللي عليه، ولو الشبكة وقعت بيحتفظ بيها ويبعتها بعدين.
      </div>
      {adding && <AddDevice onClose={() => setAdding(false)} onSaved={list.reload} />}
    </Card>
  );
}

function AddDevice({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [serial, setSerial] = useState("");
  const [name, setName] = useState("");
  const ok = /^[A-Za-z0-9_-]{4,40}$/.test(serial.trim());
  const save = () => run(async () => {
    await api.post("/attendance/devices", { serial: serial.trim(), name: name.trim() });
    toast.ok("اتضاف الجهاز. اضبط عنوان السيرفر على الجهاز، وهيظهر «متصل» في خلال دقيقة.");
    onSaved();
    onClose();
  });
  return (
    <Modal title="إضافة جهاز بصمة" onClose={onClose} footer={<><Btn kind="primary" busy={busy} disabled={!ok} onClick={save}>إضافة</Btn>
      <Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col">
        <Field label="الرقم التسلسلي (SN)" hint="على ظهر الجهاز، أو القائمة ← System Info ← Device Info">
          <TextIn value={serial} onChange={setSerial} code autoFocus /></Field>
        <Field label="اسم الجهاز" hint="مثلًا: بوابة المصنع"><TextIn value={name} onChange={setName} /></Field>
      </div>
    </Modal>
  );
}


// ---------------------------------------------------------------- مراجعة شهر موظف
type MonthDay = { day: string; kind: string; first: string | null; last: string | null; punches: number; late: number;
  overtime: number; deduct_days: string; deduct_minutes: number; extra: string; flags: string[];
  mark: null | { version: number; kind: string | null; excuse: string; permission_minutes: number; start_source: string | null;
    note: string; manual_in: string | null; manual_out: string | null } };
type Month = { days: MonthDay[]; present_days: string; absent_days: string; late_minutes: number; attendance_deduction: string;
  overtime_minutes: number; overtime_amount: string; allowances: string; review_days: number; day_pay: string;
  collections: string; commission: string; commission_min: string };

const KINDS: Record<string, [string, "gray" | "green" | "amber" | "red" | "blue" | "violet"]> = {
  normal: ["عادي", "gray"], install: ["تركيب", "blue"], travel: ["سفر", "violet"], off: ["إجازة", "green"],
  leave: ["إجازة متسجلة", "green"], absent: ["غياب", "red"], excused: ["معذور", "amber"], not_counted: ["مش محسوب", "gray"] };
const EXCUSES: Record<string, string> = { none: "مفيش", permission: "إذن", notified: "غياب بتبليغ", excused: "معذور (مايتخصمش)" };
const WEEK = ["الاتنين", "التلات", "الأربع", "الخميس", "الجمعة", "السبت", "الحد"];

function EmployeeMonth({ employee, month }: { employee: string; month: string }) {
  const people = useLoad(() => api.get<S<"Page_EmployeeOut_">>("/employees", { status: "active", limit: 500 })
    .then((p) => p.items.filter((e) => e.pay_policy_id)), []);
  const data = useLoad(() => employee ? api.get<Month>("/attendance/month", { employee_id: employee, month }) : Promise.resolve(null),
    [employee, month]);
  const [edit, setEdit] = useState<MonthDay | null>(null);
  const m = data.data;
  return (
    <Card title="مراجعة شهر موظف" actions={<div className="row" style={{ gap: 8 }}>
      <div style={{ width: 220 }}><Select value={employee} onChange={(v) => setQuery({ employee: v || undefined, month })}
        placeholder="اختار موظف (ليه سياسة مرتب)…" options={(people.data ?? []).map((e) => ({ value: e.id, label: e.full_name }))} /></div>
      <input type="month" className="input" style={{ width: 150 }} value={month} onChange={(e) => setQuery({ employee: employee || undefined, month: e.target.value })} />
    </div>}>
      {data.error && <ErrorBox text={data.error} onRetry={data.reload} />}
      {!employee && <div className="muted small">اختار موظف عشان تشوف شهره يوم بيوم: الحضور، التأخير، الغياب، الأوفر تايم، السفر، واللي محتاج مراجعة. دوس على أي يوم عشان تعدّله.</div>}
      {m && <>
        <div className="row wrap" style={{ gap: 14, marginBottom: 10 }}>
          <span>حضور <b className="num">{Number(m.present_days)}</b> يوم</span>
          <span>غياب <b className="num">{Number(m.absent_days)}</b></span>
          <span>تأخير <b className="num">{m.late_minutes}</b> دقيقة</span>
          <span>خصم الغياب والتأخير <b className="danger-text"><Money v={m.attendance_deduction} /></b></span>
          <span>أوفر تايم <b className="num">{Math.round(m.overtime_minutes / 6) / 10}</b> ساعة = <b><Money v={m.overtime_amount} /></b></span>
          <span>سفر وبدلات <b><Money v={m.allowances} /></b></span>
          {Number(m.collections) > 0 && <span>التحصيل <b><Money v={m.collections} /></b> · العمولة <b><Money v={m.commission} /></b>
            {Number(m.commission) === 0 && <span className="muted small"> (أقل من <Money v={m.commission_min} />)</span>}</span>}
          {m.review_days > 0 && <Chip color="amber">{m.review_days} يوم محتاج مراجعة</Chip>}
        </div>
        <Table rows={m.days.filter((d) => d.kind !== "not_counted")} rowKey={(d) => d.day} onRow={(d) => setEdit(d)} empty="مفيش أيام محسوبة (الموظف لسه مابصمش)" columns={[
          { key: "d", label: "اليوم", render: (d) => <span className="num">{WEEK[(new Date(d.day).getDay() + 6) % 7]} {date(d.day)}</span> },
          { key: "k", label: "النوع", render: (d) => <Chip color={KINDS[d.kind]?.[1]}>{KINDS[d.kind]?.[0] ?? d.kind}</Chip> },
          { key: "i", label: "الحضور", num: true, render: (d) => <span className="num">{d.first ? clock(d.first) : "—"}</span> },
          { key: "o", label: "الانصراف", num: true, render: (d) => <span className="num">{d.last ? clock(d.last) : "—"}</span> },
          { key: "l", label: "تأخير", num: true, render: (d) => d.late ? <span className="num">{d.late} د</span> : "" },
          { key: "x", label: "الخصم", num: true, render: (d) => <span className="danger-text num">{Number(d.deduct_days) ? `${Number(d.deduct_days)} يوم` : ""}
            {d.deduct_minutes ? ` ${d.deduct_minutes} د` : ""}</span> },
          { key: "t", label: "أوفر تايم", num: true, render: (d) => d.overtime ? <span className="num">{d.overtime} د</span> : "" },
          { key: "e", label: "إضافة", num: true, render: (d) => Number(d.extra) ? <Money v={d.extra} /> : "" },
          { key: "m", label: "ملاحظات", render: (d) => <span className="small">{d.flags.map((f, i) => <Chip key={i} color="amber">{f}</Chip>)}
            {d.mark && d.mark.excuse !== "none" && <Chip>{EXCUSES[d.mark.excuse]}{d.mark.excuse === "permission" ? ` ${d.mark.permission_minutes} د` : ""}</Chip>}
            {d.mark?.note && <span className="muted"> {d.mark.note}</span>}</span> },
        ]} />
      </>}
      {edit && <DayForm employee={employee} d={edit} onClose={() => setEdit(null)} onSaved={data.reload} />}
    </Card>
  );
}

function DayForm({ employee, d, onClose, onSaved }: { employee: string; d: MonthDay; onClose: () => void; onSaved: () => void }) {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const m = d.mark;
  const full = s.can("hr.write");
  const [v, setV] = useState({ kind: m?.kind ?? "", excuse: m?.excuse ?? "none", permission_minutes: String(m?.permission_minutes ?? 0),
    manual_in: m?.manual_in ?? "", manual_out: m?.manual_out ?? "", start_source: m?.start_source ?? "", note: m?.note ?? "" });
  const set = (k: keyof typeof v) => (x: string) => setV((y) => ({ ...y, [k]: x }));
  const save = () => run(async () => {
    await api.put(`/attendance/days/${employee}/${d.day}`, { kind: v.kind || null, excuse: v.excuse,
      permission_minutes: Number(v.permission_minutes) || 0, manual_in: v.manual_in || null, manual_out: v.manual_out || null,
      start_source: v.start_source || null, note: v.note, version: m?.version ?? null });
    toast.ok("اتحفظ. إعادة حساب كشف المرتبات بتطبقه.");
    onSaved(); onClose();
  });
  const twoStarts = d.flags.some((f) => f.includes("بصمتين")) || !!m?.start_source;
  return (
    <Modal title={`يوم ${date(d.day)}`} onClose={onClose} footer={<><Btn kind="primary" busy={busy} onClick={save}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2">
        {full && <>
          <Field label="نوع اليوم" hint="فاضي = حسب السيستم (مهام التركيب والمناطق والإجازات)"><Select value={v.kind} onChange={set("kind")} placeholder="أوتوماتيك"
            options={[{ value: "normal", label: "عادي" }, { value: "install", label: "تركيب" }, { value: "travel", label: "سفر" }, { value: "off", label: "إجازة" }]} /></Field>
          <Field label="عذر"><Select value={v.excuse} onChange={set("excuse")} options={Object.entries(EXCUSES).map(([value, label]) => ({ value, label }))} /></Field>
          {v.excuse === "permission" && <Field label="مدة الإذن (دقيقة)"><NumIn value={v.permission_minutes} onChange={set("permission_minutes")} /></Field>}
          <Field label="حضور بالإيد" hint="لو مابصمش"><input type="time" className="input" value={v.manual_in} onChange={(e) => set("manual_in")(e.target.value)} /></Field>
          <Field label="انصراف بالإيد"><input type="time" className="input" value={v.manual_out} onChange={(e) => set("manual_out")(e.target.value)} /></Field>
        </>}
        {twoStarts && <Field label="بصمة بداية اليوم المعتمدة" className="span-all"><Select value={v.start_source} onChange={set("start_source")} placeholder="الأبدر"
          options={[{ value: "device", label: "جهاز البصمة" }, { value: "app", label: "الموبايل" }]} /></Field>}
        {full && <Field label="ملاحظة" className="span-all"><TextIn value={v.note} onChange={set("note")} /></Field>}
      </div>
    </Modal>
  );
}
