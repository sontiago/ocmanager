import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { ApiProvider } from "../api/ApiProvider";
import type { ApiClient } from "../api/contract";
import { createMockClient } from "../api/mock/client";
import { I18nProvider } from "../i18n/I18nProvider";
import type { Lang } from "../telegram/auth";
import { ThemeProvider } from "../app/ThemeProvider";

export interface RenderOptions {
  client?: ApiClient;
  lang?: Lang;
  route?: string;
}

export function renderWithProviders(
  ui: ReactElement,
  { client = createMockClient(), lang = "ru", route = "/" }: RenderOptions = {},
): RenderResult {
  // retry:false и gcTime:0 — иначе тесты ждут бэкоффов и текут кэшем между собой.
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <ApiProvider client={client}>
          <ThemeProvider>
            <I18nProvider lang={lang}>
              <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
            </I18nProvider>
          </ThemeProvider>
        </ApiProvider>
      </QueryClientProvider>
    );
  }

  return render(ui, { wrapper: Wrapper });
}
