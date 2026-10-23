import { useSearchParams } from "react-router";
import { useT } from "../i18n";
import { PaymentsTab } from "./PaymentsTab";
import { WebhooksTab } from "./WebhooksTab";

export function PaymentsPage() {
  const { t } = useT();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "webhooks" ? "webhooks" : "payments";

  const tabButton = (id: "payments" | "webhooks", label: string) => (
    <button
      role="tab"
      aria-selected={tab === id}
      onClick={() => setParams(id === "payments" ? {} : { tab: id })}
      className={`border-b-2 px-3 py-1.5 ${tab === id ? "border-accent text-accent" : "border-transparent text-muted"}`}
    >
      {label}
    </button>
  );

  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold">{t("nav.payments")}</h1>
      <div role="tablist" className="flex gap-1 border-b border-border">
        {tabButton("payments", t("payments.tabPayments"))}
        {tabButton("webhooks", t("payments.tabWebhooks"))}
      </div>
      {tab === "payments" ? <PaymentsTab /> : <WebhooksTab />}
    </div>
  );
}
