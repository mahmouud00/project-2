// سياسات المرتبات والحضور (كل رقم بيتعدل)، مناطق الشغل (داخل = تركيب عادي، برّه = سفر)، والإجازات الرسمية.
import { useState } from "react";
import { api, type S } from "../api/client";
import { useAction, useLoad } from "../lib/hooks";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Check, Chip, ErrorBox, Field, Modal, Money, NumIn, PageHead, Select, Table, TextArea, TextIn } from "../components/ui";
import { DeleteBtn } from "../components/actions";
import { date } from "../lib/format";

type Policy = S<"PolicyOut">;
type Zone = S<"ZoneOut">;
type Tier = { from_minutes: number; to_minutes: number | null; action: string; value: string };
type Piece = { name: string; rate: string };
type Rules = Record<string, any> & { late_tiers: Tier[]; piece_rates: Piece[]; weekly_off: number[] };

export const WEEKDAYS = ["الاتنين", "التلات", "الأربع", "الخميس", "الجمعة", "السبت", "الحد"];
const TIER_ACTIONS: Record<string, string> = { day_fraction: "يتخصم جزء من يوم", multiplier: "الدقايق × معامل",
  compensate: "يعوّضها بعد ميعاد الانصراف", none: "مفيش خصم" };

export function PolicySettings() {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const list = useLoad(() => api.get<Policy[]>("/pay-policies"), []);
  const [edit, setEdit] = useState<Policy | "new" | null>(null);
  const can = s.can("hr.payroll");
  return (
    <div className="col" style={{ gap: 14 }}>
      <PageHead>
        {can && <Btn kind="primary" icon="plus" onClick={() => setEdit("new")}>سياسة جديدة</Btn>}
        {can && <Btn busy={busy} onClick={() => run(async () => { await api.post("/pay-policies/templates"); list.reload(); toast.ok("اتضافت السياسات والمناطق الناقصة."); })}>
          إضافة السياسات الجاهزة (الإدارة، المبيعات، المصنع، التركيبات)</Btn>}
      </PageHead>
      {list.error && <ErrorBox text={list.error} onRetry={list.reload} />}
      <Table rows={list.data} loading={list.loading} onRow={can ? (p) => setEdit(p) : undefined} empty="مفيش سياسات لسه" columns={[
        { key: "n", label: "السياسة", render: (p) => <b>{p.name}</b> },
        { key: "h", label: "المواعيد", render: (p) => <span className="num">{String(p.rules.work_start)} - {String(p.rules.work_end)}</span> },
        { key: "o", label: "الإجازة", render: (p) => (p.rules.weekly_off as number[]).map((d) => WEEKDAYS[d]).join("، ") },
        { key: "x", label: "أوفر تايم", render: (p) => p.rules.overtime_enabled ? <Chip color="green">× {Number(p.rules.overtime_multiplier)}</Chip> : "—" },
        { key: "c", label: "عمولة", render: (p) => Number(p.rules.commission_rate) ? <Chip color="violet">{Number(p.rules.commission_rate) * 100}%</Chip> : "—" },
        { key: "a", label: "بصمة موبايل", render: (p) => p.rules.app_punch ? "✓" : "" },
        { key: "e", label: "الموظفين", num: true, render: (p) => <span className="num">{p.employees}</span> },
      ]} />
      <div className="muted small">كل موظف بيتحسب مرتبه حسب السياسة اللي في ملفه. الموظف اللي مالوش سياسة بيتحسب زي الأول (المرتب + الحوافز − الخصومات).</div>
      <Zones />
      <Holidays />
      {edit && <PolicyForm policy={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={list.reload} />}
    </div>
  );
}

function PolicyForm({ policy, onClose, onSaved }: { policy: Policy | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const defaults = useLoad(() => policy ? Promise.resolve(policy.rules) : api.get<Record<string, any>>("/pay-policies/defaults"), []);
  const [name, setName] = useState(policy?.name ?? "");
  const [code, setCode] = useState(policy?.code ?? "");
  const [notes, setNotes] = useState(policy?.notes ?? "");
  const [r, setR] = useState<Rules | null>(policy ? (policy.rules as Rules) : null);
  const rules = r ?? (defaults.data as Rules | undefined);
  if (!rules) return null;
  const set = (k: string) => (v: any) => setR({ ...rules, [k]: v });
  const num = (k: string, label: string, hint?: string, unit?: string) =>
    <Field label={label} hint={hint}><NumIn value={String(rules[k] ?? "")} onChange={set(k)} unit={unit} /></Field>;
  const flag = (k: string, label: string) => <Check checked={!!rules[k]} onChange={set(k)} label={label} />;
  const tiers = rules.late_tiers ?? [];
  const setTier = (i: number, patch: Partial<Tier>) => set("late_tiers")(tiers.map((t, j) => j === i ? { ...t, ...patch } : t));
  const pieces = rules.piece_rates ?? [];
  const save = () => run(async () => {
    const body = { ...rules, commission_rate: rules.commission_rate || "0" };
    if (policy) await api.patch(`/pay-policies/${policy.id}`, { version: policy.version, name, notes, rules: body });
    else await api.post("/pay-policies", { code, name, notes, rules: body });
    toast.ok("اتحفظت السياسة. إعادة حساب كشف المرتبات بتطبقها.");
    onSaved(); onClose();
  });
  return (
    <Modal title={policy ? policy.name : "سياسة جديدة"} size="wide" onClose={onClose} footer={<>
      <Btn kind="primary" busy={busy} disabled={!name.trim() || (!policy && !code.trim())} onClick={save}>حفظ</Btn>
      {policy && !policy.employees && <DeleteBtn small={false} path={`/pay-policies/${policy.id}`} what={policy.name} onDone={() => { onSaved(); onClose(); }} />}
      <Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col" style={{ gap: 14 }}>
        <div className="grid g3">
          <Field label="الاسم"><TextIn value={name} onChange={setName} autoFocus /></Field>
          {!policy && <Field label="الكود"><TextIn value={code} onChange={setCode} code /></Field>}
        </div>
        <h4>مواعيد الشغل</h4>
        <div className="grid g3">
          <Field label="من"><input type="time" className="input" value={rules.work_start} onChange={(e) => set("work_start")(e.target.value)} /></Field>
          <Field label="لحد"><input type="time" className="input" value={rules.work_end} onChange={(e) => set("work_end")(e.target.value)} /></Field>
          {num("day_divisor", "اليوم = المرتب ÷", "عادةً 30")}
          <Field label="الإجازة الأسبوعية" className="span-all"><div className="row wrap" style={{ gap: 10 }}>
            {WEEKDAYS.map((d, i) => <Check key={i} label={d} checked={rules.weekly_off.includes(i)}
              onChange={(v) => set("weekly_off")(v ? [...rules.weekly_off, i] : rules.weekly_off.filter((x) => x !== i))} />)}</div></Field>
        </div>
        <h4>التأخير</h4>
        <div className="grid g3">
          {num("late_grace_minutes", "سماحية (دقيقة)", "التأخير لحد كده مايتحسبش")}
          {num("permissions_per_month", "عدد الأذونات في الشهر")}
          {num("permission_max_minutes", "أقصى مدة للإذن (دقيقة)")}
        </div>
        <table className="table">
          <thead><tr><th>من (دقيقة تأخير)</th><th>لحد</th><th>الحساب</th><th>القيمة</th><th /></tr></thead>
          <tbody>
            {tiers.map((t, i) => <tr key={i}>
              <td><NumIn value={String(t.from_minutes)} onChange={(v) => setTier(i, { from_minutes: Number(v) || 0 })} /></td>
              <td><NumIn value={t.to_minutes == null ? "" : String(t.to_minutes)} placeholder="وأكتر" onChange={(v) => setTier(i, { to_minutes: v === "" ? null : Number(v) })} /></td>
              <td><Select value={t.action} onChange={(v) => setTier(i, { action: v })} options={Object.entries(TIER_ACTIONS).map(([value, label]) => ({ value, label }))} /></td>
              <td>{(t.action === "day_fraction" || t.action === "multiplier") &&
                <NumIn value={String(t.value)} onChange={(v) => setTier(i, { value: v })} unit={t.action === "day_fraction" ? "يوم" : "×"} />}</td>
              <td><Btn small icon="trash" onClick={() => set("late_tiers")(tiers.filter((_, j) => j !== i))} /></td>
            </tr>)}
          </tbody>
        </table>
        <div><Btn small icon="plus" onClick={() => set("late_tiers")([...tiers, { from_minutes: 1, to_minutes: null, action: "multiplier", value: "1.5" }])}>شريحة تأخير</Btn>
          <span className="muted small"> مثلًا: بعد ٣٠ دقيقة نص يوم · أو الساعة بساعة ونص (× 1.5) · أو أقل من ساعة يعوّضها بعد الميعاد</span></div>
        <h4>الغياب (بالأيام)</h4>
        <div className="grid g3">
          {num("absence_notified_days", "غياب بتبليغ / بإذن")}
          {num("absence_unnotified_days", "غياب من غير إذن")}
          {num("absence_install_day_days", "غياب يوم عنده مهمة تركيب", "فاضي = زي الغياب العادي")}
          <div className="span-all">{flag("absence_repeat_doubles", "الغياب من غير إذن يتضاعف كل مرة في نفس الشهر (٢ ثم ٤ ثم ٨…)")}</div>
        </div>
        <h4>الأوفر تايم</h4>
        <div className="grid g3">
          <div className="span-all">{flag("overtime_enabled", "فيه أوفر تايم")}</div>
          {rules.overtime_enabled && <>
            <Field label="بيبدأ"><Select value={rules.overtime_after} onChange={set("overtime_after")}
              options={[{ value: "end", label: "بعد ميعاد الانصراف" }, { value: "hours", label: "بعد عدد ساعات شغل" }]} /></Field>
            {rules.overtime_after === "hours" && num("overtime_after_hours", "بعد كام ساعة")}
            {num("overtime_multiplier", "الساعة بـ", "1.5 = ساعة ونص", "ساعة")}
          </>}
        </div>
        <h4>التركيب والسفر وأيام الإجازة</h4>
        <div className="grid g3">
          <div className="span-all">{flag("field_days_flexible", "يوم التركيب/السفر بيبدأ من ساعة بداية الشغل (مفيش تأخير)")}</div>
          {num("field_day_hours", "ساعات يوم التركيب الصافي", "الأوفر تايم بعدها")}
          {num("travel_day_value", "يوم السفر بـ", "1.5 = يوم ونص", "يوم")}
          {num("travel_meal", "وجبة السفر", undefined, "ج")}
          {num("holiday_day_value", "الشغل يوم الإجازة/الإجازة الرسمية بـ", undefined, "يوم")}
          <div className="span-all">{flag("install_transport_by_zone", "يوم التركيب جوه منطقة: ياخد بدل مواصلات المنطقة")}</div>
          <div className="span-all">{flag("app_punch", "يقدر يبصم من الموبايل (بالمكان)")}</div>
        </div>
        <h4>عمولة المبيعات (على التحصيل)</h4>
        <div className="grid g3">
          <Field label="النسبة" hint="1 = 1% من اللي اتحصّل من عملياته"><NumIn value={String(Number(rules.commission_rate || 0) * 100)}
            onChange={(v) => set("commission_rate")(String((Number(v) || 0) / 100))} unit="%" /></Field>
          {num("commission_min_collections", "أدنى تحصيل في الشهر", "أقل منه: مفيش عمولة إلا بإذن المدير", "ج")}
        </div>
        <h4>أسعار القطعة (عمالة مؤقتة)</h4>
        {pieces.map((p, i) => <div key={i} className="row" style={{ gap: 8 }}>
          <div className="grow"><TextIn value={p.name} onChange={(v) => set("piece_rates")(pieces.map((x, j) => j === i ? { ...x, name: v } : x))} /></div>
          <div style={{ width: 140 }}><NumIn value={String(p.rate)} onChange={(v) => set("piece_rates")(pieces.map((x, j) => j === i ? { ...x, rate: v } : x))} unit="ج" /></div>
          <Btn small icon="trash" onClick={() => set("piece_rates")(pieces.filter((_, j) => j !== i))} />
        </div>)}
        <div><Btn small icon="plus" onClick={() => set("piece_rates")([...pieces, { name: "", rate: "0" }])}>سعر قطعة</Btn></div>
        <Field label="ملاحظات"><TextArea value={notes} onChange={setNotes} rows={2} /></Field>
      </div>
    </Modal>
  );
}

function Zones() {
  const s = useSession();
  const toast = useToast();
  const { run } = useAction(toast.err);
  const list = useLoad(() => api.get<Zone[]>("/work-zones"), []);
  const [edit, setEdit] = useState<Zone | "new" | null>(null);
  const can = s.can("hr.payroll");
  return (
    <Card title="مناطق الشغل (جوه المنطقة = تركيب عادي، برّه كل المناطق = سفر)"
      actions={can && <Btn small icon="plus" onClick={() => setEdit("new")}>منطقة</Btn>}>
      <Table rows={list.data} loading={list.loading} onRow={can ? (z) => setEdit(z) : undefined} empty="مفيش مناطق" columns={[
        { key: "n", label: "المنطقة", render: (z) => <b>{z.name}</b> },
        { key: "c", label: "المركز", render: (z) => <span className="num" dir="ltr">{Number(z.latitude)}, {Number(z.longitude)}</span> },
        { key: "r", label: "نصف القطر", num: true, render: (z) => <span className="num">{Number(z.radius_km)} كم</span> },
        { key: "t", label: "بدل مواصلات", num: true, render: (z) => <Money v={z.transport_allowance} /> },
        { key: "a", label: "", render: (z) => can && <Btn small onClick={(e) => { e.stopPropagation(); run(async () => {
          await api.patch(`/work-zones/${z.id}`, { version: z.version, is_active: !z.is_active }); list.reload(); }); }}>
          {z.is_active ? "إيقاف" : "تشغيل"}</Btn> },
      ]} />
      {edit && <ZoneForm zone={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={list.reload} />}
    </Card>
  );
}

function ZoneForm({ zone, onClose, onSaved }: { zone: Zone | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState({ name: zone?.name ?? "", place: zone ? `${Number(zone.latitude)}, ${Number(zone.longitude)}` : "",
    radius_km: String(zone ? Number(zone.radius_km) : 10), transport_allowance: String(zone ? Number(zone.transport_allowance) : 0) });
  const m = d.place.match(/(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)/) ?? d.place.match(/@(-?\d+\.\d+),(-?\d+\.\d+)/);
  const save = () => run(async () => {
    const body = { name: d.name, latitude: m![1], longitude: m![2], radius_km: d.radius_km, transport_allowance: d.transport_allowance || "0" };
    if (zone) await api.patch(`/work-zones/${zone.id}`, { ...body, version: zone.version });
    else await api.post("/work-zones", body);
    onSaved(); onClose();
  });
  return (
    <Modal title={zone ? zone.name : "منطقة جديدة"} onClose={onClose} footer={<>
      <Btn kind="primary" busy={busy} disabled={!d.name.trim() || !m || !Number(d.radius_km)} onClick={save}>حفظ</Btn>
      {zone && <DeleteBtn small={false} path={`/work-zones/${zone.id}`} what={zone.name} onDone={() => { onSaved(); onClose(); }} />}
      <Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col">
        <Field label="الاسم"><TextIn value={d.name} onChange={(v) => setD({ ...d, name: v })} autoFocus /></Field>
        <Field label="مركز المنطقة" hint="الصق لينك جوجل ماب أو اكتب: خط العرض، خط الطول"><TextIn value={d.place} onChange={(v) => setD({ ...d, place: v })} /></Field>
        <Field label="نصف القطر"><NumIn value={d.radius_km} onChange={(v) => setD({ ...d, radius_km: v })} unit="كم" /></Field>
        <Field label="بدل مواصلات يوم التركيب فيها"><NumIn value={d.transport_allowance} onChange={(v) => setD({ ...d, transport_allowance: v })} unit="ج" /></Field>
      </div>
    </Modal>
  );
}

function Holidays() {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [year, setYear] = useState(new Date().getFullYear());
  const list = useLoad(() => api.get<S<"HolidayOut">[]>("/public-holidays", { year }), [year]);
  const [d, setD] = useState({ day: "", name: "" });
  const can = s.can("hr.payroll");
  return (
    <Card title="الإجازات الرسمية" actions={<div style={{ width: 110 }}><NumIn value={String(year)} onChange={(v) => setYear(Number(v) || year)} /></div>}>
      <Table rows={list.data} loading={list.loading} empty="مفيش إجازات رسمية متسجلة للسنة دي" columns={[
        { key: "d", label: "اليوم", render: (h) => <span className="num">{date(h.day)}</span> },
        { key: "n", label: "المناسبة", render: (h) => h.name },
        { key: "x", label: "", width: 80, render: (h) => can && <DeleteBtn path={`/public-holidays/${h.id}`} what={h.name || h.day} onDone={list.reload} /> },
      ]} />
      {can && <div className="row mt" style={{ gap: 8 }}>
        <input type="date" className="input" style={{ width: 170 }} value={d.day} onChange={(e) => setD({ ...d, day: e.target.value })} />
        <div className="grow"><TextIn value={d.name} onChange={(v) => setD({ ...d, name: v })} placeholder="المناسبة" /></div>
        <Btn icon="plus" busy={busy} disabled={!d.day} onClick={() => run(async () => { await api.post("/public-holidays", d); setD({ day: "", name: "" }); list.reload(); })}>إضافة</Btn>
      </div>}
    </Card>
  );
}
