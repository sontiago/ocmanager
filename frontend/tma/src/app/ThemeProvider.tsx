import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { themeParams } from "@telegram-apps/sdk-react";

export type ThemeChoice = "system" | "light" | "dark";

const STORAGE_KEY = "ocm-theme";

interface ThemeContextValue {
  choice: ThemeChoice;
  setChoice: (next: ThemeChoice) => void;
  /** Что реально показано сейчас — после раскрытия «system». */
  resolved: "light" | "dark";
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStored(): ThemeChoice {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw === "light" || raw === "dark" ? raw : "system";
  } catch {
    return "system";
  }
}

function writeStored(choice: ThemeChoice) {
  try {
    localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    // Хранилище недоступно — выбор проживёт до закрытия приложения.
  }
}

function clientDark(): boolean {
  try {
    if (themeParams.isMounted()) return themeParams.isDark();
  } catch {
    // SDK не инициализирован — значит, мы точно не в Telegram.
  }
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(readStored);
  const [systemDark, setSystemDark] = useState(clientDark);

  useEffect(() => {
    const unsubs: Array<() => void> = [];

    // Тема клиента Telegram может смениться, пока приложение открыто.
    try {
      unsubs.push(themeParams.isDark.sub(() => setSystemDark(clientDark())));
    } catch {
      // не в Telegram
    }

    if (typeof window.matchMedia === "function") {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      const onChange = () => setSystemDark(clientDark());
      mq.addEventListener("change", onChange);
      unsubs.push(() => mq.removeEventListener("change", onChange));
    }

    return () => unsubs.forEach((off) => off());
  }, []);

  const resolved: "light" | "dark" =
    choice === "system" ? (systemDark ? "dark" : "light") : choice;

  // Единственное место во всём приложении, где меняется тема:
  // атрибут на <html>, за который зацеплен :root[data-theme="dark"].
  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);

  const setChoice = (next: ThemeChoice) => {
    setChoiceState(next);
    writeStored(next);
  };

  return (
    <ThemeContext.Provider value={{ choice, setChoice, resolved }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme вне ThemeProvider");
  return ctx;
}
