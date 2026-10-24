import { useState } from "react";
import { api, ApiError, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad } from "../lib/hooks";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, ErrorBox, FilePick, KV, Loading, PageHead, Pager, Table, Tabs } from "../components/ui";
import { setQuery } from "../lib/router";
import { date, dateTime } from "../lib/format";

export default function System({ route }: PageProps) {
  useTitle("الترخيص والنسخ الاحتياطي");
  const s = useSession();
  const tab = route.query.tab ?? "license";
  return (
    <Card flush>
      <Tabs value={tab} onChange={(t) => setQuery({ tab: t })} tabs={[
        { id: "license", label: "الترخيص", hidden: s.isPlatform }, { id: "backups", label: "النسخ الاحتياطي" },
        { id: "devices", label: "الأجهزة", hidden: s.isPlatform }, { id: "audit", label: "سجل التعديلات", hidden: !s.can("audit.read") },
        { id: "privacy", label: "سجل الوصول للبيانات الشخصية", hidden: !s.can("privacy.manage") },
      ]} />
      <div className="card-b">
        {tab === "license" && <License />}
        {tab === "backups" && <Backups />}
        {tab === "devices" && <Devices />}
        {tab === "audit" && <Audit />}
        {tab === "privacy" && <AccessLog />}
      </div>
    </Card>
  );
}

const LIC_STATUS: Record<string, [string, "green" | "amber" | "red" | "gray"]> = {
  valid: ["ساري", "green"], grace: ["فترة سماح", "amber"], expired: ["منتهي", "red"], missing: ["مفيش ترخيص", "red"], invalid: ["غير صالح", "red"],
};

function License() {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const lic = s.license;
  const offline = s.info.mode === "offline";
  const copy = () => { navigator.clipboard?.writeText(lic.machine_fingerprint ?? ""); toast.ok("اتنسخت بصمة الجهاز."); };
  return (
    <div className="grid g2" style={{ alignItems: "start" }}>
      <div className="col">
        <KV items={[
          ["الحالة", <Chip color={LIC_STATUS[lic.status]?.[1] ?? "gray"}>{LIC_STATUS[lic.status]?.[0] ?? lic.status}</Chip>],
          ["نوع النسخة", offline ? "أوفلاين (سيرفر في المصنع)" : "أونلاين (سحابي)"],
          ["ينتهي", <span className="num">{date(lic.expires_at)}</span>],
          ["الأجهزة", <span className="num">{lic.max_devices ?? "—"}</span>],
          ["المستخدمين", <span className="num">{lic.max_users ?? "—"}</span>],
          ["الفروع", <span className="num">{lic.max_branches ?? "—"}</span>],
          ["الأجزاء المرخصة", <div className="row wrap" style={{ gap: 4 }}>{lic.modules.map((m) => <Chip key={m} color="blue">{lic.module_names[m] ?? m}</Chip>)}</div>],
          ["إصدار السيرفر", <span className="num">v{s.info.version}</span>],
        ]} />
        {lic.reason && <div className="notice warn">{lic.reason}</div>}
      </div>
      {offline && s.can("system.manage") && (
        <div className="col">
          <div className="card" style={{ padding: 14 }}>
            <b>بصمة الجهاز (السيرفر)</b>
            <p className="muted small">ابعت البصمة دي لـ MYTech عشان يعملولك ملف الترخيص للجهاز ده.</p>
            <div className="row"><span className="code grow" style={{ wordBreak: "break-all", padding: 8 }}>{lic.machine_fingerprint}</span><Btn small icon="copy" onClick={copy}>نسخ</Btn></div>
          </div>
          <div className="card" style={{ padding: 14 }}>
            <b>تركيب ملف الترخيص</b>
            <p className="muted small">الملف الموقّع اللي وصلك من MYTech (license.json).</p>
            <FilePick accept=".json" busy={busy} onFile={(f) => run(async () => { await api.upload("/system/license", f); toast.ok("اتركب الترخيص."); await s.reload(); })}>اختار ملف الترخيص</FilePick>
          </div>
        </div>
      )}
    </div>
  );
}

type BackupMeta = { file: string; sha256: string; size: number; label: string; created_at: string };

function Backups() {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [blocked, setBlocked] = useState(false);
  const data = useLoad(() => api.get<{ last_status: any; backups: BackupMeta[]; directory: string; keep: number }>("/system/backups").catch((e) => {
    if (e instanceof ApiError && e.code === "PLATFORM_ONLY") { setBlocked(true); return null; }
    throw e;
  }), []);
  if (blocked) return <div className="notice info">النسخة السحابية: النسخ الاحتياطي اليومي بتعمله MYTech لكل الشركات. لو محتاج نسخة من بياناتك كلّم الدعم.</div>;
  if (data.error) return <ErrorBox text={data.error} onRetry={data.reload} />;
  if (!data.data) return <Loading />;
  const last = data.data.last_status;
  return (
    <div className="col">
      <PageHead title="النسخ الاحتياطي اليومي">
        <Btn kind="primary" icon="db" busy={busy} onClick={() => run(async () => { await api.post("/system/backups"); toast.ok("اتعملت نسخة احتياطية واتأكدنا منها."); data.reload(); })}>نسخة دلوقتي</Btn>
      </PageHead>
      {last && <div className={"notice " + (last.ok === false || last.error ? "err" : "ok")}>
        آخر نسخة: <span className="num">{dateTime(last.at ?? last.created_at)}</span> {last.error ? `· فشلت: ${last.error}` : "· تمام"}</div>}
      <div className="muted small">بتتحفظ في <span className="code">{data.data.directory}</span> وبيتساب آخر <span className="num">{data.data.keep}</span> نسخة. الاسترجاع بيتعمل من جهاز السيرفر بأداة الاسترجاع (شوف دليل التسطيب).</div>
      <Table rows={data.data.backups} rowKey={(b) => b.file} columns={[
        { key: "f", label: "الملف", render: (b) => <span className="code">{b.file}</span> },
        { key: "t", label: "الوقت", render: (b) => <span className="num">{dateTime(b.created_at)}</span> },
        { key: "l", label: "النوع", render: (b) => <Chip>{b.label === "daily" ? "يومي" : b.label === "manual" ? "يدوي" : b.label === "pre-update" ? "قبل تحديث" : b.label}</Chip> },
        { key: "s", label: "الحجم", num: true, render: (b) => <span className="num">{(b.size / 1048576).toFixed(1)} MB</span> },
      ]} empty="مفيش نسخ لسه" />
    </div>
  );
}

function Devices() {
  const s = useSession();
  const toast = useToast();
  const { run } = useAction(toast.err);
  const list = useLoad(() => api.get<S<"DeviceOut">[]>("/devices"), []);
  return (
    <div className="col">
      {s.license.max_devices && <div className="muted small">الترخيص: حتى <span className="num">{s.license.max_devices}</span> جهاز نشط.</div>}
      <Table rows={list.data} loading={list.loading} columns={[
        { key: "n", label: "الجهاز", render: (d) => <b>{d.name || d.device_key.slice(0, 8)}</b> },
        { key: "p", label: "النظام", render: (d) => d.platform },
        { key: "v", label: "الإصدار", render: (d) => <span className="num">{d.client_version || "—"}</span> },
        { key: "f", label: "أول دخول", render: (d) => <span className="num">{dateTime(d.first_seen_at)}</span> },
        { key: "l", label: "آخر ظهور", render: (d) => <span className="num">{dateTime(d.last_seen_at)}</span> },
        { key: "me", label: "", render: (d) => d.id === s.me.device_id && <Chip color="blue">الجهاز ده</Chip> },
        { key: "a", label: "", render: (d) => s.can("org.manage") && d.id !== s.me.device_id && (
          <Btn small kind={d.is_active ? "danger" : "success"} onClick={() => run(async () => { await api.patch(`/devices/${d.id}`, { is_active: !d.is_active }); list.reload(); })}>
            {d.is_active ? "إيقاف" : "تفعيل"}</Btn>) },
      ]} />
    </div>
  );
}

function Audit() {
  const [offset, setOffset] = useState(0);
  const list = useLoad(() => api.get<S<"Page_AuditOut_">>("/audit-log", { limit: 50, offset }), [offset]);
  return (
    <div className="col">
      {list.error && <ErrorBox text={list.error} />}
      <Table rows={list.data?.items} loading={list.loading} columns={[
        { key: "at", label: "الوقت", render: (a) => <span className="num">{dateTime(a.at)}</span> },
        { key: "e", label: "البيان", render: (a) => <span className="code">{a.entity}</span> },
        { key: "a", label: "العملية", render: (a) => <Chip color={a.action === "delete" ? "red" : a.action === "create" ? "green" : "blue"}>{
          { create: "إضافة", update: "تعديل", delete: "حذف" }[a.action] ?? a.action}</Chip> },
        { key: "c", label: "التغييرات", render: (a) => <span className="small muted ltr" style={{ display: "block", maxWidth: 520 }}>
          {Object.keys(a.changes ?? {}).join(", ")}{a.note ? ` · ${a.note}` : ""}</span> },
      ]} />
      {list.data && <Pager total={list.data.total} limit={50} offset={offset} onChange={setOffset} />}
    </div>
  );
}

function AccessLog() {
  const [offset, setOffset] = useState(0);
  const list = useLoad(() => api.get<S<"Page_AccessLogOut_">>("/privacy/access-log", { limit: 50, offset }), [offset]);
  return (
    <div className="col">
      <div className="muted small">كل مرة حد شاف أو صدّر أو عدّل أو مسح بيانات شخصية بتتسجل هنا (قانون 151 لسنة 2020).</div>
      {list.error && <ErrorBox text={list.error} />}
      <Table rows={list.data?.items} loading={list.loading} columns={[
        { key: "at", label: "الوقت", render: (a) => <span className="num">{dateTime(a.at)}</span> },
        { key: "t", label: "الشخص", render: (a) => ({ customer: "عميل", user: "مستخدم", supplier: "مورد" }[a.subject_type] ?? a.subject_type) },
        { key: "a", label: "العملية", render: (a) => ({ view: "عرض", export: "تصدير", update: "تعديل", erase: "مسح" }[a.action] ?? a.action) },
        { key: "f", label: "الحقول", render: (a) => <span className="small muted">{a.fields.join("، ")}</span> },
      ]} />
      {list.data && <Pager total={list.data.total} limit={50} offset={offset} onChange={setOffset} />}
    </div>
  );
}
