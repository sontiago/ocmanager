export const queryKeys = {
  me: ["me"] as const,
  plans: ["plans"] as const,
  subscription: ["subscription"] as const,
  devices: ["devices"] as const,
  connection: ["connection"] as const,
  checkout: (planCode: string) => ["checkout", planCode] as const,
};
