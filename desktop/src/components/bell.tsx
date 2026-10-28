// Notifications: the bell in the top bar, and a Windows / Android notification for each new one.
// The program asks the server for new ones every few seconds (works on the factory network, no internet).
import { useEffect, useRef, useState } from "react";
import { api, type S } from "../api/client";
import { inDesktop } from "../lib/discovery";
import { go } from "../lib/router";
import { dateTime } from "../lib/format";
import { Icon } from "./icons";

type Inbox = S<"Inbox">;
type Note = S<"NotificationOut">;
const POLL_MS = 15000;
const CATEGORY: Record<string, string> = { accounts: "الحسابات", sales: "المبيعات", production: "التصنيع", field: "التركيبات",
  deletions: "الحذف", library: "المكتبة" };

async function showNative(title: string, body: string) {
  try {
    if (inDesktop()) {
      const n = await import("@tauri-apps/plugin-notification");
      let ok = await n.isPermissionGranted();
      if (!ok) ok = (await n.requestPermission()) === "granted";
      if (ok) n.sendNotification({ title, body });
      return;
    }
    if (typeof Notification === "undefined") return;
    if (Notification.permission === "default") await Notification.requestPermission();
    if (Notification.permission === "granted") new Notification(title, { body });
  } catch { /* notifications are a convenience: the bell still shows them */ }
}

export function Bell() {
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [open, setOpen] = useState(false);
  const last = useRef<string | null>(null);

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        if (last.current === null) {
          const first = await api.get<Inbox>("/notifications");
          if (stop) return;
          setInbox(first);
          last.current = first.items[0]?.created_at ?? new Date().toISOString();
          return;
        }
        const fresh = await api.get<Inbox>("/notifications", { after: last.current });
        if (stop) return;
        if (fresh.items.length) {
          last.current = fresh.items[0].created_at;
          const shown = fresh.items.slice(0, 3);
          for (const n of shown) showNative(n.title, n.body);
          if (fresh.items.length > shown.length) showNative("MYTech", `${fresh.items.length - shown.length} إشعارات تانية`);
          setInbox((old) => ({ unread: fresh.unread, items: [...fresh.items, ...(old?.items ?? [])].slice(0, 50) }));
        } else setInbox((old) => old && { ...old, unread: fresh.unread });
      } catch { /* offline for a moment: try again next time */ }
    };
    tick();
    const t = setInterval(tick, POLL_MS);
    return () => { stop = true; clearInterval(t); };
  }, []);

  const openNote = async (n: Note) => {
    setOpen(false);
    if (!n.read_at) setInbox(await api.post<Inbox>(`/notifications/${n.id}/read`).catch(() => inbox));
    if (n.link) go(n.link);
  };
  const unread = inbox?.unread ?? 0;
  return (
    <div style={{ position: "relative" }}>
      <button className="icon-btn bell" onClick={() => setOpen((o) => !o)} title="الإشعارات">
        <Icon name="bell" />{unread > 0 && <span className="bell-count num">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="card bell-panel" onMouseLeave={() => setOpen(false)}>
          <div className="row" style={{ padding: "8px 10px", borderBottom: "1px solid var(--border)" }}>
            <b>الإشعارات</b>
            {unread > 0 && <button className="btn ghost sm end" onClick={async () => setInbox(await api.post<Inbox>("/notifications/read-all"))}>
              تعليم الكل كمقروء</button>}
          </div>
          <div style={{ maxHeight: 420, overflowY: "auto" }}>
            {!inbox?.items.length && <div className="muted" style={{ padding: 16, textAlign: "center" }}>مفيش إشعارات</div>}
            {inbox?.items.map((n) => (
              <button key={n.id} className={"bell-item" + (n.read_at ? "" : " unread")} onClick={() => openNote(n)}>
                <div className="row" style={{ gap: 6 }}><span className="chip gray">{CATEGORY[n.category] ?? n.category}</span>
                  <span className="muted small num end">{dateTime(n.created_at)}</span></div>
                <div className="bold">{n.title}</div>
                {n.body && <div className="small muted">{n.body}</div>}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
