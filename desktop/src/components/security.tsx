// الأمان: two-step login with an authenticator app (Google / Microsoft Authenticator…), and the devices this user is
// signed in on, each with «طلّعه». Opens by itself when the company asks it of administrators.
import { useState } from "react";
import { api, errorText } from "../api/client";
import { useLoad } from "../lib/hooks";
import { dateTime } from "../lib/format";
import { useToast } from "../state/toast";
import { Btn, Chip, Field, Modal, Table, TextIn } from "./ui";

type Setup = { secret: string; uri: string; qr_svg: string };
type Sess = { id: string; device: string; platform: string; last_seen_at: string; signed_in_at: string; current: boolean };

export function Security({ onClose, forced }: { onClose: () => void; forced?: boolean }) {
  const toast = useToast();
  const me = useLoad(() => api.get<{ two_factor_enabled: boolean; two_factor_required: boolean }>("/auth/me"), []);
  const sessions = useLoad(() => api.get<Sess[]>("/auth/sessions"), []);
  const [setup, setSetup] = useState<Setup | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [off, setOff] = useState(false);
  const [busy, setBusy] = useState(false);
  const enabled = me.data?.two_factor_enabled;
  const run = async (f: () => Promise<void>) => { setBusy(true); try { await f(); } catch (e) { toast.err(errorText(e)); } finally { setBusy(false); } };
  const digits = (v: string) => v.replace(/\D/g, "").slice(0, 6);

  return (
    <Modal title="الأمان" size="wide" onClose={forced && !enabled ? () => undefined : onClose}
      footer={!(forced && !enabled) && <Btn onClick={onClose}>تمام</Btn>}>
      <div className="col">
        {forced && !enabled && <div className="notice warn">الشركة طالبة من المديرين يفعّلوا التأكيد بخطوتين قبل ما يكمّلوا.</div>}
        <h4 style={{ margin: 0 }}>التأكيد بخطوتين {enabled ? <Chip color="green">شغّال</Chip> : <Chip>مقفول</Chip>}</h4>
        <div className="muted small">بعد كلمة المرور، البرنامج بيطلب كود من ٦ أرقام بيتغيّر كل ٣٠ ثانية في تطبيق على موبايلك
          (Google Authenticator أو Microsoft Authenticator). لو حد عرف كلمة المرور، مش هيقدر يدخل من غير موبايلك.</div>

        {!enabled && !setup && <div><Btn kind="primary" icon="shield" busy={busy} onClick={() => run(async () => {
          setSetup(await api.post<Setup>("/auth/2fa/setup")); setCode("");
        })}>تفعيل التأكيد بخطوتين</Btn></div>}

        {!enabled && setup && (
          <div className="row top wrap" style={{ gap: 18 }}>
            <div className="qr-box" dangerouslySetInnerHTML={{ __html: setup.qr_svg }} />
            <div className="col grow" style={{ minWidth: 240 }}>
              <div>١. نزّل تطبيق <b>Google Authenticator</b> على موبايلك.</div>
              <div>٢. افتحه ودوس <b>+</b> وصوّر الكود ده. (أو اكتب المفتاح: <span className="code small" style={{ userSelect: "all" }}>{setup.secret}</span>)</div>
              <div>٣. اكتب الـ٦ أرقام اللي ظهرت في التطبيق:</div>
              <div className="row" style={{ gap: 8 }}>
                <TextIn value={code} onChange={(v) => setCode(digits(v))} inputMode="numeric" autoComplete="one-time-code" autoFocus code
                  style={{ letterSpacing: 4, textAlign: "center", width: 140 }} />
                <Btn kind="primary" busy={busy} disabled={code.length !== 6} onClick={() => run(async () => {
                  await api.post("/auth/2fa/enable", { code });
                  setSetup(null); me.reload(); toast.ok("اتفعّل التأكيد بخطوتين. من دلوقتي الدخول بيطلب الكود.");
                })}>تأكيد</Btn>
              </div>
            </div>
          </div>
        )}

        {enabled && !off && <div><Btn icon="ban" onClick={() => { setOff(true); setCode(""); setPassword(""); }}>إلغاء التأكيد بخطوتين</Btn></div>}
        {enabled && off && (
          <div className="grid g3" style={{ alignItems: "end" }}>
            <Field label="كلمة المرور"><TextIn type="password" value={password} onChange={setPassword} autoComplete="current-password" /></Field>
            <Field label="الكود من التطبيق"><TextIn value={code} onChange={(v) => setCode(digits(v))} inputMode="numeric" code /></Field>
            <div className="row" style={{ gap: 6 }}>
              <Btn kind="danger" busy={busy} disabled={!password || code.length !== 6} onClick={() => run(async () => {
                await api.post("/auth/2fa/disable", { password, code });
                setOff(false); me.reload(); toast.ok("اتلغى التأكيد بخطوتين.");
              })}>إلغاء</Btn>
              <Btn onClick={() => setOff(false)}>رجوع</Btn>
            </div>
          </div>
        )}

        <h4 style={{ margin: "12px 0 0" }}>الأجهزة اللي داخل منها</h4>
        <div className="muted small">لو فيه جهاز مش بتاعك أو مش بتستخدمه، دوس «طلّعه».</div>
        <Table rows={sessions.data} loading={sessions.loading} tools={false} rowKey={(x) => x.id} empty="مفيش أجهزة" columns={[
          { key: "d", label: "الجهاز", render: (x) => <><b>{x.device}</b> {x.current && <Chip color="blue">الجهاز ده</Chip>}</> },
          { key: "p", label: "النوع", render: (x) => <span className="muted">{x.platform || "—"}</span> },
          { key: "l", label: "آخر استخدام", render: (x) => <span className="num">{dateTime(x.last_seen_at)}</span> },
          { key: "x", label: "", width: 90, render: (x) => !x.current && <Btn small kind="danger" busy={busy} onClick={() => run(async () => {
            await api.post(`/auth/sessions/${x.id}/revoke`); sessions.reload(); toast.ok(`اتطلّع ${x.device}.`);
          })}>طلّعه</Btn> },
        ]} />
      </div>
    </Modal>
  );
}
