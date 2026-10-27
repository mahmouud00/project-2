import { useRef, useState, type ReactNode } from "react";
import { useSession } from "../state/session";
import { useTheme } from "../state/theme";
import { Icon } from "./icons";
import { Btn, Field, Modal, TextIn } from "./ui";
import { api, errorText, store, CLIENT_VERSION } from "../api/client";
import { go } from "../lib/router";
import { useToast } from "../state/toast";
import { PrintPreview } from "./media";
import { Bell } from "./bell";
import { collectPage, type Report } from "../lib/printpage";
import mytechLogo from "../assets/logo-transparent.png";

export type NavItem = { id: string; icon: string; label: string; perm?: string | string[]; module?: string; platformOnly?: boolean;
  hideForPlatform?: boolean };
export const NAV: [string, NavItem[]][] = [
  ["", [{ id: "dashboard", icon: "home", label: "لوحة التحكم", hideForPlatform: true }]],
  ["المبيعات", [
    { id: "customers", icon: "users", label: "العملاء", perm: "customers.read", hideForPlatform: true },
    { id: "surveys", icon: "ruler", label: "المعاينات", perm: "surveys.read", hideForPlatform: true },
    { id: "quotations", icon: "quote", label: "عروض الأسعار", perm: "quotes.read", hideForPlatform: true },
    { id: "invoices", icon: "invoice", label: "الفواتير", perm: "treasury.read", hideForPlatform: true },
  ]],
  ["الإنتاج", [
    { id: "work-orders", icon: "factory", label: "أوامر التصنيع", perm: "workorders.read", hideForPlatform: true },
    { id: "offcuts", icon: "box", label: "البواقي", perm: "workorders.read", hideForPlatform: true },
    { id: "purchasing", icon: "cart", label: "المشتريات", perm: "purchasing.read", hideForPlatform: true },
    { id: "field", icon: "truck", label: "الفنيين", perm: ["field.read", "field.manage", "field.self"], hideForPlatform: true },
  ]],
  ["الحسابات والإدارة", [
    { id: "treasury", icon: "cash", label: "الحسابات والخزينة", perm: ["treasury.read", "purchasing.approve", "finance.read"], hideForPlatform: true },
    { id: "hr", icon: "idcard", label: "الموارد البشرية", perm: "hr.read", hideForPlatform: true },
  ]],
  ["الإعداد", [
    { id: "library", icon: "layers", label: "مكتبة القطاعات", perm: ["library.read", "platform.library.author"] },
    { id: "price-lists", icon: "tag", label: "قوائم الأسعار", perm: ["pricelists.manage", "pricelists.create", "pricelists.delete"], hideForPlatform: true },
    { id: "users", icon: "shield", label: "المستخدمين والصلاحيات", perm: "users.manage" },
    { id: "settings", icon: "gear", label: "بيانات الشركة", perm: "org.manage", hideForPlatform: true },
    { id: "system", icon: "key", label: "الترخيص والنسخ", perm: ["system.manage", "platform.library.author"] },
  ]],
];

export function navVisible(item: NavItem, s: ReturnType<typeof useSession>): boolean {
  if (s.isPlatform && item.hideForPlatform) return false;
  if (!item.perm) return true;
  const perms = Array.isArray(item.perm) ? item.perm : [item.perm];
  return perms.some((p) => s.can(p));
}

export function Shell({ page, title, crumbs, children, onLogout }:
  { page: string; title: ReactNode; crumbs?: ReactNode; children: ReactNode; onLogout: () => void }) {
  const s = useSession();
  const theme = useTheme();
  const [menu, setMenu] = useState(false);
  const [drawer, setDrawer] = useState(false);   // phones: the side menu slides in
  const [pwd, setPwd] = useState(false);
  const name = s.company.branding?.name || s.company.name;
  const lic = s.license;
  const content = useRef<HTMLDivElement>(null);
  const top = useRef<HTMLDivElement>(null);
  const [report, setReport] = useState<Report | null>(null);
  const toast = useToast();
  const printPage = () => {
    if (!content.current) return;
    const crumbs = top.current?.querySelector(".crumbs")?.textContent?.trim();
    const heading = top.current?.querySelector(".page-title")?.textContent?.trim() || "تقرير";
    const r = collectPage(content.current, heading);
    if (crumbs) r.subtitle = [crumbs, r.subtitle].filter(Boolean).join(" · ");
    if (!r.sections.length) { toast.info("مفيش جداول أو بيانات في الصفحة دي للطباعة."); return; }
    setReport(r);
  };

  return (
    <div className={"app" + (drawer ? " nav-open" : "")}>
      {drawer && <div className="nav-backdrop" onClick={() => setDrawer(false)} />}
      <aside className="sidebar">
        <div className="co-brand" title={name}>
          <div className={"co-logo" + (s.logoUrl ? "" : " empty")}>{s.logoUrl ? <img src={s.logoUrl} alt="" /> : name.slice(0, 1)}</div>
          <div className="grow">
            <div className="co-name">{name}</div>
            <div className="co-sub">{s.isPlatform ? "حساب MYTech" : s.company.code}</div>
          </div>
        </div>
        <nav className="nav">
          {NAV.map(([group, items]) => {
            const visible = items.filter((i) => navVisible(i, s));
            if (!visible.length) return null;
            return (
              <div key={group || "main"}>
                {group && <div className="nav-group">{group}</div>}
                {visible.map((i) => (
                  <a key={i.id} className={page === i.id ? "active" : ""} onClick={() => { setDrawer(false); go(i.id); }}>
                    <Icon name={i.icon} /><span>{i.label}</span>
                  </a>
                ))}
              </div>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          <div className="conn"><span className="dot" />متصل بالسيرفر</div>
          <div style={{ color: "#7F92AA", marginTop: 4 }} className="row">
            <span className="num">{store.server?.replace(/^https?:\/\//, "")}</span>
            <span className="end num">v{CLIENT_VERSION}</span>
          </div>
          <img className="mytech" src={mytechLogo} alt="MYTech Solutions" />
        </div>
      </aside>
      <div className="main">
        {!lic.can_write && lic.can_read && <div className="banner warn">الترخيص منتهي أو غير صالح: البرنامج شغال قراءة بس. كلّم MYTech لتجديد الترخيص.</div>}
        {lic.status === "grace" && <div className="banner warn">الترخيص في فترة السماح. جدّد الترخيص قبل ما البرنامج يتحول لقراءة بس.</div>}
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setDrawer(true)} aria-label="القايمة"><Icon name="menu" /></button>
          <div className="grow" ref={top}>
            {crumbs && <div className="crumbs">{crumbs}</div>}
            <div className="page-title">{title}</div>
          </div>
          {s.branches.length > 1 && (
            <select className="input hide-phone" style={{ width: "auto", minWidth: 150 }} value={s.branchId ?? ""}
              onChange={(e) => s.setBranchId(e.target.value || null)} title="الفرع">
              <option value="">كل الفروع</option>
              {s.branches.filter((b) => b.is_active).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          )}
          <Bell />
          <button className="icon-btn hide-phone" onClick={printPage} title="طباعة الصفحة / حفظ PDF"><Icon name="print" /></button>
          <button className="icon-btn" onClick={theme.toggle} title={theme.isDark ? "الوضع الفاتح" : "الوضع الغامق"}>
            <Icon name={theme.isDark ? "sun" : "moon"} />
          </button>
          <div style={{ position: "relative" }}>
            <button className="user btn ghost" style={{ color: "var(--text)" }} onClick={() => setMenu((m) => !m)}>
              <div className="avatar">{s.me.full_name.slice(0, 1)}</div>
              <div className="hide-phone" style={{ textAlign: "start" }}><b>{s.me.full_name}</b><small>{s.me.username}</small></div>
            </button>
            {menu && (
              <div className="card" style={{ position: "absolute", left: 0, top: 44, minWidth: 210, zIndex: 30, padding: 6 }}
                onMouseLeave={() => setMenu(false)}>
                <ThemeChoice />
                <button className="btn ghost" style={{ width: "100%", justifyContent: "flex-start", color: "var(--text)" }}
                  onClick={() => { setMenu(false); setPwd(true); }}><Icon name="key" />تغيير كلمة المرور</button>
                <button className="btn ghost" style={{ width: "100%", justifyContent: "flex-start", color: "var(--danger)" }}
                  onClick={onLogout}><Icon name="logout" />تسجيل الخروج</button>
              </div>
            )}
          </div>
        </header>
        <div className="content" ref={content}>{children}</div>
      </div>
      {pwd && <ChangePassword onClose={() => setPwd(false)} />}
      {report && <PrintPreview path="/documents/report" body={report} title={report.title} onClose={() => setReport(null)} />}
    </div>
  );
}

function ThemeChoice() {
  const t = useTheme();
  const opts: [typeof t.choice, string][] = [["light", "فاتح"], ["dark", "غامق"], ["system", "زي الويندوز"]];
  return (
    <div style={{ padding: "4px 8px 8px", borderBottom: "1px solid var(--line)", marginBottom: 4 }}>
      <div className="muted small mb" style={{ marginBottom: 4 }}>شكل البرنامج</div>
      <div className="row" style={{ gap: 4 }}>
        {opts.map(([v, l]) => (
          <button key={v} className={"btn sm" + (t.choice === v ? " primary" : "")} onClick={() => t.setChoice(v)}>{l}</button>
        ))}
      </div>
    </div>
  );
}

export function ChangePassword({ onClose, forced }: { onClose: () => void; forced?: boolean }) {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  const save = async () => {
    if (next !== again) { setError("كلمتين المرور الجديدة مش زي بعض."); return; }
    setBusy(true);
    try {
      await api.post("/auth/change-password", { current_password: cur, new_password: next });
      toast.ok("اتغيرت كلمة المرور.");
      onClose();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={forced ? "لازم تغيّر كلمة المرور" : "تغيير كلمة المرور"} onClose={forced ? () => undefined : onClose}
      footer={<><Btn kind="primary" busy={busy} onClick={save} disabled={!cur || next.length < 8}>حفظ</Btn>{!forced && <Btn onClick={onClose}>رجوع</Btn>}</>}>
      <div className="col">
        <Field label="كلمة المرور الحالية"><TextIn type="password" value={cur} onChange={setCur} autoFocus /></Field>
        <Field label="كلمة المرور الجديدة" hint="8 حروف على الأقل"><TextIn type="password" value={next} onChange={setNext} /></Field>
        <Field label="تأكيد كلمة المرور الجديدة"><TextIn type="password" value={again} onChange={setAgain} /></Field>
        {error && <div className="notice err">{error}</div>}
      </div>
    </Modal>
  );
}
