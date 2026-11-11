/** Turns what a screen shows (its tables and detail boxes) into a printable report for `POST /documents/report`. */
export type ReportSection = { title: string; kv: [string, string][]; columns: string[]; rows: string[][]; nums: number[];
  pics?: string[][][] };

// the drawings use the screen's colours (CSS variables): on paper they are drawn in these
const PAPER: Record<string, string> = { "--card": "#FFFFFF", "--stroke": "#475569", "--gray-soft": "#E5E7EB", "--glass": "#DBEAFE",
  "--muted": "#64748B", "--primary": "#5048E5", "--text": "#1B2533", "--border": "#CBD5E1" };

/** The pictures in a cell (a model's photo, a window's drawing) as inline images for the printout; icons left out. */
export function cellPics(cell: Element): string[] {
  const out: string[] = [];
  for (const el of Array.from(cell.querySelectorAll("img, svg"))) {
    if (out.length >= 3) break;
    try {
      if (el instanceof HTMLImageElement) {
        if (!el.complete || !el.naturalWidth) continue;
        const scale = Math.min(1, 220 / Math.max(el.naturalWidth, el.naturalHeight));
        const c = document.createElement("canvas");
        c.width = Math.round(el.naturalWidth * scale);
        c.height = Math.round(el.naturalHeight * scale);
        c.getContext("2d")!.drawImage(el, 0, 0, c.width, c.height);
        out.push(c.toDataURL("image/png"));
      } else if (el instanceof SVGSVGElement && !el.closest(".icon, button") && el.getBoundingClientRect().width >= 40) {
        const copy = el.cloneNode(true) as SVGSVGElement;
        copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
        const text = new XMLSerializer().serializeToString(copy)
          .replace(/var\((--[\w-]+)\)/g, (_, v: string) => PAPER[v] ?? "#475569");
        out.push("data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(text))));
      }
    } catch { /* a picture that cannot be copied (another site's) is left out */ }
  }
  return out;
}
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
  const keep = head.map((c, i) => [i, textOf(c).replace(/[▲▼]/g, "").trim()] as const).filter(([, t]) => t !== "");
  if (!keep.length) return null;
  const body = Array.from(table.tBodies).flatMap((b) => Array.from(b.rows)).filter((r) => !r.hidden);   // filtered out: not printed
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
