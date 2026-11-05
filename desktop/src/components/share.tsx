// Send a quotation / invoice to the customer: on WhatsApp (a message with a link they open without an account) or by
// copying the link. For a quotation the customer can approve it or ask for a change from the link; what they did shows
// here. WhatsApp does not let another program attach a file, so the link is what replaces the PDF.
import { useState } from "react";
import { api, errorText } from "../api/client";
import { useLoad } from "../lib/hooks";
import { lookups } from "../lib/lookups";
import { dateTime } from "../lib/format";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { openMap } from "./field";
import { Btn, Chip, Confirm } from "./ui";

type Share = { id: string | null; url: string | null; expires_at: string | null; reachable_outside: boolean; active: boolean;
  viewed_at: string | null; views: number; response: string | null; response_note: string; responded_at: string | null;
  customer_phone: string | null };

/** 010xxxxxxxx (Egypt) -> 2010xxxxxxxx; +, 00 and spaces removed. null when it cannot be a phone number. */
export function waNumber(phone: string | null | undefined): string | null {
  let d = (phone ?? "").replace(/[^\d+]/g, "");
  if (d.startsWith("+")) d = d.slice(1);
  else if (d.startsWith("00")) d = d.slice(2);
  else if (/^01\d{9}$/.test(d)) d = "2" + d;
  return /^\d{10,15}$/.test(d) ? d : null;
}

export function ShareActions({ kind, id, number, total, customerId, onChanged }:
  { kind: "quotations" | "invoices"; id: string; number: string; total: string | number; customerId: string; onChanged?: () => void }) {
  const s = useSession();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [cancel, setCancel] = useState(false);
  const share = useLoad(() => api.get<Share>(`/${kind}/${id}/share`), [kind, id]);
  const customer = useLoad(() => lookups.customer(customerId), [customerId]);
  const company = s.company.branding?.name || s.company.name;
  const isQuote = kind === "quotations";

  const make = async (): Promise<Share> => {
    const out = await api.post<Share>(`/${kind}/${id}/share`, { days: 14 });
    share.reload();
    onChanged?.();
    if (!out.reachable_outside) toast.info("اللينك ده بيفتح من جوه شبكة المصنع بس. عشان يفتح عند العميل برّه، لازم السيرفر الأونلاين أو عنوان عام (PUBLIC_URL).");
    return out;
  };
  const message = (url: string) => [
    `أهلاً${customer.data?.name ? " " + customer.data.name : ""}،`,
    `ده ${isQuote ? "عرض السعر" : "الفاتورة"} رقم ${number} من ${company} بإجمالي ${Number(total).toLocaleString("en", { maximumFractionDigits: 2 })} جنيه.`,
    isQuote ? "تقدر تشوفه وتوافق عليه أو تطلب تعديل من هنا:" : "تقدر تشوفها وتحفظها PDF من هنا:",
    url,
  ].join("\n");

  const whatsapp = async () => {
    setBusy(true);
    try {
      const out = await make();
      const phone = waNumber(out.customer_phone);
      const text = encodeURIComponent(message(out.url!));
      await openMap(phone ? `https://wa.me/${phone}?text=${text}` : `https://wa.me/?text=${text}`);
      if (!phone) toast.info("مفيش رقم موبايل صحيح للعميل: اختار المحادثة من واتساب.");
    } catch (e) {
      toast.err(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const copy = async () => {
    setBusy(true);
    try {
      const out = await make();
      await navigator.clipboard.writeText(message(out.url!));
      toast.ok("اتنسخت الرسالة باللينك: الزقها في أي محادثة.");
    } catch (e) {
      toast.err(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const st = share.data;
  return (
    <>
      <Btn icon="send" busy={busy} onClick={whatsapp} title="ابعت للعميل على واتساب لينك يفتحه من غير حساب">واتساب</Btn>
      <Btn icon="copy" busy={busy} onClick={copy} title="انسخ الرسالة باللينك">نسخ اللينك</Btn>
      {st?.id && (
        <span className="row" style={{ gap: 6 }}>
          {st.response === "accepted" && <Chip color="green">العميل وافق من اللينك</Chip>}
          {st.response === "change_requested" && <Chip color="amber" title={st.response_note}>العميل طلب تعديل</Chip>}
          {!st.response && st.views > 0 && <Chip color="blue" title={dateTime(st.viewed_at)}>العميل فتح اللينك</Chip>}
          {!st.response && !st.views && st.active && <Chip>اللينك اتبعت ومافتحش لسه</Chip>}
          {st.active && <button className="link-btn small" onClick={() => setCancel(true)}>إلغاء اللينكات</button>}
        </span>
      )}
      {st?.response === "change_requested" && st.response_note && (
        <div className="notice warn small" style={{ flexBasis: "100%" }}>طلب العميل: {st.response_note}</div>
      )}
      {cancel && st?.id && <Confirm danger title="إلغاء اللينكات" yes="إلغاء اللينكات" busy={busy} onClose={() => setCancel(false)}
        text="كل اللينكات اللي اتبعتت للعميل للمستند ده هتبطل تفتح."
        onYes={async () => { setBusy(true); try { await api.post(`/shares/${st.id}/revoke`); share.reload(); setCancel(false); } catch (e) { toast.err(errorText(e)); } finally { setBusy(false); } }} />}
    </>
  );
}
