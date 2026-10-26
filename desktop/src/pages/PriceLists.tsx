import { useState } from "react";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad } from "../lib/hooks";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, Field, Modal, NumIn, PageHead, Select, Table, TextIn } from "../components/ui";
import { RowsEditor } from "../components/rows";
import { DeleteBtn } from "../components/actions";
import { useSession } from "../state/session";
import { CUSTOMER_TYPES, invalidate, lookups } from "../lib/lookups";
import { clean } from "../lib/format";

type PL = S<"PriceListOut">;

export default function PriceLists(_: PageProps) {
  useTitle("قوائم الأسعار");
  const [edit, setEdit] = useState<Partial<PL> | null>(null);
  const list = useLoad(() => api.get<PL[]>("/price-lists"), []);
  const s = useSession();
  return (
    <div className="col">
      <div className="notice info">سعر الشباك = تكلفة الخامات (من المعادلات المنشورة وأسعار شركتك) + الهالك + المصنعية للمتر + هامش الربح. تقدر تحدد هامش أو سعر متر مختلف لنموذج أو قطاع معين.</div>
      <PageHead>{s.can("pricelists.create") && <Btn kind="primary" icon="plus" onClick={() => setEdit({ margin_pct: "25", labor_cost_per_m2: "0", min_unit_price: "0", items: [] })}>قائمة جديدة</Btn>}</PageHead>
      <Card flush>
        <Table rows={list.data} loading={list.loading} onRow={(p) => setEdit(p)} columns={[
          { key: "c", label: "الكود", render: (p) => <span className="code">{p.code}</span> },
          { key: "n", label: "الاسم", render: (p) => <b>{p.name}</b> },
          { key: "t", label: "لنوع العميل", render: (p) => p.customer_type ? CUSTOMER_TYPES[p.customer_type] ?? p.customer_type : <span className="faint">—</span> },
          { key: "m", label: "هامش الربح", num: true, render: (p) => <span className="num">{clean(p.margin_pct)}%</span> },
          { key: "l", label: "مصنعية المتر", num: true, render: (p) => <span className="num">{clean(p.labor_cost_per_m2)}</span> },
          { key: "i", label: "استثناءات", num: true, render: (p) => <span className="num">{p.items?.length ?? 0}</span> },
          { key: "a", label: "الحالة", render: (p) => p.is_active ? <Chip color="green">نشطة</Chip> : <Chip color="red">متوقفة</Chip> },
          { key: "del", label: "", width: 80, render: (p) => s.can("pricelists.delete") &&
            <DeleteBtn path={`/price-lists/${p.id}`} what={`قائمة ${p.name}`} onDone={() => { invalidate("priceLists"); list.reload(); }} /> },
        ]} empty="مفيش قوائم أسعار" />
      </Card>
      {edit && <PLForm pl={edit} onClose={() => setEdit(null)} onSaved={() => { invalidate("priceLists"); list.reload(); }} />}
    </div>
  );
}

function PLForm({ pl, onClose, onSaved }: { pl: Partial<PL>; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState(pl);
  const [items, setItems] = useState<S<"PriceListItemIn">[]>((pl.items ?? []).map((i) => ({ ...i })));
  const models = useLoad(() => lookups.allModels(), []);
  const systems = useLoad(() => lookups.systems(), []);
  const set = (k: keyof PL) => (v: any) => setD((x) => ({ ...x, [k]: v }));
  const save = () => run(async () => {
    const body = { name: d.name, customer_type: d.customer_type || null, margin_pct: d.margin_pct, labor_cost_per_m2: d.labor_cost_per_m2,
      min_unit_price: d.min_unit_price, items: items.map((i) => ({ model_id: i.model_id || null, system_id: i.system_id || null,
        margin_pct: i.margin_pct || null, price_per_m2: i.price_per_m2 || null })) };
    if (pl.id) await api.patch(`/price-lists/${pl.id}`, { ...body, version: pl.version, is_active: d.is_active });
    else await api.post("/price-lists", { ...body, code: d.code });
    toast.ok("اتحفظت قائمة الأسعار.");
    onSaved();
    onClose();
  });
  return (
    <Modal title={pl.id ? `قائمة ${pl.name}` : "قائمة أسعار جديدة"} size="wide" onClose={onClose}
      footer={<><Btn kind="primary" busy={busy} disabled={!d.code || !d.name} onClick={save}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g3">
        <Field label="الكود"><TextIn value={d.code} onChange={set("code")} code disabled={!!pl.id} autoFocus /></Field>
        <Field label="الاسم"><TextIn value={d.name} onChange={set("name")} /></Field>
        <Field label="افتراضية لنوع العميل"><Select value={d.customer_type ?? ""} onChange={set("customer_type")} placeholder="—"
          options={Object.entries(CUSTOMER_TYPES).map(([value, label]) => ({ value, label }))} /></Field>
        <Field label="هامش الربح"><NumIn value={d.margin_pct} onChange={set("margin_pct")} unit="%" /></Field>
        <Field label="مصنعية المتر المربع"><NumIn value={d.labor_cost_per_m2} onChange={set("labor_cost_per_m2")} /></Field>
        <Field label="أقل سعر للوحدة"><NumIn value={d.min_unit_price} onChange={set("min_unit_price")} /></Field>
        {pl.id && <Field label="الحالة"><Select value={d.is_active ? "1" : "0"} onChange={(v) => set("is_active")(v === "1")}
          options={[{ value: "1", label: "نشطة" }, { value: "0", label: "متوقفة" }]} /></Field>}
      </div>
      <h4 style={{ margin: "16px 0 6px" }}>استثناءات لنموذج أو قطاع</h4>
      <RowsEditor rows={items} onChange={setItems} addLabel="استثناء" blank={() => ({ model_id: null, system_id: null, margin_pct: null, price_per_m2: null })} columns={[
        { key: "system_id", label: "القطاع", kind: "select", placeholder: "—", options: (systems.data ?? []).map((x) => ({ value: x.id, label: x.name })) },
        { key: "model_id", label: "أو النموذج", kind: "select", placeholder: "—", options: (models.data ?? []).map((m) => ({ value: m.id, label: `${m.name} (${m.system.code})` })) },
        { key: "margin_pct", label: "هامش %", kind: "number", width: 100 },
        { key: "price_per_m2", label: "أو سعر المتر", kind: "number", width: 120 },
      ]} />
    </Modal>
  );
}
