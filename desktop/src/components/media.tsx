import { useEffect, useRef, useState, type ReactElement } from "react";
import { api, errorText } from "../api/client";
import { Btn, Modal } from "./ui";
import { useToast } from "../state/toast";

// Images need the bearer token, so they are fetched once and kept as object URLs.
const cache = new Map<string, Promise<string>>();

export function mediaUrl(id: string): Promise<string> {
  let p = cache.get(id);
  if (!p) {
    p = api.blob(`/media/${id}`).then((b) => URL.createObjectURL(b));
    p.catch(() => cache.delete(id));
    cache.set(id, p);
  }
  return p;
}

export function MediaImg({ id, className = "thumb", alt = "" }: { id: string | null | undefined; className?: string; alt?: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setSrc(null);
    if (id) mediaUrl(id).then((u) => live && setSrc(u)).catch(() => undefined);
    return () => { live = false; };
  }, [id]);
  if (!id) return <span className={className} style={{ display: "inline-grid", placeItems: "center" }}><span className="faint small">—</span></span>;
  return src ? <img className={className} src={src} alt={alt} /> : <span className={className} style={{ display: "inline-block" }} />;
}

type El = { type?: string; x_mm?: string | number; y_mm?: string | number; w_mm?: string | number; h_mm?: string | number;
  opening?: string | null; label?: string | null };

/** Drawing from the engine's drawing elements (frame / sash / glass / panel / mullion). */
export function Drawing({ elements, w, h, maxW = 150, maxH = 110 }:
  { elements: El[] | undefined; w?: string | number | null; h?: string | number | null; maxW?: number; maxH?: number }) {
  const els = elements ?? [];
  const fw = Number(w ?? Math.max(1, ...els.map((e) => Number(e.w_mm ?? 0))));
  const fh = Number(h ?? Math.max(1, ...els.map((e) => Number(e.h_mm ?? 0))));
  if (!fw || !fh) return null;
  const sc = Math.min((maxW - 8) / fw, (maxH - 8) / fh);
  const W = fw * sc, H = fh * sc;
  const parts: ReactElement[] = [];
  els.forEach((e, i) => {
    const kind = e.type ?? "rect";
    if (kind === "frame") return;
    const x = 4 + Number(e.x_mm ?? 0) * sc, y = 4 + Number(e.y_mm ?? 0) * sc;
    const ew = Number(e.w_mm ?? 0) * sc, eh = Number(e.h_mm ?? 0) * sc;
    const inset = kind === "sash" ? 3 : 0;
    parts.push(<rect key={i + "a"} x={x} y={y} width={ew} height={eh} fill="var(--card)" stroke="var(--stroke)" strokeWidth={0.9} />);
    if (["sash", "glass", "rect", "panel"].includes(kind)) {
      parts.push(<rect key={i + "b"} x={x + inset} y={y + inset} width={Math.max(ew - 2 * inset, 1)} height={Math.max(eh - 2 * inset, 1)}
        fill={kind === "panel" ? "var(--gray-soft)" : "var(--glass)"} stroke="var(--muted)" strokeWidth={0.7} />);
    }
    const op = (e.opening ?? "").toLowerCase();
    const cx = x + ew / 2, cy = y + eh / 2;
    if (op.startsWith("sliding")) {
      const d = op.endsWith("right") ? 1 : -1;
      parts.push(<path key={i + "c"} d={`M${cx - 8 * d} ${cy} h${16 * d} m${-4 * d} -3 l${4 * d} 3 l${-4 * d} 3`}
        stroke="var(--primary)" strokeWidth={1.2} fill="none" />);
    } else if (op.startsWith("casement") || op.startsWith("tilt")) {
      const hinge = op.endsWith("left") ? x + ew - inset : x + inset;
      const tip = op.endsWith("left") ? x + inset : x + ew - inset;
      parts.push(<path key={i + "c"} d={`M${hinge} ${y + inset} L${tip} ${cy} L${hinge} ${y + eh - inset}`} stroke="var(--primary)"
        strokeWidth={0.9} strokeDasharray="3 2" fill="none" />);
      if (op.startsWith("tilt")) parts.push(<path key={i + "d"} d={`M${x + inset} ${y + eh - inset} L${cx} ${y + inset} L${x + ew - inset} ${y + eh - inset}`}
        stroke="var(--primary)" strokeWidth={0.9} strokeDasharray="3 2" fill="none" />);
    }
  });
  return (
    <span className="drawing" style={{ display: "inline-block", direction: "ltr" }}>
      <svg viewBox={`0 0 ${W + 8} ${H + 8}`} width={W + 8} height={H + 8}>
        <rect x={4} y={4} width={W} height={H} fill="var(--sunken)" stroke="var(--stroke)" strokeWidth={1.4} />
        {parts}
      </svg>
    </span>
  );
}

/** Shows a printable document from the server (A4 HTML with the company's logo) and prints it. */
export function PrintPreview({ path, title, onClose }: { path: string; title: string; onClose: () => void }) {
  const [html, setHtml] = useState<string | null>(null);
  const frame = useRef<HTMLIFrameElement>(null);
  const toast = useToast();
  useEffect(() => {
    api.text(path).then(setHtml).catch((e) => { toast.err(errorText(e)); onClose(); });
  }, [path]); // eslint-disable-line react-hooks/exhaustive-deps
  const print = () => frame.current?.contentWindow?.print();
  const save = () => {
    if (!html) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    a.download = title.replace(/[\\/:*?"<>|]+/g, "-") + ".html";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  };
  return (
    <Modal title={title} onClose={onClose} size="xwide" footer={<>
      <Btn kind="primary" icon="print" onClick={print} disabled={!html}>طباعة / حفظ PDF</Btn>
      <Btn icon="download" onClick={save} disabled={!html}>حفظ نسخة</Btn>
      <span className="muted small" style={{ alignSelf: "center" }}>لحفظه PDF اختار "Microsoft Print to PDF" من شاشة الطباعة.</span>
    </>}>
      {html ? <iframe ref={frame} className="print-frame" srcDoc={html} sandbox="allow-modals allow-same-origin" title={title} />
        : <div className="empty"><span className="spinner" /></div>}
    </Modal>
  );
}
