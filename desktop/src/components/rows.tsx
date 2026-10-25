// Editable table of rows (definition lists: params, formulas, pieces, glass, ...).
import type { ReactNode } from "react";
import { Btn } from "./ui";

export type RowCol<T> = {
  key: keyof T & string; label: ReactNode; width?: number | string;
  kind?: "text" | "code" | "expr" | "number" | "select" | "check";
  options?: { value: string; label: string }[]; placeholder?: string;
  render?: (row: T, set: (patch: Partial<T>) => void, i: number) => ReactNode;
};

export function RowsEditor<T extends Record<string, any>>({ rows, onChange, columns, blank, readOnly, addLabel = "إضافة", rowClass, extraActions }:
  { rows: T[]; onChange: (rows: T[]) => void; columns: RowCol<T>[]; blank: () => T; readOnly?: boolean; addLabel?: string;
    rowClass?: (row: T, i: number) => string | undefined; extraActions?: ReactNode }) {
  const set = (i: number, patch: Partial<T>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= rows.length) return;
    const next = rows.slice();
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };
  return (
    <div>
      <div className="table-wrap">
        <table className="editor-table">
          <thead><tr>{columns.map((c) => <th key={c.key} style={{ width: c.width }}>{c.label}</th>)}{!readOnly && <th style={{ width: 96 }} />}</tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={rowClass?.(r, i)}>
                {columns.map((c) => (
                  <td key={c.key}>{c.render ? c.render(r, (p) => set(i, p), i) : <Cell col={c} value={r[c.key]} readOnly={readOnly}
                    onChange={(v) => set(i, { [c.key]: v } as Partial<T>)} />}</td>
                ))}
                {!readOnly && (
                  <td className="nowrap">
                    <Btn small icon="back" title="لفوق" onClick={() => move(i, -1)} disabled={i === 0} className="rot-up" />
                    <Btn small icon="trash" kind="danger" title="حذف" onClick={() => onChange(rows.filter((_, j) => j !== i))} />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <div className="empty small">مفيش صفوف</div>}
      </div>
      {!readOnly && <div className="row mt"><Btn small icon="plus" onClick={() => onChange([...rows, blank()])}>{addLabel}</Btn>{extraActions}</div>}
    </div>
  );
}

function Cell<T>({ col, value, onChange, readOnly }: { col: RowCol<T>; value: any; onChange: (v: any) => void; readOnly?: boolean }) {
  if (col.kind === "check") return <input type="checkbox" checked={!!value} disabled={readOnly} onChange={(e) => onChange(e.target.checked)} />;
  if (col.kind === "select") {
    return (
      <select className="input" value={value ?? ""} disabled={readOnly} onChange={(e) => onChange(e.target.value || null)}>
        {col.placeholder !== undefined && <option value="">{col.placeholder}</option>}
        {(col.options ?? []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  }
  const cls = "input" + (col.kind === "code" || col.kind === "expr" ? " code-in" : col.kind === "number" ? " num" : "");
  // names and formulas can be written in English or Arabic: the direction follows what is typed
  const dir = col.kind === "code" || col.kind === "expr" ? "auto" : col.kind === "number" ? "ltr" : undefined;
  // a name is one word: a space typed in a name becomes "_" (عرض الضلفة -> عرض_الضلفة)
  const clean = (v: string) => col.kind === "code" ? v.replace(/[\s\u00A0]+/g, "_") : v;
  return <input className={cls} dir={dir} value={value ?? ""} placeholder={col.placeholder}
    readOnly={readOnly} onChange={(e) => onChange(clean(e.target.value))} />;
}
