import { api, type S } from "../api/client";
import { useTitle } from "../lib/title";
import { useLoad, when } from "../lib/hooks";
import { useSession } from "../state/session";
import { Card, Chip, Money, Table, Btn } from "../components/ui";
import { Icon } from "../components/icons";
import { CustomerName } from "../components/pickers";
import { QUOTE_STATUS, STAGES, STAGE_COLOR, STAGE_NAMES, INVOICE_STATUS } from "../lib/lookups";
import { date, sumMoney } from "../lib/format";
import { go } from "../lib/router";


export default function Dashboard() {
  const s = useSession();
  const name = s.company.branding?.name || s.company.name;
  useTitle("لوحة التحكم", name);
  const wos = useLoad(() => when(s.can("workorders.read"), () => api.get<S<"Page_WorkOrderOut_">>("/work-orders", { limit: 500 })), []);
  const quotes = useLoad(() => when(s.can("quotes.read"), () => api.get<S<"Page_QuotationOut_">>("/quotations", { limit: 8 })), []);
  const invoices = useLoad(() => when(s.can("treasury.read"), () => api.get<S<"Page_InvoiceOut_">>("/invoices", { status: "issued", limit: 500 })), []);
  const boxes = useLoad(() => when(s.can("treasury.read"), () => api.get<S<"CashboxOut">[]>("/cashboxes")), []);

  const open = (wos.data?.items ?? []).filter((w) => w.stage !== "delivered" && w.stage !== "cancelled");
  const byStage = STAGES.map((st) => ({ st, n: open.filter((w) => w.stage === st).length }));
  const unpaid = (invoices.data?.items ?? []).filter((i) => Number(i.balance ?? 0) > 0);
  const pending = (quotes.data?.items ?? []).filter((q) => q.status === "draft" || q.status === "sent");

  const kpis = [
    { label: "أوامر شغالة", value: String(open.length), icon: "factory", color: "var(--primary)", show: s.can("workorders.read"), to: "work-orders" },
    { label: "عروض مستنية رد", value: String(pending.length), icon: "quote", color: "var(--violet)", show: s.can("quotes.read"), to: "quotations" },
    { label: "مستحق على العملاء", value: <Money v={sumMoney(unpaid.map((i) => i.balance))} />, icon: "invoice", color: "var(--warning)",
      show: s.can("treasury.read"), to: "invoices" },
    { label: "رصيد الخزائن", value: <Money v={sumMoney((boxes.data ?? []).map((b) => b.balance))} />, icon: "cash", color: "var(--success)",
      show: s.can("treasury.read"), to: "treasury" },
  ].filter((k) => k.show);

  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="grid g4">
        {kpis.map((k) => (
          <div key={k.label} className="card kpi click" style={{ cursor: "pointer" }} onClick={() => go(k.to)}>
            <div className="row">
              <div className="grow">
                <div className="label">{k.label}</div>
                <div className="value">{k.value}</div>
              </div>
              <div className="ic" style={{ color: k.color, background: `color-mix(in srgb, ${k.color} 14%, transparent)` }}><Icon name={k.icon} /></div>
            </div>
          </div>
        ))}
      </div>

      {s.can("workorders.read") && (
        <Card title="أوامر التصنيع حسب المرحلة" actions={<Btn small kind="ghost" onClick={() => go("work-orders")}>كل الأوامر</Btn>}>
          <div className="grid" style={{ gridTemplateColumns: `repeat(${STAGES.length}, minmax(0,1fr))` }}>
            {byStage.map(({ st, n }) => (
              <button key={st} className="card" style={{ padding: 12, cursor: "pointer", textAlign: "start" }} onClick={() => go("work-orders", { stage: st })}>
                <Chip color={STAGE_COLOR[st]}>{STAGE_NAMES[st]}</Chip>
                <div style={{ fontSize: 22, fontWeight: 800, marginTop: 6 }} className="num">{n}</div>
              </button>
            ))}
          </div>
        </Card>
      )}

      <div className="grid g2">
        {s.can("quotes.read") && (
          <Card title="آخر عروض الأسعار" flush actions={<Btn small kind="ghost" onClick={() => go("quotations")}>الكل</Btn>}>
            <Table rows={quotes.data?.items} loading={quotes.loading} onRow={(q) => go(`quotations/${q.id}`)} columns={[
              { key: "number", label: "الرقم", render: (q) => <span className="num">{q.number}</span> },
              { key: "c", label: "العميل", render: (q) => <CustomerName id={q.customer_id} /> },
              { key: "st", label: "الحالة", render: (q) => <Chip color={QUOTE_STATUS[q.status]?.[1]}>{QUOTE_STATUS[q.status]?.[0] ?? q.status}</Chip> },
              { key: "total", label: "الإجمالي", num: true, render: (q) => <Money v={q.total} /> },
            ]} />
          </Card>
        )}
        {s.can("treasury.read") && (
          <Card title="فواتير عليها مستحقات" flush actions={<Btn small kind="ghost" onClick={() => go("invoices")}>الكل</Btn>}>
            <Table rows={unpaid.slice(0, 8)} loading={invoices.loading} onRow={(i) => go(`invoices/${i.id}`)} empty="مفيش مستحقات" columns={[
              { key: "number", label: "الرقم", render: (i) => <span className="num">{i.number ?? "—"}</span> },
              { key: "c", label: "العميل", render: (i) => <CustomerName id={i.customer_id} /> },
              { key: "d", label: "الاستحقاق", render: (i) => <span className="num">{date(i.due_date)}</span> },
              { key: "st", label: "الحالة", render: (i) => <Chip color={INVOICE_STATUS[i.status]?.[1]}>{INVOICE_STATUS[i.status]?.[0]}</Chip> },
              { key: "b", label: "الباقي", num: true, render: (i) => <b><Money v={i.balance} /></b> },
            ]} />
          </Card>
        )}
      </div>
    </div>
  );
}
