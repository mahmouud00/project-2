// Places on the map, work order progress, and assigning visits to technicians.
import { useState } from "react";
import { api, type S } from "../api/client";
import { useAction, useLoad } from "../lib/hooks";
import { inDesktop } from "../lib/discovery";
import { JOB_KINDS } from "../lib/lookups";
import { useToast } from "../state/toast";
import { Btn, Field, Modal, Select, TextArea, TextIn } from "./ui";
import { date } from "../lib/format";

export type Place = { latitude?: string | null; longitude?: string | null; location_url?: string | null; address?: string | null };

export function mapUrl(p: Place): string | null {
  if (p.latitude != null && p.longitude != null) return `https://www.google.com/maps?q=${p.latitude},${p.longitude}`;
  if (p.location_url && /^https:\/\//.test(p.location_url)) return p.location_url;
  if (p.address) return "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(p.address);
  return null;
}

/** Opens Google Maps in the browser (the desktop app hands it to Windows). */
export async function openMap(url: string) {
  if (inDesktop()) {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("open_map", { url });
  } else {
    window.open(url, "_blank", "noopener");
  }
}

export function MapBtn({ place, small = true, label = "الخريطة" }: { place: Place; small?: boolean; label?: string }) {
  const url = mapUrl(place);
  const toast = useToast();
  if (!url) return null;
  return <Btn small={small} icon="map" onClick={(e) => { e.stopPropagation(); openMap(url).catch(() => toast.err("ماقدرتش أفتح الخريطة.")); }}>{label}</Btn>;
}

/** A Google Maps link (as the customer sends it on WhatsApp) or "lat, lng". */
export function LocationField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Field label="اللوكيشن" hint="الصق لينك جوجل ماب اللي العميل بعته، أو الإحداثيات (30.0444, 31.2357)" className="span-all">
      <TextIn value={value} onChange={onChange} code placeholder="https://maps.app.goo.gl/…" />
    </Field>
  );
}

export function Progress({ pct, late, expected }: { pct: number | null | undefined; late?: boolean; expected?: string | null }) {
  if (pct == null) return <span className="faint">—</span>;
  return (
    <div className="progress-cell" title={expected ? `التسليم المتوقع ${date(expected)}` : undefined}>
      <div className={"progress" + (late ? " late" : pct >= 100 ? " done" : "")}><span style={{ width: `${pct}%` }} /></div>
      <span className={"num small" + (late ? " danger-text bold" : "")}>{pct}%</span>
      {late && <span className="danger-text small">متأخر</span>}
    </div>
  );
}

type JobDraft = { kind: string; customer_id: string; branch_id: string; survey_id?: string; work_order_id?: string; maintenance_id?: string };

/** Assign a visit to a technician. The place comes from the survey / maintenance request / customer. */
export function AssignJob({ job, onClose, onSaved }: { job: JobDraft; onClose: () => void; onSaved: (j: S<"JobOut">) => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const techs = useLoad(() => api.get<{ id: string; full_name: string }[]>("/field/technician-users"), []);
  const tomorrow = new Date(Date.now() + 86400000);
  tomorrow.setHours(10, 0, 0, 0);
  const local = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [d, setD] = useState({ kind: job.kind, technician_id: "", scheduled_at: local(tomorrow), notes: "", location_url: "" });
  return (
    <Modal title="إسناد لفني" onClose={onClose} footer={<>
      <Btn kind="primary" busy={busy} disabled={!d.technician_id || !d.scheduled_at} onClick={() => run(async () => {
        const saved = await api.post<S<"JobOut">>("/field/jobs", { ...job, ...d, scheduled_at: new Date(d.scheduled_at).toISOString(),
          location_url: d.location_url || null });
        toast.ok(`اتبعتت المهمة لـ ${saved.technician_name}.`);
        onSaved(saved);
        onClose();
      })}>إسناد</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2">
        <Field label="نوع الزيارة"><Select value={d.kind} onChange={(v) => setD((x) => ({ ...x, kind: v }))}
          options={Object.entries(JOB_KINDS).map(([value, label]) => ({ value, label }))} /></Field>
        <Field label="الفني"><Select value={d.technician_id} onChange={(v) => setD((x) => ({ ...x, technician_id: v }))} placeholder="اختار الفني"
          options={(techs.data ?? []).map((t) => ({ value: t.id, label: t.full_name }))} /></Field>
        {techs.data && !techs.data.length && <div className="notice warn span-all">مفيش فنيين. اعمل مستخدم بدور «فني» من «المستخدمين والصلاحيات».</div>}
        <Field label="الميعاد" className="span-all"><input type="datetime-local" className="input" value={d.scheduled_at}
          onChange={(e) => setD((x) => ({ ...x, scheduled_at: e.target.value }))} /></Field>
        <LocationField value={d.location_url} onChange={(v) => setD((x) => ({ ...x, location_url: v }))} />
        <Field label="ملاحظات للفني" className="span-all"><TextArea value={d.notes} onChange={(v) => setD((x) => ({ ...x, notes: v }))} rows={2} /></Field>
      </div>
      <div className="muted small mt">لو اللوكيشن فاضي، بيتاخد من المعاينة أو طلب الصيانة أو عنوان العميل.</div>
    </Modal>
  );
}
