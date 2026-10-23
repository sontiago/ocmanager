import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { createBrowserRouter, RouterProvider } from "react-router";
import { createClient } from "../api/client";
import { SessionProvider } from "../api/session";
import { I18nProvider } from "../i18n";
import { routes } from "./routes";

export function App() {
  const [queryClient] = useState(() => new QueryClient());
  const [client] = useState(() => createClient());
  const [router] = useState(() => createBrowserRouter(routes));
  return (
    <I18nProvider>
      <QueryClientProvider client={queryClient}>
        <SessionProvider client={client}>
          <RouterProvider router={router} />
        </SessionProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
}
