// «ابدأ هنا»: a new factory's first steps on the dashboard, each ticked from its own data (nothing to tick by hand):
// company data and logo -> systems -> material prices -> users -> the first quotation. Closed with «إخفاء» or once done.
import { api } from "../api/client";
import { useLoad } from "../lib/hooks";
import { go } from "../lib/router";
import { useSession } from "../state/session";
import { Icon } from "./icons";

type Step = { id: string; done: boolean; count?: number };
type Setup = { steps: Step[]; done: number; total: number; dismissed: boolean };

const STEPS: Record<string, { title: string; text: string; to: string; query?: Record<string, string> }> = {
  company: { title: "بيانات الشركة واللوجو", text: "الاسم والتليفون والعنوان واللوجو اللي بيطلعوا على كل عرض وفاتورة.", to: "settings" },
  systems: { title: "القطاعات", text: "اختار القطاعات اللي بتشتغل بيها من مكتبة MYTech، أو ضيفها من إكسيل.", to: "library" },
  prices: { title: "أسعار الخامات والخصومات", text: "من القطاع ← الخامات: سعر الشركة لكل خامة وخصم المورد، عشان دليل السعر يطلع صح.", to: "library" },
  users: { title: "المستخدمين", text: "ضيف البياعين والفنيين والحسابات، كل واحد بصلاحياته وفرعه.", to: "users" },
  quotation: { title: "أول عرض سعر", text: "اعمل عرض لعميل: الوحدات بمقاساتها، والبرنامج يحسب القطع والسعر.", to: "quotations" },
};

export function SetupCard() {
  const s = useSession();
  const st = useLoad(() => (s.can("org.manage") ? api.get<Setup>("/company/setup") : Promise.resolve(null)), []);
  const d = st.data;
  if (!d || d.dismissed || d.done === d.total) return null;
  const next = d.steps.find((x) => !x.done)?.id;
  const hide = async () => { await api.post("/company/setup/dismiss", { dismissed: true }).catch(() => undefined); st.reload(); };
  return (
    <div className="card setup-card">
      <div className="row" style={{ gap: 10 }}>
        <div className="grow">
          <b style={{ fontSize: 15 }}>ابدأ الشغل على البرنامج</b>
          <div className="muted small">خطوات قليلة والمصنع يبقى جاهز. كل خطوة بتتعلّم لوحدها لما تخلص.</div>
        </div>
        <span className="num small muted">{d.done} / {d.total}</span>
        <button className="btn ghost sm" onClick={hide} title="إخفاء الخطوات دي">إخفاء</button>
      </div>
      <div className="setup-bar"><span style={{ width: `${(d.done / d.total) * 100}%` }} /></div>
      <ol className="setup-steps">
        {d.steps.map((x, i) => {
          const m = STEPS[x.id];
          if (!m) return null;
          return (
            <li key={x.id} className={(x.done ? "done" : "") + (x.id === next ? " next" : "")}>
              <span className="mark">{x.done ? <Icon name="check" /> : i + 1}</span>
              <div className="grow"><b>{m.title}</b><div className="small muted">{m.text}</div></div>
              {!x.done && <button className={"btn sm " + (x.id === next ? "primary" : "ghost")} onClick={() => go(m.to, m.query)}>
                {x.id === next ? "يلا" : "افتح"}</button>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
