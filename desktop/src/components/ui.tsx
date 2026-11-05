import { Fragment, useEffect, useLayoutEffect, useRef, useState, type ReactNode, type ButtonHTMLAttributes, type InputHTMLAttributes } from "react";
import { Icon, type IconName } from "./icons";
import { useSession } from "../state/session";
import { clean } from "../lib/format";
import { go, useUnsavedGuard } from "../lib/router";
import { textOf } from "../lib/printpage";
import { TableTools } from "./tabletools";

export function Btn({ icon, kind, small, busy, children, className, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { icon?: IconName; kind?: "primary" | "success" | "danger" | "ghost" | "solid-danger";
    small?: boolean; busy?: boolean }) {
  const cls = ["btn", kind === "solid-danger" ? "danger solid" : kind, small && "sm", !children && icon && "icon", className]
    .filter(Boolean).join(" ");
  return (
    <button type="button" className={cls} disabled={busy || rest.disabled} {...rest}>
      {busy ? <span className="spinner" style={{ width: 14, height: 14 }} /> : icon && <Icon name={icon} />}
      {children}
    </button>
  );
}

export function Field({ label, hint, error, children, className }:
  { label?: ReactNode; hint?: ReactNode; error?: string | null; children: ReactNode; className?: string }) {
  return (
    <div className={"field " + (className ?? "")}>
      {label && <label>{label}</label>}
      {children}
      {error ? <div className="err">{error}</div> : hint ? <div className="hint">{hint}</div> : null}
    </div>
  );
}

export function TextIn({ value, onChange, code, ...rest }:
  Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> & { value: string | null | undefined; onChange: (v: string) => void;
    code?: boolean }) {
  return <input className={"input" + (code ? " code-in" : "")} value={value ?? ""} onChange={(e) => onChange(e.target.value)} {...rest} />;
}

export function TextArea({ value, onChange, rows = 3, ...rest }:
  { value: string | null | undefined; onChange: (v: string) => void; rows?: number; placeholder?: string; disabled?: boolean }) {
  return <textarea className="input" rows={rows} value={value ?? ""} onChange={(e) => onChange(e.target.value)} {...rest} />;
}

/** Decimal number kept as a string (never a float). */
export function NumIn({ value, onChange, unit, ...rest }:
  Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> & { value: string | number | null | undefined;
    onChange: (v: string) => void; unit?: string }) {
  const input = (
    <input className="input num" inputMode="decimal" dir="ltr" value={value ?? ""}
      onChange={(e) => onChange(e.target.value.replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d))).replace("٫", "."))}
      {...rest} />
  );
  return unit ? <div className="unit-in">{input}<span className="u">{unit}</span></div> : input;
}

export function Select<T extends string>({ value, onChange, options, placeholder, disabled }:
  { value: T | null | undefined; onChange: (v: T) => void; options: { value: T; label: ReactNode }[]; placeholder?: string;
    disabled?: boolean }) {
  return (
    <select className="input" value={value ?? ""} onChange={(e) => onChange(e.target.value as T)} disabled={disabled}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => <option key={o.value} value={o.value}>{o.label as any}</option>)}
    </select>
  );
}

export function Check({ checked, onChange, label, disabled }:
  { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; disabled?: boolean }) {
  return (
    <label className="check">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

/** A length typed in the company unit (cm by default). Holds the value in mm for the API. */
export function LenIn({ mm, onChange, placeholder, label, autoFocus }:
  { mm: string | null | undefined; onChange: (mm: string | null, text: string) => void; placeholder?: string; label?: string;
    autoFocus?: boolean }) {
  const s = useSession();
  const [text, setText] = useState(() => s.len(mm));
  const last = useRef(mm);
  useEffect(() => {
    if (mm !== last.current) { last.current = mm; if (s.toApiLen(text) !== (mm ?? null)) setText(s.len(mm)); }
  }, [mm]); // eslint-disable-line react-hooks/exhaustive-deps
  const bad = text !== "" && s.toApiLen(text) === null;
  return (
    <div className="unit-in">
      {label && <span className="lbl muted">{label}</span>}
      <input className="input num" inputMode="decimal" dir="ltr" value={text} placeholder={placeholder} autoFocus={autoFocus}
        style={bad ? { borderColor: "var(--danger)" } : undefined}
        onChange={(e) => {
          setText(e.target.value);
          const v = e.target.value === "" ? null : s.toApiLen(e.target.value);
          last.current = v;
          onChange(v, e.target.value);
        }} />
      <span className="u">{s.unit === "cm" ? "سم" : "مم"}</span>
    </div>
  );
}

/** Width × height input. Width always comes first (on the right). */
export function SizeIn({ w, h, onChange, autoFocus }:
  { w: string | null | undefined; h: string | null | undefined; onChange: (w: string | null, h: string | null) => void;
    autoFocus?: boolean }) {
  return (
    <div className="size-in">
      <LenIn mm={w} label="العرض" autoFocus={autoFocus} onChange={(v) => onChange(v, h ?? null)} />
      <span className="x">×</span>
      <LenIn mm={h} label="الارتفاع" onChange={(v) => onChange(w ?? null, v)} />
    </div>
  );
}

/** Display a size: width first, in the company unit. */
export function Dim({ w, h, strong = true }: { w: string | number | null | undefined; h: string | number | null | undefined;
  strong?: boolean }) {
  const s = useSession();
  if (w === null || w === undefined || h === null || h === undefined) return <span className="faint">—</span>;
  return <span className="dim">{strong ? <b>{s.len(w)}</b> : s.len(w)}<span className="x">×</span>{s.len(h)}</span>;
}

export function Len({ mm }: { mm: string | number | null | undefined }) {
  const s = useSession();
  return <span className="num">{s.len(mm)}</span>;
}

export function Money({ v, cur }: { v: string | number | null | undefined; cur?: boolean }) {
  const s = useSession();
  const n = Number(v);
  const text = v === null || v === undefined || v === "" ? "—"
    : isFinite(n) ? n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : String(v);
  return <span className="num">{text}{cur ? " " + s.currency : ""}</span>;
}

export function Qty({ v }: { v: string | number | null | undefined }) {
  return <span className="num">{clean(v)}</span>;
}

export function Chip({ color = "gray", children }: { color?: "blue" | "green" | "amber" | "red" | "gray" | "violet"; children: ReactNode }) {
  return <span className={"chip " + color}>{children}</span>;
}

export function Card({ title, actions, children, flush, className }:
  { title?: ReactNode; actions?: ReactNode; children: ReactNode; flush?: boolean; className?: string }) {
  return (
    <div className={"card " + (className ?? "")}>
      {(title || actions) && <div className="card-h">{typeof title === "string" ? <h3>{title}</h3> : title}<div className="end row">{actions}</div></div>}
      <div className={"card-b" + (flush ? " flush" : "")}>{children}</div>
    </div>
  );
}

/** Put on a screen with unsaved work: leaving it asks first (see useUnsavedGuard). */
export function UnsavedGuard({ when, message }: { when: boolean; message?: string }) {
  useUnsavedGuard(when, message);
  return null;
}

export type Crumb = { label: ReactNode; to?: string; query?: Record<string, string | undefined> };

/** Where this page is: «المكتبة ‹ كومبن ‹ النماذج». Each part with `to` opens that page. */
export function Crumbs({ items }: { items: Crumb[] }) {
  return (
    <nav className="crumbs-path" aria-label="مكان الصفحة">
      {items.map((c, i) => (
        <Fragment key={i}>
          {i > 0 && <Icon name="forward" size={11} className="crumb-sep" />}
          {c.to !== undefined ? <a className="crumb" onClick={() => go(c.to!, c.query)}>{c.label}</a> : <span>{c.label}</span>}
        </Fragment>
      ))}
    </nav>
  );
}

export function PageHead({ title, children }: { title?: ReactNode; children?: ReactNode }) {
  return <div className="page-head">{title && <h2>{title}</h2>}<div className="end row wrap">{children}</div></div>;
}

/** A «مساعدة» button that opens the explanation of the current screen in a popup, instead of a long paragraph. */
export function Help({ title = "شرح الشاشة", label = "مساعدة", iconOnly, children }:
  { title?: string; label?: string; iconOnly?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      {iconOnly
        ? <button type="button" className="icon-btn" title={label} aria-label={label} onClick={() => setOpen(true)}><Icon name="help" /></button>
        : <button type="button" className="help-btn" onClick={() => setOpen(true)}><Icon name="help" /><span>{label}</span></button>}
      {open && <Modal title={title} onClose={() => setOpen(false)}><div className="help-body">{children}</div></Modal>}
    </>
  );
}

export type Column<T> = {
  key: string; label: ReactNode; render?: (row: T, i: number) => ReactNode; num?: boolean; width?: number | string;
  className?: string;
};

/** A table. With more than a few rows (or `tools`), it gets a quick filter, a column chooser and Excel / PDF export,
 * and any titled column sorts when its header is clicked (by the text shown, numbers as numbers). */
export function Table<T>({ rows, columns, onRow, loading, empty = "مفيش بيانات", rowKey, selected, tools }:
  { rows: T[] | undefined; columns: Column<T>[]; onRow?: (row: T) => void; loading?: boolean; empty?: ReactNode;
    rowKey?: (row: T, i: number) => string; selected?: string | null; tools?: boolean }) {
  const table = useRef<HTMLTableElement>(null);
  const store = "table.cols:" + (location.hash.split("?")[0].split("/")[1] ?? "") + ":" + columns.map((c) => c.key).join(",");
  const [hidden, setHiddenState] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem(store) ?? "[]"); } catch { return []; }
  });
  const setHidden = (v: string[]) => { setHiddenState(v); try { localStorage.setItem(store, JSON.stringify(v)); } catch { /* ignore */ } };
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [order, setOrder] = useState<string[] | null>(null);
  const [filter, setFilter] = useState("");
  const [shown, setShown] = useState<number | null>(null);
  const cols = columns.filter((c) => !hidden.includes(c.key));
  const keyed = (rows ?? []).map((r, i) => ({ r, i, k: rowKey ? rowKey(r, i) : String((r as any).id ?? i) }));
  const at = order ? new Map(order.map((k, n) => [k, n])) : null;
  const list = at ? [...keyed].sort((a, b) => (at.get(a.k) ?? 1e9) - (at.get(b.k) ?? 1e9) || a.i - b.i) : keyed;
  const showTools = tools ?? keyed.length > 5;

  // sort by what each cell shows (custom renders included): read the column's cells, order the row keys
  useLayoutEffect(() => {
    const t = table.current;
    if (!sort || !t) { if (order) setOrder(null); return; }
    const col = cols.findIndex((c) => c.key === sort.key);
    if (col < 0) { setSort(null); return; }
    const cells = Array.from(t.tBodies[0]?.rows ?? []).map((tr) => [tr.dataset.k ?? "", tr.cells[col] ? textOf(tr.cells[col]) : ""] as const);
    const num = (v: string) => { const n = Number(v.replace(/[,٬\s]/g, "").replace(/(EGP|ج\.م|%|م²|سم|مم)$/g, "")); return v.trim() !== "" && Number.isFinite(n) ? n : null; };
    const sorted = [...cells].sort(([, a], [, b]) => {
      const x = num(a), y = num(b);
      const c = x !== null && y !== null ? x - y : a.localeCompare(b, "ar", { numeric: true });
      return c * sort.dir;
    }).map(([k]) => k);
    if (!order || sorted.join("\u0000") !== order.join("\u0000")) setOrder(sorted);
  });

  // quick filter: hide the rows whose shown text does not contain it
  useLayoutEffect(() => {
    const t = table.current;
    if (!t) return;
    const q = filter.trim().toLowerCase();
    let n = 0;
    for (const tr of Array.from(t.tBodies[0]?.rows ?? [])) {
      const hide = !!q && !textOf(tr).toLowerCase().includes(q);
      tr.hidden = hide;
      if (!hide) n += 1;
    }
    const v = q ? n : null;
    if (v !== shown) setShown(v);
  });

  const clickHead = (c: Column<T>) => {
    if (c.label === "" || c.label === null || c.label === undefined) return;
    setSort((s) => (s?.key !== c.key ? { key: c.key, dir: 1 } : s.dir === 1 ? { key: c.key, dir: -1 } : null));
  };
  return (
    <div className="table-wrap">
      {showTools && <TableTools tableRef={table} filter={filter} setFilter={setFilter} columns={columns} hidden={hidden}
        setHidden={setHidden} shown={shown} />}
      <table ref={table}>
        <thead>
          <tr>{cols.map((c) => {
            const sortable = c.label !== "" && c.label !== null && c.label !== undefined;
            return (
              <th key={c.key} className={[c.num && "n", sortable && "sortable"].filter(Boolean).join(" ") || undefined} style={{ width: c.width }}
                onClick={sortable ? () => clickHead(c) : undefined} title={sortable ? "اضغط للترتيب" : undefined}>
                {c.label}{sort?.key === c.key && <span className="sort-mark">{sort.dir === 1 ? "▲" : "▼"}</span>}
              </th>
            );
          })}</tr>
        </thead>
        <tbody>
          {list.map(({ r, i, k }) => (
            <tr key={k} data-k={k} className={[onRow && "click", selected && selected === k && "sel"].filter(Boolean).join(" ")}
              onClick={onRow ? () => onRow(r) : undefined}>
              {cols.map((c) => (
                <td key={c.key} className={[c.num && "n", c.className].filter(Boolean).join(" ") || undefined}>
                  {c.render ? c.render(r, i) : ((r as any)[c.key] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {loading && !rows?.length && <div className="empty"><span className="spinner" /></div>}
      {!loading && rows && rows.length === 0 && <div className="empty">{empty}</div>}
      {!!filter.trim() && shown === 0 && <div className="empty">مفيش صفوف فيها «{filter.trim()}»</div>}
    </div>
  );
}

export function Pager({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (o: number) => void }) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <div className="pager">
      <span className="muted small">صفحة <span className="num">{page}</span> من <span className="num">{pages}</span> · <span className="num">{total}</span> سجل</span>
      <div className="end row">
        <Btn small disabled={page <= 1} onClick={() => onChange(offset - limit)}>السابق</Btn>
        <Btn small disabled={page >= pages} onClick={() => onChange(offset + limit)}>التالي</Btn>
      </div>
    </div>
  );
}

export function Modal({ title, onClose, children, footer, size }:
  { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; size?: "wide" | "xwide" }) {
  useEffect(() => {
    const on = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={"modal " + (size ?? "")} role="dialog" aria-modal="true">
        <div className="modal-h"><h3>{title}</h3><button className="icon-btn end" onClick={onClose} aria-label="إغلاق"><Icon name="x" /></button></div>
        <div className="modal-b">{children}</div>
        {footer && <div className="modal-f">{footer}</div>}
      </div>
    </div>
  );
}

export function Confirm({ title, text, onYes, onClose, danger, yes = "تأكيد", busy, children }:
  { title: string; text?: ReactNode; onYes: () => void; onClose: () => void; danger?: boolean; yes?: string; busy?: boolean;
    children?: ReactNode }) {
  return (
    <Modal title={title} onClose={onClose} footer={<>
      <Btn kind={danger ? "solid-danger" : "primary"} onClick={onYes} busy={busy}>{yes}</Btn>
      <Btn onClick={onClose}>رجوع</Btn>
    </>}>
      {text && <p style={{ marginTop: 0 }}>{text}</p>}
      {children}
    </Modal>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs }:
  { value: T; onChange: (t: T) => void; tabs: { id: T; label: ReactNode; count?: number; hidden?: boolean }[] }) {
  return (
    <div className="tabs">
      {tabs.filter((t) => !t.hidden).map((t) => (
        <button key={t.id} className={t.id === value ? "on" : ""} onClick={() => onChange(t.id)}>
          {t.label}{t.count !== undefined && <span className="n num">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Loading() {
  return <div className="empty"><span className="spinner" /></div>;
}

export function ErrorBox({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return (
    <div className="notice err row">
      <span className="grow">{text}</span>
      {onRetry && <Btn small icon="refresh" onClick={onRetry}>إعادة المحاولة</Btn>}
    </div>
  );
}

export function SearchBox({ value, onChange, placeholder = "بحث…" }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div className="unit-in search-in">
      <input className="input" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      <span className="u"><Icon name="search" size={15} /></span>
    </div>
  );
}

export function FilePick({ accept, onFile, children, icon = "upload", busy }:
  { accept?: string; onFile: (f: File) => void; children: ReactNode; icon?: IconName; busy?: boolean }) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <>
      <input ref={ref} type="file" accept={accept} hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
      <Btn icon={icon} busy={busy} onClick={() => ref.current?.click()}>{children}</Btn>
    </>
  );
}

export function KV({ items }: { items: [ReactNode, ReactNode][] }) {
  return <dl className="kv">{items.map(([k, v], i) => <div key={i} style={{ display: "contents" }}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>;
}
