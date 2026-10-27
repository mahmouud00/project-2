import { useState } from "react";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad, when } from "../lib/hooks";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, Confirm, Dim, ErrorBox, Field, Len, Loading, Modal, Money, NumIn, PageHead, Pager, Qty, Select, Table, Tabs, TextIn } from "../components/ui";
import { DeleteBtn } from "../components/actions";
import { AssignJob, Progress } from "../components/field";
import { BranchName, ColorName, CustomerName, ModelThumb, SalespersonName, SalespersonSelect } from "../components/pickers";
import { Issues, ParamLabels, type Issue } from "../components/items";
import { Drawing, MediaImg, PrintPreview } from "../components/media";
import { STAGES, STAGE_COLOR, STAGE_NAMES, UNITS, lookups } from "../lib/lookups";
import { go, setQuery } from "../lib/router";
import { date, dateTime } from "../lib/format";
import { PaymentForm } from "./Treasury";

type WO = S<"WorkOrderOut">;

export default function WorkOrders({ route }: PageProps) {
  const id = route.path[1];
  return id ? <WorkOrderDetail id={id} tab={route.query.tab ?? "items"} /> : <WorkOrderList stage={route.query.stage ?? ""} />;
}

function WorkOrderList({ stage }: { stage: string }) {
  useTitle("أوامر التصنيع");
  const s = useSession();
  const [offset, setOffset] = useState(0);
  const list = useLoad(() => api.get<S<"Page_WorkOrderOut_">>("/work-orders", { stage: stage || undefined, limit: 50, offset }), [stage, offset]);
  const rows = (list.data?.items ?? []).filter((w) => !s.branchId || w.branch_id === s.branchId);
  return (
    <>
      <PageHead>
        <div className="row wrap" style={{ gap: 6 }}>
          <Btn small kind={!stage ? "primary" : undefined} onClick={() => setQuery({ stage: undefined })}>الكل</Btn>
          {[...STAGES, "cancelled"].map((st) => (
            <Btn key={st} small kind={stage === st ? "primary" : undefined} onClick={() => { setOffset(0); setQuery({ stage: st }); }}>{STAGE_NAMES[st]}</Btn>
          ))}
        </div>
      </PageHead>
      {list.error && <ErrorBox text={list.error} onRetry={list.reload} />}
      <Card flush>
        <Table rows={rows} loading={list.loading} onRow={(w) => go(`work-orders/${w.id}`)} columns={[
          { key: "n", label: "الرقم", render: (w) => <span className="num bold">{w.number}</span> },
          { key: "c", label: "العميل", render: (w) => <CustomerName id={w.customer_id} /> },
          { key: "b", label: "الفرع", render: (w) => <BranchName id={w.branch_id} /> },
          { key: "s", label: "المرحلة", render: (w) => <Chip color={STAGE_COLOR[w.stage]}>{STAGE_NAMES[w.stage] ?? w.stage}</Chip> },
          { key: "d", label: "التسليم", render: (w) => <span className="num">{date(w.due_date)}</span> },
          { key: "t", label: "الإجمالي", num: true, render: (w) => <Money v={w.total} /> },
          { key: "p", label: "المدفوع", num: true, render: (w) => <Money v={w.paid_amount} /> },
          { key: "pr", label: "الإنجاز", render: (w) => <Progress pct={w.progress_pct} late={w.late} expected={w.expected_delivery} /> },
          { key: "del", label: "", width: 80, render: (w) => s.can("workorders.delete", w.branch_id) &&
            <DeleteBtn path={`/work-orders/${w.id}`} what={`أمر التصنيع ${w.number}`} onDone={list.reload}
              note="الأمر هيتمسح بس لو مفيش خامات اتصرفت ولا فلوس اتدفعت ولا فاتورة. غير كدا ألغيه من مراحل الأمر." /> },
        ]} empty="مفيش أوامر تصنيع" />
        {list.data && <Pager total={list.data.total} limit={50} offset={offset} onChange={setOffset} />}
      </Card>
    </>
  );
}

function Stepper({ stage }: { stage: string }) {
  const idx = STAGES.indexOf(stage as (typeof STAGES)[number]);
  return (
    <div className="stepper">
      {STAGES.map((st, i) => (
        <div key={st} className="row" style={{ gap: 0 }}>
          {i > 0 && <div className={"step-line" + (i <= idx ? " done" : "")} />}
          <div className={"step" + (i < idx || (i === idx && st === "delivered") ? " done" : i === idx ? " now" : "")}>
            <span className="b num">{i < idx || (i === idx && st === "delivered") ? "✓" : i + 1}</span>{STAGE_NAMES[st]}
          </div>
        </div>
      ))}
      {stage === "cancelled" && <Chip color="red">ملغي</Chip>}
    </div>
  );
}

function WorkOrderDetail({ id, tab }: { id: string; tab: string }) {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const wo = useLoad(() => api.get<WO>(`/work-orders/${id}`), [id]);
  useTitle(wo.data ? `أمر تصنيع ${wo.data.number}` : "…", <a onClick={() => go("work-orders")} style={{ cursor: "pointer" }}>أوامر التصنيع</a>, [wo.data?.number]);
  const [printing, setPrinting] = useState(false);
  const [saleDecision, setSaleDecision] = useState<boolean | null>(null);
  const [paying, setPaying] = useState(false);
  const [cancel, setCancel] = useState(false);
  const [edit, setEdit] = useState(false);
  const [note, setNote] = useState("");
  const [ordering, setOrdering] = useState(false);
  const [assign, setAssign] = useState(false);
  const outputs = useLoad(() => when(tab === "mfg" || tab === "cut", () => api.get<Outputs>(`/work-orders/${id}/manufacturing`)), [id, tab, wo.data?.outputs_generated_at]);
  if (wo.error) return <ErrorBox text={wo.error} onRetry={wo.reload} />;
  if (!wo.data) return <Loading />;
  const w = wo.data;
  const idx = STAGES.indexOf(w.stage as (typeof STAGES)[number]);
  const next = idx >= 0 && idx < STAGES.length - 1 ? STAGES[idx + 1] : null;
  const canStage = s.can("workorders.stage", w.branch_id);
  const frozen = ["manufacturing", "assembly", "quality", "delivered"].includes(w.stage);

  const move = (to: string) => run(async () => {
    wo.set(await api.post<WO>(`/work-orders/${id}/stage`, { version: w.version, to, note }));
    setNote("");
    toast.ok(to === "cancelled" ? "اتلغى الأمر." : `الأمر اتنقل لمرحلة ${STAGE_NAMES[to]}.`);
  });
  const regen = () => run(async () => {
    await api.post(`/work-orders/${id}/manufacturing/generate`);
    await wo.reload();
    toast.ok("اتعملت مخرجات التصنيع من جديد.");
  });
  const invoice = () => run(async () => {
    const inv = await api.post<S<"InvoiceOut">>("/invoices", { work_order_id: id });
    go(`invoices/${inv.id}`);
  });

  return (
    <div className="col" style={{ gap: 14 }}>
      <Card>
        <div className="row wrap" style={{ gap: 18 }}>
          <div><div className="muted small">العميل</div><a style={{ cursor: "pointer", fontWeight: 700 }} onClick={() => go(`customers/${w.customer_id}`)}><CustomerName id={w.customer_id} /></a></div>
          <div><div className="muted small">الفرع</div><BranchName id={w.branch_id} /></div>
          <div><div className="muted small">التسليم</div><span className="num">{date(w.due_date)}</span></div>
          <div><div className="muted small">الإجمالي</div><b><Money v={w.total} /></b></div>
          <div><div className="muted small">العربون المطلوب</div><Money v={w.deposit_required} /></div>
          <div><div className="muted small">المدفوع</div><span className={Number(w.paid_amount) >= Number(w.deposit_required) ? "success-text bold" : "bold"}><Money v={w.paid_amount} /></span></div>
          <div><div className="muted small">البائع</div><SalespersonName id={w.salesperson_id} /></div>
          {w.quotation_id && <div><div className="muted small">تأكيد الحسابات</div><Chip color={SALE_STATUS[w.sale_status ?? "pending"][1]}
            >{SALE_STATUS[w.sale_status ?? "pending"][0]}</Chip>{w.sale_approval_note && <div className="small muted">{w.sale_approval_note}</div>}</div>}
          <div style={{ minWidth: 170 }}><div className="muted small">الإنجاز{w.expected_delivery ? ` · متوقع ${date(w.expected_delivery)}` : ""}</div>
            <Progress pct={w.progress_pct} late={w.late} /></div>
          <div className="end row wrap">
            <Btn icon="print" onClick={() => setPrinting(true)}>كشف التقطيع</Btn>
            {s.can("purchasing.create", w.branch_id) && w.stage !== "cancelled" && <Btn icon="cart" onClick={() => setOrdering(true)}>طلبية بضاعة</Btn>}
            {s.can("field.manage", w.branch_id) && w.stage !== "cancelled" &&
              <Btn icon="truck" onClick={() => setAssign(true)}>مهمة تركيب</Btn>}
            {w.quotation_id && w.sale_status !== "approved" && ["survey", "quotation"].includes(w.stage) && s.can("sales.approve", w.branch_id) && <>
              <Btn kind="success" icon="check" onClick={() => setSaleDecision(true)}>تأكيد البيعة</Btn>
              {w.sale_status !== "rejected" && <Btn kind="danger" onClick={() => setSaleDecision(false)}>رفض البيعة</Btn>}</>}
            {s.can("workorders.write", w.branch_id) && !frozen && <Btn icon="edit" onClick={() => setEdit(true)}>تعديل</Btn>}
            {s.can("treasury.create", w.branch_id) && w.stage !== "cancelled" && <Btn icon="cash" onClick={() => setPaying(true)}>تحصيل</Btn>}
            {s.can("invoices.create", w.branch_id) && w.stage !== "cancelled" && w.quotation_id && <Btn icon="invoice" busy={busy} onClick={invoice}>فاتورة</Btn>}
            {s.can("workorders.delete", w.branch_id) &&
              <DeleteBtn small={false} path={`/work-orders/${id}`} what={`أمر التصنيع ${w.number}`} onDone={() => go("work-orders")}
                note="الأمر هيتمسح بس لو مفيش فلوس اتدفعت ولا فاتورة. غير كدا ألغيه من مراحل الأمر." />}
          </div>
        </div>
        <div className="mt"><Stepper stage={w.stage} /></div>
        {canStage && w.stage !== "cancelled" && w.stage !== "delivered" && (
          <div className="row mt wrap">
            <div style={{ width: 280 }}><TextIn value={note} onChange={setNote} placeholder="ملاحظة على النقل (اختياري)" /></div>
            {next && <Btn kind="primary" icon="arrow" busy={busy} disabled={next === "approved" && w.sale_status !== "approved"}
              onClick={() => move(next)}>نقل لـ {STAGE_NAMES[next]}</Btn>}
            {next === "approved" && w.sale_status !== "approved" && <span className="muted small">مستني تأكيد الحسابات على البيعة.</span>}
            <Btn kind="danger" icon="ban" className="end" onClick={() => setCancel(true)}>إلغاء الأمر</Btn>
          </div>
        )}
      </Card>

      <Card flush>
        <Tabs value={tab} onChange={(t) => setQuery({ tab: t })} tabs={[
          { id: "items", label: "الأصناف", count: w.items?.length },
          { id: "mfg", label: "التقطيع والزجاج والإكسسوار" },
          { id: "cut", label: "خطة الأعواد" },
          { id: "log", label: "سجل المراحل", count: w.stage_log?.length },
        ]} />
        {tab === "items" && <Table rows={w.items} columns={[
          { key: "p", label: "#", width: 36, render: (i) => <span className="num muted">{i.position}</span> },
          { key: "img", label: "", width: 76, render: (i) => <ModelThumb modelId={i.model_id} /> },
          { key: "m", label: "الصنف", render: (i) => <div><ModelLabel id={i.model_id} />{i.location && <span className="muted"> · {i.location}</span>}
            <div><ParamLabels modelId={i.model_id} values={i.params} /></div></div> },
          { key: "s", label: "الفتحة (عرض × ارتفاع)", render: (i) => <Dim w={i.opening_width_mm} h={i.opening_height_mm} /> },
          { key: "c", label: "اللون", render: (i) => <ColorName code={i.color_code} /> },
          { key: "g", label: "الزجاج", render: (i) => <span className="muted">{i.glass_material_code ?? "—"}</span> },
          { key: "q", label: "العدد", num: true, render: (i) => <span className="num">{i.qty}</span> },
          { key: "u", label: "سعر الوحدة", num: true, render: (i) => <Money v={i.unit_price} /> },
        ]} />}
        {(tab === "mfg" || tab === "cut") && (
          <div className="card-b col">
            <div className="row">
              {w.outputs_generated_at ? <span className="muted small">اتعملت في <span className="num">{dateTime(w.outputs_generated_at as string)}</span>{frozen && " · مجمّدة بعد بدء التصنيع"}</span>
                : <span className="muted small">معاينة (هتتجمد لما التصنيع يبدأ)</span>}
              {!frozen && s.can("workorders.write", w.branch_id) && <Btn small icon="refresh" busy={busy} className="end" onClick={regen}>إعادة الحساب</Btn>}
            </div>
            {outputs.error && <ErrorBox text={outputs.error} />}
            {outputs.loading && !outputs.data && <Loading />}
            {outputs.data && (tab === "mfg" ? <Manufacturing o={outputs.data} /> : <BarPlans o={outputs.data} />)}
          </div>
        )}
        {tab === "log" && <Table rows={w.stage_log} rowKey={(_, i) => String(i)} columns={[
          { key: "at", label: "الوقت", render: (l) => <span className="num">{dateTime(l.at as string)}</span> },
          { key: "f", label: "من", render: (l) => l.from_stage ? STAGE_NAMES[l.from_stage] : "—" },
          { key: "t", label: "إلى", render: (l) => <Chip color={STAGE_COLOR[l.to_stage]}>{STAGE_NAMES[l.to_stage] ?? l.to_stage}</Chip> },
          { key: "n", label: "ملاحظة", render: (l) => <span className="muted">{l.note}</span> },
        ]} />}
      </Card>

      {ordering && <GoodsOrder wo={w} onClose={() => setOrdering(false)} />}
      {assign && <AssignJob job={{ kind: "installation", customer_id: w.customer_id, branch_id: w.branch_id, work_order_id: w.id }}
        onClose={() => setAssign(false)} onSaved={() => undefined} />}
      {printing && <PrintPreview path={`/work-orders/${id}/print/cut-list`} title={`كشف تقطيع ${w.number}`} onClose={() => setPrinting(false)} />}
      {saleDecision !== null && <SaleDecisionForm wo={w} approve={saleDecision} onClose={() => setSaleDecision(null)} onSaved={(x) => wo.set(x)} />}
      {paying && <PaymentForm onClose={() => setPaying(false)} onSaved={() => wo.reload()}
        initial={{ direction: "in", party_type: "customer", party_id: w.customer_id, work_order_id: w.id }} />}
      {cancel && <Confirm title="إلغاء أمر التصنيع" danger yes="إلغاء الأمر" busy={busy} onClose={() => setCancel(false)}
        onYes={() => { move("cancelled"); setCancel(false); }} text="الأمر هيتلغي ومش هيرجع. الحركات المالية بتفضل وتتصحح بحركة عكسية." />}
      {edit && <WorkOrderEdit wo={w} onClose={() => setEdit(false)} onSaved={(x) => wo.set(x)} />}
    </div>
  );
}

function ModelLabel({ id }: { id: string }) {
  const m = useLoad(() => lookups.model(id), [id]);
  return <b>{m.data?.name ?? "…"}</b>;
}

function WorkOrderEdit({ wo, onClose, onSaved }: { wo: WO; onClose: () => void; onSaved: (w: WO) => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState({ due_date: wo.due_date ?? "", notes: wo.notes, deposit_required: wo.deposit_required,
    salesperson_id: wo.salesperson_id ?? null });
  return (
    <Modal title="بيانات أمر التصنيع" onClose={onClose} footer={<><Btn kind="primary" busy={busy} onClick={() => run(async () => {
      onSaved(await api.patch<WO>(`/work-orders/${wo.id}`, { version: wo.version, due_date: d.due_date || null, notes: d.notes,
        deposit_required: d.deposit_required, ...(d.salesperson_id ? { salesperson_id: d.salesperson_id } : {}) }));
      onClose();
    })}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col">
        <Field label="تاريخ التسليم"><input type="date" className="input" value={d.due_date} onChange={(e) => setD((x) => ({ ...x, due_date: e.target.value }))} /></Field>
        <Field label="العربون المطلوب"><NumIn value={d.deposit_required} onChange={(v) => setD((x) => ({ ...x, deposit_required: v }))} /></Field>
        <Field label="البائع (السيلز)"><SalespersonSelect value={d.salesperson_id} onChange={(v) => setD((x) => ({ ...x, salesperson_id: v }))} /></Field>
        <Field label="ملاحظات"><TextIn value={d.notes} onChange={(v) => setD((x) => ({ ...x, notes: v }))} /></Field>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- manufacturing outputs
type CutPiece = { length_mm: string; angle_left?: string; angle_right?: string; label?: string; element?: string | null;
  side?: "width" | "height" | null; qty: number; refs?: string[] };
type Outputs = {
  cut_list: { sku: string; material_code: string; material_name: string; pieces: CutPiece[]; total_pieces: number; total_length_mm: string }[];
  optimisation: { sku: string; bar_length_mm: string; bars_count: number; bars: { bar_no: number; pieces: { length_mm: string; label?: string }[]; used_mm: string;
    offcut_mm: string; offcut_reusable: boolean; waste_mm: string; length_mm?: string; from_offcut?: string | null }[]; waste_pct: string;
    reusable_offcuts_mm: (string | number)[]; offcuts_used?: { id: string; length_mm: string }[];
    too_long?: unknown[] }[];
  waste_pct?: string;
  glass: { item: number; location: string; label: string; material_code: string; width_mm: string; height_mm: string; qty: number; area_m2: string }[];
  glass_area_by_type: Record<string, string>;
  accessories: { sku: string; material_code: string; material_name: string; qty: string; unit: string }[];
  costs: { type: string; sku: string; qty: string; unit: string; unit_cost: string | null; amount: string | null }[];
  material_cost_total: string; missing_costs?: string[];
  drawings: { item: number; location: string; qty: number; model_name: string; model_image_id: string | null; opening_width_mm: string;
    opening_height_mm: string; width_mm: string; height_mm: string; elements: any[] }[];
  issues: Issue[];
};

function Manufacturing({ o }: { o: Outputs }) {
  const s = useSession();
  return (
    <div className="col" style={{ gap: 14 }}>
      <Issues issues={o.issues} />
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
        {o.drawings.map((d) => (
          <div key={d.item} className="card" style={{ padding: 12 }}>
            <div className="row top">
              <MediaImg id={d.model_image_id} />
              <div className="grow"><b>{d.model_name}</b><div className="muted small">{d.location} · عدد <span className="num">{d.qty}</span></div>
                <div className="small">فتحة <Dim w={d.opening_width_mm} h={d.opening_height_mm} /></div>
                <div className="small">تصنيع <Dim w={d.width_mm} h={d.height_mm} /></div></div>
              <Drawing elements={d.elements} w={d.width_mm} h={d.height_mm} maxW={110} maxH={90} />
            </div>
          </div>
        ))}
      </div>
      {o.cut_list.map((m) => (
        <div key={m.sku} className="card">
          <div className="card-h"><h3>{m.material_name}</h3><span className="code">{m.sku}</span>
            <span className="end muted small">القطع <span className="num">{m.total_pieces}</span> · الطول <span className="num"><Len mm={m.total_length_mm} /></span> {s.unit === "cm" ? "سم" : "مم"}</span></div>
          <div className="card-b flush">
            <table>
              <thead><tr><th>العنصر</th><th>عرض / ارتفاع</th><th className="n">الطول ({s.unit === "cm" ? "سم" : "مم"})</th><th className="n">العدد</th><th>الزاوية</th><th>للأصناف</th></tr></thead>
              <tbody>
                {m.pieces.map((p, i) => (
                  <tr key={i}>
                    <td><b>{p.element || p.label}</b></td>
                    <td>{p.side === "width" ? <span className="side-w bold">عرض</span> : p.side === "height" ? <span className="side-h bold">ارتفاع</span> : <span className="faint">{p.label}</span>}</td>
                    <td className="n"><b><Len mm={p.length_mm} /></b></td>
                    <td className="n num">{p.qty}</td>
                    <td className="num">{p.angle_left}° / {p.angle_right}°</td>
                    <td className="muted small">{(p.refs ?? []).join("، ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
      <div className="grid g2">
        <Card title="الزجاج" flush>
          <Table rows={o.glass} rowKey={(_, i) => String(i)} columns={[
            { key: "i", label: "الصنف", render: (g) => <span><span className="num">{g.item}</span> {g.location}</span> },
            { key: "t", label: "النوع", render: (g) => <span className="code">{g.material_code}</span> },
            { key: "s", label: "المقاس (عرض × ارتفاع)", render: (g) => <Dim w={g.width_mm} h={g.height_mm} /> },
            { key: "q", label: "العدد", num: true, render: (g) => <span className="num">{g.qty}</span> },
            { key: "a", label: "م²", num: true, render: (g) => <Qty v={g.area_m2} /> },
          ]} />
        </Card>
        <Card title="الإكسسوار" flush>
          <Table rows={o.accessories} rowKey={(a) => a.sku} columns={[
            { key: "n", label: "الصنف", render: (a) => a.material_name },
            { key: "c", label: "الكود", render: (a) => <span className="code">{a.sku}</span> },
            { key: "q", label: "الكمية", num: true, render: (a) => <span><Qty v={a.qty} /> <span className="muted small">{a.unit}</span></span> },
          ]} />
        </Card>
      </div>
      {s.can("finance.read") && (
        <Card title="تكلفة الخامات" flush actions={<b><Money v={o.material_cost_total} cur /></b>}>
          {!!o.missing_costs?.length && <div className="card-b"><div className="notice warn">خامات من غير تكلفة: {o.missing_costs.join("، ")}</div></div>}
          <Table rows={o.costs} rowKey={(_, i) => String(i)} columns={[
            { key: "s", label: "الكود", render: (c) => <span className="code">{c.sku}</span> },
            { key: "q", label: "الكمية", num: true, render: (c) => <span><Qty v={c.qty} /> <span className="muted small">{c.unit}</span></span> },
            { key: "u", label: "سعر الوحدة", num: true, render: (c) => <Money v={c.unit_cost} /> },
            { key: "a", label: "القيمة", num: true, render: (c) => <Money v={c.amount} /> },
          ]} />
        </Card>
      )}
    </div>
  );
}

function BarPlans({ o }: { o: Outputs }) {
  const s = useSession();
  const names = Object.fromEntries(o.cut_list.map((c) => [c.sku, c.material_name]));
  return (
    <div className="col" style={{ gap: 14 }}>
      {o.optimisation.map((m) => {
        const bar = Number(m.bar_length_mm) || 1;
        return (
          <div key={m.sku} className="card">
            <div className="card-h"><h3>{names[m.sku] ?? m.sku}</h3><span className="code">{m.sku}</span>
              <span className="end muted small">العود <Len mm={m.bar_length_mm} /> {s.unit === "cm" ? "سم" : "مم"} · <b className="num">{m.bars_count}</b> عود جديد
                {!!m.offcuts_used?.length && <> + <b className="num">{m.offcuts_used.length}</b> باقي من المخزون</>} · الهالك <b className="num">{Number(m.waste_pct)}%</b></span></div>
            <div className="card-b col" style={{ gap: 6 }}>
              {m.bars.map((b) => (
                <div key={b.bar_no} className="row">
                  <span className="num muted small" style={{ width: 24 }} title={b.from_offcut ? "باقي من المخزون" : ""}>{b.from_offcut ? "♻" : b.bar_no}</span>
                  <div className="bar-plan" style={{ width: `${(Number(b.length_mm ?? bar) / bar) * 100}%` }}>
                    {b.pieces.map((p, i) => <span key={i} style={{ width: `${(Number(p.length_mm) / Number(b.length_mm ?? bar)) * 100}%` }} title={`${p.label ?? ""} ${s.len(p.length_mm)}`}>{s.len(p.length_mm)}</span>)}
                    {Number(b.offcut_mm) > 0 && <span className={b.offcut_reusable ? "off" : "waste"} style={{ width: `${(Number(b.offcut_mm) / Number(b.length_mm ?? bar)) * 100}%` }}
                      title={(b.offcut_reusable ? "باقي يتشال " : "هالك ") + s.len(b.offcut_mm)}>{s.len(b.offcut_mm)}</span>}
                  </div>
                </div>
              ))}
              {!!m.reusable_offcuts_mm?.length && <div className="muted small">فُضل هتتشال (٤٠ سم وأكتر): <span className="num">{m.reusable_offcuts_mm.map((x) => s.len(x)).join("، ")}</span></div>}
            </div>
          </div>
        );
      })}
      <div className="row small muted"><span className="swatch" style={{ background: "var(--primary-soft)" }} /> قطع
        <span className="swatch" style={{ background: "var(--success-soft)" }} /> باقي يرجع المخزن
        <span className="swatch" style={{ background: "var(--danger-soft)" }} /> هالك</div>
    </div>
  );
}


type Need = S<"NeedOut"> & { include: boolean };
const NEED_KIND: Record<string, string> = { profile: "قطاع", glass: "زجاج", accessory: "إكسسوار" };

/** The order's needs (deductions after cutting optimisation, glass, each model's accessories) as a draft purchase
 *  order for this customer: pick the supplier, adjust, save. */
function GoodsOrder({ wo, onClose }: { wo: WO; onClose: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [lines, setLines] = useState<Need[] | null>(null);
  const [supplier, setSupplier] = useState("");
  const sups = useLoad(() => lookups.suppliers(), []);
  useLoad(() => api.get<S<"NeedOut">[]>(`/work-orders/${wo.id}/material-needs`).then((n) => setLines(n.map((x) => ({ ...x, include: true })))), [wo.id]);
  const qtyOf = (n: Need) => Number(n.qty);
  const set = (i: number, patch: Partial<Need>) => setLines((x) => x!.map((l, j) => j === i ? { ...l, ...patch } : l));
  const chosen = (lines ?? []).filter((n) => n.include && qtyOf(n) > 0);
  const total = chosen.reduce((t, n) => t + qtyOf(n) * Number(n.unit_cost ?? 0), 0);
  return (
    <Modal title={`طلبية بضاعة · أمر ${wo.number}`} size="xwide" onClose={onClose} footer={<>
      <Btn kind="primary" busy={busy} disabled={!supplier || !chosen.length} onClick={() => run(async () => {
        const po = await api.post<S<"POOut">>("/purchase-orders", { supplier_id: supplier, branch_id: wo.branch_id,
          work_order_id: wo.id, notes: `طلبية أمر التصنيع ${wo.number}`,
          lines: chosen.map((n) => ({ sku: n.sku, qty: String(qtyOf(n).toFixed(3)), unit_cost: String(n.unit_cost ?? 0) })) });
        toast.ok(`اتعمل أمر الشراء ${po.number}، ومستني تأكيد الحسابات.`);
        go(`purchasing/${po.id}`);
      })}>حفظ أمر الشراء</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g3 mb">
        <Field label="المورد"><Select value={supplier} onChange={setSupplier} placeholder="اختار المورد"
          options={(sups.data ?? []).map((x) => ({ value: x.id, label: x.name }))} /></Field>
      </div>
      {!lines ? <Loading /> : (
        <Table rows={lines} rowKey={(n) => n.sku} empty="مفيش خامات (اتأكد إن الأمر فيه بنود محسوبة)" columns={[
          { key: "i", label: "", width: 40, render: (n, i) => <input type="checkbox" checked={n.include} onChange={(e) => set(i, { include: e.target.checked })} /> },
          { key: "k", label: "النوع", render: (n) => <Chip color={n.kind === "profile" ? "violet" : n.kind === "glass" ? "blue" : "gray"}>{NEED_KIND[n.kind] ?? n.kind}</Chip> },
          { key: "s", label: "الكود", render: (n) => <span className="code">{n.sku}</span> },
          { key: "n", label: "الخامة", render: (n) => n.name },
          { key: "b", label: "التفاصيل", render: (n) => <span className="small muted">{n.bars ? `${n.bars} عود × ${Number(n.bar_length_mm) / 1000} م`
            : n.pieces ? `${n.pieces} لوح` : ""}{n.offcuts_used ? ` · + ${n.offcuts_used} باقي من المخزون` : ""}</span> },
          { key: "q", label: "الكمية", num: true, render: (n) => <span className="num bold">{qtyOf(n).toLocaleString("en", { maximumFractionDigits: 3 })} {UNITS[n.unit] ?? n.unit}</span> },
          { key: "c", label: "سعر الوحدة", num: true, width: 130, render: (n, i) => <NumIn value={String(n.unit_cost ?? "")} onChange={(v) => set(i, { unit_cost: v || null })} /> },
        ]} />
      )}
      <div className="row mt"><span className="muted small">القطاعات بأعواد كاملة (بعد تحسين التقطيع) بالمتر، والزجاج بالمتر المربع، والإكسسوار حسب كل نموذج × عدد الوحدات.</span>
        <b className="end">الإجمالي التقريبي: <Money v={total.toFixed(2)} /></b></div>
    </Modal>
  );
}

export const SALE_STATUS: Record<string, [string, "gray" | "green" | "red"]> = {
  pending: ["مستني الحسابات", "gray"], approved: ["الحسابات أكدت", "green"], rejected: ["الحسابات رفضت", "red"] };

/** The accounts confirm (or refuse) a sale: price, discount and deposit, before the order is approved and made. */
export function SaleDecisionForm({ wo, approve, onClose, onSaved }: { wo: WO; approve: boolean; onClose: () => void; onSaved: (w: WO) => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [note, setNote] = useState("");
  return (
    <Modal title={`${approve ? "تأكيد" : "رفض"} البيعة ${wo.number}`} onClose={onClose} footer={<>
      <Btn kind={approve ? "success" : "solid-danger"} busy={busy} disabled={!approve && !note.trim()} onClick={() => run(async () => {
        onSaved(await api.post<WO>(`/work-orders/${wo.id}/approve-sale`, { version: wo.version, approve, note }));
        toast.ok(approve ? "اتأكدت البيعة." : "اترفضت البيعة.");
        onClose();
      })}>{approve ? "تأكيد" : "رفض"}</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col">
        <div className="row wrap" style={{ gap: 16 }}><span>العميل: <b><CustomerName id={wo.customer_id} /></b></span>
          <span>الإجمالي: <b><Money v={wo.total} cur /></b></span><span>العربون المطلوب: <Money v={wo.deposit_required} /></span>
          <span>المدفوع: <Money v={wo.paid_amount} /></span></div>
        <Field label={approve ? "ملاحظة (اختياري)" : "سبب الرفض"}><TextIn value={note} onChange={setNote} /></Field>
      </div>
    </Modal>
  );
}
