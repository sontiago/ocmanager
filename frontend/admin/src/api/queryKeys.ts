type Filters = Record<string, string | number | boolean | undefined>;

/** Фабрики ключей TanStack Query: инвалидация по префиксу (`queryKeys.clients.all`). */
export const queryKeys = {
  overview: ["overview"] as const,
  clients: {
    all: ["clients"] as const,
    list: (f: Filters) => ["clients", "list", f] as const,
    detail: (id: number) => ["clients", "detail", id] as const,
  },
  subscriptions: {
    all: ["subscriptions"] as const,
    list: (f: Filters) => ["subscriptions", "list", f] as const,
  },
  plans: ["plans"] as const,
  payments: {
    all: ["payments"] as const,
    list: (f: Filters) => ["payments", "list", f] as const,
  },
  webhooks: {
    all: ["webhooks"] as const,
    list: (f: Filters) => ["webhooks", "list", f] as const,
    detail: (id: number) => ["webhooks", "detail", id] as const,
  },
  devices: {
    all: ["devices"] as const,
    list: (f: Filters) => ["devices", "list", f] as const,
    sessions: (id: number) => ["devices", "sessions", id] as const,
  },
  node: {
    all: ["node"] as const,
    status: ["node", "status"] as const,
    sessions: ["node", "sessions"] as const,
  },
  audit: (f: Filters) => ["audit", f] as const,
  stats: {
    all: ["stats"] as const,
    traffic: (days: number) => ["stats", "traffic", days] as const,
    revenue: (days: number) => ["stats", "revenue", days] as const,
    clients: (days: number) => ["stats", "clients", days] as const,
    economics: ["stats", "economics"] as const,
  },
  settings: ["settings"] as const,
  adminSessions: ["admin-sessions"] as const,
};
