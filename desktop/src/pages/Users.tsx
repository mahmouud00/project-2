import { useState } from "react";
import { api, errorText, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad } from "../lib/hooks";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Check, Chip, Confirm, ErrorBox, Field, Loading, Modal, PageHead, Pager, Select, Table, Tabs, TextIn } from "../components/ui";
import { invalidate, lookups } from "../lib/lookups";
import { setQuery } from "../lib/router";

type User = S<"UserOut">;
type Role = S<"RoleOut">;

export default function Users({ route }: PageProps) {
  useTitle("المستخدمين والصلاحيات");
  const tab = route.query.tab ?? "users";
  return (
    <Card flush>
      <Tabs value={tab} onChange={(t) => setQuery({ tab: t })} tabs={[{ id: "users", label: "المستخدمين" }, { id: "roles", label: "الأدوار والصلاحيات" }]} />
      <div className="card-b">{tab === "users" ? <UserList /> : <RoleList />}</div>
    </Card>
  );
}

function UserList() {
  const s = useSession();
  const [offset, setOffset] = useState(0);
  const [edit, setEdit] = useState<Partial<User> | null>(null);
  const [reset, setReset] = useState<User | null>(null);
  const [perms, setPerms] = useState<User | null>(null);
  const toast = useToast();
  const list = useLoad(() => api.get<S<"Page_UserOut_">>("/users", { limit: 50, offset }), [offset]);
  const roles = useLoad(() => lookups.roles(), []);
  const roleName = (id: string) => roles.data?.find((r) => r.id === id)?.name ?? "";
  const branchName = (id: string | null) => id ? s.branches.find((b) => b.id === id)?.name ?? "" : "كل الفروع";
  return (
    <div className="col">
      <PageHead>
        {s.license.max_users && <span className="muted small">الترخيص: حتى <span className="num">{s.license.max_users}</span> مستخدم</span>}
        <Btn kind="primary" icon="plus" onClick={() => setEdit({ assignments: [] })}>مستخدم جديد</Btn>
      </PageHead>
      <Table rows={list.data?.items} loading={list.loading} onRow={(u) => setEdit(u)} columns={[
        { key: "u", label: "اسم الدخول", render: (u) => <span className="code">{u.username}</span> },
        { key: "n", label: "الاسم", render: (u) => <b>{u.full_name}</b> },
        { key: "r", label: "الأدوار", render: (u) => <div className="row wrap" style={{ gap: 4 }}>{(u.assignments ?? []).map((a, i) =>
          <Chip key={i} color="blue">{roleName(a.role_id)} · {branchName(a.branch_id)}</Chip>)}</div> },
        { key: "s", label: "الحالة", render: (u) => u.is_active ? <Chip color="green">نشط</Chip> : <Chip color="red">متوقف</Chip> },
        { key: "p", label: "الصلاحيات", render: (u) => <span className="row" style={{ gap: 6 }}>
          {(u.extra_permissions?.length || u.denied_permissions?.length)
            ? <Chip color="violet">متخصصة (+{u.extra_permissions?.length ?? 0} / −{u.denied_permissions?.length ?? 0})</Chip> : null}
          <Btn small icon="shield" onClick={(e) => { e.stopPropagation(); setPerms(u); }}>تخصيص</Btn></span> },
        { key: "t", label: "التأكيد بخطوتين", render: (u) => u.two_factor_enabled
          ? <span className="row" style={{ gap: 6 }}><Chip color="green">شغّال</Chip><Btn small onClick={(e) => { e.stopPropagation(); setReset(u); }}>إلغاؤه (موبايل ضاع)</Btn></span>
          : <span className="faint small">—</span> },
      ]} />
      {reset && <Confirm title="إلغاء التأكيد بخطوتين" yes="إلغاؤه" danger onClose={() => setReset(null)}
        text={`${reset.full_name} هيدخل بكلمة المرور بس لحد ما يفعّله تاني (لو موبايله ضاع أو اتغيّر).`}
        onYes={async () => { try { await api.post(`/users/${reset.id}/2fa/reset`); toast.ok("اتلغى."); list.reload(); } catch (e) { toast.err(errorText(e)); } setReset(null); }} />}
      {list.data && <Pager total={list.data.total} limit={50} offset={offset} onChange={setOffset} />}
      {edit && <UserForm user={edit} onClose={() => setEdit(null)} onSaved={list.reload} />}
      {perms && <UserPermissions user={perms} onClose={() => setPerms(null)} onSaved={list.reload} />}
    </div>
  );
}

function UserForm({ user, onClose, onSaved }: { user: Partial<User>; onClose: () => void; onSaved: () => void }) {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const roles = useLoad(() => lookups.roles(), []);
  const [d, setD] = useState({ username: user.username ?? "", full_name: user.full_name ?? "", phone: user.phone ?? "", email: user.email ?? "",
    password: "", is_active: user.is_active ?? true });
  const [assign, setAssign] = useState<{ role_id: string; branch_id: string | null }[]>(user.assignments?.map((a) => ({ ...a })) ?? []);
  const save = () => run(async () => {
    const body = { full_name: d.full_name, phone: d.phone || null, email: d.email || null, assignments: assign.filter((a) => a.role_id) };
    if (user.id) await api.patch(`/users/${user.id}`, { ...body, version: user.version, is_active: d.is_active, password: d.password || null });
    else await api.post("/users", { ...body, username: d.username, password: d.password });
    toast.ok("اتحفظ المستخدم.");
    onSaved();
    onClose();
  });
  return (
    <Modal title={user.id ? `المستخدم ${user.username}` : "مستخدم جديد"} size="wide" onClose={onClose} footer={<><Btn kind="primary" busy={busy}
      disabled={!d.full_name || (!user.id && (!d.username || d.password.length < 8))} onClick={save}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2">
        <Field label="اسم الدخول"><TextIn value={d.username} onChange={(v) => setD((x) => ({ ...x, username: v }))} code disabled={!!user.id} autoFocus /></Field>
        <Field label="الاسم"><TextIn value={d.full_name} onChange={(v) => setD((x) => ({ ...x, full_name: v }))} /></Field>
        <Field label="التليفون"><TextIn value={d.phone} onChange={(v) => setD((x) => ({ ...x, phone: v }))} code /></Field>
        <Field label="الإيميل"><TextIn value={d.email} onChange={(v) => setD((x) => ({ ...x, email: v }))} code /></Field>
        <Field label={user.id ? "كلمة مرور جديدة (اختياري)" : "كلمة المرور"} hint="8 حروف على الأقل. المستخدم هيغيّرها أول دخول.">
          <TextIn type="password" value={d.password} onChange={(v) => setD((x) => ({ ...x, password: v }))} autoComplete="new-password" /></Field>
        {user.id && <Field label=" "><Check checked={d.is_active} onChange={(v) => setD((x) => ({ ...x, is_active: v }))} label="المستخدم نشط" /></Field>}
      </div>
      <h4 style={{ margin: "16px 0 6px" }}>الأدوار (لكل فرع)</h4>
      <table className="editor-table">
        <thead><tr><th>الدور</th><th>الفرع</th><th /></tr></thead>
        <tbody>{assign.map((a, i) => (
          <tr key={i}>
            <td><Select value={a.role_id} onChange={(v) => setAssign((x) => x.map((y, j) => j === i ? { ...y, role_id: v } : y))} placeholder="اختار…"
              options={(roles.data ?? []).map((r) => ({ value: r.id, label: r.name }))} /></td>
            <td><Select value={a.branch_id ?? ""} onChange={(v) => setAssign((x) => x.map((y, j) => j === i ? { ...y, branch_id: v || null } : y))}
              placeholder="كل الفروع" options={s.branches.map((b) => ({ value: b.id, label: b.name }))} /></td>
            <td><Btn small icon="trash" kind="danger" onClick={() => setAssign((x) => x.filter((_, j) => j !== i))} /></td>
          </tr>))}</tbody>
      </table>
      <Btn small icon="plus" className="mt" onClick={() => setAssign((x) => [...x, { role_id: "", branch_id: null }])}>دور</Btn>
    </Modal>
  );
}

function RoleList() {
  const [edit, setEdit] = useState<Partial<Role> | null>(null);
  const roles = useLoad(() => api.get<Role[]>("/roles"), []);
  const perms = useLoad(() => lookups.permissions(), []);
  return (
    <div className="col">
      <PageHead><Btn kind="primary" icon="plus" onClick={() => setEdit({ permissions: [] })}>دور جديد</Btn></PageHead>
      <Table rows={roles.data} loading={roles.loading} onRow={(r) => setEdit(r)} columns={[
        { key: "n", label: "الدور", render: (r) => <b>{r.name}</b> },
        { key: "c", label: "الكود", render: (r) => <span className="code">{r.code}</span> },
        { key: "p", label: "الصلاحيات", render: (r) => <span className="muted small">{r.permissions.length} صلاحية</span> },
        { key: "b", label: "", render: (r) => r.is_builtin && <Chip>جاهز</Chip> },
      ]} />
      {edit && <RoleForm role={edit} perms={perms.data ?? []} onClose={() => setEdit(null)} onSaved={() => { invalidate("roles"); roles.reload(); }} />}
    </div>
  );
}

const GROUP_NAMES: Record<string, string> = { org: "الشركة", users: "المستخدمين", library: "مكتبة القطاعات", engine: "الحسابات",
  customers: "العملاء", surveys: "المعاينات", quotes: "عروض الأسعار", workorders: "أوامر التصنيع",
  invoices: "الفواتير", notify: "الإشعارات", sales: "المبيعات", hr: "الموارد البشرية", finance: "الربحية ورأس المال", purchasing: "المشتريات", treasury: "الخزينة", privacy: "البيانات الشخصية",
  audit: "سجل التعديلات", system: "السيستم", maintenance: "الصيانة", field: "الفنيين والتتبع", delete: "الحذف",
  collections: "التحصيلات", integrations: "الربط مع برامج تانية" };
// read, then add, edit, delete: the order a factory owner thinks in
const ACTION_ORDER = ["read", "self", "create", "write", "print", "manage", "stage", "approve", "payroll", "calculate", "import", "delete", "permanent"];

function RoleForm({ role, perms, onClose, onSaved }: { role: Partial<Role>; perms: { code: string; name: string }[]; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const [d, setD] = useState({ code: role.code ?? "", name: role.name ?? "", permissions: new Set(role.permissions ?? []) });
  const groups = new Map<string, { code: string; name: string }[]>();
  for (const p of perms.filter((p) => !p.code.startsWith("platform."))) {
    const g = p.code.split(".")[0];
    groups.set(g, [...(groups.get(g) ?? []), p]);
  }
  const toggle = (code: string, on: boolean) => setD((x) => { const n = new Set(x.permissions); on ? n.add(code) : n.delete(code); return { ...x, permissions: n }; });
  return (
    <Modal title={role.id ? `الدور: ${role.name}` : "دور جديد"} size="wide" onClose={onClose} footer={<><Btn kind="primary" busy={busy} disabled={!d.name || !d.code}
      onClick={() => run(async () => {
        if (role.id) await api.patch(`/roles/${role.id}`, { version: role.version, name: d.name, permissions: [...d.permissions] });
        else await api.post("/roles", { code: d.code, name: d.name, permissions: [...d.permissions] });
        onSaved(); onClose();
      })}>حفظ</Btn><Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="grid g2 mb">
        <Field label="الكود"><TextIn value={d.code} onChange={(v) => setD((x) => ({ ...x, code: v }))} code disabled={!!role.id} /></Field>
        <Field label="الاسم"><TextIn value={d.name} onChange={(v) => setD((x) => ({ ...x, name: v }))} /></Field>
      </div>
      <div className="grid g2">
        {[...groups.entries()].map(([g, items]) => (
          <div key={g} className="card" style={{ padding: 10 }}>
            <div className="bold small mb">{GROUP_NAMES[g] ?? g}</div>
            {[...items].sort((x, y) => ACTION_ORDER.indexOf(x.code.split(".")[1]) - ACTION_ORDER.indexOf(y.code.split(".")[1])).map((p) => (
              <div key={p.code} className={p.code.endsWith(".delete") ? "danger-text" : undefined}>
                <Check checked={d.permissions.has(p.code)} onChange={(v) => toggle(p.code, v)} label={p.name} />
              </div>
            ))}
          </div>
        ))}
      </div>
    </Modal>
  );
}


type PermState = { version: number; from_roles: string[]; extra: string[]; denied: string[]; effective: string[];
  catalog: { code: string; label: string }[] };
// the columns of the matrix; anything else in a section is listed under «صلاحيات تانية»
const MATRIX: [string, string][] = [["read", "يشوف"], ["create", "يضيف"], ["write", "يعدّل"], ["print", "يطبع"], ["delete", "يحذف"]];

/** تخصيص صلاحيات المستخدم: what he sees, adds, edits, prints, deletes in each section, on top of his roles. A box
 * ticked by his roles and cleared here is taken away from him only; one added here is his only. */
function UserPermissions({ user, onClose, onSaved }: { user: User; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const st = useLoad(() => api.get<PermState>(`/users/${user.id}/permissions`), [user.id]);
  const [on, setOn] = useState<Set<string> | null>(null);
  if (st.error) return <Modal title="الصلاحيات" onClose={onClose}><ErrorBox text={st.error} onRetry={st.reload} /></Modal>;
  if (!st.data) return <Modal title="الصلاحيات" onClose={onClose}><Loading /></Modal>;
  const data = st.data;
  const roles = new Set(data.from_roles);
  const cur = on ?? new Set(data.effective);
  const set = (code: string, v: boolean) => setOn(() => { const n = new Set(cur); v ? n.add(code) : n.delete(code); return n; });
  const label = new Map(data.catalog.map((p) => [p.code, p.label]));
  const groups = new Map<string, string[]>();
  for (const p of data.catalog) {
    const g = p.code.split(".")[0];
    groups.set(g, [...(groups.get(g) ?? []), p.code]);
  }
  const save = () => run(async () => {
    const extra = [...cur].filter((c) => !roles.has(c));
    const denied = [...roles].filter((c) => !cur.has(c) && label.has(c));
    await api.put(`/users/${user.id}/permissions`, { version: data.version, extra_permissions: extra, denied_permissions: denied });
    toast.ok("اتحفظت صلاحيات المستخدم. بتشتغل من أول طلب جاي ليه.");
    onSaved(); onClose();
  });
  const mark = (code: string) => {
    const mine = cur.has(code), role = roles.has(code);
    return mine && !role ? " (متضافة له)" : !mine && role ? " (متشالة منه)" : "";
  };
  return (
    <Modal title={`صلاحيات ${user.full_name}`} size="wide" onClose={onClose} footer={<>
      <Btn kind="primary" busy={busy} onClick={save}>حفظ</Btn>
      <Btn busy={busy} onClick={() => setOn(new Set(data.from_roles))}>رجوع لصلاحيات الأدوار</Btn>
      <Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="notice info small mb">العلامة جاية من أدواره. شيلها عشان تمنعها عنه هو بس، أو علّم على حاجة مش في أدواره عشان تديهاله هو بس. «يشوف» من غير «يعدّل» يعني يشوف بس.</div>
      <div style={{ overflowX: "auto" }}>
        <table className="table">
          <thead><tr><th>القسم</th>{MATRIX.map(([, l]) => <th key={l} style={{ textAlign: "center" }}>{l}</th>)}<th>صلاحيات تانية</th></tr></thead>
          <tbody>
            {[...groups.entries()].filter(([g]) => g !== "platform").map(([g, codes]) => (
              <tr key={g}>
                <td className="bold">{GROUP_NAMES[g] ?? g}</td>
                {MATRIX.map(([a]) => {
                  const code = `${g}.${a}`;
                  return <td key={a} style={{ textAlign: "center" }}>{label.has(code)
                    ? <span title={(label.get(code) ?? "") + mark(code)} style={{ outline: mark(code) ? "2px solid var(--violet)" : undefined, borderRadius: 4, display: "inline-block" }}>
                        <Check checked={cur.has(code)} onChange={(v) => set(code, v)} label="" /></span>
                    : <span className="faint">—</span>}</td>;
                })}
                <td>{codes.filter((c) => !MATRIX.some(([a]) => c === `${g}.${a}`)).map((c) => (
                  <div key={c} className={"small" + (mark(c) ? " bold" : "")}><Check checked={cur.has(c)} onChange={(v) => set(c, v)} label={(label.get(c) ?? c) + mark(c)} /></div>))}</td>
              </tr>))}
          </tbody>
        </table>
      </div>
    </Modal>
  );
}
