// Language (English / Arabic with right-to-left layout) and locale-aware formatting.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ar, en, type StringKey } from "./strings";

export type Lang = "en" | "ar";

type Vars = Record<string, string | number>;

interface I18n {
  lang: Lang;
  dir: "ltr" | "rtl";
  setLang: (l: Lang) => void;
  t: (key: StringKey, vars?: Vars) => string;
  /** Translate a dynamic key, falling back to the given text. */
  tx: (key: string, fallback: string, vars?: Vars) => string;
  dateTime: (iso: string | null | undefined, tz?: string) => string;
  date: (iso: string | null | undefined, tz?: string) => string;
  number: (n: number) => string;
  /** "2026-11" -> "Nov 2026". */
  month: (ym: string, long?: boolean) => string;
  /** Quantity with up to `max` decimals. */
  qty: (n: number | string | null | undefined, max?: number) => string;
  countryName: (code: string) => string;
}

const dicts: Record<Lang, Record<string, string>> = { en, ar };

function fill(s: string, vars?: Vars) {
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] !== undefined ? String(vars[k]) : `{${k}}`));
}

function readLang(): Lang | null {
  try {
    const v = localStorage.getItem("cp.lang");
    if (v === "en" || v === "ar") return v;
  } catch { /* ignore */ }
  return null;
}

const Ctx = createContext<I18n>(null as unknown as I18n);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => readLang() ?? (navigator.language?.startsWith("ar") ? "ar" : "en"));
  const dir = lang === "ar" ? "rtl" : "ltr";

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = dir;
  }, [lang, dir]);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try { localStorage.setItem("cp.lang", l); } catch { /* ignore */ }
  }, []);

  const value = useMemo<I18n>(() => {
    // Latin digits in Arabic keep codes, quantities and dates easy to compare in plant documents.
    const locale = lang === "ar" ? "ar-EG-u-nu-latn" : "en-GB";
    const dict = dicts[lang];
    const fmtCache = new Map<string, Intl.DateTimeFormat>();
    const fmt = (tz: string | undefined, withTime: boolean) => {
      const key = `${tz ?? ""}|${withTime}`;
      let f = fmtCache.get(key);
      if (!f) {
        try {
          f = new Intl.DateTimeFormat(locale, {
            timeZone: tz, year: "numeric", month: "short", day: "2-digit",
            ...(withTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
          });
        } catch {
          f = new Intl.DateTimeFormat(locale, { year: "numeric", month: "short", day: "2-digit" });
        }
        fmtCache.set(key, f);
      }
      return f;
    };
    let regions: Intl.DisplayNames | null = null;
    try { regions = new Intl.DisplayNames([locale], { type: "region" }); } catch { regions = null; }
    const nf = new Intl.NumberFormat(locale);
    return {
      lang, dir, setLang,
      t: (key, vars) => fill(dict[key] ?? en[key] ?? key, vars),
      tx: (key, fallback, vars) => fill(dict[key] ?? (en as Record<string, string>)[key] ?? fallback, vars),
      dateTime: (iso, tz) => (iso ? fmt(tz, true).format(new Date(iso)) : ""),
      date: (iso, tz) => (iso ? fmt(tz, false).format(new Date(iso)) : ""),
      number: (n) => nf.format(n),
      month: (ym, long) => new Intl.DateTimeFormat(locale, { timeZone: "UTC", year: "numeric", month: long ? "long" : "short" })
        .format(new Date(`${ym.slice(0, 7)}-01T00:00:00Z`)),
      qty: (n, max = 3) => {
        if (n === null || n === undefined || n === "") return "";
        const v = typeof n === "string" ? Number(n) : n;
        if (!Number.isFinite(v)) return String(n);
        return new Intl.NumberFormat(locale, { maximumFractionDigits: max }).format(v);
      },
      countryName: (code) => {
        try { return regions?.of(code) ?? code; } catch { return code; }
      },
    };
  }, [lang, dir, setLang]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useI18n = () => useContext(Ctx);
