// The tools above every table: a quick filter over the rows on screen, which columns to show (remembered per table),
// and Excel / PDF of exactly what is shown (filtered rows, chosen columns, in the shown order).
import { useState, type ReactNode, type RefObject } from "react";
import { saveFile } from "../lib/save";
import { errorText, raw } from "../api/client";
import { cellPics, textOf, type Report, type ReportSection } from "../lib/printpage";
import { useToast } from "../state/toast";
import { Icon } from "./icons";
import { PrintPreview } from "./media";

/** The table as the user sees it: header texts, the rows not filtered out, numeric columns. */
export function tableReport(table: HTMLTableElement, title: string): Report {
  const head = Array.from(table.tHead?.rows[0]?.cells ?? []);
  const keep = head.map((c, i) => [i, textOf(c).replace(/[▲▼]/g, "").trim()] as const).filter(([, t]) => t !== "");
  const body = Array.from(table.tBodies).flatMap((b) => Array.from(b.rows)).filter((r) => !r.hidden);
  const kept = body.filter((r) => keep.some(([i]) => r.cells[i] && textOf(r.cells[i]) !== ""));
  const rows = kept.map((r) => keep.map(([i]) => (r.cells[i] ? textOf(r.cells[i]) : "")));
  const pics = kept.map((r) => keep.map(([i]) => (r.cells[i] ? cellPics(r.cells[i]) : [])));
  const nums = keep.map(([i], j) => (head[i].classList.contains("n") ? j : -1)).filter((j) => j >= 0);
  const section: ReportSection = { title, kv: [], columns: keep.map(([, t]) => t), rows, nums,
    pics: pics.some((r) => r.some((c) => c.length)) ? pics : undefined };
  const page = document.querySelector(".page-title")?.textContent?.trim() ?? "";
  return { title: title || page || "تقرير", subtitle: title && page && title !== page ? page : "", sections: [section] };
}

/** The name of a table: its card's title, else the page's. */
export function tableTitle(table: HTMLElement): string {
  const card = table.closest(".card");
  const h = card?.querySelector(":scope > .card-h h3, :scope > .card-h");
  return (h ? textOf(h) : "") || (document.querySelector(".page-title")?.textContent?.trim() ?? "");
}

export function TableTools({ tableRef, filter, setFilter, columns, hidden, setHidden, shown }:
  { tableRef: RefObject<HTMLTableElement | null>; filter: string; setFilter: (v: string) => void;
    columns: { key: string; label: ReactNode }[]; hidden: string[]; setHidden: (v: string[]) => void; shown: number | null }) {
  const toast = useToast();
  const [menu, setMenu] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const make = () => { const t = tableRef.current; return t ? tableReport(t, tableTitle(t)) : null; };
  const excel = async () => {
    const r = make();
    if (!r) return;
    setBusy(true);
    try {
      const res = await raw("/documents/report.xlsx", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...r, sections: r.sections.map((x) => ({ ...x, pics: undefined })) }) });
      if (!res.ok) throw new Error((await res.json().catch(() => null))?.error?.message ?? "Export failed");
      const path = await saveFile(`${r.title.replace(/[\\/:*?"<>|]/g, " ").trim() || "تقرير"}.xlsx`, await res.blob());
      toast.ok(path ? `اتحفظ في التنزيلات: ${path}` : "اتنزل الملف.");
    } catch (e) {
      toast.err(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const named = columns.filter((c) => c.label !== "" && c.label !== null && c.label !== undefined);
  const toggle = (k: string) => {
    const next = hidden.includes(k) ? hidden.filter((x) => x !== k) : [...hidden, k];
    if (named.every((c) => next.includes(c.key))) return;          // at least one column stays
    setHidden(next);
  };
  return (
    <div className="table-tools no-print">
      <label className="table-filter">
        <Icon name="search" />
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="فلترة الصفوف اللي قدامك…" />
        {filter && <button className="link-btn" onClick={() => setFilter("")} aria-label="مسح">×</button>}
      </label>
      {filter && shown !== null && <span className="muted small">{shown} صف</span>}
      <span className="grow" />
      <div style={{ position: "relative" }}>
        <button className="btn sm ghost" onClick={() => setMenu((m) => !m)} title="الأعمدة اللي تظهر"><Icon name="layers" />الأعمدة</button>
        {menu && (
          <div className="card table-cols" onMouseLeave={() => setMenu(false)}>
            {named.map((c) => (
              <label key={c.key} className="check"><input type="checkbox" checked={!hidden.includes(c.key)} onChange={() => toggle(c.key)} />{c.label}</label>
            ))}
            {hidden.length > 0 && <button className="btn sm ghost" onClick={() => setHidden([])}>إظهار الكل</button>}
          </div>
        )}
      </div>
      <button className="btn sm ghost" onClick={excel} disabled={busy} title="تصدير اللي قدامك لملف إكسيل"><Icon name="download" />إكسيل</button>
      <button className="btn sm ghost" onClick={() => setReport(make())} title="طباعة أو حفظ PDF"><Icon name="print" />PDF</button>
      {report && <PrintPreview path="/documents/report" body={report} title={report.title} onClose={() => setReport(null)} />}
    </div>
  );
}
