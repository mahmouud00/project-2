// الحضور والانصراف: البصمات بتيجي لوحدها من جهاز البصمة (ZKTeco ADMS) — حضور كل يوم، أرقام مش متربطة بموظف، والأجهزة.
import { useEffect, useState } from "react";
import { api, type S } from "../api/client";
import { useAction, useLoad } from "../lib/hooks";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, ErrorBox, Field, Modal, PageHead, Table, TextIn } from "../components/ui";
import { go } from "../lib/router";
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
