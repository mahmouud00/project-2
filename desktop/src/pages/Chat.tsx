// الشات بين المستخدمين: محادثات فردية وجروبات، صور وملفات، أونلاين وآخر ظهور. وتفويض الصلاحيات من نفس الصفحة.
import { useEffect, useRef, useState } from "react";
import { api, raw, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad } from "../lib/hooks";
import { useToast } from "../state/toast";
import { Btn, Check, Chip, Field, Modal, PageHead, Tabs, TextIn } from "../components/ui";
import { setQuery } from "../lib/router";
import { dateTime } from "../lib/format";
import { saveFile } from "../lib/save";

type Person = S<"PersonOut">;
type Conv = S<"ConversationOut">;
type Msg = S<"MessageOut">;
type Deleg = S<"DelegationOut">;

/** «متصل» / «آخر ظهور من 5 دقايق» */
export function seen(p: { online: boolean; last_seen_at?: string | null }): string {
  if (p.online) return "متصل الآن";
  if (!p.last_seen_at) return "لسه مادخلش";
  const min = Math.round((Date.now() - new Date(p.last_seen_at).getTime()) / 60000);
  if (min < 60) return `آخر ظهور من ${min} دقيقة`;
  if (min < 24 * 60) return `آخر ظهور من ${Math.round(min / 60)} ساعة`;
  return `آخر ظهور ${dateTime(p.last_seen_at)}`;
}

export default function Chat({ route }: PageProps) {
  useTitle("الشات");
  const tab = route.query.tab ?? "chat";
  return (
    <div className="col" style={{ gap: 12 }}>
      <Tabs value={tab} onChange={(t) => setQuery({ tab: t })} tabs={[{ id: "chat", label: "الشات" }, { id: "delegations", label: "تفويض الصلاحيات" }]} />
      {tab === "delegations" ? <Delegations /> : <ChatView open={route.query.c ?? null} />}
    </div>
  );
}

function Dot({ on }: { on: boolean }) {
  return <span style={{ display: "inline-block", width: 9, height: 9, borderRadius: 9, background: on ? "var(--success)" : "var(--faint, #9aa5b1)", marginInlineEnd: 6 }} />;
}

function ChatView({ open }: { open: string | null }) {
  const toast = useToast();
  const convs = useLoad(() => api.get<Conv[]>("/chat/conversations"), []);
  const people = useLoad(() => api.get<Person[]>("/chat/people"), []);
  const [group, setGroup] = useState(false);
  useEffect(() => {                                   // the list and who is online, every 10 seconds
    const t = setInterval(() => { convs.reload(); people.reload(); }, 10000);
    return () => clearInterval(t);
  }, [convs.reload, people.reload]);
  const start = async (p: Person) => {
    try { const c = await api.post<Conv>(`/chat/direct/${p.id}`); convs.reload(); setQuery({ c: c.id }); }
    catch (e) { toast.err(String((e as Error).message)); }
  };
  const current = convs.data?.find((c) => c.id === open) ?? null;
  return (
    <div className="chat-layout" style={{ display: "grid", gridTemplateColumns: "minmax(240px, 320px) 1fr", gap: 12, minHeight: "70vh" }}>
      <div className="card" style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div className="card-h"><h3>المحادثات</h3><Btn small icon="plus" className="end" onClick={() => setGroup(true)}>جروب</Btn></div>
        <div style={{ overflow: "auto", flex: 1 }}>
          {(convs.data ?? []).map((c) => {
            const other = c.kind === "direct" ? c.members.find((m) => !c.title.includes("،") && m.full_name === c.title) : null;
            return (
              <a key={c.id} className={"chat-item" + (c.id === open ? " active" : "")} onClick={() => setQuery({ c: c.id })}
                style={{ display: "block", padding: "10px 12px", borderBottom: "1px solid var(--border)", cursor: "pointer",
                  background: c.id === open ? "var(--selected)" : undefined }}>
                <div className="row" style={{ gap: 6 }}>
                  {other && <Dot on={other.online} />}<b>{c.title}</b>
                  {c.unread > 0 && <Chip color="green">{c.unread}</Chip>}
                  <span className="end muted small num">{c.last_message_at ? dateTime(c.last_message_at).slice(-5) : ""}</span>
                </div>
                <div className="muted small" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.last_message ?? ""}</div>
              </a>
            );
          })}
          {convs.data && !convs.data.length && <div className="muted small" style={{ padding: 12 }}>مفيش محادثات لسه: اختار حد من تحت.</div>}
          <div className="nav-group" style={{ padding: "10px 12px 4px" }}>الزملاء</div>
          {(people.data ?? []).map((p) => (
            <a key={p.id} onClick={() => start(p)} style={{ display: "block", padding: "8px 12px", cursor: "pointer" }}>
              <div className="row" style={{ gap: 6 }}><Dot on={p.online} /><span>{p.full_name}</span></div>
              <div className="muted small">{seen(p)}</div>
            </a>
          ))}
        </div>
      </div>
      {current ? <Thread conv={current} onSent={convs.reload} /> :
        <div className="card" style={{ display: "grid", placeItems: "center" }}><div className="muted">اختار محادثة أو زميل عشان تبدأ</div></div>}
      {group && <NewGroup people={people.data ?? []} onClose={() => setGroup(false)} onMade={(c) => { convs.reload(); setQuery({ c: c.id }); }} />}
    </div>
  );
}

function Thread({ conv, onSent }: { conv: Conv; onSent: () => void }) {
  const toast = useToast();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const last = useRef<string | null>(null);
  const names = Object.fromEntries(conv.members.map((m) => [m.id, m.full_name]));
  const others = conv.members;

  useEffect(() => {
    let live = true;
    last.current = null;
    setMsgs([]);
    const load = async () => {
      try {
        const fresh = await api.get<Msg[]>(`/chat/conversations/${conv.id}/messages`, last.current ? { after: last.current } : undefined);
        if (!live || !fresh.length) return;
        last.current = fresh[fresh.length - 1].at;
        setMsgs((m) => last.current && m.length ? [...m, ...fresh.filter((x) => !m.some((y) => y.id === x.id))] : fresh);
      } catch { /* the next poll tries again */ }
    };
    load();
    const t = setInterval(load, 4000);                // new messages every 4 seconds while it is open
    return () => { live = false; clearInterval(t); };
  }, [conv.id]);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [msgs.length]);

  const send = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      const m = await api.post<Msg>(`/chat/conversations/${conv.id}/messages`, { body: text.trim() });
      setMsgs((x) => [...x, m]); last.current = m.at; setText(""); onSent();
    } catch (e) { toast.err(String((e as Error).message)); } finally { setBusy(false); }
  };
  const sendFile = async (f: File) => {
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", f);
      const r = await raw(`/chat/conversations/${conv.id}/files?caption=${encodeURIComponent(text.trim())}`, { method: "POST", body: form });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.error?.message ?? "ماقدرتش أبعت الملف");
      const m = await r.json() as Msg;
      setMsgs((x) => [...x, m]); last.current = m.at; setText(""); onSent();
    } catch (e) { toast.err(String((e as Error).message)); } finally { setBusy(false); if (fileRef.current) fileRef.current.value = ""; }
  };
  const direct = conv.kind === "direct" ? conv.members.find((m) => m.full_name === conv.title) : null;
  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div className="card-h"><h3>{conv.title}</h3>
        <span className="muted small">{direct ? seen(direct) : `${others.length} أعضاء`}</span></div>
      <div style={{ flex: 1, overflow: "auto", padding: 12, display: "flex", flexDirection: "column", gap: 8 }}>
        {msgs.map((m) => <Bubble key={m.id} m={m} who={conv.kind === "group" && !m.mine ? names[m.sender_id] : undefined} />)}
        <div ref={endRef} />
      </div>
      <div className="row" style={{ gap: 8, padding: 10, borderTop: "1px solid var(--border)" }}>
        <input ref={fileRef} type="file" hidden onChange={(e) => e.target.files?.[0] && sendFile(e.target.files[0])} />
        <Btn icon="upload" title="صورة أو ملف" busy={busy} onClick={() => fileRef.current?.click()} />
        <div className="grow"><TextIn value={text} onChange={setText} placeholder="اكتب رسالة…"
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} /></div>
        <Btn kind="primary" icon="send" busy={busy} disabled={!text.trim()} onClick={send}>ابعت</Btn>
      </div>
    </div>
  );
}

function Bubble({ m, who }: { m: Msg; who?: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const image = (m.file_mime ?? "").startsWith("image/");
  useEffect(() => {
    if (!image || !m.file_url) return;
    let url: string | null = null;
    raw(m.file_url.replace(/^\/api\/v1/, "")).then((r) => r.blob()).then((b) => { url = URL.createObjectURL(b); setSrc(url); }).catch(() => undefined);
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [m.file_url, image]);
  const download = async () => {
    const r = await raw(m.file_url!.replace(/^\/api\/v1/, ""));
    await saveFile(m.file_name ?? "file", await r.blob());
  };
  return (
    <div style={{ alignSelf: m.mine ? "flex-start" : "flex-end", maxWidth: "75%", background: m.mine ? "var(--primary-soft)" : "var(--card-2, var(--selected))",
      borderRadius: 12, padding: "8px 12px" }}>
      {who && <div className="small bold" style={{ color: "var(--primary)" }}>{who}</div>}
      {image && src && <img src={src} alt={m.file_name ?? ""} style={{ maxWidth: 280, maxHeight: 280, borderRadius: 8, display: "block", cursor: "pointer" }} onClick={download} />}
      {m.file_url && !image && <a style={{ cursor: "pointer" }} onClick={download}>📎 {m.file_name} <span className="muted small num">({Math.max(1, Math.round((m.file_size ?? 0) / 1024))} KB)</span></a>}
      {m.body && <div style={{ whiteSpace: "pre-wrap" }}>{m.body}</div>}
      <div className="muted small num" style={{ textAlign: "end" }}>{dateTime(m.at)}</div>
    </div>
  );
}

function NewGroup({ people, onClose, onMade }: { people: Person[]; onClose: () => void; onMade: (c: Conv) => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [title, setTitle] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  return (
    <Modal title="جروب جديد" onClose={onClose} footer={<><Btn kind="primary" busy={busy} disabled={!title.trim() || !picked.size}
      onClick={() => run(async () => { onMade(await api.post<Conv>("/chat/groups", { title: title.trim(), user_ids: [...picked] })); onClose(); })}>إنشاء</Btn>
      <Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col">
        <Field label="اسم الجروب"><TextIn value={title} onChange={setTitle} autoFocus /></Field>
        <div className="col" style={{ maxHeight: 300, overflow: "auto", gap: 2 }}>
          {people.map((p) => <Check key={p.id} label={p.full_name} checked={picked.has(p.id)}
            onChange={(v) => setPicked((x) => { const y = new Set(x); v ? y.add(p.id) : y.delete(p.id); return y; })} />)}
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- تفويض الصلاحيات
function Delegations() {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const list = useLoad(() => api.get<Deleg[]>("/delegations"), []);
  const people = useLoad(() => api.get<Person[]>("/chat/people"), []);
  const [d, setD] = useState({ to: "", from: "", until: "", note: "" });
  const save = () => run(async () => {
    await api.post("/delegations", { to_user_id: d.to, starts_at: d.from ? new Date(d.from).toISOString() : null,
      ends_at: new Date(d.until).toISOString(), note: d.note });
    toast.ok("اتعمل التفويض: الزميل ده بقى معاه صلاحياتك في المدة دي.");
    setD({ to: "", from: "", until: "", note: "" }); list.reload();
  });
  return (
    <div className="col" style={{ gap: 12 }}>
      <div className="card"><div className="card-h"><h3>فوّض صلاحياتك لزميل لمدة معينة</h3></div>
        <div className="card-b col">
          <div className="muted small">الزميل بياخد كل صلاحياتك (في فروعك) من الوقت ده لحد الوقت ده بس، ومايقدرش يفوّضها لحد تاني. وأي حاجة يعملها بتتسجل باسمه في سجل التعديلات.</div>
          <div className="grid g4">
            <Field label="الزميل"><select className="input" value={d.to} onChange={(e) => setD({ ...d, to: e.target.value })}>
              <option value="">اختار…</option>{(people.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}</select></Field>
            <Field label="من" hint="فاضي = دلوقتي"><input type="datetime-local" className="input" value={d.from} onChange={(e) => setD({ ...d, from: e.target.value })} /></Field>
            <Field label="لحد"><input type="datetime-local" className="input" value={d.until} onChange={(e) => setD({ ...d, until: e.target.value })} /></Field>
            <Field label="ملاحظة"><TextIn value={d.note} onChange={(v) => setD({ ...d, note: v })} placeholder="مثلًا: إجازة" /></Field>
          </div>
          <div><Btn kind="primary" busy={busy} disabled={!d.to || !d.until} onClick={save}>تفويض</Btn></div>
        </div>
      </div>
      <PageHead title="التفويضات" />
      <table className="table"><thead><tr><th>من</th><th>لـ</th><th>من وقت</th><th>لحد</th><th>ملاحظة</th><th>الحالة</th><th /></tr></thead>
        <tbody>{(list.data ?? []).map((x) => <tr key={x.id}>
          <td>{x.from_name}</td><td>{x.to_name}</td><td className="num">{dateTime(x.starts_at)}</td><td className="num">{dateTime(x.ends_at)}</td>
          <td className="small">{x.note}</td>
          <td>{x.revoked_at ? <Chip>اتوقف</Chip> : x.active ? <Chip color="green">شغال</Chip> : new Date(x.starts_at) > new Date() ? <Chip color="amber">لسه</Chip> : <Chip>خلص</Chip>}</td>
          <td>{!x.revoked_at && new Date(x.ends_at) > new Date() && <Btn small kind="danger" onClick={() => run(async () => { await api.post(`/delegations/${x.id}/revoke`); list.reload(); })}>إيقاف</Btn>}</td>
        </tr>)}</tbody></table>
      {list.data && !list.data.length && <div className="muted small">مفيش تفويضات.</div>}
    </div>
  );
}
