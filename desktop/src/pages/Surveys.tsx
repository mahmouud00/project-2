import { useEffect, useState } from "react";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad } from "../lib/hooks";
import { useDefaultBranch, useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Chip, ErrorBox, Field, Loading, Modal, PageHead, Pager, Select, Table, TextArea, TextIn } from "../components/ui";
import { BranchName, BranchSelect, CustomerName, CustomerPicker } from "../components/pickers";
import { ItemForm } from "../components/items";
import { PrintPreview } from "../components/media";
import { SuggestedPrice, SurveySheet, blankRow, isEmptyRow, rowFromApi, rowMissingSize, rowToApi, type SheetRow, type SurveyKind } from "../components/surveysheet";
import { SURVEY_KIND, SURVEY_STATUS, lookups } from "../lib/lookups";
import { go } from "../lib/router";
import { date, today } from "../lib/format";

type Survey = S<"SurveyOut">;

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
          { key: "k", label: "النوع", render: (x) => <Chip color={x.kind === "shutter" ? "amber" : "violet"}>{SURVEY_KIND[x.kind] ?? x.kind}</Chip> },
          { key: "d", label: "التاريخ", render: (x) => <span className="num">{date(x.survey_date)}</span> },
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
  const [d, setD] = useState<{ customer_id: string | null; branch_id: string | null; survey_date: string; address: string; notes: string;
    kind: SurveyKind; floor: string; technician: string }>(
    { customer_id: customerId ?? null, branch_id: branch, survey_date: today(), address: "", notes: "", kind: "window", floor: "", technician: "" });
  return (
    <Card title="بيانات المعاينة">
      <div className="grid g2" style={{ maxWidth: 820 }}>
        <Field label="نوع المعاينة" className="span-all">
          <div className="row">
            {(["window", "shutter"] as const).map((k) => (
              <button key={k} type="button" className={"btn" + (d.kind === k ? " primary" : "")} onClick={() => setD((x) => ({ ...x, kind: k }))}>
                {k === "window" ? "شبابيك وأبواب (UPVC / ألومنيوم)" : "شيش"}
              </button>
            ))}
          </div>
        </Field>
        <Field label="العميل" className="span-all"><CustomerPicker value={d.customer_id} onChange={(id, c) => setD((x) => ({ ...x, customer_id: id,
          address: x.address || c?.address || "" }))} /></Field>
        <Field label="العنوان" className="span-all"><TextIn value={d.address} onChange={(v) => setD((x) => ({ ...x, address: v }))} /></Field>
        <Field label="الدور"><TextIn value={d.floor} onChange={(v) => setD((x) => ({ ...x, floor: v }))} /></Field>
        <Field label="الفني"><TextIn value={d.technician} onChange={(v) => setD((x) => ({ ...x, technician: v }))} /></Field>
        <Field label="التاريخ"><input type="date" className="input" value={d.survey_date} onChange={(e) => setD((x) => ({ ...x, survey_date: e.target.value }))} /></Field>
        <Field label="الفرع"><BranchSelect value={d.branch_id} onChange={(v) => setD((x) => ({ ...x, branch_id: v }))} perm="surveys.write" /></Field>
        <Field label="ملاحظات" className="span-all"><TextArea value={d.notes} onChange={(v) => setD((x) => ({ ...x, notes: v }))} rows={2} /></Field>
      </div>
      <div className="row mt">
        <Btn kind="primary" busy={busy} disabled={!d.customer_id || !d.branch_id} onClick={() => run(async () => {
          const sv = await api.post<Survey>("/surveys", { ...d, survey_date: d.survey_date || null, address: d.address || null,
            floor: d.floor || null, technician: d.technician || null });
          go(`surveys/${sv.id}`);
        })}>فتح المعاينة</Btn>
      </div>
    </Card>
  );
}

function SurveyDetail({ id }: { id: string }) {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const sv = useLoad(() => api.get<Survey>(`/surveys/${id}`), [id]);
  useTitle(sv.data ? `معاينة ${sv.data.number}` : "…", <a onClick={() => go("surveys")} style={{ cursor: "pointer" }}>المعاينات</a>, [sv.data?.number]);
  const [rows, setRows] = useState<SheetRow[]>([]);
  const [details, setDetails] = useState<number | null>(null);
  const [header, setHeader] = useState(false);
  const [printing, setPrinting] = useState(false);
  const survey = sv.data;
  const editable = !!survey && s.can("surveys.write", survey.branch_id) && survey.status === "open";
  const customer = useLoad(() => survey ? lookups.customer(survey.customer_id) : Promise.resolve(undefined), [survey?.customer_id]);

  const withBlank = (list: SheetRow[]) => editable && (!list.length || !isEmptyRow(list[list.length - 1])) ? [...list, blankRow()] : list;
  useEffect(() => {
    if (survey) setRows(withBlank((survey.openings ?? []).map(rowFromApi)));
  }, [survey?.id, survey?.version, editable]); // eslint-disable-line react-hooks/exhaustive-deps

  if (sv.error) return <ErrorBox text={sv.error} onRetry={sv.reload} />;
  if (!survey) return <Loading />;
  const openings = survey.openings ?? [];
  const filled = rows.filter((r) => !isEmptyRow(r));
  const dirty = JSON.stringify(filled.map(rowToApi)) !== JSON.stringify(openings.map(rowFromApi).map(rowToApi));

  const save = () => run(async () => {
    if (filled.some(rowMissingSize)) throw new Error("فيه صفوف من غير عرض أو ارتفاع (متعلّمة بالأحمر).");
    sv.set(await api.patch<Survey>(`/surveys/${id}`, { version: survey.version, openings: filled.map(rowToApi) }));
    toast.ok("اتحفظت المعاينة.");
  });
  const setStatus = (status: string) => run(async () => {
    if (dirty) throw new Error("احفظ التعديلات الأول.");
    sv.set(await api.patch<Survey>(`/surveys/${id}`, { version: survey.version, status }));
  });
  const detailRow = details !== null ? rows[details] : null;

  return (
    <div className="col" style={{ gap: 14 }}>
      <Card>
        <div className="row top wrap" style={{ gap: 18 }}>
          <div className="sheet-head grow">
            <div><div className="k">اسم العميل</div><a style={{ cursor: "pointer", fontWeight: 700 }} onClick={() => go(`customers/${survey.customer_id}`)}><CustomerName id={survey.customer_id} /></a></div>
            <div><div className="k">الدور</div><b>{survey.floor || "—"}</b></div>
            <div><div className="k">الموبايل</div><b className="num">{customer.data?.phone || "—"}</b></div>
            <div><div className="k">العنوان</div>{survey.address || customer.data?.address || "—"}</div>
            <div><div className="k">التاريخ</div><span className="num">{date(survey.survey_date)}</span></div>
            <div><div className="k">الفني</div><b>{survey.technician || "—"}</b></div>
          </div>
          <div className="col" style={{ alignItems: "flex-end", gap: 8 }}>
            <div className="row" style={{ gap: 6 }}>
              <Chip color="violet">{SURVEY_KIND[survey.kind] ?? survey.kind}</Chip>
              <Chip color={SURVEY_STATUS[survey.status]?.[1]}>{SURVEY_STATUS[survey.status]?.[0] ?? survey.status}</Chip>
            </div>
            <div className="row wrap" style={{ justifyContent: "flex-end" }}>
              <Btn icon="print" onClick={() => setPrinting(true)}>طباعة</Btn>
              {s.can("surveys.write", survey.branch_id) && <Btn icon="edit" onClick={() => setHeader(true)}>البيانات</Btn>}
              {editable && <Btn kind="success" busy={busy} onClick={() => setStatus("done")}>المعاينة خلصت</Btn>}
              {s.can("quotes.write", survey.branch_id) && openings.some((o) => o.model_id) &&
                <Btn kind="primary" icon="quote" onClick={() => go("quotations/new", { customer: survey.customer_id, survey: survey.id })}>عرض سعر</Btn>}
            </div>
          </div>
        </div>
      </Card>

      <Card title={`${survey.kind === "shutter" ? "الوحدات (شيش)" : "الوحدات"} (${filled.length})`} flush actions={editable && <>
        {dirty && <Chip color="amber">فيه تعديلات مش محفوظة</Chip>}
        <Btn small icon="plus" onClick={() => setRows((r) => [...r, blankRow()])}>صف</Btn>
        <Btn small kind="primary" icon="check" busy={busy} disabled={!dirty} onClick={save}>حفظ</Btn>
      </>}>
        <SurveySheet kind={survey.kind as SurveyKind} rows={rows} editable={editable} onChange={(r) => setRows(withBlank(r))}
          onDetails={(i) => setDetails(i)} />
        <div className="card-b small muted">
          المقاسات بالسنتيمتر · العرض قبل الارتفاع · «رقم الوحدة» هو النموذج من المكتبة (لازم عشان السعر المقترح وعرض السعر) · زرار التعديل في آخر الصف للعدد والزجاج وخيارات النموذج.
        </div>
      </Card>

      {s.can("quotes.read") && (
        <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 380px" }}>
          <Card title="ملاحظات">{survey.notes ? <div style={{ whiteSpace: "pre-wrap" }}>{survey.notes}</div> : <span className="faint">—</span>}</Card>
          <Card title="التسعير">
            {dirty ? <div className="notice info small">احفظ المعاينة عشان السعر يتحسب بآخر التعديلات.</div> : null}
            <SuggestedPrice surveyId={survey.id} version={survey.version} />
          </Card>
        </div>
      )}

      {detailRow && <ItemForm title={`الوحدة ${details! + 1}`} requireModel={false}
        initial={{ ...detailRow, opening_width_mm: detailRow.opening_width_mm, opening_height_mm: detailRow.opening_height_mm }}
        onClose={() => setDetails(null)} onSave={async (d) => {
          const i = details!;
          setRows((list) => withBlank(list.map((r, k) => k !== i ? r : { ...r, model_id: d.model_id ?? null, location: d.location ?? "",
            opening_width_mm: d.opening_width_mm ?? null, opening_height_mm: d.opening_height_mm ?? null,
            total_height_mm: d.total_height_mm ?? null, top_model_id: d.top_model_id ?? null, params: d.params ?? {},
            color_code: d.color_code ?? null, color_text: d.color_code ? null : r.color_text, glass_material_code: d.glass_material_code ?? null,
            qty: Number(d.qty) || 1, notes: d.notes ?? "" })));
        }} />}
      {header && <SurveyHeader survey={survey} onClose={() => setHeader(false)} onSaved={(x) => sv.set(x)} />}
      {printing && <PrintPreview path={`/surveys/${id}/print`} title={`معاينة ${survey.number}`} onClose={() => setPrinting(false)} />}
    </div>
  );
}

function SurveyHeader({ survey, onClose, onSaved }: { survey: Survey; onClose: () => void; onSaved: (s: Survey) => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState({ survey_date: survey.survey_date ?? "", address: survey.address ?? "", notes: survey.notes, status: survey.status,
    floor: survey.floor ?? "", technician: survey.technician ?? "" });
  return (
    <Modal title="بيانات المعاينة" onClose={onClose} footer={<><Btn kind="primary" busy={busy} onClick={() => run(async () => {
      onSaved(await api.patch<Survey>(`/surveys/${survey.id}`, { version: survey.version, ...d, survey_date: d.survey_date || null,
        floor: d.floor || null, technician: d.technician || null }));
      onClose();
    })}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2">
        <Field label="العنوان" className="span-all"><TextIn value={d.address} onChange={(v) => setD((x) => ({ ...x, address: v }))} /></Field>
        <Field label="الدور"><TextIn value={d.floor} onChange={(v) => setD((x) => ({ ...x, floor: v }))} /></Field>
        <Field label="الفني"><TextIn value={d.technician} onChange={(v) => setD((x) => ({ ...x, technician: v }))} /></Field>
        <Field label="التاريخ"><input type="date" className="input" value={d.survey_date} onChange={(e) => setD((x) => ({ ...x, survey_date: e.target.value }))} /></Field>
        <Field label="الحالة"><Select value={d.status} onChange={(v) => setD((x) => ({ ...x, status: v }))}
          options={Object.entries(SURVEY_STATUS).map(([value, [label]]) => ({ value, label }))} /></Field>
        <Field label="ملاحظات" className="span-all"><TextArea value={d.notes} onChange={(v) => setD((x) => ({ ...x, notes: v }))} /></Field>
      </div>
    </Modal>
  );
}
