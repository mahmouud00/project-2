// Everything the screens need about who is logged in: user, permissions per branch, the company's
// branding (name, logo, colour), settings (length unit, currency), licence and branches.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type S } from "../api/client";
import { fromMm, toMm, type LengthUnit } from "../lib/format";

export type Me = {
  id: string; username: string; full_name: string; company_id: string; device_id: string | null;
  must_change_password: boolean; grants: Record<string, string[]>;
};
export type Branding = {
  company_code: string; name: string; legal_name?: string; phone?: string; phone2?: string; email?: string; website?: string;
  address?: string; tax_number?: string; commercial_register?: string; invoice_footer?: string; accent_color?: string;
  has_logo: boolean; logo_media_id?: string | null;
};
export type Company = { id: string; code: string; name: string; version: number; settings: S<"CompanySettings">; branding: Branding };
export type License = {
  status: string; modules: string[]; max_devices: number | null; max_users: number | null; max_branches: number | null;
  expires_at: string | null; reason: string | null; license_id: string | null; can_read: boolean; can_write: boolean;
  module_names: Record<string, string>; machine_fingerprint?: string; company_code?: string | null;
};
export type ServerInfo = { product: string; version: string; mode: "offline" | "online"; min_client_version: string };

type Ctx = {
  me: Me; company: Company; license: License; info: ServerInfo; branches: S<"BranchOut">[]; isPlatform: boolean;
  logoUrl: string | null; unit: LengthUnit; currency: string;
  branchId: string | null; setBranchId: (id: string | null) => void;
  can: (perm: string, branchId?: string | null) => boolean;
  len: (mm: string | number | null | undefined) => string;
  toApiLen: (text: string) => string | null;
  reload: () => Promise<void>;
  setCompany: (c: Company) => void;
};

const SessionCtx = createContext<Ctx | null>(null);
export const PLATFORM_COMPANY_ID = "00000000-0000-0000-0000-000000000001";

export async function loadSession() {
  const [me, company, license, info, branches] = await Promise.all([
    api.get<Me>("/auth/me"),
    api.get<Company>("/company"),
    api.get<License>("/system/license").catch(() => null),
    api.public<ServerInfo>("/system/info"),
    api.get<S<"Page_BranchOut_">>("/branches", { limit: 200 }).then((p) => p.items).catch(() => []),
  ]);
  let logoUrl: string | null = null;
  if (company.branding?.has_logo) {
    logoUrl = await api.blob("/company/logo").then((b) => URL.createObjectURL(b)).catch(() => null);
  }
  const lic: License = license ?? { status: "unknown", modules: [], max_devices: null, max_users: null, max_branches: null,
    expires_at: null, reason: null, license_id: null, can_read: true, can_write: true, module_names: {} };
  return { me, company, license: lic, info, branches, logoUrl };
}

export type SessionData = Awaited<ReturnType<typeof loadSession>>;

export function SessionProvider({ initial, children }: { initial: SessionData; children: ReactNode }) {
  const [data, setData] = useState(initial);
  const [branchId, setBranch] = useState<string | null>(() => {
    try { return localStorage.getItem("mytech.branch"); } catch { return null; }
  });
  const setBranchId = useCallback((id: string | null) => {
    setBranch(id);
    try { id ? localStorage.setItem("mytech.branch", id) : localStorage.removeItem("mytech.branch"); } catch { /* */ }
  }, []);

  useEffect(() => {
    const accent = data.company.settings?.accent_color || data.company.branding?.accent_color;
    if (accent && /^#[0-9a-f]{6}$/i.test(accent)) document.documentElement.style.setProperty("--accent", accent);
    document.title = (data.company.branding?.name || data.company.name) + " · MYTech Solutions";
  }, [data.company]);

  useEffect(() => {
    if (branchId && !data.branches.some((b) => b.id === branchId)) setBranchId(null);
  }, [data.branches, branchId, setBranchId]);

  const value = useMemo<Ctx>(() => {
    const unit: LengthUnit = (data.company.settings?.length_unit as LengthUnit) || "cm";
    const grants = data.me.grants || {};
    const can = (perm: string, b?: string | null) => {
      if (grants["*"]?.includes(perm)) return true;
      if (b) return !!grants[b]?.includes(perm);
      return Object.values(grants).some((p) => p.includes(perm));
    };
    return {
      ...data, unit, currency: data.company.settings?.currency || "EGP",
      isPlatform: data.me.company_id === PLATFORM_COMPANY_ID,
      branchId, setBranchId, can,
      len: (mm) => fromMm(mm, unit),
      toApiLen: (t) => toMm(t, unit),
      reload: async () => {
        if (data.logoUrl) URL.revokeObjectURL(data.logoUrl);
        setData(await loadSession());
      },
      setCompany: (c) => setData((d) => ({ ...d, company: c })),
    };
  }, [data, branchId, setBranchId]);

  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>;
}

export function useSession(): Ctx {
  const c = useContext(SessionCtx);
  if (!c) throw new Error("useSession outside SessionProvider");
  return c;
}

/** The branch new records go to: the selected one, else the first the user can write in. */
export function useDefaultBranch(perm: string): string | null {
  const s = useSession();
  if (s.branchId && s.can(perm, s.branchId)) return s.branchId;
  return s.branches.find((b) => b.is_active && s.can(perm, b.id))?.id ?? null;
}
