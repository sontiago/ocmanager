import type { RouteObject } from "react-router";
import { AuditPage } from "../pages/Audit";
import { ProfilePage } from "../pages/Profile";
import { StatsPage } from "../pages/Stats";
import { SettingsPage } from "../pages/Settings";
import { ClientDetailPage } from "../pages/ClientDetail";
import { ClientsPage } from "../pages/Clients";
import { DevicesPage } from "../pages/Devices";
import { PaymentsPage } from "../pages/Payments";
import { PlansPage } from "../pages/Plans";
import { SubscriptionsPage } from "../pages/Subscriptions";
import { LoginPage } from "../pages/Login";
import { NodePage } from "../pages/Node";
import { OverviewPage } from "../pages/Overview";
import { AppShell } from "../ui/AppShell";
import { RequireAuth } from "./RequireAuth";

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
          { path: "/stats", element: <StatsPage /> },
          { path: "/subscriptions", element: <SubscriptionsPage /> },
          { path: "/plans", element: <PlansPage /> },
          { path: "/payments", element: <PaymentsPage /> },
          { path: "/devices", element: <DevicesPage /> },
          { path: "/node", element: <NodePage /> },
          { path: "/audit", element: <AuditPage /> },
          { path: "/settings", element: <SettingsPage /> },
          { path: "/profile", element: <ProfilePage /> },
        ],
      },
    ],
  },
];
