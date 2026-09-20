import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter } from "react-router";
import { ApiProvider } from "../api/ApiProvider";
import type { ApiClient } from "../api/contract";
import { createQueryClient } from "../api/queryClient";
import { I18nProvider } from "../i18n/I18nProvider";
import { AppRoutes } from "./router";
import { ThemeProvider } from "./ThemeProvider";

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
            </BrowserRouter>
          </I18nProvider>
        </ThemeProvider>
      </ApiProvider>
    </QueryClientProvider>
  );
}
