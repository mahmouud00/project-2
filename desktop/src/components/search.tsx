// البحث الشامل: Ctrl + K (or the magnifier in the top bar) opens one box that finds customers, surveys, quotations,
// orders, invoices, purchases, suppliers, employees and library items. The server only returns what the user may see.
import { useEffect, useMemo, useRef, useState } from "react";
import { api, errorText } from "../api/client";
import { go } from "../lib/router";
import { Icon } from "./icons";

type Hit = { id: string; title: string; subtitle: string; path: string; query: Record<string, string> };
type Group = { kind: string; label: string; items: Hit[] };

export function SearchButton() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "k" || e.key === "K" || e.code === "KeyK")) {
        e.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  return (
    <>
      <button className="icon-btn" onClick={() => setOpen(true)} title="بحث في كل البرنامج (Ctrl + K)" aria-label="بحث"><Icon name="search" /></button>
      {open && <SearchPalette onClose={() => setOpen(false)} />}
    </>
  );
}

function SearchPalette({ onClose }: { onClose: () => void }) {
  const [q, setQ] = useState("");
  const [groups, setGroups] = useState<Group[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const list = useRef<HTMLDivElement>(null);
  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);

  useEffect(() => {
    const text = q.trim();
    if (!text) { setGroups([]); setError(null); return; }
    let live = true;
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        const r = await api.get<{ groups: Group[] }>("/search", { q: text });
        if (live) { setGroups(r.groups); setActive(0); setError(null); }
      } catch (e) {
        if (live) setError(errorText(e));
      } finally {
        if (live) setBusy(false);
      }
    }, 250);
    return () => { live = false; clearTimeout(t); };
  }, [q]);

  useEffect(() => {
    list.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const open = (h: Hit) => { onClose(); go(h.path, h.query); };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.preventDefault(); onClose(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, flat.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter" && flat[active]) { e.preventDefault(); open(flat[active]); }
  };

  let i = -1;
  return (
    <div className="palette-backdrop" onMouseDown={onClose}>
      <div className="palette card" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label="بحث">
        <div className="palette-input">
          <Icon name="search" />
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey}
            placeholder="اسم عميل، تليفون، رقم عرض أو أمر أو فاتورة، كود نموذج أو خامة…" />
          {busy && <span className="spinner" />}
          <kbd className="hide-phone">Esc</kbd>
        </div>
        <div className="palette-list" ref={list}>
          {error && <div className="notice err">{error}</div>}
          {!q.trim() && <div className="empty small">اكتب أي حاجة تدوّر عليها. ↑ ↓ تتنقل، و Enter تفتح.</div>}
          {q.trim() && !busy && !error && !flat.length && <div className="empty small">مفيش نتايج لـ «{q.trim()}»</div>}
          {groups.map((g) => (
            <div key={g.kind}>
              <div className="palette-group">{g.label}</div>
              {g.items.map((h) => {
                i += 1;
                const n = i;
                return (
                  <button key={g.kind + h.id + h.path} data-i={n} className={"palette-item" + (n === active ? " on" : "")}
                    onMouseEnter={() => setActive(n)} onClick={() => open(h)}>
                    <b>{h.title}</b>{h.subtitle && <span className="muted small">{h.subtitle}</span>}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
