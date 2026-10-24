// Light / dark / follow Windows. The choice is remembered per device.
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type ThemeChoice = "light" | "dark" | "system";
const KEY = "mytech.theme";

function systemDark() {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

function resolve(choice: ThemeChoice): "light" | "dark" {
  return choice === "dark" || (choice === "system" && systemDark()) ? "dark" : "light";
}

export function savedTheme(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" || v === "system" ? v : "system";
  } catch {
    return "system";
  }
}

type Ctx = { choice: ThemeChoice; setChoice: (c: ThemeChoice) => void; isDark: boolean; toggle: () => void };
const ThemeCtx = createContext<Ctx | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoice] = useState<ThemeChoice>(savedTheme);
  const [mode, setMode] = useState(() => resolve(savedTheme()));
  useEffect(() => {
    setMode(resolve(choice));
    try { localStorage.setItem(KEY, choice); } catch { /* storage blocked */ }
    if (choice !== "system" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => setMode(resolve("system"));
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [choice]);
  useEffect(() => { document.documentElement.dataset.theme = mode; }, [mode]);
  const isDark = mode === "dark";
  return (
    <ThemeCtx.Provider value={{ choice, setChoice, isDark, toggle: () => setChoice(isDark ? "light" : "dark") }}>
      {children}
    </ThemeCtx.Provider>
  );
}

export function useTheme(): Ctx {
  const c = useContext(ThemeCtx);
  if (!c) throw new Error("useTheme outside ThemeProvider");
  return c;
}
