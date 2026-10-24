// Display helpers. Lengths: the API is in mm; the UI shows the company's unit (cm by default).
// Conversion shifts the decimal point on the string, so no floating-point rounding ever touches a size.

const DEC = /^-?\d+(\.\d+)?$/;

function shift(value: string, places: number): string {
  // value * 10^places, exact, on a decimal string
  let neg = value.startsWith("-");
  let [int, frac = ""] = (neg ? value.slice(1) : value).split(".");
  if (places > 0) {
    frac = frac.padEnd(places, "0");
    int = int + frac.slice(0, places);
    frac = frac.slice(places);
  } else if (places < 0) {
    const n = -places;
    int = int.padStart(n + 1, "0");
    frac = int.slice(int.length - n) + frac;
    int = int.slice(0, int.length - n);
  }
  int = int.replace(/^0+(?=\d)/, "");
  frac = frac.replace(/0+$/, "");
  const out = frac ? `${int}.${frac}` : int;
  if (out === "0") neg = false;
  return (neg ? "-" : "") + out;
}

export function clean(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  const s = String(value).trim();
  return DEC.test(s) ? shift(s, 0) : s;
}

export type LengthUnit = "cm" | "mm";

/** mm (API) -> display unit */
export function fromMm(mm: string | number | null | undefined, unit: LengthUnit = "cm"): string {
  if (mm === null || mm === undefined || mm === "") return "";
  const s = String(mm).trim();
  if (!DEC.test(s)) return s;
  return unit === "cm" ? shift(s, -1) : shift(s, 0);
}

/** display unit -> mm (API). Returns null if the text is not a number. */
export function toMm(text: string, unit: LengthUnit = "cm"): string | null {
  const s = text.trim().replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d))).replace("٫", ".").replace(",", ".");
  if (!DEC.test(s)) return null;
  return unit === "cm" ? shift(s, 1) : shift(s, 0);
}

export function money(x: string | number | null | undefined): string {
  if (x === null || x === undefined || x === "") return "—";
  const n = Number(x);
  if (!isFinite(n)) return String(x);
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function qty(x: string | number | null | undefined): string {
  if (x === null || x === undefined || x === "") return "";
  return clean(x);
}

export function date(x: string | null | undefined): string {
  if (!x) return "—";
  return x.slice(0, 10);
}

export function dateTime(x: string | null | undefined): string {
  if (!x) return "—";
  const d = new Date(x);
  if (isNaN(d.getTime())) return x;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function today(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function initials(name: string): string {
  return (name || "?").trim().slice(0, 1);
}

/** Exact sum of money strings (2 decimals) using integer cents. */
export function sumMoney(values: (string | number | null | undefined)[]): string {
  let cents = 0n;
  for (const v of values) {
    const s = toCents(v);
    if (s !== null) cents += s;
  }
  const neg = cents < 0n;
  const a = neg ? -cents : cents;
  return (neg ? "-" : "") + (a / 100n).toString() + "." + (a % 100n).toString().padStart(2, "0");
}

function toCents(v: string | number | null | undefined): bigint | null {
  if (v === null || v === undefined || v === "") return null;
  const s = String(v).trim();
  if (!DEC.test(s)) return null;
  const neg = s.startsWith("-");
  const [i, f = ""] = (neg ? s.slice(1) : s).split(".");
  const c = BigInt(i) * 100n + BigInt((f + "00").slice(0, 2));
  return neg ? -c : c;
}

/** Exact qty × price rounded half-up to 2 decimals (preview only; the server stores the real totals). */
export function mulMoney(a: string | number | null | undefined, b: string | number | null | undefined): string {
  const pa = scaled(a), pb = scaled(b);
  if (!pa || !pb) return "0.00";
  const scale = pa.scale + pb.scale;
  let n = pa.n * pb.n;
  const neg = n < 0n;
  if (neg) n = -n;
  const div = 10n ** BigInt(scale);
  let cents = (n * 100n * 2n + div) / (div * 2n);
  if (scale < 2) cents = n * 10n ** BigInt(2 - scale);
  const out = (cents / 100n).toString() + "." + (cents % 100n).toString().padStart(2, "0");
  return neg && cents !== 0n ? "-" + out : out;
}

function scaled(v: string | number | null | undefined): { n: bigint; scale: number } | null {
  if (v === null || v === undefined || v === "") return null;
  const s = String(v).trim();
  if (!DEC.test(s)) return null;
  const neg = s.startsWith("-");
  const [i, f = ""] = (neg ? s.slice(1) : s).split(".");
  const n = BigInt(i + f);
  return { n: neg ? -n : n, scale: f.length };
}
