/** Turns what a screen shows (its tables and detail boxes) into a printable report for `POST /documents/report`. */
export type ReportSection = { title: string; kv: [string, string][]; columns: string[]; rows: string[][]; nums: number[] };
export type Report = { title: string; subtitle: string; sections: ReportSection[] };

const SKIP = new Set(["BUTTON", "SCRIPT", "STYLE", "SVG", "IMG", "svg"]);

/** Visible text of a cell: typed values of inputs, chosen option of selects, ✓ for ticked boxes, no buttons/icons. */
export function textOf(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  if (!(node instanceof Element) || SKIP.has(node.tagName)) return "";
  if (node instanceof HTMLInputElement) {
    if (node.type === "checkbox" || node.type === "radio") return node.checked ? "✓" : "";
    if (node.type === "file" || node.type === "hidden") return "";
    return node.value;
  }
  if (node instanceof HTMLSelectElement) return node.selectedOptions[0]?.textContent ?? "";
  if (node instanceof HTMLTextAreaElement) return node.value;
  const parts = Array.from(node.childNodes).map(textOf).filter((t) => t.trim());
  return parts.join(" ").replace(/\s+/g, " ").trim();
}

function titleFor(el: Element): string {
  const card = el.closest(".card");
  const h = card?.querySelector(":scope > .card-h h3, :scope > .card-h");
  const tab = el.closest(".content")?.querySelector(".tabs button.on")?.firstChild?.textContent ?? "";
  return (h ? textOf(h) : "") || tab.trim();
}

function tableSection(table: HTMLTableElement): ReportSection | null {
  const head = Array.from(table.tHead?.rows[0]?.cells ?? table.rows[0]?.cells ?? []);
  const keep = head.map((c, i) => [i, textOf(c)] as const).filter(([, t]) => t !== "");
  if (!keep.length) return null;
  const body = Array.from(table.tBodies).flatMap((b) => Array.from(b.rows));
  const rows = body.map((r) => keep.map(([i]) => (r.cells[i] ? textOf(r.cells[i]) : "")))
    .filter((r) => r.some((v) => v !== ""));
  const nums = keep.map(([i], j) => (head[i].classList.contains("n") ? j : -1)).filter((j) => j >= 0);
  return { title: titleFor(table), kv: [], columns: keep.map(([, t]) => t), rows, nums };
}

function kvSection(dl: HTMLElement): ReportSection | null {
  const kv: [string, string][] = [];
  dl.querySelectorAll(":scope > div").forEach((d) => {
    const k = d.querySelector("dt"), v = d.querySelector("dd");
    if (k && v && textOf(k)) kv.push([textOf(k), textOf(v)]);
  });
  return kv.length ? { title: titleFor(dl), kv, columns: [], rows: [], nums: [] } : null;
}

function totalsSection(box: HTMLElement): ReportSection | null {
  const kv: [string, string][] = [];
  box.querySelectorAll(":scope > .r").forEach((r) => {
    const cells = Array.from(r.children);
    if (cells.length >= 2) kv.push([textOf(cells[0]), textOf(cells[cells.length - 1])]);
  });
  return kv.length ? { title: titleFor(box), kv, columns: [], rows: [], nums: [] } : null;
}

function headSection(box: HTMLElement): ReportSection | null {
  const kv: [string, string][] = [];
  box.querySelectorAll(":scope > div").forEach((d) => {
    const k = d.querySelector(".k");
    if (!k) return;
    const v = Array.from(d.childNodes).filter((n) => n !== k).map(textOf).join(" ").trim();
    kv.push([textOf(k), v]);
  });
  return kv.length ? { title: "", kv, columns: [], rows: [], nums: [] } : null;
}

export function collectPage(root: HTMLElement, title: string): Report {
  const sections: ReportSection[] = [];
  root.querySelectorAll<HTMLElement>("dl.kv, table, .totals, .sheet-head").forEach((el) => {
    if (el.closest(".overlay, .no-print")) return;
    if (el.tagName === "TABLE" && el.parentElement?.closest("table")) return;
    const s = el.tagName === "TABLE" ? tableSection(el as HTMLTableElement)
      : el.tagName === "DL" ? kvSection(el) : el.classList.contains("totals") ? totalsSection(el) : headSection(el);
    if (s) sections.push(s);
  });
  const search = root.querySelector<HTMLInputElement>(".search-in input")?.value?.trim();
  return { title, subtitle: search ? `بحث: ${search}` : "", sections };
}
