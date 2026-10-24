import { useState } from "react";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useAction, useLoad } from "../lib/hooks";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Card, Check, Chip, Field, Modal, PageHead, Pager, Select, Table, Tabs, TextIn } from "../components/ui";
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
      ]} />
      {list.data && <Pager total={list.data.total} limit={50} offset={offset} onChange={setOffset} />}
      {edit && <UserForm user={edit} onClose={() => setEdit(null)} onSaved={list.reload} />}
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
            {items.map((p) => <div key={p.code}><Check checked={d.permissions.has(p.code)} onChange={(v) => toggle(p.code, v)} label={p.name} /></div>)}
          </div>
        ))}
      </div>
    </Modal>
  );
}
