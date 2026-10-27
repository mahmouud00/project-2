import { useCallback, useEffect, useState } from "react";
import { TitleCtx, type Title } from "./lib/title";
import { api, logout, onApiEvent, resume, store, CLIENT_VERSION } from "./api/client";
import { ConnectPage, LoginPage } from "./pages/Auth";
import { SessionProvider, loadSession, useSession, type ServerInfo, type SessionData } from "./state/session";
import { ChangePassword, NAV, Shell, navVisible } from "./components/Shell";
import { go, useRoute } from "./lib/router";
import { Btn } from "./components/ui";
import { PAGES } from "./pages";

type Phase = { kind: "boot" } | { kind: "connect" } | { kind: "login"; info: ServerInfo } | { kind: "app"; data: SessionData }
  | { kind: "update"; server?: string; min?: string };

export default function App() {
  const [phase, setPhase] = useState<Phase>({ kind: "boot" });

  const start = useCallback(async () => {
    if (!store.server) { setPhase({ kind: "connect" }); return; }
    let info: ServerInfo;
    try {
      info = await api.public<ServerInfo>("/system/info");
    } catch {
      setPhase({ kind: "connect" });
      return;
    }
    if (await resume()) {
      try { setPhase({ kind: "app", data: await loadSession() }); return; } catch { /* fall back to login */ }
    }
    setPhase({ kind: "login", info });
  }, []);

  useEffect(() => { start(); }, [start]);
  useEffect(() => onApiEvent((e, d: any) => {
    if (e === "logout") start();
    if (e === "update-required") setPhase({ kind: "update", server: d?.error?.details?.server, min: d?.error?.details?.min_client_version });
  }), [start]);

  switch (phase.kind) {
    case "boot": return <div className="loading-page"><span className="spinner" /></div>;
    case "connect": return <ConnectPage onDone={(info) => setPhase({ kind: "login", info })} />;
    case "login": return <LoginPage info={phase.info} onChangeServer={() => setPhase({ kind: "connect" })}
      onLogin={async () => setPhase({ kind: "app", data: await loadSession() })} />;
    case "update": return <UpdateRequired server={phase.server} min={phase.min} />;
    case "app": return (
      <SessionProvider initial={phase.data} key={phase.data.me.id}>
        <Main onLogout={async () => { await logout(); start(); }} />
      </SessionProvider>
    );
  }
}

function UpdateRequired({ server, min }: { server?: string; min?: string }) {
  return (
    <div className="loading-page">
      <div className="card" style={{ maxWidth: 460 }}>
        <div className="card-b col">
          <h2 style={{ margin: 0 }}>لازم تحدّث البرنامج</h2>
          <p className="muted" style={{ margin: 0 }}>
            السيرفر اتحدّث (<span className="num">v{server ?? "?"}</span>) والنسخة دي (<span className="num">v{CLIENT_VERSION}</span>)
            أقدم من المسموح (<span className="num">v{min ?? "?"}</span>). نزّل آخر نسخة من البرنامج وسطّبها، وبياناتك كلها على السيرفر.
          </p>
          <Btn onClick={() => location.reload()} icon="refresh">إعادة المحاولة</Btn>
        </div>
      </div>
    </div>
  );
}

function Main({ onLogout }: { onLogout: () => void }) {
  const s = useSession();
  const route = useRoute();
  const [title, setTitle] = useState<Title>({ title: "" });
  const [pwd, setPwd] = useState(s.me.must_change_password);
  const first = defaultPage(s);
  const page = route.path[0] ?? first;

  useEffect(() => { if (!route.path.length) go(first); }, [route.path.length, first]);

  const Page = PAGES[page];
  const allowed = NAV.flatMap(([, items]) => items).find((i) => i.id === page);
  const ok = Page && (!allowed || navVisible(allowed, s));
  return (
    <TitleCtx.Provider value={setTitle}>
      <Shell page={page} title={title.title} crumbs={title.crumbs} onLogout={onLogout}>
        {ok ? <Page route={route} key={page} /> : <div className="empty">الصفحة دي مش متاحة.</div>}
      </Shell>
      {pwd && <ChangePassword forced onClose={() => setPwd(false)} />}
    </TitleCtx.Provider>
  );
}

function defaultPage(s: ReturnType<typeof useSession>): string {
  if (s.isPlatform) return "library";
  if (s.can("field.self") && !s.can("customers.read")) return "field";   // technicians open on their jobs
  return "dashboard";
}

