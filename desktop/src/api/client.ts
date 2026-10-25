// HTTP client for the MYTech server: bearer tokens with one shared refresh, uniform errors,
// client version header (426 = this program must be updated). Lengths go to the API in mm.
import type { components } from "./schema";

export type S<K extends keyof components["schemas"]> = components["schemas"][K];
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export const CLIENT_VERSION: string = __APP_VERSION__;

const K = { server: "mytech.server", company: "mytech.company", refresh: "mytech.refresh", device: "mytech.device",
  user: "mytech.username" };

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

function read(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function write(key: string, value: string | null) {
  try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch { /* storage blocked */ }
}

export const store = {
  get server() { return read(K.server); },
  set server(v: string | null) { write(K.server, v); },
  get company() { return read(K.company) ?? ""; },
  set company(v: string) { write(K.company, v); },
  get username() { return read(K.user) ?? ""; },
  set username(v: string) { write(K.user, v); },
  get deviceKey() {
    let k = read(K.device);
    if (!k) { k = crypto.randomUUID(); write(K.device, k); }
    return k;
  },
};

type Listener = (event: "logout" | "update-required" | "license", detail?: unknown) => void;
const listeners = new Set<Listener>();
export function onApiEvent(fn: Listener) { listeners.add(fn); return () => { listeners.delete(fn); }; }
const emit: Listener = (e, d) => listeners.forEach((l) => l(e, d));

let access: string | null = null;
let refreshing: Promise<boolean> | null = null;

export function normalizeServer(input: string): string {
  let s = input.trim().replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(s)) s = "http://" + s;
  if (!/:\d+$/.test(s.replace(/^https?:\/\//i, "").split("/")[0])) s += ":8000";
  return s;
}

function base(): string {
  if (!store.server) throw new ApiError(0, "NO_SERVER", "لم يتم اختيار السيرفر");
  return store.server + "/api/v1";
}

function qs(query?: Record<string, unknown>): string {
  if (!query) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? "?" + s : "";
}

async function parseError(r: Response): Promise<ApiError> {
  let body: any = null;
  try { body = await r.json(); } catch { /* not json */ }
  const e = body?.error;
  return new ApiError(r.status, e?.code ?? `HTTP_${r.status}`, e?.message ?? r.statusText, e?.details);
}

async function doRefresh(): Promise<boolean> {
  const token = read(K.refresh);
  if (!token) return false;
  try {
    const r = await fetch(base() + "/auth/refresh", { method: "POST", headers: { "Content-Type": "application/json",
      "X-Client-Version": CLIENT_VERSION }, body: JSON.stringify({ refresh_token: token }) });
    if (!r.ok) { write(K.refresh, null); access = null; return false; }
    const t = await r.json();
    access = t.access_token;
    write(K.refresh, t.refresh_token);
    return true;
  } catch {
    return false;
  }
}

function refreshOnce(): Promise<boolean> {
  if (!refreshing) refreshing = doRefresh().finally(() => { refreshing = null; });
  return refreshing;
}

export async function raw(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("X-Client-Version", CLIENT_VERSION);
  if (access) headers.set("Authorization", "Bearer " + access);
  let r: Response;
  try {
    r = await fetch(base() + path, { ...init, headers });
  } catch {
    throw new ApiError(0, "NETWORK", "تعذّر الاتصال بالسيرفر");
  }
  if (r.status === 401 && retry && read(K.refresh)) {
    if (await refreshOnce()) return raw(path, init, false);
    emit("logout");
  }
  if (r.status === 426) emit("update-required", await r.clone().json().catch(() => null));
  if (r.status === 402) emit("license", await r.clone().json().catch(() => null));
  return r;
}

async function json<T>(method: string, path: string, body?: unknown, query?: Record<string, unknown>): Promise<T> {
  const r = await raw(path + qs(query), {
    method, headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw await parseError(r);
  if (r.status === 204) return undefined as T;
  const text = await r.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T>(path: string, query?: Record<string, unknown>) => json<T>("GET", path, undefined, query),
  post: <T>(path: string, body?: unknown, query?: Record<string, unknown>) => json<T>("POST", path, body ?? {}, query),
  patch: <T>(path: string, body: unknown) => json<T>("PATCH", path, body),
  put: <T>(path: string, body: unknown) => json<T>("PUT", path, body),
  del: <T>(path: string) => json<T>("DELETE", path),
  async upload<T>(path: string, file: File | Blob, name = "file"): Promise<T> {
    const fd = new FormData();
    fd.append(name, file, (file as File).name ?? "upload");
    const r = await raw(path, { method: "POST", body: fd });
    if (!r.ok) throw await parseError(r);
    return r.json();
  },
  async text(path: string): Promise<string> {
    const r = await raw(path);
    if (!r.ok) throw await parseError(r);
    return r.text();
  },
  async blob(path: string): Promise<Blob> {
    const r = await raw(path);
    if (!r.ok) throw await parseError(r);
    return r.blob();
  },
  /** Public endpoint (no token), e.g. server info or branding before login. */
  async public<T>(path: string, query?: Record<string, unknown>, server?: string): Promise<T> {
    const root = (server ?? store.server) + "/api/v1";
    let r: Response;
    try {
      r = await fetch(root + path + qs(query), { headers: { "X-Client-Version": CLIENT_VERSION } });
    } catch {
      throw new ApiError(0, "NETWORK", "تعذّر الاتصال بالسيرفر");
    }
    if (!r.ok) throw await parseError(r);
    return r.headers.get("content-type")?.includes("json") ? r.json() : (r.blob() as any);
  },
  /** Upload without a token (licence activation before anyone can log in). */
  async publicUpload<T>(path: string, file: File | Blob, name = "file"): Promise<T> {
    const fd = new FormData();
    fd.append(name, file, (file as File).name ?? "upload");
    let r: Response;
    try {
      r = await fetch(base() + path, { method: "POST", body: fd, headers: { "X-Client-Version": CLIENT_VERSION } });
    } catch {
      throw new ApiError(0, "NETWORK", "تعذّر الاتصال بالسيرفر");
    }
    if (!r.ok) throw await parseError(r);
    return r.json();
  },
};

export async function login(company: string, username: string, password: string) {
  const r = await fetch(base() + "/auth/login", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Client-Version": CLIENT_VERSION },
    body: JSON.stringify({ company_code: company || null, username, password, device_key: store.deviceKey,
      device_name: deviceName(), client_version: CLIENT_VERSION, platform: platformName() }),
  }).catch(() => { throw new ApiError(0, "NETWORK", "تعذّر الاتصال بالسيرفر"); });
  if (!r.ok) throw await parseError(r);
  const t = await r.json();
  access = t.access_token;
  write(K.refresh, t.refresh_token);
  store.company = company;
  store.username = username;
  return t;
}

export async function resume(): Promise<boolean> {
  return refreshOnce();
}

export async function logout() {
  const token = read(K.refresh);
  if (token) await fetch(base() + "/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: token }) }).catch(() => undefined);
  write(K.refresh, null);
  access = null;
}

function platformName() {
  const ua = navigator.userAgent;
  return /Windows/i.test(ua) ? "windows" : /Mac/i.test(ua) ? "mac" : /Linux/i.test(ua) ? "linux" : "other";
}
function deviceName() {
  return "MYTech Desktop (" + platformName() + ")";
}

/** Arabic message for an API error. */
export function errorText(e: unknown): string {
  if (!(e instanceof ApiError)) return e instanceof Error ? e.message : String(e);
  const m = MESSAGES[e.code];
  if (m) return m;
  if (e.code === "VALIDATION_FAILED" && Array.isArray(e.details)) {
    return "بيانات غير صحيحة: " + (e.details as any[]).map((d) => fieldName(d.loc ?? []) + ": " + validationText(d.msg ?? "")).join("، ");
  }
  return e.message || e.code;
}

const SECTIONS: Record<string, string> = {
  params: "المتغيرات", formulas: "المعادلات", pieces: "القطع", glass: "الزجاج", accessories: "الإكسسوار",
  validations: "التحقق", drawing: "الرسمة", constants: "الثوابت",
};
const FIELDS: Record<string, string> = {
  key: "الاسم", name: "الاسم", label: "الوصف", expr: "المعادلة", length_expr: "معادلة الطول", qty_expr: "العدد",
  width_expr: "معادلة العرض", height_expr: "معادلة الارتفاع", area_expr: "المساحة", condition: "الشرط",
  material_code: "الخامة", code: "الكود", message: "الرسالة",
};

/** ["body", "definition", "formulas", 0, "key"] -> "المعادلات، سطر 1، الاسم" */
function fieldName(loc: (string | number)[]): string {
  const parts: string[] = [];
  for (const p of loc.slice(1)) {
    if (p === "definition") continue;
    if (typeof p === "number") parts.push(`سطر ${p + 1}`);
    else parts.push(SECTIONS[p] ?? FIELDS[p] ?? p);
  }
  return parts.join("، ");
}

function validationText(msg: string): string {
  if (msg.includes("must be an identifier"))
    return "الاسم لازم يبقى كلمة واحدة: حروف (عربي أو إنجليزي) وأرقام و _ من غير مسافات، ومايبدأش برقم (مثلًا عرض_الضلفة)";
  if (msg.includes("Field required")) return "مطلوب";
  return msg;
}

const MESSAGES: Record<string, string> = {
  BAD_REQUEST: "الطلب ده مش صحيح.",
  UNAUTHORIZED: "لازم تسجّل دخول تاني.",
  CONFLICT: "مينفعش تعمل ده دلوقتي.",
  LICENSE_REQUIRED: "الترخيص مش سامح بده.",
  TOKEN_EXPIRED: "الجلسة انتهت. سجّل دخول تاني.",
  TOKEN_INVALID: "الجلسة مش صالحة. سجّل دخول تاني.",
  TOKEN_REUSED: "الجلسة اتستخدمت من مكان تاني. سجّل دخول تاني.",
  CALC_INVALID: "الوحدة دي مينفعش تتصنع بالنموذج ده بالمقاس ده (فيه خطأ في الحساب). جرّب الحساب من تفاصيل الوحدة.",
  OPENING_WITHOUT_MODEL: "فيه وحدة في المعاينة من غير نموذج (رقم الوحدة). اختار النموذج الأول.",
  SURVEY_CUSTOMER: "المعاينة دي لعميل تاني.",
  CUSTOMER_REQUIRED: "اختار العميل والفرع.",
  CONSTANT_REQUIRED: "خلوص التركيب ثابت أساسي ومينفعش يتمسح.",
  UNKNOWN_CONSTANT: "فيه ثابت مش موجود في السيستم.",
  UNKNOWN_MATERIAL: "فيه خامة مش موجودة في المكتبة.",
  UNKNOWN_SKU: "الصنف ده مش موجود.",
  UNKNOWN_PERMISSION: "صلاحية مش معروفة.",
  PRICE_ITEM_TARGET: "كل بند في قائمة الأسعار لازم يكون لنموذج أو لسيستم واحد بس.",
  LINE_MISMATCH: "البند ده مش من الأمر ده.",
  OVER_RECEIPT: "الكمية المستلمة أكبر من المطلوبة.",
  QTY_ZERO: "الكمية مينفعش تبقى صفر.",
  SAME_WAREHOUSE: "اختار مخزن تاني للتحويل.",
  WAREHOUSE_BRANCH: "المخزن ده تبع فرع تاني.",
  PARTY_REQUIRED: "اختار العميل أو المورد.",
  PARTY_MISMATCH: "ده تبع عميل تاني.",
  WO_CANCELLED: "أمر التصنيع ده ملغي.",
  WO_MISMATCH: "أمر التصنيع ده مينفعش ياخد العرض ده.",
  NO_OUTPUTS: "اعمل مخرجات التصنيع الأول.",
  NO_QUOTATION: "مفيش عرض سعر متوافق عليه.",
  NO_LOGO: "مفيش لوجو.",
  NOT_OFFLINE: "ده للنسخة الأوفلاين بس.",
  PLATFORM_ONLY: "ده بتعمله MYTech بس.",
  SUBJECT_TYPE: "نوع البيانات مش معروف.",
  IMPORT_DONE: "الحزمة دي اتطبقت قبل كده.",
  PACKAGE_MISSING: "ملف الحزمة مش موجود. افتحها تاني.",
  PACKAGE_INVALID: "ملف الحزمة بايظ.",
  PACKAGE_CORRUPTED: "ملف الحزمة بايظ.",
  PACKAGE_FORMAT: "ده مش ملف حزمة مكتبة.",
  PACKAGE_INCOMPLETE: "ملف الحزمة ناقص.",
  PACKAGE_COLLISION: "الحزمة فيها أكواد بتتعارض مع بيانات الشركة.",
  PACKAGE_VERSION_CONFLICT: "الحزمة بتغيّر نسخة منشورة قبل كده، ومينفعش.",
  NETWORK: "تعذّر الاتصال بالسيرفر. اتأكد إن السيرفر شغال وإن الجهاز على نفس الشبكة.",
  NO_SERVER: "اختار السيرفر الأول.",
  INVALID_CREDENTIALS: "اسم المستخدم أو كلمة المرور غلط.",
  ACCOUNT_LOCKED: "الحساب متقفل مؤقتًا بسبب محاولات دخول كتير. حاول بعد شوية.",
  USER_DISABLED: "المستخدم ده متوقف.",
  DEVICE_DISABLED: "الجهاز ده متوقف من الإدارة.",
  COMPANY_REQUIRED: "اكتب كود الشركة.",
  VERSION_CONFLICT: "البيانات دي اتعدلت من جهاز تاني. حدّث الصفحة وحاول تاني.",
  PERMISSION_DENIED: "مالكش صلاحية تعمل ده.",
  FORBIDDEN: "مالكش صلاحية تعمل ده.",
  NOT_FOUND: "مش موجود.",
  LICENSE_INVALID: "الترخيص غير صالح أو مش موجود.",
  LICENSE_READ_ONLY: "الترخيص منتهي: البرنامج شغال قراءة بس.",
  LICENSE_DEVICE_LIMIT: "عدد الأجهزة وصل للحد المسموح في الترخيص.",
  LICENSE_USER_LIMIT: "عدد المستخدمين وصل للحد المسموح في الترخيص.",
  LICENSE_BRANCH_LIMIT: "عدد الفروع وصل للحد المسموح في الترخيص.",
  LICENSE_REJECTED: "ملف الترخيص مرفوض (مش لنفس الجهاز أو التوقيع غلط أو منتهي).",
  LICENSE_FILE_INVALID: "ده مش ملف ترخيص.",
  ARCH_MODEL_REQUIRED: "الوحدة ليها ارتفاع كلي (أرج): اختار نموذج الأرج، أو حدد نموذج أرج افتراضي في الإعدادات.",
  ARCH_LINE_MANAGED: "سطر الأرج بيتعدل من البند بتاعه.",
  LICENSE_ACTIVE: "فيه ترخيص شغال. التغيير من صفحة الترخيص والنسخ بعد الدخول.",
  MODULE_NOT_LICENSED: "الجزء ده مش ضمن الترخيص.",
  CLIENT_UPDATE_REQUIRED: "لازم تحدّث البرنامج عشان يشتغل مع السيرفر.",
  DUPLICATE_CODE: "الكود ده مستخدم قبل كده.",
  DUPLICATE_USERNAME: "اسم المستخدم ده موجود.",
  DUPLICATE_NAME: "الاسم ده موجود.",
  LIBRARY_READ_ONLY: "دي من مكتبة MYTech ومينفعش تتعدل. تقدر تعمل معايرة خاصة بالشركة.",
  QUOTE_LOCKED: "عرض السعر مقفول ومينفعش يتعدل.",
  INVOICE_LOCKED: "الفاتورة صدرت ومينفعش تتعدل. تقدر تلغيها.",
  INVOICE_EMPTY: "الفاتورة مفيهاش سطور.",
  ALREADY_INVOICED: "اتعملت فاتورة لده قبل كده.",
  QUOTE_NOT_ACCEPTED: "لازم عرض السعر يتقبل الأول.",
  QUOTE_ALREADY_ORDERED: "عرض السعر ده اتعمل منه أمر تصنيع.",
  INVALID_TRANSITION: "مينفعش تنقل للمرحلة دي من المرحلة الحالية.",
  DEPOSIT_REQUIRED: "لازم العربون يتدفع الأول.",
  INSUFFICIENT_STOCK: "الكمية في المخزن مش كفاية.",
  INSUFFICIENT_CASH: "رصيد الخزينة مش كفاية.",
  MANUFACTURING_ERRORS: "فيه أخطاء في الحسابات لازم تتصلح الأول.",
  MODEL_NOT_PUBLISHED: "النموذج ده لسه مش منشور.",
  NOT_PUBLISHED: "القطاع لسه مش منشور.",
  NOTHING_TO_PUBLISH: "مفيش نماذج للنشر.",
  PUBLISH_FAILED: "النشر اترفض: فيه نموذج فيه غلط أو اختبار مرجعي مش مطابق.",
  NO_PRICE_LIST: "مفيش قائمة أسعار. اعمل قائمة أسعار الأول.",
  NO_WAREHOUSE: "اختار المخزن.",
  MATERIALS_ISSUED: "الخامات اتصرفت خلاص.",
  OUTPUTS_FROZEN: "مخرجات التصنيع اتجمدت بعد صرف الخامات.",
  ALREADY_REVERSED: "الحركة دي اتعكست قبل كده.",
  DISCOUNT_TOO_LARGE: "الخصم أكبر من الإجمالي.",
  FILE_TOO_LARGE: "الملف كبير (الحد 5 ميجا).",
  FILE_TYPE: "نوع الملف مش مدعوم (PNG أو JPEG أو WEBP).",
  WRONG_PASSWORD: "كلمة المرور الحالية غلط.",
  PACKAGE_SIGNATURE_INVALID: "توقيع الحزمة غلط. الحزمة مش من MYTech أو اتعدلت.",
  BACKUP_FAILED: "النسخة الاحتياطية فشلت.",
  SELF_ERASE: "مينفعش تمسح بياناتك بنفسك.",
};
