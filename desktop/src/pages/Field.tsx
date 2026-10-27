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
import { MapBtn, mapUrl, openMap } from "../components/field";
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
  return <Office tab={route.query.tab ?? "map"} />;
}

function Office({ tab }: { tab: string }) {
  useTitle("الفنيين");
  const s = useSession();
  return (
    <div className="col" style={{ gap: 14 }}>
      <PhoneLink />
      <Card flush>
        <Tabs value={tab} onChange={(t) => setQuery({ tab: t })} tabs={[
          { id: "map", label: "مكان الفنيين", hidden: !s.can("field.read") },
          { id: "jobs", label: "المهام" },
        ]} />
        <div className="card-b">{tab === "jobs" || !s.can("field.read") ? <Jobs /> : <TechMap />}</div>
      </Card>
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
  const jobs = useLoad(() => api.get<Job[]>("/field/jobs", { mine: true }), []);
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
            </div>
            {(next[j.status] ?? []).length > 0 && <div className="row wrap mt" style={{ gap: 8 }}>
              {next[j.status].map(([to, label, kind]) => (
                <Btn key={to} kind={kind} busy={busy} className="grow" onClick={() => move(j, to)}>{label}</Btn>
              ))}
            </div>}
          </Card>
        );
      })}
    </div>
  );
}
