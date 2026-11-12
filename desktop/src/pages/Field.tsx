// الفنيين: jobs assigned to technicians (surveys, installations, maintenance), where each technician is now,
// and the link of the technicians' phone app (served by the same server, same data as this program).
import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api, store, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad } from "../lib/hooks";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, Confirm, Modal, PageHead, Select, Table, Tabs } from "../components/ui";
import { DeleteBtn } from "../components/actions";
import { PrintPreview } from "../components/media";
import { AssignJob, MapBtn, mapUrl, openMap } from "../components/field";
import { watchPosition, type Fix } from "../lib/geo";
import { CustomerName } from "../components/pickers";
import { JOB_KINDS, JOB_STATUS } from "../lib/lookups";
import { go, setQuery } from "../lib/router";
import { dateTime, today } from "../lib/format";

type Job = S<"JobOut">;
type Tech = S<"TechnicianOut">;

export default function FieldPage({ route }: PageProps) {
  const s = useSession();
  if (!s.can("field.read") && !s.can("field.manage") && s.can("field.self")) return <MyJobs />;
  return <Office tab={route.query.tab ?? (s.can("field.read") ? "map" : "install")} />;
}

function Office({ tab }: { tab: string }) {
  useTitle("الفنيين");
  const s = useSession();
  return (
    <div className="col" style={{ gap: 14 }}>
      <PhoneLink />
      <Card flush>
        <Tabs value={tab} onChange={(t) => setQuery({ tab: t })} tabs={[
          { id: "install", label: "التركيبات", hidden: !s.can("field.read") && !s.can("field.install_doc") },
          { id: "map", label: "مكان الفنيين", hidden: !s.can("field.read") },
          { id: "jobs", label: "المهام" },
        ]} />
        <div className="card-b">{tab === "install" ? <Installations />
          : tab === "jobs" || !s.can("field.read") ? (s.can("field.read") || s.can("field.self") ? <Jobs /> : <Installations />) : <TechMap />}</div>
      </Card>
    </div>
  );
}

type Install = { work_order_id: string; number: string; branch_id: string; customer_id: string; customer_name: string;
  address: string | null; windows: number; entered_at: string | null; job_id: string | null; job_status: string | null;
  technician_name: string; scheduled_at: string | null };

/** التركيبات: orders whose manufacturing is done (stage «تركيب»): the installations manager gives each to a technician;
 *  the installation order (every window with where it goes) is there for whoever may see it. */
function Installations() {
  const s = useSession();
  const list = useLoad(() => api.get<Install[]>("/field/installations"), []);
  const [assign, setAssign] = useState<Install | null>(null);
  const [doc, setDoc] = useState<Install | null>(null);
  return (
    <div className="col">
      <div className="muted small">الأوامر اللي خلص تصنيعها ووصلت لمرحلة «تركيب». مدير التركيبات يسند كل أمر لفني، والأمر بيتقفل «تسليم» لوحده لما الفني يخلّص.</div>
      <Table rows={list.data} loading={list.loading} rowKey={(i) => i.work_order_id} empty="مفيش أوامر مستنية تركيب" columns={[
        { key: "n", label: "الأمر", render: (i) => <a style={{ cursor: "pointer" }} onClick={() => go(`work-orders/${i.work_order_id}`)}><b className="num">{i.number}</b></a> },
        { key: "c", label: "العميل", render: (i) => <span>{i.customer_name}<div className="small muted">{i.address ?? ""}</div></span> },
        { key: "w", label: "الشبابيك", num: true, render: (i) => <span className="num">{i.windows}</span> },
        { key: "e", label: "جاهز من", render: (i) => <span className="num small">{dateTime(i.entered_at)}</span> },
        { key: "t", label: "الفني", render: (i) => i.job_id
          ? <span>{i.technician_name}<div className="small muted num">{dateTime(i.scheduled_at)} · {JOB_STATUS[i.job_status ?? ""]?.[0] ?? i.job_status}</div></span>
          : <Chip color="amber">مستني فني</Chip> },
        { key: "x", label: "", render: (i) => <div className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
          {s.can("field.install_doc", i.branch_id) && <Btn small icon="print" onClick={() => setDoc(i)}>أمر التركيب</Btn>}
          {s.can("field.manage", i.branch_id) && <Btn small kind={i.job_id ? undefined : "primary"} icon="truck" onClick={() => setAssign(i)}>
            {i.job_id ? "فني تاني" : "إسناد لفني"}</Btn>}
        </div> },
      ]} />
      {assign && <AssignJob job={{ kind: "installation", customer_id: assign.customer_id, branch_id: assign.branch_id, work_order_id: assign.work_order_id }}
        onClose={() => setAssign(null)} onSaved={() => { setAssign(null); list.reload(); }} />}
      {doc && <PrintPreview path={`/work-orders/${doc.work_order_id}/print/installation`} title={`أمر تركيب ${doc.number}`} onClose={() => setDoc(null)} />}
    </div>
  );
}

function PhoneLink() {
  const toast = useToast();
  const url = (store.server ?? "").replace(/\/$/, "") + "/tech";
  const secure = url.startsWith("https://");
  return (
    <div className={"notice " + (secure ? "info" : "warn")}>
      <b>الفنيين على الموبايل:</b> تطبيق MYTech على الموبايل (نفس البرنامج) بيدخل بمستخدم دوره «فني» ويفتح على مهامه.
      أو من المتصفح: <span className="num code">{url}</span>{" "}
      <Btn small icon="copy" onClick={() => { navigator.clipboard?.writeText(url); toast.ok("اتنسخ اللينك."); }}>نسخ</Btn>
      {!secure && <div className="small mt">السيرفر ده على شبكة المصنع بس: الفني برا المصنع مش هيوصل له، فالمهام والتتبع برا المصنع
        بيشتغلوا لما السيرفر يبقى أونلاين.</div>}
    </div>
  );
}

function TechMap() {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const techs = useLoad(() => api.get<Tech[]>("/field/technicians"), []);
  useEffect(() => { const t = setInterval(techs.reload, 30000); return () => clearInterval(t); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!box.current || map.current) return;
    map.current = L.map(box.current, { zoomControl: true }).setView([30.0444, 31.2357], 11);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    return () => { map.current?.remove(); map.current = null; };
  }, []);
  useEffect(() => {
    if (!map.current || !layer.current) return;
    layer.current.clearLayers();
    const points: L.LatLngExpression[] = [];
    for (const t of techs.data ?? []) {
      if (!t.last) continue;
      const pos: L.LatLngExpression = [Number(t.last.latitude), Number(t.last.longitude)];
      points.push(pos);
      const icon = L.divIcon({ className: "", iconSize: [34, 34], iconAnchor: [17, 17],
        html: `<div style="width:34px;height:34px;border-radius:50%;background:#5048E5;color:#fff;display:grid;place-items:center;font-weight:800;border:3px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.35)">${escapeHtml(t.full_name.slice(0, 1))}</div>` });
      const job = t.active_job;
      L.marker(pos, { icon }).addTo(layer.current).bindPopup(
        `<b>${escapeHtml(t.full_name)}</b><br>${job ? `${escapeHtml(JOB_KINDS[job.kind] ?? job.kind)} · ${escapeHtml(job.customer_name)}<br>${escapeHtml(JOB_STATUS[job.status]?.[0] ?? job.status)}<br>` : ""}` +
        `<span dir="ltr">${new Date(t.last.at).toLocaleTimeString("ar-EG")}</span>`);
    }
    if (points.length) map.current.fitBounds(L.latLngBounds(points), { maxZoom: 15, padding: [40, 40] });
  }, [techs.data]);
  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0,2fr) minmax(260px,1fr)" }}>
      <div ref={box} className="tech-map" />
      <Table rows={techs.data} loading={techs.loading} rowKey={(t) => t.user_id} empty="مفيش فنيين (اعمل مستخدم بدور «فني»)" columns={[
        { key: "n", label: "الفني", render: (t) => <b>{t.full_name}</b> },
        { key: "j", label: "دلوقتي", render: (t) => t.active_job
          ? <span className="small">{JOB_KINDS[t.active_job.kind]} · {t.active_job.customer_name}<br />
            <Chip color={JOB_STATUS[t.active_job.status]?.[1]}>{JOB_STATUS[t.active_job.status]?.[0]}</Chip></span>
          : <span className="faint small">مش في مهمة · {t.jobs_today} النهارده</span> },
        { key: "l", label: "آخر مكان", render: (t) => t.last
          ? <Btn small icon="map" onClick={() => openMap(`https://www.google.com/maps?q=${t.last!.latitude},${t.last!.longitude}`)}>
              <span className="num">{new Date(t.last.at).toLocaleTimeString("ar-EG", { hour: "numeric", minute: "2-digit" })}</span></Btn>
          : <span className="faint">—</span> },
      ]} />
    </div>
  );
}

function escapeHtml(t: string) {
  return t.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}

function Jobs() {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [day, setDay] = useState(today());
  const [status, setStatus] = useState("");
  const [tech, setTech] = useState("");
  const [track, setTrack] = useState<Job | null>(null);
  const [cancel, setCancel] = useState<Job | null>(null);
  const [install, setInstall] = useState<Job | null>(null);
  const mine = !s.can("field.read");
  const techs = useLoad(() => mine ? Promise.resolve([]) : api.get<{ id: string; full_name: string }[]>("/field/technician-users"), []);
  const jobs = useLoad(() => api.get<Job[]>("/field/jobs", { day: day || undefined, status: status || undefined, technician_id: tech || undefined,
    mine: mine || undefined }), [day, status, tech]);
  const move = (j: Job, to: string) => run(async () => { await api.post(`/field/jobs/${j.id}/status`, { status: to }); jobs.reload(); });
  return (
    <div className="col">
      <PageHead>
        <input type="date" className="input" style={{ width: 170 }} value={day} onChange={(e) => setDay(e.target.value)} />
        <Btn small onClick={() => setDay("")}>كل الأيام</Btn>
        <div style={{ width: 160 }}><Select value={status} onChange={setStatus} placeholder="كل الحالات"
          options={Object.entries(JOB_STATUS).map(([value, [label]]) => ({ value, label }))} /></div>
        {!mine && <div style={{ width: 180 }}><Select value={tech} onChange={setTech} placeholder="كل الفنيين"
          options={(techs.data ?? []).map((t) => ({ value: t.id, label: t.full_name }))} /></div>}
      </PageHead>
      <div className="muted small">المهام بتتعمل من المعاينة («إسناد لفني») أو أمر التصنيع («مهمة تركيب») أو طلب الصيانة في بروفايل العميل.</div>
      <Table rows={jobs.data} loading={jobs.loading} empty="مفيش مهام" columns={[
        { key: "w", label: "الميعاد", render: (j) => <span className="num">{dateTime(j.scheduled_at)}</span> },
        { key: "k", label: "الزيارة", render: (j) => <Chip color="violet">{JOB_KINDS[j.kind] ?? j.kind}</Chip> },
        { key: "c", label: "العميل", render: (j) => <a style={{ cursor: "pointer" }} onClick={() => go(`customers/${j.customer_id}`)}><CustomerName id={j.customer_id} /></a> },
        { key: "r", label: "المرجع", render: (j) => <span className="num">{j.reference}</span> },
        { key: "t", label: "الفني", render: (j) => j.technician_name },
        { key: "s", label: "الحالة", render: (j) => <Chip color={JOB_STATUS[j.status]?.[1]}>{JOB_STATUS[j.status]?.[0] ?? j.status}</Chip> },
        { key: "a", label: "العنوان", render: (j) => <span className="small muted">{j.address ?? ""}</span> },
        { key: "x", label: "", render: (j) => <div className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
          <MapBtn place={j} label="" />
          {j.kind === "installation" && j.work_order_id && s.can("field.install_doc", j.branch_id) &&
            <Btn small icon="print" onClick={() => setInstall(j)}>أمر التركيب</Btn>}
          {!mine && (j.started_at || j.status === "done") && <Btn small onClick={() => setTrack(j)}>المسار</Btn>}
          {s.can("field.manage", j.branch_id) && ["scheduled", "on_way", "arrived"].includes(j.status) &&
            <Btn small kind="danger" busy={busy} onClick={() => setCancel(j)}>إلغاء</Btn>}
          {mine && j.status === "scheduled" && <Btn small busy={busy} onClick={() => move(j, "on_way")}>في الطريق</Btn>}
          {mine && j.status === "on_way" && <Btn small busy={busy} onClick={() => move(j, "arrived")}>وصلت</Btn>}
          {mine && j.status === "arrived" && <Btn small kind="success" busy={busy} onClick={() => move(j, "done")}>خلصت</Btn>}
          {s.can("field.delete", j.branch_id) && <DeleteBtn path={`/field/jobs/${j.id}`} what="المهمة" onDone={jobs.reload} />}
        </div> },
      ]} />
      {track && <Track job={track} onClose={() => setTrack(null)} />}
      {install && <PrintPreview path={`/field/jobs/${install.id}/installation-order`} title={`أمر تركيب ${install.reference}`}
        onClose={() => setInstall(null)} />}
      {cancel && <Confirm danger title="إلغاء المهمة" text={`إلغاء مهمة ${JOB_KINDS[cancel.kind]} للعميل ${cancel.customer_name}؟`} busy={busy}
        onClose={() => setCancel(null)} onYes={() => { move(cancel, "cancelled"); setCancel(null); }} />}
    </div>
  );
}

function Track({ job, onClose }: { job: Job; onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const points = useLoad(() => api.get<S<"PointOut">[]>(`/field/jobs/${job.id}/track`), [job.id]);
  useEffect(() => {
    if (!box.current || !points.data) return;
    const m = L.map(box.current);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(m);
    const line = points.data.map((p) => [Number(p.latitude), Number(p.longitude)] as L.LatLngTuple);
    const all = [...line];
    if (job.latitude && job.longitude) {   // the customer's place
      const dest: L.LatLngTuple = [Number(job.latitude), Number(job.longitude)];
      L.circleMarker(dest, { radius: 8, color: "#C62828" }).addTo(m).bindPopup(job.customer_name);
      all.push(dest);
    }
    if (line.length) {
      L.polyline(line, { color: "#5048E5", weight: 4 }).addTo(m);
      L.circleMarker(line[line.length - 1], { radius: 7, color: "#15803D" }).addTo(m);
    }
    if (all.length) m.fitBounds(L.latLngBounds(all), { maxZoom: 16, padding: [30, 30] });
    else m.setView([30.0444, 31.2357], 11);
    return () => { m.remove(); };
  }, [points.data, job.latitude, job.longitude]);
  return (
    <Modal title={`مسار ${job.technician_name} · ${JOB_KINDS[job.kind]} ${job.customer_name}`} size="xwide" onClose={onClose}>
      <div className="muted small mb">بدأ {dateTime(job.started_at)} · وصل {dateTime(job.arrived_at)} · خلص {dateTime(job.finished_at)} ·{" "}
        <span className="num">{points.data?.length ?? 0}</span> نقطة</div>
      <div ref={box} className="tech-map" />
      {points.data && !points.data.length && <div className="muted small mt">مفيش نقط: الموبايل مابعتش مكانه (محتاج https وإذن الموقع).</div>}
    </Modal>
  );
}

/** The technician's own screen (phone app): today's jobs as cards; the position is sent only during a job. */
function MyJobs() {
  useTitle("مهامي");
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const s = useSession();
  const jobs = useLoad(() => api.get<Job[]>("/field/jobs", { mine: true }), []);
  const [install, setInstall] = useState<Job | null>(null);
  const [gps, setGps] = useState<"off" | "on" | string>("off");
  const active = (jobs.data ?? []).some((j) => j.status === "on_way" || j.status === "arrived");
  useEffect(() => { const t = setInterval(jobs.reload, 60000); return () => clearInterval(t); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!active) { setGps("off"); return; }
    let stop: (() => void) | null = null, last = 0, alive = true;
    const send = (f: Fix) => {
      if (Date.now() - last < 30000) return;
      last = Date.now();
      api.post("/field/locations", { latitude: f.latitude.toFixed(6), longitude: f.longitude.toFixed(6),
        accuracy_m: f.accuracy != null ? Math.round(f.accuracy) : null }).then(() => setGps("on")).catch(() => jobs.reload());
    };
    watchPosition(send, (msg) => setGps(msg)).then((s) => { if (alive) stop = s; else s(); });
    return () => { alive = false; stop?.(); };
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps
  const move = (j: Job, to: string) => run(async () => {
    const note = to === "done" ? (window.prompt("اكتب ملاحظة عن اللي اتعمل (اختياري):", "") ?? "") : "";
    await api.post(`/field/jobs/${j.id}/status`, { status: to, note });
    jobs.reload();
  });
  const next: Record<string, [string, string, "primary" | "success" | undefined][]> = {
    scheduled: [["on_way", "أنا في الطريق", undefined], ["arrived", "وصلت", "primary"]],
    on_way: [["arrived", "وصلت", "primary"]], arrived: [["done", "خلصت المهمة", "success"]] };
  return (
    <div className="col" style={{ gap: 12, maxWidth: 640, marginInline: "auto" }}>
      {active && <div className={"notice " + (gps === "on" ? "ok" : "warn")}>
        {gps === "on" ? "📍 مكانك بيتبعت للمكتب لحد ما تخلّص المهمة." : gps === "off" ? "بيجهّز المكان…" : gps}</div>}
      <AppPunch />
      {jobs.loading && !jobs.data && <div className="empty"><span className="spinner" /></div>}
      {jobs.data && !jobs.data.length && <div className="empty">مفيش مهام ليك دلوقتي 👌</div>}
      {(jobs.data ?? []).map((j) => {
        const map = mapUrl(j);
        return (
          <Card key={j.id}>
            <div className="row" style={{ gap: 6 }}>
              <Chip color="violet">{JOB_KINDS[j.kind] ?? j.kind}</Chip>
              <Chip color={JOB_STATUS[j.status]?.[1]}>{JOB_STATUS[j.status]?.[0] ?? j.status}</Chip>
              <span className="end muted small num">{j.reference}</span>
            </div>
            <h3 style={{ margin: "8px 0 4px" }}>{j.customer_name}</h3>
            <div className="muted small" style={{ lineHeight: 1.8 }}>
              🕒 <span className="num">{dateTime(j.scheduled_at)}</span><br />
              {j.address && <>📌 {j.address}<br /></>}
              {j.notes && <>📝 {j.notes}</>}
            </div>
            <div className="row wrap mt" style={{ gap: 8 }}>
              {j.customer_phone && <Btn icon="phone" onClick={() => openMap(`tel:${j.customer_phone}`).catch(() => undefined)}>
                <span className="num">{j.customer_phone}</span></Btn>}
              {map && <Btn icon="map" onClick={() => openMap(map).catch(() => toast.err("ماقدرتش أفتح الخريطة."))}>الخريطة</Btn>}
              {j.kind === "installation" && j.work_order_id && s.can("field.install_doc") &&
                <Btn icon="print" onClick={() => setInstall(j)}>أمر التركيب</Btn>}
            </div>
            {(next[j.status] ?? []).length > 0 && <div className="row wrap mt" style={{ gap: 8 }}>
              {next[j.status].map(([to, label, kind]) => (
                <Btn key={to} kind={kind} busy={busy} className="grow" onClick={() => move(j, to)}>{label}</Btn>
              ))}
            </div>}
          </Card>
        );
      })}
      {install && <PrintPreview path={`/field/jobs/${install.id}/installation-order`} title={`أمر تركيب ${install.reference}`}
        onClose={() => setInstall(null)} />}
    </div>
  );
}


/** بصمة من الموبايل (لو سياسة مرتبه بتسمح): أول اليوم لو مش هيعدّي على المصنع، وآخر اليوم وهو سايب الموقع. */
function AppPunch() {
  const toast = useToast();
  const me = useLoad(() => api.get<{ can_punch: boolean; punches: { at: string; source: string }[] }>("/attendance/me").catch(() => null), []);
  const [busy, setBusy] = useState(false);
  if (!me.data?.can_punch) return null;
  const punch = async () => {
    setBusy(true);
    let stop: (() => void) | null = null;
    let done = false;
    const finish = (msg?: string) => { if (done) return; done = true; stop?.(); setBusy(false); if (msg) toast.err(msg); };
    const timer = setTimeout(() => finish("ماقدرتش أجيب مكانك: شغّل الـ Location وجرّب تاني."), 40000);
    stop = await watchPosition((f) => {
      if (done) return;
      clearTimeout(timer);
      api.post("/attendance/my-punch", { latitude: f.latitude.toFixed(6), longitude: f.longitude.toFixed(6),
        accuracy_m: f.accuracy != null ? Math.round(f.accuracy) : null })
        .then(() => { toast.ok("اتسجلت البصمة."); me.reload(); finish(); })
        .catch((e) => finish(e instanceof Error ? e.message : String(e)));
    }, (msg) => { clearTimeout(timer); finish(msg); });
    if (done) stop();
  };
  const times = me.data.punches.map((p) => `${p.at.slice(11, 16)}${p.source === "app" ? " 📱" : ""}`);
  return (
    <Card>
      <div className="row wrap" style={{ gap: 10, alignItems: "center" }}>
        <Btn kind="primary" icon="hand" busy={busy} onClick={punch}>بصمة (حضور / انصراف)</Btn>
        <span className="muted small">{times.length ? <>بصمات النهارده: <span className="num">{times.join(" · ")}</span></> : "مفيش بصمات النهارده لسه"}</span>
      </div>
      <div className="muted small mt">ابصم من هنا أول اليوم لو مش هتعدّي على المصنع، وآخر اليوم وانت سايب الموقع. مكانك بيتسجل مع البصمة.</div>
    </Card>
  );
}
