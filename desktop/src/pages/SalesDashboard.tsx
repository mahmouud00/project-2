// داش بورد موظف المبيعات: everything about one salesperson's work for a period; the sales manager picks anyone,
// sees the team side by side, and moves all of one person's work to another.
import { useState } from "react";
import { api } from "../api/client";
import { useTitle } from "../lib/title";
import { useAction, useLoad, when } from "../lib/hooks";
import { go } from "../lib/router";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, ErrorBox, Field, Loading, Modal, Money, Select, Table } from "../components/ui";
import { Icon } from "../components/icons";

type Status = { count: number; value: string };
type Report = {
  user_id: string; name: string; from: string; to: string;
  customers: { total: number; new: number; by_contact_method: Record<string, number> };
  surveys: { made: number; waiting_manager: number };
  quotations: { made: number; by_status: Record<string, Status>; value_made: string; accepted_count: number; accepted_value: string;
    conversion_pct: string; average_value: string; waiting_manager: number; discount_requests: number; discount_given: string;
    to_follow_up: { id: string; number: string; total: string; days: number }[] };
  invoices: { issued: number; sales_value: string; open_balance: string };
  collections: { confirmed: string; pending_count: number; pending_amount: string; rejected: number; collection_pct: string };
  top_customers: { name: string; sales: string }[];
  months: { month: string; sales: string; collected: string; quotations: number }[];
};
type TeamRow = { user_id: string; name: string; customers_new: number; quotations: number; accepted: number; conversion_pct: string;
  sales: string; collected: string; open_balance: string };

const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => today().slice(0, 8) + "01";
const STATUS_AR: Record<string, string> = { draft: "مسودة", sent: "اتبعت", accepted: "مقبول", rejected: "مرفوض", expired: "منتهي" };

export default function SalesDashboard() {
  useTitle("داش بورد المبيعات");
  const s = useSession();
  const all = s.can("sales.all");
  const [who, setWho] = useState<string>("");
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());
  const [moving, setMoving] = useState(false);
  const people = useLoad(() => api.get<{ id: string; name: string }[]>("/sales/people"), []);
  const r = useLoad(() => api.get<Report>("/sales/dashboard", { user_id: who || undefined, date_from: from, date_to: to }), [who, from, to]);
  const team = useLoad(() => when(all, () => api.get<{ people: TeamRow[] }>("/sales/team", { date_from: from, date_to: to })), [from, to]);
  const d = r.data;

  const kpi = (label: string, value: React.ReactNode, icon: string, color: string, sub?: React.ReactNode) => (
    <div className="card kpi"><div className="row"><div className="grow">
      <div className="label">{label}</div><div className="value">{value}</div>{sub && <div className="small muted">{sub}</div>}</div>
      <div className="ic" style={{ color, background: `color-mix(in srgb, ${color} 14%, transparent)` }}><Icon name={icon} /></div></div></div>
  );
  return (
    <div className="col" style={{ gap: 14 }}>
      <Card>
        <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
          {all && <Field label="موظف المبيعات"><Select value={who} onChange={setWho} placeholder="أنا"
            options={(people.data ?? []).map((p) => ({ value: p.id, label: p.name }))} /></Field>}
          <Field label="من"><input type="date" className="input" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label="لحد"><input type="date" className="input" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          {s.can("sales.transfer") && <Btn icon="users" onClick={() => setMoving(true)}>نقل كل شغل موظف</Btn>}
        </div>
      </Card>
      {r.error ? <ErrorBox text={r.error} onRetry={r.reload} /> : !d ? <Loading /> : <>
        <div className="grid g4">
          {kpi("المبيعات (فواتير)", <Money v={d.invoices.sales_value} />, "invoice", "var(--primary)", <>{d.invoices.issued} فاتورة</>)}
          {kpi("التحصيلات المتأكدة", <Money v={d.collections.confirmed} />, "cash", "var(--success)", <>نسبة التحصيل {d.collections.collection_pct}%</>)}
          {kpi("عروض الأسعار", String(d.quotations.made), "quote", "var(--violet)", <>اتقبل {d.quotations.accepted_count} · التحويل {d.quotations.conversion_pct}%</>)}
          {kpi("العملاء", String(d.customers.total), "users", "var(--warning)", <>جداد في الفترة {d.customers.new}</>)}
        </div>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
          <Card title="عروض الأسعار">
            <div className="totals" style={{ width: "100%" }}>
              {Object.entries(d.quotations.by_status).map(([k, v]) => (
                <div key={k} className="r"><span>{STATUS_AR[k] ?? k} <span className="num muted">({v.count})</span></span><Money v={v.value} /></div>))}
              <div className="r"><span>متوسط العرض</span><Money v={d.quotations.average_value} /></div>
              <div className="r"><span>الخصومات في المقبول</span><Money v={d.quotations.discount_given} /></div>
              <div className="r"><span>مستنية تأكيد المدير</span><span className="num">{d.quotations.waiting_manager}</span></div>
              <div className="r"><span>طلبات خصم</span><span className="num">{d.quotations.discount_requests}</span></div>
            </div>
          </Card>
          <Card title="الفلوس">
            <div className="totals" style={{ width: "100%" }}>
              <div className="r"><span>المتبقي على عملائه</span><Money v={d.invoices.open_balance} /></div>
              <div className="r"><span>تحصيلات مستنية الحسابات <span className="num muted">({d.collections.pending_count})</span></span><Money v={d.collections.pending_amount} /></div>
              <div className="r"><span>تحصيلات مرفوضة</span><span className="num">{d.collections.rejected}</span></div>
            </div>
          </Card>
          <Card title="العملاء والمعاينات">
            <div className="totals" style={{ width: "100%" }}>
              {Object.entries(d.customers.by_contact_method).map(([k, n]) => <div key={k} className="r"><span>{k}</span><span className="num">{n}</span></div>)}
              <div className="r"><span>معاينات في الفترة</span><span className="num">{d.surveys.made}</span></div>
              <div className="r"><span>معاينات مستنية تأكيد المدير</span><span className="num">{d.surveys.waiting_manager}</span></div>
            </div>
          </Card>
        </div>
        <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)" }}>
          <Card title="محتاج متابعة: عروض اتبعتت من أكتر من أسبوع" flush>
            <Table rows={d.quotations.to_follow_up} empty="مفيش 👍" onRow={(q) => go(`quotations/${q.id}`)} columns={[
              { key: "n", label: "العرض", render: (q) => <span className="code">{q.number}</span> },
              { key: "t", label: "القيمة", num: true, render: (q) => <Money v={q.total} /> },
              { key: "d", label: "من", render: (q) => <Chip color="amber">{q.days} يوم</Chip> },
            ]} />
          </Card>
          <Card title="أكبر العملاء" flush>
            <Table rows={d.top_customers} empty="—" columns={[
              { key: "n", label: "العميل", render: (c) => c.name },
              { key: "s", label: "المبيعات", num: true, render: (c) => <Money v={c.sales} /> },
            ]} />
          </Card>
        </div>
        <Card title="آخر 6 شهور" flush>
          <Table rows={d.months} columns={[
            { key: "m", label: "الشهر", render: (m) => <span className="num">{m.month}</span> },
            { key: "q", label: "عروض", num: true, render: (m) => <span className="num">{m.quotations}</span> },
            { key: "s", label: "المبيعات", num: true, render: (m) => <Money v={m.sales} /> },
            { key: "c", label: "التحصيل", num: true, render: (m) => <Money v={m.collected} /> },
          ]} />
        </Card>
      </>}
      {all && team.data && (
        <Card title="الفريق كله" flush>
          <Table rows={team.data.people} empty="—" onRow={(p) => setWho(p.user_id)} columns={[
            { key: "n", label: "الموظف", render: (p) => <b>{p.name}</b> },
            { key: "c", label: "عملاء جداد", num: true, render: (p) => <span className="num">{p.customers_new}</span> },
            { key: "q", label: "عروض", num: true, render: (p) => <span className="num">{p.quotations}</span> },
            { key: "a", label: "مقبول", num: true, render: (p) => <span className="num">{p.accepted} <span className="muted small">({p.conversion_pct}%)</span></span> },
            { key: "s", label: "المبيعات", num: true, render: (p) => <Money v={p.sales} /> },
            { key: "k", label: "التحصيل", num: true, render: (p) => <Money v={p.collected} /> },
            { key: "o", label: "المتبقي", num: true, render: (p) => <Money v={p.open_balance} /> },
          ]} />
        </Card>
      )}
      {moving && <MoveAll people={people.data ?? []} onClose={() => setMoving(false)} onDone={() => { r.reload(); team.reload(); }} />}
    </div>
  );
}

function MoveAll({ people, onClose, onDone }: { people: { id: string; name: string }[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const opts = people.map((p) => ({ value: p.id, label: p.name }));
  const save = () => run(async () => {
    const r = await api.post<{ moved: Record<string, number> }>("/sales/transfer", { from_user_id: from, to_user_id: to });
    toast.ok(`اتنقل ${r.moved.customers ?? 0} عميل و${r.moved.quotations ?? 0} عرض و${r.moved.invoices ?? 0} فاتورة.`);
    onDone(); onClose();
  });
  return (
    <Modal title="نقل كل شغل موظف لموظف تاني" onClose={onClose}
      footer={<><Btn kind="primary" busy={busy} disabled={!from || !to || from === to} onClick={save}>نقل</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2">
        <Field label="من"><Select value={from} onChange={setFrom} placeholder="اختار" options={opts} /></Field>
        <Field label="لـ"><Select value={to} onChange={setTo} placeholder="اختار" options={opts.filter((o) => o.value !== from)} /></Field>
      </div>
      <div className="notice info small mt">كل عملائه ومعايناته وعروضه وفواتيره هتختفي من عنده وتظهر عند الموظف التاني.</div>
    </Modal>
  );
}
