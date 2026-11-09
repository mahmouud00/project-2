// A select with a search box: for long lists (a system's materials). Click, type part of the code or the name,
// pick with the mouse or ↑ ↓ Enter. The list floats over the page (position: fixed), so a table never clips it.
import { useEffect, useLayoutEffect, useRef, useState } from "react";

type Opt = { value: string; label: string };

/** Arabic letters compared loosely (أ/إ/آ = ا, ة = ه, ى = ي), case and spaces ignored. */
export function loose(s: string): string {
  return s.replace(/[أإآٱ]/g, "ا").replace(/ة/g, "ه").replace(/ى/g, "ي").replace(/ـ/g, "").replace(/\s+/g, " ").trim().toLowerCase();
}

export function SearchSelect({ value, onChange, options, placeholder = "اختار…", disabled, emptyLabel }:
  { value: string | null | undefined; onChange: (v: string | null) => void; options: Opt[]; placeholder?: string;
    disabled?: boolean; emptyLabel?: string }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [hi, setHi] = useState(0);
  const [pos, setPos] = useState<{ top: number; left: number; width: number; up: boolean } | null>(null);
  const box = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const current = options.find((o) => o.value === value);
  const words = loose(q).split(" ").filter(Boolean);
  const shown = (emptyLabel !== undefined ? [{ value: "", label: emptyLabel }] : []).concat(
    options.filter((o) => words.every((w) => loose(o.label + " " + o.value).includes(w))));

  useLayoutEffect(() => {
    if (!open || !box.current) return;
    const r = box.current.getBoundingClientRect();
    const up = r.bottom + 300 > window.innerHeight && r.top > 300;
    setPos({ top: up ? r.top : r.bottom, left: r.left, width: Math.max(r.width, 260), up });
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e.type === "scroll" && list.current?.contains(e.target as Node)) return;
      if (e.type === "mousedown" && (list.current?.contains(e.target as Node) || box.current?.contains(e.target as Node))) return;
      setOpen(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("scroll", close, true); window.removeEventListener("resize", close); };
  }, [open]);
  useEffect(() => { list.current?.querySelector(".ss-opt.hi")?.scrollIntoView({ block: "nearest" }); }, [hi]);

  const pick = (o: Opt) => { onChange(o.value || null); setOpen(false); box.current?.focus(); };
  const key = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(h + 1, shown.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); if (shown[hi]) pick(shown[hi]); }
    else if (e.key === "Escape") { e.preventDefault(); setOpen(false); box.current?.focus(); }
  };
  return (
    <>
      <button type="button" ref={box} className="input ss-box" disabled={disabled} title={current?.label}
        onClick={() => { setQ(""); setHi(0); setOpen((o) => !o); }}
        onKeyDown={(e) => { if (!open && (e.key === "ArrowDown" || e.key === "Enter")) { e.preventDefault(); setQ(""); setHi(0); setOpen(true); } }}>
        <span className={current ? "" : "faint"}>{current?.label ?? (value ? value : (emptyLabel ?? placeholder))}</span>
      </button>
      {open && pos && (
        <div ref={list} className="ss-pop card" style={{ left: pos.left, width: pos.width,
          ...(pos.up ? { bottom: window.innerHeight - pos.top + 4 } : { top: pos.top + 4 }) }}>
          <input className="input" autoFocus value={q} placeholder="ابحث بالكود أو الاسم…" onKeyDown={key}
            onChange={(e) => { setQ(e.target.value); setHi(0); }} />
          <div className="ss-list">
            {shown.map((o, i) => (
              <div key={o.value || "_"} className={"ss-opt" + (i === hi ? " hi" : "") + (o.value === (value ?? "") ? " on" : "")}
                onMouseEnter={() => setHi(i)} onMouseDown={(e) => { e.preventDefault(); pick(o); }}>{o.label}</div>
            ))}
            {!shown.length && <div className="faint small" style={{ padding: 8 }}>مفيش نتايج</div>}
          </div>
        </div>
      )}
    </>
  );
}
