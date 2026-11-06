// Light / dark / follow-system theme, stored per browser and per user.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

export type ThemeChoice = "light" | "dark" | "system";

const ThemeCtx = createContext<{ choice: ThemeChoice; resolved: "light" | "dark"; setChoice: (c: ThemeChoice) => void }>(
  { choice: "system", resolved: "light", setChoice: () => {} },
);

const media = window.matchMedia("(prefers-color-scheme: dark)");

function read(): ThemeChoice {
  try {
    const v = localStorage.getItem("cp.theme");
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch { /* storage unavailable */ }
  return "system";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(read);
  const [systemDark, setSystemDark] = useState(media.matches);
  useEffect(() => {
    const fn = () => setSystemDark(media.matches);
    media.addEventListener("change", fn);
    return () => media.removeEventListener("change", fn);
  }, []);
  const resolved = choice === "system" ? (systemDark ? "dark" : "light") : choice;
  useEffect(() => { document.documentElement.dataset.theme = resolved; }, [resolved]);
  const setChoice = useCallback((c: ThemeChoice) => {
    setChoiceState(c);
    try { localStorage.setItem("cp.theme", c); } catch { /* ignore */ }
  }, []);
  return <ThemeCtx.Provider value={{ choice, resolved, setChoice }}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);
