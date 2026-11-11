// «فيه نسخة جديدة»: the server carries the newest desktop and phone programs (every server build ships them), so
// when the server is updated every PC and phone is offered the new version on its next start. No internet needed.
import { useEffect, useState } from "react";
import { api, CLIENT_VERSION, store } from "../api/client";
import { inDesktop } from "../lib/discovery";
import { openMap } from "./field";
import { useToast } from "../state/toast";

type Client = { version: string; size: number; file: string; url: string } | null;

/** "0.1.12" > "0.1.9" */
export function newer(a: string, b: string): boolean {
  const p = (v: string) => v.split(/[.-]/).slice(0, 3).map((x) => parseInt(x, 10) || 0);
  const [x, y] = [p(a), p(b)];
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i];
  return false;
}

const SKIP = "update.skip";

export function UpdateBanner() {
  const [offer, setOffer] = useState<Client>(null);
  const toast = useToast();
  const phone = /Android/i.test(navigator.userAgent);
  useEffect(() => {
    if (!inDesktop() && !phone) return;           // the browser version is always the server's own
    let live = true;
    api.get<{ desktop: Client; android: Client }>("/system/clients").then((c) => {
      const mine = phone ? c.android : c.desktop;
      let skipped: string | null = null;
      try { skipped = sessionStorage.getItem(SKIP); } catch { /* blocked */ }
      if (live && mine && newer(mine.version, CLIENT_VERSION) && skipped !== mine.version) setOffer(mine);
    }).catch(() => { /* an older server: nothing to offer */ });
    return () => { live = false; };
  }, [phone]);
  if (!offer) return null;
  const later = () => { try { sessionStorage.setItem(SKIP, offer.version); } catch { /* blocked */ } setOffer(null); };
  return (
    <div className="banner info row" style={{ gap: 10 }}>
      <span className="grow">فيه نسخة جديدة من البرنامج <b className="num">{offer.version}</b> (عندك <span className="num">{CLIENT_VERSION}</span>).
        {phone ? " نزّلها وافتحها عشان تتسطب فوق القديمة." : " نزّلها وشغّلها، وهتتسطب فوق القديمة والبيانات زي ما هي."}</span>
      {/* the installer downloads in the browser (Edge on the PC) from the server */}
      <button className="btn primary sm" onClick={() => openMap(store.server + offer.url).catch(() => toast.err("ماقدرتش أفتح التحميل."))}>
        تحديث ({Math.max(1, Math.round(offer.size / 1048576))} ميجا)</button>
      <button className="btn ghost sm" onClick={later}>بعدين</button>
    </div>
  );
}
