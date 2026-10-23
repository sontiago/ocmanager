import type { RouteObject } from "react-router";
import { ClientDetailPage } from "../pages/ClientDetail";
import { ClientsPage } from "../pages/Clients";
import { PlansPage } from "../pages/Plans";
import { SubscriptionsPage } from "../pages/Subscriptions";
import { LoginPage } from "../pages/Login";
import { OverviewPage } from "../pages/Overview";
import { AppShell } from "../ui/AppShell";
import { RequireAuth } from "./RequireAuth";

function Stub({ name }: { name: string }) {
  return <h1 className="text-lg font-semibold">{name}</h1>;
}

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: "/", element: <OverviewPage /> },
          { path: "/clients", element: <ClientsPage /> },
          { path: "/clients/:id", element: <ClientDetailPage /> },
          { path: "/subscriptions", element: <SubscriptionsPage /> },
          { path: "/plans", element: <PlansPage /> },
          { path: "/payments", element: <Stub name="Платежи" /> },
          { path: "/devices", element: <Stub name="Устройства" /> },
          { path: "/node", element: <Stub name="Нода" /> },
          { path: "/audit", element: <Stub name="Аудит" /> },
          { path: "/settings", element: <Stub name="Настройки" /> },
          { path: "/profile", element: <Stub name="Профиль" /> },
        ],
      },
    ],
  },
];
