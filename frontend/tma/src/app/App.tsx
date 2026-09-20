import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router";
import { ApiProvider } from "../api/ApiProvider";
import type { ApiClient } from "../api/contract";
import { createQueryClient } from "../api/queryClient";
import { I18nProvider } from "../i18n/I18nProvider";
import { AppRoutes } from "./router";
import { ThemeProvider } from "./ThemeProvider";
import { lazy, Suspense, useState } from "react";
/**
 * Панель существует только в dev-сборке. Условие написано прямо на
 * import.meta.env: Vite подставляет сюда литералы при сборке, тернарник
 * сворачивается в null, и динамический импорт исчезает вместе с чанком.
 * Через env.devPanel из env.ts это не работает — там значение вычисляется
 * в рантайме, и сборщик обязан оставить модуль на случай, если флаг
 * окажется истинным.
 */
const DevPanel =
  import.meta.env.DEV && import.meta.env.VITE_DEV_PANEL === "true"
    ? lazy(() => import("./DevPanel").then((m) => ({ default: m.DevPanel })))
    : null;

export function App({ client }: { client: ApiClient }) {
  // useState, а не модульная константа: QueryClient должен пережить
  // StrictMode-двойной рендер, но не переживать перемонтирование App.
  const [queryClient] = useState(createQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      <ApiProvider client={client}>
        <ThemeProvider>
          <I18nProvider>
            <BrowserRouter>
              <AppRoutes />
              {DevPanel && (
                <Suspense fallback={null}>
                  <DevPanel />
                </Suspense>
              )}
            </BrowserRouter>
          </I18nProvider>
        </ThemeProvider>
      </ApiProvider>
    </QueryClientProvider>
  );
}
