// The signed-in user, their company and their sites, loaded from /api/auth/me.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiError, get, onAuthError, patch, post } from "./api";
import { useI18n, type Lang } from "./i18n";
import { useTheme, type ThemeChoice } from "./theme";

export interface Site { id: string; code: string; name: string; country: string; timezone: string; active: boolean; roles: string[]; }
export interface Me {
  user: {
    id: string; email: string; full_name: string; is_platform_admin: boolean; is_tenant_admin: boolean;
    language: Lang | null; theme: ThemeChoice; must_change_password: boolean;
    guide?: { checklist_hidden?: boolean; tours?: string[] };
  };
  policy: Policy;
  tenant: null | {
    id: string; code: string; name: string; country: string; timezone: string; default_language: Lang;
    features: Record<string, boolean>; terminology: Record<string, { en: string; ar: string }>;
    ai: { configured: boolean; review: boolean; read: boolean; science: boolean };
  };
  sites: Site[];
}
export interface Policy {
  min_length: number; require_upper: boolean; require_lower: boolean; require_digit: boolean;
  require_symbol: boolean; expiry_days: number; history: number; max_failed_attempts: number;
  lockout_minutes: number; session_timeout_minutes: number;
}

type Status = "loading" | "signed-out" | "signed-in";

interface SessionCtx {
  status: Status;
  me: Me | null;
  signedOutReason: string | null;
  refresh: () => Promise<void>;
  setMe: (me: Me) => void;
  signOut: () => Promise<void>;
  siteId: string | null;
  setSiteId: (id: string) => void;
  savePreference: (p: { language?: Lang; theme?: ThemeChoice }) => void;
}

const Ctx = createContext<SessionCtx>(null as unknown as SessionCtx);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMeState] = useState<Me | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [siteId, setSiteIdState] = useState<string | null>(null);
  const { setLang } = useI18n();
  const { setChoice } = useTheme();

  const setMe = useCallback((m: Me) => {
    setMeState(m);
    setStatus("signed-in");
    setReason(null);
    if (m.user.language) setLang(m.user.language);
    else if (m.tenant?.default_language && !localStorage.getItem("cp.lang")) setLang(m.tenant.default_language);
    if (m.user.theme) setChoice(m.user.theme);
    const saved = localStorage.getItem(`cp.site.${m.user.id}`);
    const pick = m.sites.find((s) => s.id === saved) ?? m.sites[0];
    setSiteIdState(pick ? pick.id : null);
  }, [setLang, setChoice]);

  const refresh = useCallback(async () => {
    try {
      setMe(await get<Me>("/api/auth/me"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setMeState(null);
        setStatus("signed-out");
        if (e.code === "session_expired") setReason("expired");
      } else {
        setStatus((s) => (s === "loading" ? "signed-out" : s));
      }
    }
  }, [setMe]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => onAuthError((err) => {
    setMeState(null);
    setStatus("signed-out");
    setReason(err.code === "session_expired" ? "expired" : null);
  }), []);

  const signOut = useCallback(async () => {
    try { await post("/api/auth/logout"); } catch { /* already signed out */ }
    setMeState(null);
    setStatus("signed-out");
    setReason("signed-out");
  }, []);

  const setSiteId = useCallback((id: string) => {
    setSiteIdState(id);
    if (me) localStorage.setItem(`cp.site.${me.user.id}`, id);
  }, [me]);

  const savePreference = useCallback((p: { language?: Lang; theme?: ThemeChoice }) => {
    if (p.language) setLang(p.language);
    if (p.theme) setChoice(p.theme);
    if (status === "signed-in") patch("/api/auth/preferences", p).catch(() => { /* preference is still kept locally */ });
  }, [setLang, setChoice, status]);

  return (
    <Ctx.Provider value={{ status, me, signedOutReason: reason, refresh, setMe, signOut, siteId, setSiteId, savePreference }}>
      {children}
    </Ctx.Provider>
  );
}

export const useSession = () => useContext(Ctx);

/** Company-specific wording for renamable terms such as "batch". */
export function useTerm() {
  const { me } = useSession();
  const { lang } = useI18n();
  return (key: string, fallback: string) => me?.tenant?.terminology?.[key]?.[lang] ?? fallback;
}

/** What the signed-in user may change. */
export function usePerms() {
  const { me, siteId } = useSession();
  const admin = !!me?.user.is_tenant_admin;
  const has = (role: string, id?: string | null) =>
    !!me?.sites.some((s) => (!id || s.id === id) && s.roles.includes(role));
  const editLibrary = admin || has("artwork_editor");
  const startAt = (id: string | null | undefined) => admin || has("reviewer", id) || has("artwork_editor", id);
  const site = me?.sites.find((s) => s.id === siteId) ?? null;
  return { admin, editLibrary, startAt, has, site, siteId };
}
