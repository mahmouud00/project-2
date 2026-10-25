import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, errorText, login, normalizeServer, store, CLIENT_VERSION } from "../api/client";
import { discover, inDesktop, serverUrl, type FoundServer } from "../lib/discovery";
import { Btn, Field, FilePick, TextIn } from "../components/ui";
import { Icon } from "../components/icons";
import mytechLogo from "../assets/logo-transparent.png";
import type { ServerInfo } from "../state/session";
import { useTheme } from "../state/theme";

function Art() {
  return (
    <div className="auth-art">
      <img className="mt-logo" src={mytechLogo} alt="MYTech Solutions" />
      <div>
        <h1>نظام إدارة مصانع الشبابيك والأبواب</h1>
        <p style={{ maxWidth: 420 }}>UPVC · شاتر · ألومنيوم — من المعاينة وعرض السعر لحد التقطيع والتسليم والفاتورة.</p>
      </div>
      <div className="small" style={{ color: "#7F92AA" }}>MYTech Solutions · <span className="num">v{CLIENT_VERSION}</span></div>
    </div>
  );
}

function ThemeCorner() {
  const t = useTheme();
  return (
    <button className="icon-btn" style={{ position: "fixed", top: 14, left: 14 }} onClick={t.toggle}
      title={t.isDark ? "الوضع الفاتح" : "الوضع الغامق"}>
      <Icon name={t.isDark ? "sun" : "moon"} />
    </button>
  );
}

export function ConnectPage({ onDone }: { onDone: (info: ServerInfo) => void }) {
  const [found, setFound] = useState<FoundServer[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [manual, setManual] = useState(store.server?.replace(/^https?:\/\//, "") ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const scan = async () => {
    setSearching(true);
    try { setFound(await discover()); } catch { setFound([]); } finally { setSearching(false); }
  };
  useEffect(() => { if (inDesktop()) scan(); }, []);

  const connect = async (url: string) => {
    setBusy(true);
    setError(null);
    try {
      const info = await api.public<ServerInfo>("/system/info", undefined, url);
      if (info.product !== "MYTech Solutions") throw new Error("ده مش سيرفر MYTech");
      store.server = url;
      onDone(info);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <ThemeCorner />
      <Art />
      <div className="auth-form">
        <div className="auth-card">
          <h2>الاتصال بالسيرفر</h2>
          <p className="muted">اختار سيرفر المصنع من الشبكة، أو اكتب عنوانه.</p>
          {inDesktop() && (
            <div className="card mb">
              <div className="card-h"><h3>السيرفرات على الشبكة</h3>
                <div className="end"><Btn small icon="refresh" busy={searching} onClick={scan}>بحث</Btn></div></div>
              <div className="card-b flush">
                {found?.length ? found.map((s) => (
                  <button key={s.address + s.port} className="btn" style={{ width: "100%", justifyContent: "flex-start", border: 0,
                    borderRadius: 0, borderBottom: "1px solid var(--line)", minHeight: 48 }} onClick={() => connect(serverUrl(s))}>
                    <Icon name="monitor" />
                    <span className="grow" style={{ textAlign: "start" }}>{s.host}<br /><span className="muted small num">{s.address}:{s.port} · v{s.version}</span></span>
                    <Icon name="arrow" />
                  </button>
                )) : <div className="empty">{searching ? <span className="spinner" /> : "مالقيناش سيرفر. اتأكد إن السيرفر شغال، أو اكتب العنوان تحت."}</div>}
              </div>
            </div>
          )}
          <form onSubmit={(e) => { e.preventDefault(); if (manual.trim()) connect(normalizeServer(manual)); }} className="col">
            <Field label="عنوان السيرفر" hint="مثال: 192.168.1.10 أو 192.168.1.10:8000 أو https://cloud.example.com">
              <TextIn value={manual} onChange={setManual} code placeholder="192.168.1.10" autoFocus={!inDesktop()} />
            </Field>
            {error && <div className="notice err">{error}</div>}
            <Btn kind="primary" type="submit" busy={busy} disabled={!manual.trim()}>اتصال</Btn>
          </form>
        </div>
      </div>
    </div>
  );
}

type Activation = { status: string; reason?: string | null; machine_fingerprint: string };

const LICENSE_REASON: Record<string, string> = {
  no_license_file: "مفيش ترخيص متركّب على السيرفر لسه.",
  machine_mismatch: "ملف الترخيص معمول لجهاز تاني: البصمة اللي فيه مش بصمة جهاز السيرفر ده.",
  bad_signature: "ملف الترخيص متعدّل أو مش موقّع من MYTech.",
  unreadable: "ملف الترخيص بايظ أو مش مقروء.",
  expired: "الترخيص منتهي.",
};

function reasonText(e: unknown): string {
  const reason = e instanceof ApiError ? (e.details as { reason?: string } | undefined)?.reason : undefined;
  return (reason && LICENSE_REASON[reason]) || errorText(e);
}

/** Offline server without a usable licence: nobody can log in yet, so the licence is installed from here. */
function ActivationCard({ state, onDone }: { state: Activation; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(state.machine_fingerprint); setCopied(true); } catch { /* clipboard blocked */ }
  };
  const install = async (f: File) => {
    setBusy(true);
    setMsg(null);
    try {
      await api.publicUpload("/system/activation", f);
      setMsg({ kind: "ok", text: "اتركب الترخيص. تقدر تدخل دلوقتي." });
      onDone();
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof ApiError && e.code === "LICENSE_REJECTED" ? "الملف اترفض: " + reasonText(e) : errorText(e) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="card" style={{ padding: 14 }}>
      <b>تفعيل البرنامج</b>
      <div className="notice warn" style={{ margin: "8px 0" }}>{LICENSE_REASON[state.reason ?? ""] ?? "الترخيص غير صالح."}</div>
      <p className="muted small">ابعت بصمة جهاز السيرفر لـ MYTech، وركّب ملف الترخيص (license.json) اللي هيوصلك.</p>
      <div className="row" style={{ marginBottom: 8 }}>
        <span className="code grow num" style={{ wordBreak: "break-all", padding: 8 }}>{state.machine_fingerprint}</span>
        <Btn small icon="copy" onClick={copy}>{copied ? "اتنسخت" : "نسخ"}</Btn>
      </div>
      <FilePick accept=".json" busy={busy} onFile={install}>تركيب ملف الترخيص</FilePick>
      {msg && <div className={"notice " + msg.kind} style={{ marginTop: 8 }}>{msg.text}</div>}
    </div>
  );
}

type PublicBranding = { company_code: string; name: string; has_logo: boolean; accent_color?: string };

export function LoginPage({ info, onLogin, onChangeServer }:
  { info: ServerInfo; onLogin: () => Promise<void>; onChangeServer: () => void }) {
  const online = info.mode === "online";
  const [company, setCompany] = useState(store.company);
  const [username, setUsername] = useState(store.username);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [brand, setBrand] = useState<PublicBranding | null>(null);
  const [logo, setLogo] = useState<string | null>(null);
  const [activation, setActivation] = useState<Activation | null>(null);

  const checkActivation = async () => {
    if (online) return;
    try {
      const a = await api.public<Activation>("/system/activation");
      setActivation(a.status === "valid" || a.status === "grace" ? null : a);
    } catch { /* older server: no public activation */ }
  };
  useEffect(() => { checkActivation(); }, [online]);

  useEffect(() => {
    let live = true;
    const code = company.trim();
    if (online && code.length < 2) { setBrand(null); setLogo(null); return; }
    const t = setTimeout(async () => {
      try {
        const b = await api.public<PublicBranding>("/system/branding", online ? { company_code: code } : undefined);
        if (!live) return;
        setBrand(b);
        if (b.has_logo) {
          const blob = await api.public<Blob>("/system/branding/logo", online ? { company_code: code } : undefined);
          if (live) setLogo(URL.createObjectURL(blob));
        } else setLogo(null);
      } catch {
        if (live) { setBrand(null); setLogo(null); }
      }
    }, online ? 400 : 0);
    return () => { live = false; clearTimeout(t); };
  }, [company, online]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(online ? company.trim() : (brand?.company_code ?? ""), username.trim(), password);
      await onLogin();
    } catch (err) {
      if (err instanceof ApiError && err.code === "LICENSE_INVALID") {
        const why = reasonText(err);
        setError(why === errorText(err) ? why : errorText(err) + " " + why);
        await checkActivation();
      } else setError(errorText(err));
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <ThemeCorner />
      <Art />
      <div className="auth-form">
        <form className="auth-card col" onSubmit={submit}>
          <div className="co">
            <div className={"co-logo" + (logo ? "" : " empty")}>{logo ? <img src={logo} alt="" /> : (brand?.name ?? "M").slice(0, 1)}</div>
            <div>
              <h2>{brand?.name ?? "تسجيل الدخول"}</h2>
              <div className="muted small">{brand ? "تسجيل الدخول" : online ? "اكتب كود الشركة" : ""}</div>
            </div>
          </div>
          {activation && <ActivationCard state={activation} onDone={() => { setActivation(null); setError(null); }} />}
          {online && (
            <Field label="كود الشركة"><TextIn value={company} onChange={setCompany} code autoFocus={!company} /></Field>
          )}
          <Field label="اسم المستخدم"><TextIn value={username} onChange={setUsername} autoFocus={!online || !!company} autoComplete="username" /></Field>
          <Field label="كلمة المرور"><TextIn type="password" value={password} onChange={setPassword} autoComplete="current-password" /></Field>
          {error && <div className="notice err">{error}</div>}
          <Btn kind="primary" type="submit" busy={busy} disabled={!username || !password}>دخول</Btn>
          <div className="row small muted">
            <span className="dot" /> <span className="num">{store.server?.replace(/^https?:\/\//, "")}</span>
            <button type="button" className="btn ghost sm end" onClick={onChangeServer}>تغيير السيرفر</button>
          </div>
        </form>
      </div>
    </div>
  );
}
