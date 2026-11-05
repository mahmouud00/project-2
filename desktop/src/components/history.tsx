// سجل التغييرات: who changed what on this record, and when (its lines included: a quotation's prices are on them).
import { useState } from "react";
import { api } from "../api/client";
import { useLoad } from "../lib/hooks";
import { dateTime } from "../lib/format";
import type { RecordRef } from "../lib/title";
import { useSession } from "../state/session";
import { Icon } from "./icons";
import { ErrorBox, Loading, Modal } from "./ui";

type Entry = { at: string; user_id: string | null; user_name: string | null; entity: string; entity_id: string; action: string;
  changes: Record<string, any>; note: string | null };

const ENTITY: Record<string, string> = {
  quotations: "العرض", quotation_lines: "بند", work_orders: "الأمر", work_order_items: "بند", site_surveys: "المعاينة",
  survey_openings: "وحدة", invoices: "الفاتورة", invoice_lines: "بند", purchase_orders: "أمر الشراء", purchase_order_lines: "بند",
  customers: "العميل", suppliers: "المورد", employees: "الموظف", product_models: "النموذج", model_test_cases: "اختبار مرجعي",
  profile_systems: "القطاع", system_constants: "ثابت", materials: "الخامة",
};
const ACTION: Record<string, string> = { create: "إضافة", update: "تعديل", delete: "حذف" };
const FIELD: Record<string, string> = {
  status: "الحالة", stage: "المرحلة", name: "الاسم", full_name: "الاسم", phone: "التليفون", address: "العنوان", email: "الإيميل",
  notes: "ملاحظات", note: "ملاحظة", description: "الوصف", code: "الكود", number: "الرقم", qty: "العدد", location: "المكان",
  manual_unit_price: "سعر الوحدة", unit_price: "سعر الوحدة", price_per_m2: "سعر المتر", discount_pct: "الخصم %", discount: "الخصم",
  discount_amount: "الخصم", tax_pct: "الضريبة %", total: "الإجمالي", subtotal: "المجموع", deposit: "العربون", paid_amount: "المدفوع",
  valid_until: "صالح لحد", delivery_date: "التسليم", model_id: "النموذج", color_code: "اللون", glass_material_code: "الزجاج",
  opening_width_mm: "العرض", opening_height_mm: "الارتفاع", total_height_mm: "الارتفاع الكلي", customer_id: "العميل",
  branch_id: "الفرع", salesperson_id: "البائع", definition: "التعريف (المعادلات والقطع)", image_id: "الصورة", color_images: "صور الألوان",
  category: "النوع", is_active: "نشط", value: "القيمة", label: "الوصف", reference_cost: "التكلفة المرجعية", unit: "الوحدة",
  bar_length_mm: "طول العود", min_piece_mm: "أقل قطعة", rounding_step_mm: "التقريب", deleted_at: "اتحذف", sale_status: "تأكيد الحسابات",
  price_approved_total: "السعر المعتمد", params: "المتغيرات", sort: "الترتيب",
};
const STATUS: Record<string, string> = {
  draft: "مسودة", sent: "اتبعت", accepted: "مقبول", rejected: "مرفوض", expired: "منتهي", open: "مفتوحة", done: "خلصت",
  cancelled: "ملغي", issued: "صادرة", trial: "تحت التجربة", approved: "معتمد", pending: "مستني", window: "شباك", door: "باب",
};
const SKIP = new Set(["id", "company_id", "created_by", "updated_by", "quotation_id", "work_order_id", "survey_id", "invoice_id",
  "purchase_order_id", "model_id_snapshot", "system_id"]);

function useShow() {
  const s = useSession();
  return (key: string, v: any): string => {
    if (v === null || v === undefined || v === "") return "—";
    if (v === "***") return "(بيانات شخصية متخفية)";
    if (typeof v === "boolean") return v ? "نعم" : "لا";
    if (key.endsWith("_mm") && !isNaN(Number(v))) return `${s.len(String(v))} ${s.unit === "cm" ? "سم" : "مم"}`;
    if (typeof v === "string" && STATUS[v]) return STATUS[v];
    if (typeof v === "object") return Array.isArray(v) ? `${v.length} عنصر` : "اتغيّر";
    const t = String(v);
    return t.length > 80 ? t.slice(0, 80) + "…" : t;
  };
}

export function HistoryButton({ record }: { record: RecordRef }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="icon-btn" onClick={() => setOpen(true)} title="سجل التغييرات: مين غيّر إيه وإمتى" aria-label="سجل التغييرات"><Icon name="clock" /></button>
      {open && <History record={record} onClose={() => setOpen(false)} />}
    </>
  );
}

function History({ record, onClose }: { record: RecordRef; onClose: () => void }) {
  const list = useLoad(() => api.get<Entry[]>(`/history/${record.kind}/${record.id}`), [record.kind, record.id]);
  const show = useShow();
  return (
    <Modal title="سجل التغييرات" size="wide" onClose={onClose}>
      {list.error && <ErrorBox text={list.error} onRetry={list.reload} />}
      {list.loading && !list.data && <Loading />}
      {list.data && !list.data.length && <div className="empty">مفيش تغييرات متسجلة.</div>}
      <div className="col history">
        {(list.data ?? []).map((e, i) => {
          const fields = Object.entries(e.changes).filter(([k]) => !SKIP.has(k));
          const isDiff = e.action === "update";
          return (
            <div key={i} className="history-row">
              <div className="row small" style={{ gap: 8 }}>
                <b>{ACTION[e.action] ?? e.action} {ENTITY[e.entity] ?? e.entity}</b>
                <span className="muted">{e.user_name ?? "النظام"}</span>
                <span className="muted num end">{dateTime(e.at)}</span>
              </div>
              {e.note && <div className="small muted">{e.note}</div>}
              {isDiff && fields.length > 0 && (
                <table className="history-changes"><tbody>
                  {fields.map(([k, c]) => (
                    <tr key={k}><td className="muted">{FIELD[k] ?? k}</td>
                      <td><span className="del">{show(k, c?.old)}</span> ← <span className="ins">{show(k, c?.new)}</span></td></tr>
                  ))}
                </tbody></table>
              )}
            </div>
          );
        })}
      </div>
    </Modal>
  );
}
