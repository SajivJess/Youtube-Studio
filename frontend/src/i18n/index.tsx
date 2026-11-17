import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import en from "./locales/en";

type Catalog = Record<string, string>;

export const UI_LANGUAGES = [
  { code: "en", name: "English" },
];
export const RTL = new Set<string>();
const DEFAULT = "en";

type Vars = Record<string, string | number>;
export type T = (key: string, vars?: Vars) => string;

interface I18n {
  lang: string;
  dir: "ltr" | "rtl";
  t: T;
  setLang: (code: string) => void;
  num: (n: number, digits?: number) => string;
  relTime: (iso: string) => string;
}

const Ctx = createContext<I18n | null>(null);

function stored(): string {
  try {
    localStorage.setItem("cf-lang", "en");
    localStorage.setItem("cf-lang-set", "1");
  } catch {
    /* ignore */
  }
  return DEFAULT;
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState(stored);
  const [cat] = useState<Catalog>(() => en);

  useEffect(() => {
    const el = document.documentElement;
    el.lang = "en";
    el.dir = "ltr";
    try {
      localStorage.setItem("cf-lang", "en");
      localStorage.setItem("cf-lang-set", "1");
    } catch {
      /* ignore */
    }
  }, []);

  const setLang = useCallback((_code: string) => {
    setLangState("en");
  }, []);

  const value = useMemo<I18n>(() => {
    const plural = new Intl.PluralRules("en");
    const t: T = (key, vars) => {
      let s: string | undefined;
      const n = vars ? (typeof vars.n === "number" ? vars.n : typeof vars.n === "string" ? Number(vars.n.replace(/[^\d-]/g, "")) : NaN) : NaN;
      if (vars && vars.n !== "" && Number.isFinite(n)) {
        const rule = plural.select(n);
        s = en[`${key}_${rule}`] ?? en[`${key}_other`];
      }
      s = s ?? en[key] ?? key;
      if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
      return s;
    };
    const locale = "en-US";
    const nf = new Map<number, Intl.NumberFormat>();
    const num = (n: number, digits = 0) => {
      if (!nf.has(digits))
        nf.set(digits, new Intl.NumberFormat(locale, { maximumFractionDigits: digits, minimumFractionDigits: digits }));
      return nf.get(digits)!.format(n);
    };
    const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
    const relTime = (iso: string) => {
      const diff = (new Date(iso).getTime() - Date.now()) / 1000;
      const abs = Math.abs(diff);
      if (abs < 60) return rtf.format(Math.round(diff), "second");
      if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
      if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
      return rtf.format(Math.round(diff / 86400), "day");
    };
    return { lang, dir: "ltr", t, setLang, num, relTime };
  }, [lang, setLang, cat]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const v = useContext(Ctx);
  if (!v) throw new Error("useI18n outside provider");
  return v;
}
