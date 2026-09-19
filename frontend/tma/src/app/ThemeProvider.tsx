import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

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

function prefersDark(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(readStored);
  const [systemDark, setSystemDark] = useState(prefersDark);

  // Тема клиента Telegram может смениться, пока приложение открыто, —
  // поэтому здесь подписка, а не однократное чтение.
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
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
