// Small cached reference lists used by many screens. invalidate() after editing one of them.
import { api, type S } from "../api/client";

const cache = new Map<string, Promise<unknown>>();

function cached<T>(key: string, fn: () => Promise<T>): Promise<T> {
  let p = cache.get(key) as Promise<T> | undefined;
  if (!p) {
    p = fn();
    p.catch(() => cache.delete(key));
    cache.set(key, p);
  }
  return p;
}

export function invalidate(prefix?: string) {
  for (const k of [...cache.keys()]) if (!prefix || k.startsWith(prefix)) cache.delete(k);
}

export const lookups = {
  systems: () => cached("systems", () => api.get<S<"SystemOut">[]>("/library/systems")),
  models: (systemId: string) => cached("models:" + systemId, () => api.get<S<"ModelOut">[]>("/library/models", { system_id: systemId })),
  async allModels(): Promise<(S<"ModelOut"> & { system: S<"SystemOut"> })[]> {
    const systems = await lookups.systems();
    const lists = await Promise.all(systems.map((s) => lookups.models(s.id).then((ms) => ms.map((m) => ({ ...m, system: s })))));
    return lists.flat();
  },
  model: async (id: string) => (await lookups.allModels()).find((m) => m.id === id),
  colors: () => cached("colors", () => api.get<S<"ColorOut">[]>("/library/colors")),
  glass: () => cached("glass", () => api.get<S<"Page_MaterialOut_">>("/library/materials", { kind: "glass", limit: 500 }).then((p) => p.items)),
  priceLists: () => cached("priceLists", () => api.get<S<"PriceListOut">[]>("/price-lists")),
  warehouses: () => cached("warehouses", () => api.get<S<"WarehouseOut">[]>("/warehouses")),
  cashboxes: () => cached("cashboxes", () => api.get<S<"CashboxOut">[]>("/cashboxes")),
  roles: () => cached("roles", () => api.get<S<"RoleOut">[]>("/roles")),
  permissions: () => cached("permissions", () => api.get<{ code: string; name: string }[]>("/permissions")),
  suppliers: () => cached("suppliers", () => api.get<S<"Page_SupplierOut_">>("/suppliers", { limit: 500 }).then((p) => p.items)),
  customer: (id: string) => cached("customer:" + id, () => api.get<S<"CustomerOut">>(`/customers/${id}`)),
};

export const STAGES = ["survey", "quotation", "approved", "manufacturing", "assembly", "quality", "delivered"] as const;
export const STAGE_NAMES: Record<string, string> = {
  survey: "معاينة", quotation: "عرض سعر", approved: "موافقة وعربون", manufacturing: "تصنيع", assembly: "تجميع",
  quality: "جودة", delivered: "تسليم", cancelled: "ملغي",
};
export const STAGE_COLOR: Record<string, "blue" | "green" | "amber" | "red" | "gray" | "violet"> = {
  survey: "gray", quotation: "blue", approved: "violet", manufacturing: "amber", assembly: "amber", quality: "blue",
  delivered: "green", cancelled: "red",
};

export const QUOTE_STATUS: Record<string, [string, "blue" | "green" | "amber" | "red" | "gray" | "violet"]> = {
  draft: ["مسودة", "gray"], sent: ["اتبعت للعميل", "blue"], accepted: ["مقبول", "green"], rejected: ["مرفوض", "red"],
  expired: ["منتهي", "amber"], ordered: ["اتعمل أمر تصنيع", "violet"],
};
export const INVOICE_STATUS: Record<string, [string, "blue" | "green" | "amber" | "red" | "gray" | "violet"]> = {
  draft: ["مسودة", "gray"], issued: ["صادرة", "blue"], cancelled: ["ملغية", "red"],
};
export const PO_STATUS: Record<string, [string, "blue" | "green" | "amber" | "red" | "gray" | "violet"]> = {
  draft: ["مسودة", "gray"], ordered: ["اتطلب", "blue"], partial: ["استلام جزئي", "amber"], received: ["اتستلم", "green"],
  cancelled: ["ملغي", "red"],
};
export const SURVEY_STATUS: Record<string, [string, "blue" | "green" | "amber" | "red" | "gray" | "violet"]> = {
  open: ["مفتوحة", "blue"], done: ["خلصت", "green"], cancelled: ["ملغية", "red"],
};
export const SURVEY_KIND: Record<string, string> = { window: "شبابيك وأبواب", shutter: "شيش" };
export const CUSTOMER_TYPES: Record<string, string> = { end: "عميل نهائي", dealer: "موزّع", contractor: "مقاول" };
export const MATERIAL_TYPES: Record<string, string> = { upvc: "UPVC", shutter: "شاتر", aluminum: "ألومنيوم" };
export const MATERIAL_KINDS: Record<string, string> = {
  profile: "قطاع", reinforcement: "حديد تدعيم", accessory: "إكسسوار", glass: "زجاج", gasket: "كاوتش", consumable: "مستهلكات",
  panel: "بانل", other: "أخرى",
};
export const UNITS: Record<string, string> = { m: "متر", pcs: "قطعة", set: "طقم", roll: "لفة", m2: "م²", kg: "كجم", l: "لتر" };
export const METHODS: Record<string, string> = { cash: "نقدي", transfer: "تحويل", cheque: "شيك", card: "كارت" };
