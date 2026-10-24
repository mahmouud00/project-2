import { useState } from "react";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad } from "../lib/hooks";
import { useDefaultBranch, useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, Confirm, Dim, ErrorBox, Field, Loading, Modal, PageHead, Pager, Select, Table, TextArea, TextIn } from "../components/ui";
import { BranchName, BranchSelect, ColorName, CustomerName, CustomerPicker, ModelThumb } from "../components/pickers";
import { ItemForm, ParamLabels, type ItemDraft } from "../components/items";
import { SURVEY_STATUS, lookups } from "../lib/lookups";
import { go } from "../lib/router";
import { date } from "../lib/format";

type Survey = S<"SurveyOut">;
type Opening = S<"OpeningOut">;

export default function Surveys({ route }: PageProps) {
  const id = route.path[1];
  if (id === "new") return <NewSurvey customerId={route.query.customer} />;
  return id ? <SurveyDetail id={id} /> : <SurveyList />;
}

function SurveyList() {
  useTitle("المعاينات");
  const s = useSession();
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const list = useLoad(() => api.get<S<"Page_SurveyOut_">>("/surveys", { status: status || undefined, limit: 50, offset }), [status, offset]);
  const rows = (list.data?.items ?? []).filter((x) => !s.branchId || x.branch_id === s.branchId);
  return (
    <>
      <PageHead>
        <div style={{ width: 170 }}>
          <Select value={status} onChange={(v) => { setStatus(v); setOffset(0); }} placeholder="كل الحالات"
            options={Object.entries(SURVEY_STATUS).map(([value, [label]]) => ({ value, label }))} />
        </div>
        {s.can("surveys.write") && <Btn kind="primary" icon="plus" onClick={() => go("surveys/new")}>معاينة جديدة</Btn>}
      </PageHead>
      {list.error && <ErrorBox text={list.error} onRetry={list.reload} />}
      <Card flush>
        <Table rows={rows} loading={list.loading} onRow={(x) => go(`surveys/${x.id}`)} columns={[
          { key: "n", label: "الرقم", render: (x) => <span className="num bold">{x.number}</span> },
          { key: "c", label: "العميل", render: (x) => <CustomerName id={x.customer_id} /> },
          { key: "d", label: "الميعاد", render: (x) => <span className="num">{date(x.survey_date)}</span> },
          { key: "a", label: "العنوان", render: (x) => <span className="muted">{x.address ?? ""}</span> },
          { key: "o", label: "الفتحات", num: true, render: (x) => <span className="num">{x.openings?.length ?? 0}</span> },
          { key: "b", label: "الفرع", render: (x) => <BranchName id={x.branch_id} /> },
          { key: "s", label: "الحالة", render: (x) => <Chip color={SURVEY_STATUS[x.status]?.[1]}>{SURVEY_STATUS[x.status]?.[0] ?? x.status}</Chip> },
        ]} empty="مفيش معاينات" />
        {list.data && <Pager total={list.data.total} limit={50} offset={offset} onChange={setOffset} />}
      </Card>
    </>
  );
}

function NewSurvey({ customerId }: { customerId?: string }) {
  useTitle("معاينة جديدة", <a onClick={() => go("surveys")} style={{ cursor: "pointer" }}>المعاينات</a>);
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const branch = useDefaultBranch("surveys.write");
  const [d, setD] = useState<{ customer_id: string | null; branch_id: string | null; survey_date: string; address: string; notes: string }>(
    { customer_id: customerId ?? null, branch_id: branch, survey_date: "", address: "", notes: "" });
  return (
    <Card title="بيانات المعاينة">
      <div className="grid g2" style={{ maxWidth: 820 }}>
        <Field label="العميل" className="span-all"><CustomerPicker value={d.customer_id} onChange={(id, c) => setD((x) => ({ ...x, customer_id: id,
          address: x.address || c?.address || "" }))} /></Field>
        <Field label="الفرع"><BranchSelect value={d.branch_id} onChange={(v) => setD((x) => ({ ...x, branch_id: v }))} perm="surveys.write" /></Field>
        <Field label="الميعاد"><input type="date" className="input" value={d.survey_date} onChange={(e) => setD((x) => ({ ...x, survey_date: e.target.value }))} /></Field>
        <Field label="العنوان" className="span-all"><TextIn value={d.address} onChange={(v) => setD((x) => ({ ...x, address: v }))} /></Field>
        <Field label="ملاحظات" className="span-all"><TextArea value={d.notes} onChange={(v) => setD((x) => ({ ...x, notes: v }))} rows={2} /></Field>
      </div>
      <div className="row mt">
        <Btn kind="primary" busy={busy} disabled={!d.customer_id || !d.branch_id} onClick={() => run(async () => {
          const sv = await api.post<Survey>("/surveys", { ...d, survey_date: d.survey_date || null, address: d.address || null });
          go(`surveys/${sv.id}`);
        })}>إنشاء المعاينة</Btn>
      </div>
    </Card>
  );
}

function toIn(o: Opening | ItemDraft) {
  return { location: o.location ?? "", opening_width_mm: String(o.opening_width_mm), opening_height_mm: String(o.opening_height_mm),
    qty: Number(o.qty ?? 1), model_id: o.model_id || null, params: o.params ?? {}, color_code: o.color_code || null,
    glass_material_code: o.glass_material_code || null, notes: o.notes ?? "", ...("photo_id" in o ? { photo_id: o.photo_id } : {}) };
}

function SurveyDetail({ id }: { id: string }) {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const sv = useLoad(() => api.get<Survey>(`/surveys/${id}`), [id]);
  useTitle(sv.data ? `معاينة ${sv.data.number}` : "…", <a onClick={() => go("surveys")} style={{ cursor: "pointer" }}>المعاينات</a>, [sv.data?.number]);
  const [edit, setEdit] = useState<number | "new" | null>(null);
  const [del, setDel] = useState<number | null>(null);
  const [header, setHeader] = useState(false);
  if (sv.error) return <ErrorBox text={sv.error} onRetry={sv.reload} />;
  if (!sv.data) return <Loading />;
  const survey = sv.data;
  const openings = survey.openings ?? [];
  const can = s.can("surveys.write", survey.branch_id) && survey.status === "open";

  const saveOpenings = async (list: ReturnType<typeof toIn>[]) => {
    sv.set(await api.patch<Survey>(`/surveys/${id}`, { version: survey.version, openings: list }));
  };
  const setStatus = (status: string) => run(async () => {
    sv.set(await api.patch<Survey>(`/surveys/${id}`, { version: survey.version, status }));
  });

  return (
    <div className="col" style={{ gap: 14 }}>
      <Card>
        <div className="row wrap" style={{ gap: 18 }}>
          <div><div className="muted small">العميل</div><a style={{ cursor: "pointer", fontWeight: 700 }} onClick={() => go(`customers/${survey.customer_id}`)}><CustomerName id={survey.customer_id} /></a></div>
          <div><div className="muted small">الحالة</div><Chip color={SURVEY_STATUS[survey.status]?.[1]}>{SURVEY_STATUS[survey.status]?.[0] ?? survey.status}</Chip></div>
          <div><div className="muted small">الميعاد</div><span className="num">{date(survey.survey_date)}</span></div>
          <div className="grow"><div className="muted small">العنوان</div>{survey.address ?? "—"}</div>
          <div className="end row wrap">
            {s.can("surveys.write", survey.branch_id) && <Btn icon="edit" onClick={() => setHeader(true)}>تعديل</Btn>}
            {can && <Btn kind="success" busy={busy} onClick={() => setStatus("done")}>المعاينة خلصت</Btn>}
            {s.can("quotes.write", survey.branch_id) && openings.some((o) => o.model_id) &&
              <Btn kind="primary" icon="quote" onClick={() => go("quotations/new", { customer: survey.customer_id, survey: survey.id })}>عرض سعر من المعاينة</Btn>}
          </div>
        </div>
      </Card>
      <Card title={`الفتحات (${openings.length})`} flush actions={can && <Btn kind="primary" small icon="plus" onClick={() => setEdit("new")}>إضافة فتحة</Btn>}>
        <Table rows={openings} empty="مفيش فتحات لسه" columns={[
          { key: "p", label: "#", width: 36, render: (o) => <span className="num muted">{o.position}</span> },
          { key: "img", label: "", width: 76, render: (o) => o.model_id ? <ModelThumb modelId={o.model_id} /> : <span className="faint small">بدون نموذج</span> },
          { key: "l", label: "المكان", render: (o) => <b>{o.location || "—"}</b> },
          { key: "m", label: "النموذج", render: (o) => <div><ModelName id={o.model_id} /><div><ParamLabels modelId={o.model_id} values={o.params} /></div></div> },
          { key: "s", label: "المقاس (عرض × ارتفاع)", render: (o) => <Dim w={o.opening_width_mm} h={o.opening_height_mm} /> },
          { key: "c", label: "اللون", render: (o) => <ColorName code={o.color_code} /> },
          { key: "q", label: "العدد", num: true, render: (o) => <span className="num">{o.qty}</span> },
          { key: "n", label: "ملاحظات", render: (o) => <span className="muted small">{o.notes}</span> },
          ...(can ? [{ key: "a", label: "", width: 80, render: (_o: Opening, i: number) => (
            <div className="row" style={{ gap: 4 }}><Btn small icon="edit" onClick={() => setEdit(i)} /><Btn small icon="trash" kind="danger" onClick={() => setDel(i)} /></div>) }] : []),
        ]} />
      </Card>
      {edit !== null && <ItemForm title={edit === "new" ? "فتحة جديدة" : "تعديل الفتحة"} requireModel={false}
        initial={edit === "new" ? undefined : { ...openings[edit], opening_width_mm: String(openings[edit].opening_width_mm),
          opening_height_mm: String(openings[edit].opening_height_mm) }}
        onClose={() => setEdit(null)} onSave={async (d) => {
          const list = openings.map(toIn);
          if (edit === "new") list.push(toIn(d)); else list[edit] = { ...list[edit], ...toIn(d) };
          await saveOpenings(list);
          toast.ok("اتحفظت الفتحة.");
        }} />}
      {del !== null && <Confirm title="حذف الفتحة" danger yes="حذف" busy={busy} onClose={() => setDel(null)}
        onYes={() => run(async () => { await saveOpenings(openings.filter((_, i) => i !== del).map(toIn)); setDel(null); })} />}
      {header && <SurveyHeader survey={survey} onClose={() => setHeader(false)} onSaved={(x) => sv.set(x)} />}
    </div>
  );
}

function ModelName({ id }: { id: string | null | undefined }) {
  const m = useLoad(() => id ? lookups.model(id) : Promise.resolve(undefined), [id]);
  return id ? <span>{m.data?.name ?? "…"}</span> : <span className="faint">—</span>;
}

function SurveyHeader({ survey, onClose, onSaved }: { survey: Survey; onClose: () => void; onSaved: (s: Survey) => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState({ survey_date: survey.survey_date ?? "", address: survey.address ?? "", notes: survey.notes, status: survey.status });
  return (
    <Modal title="بيانات المعاينة" onClose={onClose} footer={<><Btn kind="primary" busy={busy} onClick={() => run(async () => {
      onSaved(await api.patch<Survey>(`/surveys/${survey.id}`, { version: survey.version, ...d, survey_date: d.survey_date || null }));
      onClose();
    })}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col">
        <Field label="الميعاد"><input type="date" className="input" value={d.survey_date} onChange={(e) => setD((x) => ({ ...x, survey_date: e.target.value }))} /></Field>
        <Field label="العنوان"><TextIn value={d.address} onChange={(v) => setD((x) => ({ ...x, address: v }))} /></Field>
        <Field label="الحالة"><Select value={d.status} onChange={(v) => setD((x) => ({ ...x, status: v }))}
          options={Object.entries(SURVEY_STATUS).map(([value, [label]]) => ({ value, label }))} /></Field>
        <Field label="ملاحظات"><TextArea value={d.notes} onChange={(v) => setD((x) => ({ ...x, notes: v }))} /></Field>
      </div>
    </Modal>
  );
}
